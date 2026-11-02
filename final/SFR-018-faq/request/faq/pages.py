"""첨부 원문의 쪽 표식 — 근거 문장이 몇 쪽인지 코드가 정한다.

첨부용 전처리기(`high_preprocessor.py`)가 청크 머리에 `[[GENON_PAGE n]]` 한 줄을 붙인다.
첨부 봉투(`<doc …>본문</doc>`)에는 레코드의 쪽 필드가 실리지 않아 본문이 유일한 통로다.

**LLM 에는 표식을 걷어 낸 원문을 준다.** 쪽을 LLM 에 묻지 않는다 — 근거 대조
(`EvidenceChecker`)가 근거를 문서에서 찾은 뒤, 그 문장이 든 쪽을 여기서 나눈 구간으로 정한다.
표식이 없는 원문(직접 업로드 · 표식을 끈 등록)은 구간이 비고 쪽 없이 나간다.
"""

import re

_MARKER_RE = re.compile(r"\[\[GENON_PAGE (\d+)\]\][ \t]*\n?")


def split_pages(text: str) -> tuple:
    """→ (표식을 걷은 원문, [(쪽, 그 쪽 글)]).

    첫 표식 앞의 글은 쪽을 모르므로 구간에 넣지 않는다. 첨부가 여럿이면 쪽이 문서마다
    1 부터 다시 시작하고, 구간은 문서 순서 그대로다.
    """
    text = text or ""
    parts: list = []
    segments: list = []
    page = None
    last = 0
    for match in _MARKER_RE.finditer(text):
        piece = text[last:match.start()]
        parts.append(piece)
        if page is not None and piece.strip():
            segments.append((page, piece))
        page = int(match.group(1))
        last = match.end()
    tail = text[last:]
    parts.append(tail)
    if page is not None and tail.strip():
        segments.append((page, tail))
    return "".join(parts), segments
