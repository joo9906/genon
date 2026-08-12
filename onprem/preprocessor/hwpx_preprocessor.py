"""GenOS 전처리기(area 05) — hwpx 전용. **이 파일 하나가 등록 단위다.**

## 왜 파일이 하나인가

GenOS 전처리기는 MCP 와 같은 방식으로 등록한다 — 생성·수정 화면에 소스 **파일 하나**를
그대로 올리고, 그 파일이 정의하는 `DocumentProcessor` 를 런타임이 그대로 실행한다
(`onprem/mcp/README.md` 의 MCP 등록 방식과 동일한 제약. `docs/GENOS_RULES.md` §C 의
"전처리기 | 생성·수정 화면의 환경 변수" 항목도 코드서빙의 Git 저장소 방식과는 다른
파일 단위 등록임을 가리킨다). 그래서 이 파일은 **다른 파일을 import 하지 않는다**
(표준 라이브러리 + `lxml` 만) — 패키지로 쪼개면 등록 시점에 나머지 파일이 따라가지
않는다.

## 계약 (`docs/GENOS_RULES.md` §A.4, §F)

- 인자 없이 생성 가능한 `DocumentProcessor`, 비동기 `__call__(request, file_path, **kwargs)`
- 반환은 `list[dict]`. 각 항목에 **`text` 키 필수**(임베딩이 직접 읽는다), 빈 문자열 불가
- `page`·`bbox` 등 **실제로 못 채우는 필드는 지어내지 않고 `None`** 으로 둔다
- 오류는 오류 dict 를 반환하지 않고 **예외를 던진다** (로그에 오류코드 남긴 뒤)

## 지능형 전처리기와 다른 점 — 왜 새로 만들었나

`genos_files/intelligence_processor.py` 의 `DocumentProcessor` 는 hwpx 를 포함한
비-PDF 입력을 **무조건 PDF 로 변환한 뒤** docling 으로 읽는다. 그 변환에서 표 안의
`rowSpan`/`colSpan` 이 깨지고 셀 좌표가 다시 계산되며, 수치가 어느 항목의 값인지가
사라진다(`onprem/preprocessor/README.md` "왜 만들었나" 절, 요구사항 §5). 이 파일은
hwpx 를 PDF 로 바꾸지 않고 **ZIP 안의 `Contents/sectionN.xml` 을 직접 읽어** 문단과
표를 판정한다 — 병합·중첩이 있는 표만 HTML 로 내고, 나머지는 마크다운으로 낸다.
그 대가로 **페이지 번호가 없다**(hwpx 는 흐름 문서라 렌더링 전에는 페이지가 정해지지
않는다) — 지어내지 않고 `None` 으로 둔다. 페이지가 꼭 필요하면 지능형 전처리기(PDF
경로)를 써야 하고, 그건 표가 깨지는 쪽이다. 둘 중 하나를 고르는 것이지 이 파일이
흉내 낼 일이 아니다.

**다른 파일 형식은 다루지 않는다.** hwpx 가 아닌 확장자는 명시적으로 거부한다 —
지능형/첨부용 전처리기가 이미 그 형식들을 처리하고 있으므로 여기서 다시 구현할
이유가 없다.

## GenOS 등록 시 넘기는 값 (`__call__` 의 `**kwargs`)

| 키 | 기본값 | 의미 |
|---|---|---|
| `chunk_size` | 1000 | 청크 최대 문자 수 |
| `chunk_overlap` | 100 | 문단 청크 사이 겹침 문자 수 (표 조각에는 적용 안 됨) |
| `file_name` | `file_path` 의 basename | 검색 결과 출처 표시용 |
| `extra_metadata` | 없음 | 모든 레코드에 병합할 dict (`security_level` 등 배포별 필드) |

값이 없거나 잘못된 타입/범위면 **에러를 내지 않고 기본값으로 떨어진다** — 등록 화면의
파라미터 입력 실수가 전체 재적재를 막으면 안 되기 때문이다. 대신 로그에 남긴다.
"""

from __future__ import annotations

import html as _html
import io
import logging
import os
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from lxml import etree

_log = logging.getLogger(__name__)

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"

_PARA = f"{{{HP_NS}}}p"
_TEXT = f"{{{HP_NS}}}t"
_TBL = f"{{{HP_NS}}}tbl"
_TR = f"{{{HP_NS}}}tr"
_TC = f"{{{HP_NS}}}tc"
_CELL_ADDR = f"{{{HP_NS}}}cellAddr"
_CELL_SPAN = f"{{{HP_NS}}}cellSpan"

_SECTION_ENTRY_RE = re.compile(r"^Contents/section(\d+)\.xml$")

# <hp:t> 안의 \n 은 문단 분리가 아니다 — 그대로 두면 마크다운에서 문단이 갈린다
_NEWLINE_REPLACEMENT = " "
# 셀 안 줄바꿈은 마크다운 표를 깨뜨린다 — 표에서만 <br> 로 바꾼다
_CELL_LINE_BREAK = "<br>"

# 문장 경계 — **구분자를 소비하지 않는 lookbehind 만** 쓴다. `(?<=[다요])\.\s+` 를
# 함께 뒀다가 테스트에 걸렸다: 그쪽은 마침표를 소비해 "완료하였습니다. 본 사업은" 이
# "완료하였습니다 본 사업은" 으로 바뀌었다 — 청킹이 본문 글자를 지운 것이다.
_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s+")

_MARKDOWN_DIVIDER = re.compile(r"^\|[\s\-:|]+\|$")


class HwpxParseError(ValueError):
    """hwpx 해석/처리 실패 — ZIP·XML 손상, 미지원 확장자, 빈 문서 포함.

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다(문서 원문을
    담지 않는다). `docs/GENOS_RULES.md` §A.4 — 전처리기는 오류 dict 를 반환하지 않고
    이 예외를 던진다.
    """


# ---------------------------------------------------------------------------
# 파싱 — hwpx → 구조 블록. **표 규칙의 정본**
#
# 마크다운 한 덩어리로 뭉치지 않는 이유는 청킹이 블록 경계를 알아야 하기 때문이다 —
# 표 한가운데를 자르면 머리행을 잃어 그 청크가 통째로 쓸모없어진다.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Block:
    """문서를 이루는 한 덩어리. **청킹이 이 경계를 지킨다.**

    Attributes:
        kind: `"paragraph"` 또는 `"table"`.
        text: 렌더된 내용. 표는 마크다운 표 또는 HTML 표 문자열이다.
        section: 몇 번째 `Contents/sectionN.xml` 에서 왔나 (0-based).
        table_format: 표일 때만 `"markdown"` / `"html"`. 문단이면 빈 문자열.
    """

    kind: str
    text: str
    section: int
    table_format: str = ""

    @property
    def is_table(self) -> bool:
        return self.kind == "table"


@dataclass(frozen=True)
class Document:
    """파싱 결과.

    문단·표 개수를 함께 내는 이유는 호출부가 **파싱 품질을 로그에 남기기** 위해서다 —
    0개면 파서가 문서를 못 읽은 것이고, 그 상태로 빈 결과가 정상처럼 흘러가면 안 된다.
    """

    blocks: list = field(default_factory=list)
    section_count: int = 0

    @property
    def paragraph_count(self) -> int:
        return sum(1 for block in self.blocks if block.kind == "paragraph")

    @property
    def table_count(self) -> int:
        return sum(1 for block in self.blocks if block.is_table)

    def to_markdown(self, max_chars: int = 0) -> str:
        """블록 사이 빈 줄로 이은 문자열 (디버깅/미리보기용).

        `max_chars` 가 0 보다 크면 그 길이에서 자른다. **잘렸다는 사실은 여기서 알려주지
        않는다** — 호출부가 길이를 비교해 판단한다.
        """
        markdown = "\n\n".join(block.text for block in self.blocks)
        if max_chars > 0 and len(markdown) > max_chars:
            markdown = markdown[:max_chars].rstrip()
        return markdown


def _open(hwpx_bytes: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(hwpx_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise HwpxParseError("hwpx 파일이 아니거나 손상된 파일입니다.") from exc


def _section_order(entry_name: str):
    """본문 섹션이면 섹션 번호, 아니면 None.

    문자열 정렬을 쓰지 않는 이유: `section10` 이 `section2` 앞에 온다. 문단 순서가
    밀리면 청크 순서와 원본 대조가 어긋난다.
    """
    match = _SECTION_ENTRY_RE.match(entry_name)
    return int(match.group(1)) if match else None


def _iter_section_xml(hwpx_bytes: bytes):
    with _open(hwpx_bytes) as archive:
        names = [n for n in archive.namelist() if _section_order(n) is not None]
        for name in sorted(names, key=_section_order):
            yield name, archive.read(name)


def _parse_xml(xml_bytes: bytes):
    try:
        return etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise HwpxParseError("hwpx 본문 XML 을 해석하지 못했습니다.") from exc


def _nearest_para(node):
    """이 노드를 직접 담고 있는 문단. 표 안(hp:tc→hp:subList→hp:p)까지 따라간다."""
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _PARA:
            return parent
        parent = parent.getparent()
    return None


def _own_text(para) -> str:
    """이 문단이 **직접** 가진 텍스트.

    hwpx 표는 hp:p → hp:run → hp:tbl → … → hp:p 로 중첩된다. `para.iter()` 를 그대로
    쓰면 표 전체가 한 문단으로 붙어 마크다운이 통째로 깨진다.
    """
    parts = [
        (node.text or "")
        for node in para.iter(_TEXT)
        if _nearest_para(node) is para
    ]
    text = "".join(parts).replace("\r\n", "\n").replace("\n", _NEWLINE_REPLACEMENT)
    return text.strip()


def _children(elem, tag: str) -> list:
    """직접 자식만 (중첩 표의 tr/tc 가 섞이지 않게)."""
    return [child for child in elem if child.tag == tag]


def _int_attr(elem, name: str, default: int) -> int:
    if elem is None:
        return default
    try:
        return int((elem.get(name) or "").strip())
    except ValueError:
        return default


def _owning_cell(node):
    """이 노드를 담고 있는 **가장 가까운** 셀. 중첩 표를 가르는 기준이다."""
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _TC:
            return parent
        parent = parent.getparent()
    return None


def _cell_parts(tc) -> list:
    """셀 내용을 `("text", str)` 과 `("table", elem)` 으로 **문서 순서대로** 나눈다.

    `tc.iter(hp:p)` 를 그대로 쓰면 **중첩 표 안의 문단까지 딸려온다.** 소유 셀을 따져
    자기 것만 고른다.
    """
    parts = []
    for node in tc.iter():
        if node.tag == _PARA and _owning_cell(node) is tc:
            text = _own_text(node)
            if text:
                parts.append(("text", text))
        elif node.tag == _TBL and _owning_cell(node) is tc:
            parts.append(("table", node))
    return parts


def _cell_text(tc) -> str:
    """마크다운 표용 셀 텍스트. 여러 문단은 <br> 로 잇고 파이프는 이스케이프한다.

    이 경로는 **중첩 표가 없는 표에서만** 쓰인다 (`_needs_html` 이 갈라낸다).
    """
    parts = [value for kind, value in _cell_parts(tc) if kind == "text"]
    return _CELL_LINE_BREAK.join(parts).replace("|", "\\|")


def _cell_html(tc) -> str:
    """HTML 표용 셀 내용. 중첩 표는 `<table>` 로 그대로 살린다."""
    pieces = []
    previous_was_text = False
    for kind, value in _cell_parts(tc):
        if kind == "text":
            if previous_was_text:
                pieces.append(_CELL_LINE_BREAK)
            pieces.append(_html.escape(value, quote=False))
            previous_was_text = True
        else:
            pieces.append("".join(_table_html(value)))
            previous_was_text = False
    return "".join(pieces)


def _table_grid(tbl) -> tuple:
    """hp:tbl → `(anchors, covered, height, width)`.

    `anchors[(row, col)] = (tc, row_span, col_span)` — 셀이 **시작하는** 자리.
    `covered` 는 병합으로 덮인 자리(앵커 제외).
    """
    anchors: dict = {}
    occupied: set = set()
    height = 0
    width = 0

    for row_index, tr in enumerate(_children(tbl, _TR)):
        cursor = 0
        for tc in _children(tr, _TC):
            addr = tc.find(_CELL_ADDR)
            span = tc.find(_CELL_SPAN)
            col_span = _int_attr(span, "colSpan", 1)
            row_span = _int_attr(span, "rowSpan", 1)
            if addr is not None:
                row = _int_attr(addr, "rowAddr", row_index)
                col = _int_attr(addr, "colAddr", cursor)
            else:
                # 좌표가 없는 문서 — 앞 셀 다음 빈 자리를 쓴다
                row, col = row_index, cursor
                while (row, col) in occupied:
                    col += 1
            anchors[(row, col)] = (tc, row_span, col_span)
            for d_row in range(row_span):
                for d_col in range(col_span):
                    occupied.add((row + d_row, col + d_col))
            cursor = col + col_span
            height = max(height, row + row_span)
            width = max(width, col + col_span)

    covered = occupied - set(anchors)
    return anchors, covered, height, width


def _needs_html(tbl) -> bool:
    """마크다운 표로 **표현할 수 없는** 구조인가 (병합 셀 또는 중첩 표)."""
    if any(node is not tbl for node in tbl.iter(_TBL)):
        return True
    for tr in _children(tbl, _TR):
        for tc in _children(tr, _TC):
            span = tc.find(_CELL_SPAN)
            if _int_attr(span, "rowSpan", 1) > 1 or _int_attr(span, "colSpan", 1) > 1:
                return True
    return False


def _table_markdown(tbl) -> list:
    """hp:tbl → 마크다운 표 줄 목록 (병합·중첩이 없는 표 전용)."""
    anchors, _covered, height, width = _table_grid(tbl)
    if not width or not height:
        return []

    lines = []
    for row in range(height):
        values = [
            _cell_text(anchors[(row, col)][0]) if (row, col) in anchors else ""
            for col in range(width)
        ]
        lines.append("| " + " | ".join(value or " " for value in values) + " |")
        if row == 0:
            # hwpx 는 머리행 표시가 없다 — 첫 행을 머리행으로 본다(구조를 지어내지
            # 않는 최소 가정).
            lines.append("|" + "---|" * width)
    return lines


def _table_html(tbl) -> list:
    """hp:tbl → HTML 표 줄 목록. `rowspan`/`colspan`/중첩을 그대로 살린다.

    형태는 지능형 전처리기가 내는 것과 맞춘다(`<table><tbody><tr><td>…`) — 새 형식을
    만드는 것이 아니라 이미 지원되는 형식으로 내는 것이다.
    """
    anchors, covered, height, width = _table_grid(tbl)
    if not width or not height:
        return []

    lines = ["<table><tbody>"]
    for row in range(height):
        cells = []
        for col in range(width):
            if (row, col) in covered:
                continue  # 병합으로 덮인 자리 — td 를 내면 열이 하나 늘어난다
            anchor = anchors.get((row, col))
            if anchor is None:
                cells.append("<td></td>")  # 빈 칸도 자리를 지켜야 한다
                continue
            tc, row_span, col_span = anchor
            attrs = ""
            if row_span > 1:
                attrs += f' rowspan="{row_span}"'
            if col_span > 1:
                attrs += f' colspan="{col_span}"'
            cells.append(f"<td{attrs}>{_cell_html(tc)}</td>")
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines.append("</tbody></table>")
    return lines


def _render_table(tbl) -> list:
    """hp:tbl → 표 줄 목록. **병합·중첩이 있으면 HTML, 아니면 마크다운.**"""
    return _table_html(tbl) if _needs_html(tbl) else _table_markdown(tbl)


def parse(hwpx_bytes: bytes) -> Document:
    """hwpx 본문을 블록 목록으로 판다.

    Args:
        hwpx_bytes: hwpx 파일 바이트.

    Returns:
        Document — 문단과 표가 **문서 순서대로** 담긴다.

    Raises:
        HwpxParseError: ZIP/XML 손상.
    """
    blocks: list = []
    section_count = 0

    for section_index, (_name, xml_bytes) in enumerate(_iter_section_xml(hwpx_bytes)):
        section_count += 1
        root = _parse_xml(xml_bytes)

        # lxml 프록시는 참조가 끊기면 회수되고 **id 가 재사용된다.** 순회 결과를 리스트로
        # 붙들어 둔 뒤에 id 로 묶는다 — 안 그러면 표가 엉뚱한 문단에 붙는다.
        paragraphs = list(root.iter(_PARA))
        tables = list(root.iter(_TBL))
        owned_tables: dict = {}
        for tbl in tables:
            owner = _nearest_para(tbl)
            if owner is not None:
                owned_tables.setdefault(id(owner), []).append(tbl)

        for para in paragraphs:
            # 표 셀·머리말·각주의 문단은 상위 hp:p 안에 중첩된다. 표는 소유 문단에서
            # 따로 렌더링하고, 머리말/각주는 본문 흐름이 아니라 제외한다.
            if _nearest_para(para) is not None:
                continue

            text = _own_text(para)
            if text:
                blocks.append(Block(kind="paragraph", text=text, section=section_index))

            for tbl in owned_tables.get(id(para), ()):
                lines = _render_table(tbl)
                if not lines:
                    continue
                blocks.append(
                    Block(
                        kind="table",
                        text="\n".join(lines),
                        section=section_index,
                        table_format="html" if _needs_html(tbl) else "markdown",
                    )
                )

    return Document(blocks=blocks, section_count=section_count)


# ---------------------------------------------------------------------------
# 청킹 — 블록 → 청크. **표를 쪼개지 않는 것**이 이 부분의 존재 이유다.
#
# 문자 수만 보고 자르는 청커에 문서를 통째로 넣으면 표 한가운데가 잘린다. 뒤 조각은
# 머리행이 없어 검색돼도 쓸모가 없다. 그래서:
#   1. 표는 통째로 한 청크. 상한을 넘으면 머리행을 반복하며 행 단위로 나눈다.
#   2. 문단은 이어 붙이되 문단 중간을 자르지 않는다 — 상한을 넘을 때만 문장 경계로,
#      그래도 안 되면 문자로 자른다.
#   3. 겹침(overlap)은 문단 경계에서만. 표 조각에는 주지 않는다(머리행이 이미 반복된다).
# ---------------------------------------------------------------------------

_DEFAULT_MAX_CHARS = 1000
_DEFAULT_OVERLAP_CHARS = 100
_DEFAULT_MIN_CHARS = 40


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

    `max_chars` 기본값 1000 은 임베딩 모델 컨텍스트에 맞춰 호출부가 조정한다.
    `length` 는 문자 수 기본값 — 폐쇄망에 토크나이저 파일이 없을 수 있어서다. 토큰
    기준이 필요하면 콜러블을 주입한다.
    """

    max_chars: int = _DEFAULT_MAX_CHARS
    overlap_chars: int = _DEFAULT_OVERLAP_CHARS
    # 이보다 짧은 청크는 앞 청크에 붙인다. 한두 단어짜리 청크는 검색 노이즈만 된다.
    min_chars: int = _DEFAULT_MIN_CHARS
    length: object = len

    def __post_init__(self) -> None:
        # 문자 분할 예외 경로(`_split_long_text`)는 매 반복마다 `max_chars - overlap_chars`
        # 만큼 전진한다. `overlap_chars >= max_chars` 면 그 값이 0 이하가 되어 같은
        # 조각을 무한히 반복한다 — GenOS 등록 화면에서 파라미터를 잘못 입력해도
        # 재적재가 멈추지 않게 여기서 막는다(`docs/GENOS_RULES.md` §F 의 "파라미터
        # 최소·최대/범위 밖" 테스트 요건).
        if self.max_chars < 1:
            self.max_chars = _DEFAULT_MAX_CHARS
        if self.overlap_chars < 0 or self.overlap_chars >= self.max_chars:
            self.overlap_chars = max(0, self.max_chars // 4)
        if self.min_chars < 0:
            self.min_chars = 0


def _length(options: ChunkOptions, text: str) -> int:
    return options.length(text)


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


def chunk_blocks(blocks: list, options: ChunkOptions | None = None) -> list:
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


# ---------------------------------------------------------------------------
# VDB 레코드 — 청크 → GenOS 임베딩 입력.
#
# `pydantic` 모델을 만들지 않고 **dict 를 낸다** — `docs/GENOS_RULES.md` §I 가 요구하는
# "JSON 직렬화 가능한 값만 반환" 을 자연히 만족한다.
#
# hwpx 직접 파싱에는 페이지도 bbox 도 없다. 흐름 문서라 렌더링 전에는 페이지가 정해지지
# 않기 때문이다. **틀린 페이지 번호는 없는 것보다 나쁘다** — 0 으로 채우면 1페이지처럼
# 읽힌다. 대신 `i_section`/`n_section`/`source_kind`/`table_part` 를 추가로 싣는다.
# ---------------------------------------------------------------------------


def _counts(text: str) -> dict:
    """`n_char`/`n_word`/`n_line`. 지능형 전처리기의 `GenOSVectorMeta` 와 같은 이름·같은
    세는 법 — 검색 쪽이 그 이름으로 읽으므로 어긋나면 안 된다."""
    return {
        "n_char": len(text),
        "n_word": len(text.split()),
        "n_line": len(text.splitlines()) or 1,
    }


def to_records(
    chunks: list,
    *,
    file_name: str = "",
    file_path: str = "",
    section_count: int = 0,
    reg_date: str = "",
    extra: dict | None = None,
) -> list:
    """청크 목록 → VDB 레코드(dict) 목록.

    Args:
        chunks: `chunk_blocks` 산출물.
        file_name: 원본 파일명 (검색 결과 출처 표시에 쓰인다).
        file_path: 원본 경로.
        section_count: 문서의 섹션 수 (`n_section`).
        reg_date: 적재 일시. 비우면 지금 시각(로컬 타임존)을 쓴다.
        extra: 모든 레코드에 함께 실을 값 (`security_level` 등 배포별 필드).

    Returns:
        `text` 키를 포함한 dict 목록. `i_chunk_on_doc`/`n_chunk_of_doc` 는 여기서
        매긴다 — 호출부가 매기면 문서를 나눠 처리할 때 번호가 겹친다.
    """
    stamp = reg_date or datetime.now(timezone.utc).astimezone().isoformat()
    total = len(chunks)
    records = []

    for index, chunk in enumerate(chunks):
        record = {
            "text": chunk.text,
            **_counts(chunk.text),
            # 페이지 관련은 전부 None — 위 모듈 docstring 참고
            "i_page": None,
            "e_page": None,
            "n_page": None,
            "i_chunk_on_page": None,
            "n_chunk_of_page": None,
            "i_chunk_on_doc": index,
            "n_chunk_of_doc": total,
            "reg_date": stamp,
            "chunk_bboxes": None,
            "media_files": None,
            # ── 이 경로에만 있는 것 ──
            "file_name": file_name,
            "file_path": file_path,
            "i_section": chunk.section,
            "n_section": section_count,
            # 검색 결과를 표로 보여줄지 문단으로 보여줄지 UI 가 고를 근거
            "source_kind": chunk.kind,
        }
        if chunk.table_part is not None:
            part_index, part_total = chunk.table_part
            # 표가 쪼개졌다는 사실을 숨기지 않는다 — 조각만 보고 "표가 이게 전부" 라고
            # 읽으면 안 된다.
            record["table_part"] = part_index
            record["n_table_part"] = part_total
        if extra:
            record.update(extra)
        records.append(record)

    return records


# ---------------------------------------------------------------------------
# GenOS 등록 단위 진입점
# ---------------------------------------------------------------------------

_ALLOWED_LOG_FIELDS = (
    "event",
    "trace_id",
    "request_id",
    "resource_id",
    "status",
    "duration_ms",
    "item_count",
    "upstream_status",
    "error_code",
    "error_type",
)


def _int_kwarg(value: Any, default: int, name: str) -> int:
    """kwargs 로 들어온 값을 int 로. 실패해도 예외를 내지 않고 기본값으로 떨어진다.

    등록 화면 파라미터 입력 실수(빈 문자열, 문자열 숫자, 범위 밖)가 재적재 전체를
    막으면 안 된다 — `ChunkOptions.__post_init__` 이 마지막 안전망으로 한 번 더
    범위를 강제한다.
    """
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        _log.warning(
            "invalid preprocessor parameter, using default",
            extra={"event": "hwpx_preprocess_param_invalid", "error_code": "05-00020003"},
        )
        return default


class DocumentProcessor:
    """hwpx 전용 GenOS 전처리기(area 05).

    `docs/GENOS_RULES.md` §F 계약: 인자 없이 생성 가능해야 하고, `__call__` 은
    비동기이며 `text` 키를 가진 dict 목록을 돌려주거나 예외를 던진다.
    """

    SUPPORTED_EXTENSIONS = (".hwpx",)

    def __init__(self, config_path: str | None = None) -> None:
        # GenOS 는 `DocumentProcessor()` 를 무인자로 호출한다. `config_path` 는 다른
        # 전처리기(`genos_files/intelligence_processor.py` 등)와 생성자 시그니처를
        # 맞추기 위해 받아 두지만, 이 처리기는 설정 파일이 필요 없다 — 조정 가능한
        # 값은 전부 요청 시점의 `__call__(**kwargs)` 로 받는다.
        self._config_path = config_path

    async def __call__(self, request: Any, file_path: str, **kwargs: Any) -> list:
        start = time.monotonic()
        try:
            records = self._process(file_path, **kwargs)
        except HwpxParseError as exc:
            _log.warning(
                "hwpx preprocessing rejected input",
                extra={
                    "event": "hwpx_preprocess_failed",
                    "error_code": "05-00020003",
                    "error_type": type(exc).__name__,
                },
            )
            raise
        except Exception as exc:
            # 예상 못한 실패도 오류 dict 가 아니라 예외로 올린다(§A.4) — 여기서 삼키면
            # 반환값이 `list[dict]` 계약을 지키지 못한 채 조용히 빈 결과로 보일 수 있다.
            _log.warning(
                "hwpx preprocessing failed unexpectedly",
                extra={
                    "event": "hwpx_preprocess_failed",
                    "error_code": "05-00020003",
                    "error_type": type(exc).__name__,
                },
            )
            raise HwpxParseError(f"hwpx 처리 중 예기치 못한 오류가 발생했습니다: {exc}") from exc

        _log.info(
            "hwpx preprocessed",
            extra={
                "event": "hwpx_preprocess_done",
                "item_count": len(records),
                "duration_ms": int((time.monotonic() - start) * 1000),
            },
        )
        return records

    def _process(self, file_path: str, **kwargs: Any) -> list:
        base_name = os.path.basename(file_path)
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise HwpxParseError(
                f"hwpx 전용 전처리기입니다 — 지원하지 않는 확장자입니다: '{ext or base_name}'"
            )

        try:
            with open(file_path, "rb") as fh:
                hwpx_bytes = fh.read()
        except OSError as exc:
            raise HwpxParseError(f"파일을 읽지 못했습니다: {base_name}") from exc

        if not hwpx_bytes:
            raise HwpxParseError(f"빈 파일입니다: {base_name}")

        document = parse(hwpx_bytes)
        if not document.blocks:
            raise HwpxParseError(
                f"본문 내용을 찾지 못했습니다(빈 문서이거나 지원하지 않는 구조): {base_name}"
            )

        options = ChunkOptions(
            max_chars=_int_kwarg(kwargs.get("chunk_size"), _DEFAULT_MAX_CHARS, "chunk_size"),
            overlap_chars=_int_kwarg(
                kwargs.get("chunk_overlap"), _DEFAULT_OVERLAP_CHARS, "chunk_overlap"
            ),
        )
        chunks = chunk_blocks(document.blocks, options)
        if not chunks:
            raise HwpxParseError(f"청크를 만들지 못했습니다: {base_name}")

        extra = kwargs.get("extra_metadata")
        records = to_records(
            chunks,
            file_name=kwargs.get("file_name") or base_name,
            file_path=file_path,
            section_count=document.section_count,
            extra=extra if isinstance(extra, dict) else None,
        )

        for record in records:
            if not record.get("text"):
                # 여기까지 오면 chunk_blocks/to_records 의 불변식이 깨진 것이다 — 조용히
                # 넘기지 않는다(§F: text 키는 필수이며 빈 문자열이면 안 된다).
                raise HwpxParseError("빈 텍스트 청크가 생성되었습니다(내부 오류).")

        return records
