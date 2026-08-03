"""필드 값 추출 프롬프트 (프롬프트 문자열은 로직과 분리 — 저장소 컨벤션).

LLM 의 역할은 "사용자 발화에서 템플릿 필드에 해당하는 값을 찾아내는 것"
하나로 한정한다. 어떤 필드가 채워졌고 부족한지의 최종 판정은 코드가
결정적으로 수행한다 (LLM 응답을 믿지 않는다 — CLAUDE.md §5).
"""

import json

EXTRACT_SYSTEM_PROMPT = (
    "당신은 문서 템플릿의 빈칸(누름틀)을 채우기 위해 사용자 발화에서 값을 추출하는 "
    "도우미입니다.\n"
    "규칙:\n"
    "1) 반드시 JSON 객체 하나만 출력한다. 설명, 인사말, 코드블록 표시(```)를 붙이지 않는다.\n"
    '2) 출력 형식: {"updates": {"필드명": "값", ...}}\n'
    "3) 필드명은 아래 [필드 목록]에 있는 이름만 사용한다. 목록에 없는 필드명을 만들지 않는다.\n"
    "4) 사용자가 이번 발화에서 실제로 제공한 정보만 담는다. 추측하거나 지어내지 않는다.\n"
    "5) 사용자가 언급하지 않은 필드는 updates 에 포함하지 않는다 (빈 문자열도 넣지 않는다).\n"
    "6) 사용자가 기존 값을 고쳐달라고 하면 고친 값을 updates 에 담는다.\n"
    "7) 값은 문서에 그대로 들어갈 완성된 표현으로 정리한다 (예: 날짜는 '2026. 8. 3.' 형태).\n"
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
