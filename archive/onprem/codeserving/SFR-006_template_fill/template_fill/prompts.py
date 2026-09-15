"""프롬프트 조립 — 문구는 `onprem/prompt/SFR-006_template_fill/*.txt` 에 있다.

이 파일은 **템플릿에 넘길 변수를 정리하는 역할만** 한다.

## 넘기는 값은 **전부 문자열**이다 (2026-09-07)

로더에서 jinja 를 걷어내면서 `{{ name }}` 치환만 남았다 — `{% for %}`·`{% if %}` 가
없으므로 **목록을 이어붙이고 있어야 할 블록을 넣거나 빼는 일을 이 파일이 한다.**
리스트를 그대로 넘기면 로더가 `str(value)` 로 떨어뜨려 **`['- 제목 (미입력)']` 이라는
파이썬 repr 이 프롬프트에 실린다** — 오류가 아니라 결과물 품질로만 드러난다.
그래서 `_field_lines`·`_block_lines` 는 목록을 만들고 **`_joined` 가 문자열로 굳힌다.**
`onprem/test/check_prompt_render.py` 가 네 단위의 실제 빌더를 불러 이것을 본다. 문구를 코드 밖으로 뺀 이유는
`prompt_loader.py` 머리말에 적었다 (번역·FAQ 단위와 같은 계약).

LLM 의 역할은 두 곳 모두 좁게 한정한다:
- 값 추출(02) — "사용자 발화에서 항목 값과 지움 지시를 찾아내는 것"까지. 어떤 항목이
  채워졌는지, 목록에 없는 이름을 걸러낼지는 `run_chat.py` 가 화이트리스트로 결정적으로
  판정한다.
- 톤 변환(03) — 문체만. 숫자·날짜 보존은 `value_guard` 가 변환 후 다시 검증한다.

두 경우 모두 **프롬프트 지시를 보장으로 보지 않는다** (CLAUDE.md §5).

반환 형태를 `(system, user)` 튜플로 맞춘 이유: 예전에는 시스템 프롬프트가 모듈 상수라
호출부가 `SYSTEM 상수 + build_*_user_prompt()` 두 개를 따로 들고 있었다. 렌더는 실패할
수 있으므로(템플릿 부재·변수 누락) 상수로 둘 수 없고, 두 프롬프트를 한 함수에서 만들면
템플릿 변수를 늘릴 때 한쪽만 고치는 실수도 막힌다 (번역 단위 `prompt_builder.py` 와 동형).
"""

import json
import re

from .logging_utils import log_warning
from .prompt_loader import PromptRenderError, prompt_exists, render


def _field_lines(fields: list, current_values: dict) -> list:
    """필드 스키마를 프롬프트에 실을 한 줄짜리 표기로 바꾼다.

    상태 라벨(`채워짐`/`미입력`)을 코드가 붙이는 이유: 채워짐 판정은 세션에 모인 값과
    템플릿에 원래 적힌 값(`spec.filled`) 둘 다를 봐야 하는데, 그 판단을 프롬프트로
    설명해 LLM 에 맡기면 이미 채워진 항목을 다시 묻는 답변이 나온다.
    """
    lines = []
    for spec in fields:
        status = "채워짐" if (spec.name in current_values or spec.filled) else "미입력"
        # 슬롯은 따옴표 안 문자열이 곧 항목명이자 안내문이라 둘이 같다. 같은 말을 두 번
        # 적으면 프롬프트만 길어지고 모델이 두 항목으로 오해할 여지가 생긴다.
        guide = f" — 안내문: {spec.guide}" if spec.guide and spec.guide != spec.name else ""
        lines.append(f"- {spec.name} ({status}){guide}")
    return lines


def _joined(lines: list) -> str:
    """목록을 프롬프트에 실을 한 덩어리로 굳힌다.

    비어 있으면 **빈 문자열**이다 — `"- (없음)"` 같은 자리표시를 코드가 만들면 그 말이
    프롬프트 문구가 되고, 문구는 템플릿이 갖는다는 규약과 어긋난다.
    """
    return "\n".join(lines)


def _block_lines(blocks) -> list:
    """지금까지 쌓인 본문 블록을 `번호. [서식] 내용` 목록으로 바꾼다.

    번호를 붙여 보여줘야 사용자가 "2번 빼줘" 라고 말할 수 있다 (규칙 16).
    `BodyBlock` 과 dict 를 모두 받는다 — 세션에서 복원한 블록은 dict 다.
    """
    lines = []
    for index, block in enumerate(blocks or (), start=1):
        text = getattr(block, "text", None)
        style_ref = getattr(block, "style_ref", None)
        if text is None and isinstance(block, dict):
            text, style_ref = block.get("text"), block.get("style_ref")
        style = f" [{style_ref}]" if style_ref else ""
        lines.append(f"{index}.{style} {text}")
    return lines


# ── 템플릿별 프롬프트 (2026-09-15 요구 추가) ────────────────────────────────
#
# 고객사 요구: **보고서 채우기를 고르면 보고서만의 시스템 프롬프트**로 채운다.
# 템플릿마다 "무엇을 어떻게 읽어 항목에 넣을까" 가 다르기 때문이다.
#
# 이름 규칙은 `<기본이름>__<템플릿>` 이고, **본문이 실제로 있을 때만** 그 이름을 쓴다 —
# 이름만 보고 골랐다가 파일이 없으면 `PromptRenderError` 로 요청이 서고, **템플릿 하나에
# 전용 프롬프트를 안 만들었다는 이유로 그 템플릿이 통째로 죽는다.** 글다듬이의
# `_tone_prompt_name` 이 같은 이유로 같은 모양이다.
#
# 구분자가 `__`(밑줄 둘)인 이유: 템플릿 id 에 밑줄이 들어갈 수 있어 한 개로는 경계가
# 모호하다(`extract_system_보도_자료` 가 무엇의 접미어인지 알 수 없다).
_TEMPLATE_PROMPT_SEPARATOR = "__"

# 템플릿 id 를 프롬프트 이름에 쓸 수 있는 글자로 좁힌다. `template_index._index_key` 와
# 같은 규약이다 — 그쪽은 Redis 키, 이쪽은 파일 이름이라 **경로 조작을 여기서 한 번 더**
# 막는다(`prompt_loader` 도 막지만, 막는 층이 하나뿐이면 그 층이 바뀔 때 뚫린다).
_PROMPT_NAME_SAFE = re.compile(r"[^0-9A-Za-z가-힣._-]+")


def template_prompt_name(base: str, template_id: str) -> str:
    """이 템플릿에 쓸 프롬프트 이름. 전용 프롬프트가 없으면 `base` 그대로.

    Args:
        base: `"extract_system"` 처럼 확장자를 뗀 기본 이름.
        template_id: 이번 턴 템플릿. 비어 있으면 `base`.

    Returns:
        `"extract_system__보고서"` 또는 `"extract_system"`.
    """
    wanted = (template_id or "").strip()
    if not wanted:
        return base
    safe = _PROMPT_NAME_SAFE.sub("_", wanted)[:64].strip("_")
    if not safe:
        return base
    name = f"{base}{_TEMPLATE_PROMPT_SEPARATOR}{safe}"
    return name if prompt_exists(name) else base


def build_polish_instruction(template_id: str) -> str:
    """이 템플릿의 **본문 문체 지시문**. 없으면 빈 문자열.

    글다듬이 `POST /polish` 의 `extra_instruction` 으로 간다 — 그쪽이 문서유형 지시문
    **뒤에** 잇는다. 006 이 이 문장을 들고 있는 이유는 **템플릿 목록을 006 이 갖기**
    때문이다: 글다듬이에 두면 템플릿이 늘 때마다 남의 단위 프롬프트를 고쳐야 한다.

    **없는 것이 정상이다.** 템플릿별 문체 지시를 안 만든 배포에서는 글다듬이의
    문서유형·톤 지시문만으로 다듬는다.
    """
    name = template_prompt_name("polish_instruction", template_id)
    if name == "polish_instruction" and not prompt_exists(name):
        return ""
    try:
        return render(f"{name}.txt").strip()
    except PromptRenderError:
        # 지시문 하나 때문에 커밋이 막히면 안 된다 — 없을 때와 같은 자리로 떨어진다.
        log_warning(
            "템플릿 문체 지시문을 렌더하지 못했다 — 그 줄 없이 진행한다",
            event="polish_instruction_unavailable",
            resource_id=name,
        )
        return ""


def build_extract_prompts(
    fields: list,
    current_values: dict,
    user_message: str,
    block_styles: list | None = None,
    blocks: list | None = None,
    template_id: str = "",
) -> tuple:
    """(system, user) 값 추출 프롬프트.

    Args:
        fields: `hwpx_fields.FieldSpec` 목록.
        current_values: 지금까지 수집된 {항목명: 값}.
        user_message: 이번 턴 사용자 발화.
        block_styles: 본문 블록의 `style_ref` 로 쓸 수 있는 항목명 목록.
            비어 있으면 본문 추가 항목을 **사용자 프롬프트에 넣지 않는다** — 쓸 수 없는
            기능에 목록을 붙여 보여주면 LLM 이 그쪽으로 답을 만든다.
        blocks: 지금까지 쌓인 본문 블록 (`BodyBlock` 또는 dict).

    Raises:
        prompt_loader.PromptRenderError: 템플릿 부재·변수 누락.
    """
    user = render(
        "extract_user.txt",
        field_lines=_joined(_field_lines(fields, current_values)),
        # JSON 은 코드가 만들어 그대로 싣는다 — 템플릿으로 조립하면 따옴표·역슬래시가
        # 든 값에서 깨진다 (extract_user.txt 주석 참고).
        current_values_json=json.dumps(current_values, ensure_ascii=False),
        body_section=_body_section(block_styles, blocks),
        user_message=user_message,
    )
    # 템플릿 전용 시스템 프롬프트가 있으면 그것이 이긴다 (2026-09-15).
    return render(f"{template_prompt_name('extract_system', template_id)}.txt"), user


def _body_section(block_styles: list | None, blocks: list | None) -> str:
    """본문 추가 구획. **쓸 수 없으면 빈 문자열이다.**

    `block_styles` 가 비면 본문 블록을 만들 서식이 없다는 뜻이라 구획을 아예 넣지
    않는다 — 쓸 수 없는 기능에 목록을 붙여 보여주면 LLM 이 그쪽으로 답을 만든다
    (`build_extract_prompts` 의 인자 설명과 같은 근거).

    넣는가 마는가의 판단이 여기 있는 이유는 로더에 `{% if %}` 가 없기 때문이다.
    앞뒤 개행은 이 함수가 붙인다 — `extract_user.txt` 는 `{{ body_section }}` 한 줄로
    받으므로, 빈 문자열일 때 빈 줄이 남지 않아야 한다.
    """
    styles = list(block_styles or ())
    if not styles:
        return ""
    section = render(
        "extract_body.txt",
        style_lines=_joined([f"- {name}" for name in styles]),
        block_lines=_joined(_block_lines(blocks)),
    )
    return f"\n{section}\n"


def build_document_prompts(
    fields: list,
    document: str,
    chunk_index: int = 1,
    chunk_total: int = 1,
    template_id: str = "",
) -> tuple:
    """(system, user) 문서 자동 채움 프롬프트 (2026-08-31 신규).

    Args:
        fields: **아직 비어 있는** 항목의 `FieldSpec` 목록. 채워진 항목을 함께 넘기지
            않는다 — 근거는 `document_user.j2` 머리말에 있다.
        document: 문서 조각 본문.
        chunk_index: 이 조각이 몇 번째인가 (1부터).
        chunk_total: 조각이 모두 몇 개인가.

    Raises:
        prompt_loader.PromptRenderError: 템플릿 부재·변수 누락.

    `build_extract_prompts` 와 **다른 프롬프트를 쓴다.** 그쪽은 "이번 턴 사용자 발화"
    에서 값을 뽑는 지시문이라, 문서를 발화 자리에 넣으면 지움 지시·본문 추가 의도를
    문서 문장에서 찾아내려 든다. 상세는 `document_system.j2` 머리말.
    """
    user = render(
        "document_user.txt",
        # 상태 라벨을 붙이지 않는다 — 여기 들어오는 항목은 전부 미입력이다. `(미입력)`
        # 을 매 줄에 붙이면 토큰만 늘고 구분에 쓰이지도 않는다.
        field_lines=_joined([
            f"- {spec.name}"
            + (f" — 안내문: {spec.guide}" if spec.guide and spec.guide != spec.name else "")
            for spec in fields
        ]),
        document=document,
        chunk_note=_chunk_note(chunk_index, chunk_total),
    )
    # 템플릿 전용 시스템 프롬프트가 있으면 그것이 이긴다 (2026-09-15).
    return render(f"{template_prompt_name('document_system', template_id)}.txt"), user


def _chunk_note(chunk_index: int, chunk_total: int) -> str:
    """조각 표기. **조각이 하나뿐이면 빈 문자열이다.**

    문서가 잘려 보이는 이유를 모델이 알아야 "문서에 없다" 와 "이 조각에 없다" 를
    혼동하지 않는다. 반대로 조각이 하나일 때 이 말을 붙이면 **없는 잘림을 알리는
    셈**이라, 그 판단을 여기서 한다 (`document_user.txt` 머리말과 같은 근거 —
    로더에 `{% if %}` 가 없으므로 코드가 정한다).
    """
    if chunk_total <= 1:
        return ""
    return f" ({chunk_total}개 구간 중 {chunk_index}번째)"
