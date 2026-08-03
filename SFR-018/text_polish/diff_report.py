"""다듬기 전/후 변경 내역 생성.

변경 내역을 LLM에게 별도로 물어보지 않고 difflib으로 결정적으로 계산한다.
- LLM 호출 1회 절감 (비용/지연 감소)
- LLM이 변경 내역을 지어내는(할루시네이션) 위험 제거
- 파싱 실패 fallback이 필요 없음

문장 단위로 정렬해 "원문 → 수정문" 쌍 목록을 만든다. 마크다운 구조를 고려해
줄 단위 우선, 줄 안에서는 문장 단위로 비교한다.
"""

import difflib
import re
from typing import List, TypedDict

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)\s+")


class ChangeItem(TypedDict):
    before: str
    after: str


def _split_units(text: str) -> List[str]:
    """마크다운 친화적 비교 단위: 줄 → 문장 순으로 분해."""
    units: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 마크다운 구조 줄(heading, 표, 리스트 마커만 있는 줄)은 통째로 하나의 단위
        if line.startswith(("#", "|", "```")):
            units.append(line)
            continue
        parts = [p.strip() for p in _SENT_SPLIT_RE.split(line) if p.strip()]
        units.extend(parts if parts else [line])
    return units


def build_change_list(original: str, polished: str, max_items: int = 50) -> List[ChangeItem]:
    """원문/수정문을 비교해 실제로 바뀐 문장 쌍만 추출한다.

    Args:
        original: 다듬기 전 텍스트.
        polished: 다듬은 후 텍스트.
        max_items: 응답 크기 제한 (문서가 매우 길 때 result payload 폭주 방지).

    Returns:
        [{"before": ..., "after": ...}, ...] — 변경된 항목만 포함.
    """
    src = _split_units(original)
    dst = _split_units(polished)
    matcher = difflib.SequenceMatcher(a=src, b=dst, autojunk=False)

    changes: List[ChangeItem] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        before = " ".join(src[i1:i2]).strip()
        after = " ".join(dst[j1:j2]).strip()
        if before == after:
            continue
        changes.append({"before": before, "after": after})
        if len(changes) >= max_items:
            break
    return changes


def format_changes_markdown(changes: List[ChangeItem]) -> str:
    """채팅 답변 하단에 붙일 변경 내역 마크다운."""
    if not changes:
        return "\n\n---\n**변경 내역**: 수정된 문장이 없습니다."
    lines = ["\n\n---\n**변경 내역** (총 {}건)".format(len(changes)), ""]
    lines.append("| 원문 | 수정문 |")
    lines.append("|---|---|")
    for item in changes:
        before = item["before"].replace("|", "\\|").replace("\n", " ")
        after = item["after"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {before} | {after} |")
    return "\n".join(lines)
