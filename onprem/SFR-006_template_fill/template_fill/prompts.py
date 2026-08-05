"""필드 값 추출 프롬프트 (프롬프트 문자열은 로직과 분리 — 저장소 컨벤션).

LLM 의 역할은 "사용자 발화에서 템플릿 필드에 해당하는 값을 찾아내는 것"
하나로 한정한다. 어떤 필드가 채워졌고 부족한지의 최종 판정은 코드가
결정적으로 수행한다 (LLM 응답을 믿지 않는다 — CLAUDE.md §5).
"""

import json

EXTRACT_SYSTEM_PROMPT = (
    "당신은 문서 템플릿의 항목을 채우고 고치기 위해 사용자 발화에서 값과 지시를 "
    "추출하는 도우미입니다.\n"
    "규칙:\n"
    "1) 반드시 JSON 객체 하나만 출력한다. 설명, 인사말, 코드블록 표시(```)를 붙이지 않는다.\n"
    '2) 출력 형식: {"updates": {"항목명": "값", ...}, "clears": ["항목명", ...]}\n'
    "3) 항목명은 아래 [필드 목록]에 있는 이름만 사용한다. 목록에 없는 이름을 만들지 않는다.\n"
    "4) 사용자가 이번 발화에서 실제로 제공한 정보만 담는다. 추측하거나 지어내지 않는다.\n"
    "5) 사용자가 언급하지 않은 필드는 updates 와 clears 어디에도 넣지 않는다.\n"
    "6) 사용자가 기존 값을 고쳐달라고 하면 고친 값을 updates 에 담는다.\n"
    "7) 사용자가 어떤 항목을 **지우거나 비우라고** 하면 그 항목명을 clears 에 담는다 "
    "(예: '담당자는 지워줘', '배포일 빼줘'). updates 에 빈 문자열을 넣지 않는다.\n"
    "8) 같은 항목을 updates 와 clears 에 동시에 넣지 않는다.\n"
    "9) 값은 문서에 그대로 들어갈 완성된 표현으로 정리한다 (예: 날짜는 '2026. 8. 3.' 형태).\n"
    "10) 값에 항목명과 콜론을 다시 쓰지 않는다 "
    "(예: '제목: 실적 보고' 가 아니라 '실적 보고'). 문서에는 항목명이 이미 적혀 있다.\n"
)


TONE_SYSTEM_PROMPT = (
    "당신은 문서에 들어갈 문구를 지정된 문체(톤)로 다듬는 편집자입니다.\n"
    "규칙:\n"
    "1) 반드시 JSON 객체 하나만 출력한다. 설명, 인사말, 코드블록 표시(```)를 붙이지 않는다.\n"
    '2) 출력 형식: {"converted": {"필드명": "다듬은 값", ...}}\n'
    "3) 입력에 있는 필드명만 사용한다. 필드를 추가하거나 빼지 않는다.\n"
    "4) 숫자·날짜·금액·고유명사(사람/부서/기관 이름)는 **표기 그대로 유지**한다. "
    "값을 바꾸거나 생략하면 안 된다.\n"
    "5) 내용을 새로 만들지 않는다. 없는 사실을 덧붙이거나 추측하지 않는다.\n"
    "6) 문체만 바꾼다. 문장의 정보량은 유지한다.\n"
    "7) 문서에 그대로 들어갈 완성된 문구만 담는다 (따옴표·머리기호를 덧붙이지 않는다).\n"
)


def build_tone_user_prompt(targets: dict, tone_label: str, tone_instruction: str) -> str:
    """톤 변환 대상 필드 값들을 하나의 프롬프트로 조립한다.

    Args:
        targets: {필드명: 원본 값} — 서술형으로 판정된 필드만.
        tone_label: 톤 표시 이름 (예: 간결 및 보고체).
        tone_instruction: 톤 프리셋 지시문.
    """
    return (
        f"[적용할 톤: {tone_label}]\n"
        + tone_instruction
        + "\n\n[다듬을 필드 값]\n"
        + json.dumps(targets, ensure_ascii=False, indent=2)
    )


def build_extract_user_prompt(fields: list, current_values: dict, user_message: str) -> str:
    """필드 스키마 + 현재 수집 상태 + 사용자 발화를 하나의 프롬프트로 조립한다.

    Args:
        fields: hwpx_fields.FieldSpec 목록.
        current_values: 지금까지 수집된 {필드명: 값}.
        user_message: 이번 턴 사용자 발화.
    """
    field_lines = []
    for spec in fields:
        status = "채워짐" if (spec.name in current_values or spec.filled) else "미입력"
        guide = f" — 안내문: {spec.guide}" if spec.guide else ""
        field_lines.append(f"- {spec.name} ({status}){guide}")

    return (
        "[필드 목록]\n"
        + "\n".join(field_lines)
        + "\n\n[지금까지 수집된 값]\n"
        + json.dumps(current_values, ensure_ascii=False)
        + "\n\n[사용자 발화]\n"
        + user_message
    )
