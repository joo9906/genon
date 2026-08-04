"""문단 배열 ↔ LLM 입출력 정렬.

원본 hwpx 에 되쓰려면 "몇 번째 문단이 무엇으로 바뀌었는지"가 정확해야 한다. 그런데
LLM 은 줄을 합치거나 쪼개므로 **줄 순서만 믿을 수 없다.** 그래서 문단마다 번호 표시를
붙여 보내고, 응답에서 그 번호로 되찾는다. 번호가 빠지거나 겹치면 그 문단은 **채택하지
않고 기각 사유를 함께 돌려준다** (LLM 응답을 믿지 않고 검증하는 이 저장소 컨벤션 —
번역의 `validation.py` 와 같은 방식).

표시는 `⟦12⟧` 형태다. 한국어 문서에 거의 등장하지 않는 괄호를 골라 본문과 충돌을 줄였다.
"""

import re

MARKER_TEMPLATE = "⟦{index}⟧"
_MARKER_RE = re.compile(r"⟦(\d+)⟧")

# 프롬프트에 붙이는 지시문. 번호 보존이 되쓰기의 전제이므로 명시적으로 요구한다.
# 다만 지시만 믿지 않고 parse 단계에서 코드가 검증한다.
MARKER_INSTRUCTION = (
    "입력의 각 줄은 ⟦번호⟧ 로 시작하는 문단이다.\n"
    "- 출력도 같은 ⟦번호⟧ 로 시작하는 줄로, 문단 하나당 한 줄로 쓴다.\n"
    "- 번호를 바꾸거나 빼거나 새로 만들지 않는다. 문단을 합치거나 나누지 않는다.\n"
    "- 번호 표시 뒤의 본문만 다듬는다.\n"
)


def build_numbered_source(paragraphs: list) -> str:
    """`[{"index": n, "text": …}]` → `⟦n⟧ 본문` 줄 묶음."""
    lines = []
    for item in paragraphs:
        text = str(item.get("text", "")).replace("\r\n", "\n").replace("\n", " ").strip()
        if not text:
            continue
        lines.append(f"{MARKER_TEMPLATE.format(index=item['index'])} {text}")
    return "\n".join(lines)


def parse_numbered_result(response: str, expected_indexes) -> tuple:
    """`⟦n⟧ 본문` 응답을 `{index: text}` 로 되돌린다.

    Args:
        response: LLM 응답 전문.
        expected_indexes: 원본에 있는 문단 index 집합.

    Returns:
        (`{index: text}` 채택분, 기각 사유 목록). 기각 사유는 사용자·로그에 노출한다.
    """
    expected = set(expected_indexes)
    parsed: dict = {}
    duplicated: list = []
    unknown: list = []

    # 표시 위치로 잘라야 한다 — 본문에 줄바꿈이 섞여도 문단 경계를 잃지 않는다
    matches = list(_MARKER_RE.finditer(response or ""))
    for position, match in enumerate(matches):
        index = int(match.group(1))
        end = matches[position + 1].start() if position + 1 < len(matches) else len(response)
        body = response[match.end() : end].strip()
        if index not in expected:
            unknown.append(index)  # LLM 이 없는 번호를 만들었다
            continue
        if index in parsed:
            duplicated.append(index)  # 같은 번호를 두 번 냈다 — 어느 쪽이 맞는지 알 수 없다
            continue
        if body:
            parsed[index] = body

    missing = sorted(expected - set(parsed))
    rejections = []
    if missing:
        rejections.append(f"응답에 빠진 문단 {len(missing)}개는 원문을 유지합니다.")
    if duplicated:
        rejections.append(f"번호가 중복된 문단 {len(set(duplicated))}개는 채택하지 않았습니다.")
    if unknown:
        rejections.append(f"원문에 없는 번호 {len(set(unknown))}개는 무시했습니다.")
    return parsed, rejections


def merge_display_text(paragraphs: list, polished: dict) -> str:
    """화면에 보여줄 본문. 채택되지 않은 문단은 원문을 그대로 쓴다.

    파일에 들어가는 값과 화면 값이 같아야 하므로, 되쓰기에 넘길 것과 **같은 조합**으로
    만든다.
    """
    lines = []
    for item in paragraphs:
        index = item["index"]
        lines.append(polished.get(index, str(item.get("text", ""))))
    return "\n".join(lines)
