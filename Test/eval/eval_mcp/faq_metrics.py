"""FAQ 생성 단계의 **결정적** 산출 지표 — 근거성 논쟁과 무관한 것만 잰다.

## 왜 생겼나 — FAQ 의 운영 기준이 PII 하나였다

`suites.py` 의 `faq` 묶음은 근거성(`grounding_overlap`)을 **스크리닝**으로만 쓴다.
어휘 중복이 낮다고 곧 오답이 아니기 때문이고(재서술), 그 판단은 그대로 유효하다.
문제는 그 결과로 **FAQ 의 합불 기준이 `pii_leak_count` 하나**가 됐다는 것이다 —
30개를 요청했는데 2개가 나와도, 기각의 대부분이 스키마 위반이어도 `verdict` 는
`pass` 다. 품질이 무너져도 리포트가 초록불이면 가드레일이 아니다.

그런데 서빙은 이미 답을 들고 있다. `FaqResult.as_payload()` 가 내는
`count`·`requested_count`·`rejected{schema,ungrounded,duplicate}`·`coverage_capped`·
`source_truncated` 는 **전부 결정적 사실**이고 재서술 논쟁과 아무 관계가 없다.
계산해 놓은 값을 아무도 채점하지 않고 있었다.

## 무엇을 걸고 무엇을 보고만 하나

| 값 | 기준을 거나 | 왜 |
|---|---|---|
| `yield_rate` (산출/요청) | **건다** | "고른 숫자가 곧 받는 개수" 가 요구다 (2026-09-03). 못 채운 것은 실패다 |
| `rejection_rates.schema` | **건다** | 스키마는 **우리가 프롬프트로 못박은 계약**이라 문서 성격과 무관하다 |
| `rejection_rates.ungrounded` / `.duplicate` | 보고만 | 원천 문서의 성격에 달렸다 — 기준을 걸면 문서 탓으로 상시 빨간불이 된다 |
| `coverage.capped` / `.source_truncated` | 보고만 | **비용 손잡이**(`FAQ_MAX_CHUNK_CALLS`)가 정하는 값이다. 배포 설정을 품질 불합격으로 세면 사람이 지표를 끈다 |

`ungrounded` 를 안 거는 것은 `targets` 를 비워 둔 원래 판단과 같은 근거다 —
**여기서 바뀌는 것은 "근거성을 채점한다" 가 아니라 "산출량과 형식 준수를 채점한다" 다.**

## 재지 않은 것을 0 으로 만들지 않는다

후보가 0건이면(`produced + rejected == 0`) 기각률은 **정의되지 않는다.** 0.0 을
돌려주면 "아무것도 안 나온 실행" 이 스키마 기준을 **만점으로 통과**한다 — 이 패키지가
막으려는 바로 그 형태다. `None` 을 내서 `not_measured` 로 남긴다.

반대로 **산출 개수가 없는 것은 미측정이 아니라 0건**이다(불합격). 다듬기·번역이
빈 결과를 냈을 때와 같은 규약이다 (`pairs.py`).

## 임계값은 실측 전 잠정값이다

`yield_rate > 0.8` 과 `schema < 0.1` 은 **LLM 실호출 없이 정한 값**이다
(HANDOFF §A-2 의 조각 예산과 같은 성격). 실물에서 처음 재는 순간 조정 대상이고,
그때까지는 `payload.thresholds` 로 덮는다.
"""

from .error_codes import fail

ERR_NOT_A_MAPPING = "FAQ 생성 통계는 객체여야 합니다."
ERR_REQUESTED_MISSING = (
    "FAQ 생성 통계에 요청 개수(requested_count)가 없습니다. "
    "요청 개수 없이는 산출률이 정의되지 않습니다."
)

_REJECT_REASONS = ("schema", "ungrounded", "duplicate")


def _count(value):
    """정수 개수로 읽는다. 계약에 안 맞으면 `None` — 호출부가 `fail()` 로 로그를 남긴다.

    여기서 바로 `EvalInputError` 를 던지지 않는 것은 이 패키지의 규약 때문이다
    (`error_codes` 머리말) — 로그 없이 예외만 던지면 폐쇄망에서 근거가 안 남는다.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = int(value)
    return None if number < 0 else number


def generation_health(generation: dict) -> dict:
    """FAQ 한 번의 생성 결과를 산출률·기각 구성·커버리지로 요약한다.

    Args:
        generation: 서빙 `FaqResult.as_payload()` 의 부분집합.
            `requested_count`(필수) · `count` · `rejected{schema,ungrounded,duplicate}` ·
            `coverage_capped` · `source_truncated` · `chunks_planned` · `chunks_used`.

    Returns:
        `yield_rate` 는 클램프하지 않는다 — 1 을 넘으면 **고른 숫자보다 많이 온 것**이고
        그것도 계약 위반이라 `overproduced` 로 함께 드러낸다.
    """
    if not isinstance(generation, dict):
        fail(ERR_NOT_A_MAPPING, event="faq_generation_not_a_mapping")
    if generation.get("requested_count") is None:
        fail(ERR_REQUESTED_MISSING, event="faq_requested_count_missing")

    rejected_raw = generation.get("rejected") or {}
    if not isinstance(rejected_raw, dict):
        fail(ERR_NOT_A_MAPPING, event="faq_generation_bad_counts")
    counts = {
        "requested": _count(generation.get("requested_count")),
        "produced": _count(generation.get("count", 0)),
        **{reason: _count(rejected_raw.get(reason, 0)) for reason in _REJECT_REASONS},
    }
    if any(value is None for value in counts.values()):
        fail(ERR_NOT_A_MAPPING, event="faq_generation_bad_counts")
    requested, produced = counts["requested"], counts["produced"]
    rejected = {reason: counts[reason] for reason in _REJECT_REASONS}
    if requested <= 0:
        fail(ERR_REQUESTED_MISSING, event="faq_requested_count_zero")

    rejected_total = sum(rejected.values())
    candidates = produced + rejected_total
    # 후보가 0건이면 기각률은 정의되지 않는다 — 0.0 이 아니라 미측정이다.
    rates = (
        {reason: round(rejected[reason] / candidates, 4) for reason in _REJECT_REASONS}
        if candidates
        else {reason: None for reason in _REJECT_REASONS}
    )
    return {
        "requested": requested,
        "produced": produced,
        "yield_rate": round(produced / requested, 4),
        "overproduced": produced > requested,
        "candidates": candidates,
        "rejected": rejected,
        "rejected_total": rejected_total,
        "rejection_rates": rates,
        # 아래는 **보고만** 한다 (기준을 걸지 않는 이유는 이 파일 머리말의 표).
        "coverage": {
            "capped": bool(generation.get("coverage_capped")),
            "source_truncated": bool(generation.get("source_truncated")),
            "chunks_planned": generation.get("chunks_planned"),
            "chunks_used": generation.get("chunks_used"),
        },
    }
