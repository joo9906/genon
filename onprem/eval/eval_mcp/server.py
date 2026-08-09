"""genon 평가지표 MCP 서버 — `@mcp.tool` 어댑터 층.

여기에는 계산 로직을 두지 않는다. 각 도구는 metrics 모듈 함수를 그대로 호출하고
결과 dict 를 돌려주는 얇은 껍데기다 (테스트·재사용이 MCP 런타임과 무관하게 되도록).

도구 이름은 README 지표 이름과 1:1 로 맞췄다 — catalog.py 참고.
결정적 도구(Text/Numeric/Structure)는 상시 호출용, `llm_judge_gate` 는
게이트 판정용이며 판정 모델 자체는 호출하지 않는다.

실행:
    python -m eval_mcp.server          # stdio 전송
"""

import os

try:  # 공식 python-sdk
    from mcp.server.fastmcp import FastMCP
except ImportError:  # fastmcp 단독 배포판
    from fastmcp import FastMCP

from . import numeric_metrics, scenario_metrics, structure_metrics, suites, text_metrics, tone_metrics
from .catalog import CATALOG, NOT_IMPLEMENTED
from .gating import DEFAULT_SAMPLE_RATE, DEFAULT_SIMILARITY_THRESHOLD, gate_llm_judge
from .logging_utils import configure_stderr_logging, log_info

mcp = FastMCP("genon-eval")


# ─────────────────────────────────────────────────────────────
# 카탈로그 · 기능별 묶음
# ─────────────────────────────────────────────────────────────
@mcp.tool()
def metric_catalog(scope: str | None = None) -> dict:
    """지표 카탈로그. 각 도구의 태그(Text/Numeric/Structure/LLM Judge), 대상 기능,
    참조 데이터 필요 여부, 게이트드 여부와 **미구현 지표 및 그 이유**를 함께 돌려준다.

    Args:
        scope: 부분 문자열로 대상 기능을 걸러낸다 ("006", "번역", "글다듬이", "FAQ", "공통").
    """
    metrics = [row for row in CATALOG if not scope or scope in row["scope"]]
    return {
        "principle": (
            "결정적(Text/Numeric/Structure) 도구가 1차 방어선이자 운영 지표다. "
            "LLM Judge 는 스크리닝 미통과분만 샘플링·opt-in 으로 호출한다."
        ),
        "metrics": metrics,
        "features": list(suites.SUITES),
        "not_implemented": NOT_IMPLEMENTED,
    }


@mcp.tool()
def feature_suites(feature: str | None = None) -> dict:
    """기능별 지표 묶음 정의 — 네 기능은 서로 다른 지표·기준으로 평가한다.

    각 기능의 지표 목록, 필요한 입력 키, 운영 합불 기준(targets), 역할
    (operational / advisory / screening)을 돌려준다. run_feature_eval 을 호출하기 전에
    무엇을 넣어야 하는지 확인하는 용도.

    Args:
        feature: template_fill | text_polish | translation | faq (생략 시 전체)
    """
    return suites.list_suites(feature)


@mcp.tool()
def run_feature_eval(
    feature: str,
    payload: dict,
    judge_opt_in: bool = False,
    judge_enabled: bool = False,
    sample_rate: float = DEFAULT_SAMPLE_RATE,
) -> dict:
    """기능 하나의 지표 묶음을 한 번에 실행하고 합불·미측정 항목을 함께 낸다.

    입력이 없는 지표는 실행하지 않고 `skipped_metrics` 에 이유가 남는다
    ("측정 안 함"과 "통과"를 섞지 않는다). 결정적 지표를 통과 못한 항목만
    `llm_judge_gate` 후보로 올라가며, 게이트는 opt-in + 서빙 확인 시에만 열린다.

    payload 키 (기능별 — feature_suites 로 확인):
      template_fill: extraction_samples, hwpx_before, hwpx_after, written_values, scenarios
      text_polish:   pairs[{id, original, result, tone, doc_type}]
      translation:   records[{id, segments_in, segments_out, fallback}],
                     pairs[{id, source, target, reference?, glossary?}], glossary
      faq:           items[{id, answer, sources[]}], ngram
      공통 선택 키:   thresholds{"지표경로": 기준값}, entities[]
    """
    return suites.run_suite(
        feature,
        payload,
        judge_opt_in=judge_opt_in,
        judge_enabled=judge_enabled,
        sample_rate=sample_rate,
    )


# ─────────────────────────────────────────────────────────────
# 공통 프리미티브
# ─────────────────────────────────────────────────────────────
@mcp.tool()
def text_match(
    text: str,
    expected: str,
    mode: str = "exact",
    drop_punct: bool = False,
    lower: bool = False,
) -> dict:
    """`Text` — 정규화(NFKC·공백 축약) 후 exact / contains / regex 매칭.

    Args:
        mode: exact | contains | regex
        drop_punct: 구두점을 제거하고 비교 (표기 편차 흡수)
        lower: 라틴 문자 소문자화
    """
    return text_metrics.match_text(text, expected, mode=mode, drop_punct=drop_punct, lower=lower)


@mcp.tool()
def numeric_threshold(
    value: float | str,
    operator: str,
    threshold: float | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> dict:
    """`Numeric` — 수치 임계 비교. operator: lt | gt | eq | between.

    value 가 문자열이면 첫 수치를 추출해 비교한다. between 은 minimum·maximum 필수.
    """
    return numeric_metrics.compare_threshold(
        value, operator, threshold=threshold, minimum=minimum, maximum=maximum
    )


@mcp.tool()
def structure_fingerprint(original: str, result: str) -> dict:
    """`Structure` — 마크다운/HTML 구조 지문(표 행·셀, 제목, 코드펜스) 대조.

    첨부용 마크다운 표와 지능형 한 줄 HTML 표를 모두 점검한다.
    """
    return structure_metrics.fingerprint_diff(original, result)


# ─────────────────────────────────────────────────────────────
# 006 — HWPX 템플릿 채우기
# ─────────────────────────────────────────────────────────────
@mcp.tool()
def field_extraction_score(samples: list) -> dict:
    """`Text` — 006 필드 추출 정확도 (파이프라인의 유일한 비결정 구간을 결정적으로 채점).

    필드별/전체 precision·recall·F1, 값 exact·부분 일치율, 화이트리스트 밖
    필드명 생성(환각)률을 낸다.

    Args:
        samples: [{"predicted": {필드:값}, "gold": {필드:값},
                   "allowed_names": [템플릿 필드명…] (선택 — 환각률 계산에 필요)}]
    """
    return text_metrics.aggregate_extraction(samples)


@mcp.tool()
def hwpx_fill_roundtrip(before_path: str, after_path: str, written_values: dict | None = None) -> dict:
    """`Structure` — 006 라운드트립: 채움 → 재스캔 시 채워짐/부족 판정 일치율.

    계약상 `agreement_rate` 는 1.0 이어야 한다. 값을 주지 않은 필드가 안내문
    상태로 남았는지(부분 초안 계약)와 기록값↔재스캔값 불일치도 함께 낸다.

    Args:
        before_path: 채우기 전 hwpx 경로
        after_path: 채우기 후 hwpx 경로
        written_values: 이번에 기록한 {필드명: 값} (기대 판정의 근거)
    """
    return structure_metrics.hwpx_roundtrip(before_path, after_path, written_values)


@mcp.tool()
def hwpx_document_integrity(before_path: str, after_path: str) -> dict:
    """`Structure` — 006 문서 무결성: 필드 값 제외 영역의 텍스트 동일성 + 개체 수 일치.

    누름틀 치환은 필드 run 텍스트만 바꾸므로 필드 밖 텍스트·XML 태그 수·ZIP
    엔트리 목록이 모두 같아야 한다. 하나라도 다르면 필러가 문서를 건드린 것이다.
    """
    return structure_metrics.hwpx_integrity(before_path, after_path)


@mcp.tool()
def hwpx_text_crosscheck(before_path: str, after_path: str) -> dict:
    """`Structure` — 006 문서 무결성 교차검증: 독립 파서(python-hwpx)로 문단 보존 재측정.

    `hwpx_document_integrity` 와 같은 것을 다른 파서로 잰다. 두 결과가 어긋나면 둘 중
    하나가 문서를 잘못 읽고 있다는 신호다 — 한 벌만 있으면 알 수 없다.
    python-hwpx 가 없으면 `available=False` 로 **미측정**을 돌려준다 (통과 아님).
    """
    return structure_metrics.hwpx_text_crosscheck(before_path, after_path)


@mcp.tool()
def multiturn_scenario_score(scenarios: list) -> dict:
    """`Numeric`+`Structure` — 006 E2E 멀티턴: 완성 성공률, 완성 턴 수, 세션 누적 정확성.

    Args:
        scenarios: [{"id":…, "required_fields":[…],
                     "turns":[{"extracted":{…}, "session_after":{…}}, …]}]
    """
    return scenario_metrics.aggregate_scenarios(scenarios)


# ─────────────────────────────────────────────────────────────
# 018 — 글다듬이 / 번역 / FAQ
# ─────────────────────────────────────────────────────────────
@mcp.tool()
def polish_structure_pass_rate(pairs: list) -> dict:
    """`Structure` — 018 글다듬이 지문 대조 통과율 + 훼손 유형별 건수.

    Args:
        pairs: [{"id":… (선택), "original": 원문, "result": 다듬은 결과}]
    """
    return structure_metrics.structure_pass_rate(pairs)


@mcp.tool()
def translation_structure_health(records: list) -> dict:
    """`Structure` — 018 번역 구조 건전성: fallback 발생률·세그먼트 수 불일치율(0 수렴 목표).

    Args:
        records: [{"id":…, "segments_in": n, "segments_out": m, "fallback": bool}]
    """
    return structure_metrics.translation_fallback_rate(records)


@mcp.tool()
def tone_rule_check(text: str, tone: str, doc_type: str | None = None) -> dict:
    """`Text` — 018 톤 적합성 규칙 검사 (LLM 미사용).

    종결 형태 일치율, 톤별 금지 표현(반말·명령형·구어체·과장 수식어), 조사
    오류를 낸다. doc_type 이 톤 고정군이면 정책 톤으로 채점하고 그 사실을 알린다.

    Args:
        tone: polite | friendly | report
        doc_type: email | post | press_release | official_doc | debt_reason |
                  reviewer_opinion | asset_opinion | customer_notice
    """
    return tone_metrics.tone_rule_check(text, tone, doc_type)


@mcp.tool()
def tone_pass_rate(items: list) -> dict:
    """`Text` — 018 톤 합불 집계. items: [{"id":…, "text":…, "tone":…, "doc_type":… }]"""
    return tone_metrics.tone_pass_rate(items)


@mcp.tool()
def ending_consistency(text: str) -> dict:
    """`Text` — 018 어미 일관성: 문서 초반·후반의 우세 종결 유형이 같은지."""
    return structure_metrics.ending_consistency(text)


@mcp.tool()
def sentence_length_stats(text: str) -> dict:
    """`Numeric`(참고용) — 문장 길이 분포. 문서별 편차가 커서 합불 기준으로 쓰지 않는다."""
    return numeric_metrics.sentence_length_stats(text)


@mcp.tool()
def fact_preservation_check(source: str, result: str, entities: list | None = None) -> dict:
    """`Text`/`Numeric` — 018 의미·사실 보존 1차 방어선.

    숫자·날짜·단위·고유명사를 원문과 결과에서 뽑아 교차 대조하고, 사라진 값
    (dropped)과 새로 생긴 값(added, 환각 후보)을 따로 낸다.

    Args:
        entities: 한국어 고유명사 목록 (NER 모델을 쓰지 않으므로 호출부가 준 것만 센다)
    """
    return numeric_metrics.cross_check_facts(source, result, entities=entities)


@mcp.tool()
def chrf_score(candidate: str, reference: str, max_n: int = 6, beta: float = 2.0) -> dict:
    """`Numeric` — 참조 번역이 있는 테스트셋의 chrF (한국어에서 BLEU 보다 안정적).

    BERTScore 는 미포함 — 모델 서빙 가용성 확인 후 별도 도구로 붙인다.
    """
    return numeric_metrics.chrf(candidate, reference, max_n=max_n, beta=beta)


@mcp.tool()
def glossary_compliance(source: str, target: str, glossary: dict) -> dict:
    """`Text` — 018 용어집 준수율.

    분모는 "원문에 실제로 등장한 용어 수"다. 등장하지 않은 용어는 점수에 섞지 않는다.

    Args:
        glossary: {"원문 용어": "지정 번역어"} 또는 {"원문 용어": ["허용어1","허용어2"]}
    """
    return text_metrics.glossary_compliance(source, target, glossary)


@mcp.tool()
def grounding_overlap(answer: str, sources: list, ngram: int = 3) -> dict:
    """`Text` — 018 FAQ 근거성 1차 스크리닝: 답변 문장별 원천 n-gram 중복·자카드.

    점수가 낮다고 곧 오답은 아니다(재서술 가능) — 판정은 llm_judge_gate 로 넘긴다.
    """
    return text_metrics.grounding_overlap(answer, sources, ngram=ngram)


# ─────────────────────────────────────────────────────────────
# LLM Judge 게이트
# ─────────────────────────────────────────────────────────────
@mcp.tool()
def llm_judge_gate(
    items: list,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    sample_rate: float = DEFAULT_SAMPLE_RATE,
    opt_in: bool = False,
    judge_enabled: bool = False,
) -> dict:
    """`LLM Judge`(게이트드) — 생성형 판정을 붙일 대상만 고른다. 판정 모델은 호출하지 않는다.

    결정적 지표 통과분과 임베딩 유사도 임계 이상 건은 후보에서 빠지고, 남은
    후보 중 id 해시 기반 표본만 대상이 된다(재현 가능). opt_in 과 judge_enabled
    (온프레미스 서빙 가용성 확인)가 모두 참이어야 게이트가 열린다.

    Args:
        items: [{"id":…, "deterministic_passed": bool, "similarity": float|null}]
               similarity 가 null 이면 임베딩 스크리닝 미실시로 보고한다.
    """
    return gate_llm_judge(
        items,
        similarity_threshold=similarity_threshold,
        sample_rate=sample_rate,
        opt_in=opt_in,
        judge_enabled=judge_enabled,
    )


def main() -> None:
    # stdio 전송에서 stdout 은 JSON-RPC 프레임 전용이다 — 로그는 stderr 로만 나간다.
    configure_stderr_logging(os.getenv("LOG_LEVEL", "INFO"))
    log_info("평가지표 MCP 서버 시작", event="server_start", status="stdio")
    mcp.run()


if __name__ == "__main__":
    main()
