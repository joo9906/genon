"""프롬프트가 실제로 렌더되는가 — **네 단위의 실제 조립 함수**를 부른다.

```
python onprem/test/check_prompt_render.py
```

서버도 LLM 도 필요 없다. 배포 단위의 빌더를 그대로 불러 프롬프트 문자열을 받아 본다.

## 왜 이 점검이 있나 (2026-09-07 신설)

**이 층을 보는 점검이 하나도 없었다.** 2026-09-07 에 jinja 를 걷어내면서 로더는
`{{ name }}` 치환만 남았고(`{% for %}`·`{% if %}` 가 없다), 그래서 템플릿은 **미리
조립된 문자열**을 받도록 다시 쓰였다 — `field_lines`(줄을 이은 것)·`glossary_block`
(절 전체)·`context_line`(개행 포함)·`existing_block`·`body_section`·`chunk_note`·
`doc_type_block`. 그런데 **조립 함수는 옛 변수 이름을 그대로 넘기고 있었다.**

실측한 결과 넷이 렌더에서 죽었다: 006 문서 자동 채움 · 번역 배치 · 번역 단건 ·
FAQ 부족분 재요청. **넷 다 예외를 잡아 fail-open 한다** — 006 은 `prefill_failed`
한 줄, FAQ 는 1차 결과를 그대로 쓰고 조용히 포기, 번역은 요청이 서지만 그 사유가
`prompt_render_failed` 라 "LLM 이 안 된다" 와 로그에서만 갈린다. 그래서 넉 달을
살아남을 수 있었다.

## 무엇을 보는가

1. **네 단위의 모든 조립 경로가 렌더된다.** 대역이 아니라 배포 단위의 실제 함수다 —
   변수 목록을 손으로 적으면 빌더가 이름을 바꿔도 사본이 그대로라 대조가 성립하지 않는다.
2. **파이썬 repr 이 프롬프트에 실리지 않는다.** 로더는 문자열이 아닌 값을 `str(value)`
   로 떨어뜨리므로 리스트를 넘기면 **렌더가 죽지 않고** `['- 제목 (미입력)']` 이
   프롬프트에 실린다. 오류가 아니라 결과물 품질로만 드러나는 형태라 따로 본다.
3. **넣고 빼는 판단이 살아 있다.** 조각이 하나면 조각 표기가 없고, 용어가 없으면
   용어사전 절이 없고, 본문 서식이 없으면 본문 추가 구획이 없다. 그 판단이 예전에는
   템플릿의 `{% if %}` 였으므로 **옮겨 오다 빠지기 쉬운 자리**다.
4. **템플릿 문법이 로더가 받는 범위 안이다** — 남은 `{% %}` 는 로더가 거부한다.
"""

import os
import re
import sys
import types

_ONPREM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CS = os.path.join(_ONPREM, "codeserving")
_PROMPT_ROOT = os.path.join(_ONPREM, "prompt")

for _unit in (
    "SFR-006_template_fill",
    "SFR-018_faq",
    "SFR-018_translation",
    "SFR-018_text_polish",
):
    sys.path.insert(0, os.path.join(_CS, _unit))


class Report:
    def __init__(self) -> None:
        self.checks = 0
        self.failures: list = []

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        self.checks += 1
        if ok:
            print(f"[OK  ] {label}")
        else:
            self.failures.append(label)
            print(f"[FAIL] {label}")
            if detail:
                print(f"        {detail}")


# --------------------------------------------------------------------------
# 픽스처 — 빌더가 읽는 것만 가진 최소 대역
# --------------------------------------------------------------------------

def _spec(name: str, guide: str = "", filled: bool = False):
    """`hwpx_fields.FieldSpec` 대역. 프롬프트 조립은 `name`·`guide`·`filled` 만 본다."""
    return types.SimpleNamespace(name=name, guide=guide, filled=filled)


def _term(source: str, target: str):
    """`GlossaryTerm` 대역."""
    return types.SimpleNamespace(term_source=source, term_target=target)


def _faq_item(question: str):
    return types.SimpleNamespace(question=question)


# 파이썬 컨테이너가 문자열로 떨어진 흔적. **작은따옴표만** 본다 — 파이썬 repr 은
# 홑따옴표를 쓰고, 큰따옴표 쪽은 프롬프트가 일부러 싣는 JSON 예시다
# (FAQ `system.txt` 의 `{"faqs": [...]}` 가 그것이다). 큰따옴표까지 잡으면 그 예시가
# 오탐으로 걸리고, **오탐은 결국 미탐으로 간다** — 사람이 판정을 끈다.
_REPR_RE = re.compile(r"\[\s*'|\[\s*\{\s*'|\{\s*'\w+'\s*:")


def _no_repr(rep: Report, label: str, *texts: str) -> None:
    """프롬프트에 파이썬 repr 이 실리지 않았는가.

    로더가 리스트를 `str(value)` 로 떨어뜨리므로 **렌더는 성공하고** 프롬프트만
    망가진다. 그 실패는 오류가 아니라 결과물 품질로만 드러난다.
    """
    hits = [
        match.group(0)
        for text in texts
        for match in [_REPR_RE.search(text or "")]
        if match
    ]
    rep.check(not hits, f"{label} — 파이썬 repr 미노출", f"발견: {hits}")


# --------------------------------------------------------------------------
# 0. 템플릿 문법 — 로더가 받는 범위인가
# --------------------------------------------------------------------------

def check_template_syntax(rep: Report) -> None:
    """`{% %}` 가 남아 있으면 로더가 그 프롬프트를 통째로 거부한다.

    jinja 제거가 **파일마다** 끝났는지 보는 판정이다. 하나만 남아도 그 기능의
    프롬프트가 렌더되지 않고, fail-open 이라 조용하다.
    """
    for unit in sorted(os.listdir(_PROMPT_ROOT)):
        unit_dir = os.path.join(_PROMPT_ROOT, unit)
        if not os.path.isdir(unit_dir):
            continue
        for name in sorted(os.listdir(unit_dir)):
            path = os.path.join(unit_dir, name)
            if not os.path.isfile(path) or name.startswith("README"):
                continue
            with open(path, encoding="utf-8") as handle:
                body = handle.read()
            rep.check(
                "{%" not in body,
                f"{unit}/{name} — 지원하는 문법만 쓴다 (`{{% %}}` 없음)",
                "로더가 이 프롬프트를 거부한다 (`_render_source`)",
            )
            rep.check(
                name.endswith(".txt"),
                f"{unit}/{name} — 확장자가 `.txt` 다",
                "로더의 `_TEMPLATE_SUFFIX` 는 `.txt` 다 (2026-09-07)",
            )


# --------------------------------------------------------------------------
# 1. SFR-006 템플릿 채우기
# --------------------------------------------------------------------------

def check_template_fill(rep: Report) -> None:
    from template_fill import prompts

    fields = [_spec("제목"), _spec("작성자"), _spec("기간", guide="YYYY. M. D.")]

    # ── 값 추출 ──
    system, user = prompts.build_extract_prompts(fields, {"제목": "가나다"}, "작성자는 왕주영")
    rep.check(bool(system.strip()), "006 값 추출 — 시스템 프롬프트가 비지 않는다")
    rep.check(
        "- 제목 (채워짐)" in user and "- 작성자 (미입력)" in user,
        "006 값 추출 — 항목 줄이 이어붙어 실린다",
        user[:200],
    )
    rep.check("작성자는 왕주영" in user, "006 값 추출 — 이번 턴 발화가 실린다")
    rep.check('{"제목": "가나다"}' in user, "006 값 추출 — 수집된 값이 JSON 으로 실린다")
    _no_repr(rep, "006 값 추출", system, user)

    # 본문 서식이 없으면 본문 추가 구획을 아예 넣지 않는다 (옛 `{% if %}`).
    # 쓸 수 없는 기능에 목록을 붙여 보여주면 LLM 이 그쪽으로 답을 만든다.
    rep.check(
        "[본문 서식 목록]" not in user,
        "006 값 추출 — 서식이 없으면 본문 추가 구획이 없다",
        user[:300],
    )
    _, with_body = prompts.build_extract_prompts(
        fields, {}, "본문 추가", block_styles=["본문"], blocks=[{"text": "첫 문단", "style_ref": "본문"}]
    )
    rep.check(
        "[본문 서식 목록]" in with_body and "- 본문" in with_body,
        "006 값 추출 — 서식이 있으면 본문 추가 구획이 들어간다",
        with_body[:300],
    )
    rep.check(
        "1. [본문] 첫 문단" in with_body,
        "006 값 추출 — 쌓인 블록이 번호와 함께 실린다",
        with_body[:300],
    )
    _no_repr(rep, "006 값 추출(본문)", with_body)

    # ── 문서 자동 채움 (캔버스 첨부 경로) ──
    system, user = prompts.build_document_prompts(fields, "제목: 통합 플랫폼 구축", 1, 1)
    rep.check(bool(system.strip()), "006 자동 채움 — 시스템 프롬프트가 비지 않는다")
    rep.check("제목: 통합 플랫폼 구축" in user, "006 자동 채움 — 문서 본문이 실린다")
    rep.check(
        "- 제목" in user and "(미입력)" not in user,
        "006 자동 채움 — 상태 라벨을 붙이지 않는다 (전부 미입력이다)",
        user[:200],
    )
    _no_repr(rep, "006 자동 채움", system, user)

    # 조각이 하나뿐일 때 조각 표기를 붙이면 **없는 잘림을 알리는 셈**이다
    rep.check("구간 중" not in user, "006 자동 채움 — 조각 하나면 조각 표기가 없다", user[:200])
    _, chunked = prompts.build_document_prompts(fields, "본문", 2, 3)
    rep.check(
        "(3개 구간 중 2번째)" in chunked,
        "006 자동 채움 — 조각이 여럿이면 몇 번째인지 알린다",
        chunked[:200],
    )


# --------------------------------------------------------------------------
# 2. SFR-018 FAQ
# --------------------------------------------------------------------------

def check_faq(rep: Report) -> None:
    from faq.prompt_loader import render

    system = render("system.txt", count=5, difficulty_note="난이도 안내")
    rep.check("5" in system, "FAQ 시스템 — 개수가 실린다", system[:150])
    user = render("user.txt", document="문서 본문이다.", count=5)
    rep.check("문서 본문이다." in user, "FAQ 유저 — 문서가 실린다", user[:150])
    _no_repr(rep, "FAQ 생성", system, user)

    # 부족분 재요청 — 옛 `existing_questions`(list) 를 넘기면 렌더가 죽는다
    retry = render(
        "retry_shortfall.txt",
        document="문서 본문이다.",
        missing=2,
        existing_block="- 첫 질문\n- 둘째 질문",
    )
    rep.check(
        "- 첫 질문" in retry and "- 둘째 질문" in retry,
        "FAQ 재요청 — 이미 만든 질문이 줄로 실린다",
        retry[:200],
    )
    rep.check("2개 더" in retry, "FAQ 재요청 — 부족한 개수가 실린다", retry[:200])
    _no_repr(rep, "FAQ 재요청", retry)

    # 실제 호출부가 그 이름으로 넘기는지 — 소스에서 직접 본다. 템플릿만 맞고
    # `generator.py` 가 옛 이름을 넘기면 위 판정은 통과하고 운영만 죽는다.
    path = os.path.join(_CS, "SFR-018_faq", "faq", "generator.py")
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    rep.check(
        "existing_block=" in source and "existing_questions=" not in source,
        "FAQ 재요청 — `generator.py` 가 조립된 블록을 넘긴다",
        "옛 이름(`existing_questions`)이 남아 있으면 렌더가 죽고 재요청이 조용히 포기된다",
    )


# --------------------------------------------------------------------------
# 3. SFR-018 번역
# --------------------------------------------------------------------------

def check_translation(rep: Report) -> None:
    from translation_pipeline.common import prompt_builder

    context = types.SimpleNamespace(
        source_label="한국어",
        target_label="영어",
        register_label="문어체",
        register_instruction="문어체로 씁니다.",
    )
    terms = [_term("가맹점", "merchant")]

    # ── 배치 ──
    system, user = prompt_builder.build_batch_prompts(
        context, [("u1", "가맹점 수수료", "제1장 총칙")], terms
    )
    rep.check("한국어 → 영어" in system, "번역 배치 — 방향이 실린다", system[:150])
    rep.check("문어체로 씁니다." in system, "번역 배치 — 문체 지시가 실린다")
    rep.check(
        '- "가맹점" -> "merchant"' in system,
        "번역 배치 — 용어사전이 줄로 실린다",
        system[-300:],
    )
    rep.check(
        '"s": "가맹점 수수료"' in user and '"c": "제1장 총칙"' in user,
        "번역 배치 — 원문·문맥이 JSON 으로 실린다",
        user[:200],
    )
    _no_repr(rep, "번역 배치", user)
    rep.check(
        "'source'" not in system and "'target'" not in system,
        "번역 배치 — 용어 dict repr 이 실리지 않는다",
        system[-300:],
    )

    # 용어가 없으면 용어사전 절 자체를 넣지 않는다 (옛 `{% if %}`) —
    # 등장하지 않는 용어까지 지시하면 모델이 억지로 끼워 넣는다
    bare, _ = prompt_builder.build_batch_prompts(context, [("u1", "본문", "")], [])
    rep.check(
        "[용어사전" not in bare,
        "번역 배치 — 용어가 없으면 용어사전 절이 없다",
        bare[-200:],
    )

    # ── 단건 (배치 실패 폴백) ──
    system, user = prompt_builder.build_single_prompts(context, "가맹점 수수료", terms, "제1장 총칙")
    rep.check("한국어 → 영어" in system, "번역 단건 — 방향이 실린다")
    rep.check(
        '- "가맹점" -> "merchant"' in system,
        "번역 단건 — 용어사전이 배치와 같이 실린다",
        system[-300:],
    )
    rep.check(
        "제1장 총칙" in user and user.strip().endswith("SOURCE_TEXT: 가맹점 수수료"),
        "번역 단건 — 문맥이 원문 앞 줄에 실린다",
        repr(user),
    )
    _no_repr(rep, "번역 단건", system, user)

    # 문맥이 없을 때 빈 줄이 남으면 모델이 그 자리를 무엇으로 읽을지 모른다
    _, no_scope = prompt_builder.build_single_prompts(context, "본문", [], "")
    rep.check(
        no_scope.strip() == "SOURCE_TEXT: 본문",
        "번역 단건 — 문맥이 없으면 줄이 남지 않는다",
        repr(no_scope),
    )


# --------------------------------------------------------------------------
# 4. SFR-018 글다듬이
# --------------------------------------------------------------------------

def check_text_polish(rep: Report) -> None:
    import main as polish_main
    from text_polish.prompt_loader import render

    policy = types.SimpleNamespace(label="메일", extra_instruction="수신자를 배려합니다.")
    tone = types.SimpleNamespace(label="격식·정중", instruction="정중한 표현을 씁니다.")

    system = render(
        "system.txt",
        doc_type_label=policy.label,
        doc_type_block=polish_main._doc_type_block("email", policy),
        tone_label=tone.label,
        tone_instruction=tone.instruction,
    )
    rep.check("[문서유형: 메일]" in system, "글다듬이 — 문서유형 라벨이 실린다", system[-300:])
    rep.check("[톤: 격식·정중]" in system, "글다듬이 — 톤 라벨이 실린다", system[-300:])
    rep.check("정중한 표현을 씁니다." in system, "글다듬이 — 톤 지시문이 실린다")
    _no_repr(rep, "글다듬이", system)

    # 문서유형 지시문이 없으면 **빈 문자열**이고, 있으면 개행으로 끝난다 —
    # 그 규약이라야 `[톤: …]` 앞 빈 줄이 두 경우 모두 맞는다
    empty_policy = types.SimpleNamespace(label="메일", extra_instruction="")
    rep.check(
        polish_main._doc_type_block("", empty_policy) == "",
        "글다듬이 — 지시문이 없으면 문서유형 블록이 빈 문자열이다",
        repr(polish_main._doc_type_block("", empty_policy)),
    )
    block = polish_main._doc_type_block("", policy)
    rep.check(
        block.endswith("\n") and block.strip() == "수신자를 배려합니다.",
        "글다듬이 — 지시문이 있으면 개행으로 끝난다",
        repr(block),
    )

    # 라우트가 그 이름으로 넘기는지 — 소스에서 본다 (템플릿만 맞으면 통과하기 때문)
    path = os.path.join(_CS, "SFR-018_text_polish", "main.py")
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    rep.check(
        "doc_type_block=" in source and "doc_type_instruction=_doc_type" not in source,
        "글다듬이 — 라우트가 조립된 블록을 넘긴다",
        "옛 이름(`doc_type_instruction`)을 넘기면 렌더가 죽고 글다듬이가 통째로 막힌다",
    )


def main() -> int:
    rep = Report()
    for label, fn in (
        ("템플릿 문법", check_template_syntax),
        ("SFR-006 템플릿 채우기", check_template_fill),
        ("SFR-018 FAQ", check_faq),
        ("SFR-018 번역", check_translation),
        ("SFR-018 글다듬이", check_text_polish),
    ):
        print(f"\n─── {label} ───")
        try:
            fn(rep)
        except Exception as exc:  # noqa: BLE001
            # 렌더 실패는 **예외로 온다.** 그것이 이 점검의 주된 발견 형태이므로
            # 여기서 삼키지 않고 FAIL 로 세운다 — 다른 단위 판정은 계속 돌린다.
            rep.check(False, f"{label} — 조립이 예외 없이 끝난다", f"{type(exc).__name__}: {exc}")

    print()
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        print()
        print("프롬프트 변수 계약이 갈렸다. 고칠 자리는 둘 중 하나다:")
        print("  - 조립 함수  : template_fill/prompts.py · faq/generator.py ·")
        print("                 translation_pipeline/common/prompt_builder.py ·")
        print("                 SFR-018_text_polish/main.py")
        print("  - 템플릿     : onprem/prompt/<단위>/*.txt  (변수 목록은 머리말 주석에 있다)")
        print()
        print("로더는 `{{ name }}` 치환만 한다 — 목록을 이어붙이는 것과 절을 넣고 빼는")
        print("판단은 **조립 함수의 몫**이다 (2026-09-07 jinja 제거).")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
