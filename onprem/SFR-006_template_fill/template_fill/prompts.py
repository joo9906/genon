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
        guide = f" — 안내문: {spec.guide}" if spec.guide else ""
        lines.append(f"- {spec.name} ({status}){guide}")
    return lines


async def build_extract_prompts(fields: list, current_values: dict, user_message: str) -> tuple:
    """(system, user) 값 추출 프롬프트.

    Args:
        fields: `hwpx_fields.FieldSpec` 목록.
        current_values: 지금까지 수집된 {항목명: 값}.
        user_message: 이번 턴 사용자 발화.

    Raises:
        prompt_loader.PromptRenderError: 템플릿 부재·변수 누락.
    """
    user = await render(
        "extract_user",
        field_lines=_field_lines(fields, current_values),
        # JSON 은 코드가 만들어 그대로 싣는다 — jinja 로 조립하면 따옴표·역슬래시가
        # 든 값에서 깨진다 (extract_user.j2 주석 참고).
        current_values_json=json.dumps(current_values, ensure_ascii=False),
        user_message=user_message,
    )
    return await render("extract_system"), user


async def build_tone_prompts(targets: dict, tone_label: str, tone_instruction: str) -> tuple:
    """(system, user) 톤 변환 프롬프트.

    Args:
        targets: {항목명: 원본 값} — 서술형으로 판정된 항목만.
        tone_label: 톤 표시 이름 (예: 간결 및 보고체).
        tone_instruction: 톤 프리셋 지시문.

    Raises:
        prompt_loader.PromptRenderError: 템플릿 부재·변수 누락.
    """
    user = await render(
        "tone_user",
        tone_label=tone_label,
        tone_instruction=tone_instruction,
        targets_json=json.dumps(targets, ensure_ascii=False, indent=2),
    )
    return await render("tone_system"), user
