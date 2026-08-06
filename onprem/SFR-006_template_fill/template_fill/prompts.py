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
    '2) 출력 형식: {"updates": {"항목명": "값", ...}, "clears": ["항목명", ...], '
    '"blocks": [{"style_ref": "항목명", "text": "본문"}], "block_clears": [번호]}\n'
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
    "\n"
    "[본문 추가 — blocks]\n"
    "11) 템플릿 항목에 해당하지 않는 **새로운 본문 내용**을 요청하면 blocks 에 담는다 "
    "(예: '아래에 추진 배경이랑 기대 효과도 써줘'). 항목에 해당하는 내용은 blocks 가 "
    "아니라 updates 에 담는다 — 항목이 우선이다.\n"
    "12) blocks 의 각 항목은 문서에 들어갈 한 덩어리다. text 에는 문서에 그대로 인쇄될 "
    "문장만 쓴다. 소제목과 본문처럼 서식이 다르면 **덩어리를 나눈다.**\n"
    "13) style_ref 는 [본문 서식 목록] 에 있는 이름만 쓴다. 그 항목의 글꼴·크기·여백을 "
    "그대로 물려받는다는 뜻이다. 소제목은 제목 계열, 설명 문장은 본문 계열을 고른다. "
    "마땅한 것이 없으면 style_ref 를 빈 문자열로 둔다.\n"
    "14) text 에 서식 표기(`{16pt, 고딕}`)나 마크다운 기호(`#`, `**`)를 쓰지 않는다. "
    "서식은 style_ref 로만 지정한다.\n"
    "15) 여러 문단이면 text 안에서 줄바꿈(\\n)으로 나눈다. 줄 하나가 문단 하나가 된다.\n"
    "16) 이미 추가된 본문을 빼달라고 하면 그 **번호**를 block_clears 에 담는다 "
    "(예: '2번 문단 빼줘' → [2]). 번호는 [현재 본문 추가 내용] 에 표시된 것이다.\n"
    "17) 사용자가 본문 추가를 요청하지 않았으면 blocks 와 block_clears 를 넣지 않는다.\n"
)


# 018 글다듬이(`text_polish/main.py` `_BASE_SYSTEM_PROMPT`)와 **같은 일**을 시키는 프롬프트다.
# 다른 점은 출력 형식뿐이다 — 018 은 글 전체를 통째로 돌려주지만, 006 은 어느 항목·어느
# 문단의 문구인지 되짚어야 해서 JSON 으로 받는다. 마크다운 구조 유지 지시(018 규칙 3)는
# 여기 없다. 대상이 문서 전체가 아니라 조각이라 지킬 표·제목이 애초에 없다.
TONE_SYSTEM_PROMPT = (
    "당신은 한국어 교정/윤문 전문가입니다. 문서에 들어갈 문구를 지정된 문체(톤)에 맞춰 "
    "다듬습니다.\n"
    "규칙:\n"
    "1) 반드시 JSON 객체 하나만 출력한다. 설명, 인사말, 코드블록 표시(```)를 붙이지 않는다.\n"
    '2) 출력 형식: {"converted": {"항목명": "다듬은 값", ...}}\n'
    "3) 입력에 있는 항목명만 사용한다. 항목을 추가하거나 빼지 않는다.\n"
    "4) 숫자·날짜·금액·고유명사(사람/부서/기관 이름)는 **표기 그대로 유지**한다. "
    "값을 바꾸거나 생략하면 안 된다.\n"
    "5) 내용을 새로 만들지 않는다. 없는 사실을 덧붙이거나 추측하지 않는다.\n"
    "6) 오탈자·띄어쓰기·비문을 교정한다.\n"
    "7) 문체만 바꾼다. 문장의 정보량은 유지한다.\n"
    "8) 문서에 그대로 들어갈 완성된 문구만 담는다 (따옴표·머리기호를 덧붙이지 않는다).\n"
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


def build_extract_user_prompt(
    fields: list,
    current_values: dict,
    user_message: str,
    block_styles: list | None = None,
    blocks: list | None = None,
) -> str:
    """필드 스키마 + 현재 수집 상태 + 사용자 발화를 하나의 프롬프트로 조립한다.

    Args:
        fields: hwpx_fields.FieldSpec 목록.
        current_values: 지금까지 수집된 {필드명: 값}.
        user_message: 이번 턴 사용자 발화.
        block_styles: 본문 블록의 `style_ref` 로 쓸 수 있는 항목명 목록.
            비어 있으면 본문 추가 항목을 프롬프트에 넣지 않는다 — 쓸 수 없는 기능을
            설명하면 LLM 이 그쪽으로 답을 만든다.
        blocks: 지금까지 쌓인 본문 블록 (`BodyBlock` 또는 dict). 번호를 붙여 보여줘야
            사용자가 "2번 빼줘" 라고 말할 수 있다.
    """
    field_lines = []
    for spec in fields:
        status = "채워짐" if (spec.name in current_values or spec.filled) else "미입력"
        # 슬롯은 따옴표 안 문자열이 곧 항목명이자 안내문이라 둘이 같다. 같은 말을 두 번
        # 적으면 프롬프트만 길어지고 모델이 두 항목으로 오해할 여지가 생긴다.
        guide = f" — 안내문: {spec.guide}" if spec.guide and spec.guide != spec.name else ""
        field_lines.append(f"- {spec.name} ({status}){guide}")

    sections = [
        "[필드 목록]\n" + "\n".join(field_lines),
        "[지금까지 수집된 값]\n" + json.dumps(current_values, ensure_ascii=False),
    ]

    if block_styles:
        sections.append("[본문 서식 목록]\n" + "\n".join(f"- {name}" for name in block_styles))
        current_blocks = []
        for index, block in enumerate(blocks or (), start=1):
            text = getattr(block, "text", None)
            style_ref = getattr(block, "style_ref", None)
            if text is None and isinstance(block, dict):
                text, style_ref = block.get("text"), block.get("style_ref")
            style = f" [{style_ref}]" if style_ref else ""
            current_blocks.append(f"{index}.{style} {text}")
        sections.append(
            "[현재 본문 추가 내용]\n" + ("\n".join(current_blocks) if current_blocks else "(없음)")
        )

    sections.append("[사용자 발화]\n" + user_message)
    return "\n\n".join(sections)
