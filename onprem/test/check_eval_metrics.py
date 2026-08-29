"""평가지표(eval) 회귀 점검 — **가드레일 자체를 검증한다.**

`python onprem/test/check_eval_metrics.py`

## 왜 필요한가 — 지금까지 eval 에는 회귀 점검이 0건이었다

`onprem/eval/README.md` 는 "도구 전수 스모크는 합성 hwpx 픽스처로 확인했다(세션 임시
디렉토리, 저장소에 남지 않음)" 라고 적어 뒀다. 즉 **네 기능의 합불을 정하는 코드가
자동 점검 없이** 있었다. eval 은 실제 검증·평가에 쓰이는 가드레일이므로, 여기가 조용히
틀리면 **틀린 기준으로 합격 도장을 찍는다** — 기능 코드가 틀리는 것보다 나쁘다.

## 무엇을 보는가 — 순서가 곧 우선순위다

1. **미측정을 통과로 세지 않는가.** eval 의 제1 규약이고, 어기면 리포트가 거짓말을 한다.
   실제로 어기고 있었다 (2026-08-30 수정): 화이트리스트를 안 준 환각률이 `0.0` 으로
   나가 `< 0.05` 기준을 늘 통과했다.
2. **아무것도 재지 않고 통과하지 않는가.** 입력 키를 잘못 주면 빈 문자열끼리 비교해
   `pass_rate 1.0` 이 나오던 자리(2026-08-30 수정).
3. **판정이 실제로 갈리는가.** 통과·불합격 짝을 같이 태운다. 한쪽만 보면 "언제나
   통과하는 지표" 를 통과로 읽는다.
4. **기준 경로가 산출물에 실제로 있는가.** `SUITES[…]["targets"]` 의 경로가 지표
   결과에서 도달하지 못하면 그 기준은 **영원히 `not_measured`** 가 된다 — 지표 키를
   한 번 바꾸면 조용히 그렇게 된다. 완전한 입력을 주고 **모든 기준이 측정되는지** 본다.
5. **게이트 규율.** 전건 호출 금지·opt-in·표본 재현성.
6. **도구 표면 정합성.** `server.py` 의 `@mcp.tool()` 목록 ↔ `catalog.py` (표에 없는
   도구는 운영 지표가 아니라는 규약).

hwpx 지표는 **합성 hwpx 픽스처**를 그때그때 만들어 태운다(임시 디렉토리, 남기지 않는다).
읽기만 하고 아무것도 고치지 않는다. 어긋나면 종료 코드 1.
"""

import ast
import os
import shutil
import sys
import tempfile
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ONPREM = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ONPREM, "eval"))

from eval_mcp import (  # noqa: E402
    catalog,
    gating,
    numeric_metrics,
    scenario_metrics,
    structure_metrics,
    suites,
    text_metrics,
    tone_metrics,
)
from eval_mcp.error_codes import EvalInputError  # noqa: E402

_SERVER_PY = os.path.join(_ONPREM, "eval", "eval_mcp", "server.py")


class Report:
    def __init__(self) -> None:
        self.failures: list = []
        self.checks = 0

    def expect(self, condition: bool, label: str, detail: str = "") -> None:
        self.checks += 1
        if condition:
            print(f"[OK  ] {label}")
            return
        self.failures.append(label)
        print(f"[FAIL] {label}")
        if detail:
            for line in detail.splitlines():
                print(f"        {line}")

    def raises(self, func, label: str) -> None:
        """계약 위반이 **조용히 통과하지 않는지** — 예외를 던져야 한다."""
        self.checks += 1
        try:
            result = func()
        except EvalInputError:
            print(f"[OK  ] {label}")
            return
        self.failures.append(label)
        print(f"[FAIL] {label}")
        print(f"        예외 없이 통과했다: {str(result)[:120]}")


# ─────────────────────────────────────────────────────────────
# 합성 hwpx 픽스처 — 슬롯 2개(표 안 1개) + 누름틀 1개
# ─────────────────────────────────────────────────────────────
_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def _para(text: str) -> str:
    return f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"


def _field_para(name: str, guide: str, shown: str) -> str:
    """누름틀 문단. `Command` 블롭을 **먼저** 두어 실물 모양을 흉내낸다.

    안내문을 '첫 stringParam' 으로 잡으면 이 블롭이 안내문이 되어 빈 필드가 늘
    '입력됨' 으로 판정된다 — 운영과 eval 이 **같은 실수를 했던** 자리다.
    """
    return (
        "<hp:p><hp:run>"
        f'<hp:ctrl><hp:fieldBegin type="CLICK_HERE" name="{name}"><hp:parameterset>'
        '<hp:stringParam name="Command">Clickhere:set:51:0</hp:stringParam>'
        f'<hp:stringParam name="Direction">{guide}</hp:stringParam>'
        "</hp:parameterset></hp:fieldBegin></hp:ctrl>"
        f"<hp:t>{shown}</hp:t>"
        "<hp:ctrl><hp:fieldEnd/></hp:ctrl>"
        "</hp:run></hp:p>"
    )


def _table(cell_text: str) -> str:
    return (
        "<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList>"
        f"{_para(cell_text)}"
        "</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>"
    )


def _section(title_line: str, cell_line: str, dept_shown: str, tail: str = "붙임: 없음") -> bytes:
    body = "".join(
        [
            _para(title_line),
            _field_para("부서", "부서를 입력하세요", dept_shown),
            _table(cell_line),
            _para(tail),
        ]
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hp="{_HP}" xmlns:hs="urn:sec">{body}</hs:sec>'.encode()


def _write_hwpx(path: str, section: bytes) -> str:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", section)
    return path


def _fixtures(tmp: str) -> dict:
    """(템플릿, 정상 채움, 골격 훼손) 세 벌."""
    before = _write_hwpx(
        os.path.join(tmp, "before.hwpx"),
        _section("제 목 : {'제목', 16pt}", "작성자 : {'작성자'}", "부서를 입력하세요"),
    )
    after = _write_hwpx(
        os.path.join(tmp, "after.hwpx"),
        _section("제 목 : 2026년 사업계획", "작성자 : 홍길동", "영업본부"),
    )
    # 골격(중괄호 밖 텍스트)을 건드린 문서 — 채우기가 문서를 훼손한 경우다.
    broken = _write_hwpx(
        os.path.join(tmp, "broken.hwpx"),
        _section("제목 >> 2026년 사업계획", "작성자 : 홍길동", "영업본부", tail="붙임: 삭제됨"),
    )
    return {"before": before, "after": after, "broken": broken}


# ─────────────────────────────────────────────────────────────
# 1. 미측정을 통과로 세지 않는가 (eval 제1 규약)
# ─────────────────────────────────────────────────────────────
def _check_not_measured(rep: Report) -> None:
    print("\n── 1. 미측정을 통과로 세지 않는가 ─────────────────────────")

    # 환각률 — 화이트리스트(템플릿 스키마)를 안 주면 셀 대상이 없다.
    # 2026-08-30 이전에는 `rate: 0.0` 을 내어 `< 0.05` 기준을 **늘 통과**했다.
    scored = text_metrics.aggregate_extraction([{"predicted": {"제목": "가"}, "gold": {"제목": "가"}}])
    rep.expect(
        scored["hallucination"]["rate"] is None and scored["hallucination"]["measurable"] is False,
        "환각률: 화이트리스트가 없으면 값을 내지 않는다",
        f"hallucination={scored['hallucination']}",
    )
    with_list = text_metrics.aggregate_extraction(
        [{"predicted": {"제목": "가", "지어낸필드": "나"}, "gold": {"제목": "가"}, "allowed_names": ["제목"]}]
    )
    rep.expect(
        with_list["hallucination"]["rate"] == 0.5,
        "환각률: 화이트리스트를 주면 실제로 센다",
        f"rate={with_list['hallucination']['rate']}",
    )

    # 용어집 — 원문에 용어가 없으면 준수율은 정의되지 않는다 (0점이 아니다).
    empty = text_metrics.glossary_compliance("아무 내용", "nothing", {"예산": "budget"})
    rep.expect(
        empty["compliance_rate"] is None and empty["measurable"] is False,
        "용어집: 원문에 용어가 없으면 준수율이 None 이다",
        f"{empty}",
    )

    # 톤 — 채점 규칙이 없는 톤(관리자가 추가한 톤)은 분모에서 빠진다.
    tone = tone_metrics.tone_pass_rate(
        [{"id": "a", "text": "연차는 15일입니다.", "tone": "관리자가_추가한_톤"}]
    )
    rep.expect(
        tone["scored"] == 0 and tone["pass_rate"] is None and len(tone["skipped"]) == 1,
        "톤: 규칙 없는 톤은 통과로도 불합격으로도 세지 않는다",
        f"{tone}",
    )

    # 어미 일관성 — 앞뒤 절반을 비교하는 지표라 문장이 몇 개는 있어야 성립한다.
    short = structure_metrics.ending_consistency("연차 휴가는 15일입니다.")
    rep.expect(
        short["measurable"] is False and short["consistent"] is None,
        "어미 일관성: 한 문장짜리 문서는 미측정이다 (불합격 아님)",
        f"{short}",
    )
    listed = structure_metrics.ending_consistency("가. 연차 15일임")
    rep.expect(
        listed["measurable"] is False,
        "어미 일관성: 목록 표기(`가.`)만 있는 문서를 불일치로 잡지 않는다",
        f"{listed}",
    )

    # 참조가 없으면 측정하지 않는다 (조용히 0점을 주지 않는다).
    rep.raises(lambda: numeric_metrics.chrf("번역문", ""), "chrF: 참조가 없으면 예외")
    rep.raises(
        lambda: text_metrics.grounding_overlap("답변입니다.", []),
        "근거성: 원천이 없으면 예외",
    )

    # verdict 4갈래 — 미측정이 pass 로 읽히지 않는다.
    partial = suites.run_suite(
        "translation", {"records": [{"id": "r", "segments_in": 2, "segments_out": 2, "fallback": False}]}
    )
    rep.expect(
        partial["verdict"] == "pass_but_incomplete" and partial["passed"] is False,
        "verdict: 일부만 잰 묶음은 pass 가 아니다",
        f"verdict={partial['verdict']} passed={partial['passed']}",
    )
    nothing = suites.run_suite("translation", {})
    rep.expect(
        nothing["verdict"] == "not_measured" and nothing["passed"] is False,
        "verdict: 아무것도 못 잰 묶음은 not_measured 다",
        f"verdict={nothing['verdict']}",
    )
    faq = suites.run_suite("faq", {"items": [{"id": "1", "answer": "연차는 15일입니다.", "sources": ["연차는 15일입니다."]}]})
    rep.expect(
        faq["verdict"] == "no_operational_target",
        "verdict: 합불 기준이 없는 FAQ 는 그 사실을 말한다",
        f"verdict={faq['verdict']}",
    )


# ─────────────────────────────────────────────────────────────
# 2. 아무것도 재지 않고 통과하지 않는가 (입력 계약)
# ─────────────────────────────────────────────────────────────
def _check_input_contract(rep: Report) -> None:
    print("\n── 2. 입력 계약 — 빈 비교로 만점을 주지 않는가 ─────────────")

    damaged = "표를 다 날려먹은 결과입니다. 정말 그렇습니다. 확실합니다. 맞습니다."
    table = "# 제목\n\n| a | b |\n|---|---|\n| 1 | 2 |"

    # 같은 훼손을 **두 별칭 모두**에서 잡아야 한다. 2026-08-30 이전에는
    # `source`/`target` 으로 주면 빈 문자열끼리 비교해 pass_rate 1.0 이 나왔다.
    for source_key, result_key in (("original", "result"), ("source", "target")):
        pairs = [{"id": "1", source_key: table, result_key: damaged, "tone": "polite"}]
        scored = structure_metrics.structure_pass_rate(pairs)
        rep.expect(
            scored["pass_rate"] == 0.0,
            f"구조 지문: `{source_key}/{result_key}` 별칭으로도 훼손을 잡는다",
            f"pass_rate={scored['pass_rate']} issues={scored['issue_counts']}",
        )

    rep.raises(
        lambda: structure_metrics.structure_pass_rate([{"id": "1", "result": "결과만 있다"}]),
        "원문이 없는 항목은 예외 (빈 비교로 만점을 주지 않는다)",
    )
    rep.raises(
        lambda: suites.run_suite("translation", {"pairs": [{"id": "1", "target": "번역문만"}]}),
        "묶음 실행에서도 원문 없는 항목은 예외",
    )

    # 결과물이 비어 있는 것은 **미측정이 아니라 불합격**이다.
    empty_result = suites.run_suite(
        "text_polish",
        {"pairs": [{"id": "1", "original": "연차는 15일입니다. 신청은 결재로 합니다.", "result": "", "tone": "polite"}]},
    )
    tone_rate = suites._dig(empty_result["metrics"], "tone_pass_rate.pass_rate")
    rep.expect(
        tone_rate == 0.0 and empty_result["verdict"] == "fail",
        "빈 결과물은 불합격으로 센다 (건너뛰지 않는다)",
        f"tone_pass_rate={tone_rate} verdict={empty_result['verdict']}",
    )


# ─────────────────────────────────────────────────────────────
# 3. 판정이 실제로 갈리는가 (통과·불합격 짝)
# ─────────────────────────────────────────────────────────────
def _check_discrimination(rep: Report) -> None:
    print("\n── 3. 판정이 실제로 갈리는가 ───────────────────────────────")

    base = "# 제목\n\n| 구분 | 값 |\n|---|---|\n| 예산 | 1,200 |\n\n```\ncode\n```"
    cases = {
        "markdown_table": "# 제목\n\n| 구분 | 값 | 추가 |\n|---|---|\n| 예산 | 1,200 |\n\n```\ncode\n```",
        "heading": "## 제목\n\n| 구분 | 값 |\n|---|---|\n| 예산 | 1,200 |\n\n```\ncode\n```",
        "code_fence": "# 제목\n\n| 구분 | 값 |\n|---|---|\n| 예산 | 1,200 |\n\ncode",
    }
    rep.expect(
        structure_metrics.fingerprint_diff(base, base)["passed"],
        "구조 지문: 같은 문서는 통과",
    )
    for kind, damaged in cases.items():
        issues = structure_metrics.fingerprint_diff(base, damaged)["issues"]
        rep.expect(kind in issues, f"구조 지문: {kind} 훼손을 잡는다", f"issues={issues}")
    html_before = "<table><tr><td>a</td><td>b</td></tr></table>"
    html_after = "<table><tr><td>a</td></tr></table>"
    rep.expect(
        "html_table" in structure_metrics.fingerprint_diff(html_before, html_after)["issues"],
        "구조 지문: HTML 표 셀 수 변화를 잡는다",
    )

    # 사실 보존 — 날짜 표기 차이는 감점 대상이 아니고, 값이 바뀌면 잡아야 한다.
    same = numeric_metrics.cross_check_facts(
        "계약일은 2026년 3월 12일이고 예산은 1,200만원이다.",
        "계약일은 2026-03-12이고 예산은 1,200만원이다.",
    )
    rep.expect(same["passed"], "사실 보존: 날짜 표기 차이로 감점하지 않는다", f"{same['penalty_counts']}")
    dropped = numeric_metrics.cross_check_facts("예산은 1,200만원이다.", "예산은 정해졌다.")
    rep.expect(
        not dropped["passed"] and dropped["checks"]["numbers"]["dropped"] == ["1200"],
        "사실 보존: 사라진 숫자를 잡는다",
        f"{dropped['checks']['numbers']}",
    )
    added = numeric_metrics.cross_check_facts("예산이 배정되었다.", "예산은 999만원이다.")
    rep.expect(
        not added["passed"] and added["checks"]["numbers"]["added"] == ["999"],
        "사실 보존: 새로 생긴 숫자(환각 후보)를 잡는다",
        f"{added['checks']['numbers']}",
    )

    # 용어집 — 지정어를 쓰면 준수, 다른 말로 옮기면 위반.
    ok = text_metrics.glossary_compliance("예산을 늘린다", "increase the budget", {"예산": "budget"})
    bad = text_metrics.glossary_compliance("예산을 늘린다", "increase the funds", {"예산": "budget"})
    rep.expect(
        ok["compliance_rate"] == 1.0 and bad["compliance_rate"] == 0.0,
        "용어집: 준수/위반이 갈린다",
        f"ok={ok['compliance_rate']} bad={bad['compliance_rate']}",
    )
    multi = text_metrics.glossary_compliance("예산을 늘린다", "increase the funding", {"예산": ["budget", "funding"]})
    rep.expect(multi["compliance_rate"] == 1.0, "용어집: 허용어 목록 중 하나면 준수")

    # 근거성 — 원천 길이에 흔들리지 않아야 임계를 걸 수 있다.
    long_source = ["연차 휴가는 15일입니다." + " 다른 문장입니다." * 200]
    grounded = text_metrics.grounding_overlap("연차 휴가는 15일입니다.", long_source)
    fabricated = text_metrics.grounding_overlap("연차는 30일까지 무제한 이월됩니다.", long_source)
    rep.expect(
        grounded["sentences"][0]["jaccard"] == 1.0,
        "근거성: 자카드가 원천 길이에 흔들리지 않는다",
        f"jaccard={grounded['sentences'][0]['jaccard']}",
    )
    rep.expect(
        fabricated["mean_ngram_overlap"] < grounded["mean_ngram_overlap"],
        "근거성: 지어낸 답변이 더 낮은 점수를 받는다",
        f"지어냄={fabricated['mean_ngram_overlap']} 근거있음={grounded['mean_ngram_overlap']}",
    )

    # chrF — 동일 번역 1.0, 무관한 문장은 낮다.
    rep.expect(
        numeric_metrics.chrf("가나다라마바사", "가나다라마바사")["chrf"] == 1.0,
        "chrF: 동일 문장은 1.0",
    )
    rep.expect(
        numeric_metrics.chrf("전혀 다른 내용", "가나다라마바사")["chrf"] < 0.3,
        "chrF: 무관한 문장은 낮다",
    )

    # 톤 — 종결·금지 표현·조사.
    polite_ok = tone_metrics.tone_rule_check("연차는 15일입니다. 신청은 결재로 합니다.", "polite")
    polite_bad = tone_metrics.tone_rule_check("연차는 15일이다. 결재로 신청한다.", "polite")
    rep.expect(
        polite_ok["passed"] and not polite_bad["passed"],
        "톤: 정중체 위반(반말 종결)을 잡는다",
        f"ok={polite_ok['passed']} bad={polite_bad['forbidden_hits']}",
    )
    forced = tone_metrics.tone_rule_check("연차는 15일임. 신청은 결재로 함.", "polite", "debt_reason")
    rep.expect(
        forced["tone_applied"] == "report" and forced["tone_forced_by_policy"],
        "톤: 문서유형이 톤을 강제하면 그 톤으로 채점한다",
        f"{forced['tone_applied']}",
    )

    # 조사 — **오검출이 없어야 한다.** 넓게 잡던 시절 `평가`·`증가` 를 오류로 냈다.
    ordinary = tone_metrics.particle_errors("평가. 증가. 국가. 가을. 사과. 진로.")
    rep.expect(
        ordinary["issues"] == [] and ordinary["scope"] == "not_checked",
        "조사: 목록 없이 평범한 낱말을 오검출하지 않는다",
        f"{ordinary}",
    )
    with_nouns = tone_metrics.particle_errors("예산를 늘렸습니다. 계약이 체결됐습니다.", nouns=["예산", "계약"])
    rep.expect(
        len(with_nouns["issues"]) == 1 and with_nouns["issues"][0]["expected"] == "을",
        "조사: 명사 목록을 주면 실제 오류를 잡는다",
        f"{with_nouns}",
    )
    rep.expect(
        tone_metrics.particle_errors("평가. 증가.", nouns=["평가", "증가"])["issues"] == [],
        "조사: 목록에 있는 낱말이라도 조사가 아니면 잡지 않는다",
    )

    # 시나리오 — 유실·덮어쓰기.
    lost = scenario_metrics.score_scenario(
        {
            "id": "s",
            "required_fields": ["제목"],
            "turns": [
                {"extracted": {"제목": "가"}, "session_after": {"제목": "가"}},
                {"extracted": {"부서": "나"}, "session_after": {"부서": "나"}},
            ],
        }
    )
    rep.expect(
        lost["lost_values"] and not lost["session_accuracy_passed"],
        "시나리오: 이전 턴 값 유실을 잡는다",
        f"{lost['lost_values']}",
    )
    overwritten = scenario_metrics.score_scenario(
        {
            "id": "s",
            "required_fields": ["제목"],
            "turns": [
                {"extracted": {"제목": "가"}, "session_after": {"제목": "가"}},
                {"extracted": {"부서": "나"}, "session_after": {"제목": "덮어씀", "부서": "나"}},
            ],
        }
    )
    rep.expect(
        overwritten["overwritten_values"] and not overwritten["session_accuracy_passed"],
        "시나리오: 추출하지 않은 필드가 바뀐 것을 잡는다",
        f"{overwritten['overwritten_values']}",
    )
    clean = scenario_metrics.score_scenario(
        {
            "id": "s",
            "required_fields": ["제목", "부서"],
            "turns": [
                {"extracted": {"제목": "가"}, "session_after": {"제목": "가"}},
                {"extracted": {"부서": "나"}, "session_after": {"제목": "가", "부서": "나"}},
            ],
        }
    )
    rep.expect(
        clean["session_accuracy_passed"] and clean["turns_to_complete"] == 2,
        "시나리오: 정상 누적은 통과하고 완성 턴 수를 센다",
        f"{clean}",
    )

    # 번역 구조 건강도.
    health = structure_metrics.translation_fallback_rate(
        [
            {"id": "a", "segments_in": 3, "segments_out": 3, "fallback": False},
            {"id": "b", "segments_in": 3, "segments_out": 2, "fallback": True},
        ]
    )
    rep.expect(
        health["fallback_rate"] == 0.5 and health["segment_mismatch_rate"] == 0.5,
        "번역 건강도: 폴백·세그먼트 불일치를 각각 센다",
        f"{health['fallback_rate']} / {health['segment_mismatch_rate']}",
    )

    # 필드 추출 P/R/F1.
    extraction = text_metrics.aggregate_extraction(
        [{"predicted": {"제목": "가", "부서": "나"}, "gold": {"제목": "가", "작성자": "다"}}]
    )
    overall = extraction["overall"]
    rep.expect(
        (overall["tp"], overall["fp"], overall["fn"]) == (1, 1, 1) and overall["f1"] == 0.5,
        "필드 추출: tp/fp/fn 과 F1 이 맞다",
        f"{overall}",
    )


# ─────────────────────────────────────────────────────────────
# 4. 기준 경로가 산출물에 실제로 있는가
# ─────────────────────────────────────────────────────────────
def _full_payloads(fixtures: dict) -> dict:
    """모든 기준이 **측정될 수 있는** 완전한 입력."""
    polish_pairs = [
        {
            "id": "p1",
            "original": "연차 휴가는 15일입니다. 신청은 결재로 합니다. 승인은 팀장이 합니다. 취소도 가능합니다.",
            "result": "연차 휴가는 15일입니다. 신청은 결재로 합니다. 승인은 팀장이 합니다. 취소도 가능합니다.",
            "tone": "polite",
        }
    ]
    return {
        "template_fill": {
            "extraction_samples": [
                {"predicted": {"제목": "가"}, "gold": {"제목": "가"}, "allowed_names": ["제목"]}
            ],
            "hwpx_before": fixtures["before"],
            "hwpx_after": fixtures["after"],
            "written_values": {"제목": "2026년 사업계획", "작성자": "홍길동", "부서": "영업본부"},
            "scenarios": [
                {
                    "id": "s1",
                    "required_fields": ["제목"],
                    "turns": [{"extracted": {"제목": "가"}, "session_after": {"제목": "가"}}],
                }
            ],
        },
        "text_polish": {"pairs": polish_pairs},
        "translation": {
            "records": [{"id": "r1", "segments_in": 3, "segments_out": 3, "fallback": False}],
            "pairs": [
                {
                    "id": "t1",
                    "source": "예산은 1,200만원입니다.",
                    "target": "The budget is 1,200 만원.",
                    "reference": "The budget is 1,200 만원.",
                }
            ],
            "glossary": {"예산": "budget"},
        },
        "faq": {"items": [{"id": "f1", "answer": "연차는 15일입니다.", "sources": ["연차는 15일입니다."]}]},
    }


def _check_targets_reachable(rep: Report, fixtures: dict) -> None:
    print("\n── 4. 기준 경로가 산출물에 실제로 있는가 ───────────────────")
    payloads = _full_payloads(fixtures)
    # python-hwpx 는 선택 의존이다. 없으면 그 기준만 not_measured 가 정상이다.
    optional = {"hwpx_text_crosscheck.no_paragraph_loss"}
    # 용어집 기준은 원문/번역문 양쪽에 용어가 있어야 측정된다. 위 픽스처가 그 조건을 만든다.

    for feature, payload in payloads.items():
        result = suites.run_suite(feature, payload)
        unreachable = [
            path for path in result["not_measured_targets"] if path not in optional
        ]
        rep.expect(
            not unreachable,
            f"{feature}: 완전한 입력에서 모든 기준이 측정된다",
            f"측정 못한 기준={unreachable}\n"
            "지표 키를 바꾸면 그 기준은 영원히 not_measured 가 된다 (조용한 미측정).",
        )
        # 선언한 지표가 전부 실행됐는가 — 실행도 안 되고 skipped 에도 없는 지표가 있으면
        # 리포트 어디에도 그 사실이 안 남는다.
        declared = {spec["tool"] for spec in suites.SUITES[feature]["metrics"]}
        ran = set(result["metrics"])
        skipped = {row["tool"] for row in result["skipped_metrics"]}
        rep.expect(
            declared <= ran | skipped,
            f"{feature}: 선언한 지표는 실행되거나 건너뛴 사유가 남는다",
            f"누락={sorted(declared - ran - skipped)}",
        )

    # 완전 입력의 006 은 실제로 pass 여야 한다 (픽스처가 정상 채움이므로).
    full = suites.run_suite("template_fill", payloads["template_fill"])
    rep.expect(
        full["verdict"] in ("pass", "pass_but_incomplete") and not full["failed_targets"],
        "006: 정상 채움 픽스처는 기준을 통과한다",
        f"verdict={full['verdict']} failed={full['failed_targets']}",
    )


# ─────────────────────────────────────────────────────────────
# 5. hwpx 지표
# ─────────────────────────────────────────────────────────────
def _check_hwpx(rep: Report, fixtures: dict) -> None:
    print("\n── 5. hwpx 지표 (합성 픽스처) ──────────────────────────────")

    scan = structure_metrics.scan_hwpx(fixtures["before"])
    names = sorted(field["name"] for field in scan["fields"])
    rep.expect(
        names == ["부서", "작성자", "제목"],
        "스캔: 슬롯 2개(표 안 1개) + 누름틀 1개를 모두 찾는다",
        f"{names}",
    )
    dept = next(f for f in scan["fields"] if f["name"] == "부서")
    rep.expect(
        dept["guide"] == "부서를 입력하세요" and not dept["filled"],
        "스캔: 누름틀 안내문을 `Direction` 에서 읽는다 (Command 블롭이 아니다)",
        f"guide={dept['guide']!r} filled={dept['filled']}",
    )

    roundtrip = structure_metrics.hwpx_roundtrip(
        fixtures["before"],
        fixtures["after"],
        {"제목": "2026년 사업계획", "작성자": "홍길동", "부서": "영업본부"},
    )
    rep.expect(
        roundtrip["agreement_rate"] == 1.0 and not roundtrip["value_mismatch"],
        "라운드트립: 채운 값이 그대로 재스캔된다",
        f"agreement={roundtrip['agreement_rate']} mismatch={roundtrip['value_mismatch']}",
    )
    integrity = structure_metrics.hwpx_integrity(fixtures["before"], fixtures["after"])
    rep.expect(
        integrity["passed"] and integrity["object_counts_match"],
        "무결성: 값만 채운 문서는 골격이 같다",
        f"{integrity['tag_count_diff']} broken={integrity['skeleton_broken_paragraphs']}",
    )

    broken = structure_metrics.hwpx_integrity(fixtures["before"], fixtures["broken"])
    rep.expect(
        not broken["passed"],
        "무결성: 골격(중괄호 밖 텍스트)이 바뀌면 잡는다",
        f"identical={broken['outside_text_identical']} broken={broken['skeleton_broken_paragraphs']}",
    )

    # 값을 안 채운 문서를 "채웠다" 고 주장하면 라운드트립이 어긋나야 한다.
    unfilled = structure_metrics.hwpx_roundtrip(
        fixtures["before"], fixtures["before"], {"제목": "2026년 사업계획"}
    )
    rep.expect(
        unfilled["agreement_rate"] < 1.0 and "제목" in unfilled["disagreements"],
        "라운드트립: 값을 줬는데 안 채워졌으면 불일치로 잡는다",
        f"{unfilled['agreement_rate']} {unfilled['disagreements']}",
    )

    rep.raises(
        lambda: structure_metrics.scan_hwpx(os.path.join(os.path.dirname(fixtures["before"]), "없다.hwpx")),
        "hwpx: 없는 파일은 예외",
    )
    not_zip = os.path.join(os.path.dirname(fixtures["before"]), "plain.hwpx")
    with open(not_zip, "wb") as handle:
        handle.write(b"not a zip")
    rep.raises(lambda: structure_metrics.scan_hwpx(not_zip), "hwpx: zip 이 아니면 예외")


# ─────────────────────────────────────────────────────────────
# 6. 게이트 규율
# ─────────────────────────────────────────────────────────────
def _check_gate(rep: Report) -> None:
    print("\n── 6. LLM Judge 게이트 규율 ────────────────────────────────")

    items = [{"id": f"i{n}", "deterministic_passed": n % 2 == 0, "similarity": None} for n in range(20)]
    gate = gating.gate_llm_judge(items, opt_in=True, judge_enabled=True, sample_rate=1.0)
    rep.expect(
        all(c["reason"] == "deterministic_failed" for c in gate["candidates"]),
        "게이트: 결정적 지표 통과분은 후보에서 빠진다 (전건 호출 금지)",
        f"candidates={len(gate['candidates'])}/{len(items)}",
    )
    rep.expect(
        len(gate["items_without_embedding_screening"]) == 10,
        "게이트: 임베딩 스크리닝 없이 통과한 건을 따로 보고한다",
        f"{len(gate['items_without_embedding_screening'])}",
    )

    closed = gating.gate_llm_judge(items, opt_in=True, judge_enabled=False, sample_rate=1.0)
    rep.expect(
        closed["gate_open"] is False and not closed["sampled_for_judge"] and closed["blocked_reason"],
        "게이트: opt_in 만으로는 열리지 않는다 (서빙 확인 필요)",
        f"open={closed['gate_open']}",
    )

    first = gating.gate_llm_judge(items, opt_in=True, judge_enabled=True, sample_rate=0.5)
    second = gating.gate_llm_judge(items, opt_in=True, judge_enabled=True, sample_rate=0.5)
    rep.expect(
        [c["id"] for c in first["sampled_for_judge"]] == [c["id"] for c in second["sampled_for_judge"]],
        "게이트: 같은 입력이면 같은 표본 (난수 아님 — 지표 재현)",
        f"{[c['id'] for c in first['sampled_for_judge']]}",
    )
    rep.expect(
        len(first["sampled_for_judge"]) < len(first["candidates"]),
        "게이트: 표본 비율이 실제로 후보를 줄인다",
        f"{len(first['sampled_for_judge'])}/{len(first['candidates'])}",
    )
    rep.raises(
        lambda: gating.gate_llm_judge(items, sample_rate=1.5),
        "게이트: 표본 비율 범위를 검증한다",
    )

    # 임베딩 유사도가 임계 이상이면 스크리닝 통과로 빠진다.
    screened = gating.gate_llm_judge(
        [{"id": "a", "deterministic_passed": True, "similarity": 0.95},
         {"id": "b", "deterministic_passed": True, "similarity": 0.1}],
        opt_in=True, judge_enabled=True, sample_rate=1.0,
    )
    rep.expect(
        [c["id"] for c in screened["candidates"]] == ["b"],
        "게이트: 임베딩 통과분은 빠지고 낮은 건만 후보가 된다",
        f"{screened['candidates']}",
    )


# ─────────────────────────────────────────────────────────────
# 7. 도구 표면 정합성 (server.py ↔ catalog ↔ suites)
# ─────────────────────────────────────────────────────────────
def _tool_names_in_server() -> list:
    """`server.py` 를 **import 하지 않고** `@mcp.tool()` 이름을 뽑는다.

    fastmcp 는 이 저장소의 로컬 환경에 없다(배포 시 PyPI 등록). 그래서 정적으로 읽는다.
    """
    tree = ast.parse(open(_SERVER_PY, encoding="utf-8").read())
    names = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Attribute) and target.attr == "tool":
                names.append(node.name)
    return names


def _check_tool_surface(rep: Report) -> None:
    print("\n── 7. 도구 표면 정합성 ─────────────────────────────────────")
    server_tools = set(_tool_names_in_server())
    catalog_tools = {row["tool"] for row in catalog.CATALOG}
    # `metric_catalog` 는 카탈로그 자신을 내는 도구라 표에 넣지 않는다.
    rep.expect(
        server_tools - {"metric_catalog"} == catalog_tools,
        "도구 목록 ↔ 카탈로그가 같다 (표에 없는 도구는 운영 지표가 아니다)",
        f"서버에만={sorted(server_tools - catalog_tools - {'metric_catalog'})}\n"
        f"표에만={sorted(catalog_tools - server_tools)}",
    )

    declared = {spec["tool"] for suite in suites.SUITES.values() for spec in suite["metrics"]}
    rep.expect(
        declared <= catalog_tools,
        "묶음이 선언한 지표가 전부 카탈로그에 있다",
        f"표에 없는 지표={sorted(declared - catalog_tools)}",
    )

    # 도구는 전부 타입힌트가 있어야 한다 (가이드 p.24 — 없으면 입력 형식이 안 만들어진다).
    tree = ast.parse(open(_SERVER_PY, encoding="utf-8").read())
    missing = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in server_tools:
            continue
        if node.returns is None:
            missing.append(f"{node.name}(반환)")
        for arg in node.args.args:
            if arg.annotation is None:
                missing.append(f"{node.name}({arg.arg})")
    rep.expect(not missing, "모든 도구에 타입힌트가 있다", f"누락={missing}")

    rep.expect(
        bool(catalog.NOT_IMPLEMENTED),
        "미구현 지표 목록이 비어 있지 않다 (측정 공백을 숨기지 않는다)",
    )


def main() -> int:
    print("평가지표(eval) 회귀 점검 — 가드레일 자체를 검증한다\n")
    rep = Report()
    tmp = tempfile.mkdtemp(prefix="genon-eval-check-")
    try:
        fixtures = _fixtures(tmp)
        _check_not_measured(rep)
        _check_input_contract(rep)
        _check_discrimination(rep)
        _check_targets_reachable(rep, fixtures)
        _check_hwpx(rep, fixtures)
        _check_gate(rep)
        _check_tool_surface(rep)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        for label in rep.failures:
            print(f"  - {label}")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
