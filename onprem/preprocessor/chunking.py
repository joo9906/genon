"""블록 → 청크. **표를 쪼개지 않는 것**이 이 모듈의 존재 이유다.

`onprem/preprocessor/README.md` 를 먼저 볼 것. 아직 어디에도 배선돼 있지 않다.

## 왜 따로 있나 — 일반 청커에 넣으면 안 되는 이유

문자 수만 보고 자르는 청커에 문서를 통째로 넣으면 **표 한가운데가 잘린다.** 그러면:

```
| 항목 | 2025 | 2026 |
|---|---|---|
| 예산 | 1,200 | 3,400 |      ← 여기서 잘리면
--- 다음 청크 ---
| 인원 | 12 | 15 |            ← 이 숫자가 무엇의 값인지 알 수 없다
```

뒤 청크는 **머리행이 없어 검색돼도 쓸모가 없다.** 표는 그 자체가 의미 단위라
블록 경계를 지켜야 한다.

## 규칙

1. **표는 통째로 한 청크.** 상한을 넘으면 **머리행을 반복하며** 행 단위로 나눈다 —
   나눠도 각 조각이 스스로 해석 가능해야 한다.
2. **문단은 이어 붙이되 문단 중간을 자르지 않는다.** 한 문단이 상한을 넘을 때만
   문장 경계로 자르고, 문장으로도 안 되면 그때 문자로 자른다.
3. **겹침(overlap)은 문단 경계에서만.** 표 조각에는 겹침을 주지 않는다 — 머리행이
   이미 반복되고 있어 중복만 늘어난다.

## 길이 재는 법

기본은 **문자 수**다. 기존 전처리기가 토크나이저를 `char`/HuggingFace 로 갈아 끼울 수
있게 해 뒀으므로 여기도 `length` 콜러블을 주입받는다 — 토크나이저를 쓰려면 그걸 넘긴다.
문자 기본값을 고른 이유는 **폐쇄망에서 토크나이저 파일이 없을 수 있어서**이고, 없을 때
청킹이 통째로 실패하는 것보다 대략적인 길이로라도 도는 편이 낫다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .hwpx import Block

# 문장 경계 — **구분자를 소비하지 않는 lookbehind 만** 쓴다.
#
# 처음에 `(?<=[다요])\.\s+` 를 함께 뒀다가 테스트에 걸렸다. 그쪽은 마침표를 **소비**해서
# `re.split` 이 문장 끝 `.` 를 통째로 지웠다 — "완료하였습니다. 본 사업은" 이
# "완료하였습니다 본 사업은" 이 됐다. 청킹이 본문 글자를 지우는 것이라, 검색 결과에
# 원문과 다른 문장이 뜬다. 게다가 앞 대안이 이미 `…다. ` 를 덮으므로 필요도 없었다.
#
# 완벽할 필요는 없다 — 문단이 상한을 넘긴 **예외 경로**에서만 쓰이고, 여기서 못 자르면
# 아래 문자 분할이 받는다.
_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s+")

_MARKDOWN_DIVIDER = re.compile(r"^\|[\s\-:|]+\|$")


@dataclass(frozen=True)
class Chunk:
    """VDB 에 실릴 한 조각.

    Attributes:
        text: 본문.
        section: 원본 섹션 번호.
        kind: `"paragraph"` / `"table"` — 표 조각인지 알아야 검색 결과 표시가 달라진다.
        table_part: 표를 나눴을 때 `(몇 번째, 총 몇 개)`. 안 나눴으면 `None`.
    """

    text: str
    section: int
    kind: str
    table_part: tuple | None = None


@dataclass
class ChunkOptions:
    """청킹 설정.

    `max_chars` 기본값 1000 은 기존 전처리기의 문자 모드 기본과 같은 자리다.
    임베딩 모델 컨텍스트에 맞춰 호출부가 조정한다.
    """

    max_chars: int = 1000
    overlap_chars: int = 100
    # 이보다 짧은 청크는 앞 청크에 붙인다. 한두 단어짜리 청크는 검색 노이즈만 된다.
    min_chars: int = 40
    length: object = len


def _length(options: ChunkOptions, text: str) -> int:
    return options.length(text)


# ---------------------------------------------------------------------------
# 표
# ---------------------------------------------------------------------------

def _markdown_header(lines: list) -> list:
    """마크다운 표의 머리행 + 구분선. 없으면 빈 목록."""
    if len(lines) >= 2 and _MARKDOWN_DIVIDER.match(lines[1].strip()):
        return lines[:2]
    return []


def _split_markdown_table(text: str, options: ChunkOptions) -> list:
    """마크다운 표를 **머리행을 반복하며** 행 단위로 나눈다."""
    lines = text.splitlines()
    header = _markdown_header(lines)
    body = lines[len(header):]
    if not body:
        return [text]

    parts: list = []
    current: list = []
    for line in body:
        candidate = "\n".join(header + current + [line])
        if current and _length(options, candidate) > options.max_chars:
            parts.append("\n".join(header + current))
            current = [line]
        else:
            current.append(line)
    if current:
        parts.append("\n".join(header + current))
    return parts


def _split_html_table(text: str, options: ChunkOptions) -> list:
    """HTML 표를 `<tr>` 단위로 나눈다. 첫 행을 머리행으로 보고 반복한다.

    **중첩 표가 든 행은 쪼개지 않는다** — 안쪽 `<tr>` 까지 경계로 잡으면 표가 깨진다.
    행 목록은 최상위 `<tr>` 로 시작하는 줄만 센다(렌더러가 행마다 한 줄로 낸다).
    """
    lines = text.splitlines()
    rows = [line for line in lines if line.startswith("<tr>")]
    if len(rows) <= 1:
        return [text]

    header_row = rows[0]
    open_tag, close_tag = "<table><tbody>", "</tbody></table>"

    parts: list = []
    current: list = []
    for row in rows[1:]:
        candidate = "\n".join([open_tag, header_row] + current + [row, close_tag])
        if current and _length(options, candidate) > options.max_chars:
            parts.append("\n".join([open_tag, header_row] + current + [close_tag]))
            current = [row]
        else:
            current.append(row)
    if current:
        parts.append("\n".join([open_tag, header_row] + current + [close_tag]))
    return parts or [text]


def _table_chunks(block: Block, options: ChunkOptions) -> list:
    if _length(options, block.text) <= options.max_chars:
        return [Chunk(text=block.text, section=block.section, kind="table")]

    if block.table_format == "html":
        parts = _split_html_table(block.text, options)
    else:
        parts = _split_markdown_table(block.text, options)

    total = len(parts)
    return [
        Chunk(text=part, section=block.section, kind="table", table_part=(index, total))
        for index, part in enumerate(parts)
    ]


# ---------------------------------------------------------------------------
# 문단
# ---------------------------------------------------------------------------

def _split_long_text(text: str, options: ChunkOptions) -> list:
    """한 문단이 상한을 넘을 때만 쓰는 예외 경로. 문장 → 문자 순으로 내려간다."""
    sentences = [s for s in _SENTENCE_END.split(text) if s.strip()]
    pieces: list = []
    current = ""
    for sentence in sentences or [text]:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and _length(options, candidate) > options.max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)

    # 문장으로도 안 잘리는 경우(한 문장이 통째로 길다) — 마지막 수단으로 문자 분할
    out: list = []
    for piece in pieces:
        while _length(options, piece) > options.max_chars:
            out.append(piece[: options.max_chars])
            piece = piece[options.max_chars - options.overlap_chars:]
        if piece:
            out.append(piece)
    return out


def _overlap_tail(text: str, options: ChunkOptions) -> str:
    """다음 청크 앞에 붙일 꼬리. 문장 경계를 넘지 않게 자른다."""
    if options.overlap_chars <= 0:
        return ""
    tail = text[-options.overlap_chars:]
    match = _SENTENCE_END.search(tail)
    return tail[match.end():] if match else tail


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def chunk_blocks(blocks: list, options: ChunkOptions = None) -> list:
    """블록 목록 → 청크 목록.

    표는 블록 경계를 넘지 않고, 문단은 상한까지 이어 붙인다. 표를 만나면 쌓아 둔 문단을
    **먼저 끊는다** — 문단과 표를 한 청크에 섞으면 표가 문단 꼬리에 붙어 검색 결과가
    읽기 어려워진다.
    """
    options = options or ChunkOptions()
    chunks: list = []
    buffer = ""
    buffer_section = 0

    def flush():
        nonlocal buffer
        if buffer.strip():
            chunks.append(Chunk(text=buffer.strip(), section=buffer_section, kind="paragraph"))
        buffer = ""

    for block in blocks:
        if block.is_table:
            flush()
            chunks.extend(_table_chunks(block, options))
            continue

        pieces = (
            [block.text]
            if _length(options, block.text) <= options.max_chars
            else _split_long_text(block.text, options)
        )
        for piece in pieces:
            candidate = f"{buffer}\n\n{piece}" if buffer else piece
            if buffer and _length(options, candidate) > options.max_chars:
                flush()
                tail = _overlap_tail(chunks[-1].text, options) if chunks else ""
                buffer = f"{tail}\n\n{piece}".strip() if tail else piece
                buffer_section = block.section
            else:
                buffer = candidate
                if not chunks and not buffer_section:
                    buffer_section = block.section

    flush()
    return _merge_tiny(chunks, options)


def _merge_tiny(chunks: list, options: ChunkOptions) -> list:
    """너무 짧은 **문단** 청크를 앞에 붙인다.

    표 청크는 건드리지 않는다 — 짧아도 그 자체가 의미 단위이고, 문단에 붙이면 표가
    문단 꼬리에 섞여 버린다.
    """
    merged: list = []
    for chunk in chunks:
        if (
            chunk.kind == "paragraph"
            and merged
            and merged[-1].kind == "paragraph"
            and _length(options, chunk.text) < options.min_chars
        ):
            previous = merged.pop()
            merged.append(
                Chunk(
                    text=f"{previous.text}\n\n{chunk.text}",
                    section=previous.section,
                    kind="paragraph",
                )
            )
        else:
            merged.append(chunk)
    return merged
