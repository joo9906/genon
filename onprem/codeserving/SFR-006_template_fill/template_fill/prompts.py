"""프롬프트 조립 — 문구는 `onprem/prompt/SFR-006_template_fill/*.j2` 에 있다.

이 파일은 **템플릿에 넘길 변수를 정리하는 역할만** 한다. 문구를 코드 밖으로 뺀 이유는
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

from .prompt_loader import render


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


def build_extract_prompts(
    fields: list,
    current_values: dict,
    user_message: str,
    block_styles: list | None = None,
    blocks: list | None = None,
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
        "extract_user.j2",
        field_lines=_field_lines(fields, current_values),
        # JSON 은 코드가 만들어 그대로 싣는다 — jinja 로 조립하면 따옴표·역슬래시가
        # 든 값에서 깨진다 (extract_user.j2 주석 참고).
        current_values_json=json.dumps(current_values, ensure_ascii=False),
        block_styles=list(block_styles or ()),
        block_lines=_block_lines(blocks),
        user_message=user_message,
    )
    return render("extract_system.j2"), user


def build_document_prompts(
    fields: list,
    document: str,
    chunk_index: int = 1,
    chunk_total: int = 1,
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
        "document_user.j2",
        # 상태 라벨을 붙이지 않는다 — 여기 들어오는 항목은 전부 미입력이다. `(미입력)`
        # 을 매 줄에 붙이면 토큰만 늘고 구분에 쓰이지도 않는다.
        field_lines=[
            f"- {spec.name}"
            + (f" — 안내문: {spec.guide}" if spec.guide and spec.guide != spec.name else "")
            for spec in fields
        ],
        document=document,
        chunk_index=chunk_index,
        chunk_total=chunk_total,
    )
    return render("document_system.j2"), user
