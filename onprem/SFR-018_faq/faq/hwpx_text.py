"""hwpx 본문을 마크다운으로 직접 뽑는다 (전처리기를 거치지 않는 입력 경로).

## 왜 직접 파싱하는가

docx·pdf 는 전처리기가 마크다운으로 바꿔 주지만 **hwpx 는 직접 파싱해야 한다**
(요구사항 §1). 표를 전처리기에 태우면 안의 수치가 깨지는데, FAQ 는 표에 든
날짜·금액·기한을 그대로 근거로 삼아야 하므로 그 손실을 받을 수 없다.

셀 좌표는 `hp:cellAddr` 이 정본이다. 병합 셀은 **앵커 셀 하나만 존재**하고 이어지는
자리에는 `hp:tc` 가 아예 없다 → 좌표를 무시하고 등장 순서로 채우면 열이 밀린다.

**이 파일은 SFR-006 `hwpx_markdown.py`·SFR-018_translation `hwpx_text.py` 와 같은
규칙의 사본이다** (배포 단위 간 import 금지). 표 격자 규칙을 고칠 때는 셋을 함께 본다.

## 산출물이 곧 FAQ 입력이자 근거 대조 원본이다

여기서 만든 마크다운이 LLM 컨텍스트가 되고, 동시에 `evidence.py` 가 LLM 이 돌려준
근거 문장을 대조하는 원본이 된다. 두 곳이 다른 텍스트를 보면 근거가 있는데도
기각되는 일이 생긴다.

## 경계 (알고 쓰는 한계)

- 머리말/꼬리말(`hp:header`/`footer`)·각주는 본문 흐름이 아니라 제외한다.
- 셀 안에 또 표가 있으면 그 문단 텍스트를 셀 안에 이어 붙인다(구조는 평탄화).
- 마크다운에 rowspan 이 없다. 세로 병합은 앵커 행에만 값을 두고 이어지는 행은 비운다
  (구조를 지어내지 않는다).
- **읽기 전용이다.** FAQ 의 hwpx 다운로드는 원본 되쓰기가 아니라 별도 FAQ 템플릿을
  채우는 경로(`exporters/hwpx_export.py`)라 이 파일과 무관하다.
"""

import io
import re
import zipfile
from dataclasses import dataclass

from lxml import etree

from .hwpx_xml import (
    CELL_ADDR,
    CELL_SPAN,
    PARA,
    TBL,
    TC,
    TR,
    nearest_para,
    own_text_nodes,
)

# 본문은 Contents/sectionN.xml 이다. header.xml 등은 서식 정의라 본문이 아니다.
_SECTION_ENTRY_RE = re.compile(r"^Contents/section(\d+)\.xml$")

# <hp:t> 안의 \n 은 문단 분리가 아니다 — 그대로 두면 마크다운에서 문단이 갈린다
_NEWLINE_REPLACEMENT = " "
# 셀 안 줄바꿈은 마크다운 표를 깨뜨린다 — 표에서만 <br> 로 바꾼다
_CELL_LINE_BREAK = "<br>"


class HwpxParseError(ValueError):
    """hwpx 해석 실패 (ZIP/XML 손상).

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다.
    호출부가 사용자 노출 오류로 그대로 쓴다 (3.8절).
    """


@dataclass(frozen=True)
class HwpxDocument:
    markdown: str
    paragraph_count: int
    table_count: int


def _open(hwpx_bytes: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(hwpx_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise HwpxParseError("hwpx 파일이 아니거나 손상된 파일입니다.") from exc


def _section_order(entry_name: str):
    """본문 섹션이면 섹션 번호, 아니면 None.

    문자열 정렬을 쓰지 않는 이유: `section10` 이 `section2` 앞에 온다. 문단 순서가
    밀리면 번역 결과와 원본 대조(하이라이트)가 어긋난다.
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


def _own_text(para) -> str:
    """이 문단이 **직접** 가진 텍스트 (중첩 문단 제외 규칙은 `hwpx_xml` 에 있다)."""
    parts = [(node.text or "") for node in own_text_nodes(para)]
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


def _cell_text(tc) -> str:
    """셀 텍스트. 여러 문단은 <br> 로 잇고 파이프는 이스케이프한다.

    파이프를 escape 하지 않으면 셀 내용이 열 경계로 읽혀 표가 밀린다.
    """
    parts = [text for para in tc.iter(PARA) if (text := _own_text(para))]
    return _CELL_LINE_BREAK.join(parts).replace("|", "\\|")


def _render_table(tbl) -> list:
    """hp:tbl → 마크다운 표 줄 목록. 셀 좌표(cellAddr)를 정본으로 격자를 만든다."""
    cells: dict = {}
    occupied: set = set()
    height = 0
    width = 0

    for row_index, tr in enumerate(_children(tbl, TR)):
        cursor = 0
        for tc in _children(tr, TC):
            addr = tc.find(CELL_ADDR)
            span = tc.find(CELL_SPAN)
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
            cells[(row, col)] = _cell_text(tc)
            for d_row in range(row_span):
                for d_col in range(col_span):
                    occupied.add((row + d_row, col + d_col))
            cursor = col + col_span
            height = max(height, row + row_span)
            width = max(width, col + col_span)

    if not width or not height:
        return []

    lines = []
    for row in range(height):
        values = [cells.get((row, col), "") for col in range(width)]
        lines.append("| " + " | ".join(value or " " for value in values) + " |")
        if row == 0:
            # 마크다운 표는 구분선이 필수다. hwpx 는 머리행 표시가 없으므로 첫 행을
            # 머리행으로 본다 (구조를 지어내지 않는 최소 가정).
            lines.append("|" + "---|" * width)
    return lines


def to_markdown(hwpx_bytes: bytes, max_chars: int = 0) -> HwpxDocument:
    """hwpx 본문을 마크다운 문자열로 변환한다.

    Args:
        hwpx_bytes: 업로드된 hwpx 바이트.
        max_chars: 0 보다 크면 그 길이에서 자른다 (LLM 예산 보호는 호출부 책임이지만,
            파싱 산출물 자체를 무제한으로 메모리에 들고 있지 않기 위한 상한).

    Raises:
        HwpxParseError: ZIP/XML 손상.
    """
    blocks: list = []
    paragraph_count = 0
    table_count = 0

    for _, xml_bytes in _iter_section_xml(hwpx_bytes):
        root = _parse_xml(xml_bytes)
        # lxml 프록시는 참조가 끊기면 회수되고 id 가 재사용된다 — 순회 결과를 리스트로
        # 붙들어 둔 뒤에 id 로 묶는다 (SFR-006 에서 항목 순서가 뒤섞이는 버그로 드러난 함정).
        paragraphs = list(root.iter(PARA))
        tables = list(root.iter(TBL))
        owned_tables: dict = {}
        for tbl in tables:
            owner = nearest_para(tbl)
            if owner is not None:
                owned_tables.setdefault(id(owner), []).append(tbl)

        for para in paragraphs:
            # 표 셀·머리말·각주의 문단은 상위 hp:p 안에 중첩된다. 표는 소유 문단에서
            # 따로 렌더링하고, 머리말/각주는 본문 흐름이 아니라 제외한다.
            if nearest_para(para) is not None:
                continue
            text = _own_text(para)
            if text:
                paragraph_count += 1
                blocks.append(text)
            for tbl in owned_tables.get(id(para), ()):
                lines = _render_table(tbl)
                if lines:
                    table_count += 1
                    blocks.append("\n".join(lines))

    markdown = "\n\n".join(blocks)
    if max_chars > 0 and len(markdown) > max_chars:
        markdown = markdown[:max_chars].rstrip()
    return HwpxDocument(
        markdown=markdown,
        paragraph_count=paragraph_count,
        table_count=table_count,
    )
