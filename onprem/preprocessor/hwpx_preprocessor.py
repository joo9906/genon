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
표를 판정한다 — 표는 **언제나 한 줄짜리 HTML** 로 낸다(`_render_table` 이 이유를 적는다:
검색 결과가 LLM 에게 갈 때 개행이 뭉개져 마크다운 표는 표가 아니게 된다).
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
| `outline_mode` | `auto` | 조문 위계(편/장/절/관/조/항/호/목) — `auto`/`statute`/`off` |
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
from dataclasses import dataclass, field, replace
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
_POS = f"{{{HP_NS}}}pos"

_SECTION_ENTRY_RE = re.compile(r"^Contents/section(\d+)\.xml$")

# <hp:t> 안의 \n 은 문단 분리가 아니다 — 그대로 두면 마크다운에서 문단이 갈린다
_NEWLINE_REPLACEMENT = " "
# 셀 안 줄바꿈은 표 한 칸을 여러 줄로 만든다 — 표에서만 <br> 로 바꾼다
_CELL_LINE_BREAK = "<br>"

# 문장 경계 — **구분자를 소비하지 않는 lookbehind 만** 쓴다. `(?<=[다요])\.\s+` 를
# 함께 뒀다가 테스트에 걸렸다: 그쪽은 마침표를 소비해 "완료하였습니다. 본 사업은" 이
# "완료하였습니다 본 사업은" 으로 바뀌었다 — 청킹이 본문 글자를 지운 것이다.
_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s+")

# ── 조문 위계 (편/장/절/관/조/항/호/목) ────────────────────────────────────────
#
# **이 사다리는 추측이 아니라 문법이다.** 법령·행정규칙의 조문 구조는 발행처가 정한
# 표기(조 → 항 `①` → 호 `1.` → 목 `가.`)를 따르므로, 마크다운 표 문법이나 hwpx 슬롯
# 문법과 같은 성격의 결정적 규칙으로 적는다. LLM 에 물을 이유가 없고, 물으면 같은
# 문서가 적재할 때마다 다른 청크로 갈릴 수 있다(청크 경계는 결정적이어야 한다).
#
# **다만 "어느 사다리인가" 는 결정적이지 않다.** 같은 `1.` 이 법령에서는 호(조 아래
# 3단계)이고 공문서에서는 최상위 항목이다. 그래서 사다리를 문서에 무조건 적용하지 않고
# `outline_mode="auto"` 가 조문 표기를 실제로 세어 본 뒤에만 켠다 — 아래 참고.
_OUTLINE_OFF = "off"
_OUTLINE_AUTO = "auto"
_OUTLINE_STATUTE = "statute"
_OUTLINE_MODES = (_OUTLINE_AUTO, _OUTLINE_STATUTE, _OUTLINE_OFF)

# 조 = 5. 청킹은 **이 레벨 이하(편·장·절·관·조)에서만 끊는다** — 항·호·목에서 끊으면
# 조문 하나가 여러 청크로 흩어져 "제5조가 무엇을 정하는가" 에 답할 수 없게 된다.
_LEVEL_ARTICLE = 5

# 제목 줄기(`outline_path`)에는 **구조 제목까지만** 담는다. 항·호·목은 제목이 아니라
# 조문의 **내용**이라, 줄기에 넣으면 머리말이 본문 문장을 통째로 되풀이한다
# (`제5조(목적) > ① 직원은 성실히 근무하여야 한다. > 1. 근무시간을 준수할 것 > …`).
_LEVEL_PATH_MAX = _LEVEL_ARTICLE

# 목(目) 기호는 가나다 순서다. `[가-힣]\.` 로 넓게 잡으면 "완료.", "사업." 같은 본문
# 문단이 목으로 승격된다.
_MOK_LETTERS = "가나다라마바사아자차카타파하"

# 인용과 제목을 가르는 것은 **뒤에 오는 글자**다. `제5조(목적)` 은 제목이고
# `제5조에 따라` 는 본문 인용이다 — 조사(가-힣)가 붙으면 제목이 아니다.
_NOT_CITED = r"(?![가-힣])"

_STATUTE_RULES = (
    (1, re.compile(rf"^제\s*\d+\s*편{_NOT_CITED}")),
    (2, re.compile(rf"^제\s*\d+\s*장{_NOT_CITED}")),
    (2, re.compile(r"^부\s*칙(?=[\s(<[]|$)")),
    (3, re.compile(rf"^제\s*\d+\s*절{_NOT_CITED}")),
    (4, re.compile(rf"^제\s*\d+\s*관{_NOT_CITED}")),
    # 가지조문(`제5조의2`)까지 한 조로 본다. `제5조의무` 는 `의` 뒤에 숫자가 없어
    # 그룹이 안 붙고 `_NOT_CITED` 가 막는다.
    (_LEVEL_ARTICLE, re.compile(rf"^제\s*\d+\s*조(?:\s*의\s*\d+)?{_NOT_CITED}")),
    (6, re.compile(r"^[①-⑳]")),          # 항 ①~⑳
    # 호는 한두 자리로 제한한다 — `2026. 8. 13.` 같은 날짜 문단이 1호로 잡히지 않게.
    (7, re.compile(r"^\d{1,2}\.(?=\s)")),
    (8, re.compile(rf"^[{_MOK_LETTERS}]\.(?=\s)")),
)

_ARTICLE_RE = next(pattern for level, pattern in _STATUTE_RULES if level == _LEVEL_ARTICLE)

# auto 판정 문턱. 1개면 본문에 조문을 한 번 인용한 일반 문서일 수 있다 — 2개부터
# 조문 문서로 본다. **못 미치면 위계를 아예 끄고** 기존 동작 그대로 간다: 일반 문서에
# 사다리를 걸면 `1.` 목록이 전부 제목으로 승격돼 청킹이 지금보다 나빠진다.
_AUTO_ARTICLE_MIN = 2

# 위계 이름표가 이보다 길면 표기 + 괄호 제목까지만 남긴다. 조문 제목은 본문과 한 문단에
# 붙어 오는 일이 흔하다 (`제5조(목적) 이 규칙은 …`).
_LABEL_MAX_CHARS = 40

# 청크 머리말 구분자. 쉼표로 이으면 본문 문장과 구분이 안 된다.
_OUTLINE_SEPARATOR = " > "


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
        text: 렌더된 내용. 표는 **한 줄짜리 HTML 표**다 (`_render_table` 이 이유를 적는다).
        section: 몇 번째 `Contents/sectionN.xml` 에서 왔나 (0-based).
        outline_level: 조문 위계 (1 편 … 5 조 … 8 목). **0 이면 제목이 아니라 본문**이다.
        outline_path: 이 블록을 감싸는 제목 줄기 (`("제2장 총칙", "제5조(목적)")`).
            제목 블록이면 자기 이름표가 마지막 원소다. 표 블록도 줄기를 물려받는다 —
            표만 검색돼 나왔을 때 어느 조의 표인지 알아야 한다.

    `parse()` 는 이 둘을 채우지 않는다(XML 에 없는 정보다). `annotate_outline()` 이
    채운다 — 파싱과 위계 판정을 갈라 둬야 위계를 꺼도 파싱 결과가 같다.
    """

    kind: str
    text: str
    section: int
    outline_level: int = 0
    outline_path: tuple = ()

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
    쓰면 표 전체가 한 문단으로 붙어 표가 통째로 깨진다.
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


def _table_html(tbl) -> list:
    """hp:tbl → HTML 표 줄 목록. `rowspan`/`colspan`/중첩을 그대로 살린다.

    형태는 지능형 전처리기가 내는 것과 맞춘다(`<table><tbody><tr><th>…`) — 새 형식을
    만드는 것이 아니라 이미 지원되는 형식으로 내는 것이다.

    **첫 행은 `<th>` 다.** 마크다운 표에서 그 일을 하던 구분선(`|---|`)이 없어졌으므로
    (→ `_render_table`) 머리행 표시를 태그가 맡는다. 조각마다 머리행을 반복하는 것이
    이 분할의 요점인데, 표시가 없으면 그 반복이 데이터 행처럼 읽힌다.
    """
    anchors, covered, height, width = _table_grid(tbl)
    if not width or not height:
        return []

    lines = ["<table><tbody>"]
    for row in range(height):
        # hwpx 는 머리행 표시가 없다 — 첫 행을 머리행으로 본다(구조를 지어내지 않는
        # 최소 가정. 마크다운 표에서 구분선을 첫 행 뒤에 넣던 것과 같은 판정이다).
        tag = "th" if row == 0 else "td"
        cells = []
        for col in range(width):
            if (row, col) in covered:
                continue  # 병합으로 덮인 자리 — 칸을 내면 열이 하나 늘어난다
            anchor = anchors.get((row, col))
            if anchor is None:
                cells.append(f"<{tag}></{tag}>")  # 빈 칸도 자리를 지켜야 한다
                continue
            tc, row_span, col_span = anchor
            attrs = ""
            if row_span > 1:
                attrs += f' rowspan="{row_span}"'
            if col_span > 1:
                attrs += f' colspan="{col_span}"'
            cells.append(f"<{tag}{attrs}>{_cell_html(tc)}</{tag}>")
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines.append("</tbody></table>")
    return lines


def _render_table(tbl) -> list:
    """hp:tbl → 표 줄 목록. **언제나 HTML 이다.**

    ## 왜 마크다운을 안 쓰나 (2026-08-13 변경)

    예전에는 병합·중첩이 있는 표만 HTML 로 내고 나머지는 마크다운으로 냈다 — 잃을 게
    없는 표까지 바꾸면 토큰만 늘고 사람이 읽기 나쁘다는 이유였다. 실제 검색 결과를 받아
    보고 뒤집었다: **검색 결과가 LLM 에게 갈 때 개행이 공백으로 뭉개진다.**

        | 순번 | … | 수용<br>여부 | |---|---|---| | 3 | 차기 변제금 …

    마크다운 표는 **행 경계가 개행뿐**이라 이 한 줄에서 표가 아니게 된다 — 구분선이 본문
    줄에 붙고 7열이 뒤섞인다. 수치는 남지만 그 수치가 무엇의 값인지 사라지는 것이고,
    그건 애초에 이 전처리기를 만든 이유(요구사항 §5 "표 깨짐")와 같은 실패다.

    HTML 표는 **행·칸 경계가 태그**라 개행이 없어도 구조가 그대로다. 새 형식도 아니다 —
    지능형 전처리기가 이미 한 줄 HTML 표를 내고 있어 검색·프롬프트 경로가 그 형태를
    이미 받는다. 대가는 토큰 증가(이 문서에서 약 10%)이고, 표가 아니게 되는 것보다
    낫다는 판단이다.
    """
    return _table_html(tbl)


def _vertical_key(tbl):
    """같은 문단에 매달린 개체의 **세로 위치**. 비교할 수 없으면 `None`.

    hwpx 의 표·상자는 문단에 매달리고(anchor), **XML 순서가 곧 화면 순서는 아니다.**
    실물에서 드러났다: 제목상자(1칸 표, `treatAsChar="1"`)와 본문 표
    (`treatAsChar="0"`, `vertOffset="5940"`)가 **같은 문단**에 매달려 있는데 XML 에는
    본문 표가 먼저 있어, 문서 제목이 표 **뒤로** 밀렸다. 그러면 표 조각 어디에도
    제목이 없고, 마지막 청크에서 제목·날짜·서명이 한 덩어리가 된다.

    - `hp:pos` 가 없으면 흐름 그대로 → 0
    - `treatAsChar="1"`(글자처럼 취급)은 문단 자리에 그대로 온다 → 0
    - 그 외에는 `vertOffset`. 단 **기준이 문단(`vertRelTo="PARA"`)일 때만** 쓴다 —
      페이지·단 기준 오프셋은 문단 기준 값과 크기를 비교할 수 없다(0 으로 뭉개면
      순서를 지어내는 셈이라 `None` 을 돌려 정렬 자체를 포기한다).
    """
    found = _children(tbl, _POS)
    if not found:
        return 0
    pos = found[0]
    if pos.get("treatAsChar") == "1":
        return 0
    if (pos.get("vertRelTo") or "PARA") != "PARA":
        return None
    return _int_attr(pos, "vertOffset", 0)


def _in_visual_order(tables: list) -> list:
    """한 문단에 매달린 개체들을 화면에 놓이는 순서로. **판정 불가면 문서 순서 그대로.**

    개체가 하나뿐이면(대부분의 문서) 손대지 않는다 — 이 정렬은 한 문단이 둘 이상을
    물고 있을 때만 의미가 있다.
    """
    if len(tables) < 2:
        return tables
    keys = [_vertical_key(tbl) for tbl in tables]
    if any(key is None for key in keys):
        return tables
    # 색인을 두 번째 키로 둬서 **동점이면 문서 순서**를 지킨다(그리고 lxml 프록시끼리
    # 비교되는 일이 없다 — 색인이 유일하므로 튜플 비교가 거기서 끝난다).
    order = sorted(zip(keys, range(len(tables)), tables), key=lambda item: item[:2])
    return [tbl for _key, _index, tbl in order]


def _boxed_text(tbl):
    """칸이 하나뿐인 표는 **표가 아니라 제목·강조 상자다** → 그 안의 글을 돌려준다.

    hwpx 는 제목상자·박스형 강조를 1칸 표로 만드는 일이 흔한데, 그대로 표로 내면 본문
    행이 0개인 퇴화된 표가 된다:

        | 『…』 사업 기술협상서 |
        |---|

    글자를 잃지는 않지만(머리행에 남는다) 표가 아닌 것이 표로 검색되고, 구분선이
    노이즈로 임베딩되며, 조문 위계 판정도 지나쳐 간다. 문단으로 내면 셋 다 해소된다.

    Returns:
        문단 텍스트. 칸이 하나가 아니거나 **중첩 표가 들어 있으면 `None`** — 후자는
        문단으로 펴면 안쪽 표를 통째로 잃는다.
    """
    anchors, _covered, _height, _width = _table_grid(tbl)
    if len(anchors) != 1:
        return None

    (tc, _row_span, _col_span), = anchors.values()
    parts = _cell_parts(tc)
    if any(kind == "table" for kind, _value in parts):
        return None
    # 셀 안 여러 문단은 진짜 줄바꿈으로 잇는다 — `<br>` 은 표 한 칸을 지키려고
    # 쓰는 것이라, 표를 벗어난 이 경로에서는 글자로 보일 뿐이다.
    return "\n".join(value for kind, value in parts if kind == "text").strip()


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

            # XML 순서가 아니라 **화면 순서**로 낸다 — 같은 문단에 제목상자와 본문 표가
            # 함께 매달려 있으면 XML 에서는 표가 먼저 나오는 일이 있다(`_in_visual_order`).
            for tbl in _in_visual_order(owned_tables.get(id(para), [])):
                boxed = _boxed_text(tbl)
                if boxed is not None:
                    # 빈 상자는 아예 내지 않는다 — 표로 내면 `|  |` / `|---|` 두 줄이
                    # 남아 글자 없는 청크가 생긴다.
                    if boxed:
                        blocks.append(
                            Block(kind="paragraph", text=boxed, section=section_index)
                        )
                    continue

                lines = _render_table(tbl)
                if not lines:
                    continue
                blocks.append(
                    Block(kind="table", text="\n".join(lines), section=section_index)
                )

    return Document(blocks=blocks, section_count=section_count)


# ---------------------------------------------------------------------------
# 조문 위계 판정 — 블록 → 블록(+`outline_level`/`outline_path`)
#
# **왜 파싱과 갈라 두나.** hwpx XML 에는 "이 문단이 제5조다" 라는 정보가 없다. 조문
# 위계는 텍스트 표기에서 읽어내는 별개의 층이고, 껐을 때 파싱 결과가 그대로여야
# 위계 규칙을 고쳐도 표·문단 경계는 흔들리지 않는다.
#
# **왜 레이아웃 모델을 쓰지 않나.** 지능형 전처리기는 PDF 로 변환한 뒤 레이아웃(비전)
# 모델이 매긴 `SECTION_HEADER`/`TITLE` 라벨로 구조를 잡는데, 그 라벨은 깊이가 0/1 로
# 평탄화돼 편–장–조–항 4단 위계를 표현하지 못한다. 이 경로는 hwpx 를 직접 읽어 문단
# 텍스트가 그대로 있으므로 표기에서 위계를 바로 읽을 수 있다.
# ---------------------------------------------------------------------------


def _match_statute(text: str) -> tuple:
    """문단 첫머리에서 조문 표기를 찾는다. → `(레벨, 이름표)`. 못 찾으면 `(0, "")`.

    **첫머리에서만** 본다. 본문 가운데의 `… 제5조에 따라 …` 는 인용이지 제목이 아니고,
    문단 전체를 훑으면 그 인용이 새 조를 여는 것처럼 보여 청크가 엉뚱하게 끊긴다.
    """
    stripped = text.strip()
    if not stripped:
        return 0, ""
    for level, pattern in _STATUTE_RULES:
        match = pattern.match(stripped)
        if match:
            return level, _outline_label(stripped, match)
    return 0, ""


def _outline_label(stripped: str, match) -> str:
    """제목 줄기에 실을 짧은 이름표.

    조문 제목은 본문과 한 문단에 붙어 오는 일이 흔하다(`제5조(목적) 이 규칙은 …`).
    그대로 쓰면 청크 머리말이 본문을 통째로 되풀이한다. 그래서 순서가 이렇다:

    1. **괄호 제목이 있으면 길이와 무관하게 거기까지** — `제5조(목적)`. 조문 제목의
       정식 표기라, 짧다는 이유로 본문까지 이름표에 넣으면 조마다 이름표 모양이 달라진다.
    2. 괄호가 없고 문단이 짧으면 그대로 (`제2장 총칙` — 제목 줄 하나가 곧 이름표다).
    3. 둘 다 아니면 표기만 (`제5조`).
    """
    marker = match.group(0).strip()
    rest = stripped[match.end():].lstrip()
    if rest.startswith("("):
        close = rest.find(")")
        if close != -1:
            return f"{marker}{rest[:close + 1]}"
    if len(stripped) <= _LABEL_MAX_CHARS:
        return stripped
    return marker or stripped[:_LABEL_MAX_CHARS].rstrip()


def _detect_outline_mode(blocks: list) -> str:
    """`auto` 판정 — 조문 표기를 실제로 세어 본다.

    **일반 문서에 사다리를 걸면 지금보다 나빠진다.** `1.`·`가.` 로 시작하는 평범한
    목록이 전부 제목으로 승격돼 청크가 잘게 부서지기 때문이다. 그래서 조 표기가
    `_AUTO_ARTICLE_MIN` 개 이상일 때만 켠다 — `제N조` 는 목록 기호로 쓰이지 않으므로
    이 판정은 오탐이 사실상 없다.
    """
    hits = 0
    for block in blocks:
        if block.kind != "paragraph":
            continue
        if _ARTICLE_RE.match(block.text.strip()):
            hits += 1
            if hits >= _AUTO_ARTICLE_MIN:
                return _OUTLINE_STATUTE
    return _OUTLINE_OFF


def annotate_outline(blocks: list, mode: str = _OUTLINE_AUTO) -> list:
    """블록에 조문 위계를 매긴다. 원본은 건드리지 않고 새 목록을 돌려준다.

    Args:
        blocks: `parse()` 산출물.
        mode: `"auto"`(기본 — 조문 문서로 보일 때만 켠다) / `"statute"`(무조건 켠다) /
            `"off"`(끈다). 알 수 없는 값은 경고 후 `"auto"` 로 떨어진다 — 등록 화면
            오타가 재적재를 막으면 안 된다.

    Returns:
        `outline_level`/`outline_path` 가 채워진 블록 목록. `mode` 가 꺼지면 입력과
        같은 내용(위계 필드는 기본값)이다.
    """
    if mode not in _OUTLINE_MODES:
        _log.warning(
            "invalid preprocessor parameter, using default",
            extra={"event": "hwpx_preprocess_param_invalid", "error_code": "05-00020003"},
        )
        mode = _OUTLINE_AUTO
    if mode == _OUTLINE_AUTO:
        mode = _detect_outline_mode(blocks)
    if mode == _OUTLINE_OFF:
        return list(blocks)

    trail: dict = {}
    annotated: list = []
    for block in blocks:
        level, label = _match_statute(block.text) if block.kind == "paragraph" else (0, "")
        if level:
            # 같은 레벨이거나 더 깊은 줄기는 여기서 닫힌다. 안 닫으면 제3조의 항이
            # 제5조 청크의 머리말에 남는다.
            trail = {depth: name for depth, name in trail.items() if depth < level}
            if level <= _LEVEL_PATH_MAX:
                trail[level] = label
        annotated.append(
            replace(
                block,
                outline_level=level,
                outline_path=tuple(trail[depth] for depth in sorted(trail)),
            )
        )
    return annotated


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

# 표 바로 앞 문단을 그 표의 제목으로 볼 수 있는 최대 길이. 넘으면 제목이 아니라 본문
# 문단이라고 본다 — 본문을 표 조각마다 반복하면 임베딩이 본문 쪽으로 끌려간다.
_TABLE_TITLE_MAX_CHARS = 60
# 상한을 넘는 행을 쪼갤 때, 이 길이 이하의 셀은 **조각마다 통째로 반복**한다.
# 순번·담당·수용여부처럼 짧은 칸이 여기 해당하고, 그게 있어야 조각이 혼자 해석된다.
_ROW_ANCHOR_MAX_CHARS = 80
# `<tr>` 한 줄에서 칸을 뜯어낼 때. 속성을 **그대로 보존**해야 하므로 따로 잡는다.
_HTML_CELL_RE = re.compile(r"<(td|th)\b([^>]*)>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
# 병합 선언. 이게 걸린 행은 조각마다 되풀이하면 없던 격자를 지어낸다.
_SPAN_ATTR_RE = re.compile(r"\b(?:row|col)span\s*=", re.IGNORECASE)
# 행을 쪼갠 조각에서 "이 칸의 내용은 다른 조각에 있다" 는 표시. 빈칸과 구분돼야 한다.
_ELLIPSIS = "…"


@dataclass(frozen=True)
class Chunk:
    """VDB 에 실릴 한 조각.

    Attributes:
        text: 본문.
        section: 원본 섹션 번호.
        kind: `"paragraph"` / `"table"` — 표 조각인지 알아야 검색 결과 표시가 달라진다.
        table_part: 표를 나눴을 때 `(몇 번째, 총 몇 개)`. 안 나눴으면 `None`.
        table_title: 표 바로 앞 문단(= 표 제목). 표 청크에만, 없으면 빈 값.
        outline_path: 이 청크가 속한 조문 줄기. 위계를 껐거나 조문 문서가 아니면 빈 값.
    """

    text: str
    section: int
    kind: str
    table_part: tuple | None = None
    table_title: str = ""
    outline_path: tuple = ()


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
    # 이 레벨 이하의 제목에서 청크를 끊는다. 기본은 조(5) — 조가 검색 단위다.
    # 0 이면 위계로 끊지 않는다(길이 기준만 쓰는 옛 동작).
    outline_break_level: int = _LEVEL_ARTICLE
    # 청크 본문 앞에 `제2장 총칙 > 제5조(목적)` 머리말을 붙일지. 붙이는 이유는 조각이
    # **혼자서도 해석 가능**해야 하기 때문이다 — 표 조각에 머리행을 반복하는 것과 같은
    # 이유이고, 임베딩되는 문자열 자체에 들어가야 검색에 걸린다.
    outline_prefix: bool = True

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
        if self.outline_break_level < 0:
            self.outline_break_level = _LEVEL_ARTICLE


def _length(options: ChunkOptions, text: str) -> int:
    return options.length(text)


def _cell_segments(cell: str, options: ChunkOptions) -> list:
    """셀 내용을 이어붙일 수 있는 조각으로. → `[(앞에 붙일 이음쇠, 글자)]`.

    1차 경계는 셀 안 줄바꿈(`<br>`)이다. 그 한 줄이 혼자 상한을 넘으면 문장 경계로 한 번
    더 나눈다 — 그때 이음쇠는 **공백**이다. `<br>` 로 다시 이으면 원문에 없던 줄바꿈을
    만들어 내는 셈이고, 그 줄바꿈은 되돌릴 수 없다.
    """
    segments: list = []
    for index, line in enumerate(cell.split(_CELL_LINE_BREAK)):
        separator = _CELL_LINE_BREAK if index else ""
        if _length(options, line) <= options.max_chars:
            segments.append((separator, line))
            continue
        for order, sentence in enumerate(s for s in _SENTENCE_END.split(line) if s):
            segments.append((separator if order == 0 else " ", sentence))
    return segments


def _row_cells(row: str) -> list:
    """`<tr>` 한 줄 → `[(태그, 속성, 내용)]`. 모양이 예상과 다르면 빈 목록.

    되돌려 렌더한 것이 원래 줄과 **글자까지 같을 때만** 쪼갠다. 정규식으로 훑는 것이라
    모르는 모양(속성에 `>` 가 들어간 경우 등)에서 조용히 글자를 잃을 수 있는데, 그 손실은
    검색 결과에 아무 흔적도 남기지 않는다.
    """
    cells = _HTML_CELL_RE.findall(row)
    if len(cells) < 2 or _render_row(cells, [inner for _t, _a, inner in cells], ()) != row:
        return []
    return cells


def _render_row(cells: list, values: list, long_columns) -> str:
    """셀 목록 + 값 목록 → `<tr>` 한 줄.

    `long_columns` 에 든 칸이 비어 있으면 생략 표시를 넣는다 — 이 조각에 안 실렸다는
    뜻이지 값이 없다는 뜻이 아니다. 앵커로 반복되는 **진짜 빈칸**과 구분돼야 한다.
    """
    pieces = []
    for index, ((tag, attrs, _inner), value) in enumerate(zip(cells, values)):
        if not value and index in long_columns:
            value = _ELLIPSIS
        pieces.append(f"<{tag}{attrs}>{value}</{tag}>")
    return "<tr>" + "".join(pieces) + "</tr>"


def _split_wide_row(row: str, prefix: list, suffix: list, options: ChunkOptions) -> list:
    """행 **하나**가 상한을 넘을 때 셀 안에서 나눈다. → `<tr>` 줄 목록.

    행 단위로만 쪼개던 때는 여기서 멈췄고, 그 조각은 상한을 넘긴 채 임베딩으로 갔다
    (실물에서 1,929자). 임베딩 컨텍스트가 그보다 짧으면 **뒤쪽이 조용히 잘린다** —
    레코드에는 글자가 그대로 남아 있어서 검색이 왜 실패했는지 아무 데도 안 드러난다.

    나누는 규칙:
    - 짧은 셀(`_ROW_ANCHOR_MAX_CHARS` 이하)은 **조각마다 통째로 반복**한다. 순번·담당·
      수용여부가 그것이고, 그게 있어야 조각만 봐도 몇 번 항목인지 안다(머리행을 반복하는
      것과 같은 이유다).
    - 긴 셀은 `<br>`(그래도 길면 문장) 경계로 나눠 채운다. **열 수는 그대로**라 조각도
      여전히 올바른 표다.
    - 글자는 하나도 버리지 않고 겹치지도 않는다 — 표 안에서 겹치면 같은 수치가 두 번
      나와 합계가 틀린다.

    **손대지 않는 행 셋**(그대로 돌려준다):
    - 중첩 표가 든 행 — 안쪽 표가 조각 사이에서 갈린다.
    - `rowspan`/`colspan` 이 걸린 행 — 조각마다 되풀이하면 **없던 격자를 지어낸다.**
      병합은 "이 칸이 몇 행·몇 열을 덮는다" 는 선언이라 복제되면 뜻이 달라진다.
    - 쪼갤 데가 없는 행 (칸이 하나뿐이거나 긴 칸이 없는 행).
    """
    if "<table" in row.lower():
        return [row]
    cells = _row_cells(row)
    if not cells or any(_SPAN_ATTR_RE.search(attrs) for _tag, attrs, _inner in cells):
        return [row]

    inners = [inner for _tag, _attrs, inner in cells]
    anchors = [
        inner if _length(options, inner) <= _ROW_ANCHOR_MAX_CHARS else "" for inner in inners
    ]
    long_columns = [index for index, value in enumerate(anchors) if not value]
    if not long_columns:
        return [row]

    def fits(values: list) -> bool:
        candidate = prefix + [_render_row(cells, values, long_columns)] + suffix
        return _length(options, "\n".join(candidate)) <= options.max_chars

    rows: list = []
    current = list(anchors)
    filled = False
    for column in long_columns:
        for separator, segment in _cell_segments(inners[column], options):
            candidate = list(current)
            candidate[column] = (
                f"{candidate[column]}{separator}{segment}" if candidate[column] else segment
            )
            if filled and not fits(candidate):
                rows.append(_render_row(cells, current, long_columns))
                current = list(anchors)
                # 새 조각의 첫 글자다 — 앞의 이음쇠는 버린다(칸이 이음쇠로 시작하면
                # 그 조각만 읽었을 때 앞이 잘린 것처럼 보인다).
                current[column] = segment
            else:
                current = candidate
            filled = True
    rows.append(_render_row(cells, current, long_columns))
    return rows


def _split_html_table(text: str, options: ChunkOptions) -> list:
    """HTML 표를 `<tr>` 단위로 나눈다. 첫 행을 머리행으로 보고 반복한다.

    행 하나가 그것만으로 상한을 넘으면 `_split_wide_row` 가 셀 안에서 한 번 더 나눈다.
    """
    lines = text.splitlines()
    rows = [line for line in lines if line.startswith("<tr>")]
    if len(rows) <= 1:
        return [text]

    header_row = rows[0]
    open_tag, close_tag = "<table><tbody>", "</tbody></table>"

    widened: list = []
    for row in rows[1:]:
        if _length(options, "\n".join([open_tag, header_row, row, close_tag])) > options.max_chars:
            widened.extend(_split_wide_row(row, [open_tag, header_row], [close_tag], options))
        else:
            widened.append(row)

    parts: list = []
    current: list = []
    for row in widened:
        candidate = "\n".join([open_tag, header_row] + current + [row, close_tag])
        if current and _length(options, candidate) > options.max_chars:
            parts.append("\n".join([open_tag, header_row] + current + [close_tag]))
            current = [row]
        else:
            current.append(row)
    if current:
        parts.append("\n".join([open_tag, header_row] + current + [close_tag]))
    return parts or [text]


def _table_prefix_reserve(
    block: Block, options: ChunkOptions, title: str, *, part: bool
) -> int:
    """조각에 붙을 머리말이 차지할 자리. **쪼개기 전에 미리 빼 둔다.**

    조문 머리말은 일부러 길이 계산 **뒤**에 붙인다(조가 깊을수록 본문이 밀려 청크
    크기가 들쭉날쭉해지므로). 표는 사정이 다르다 — 제목이 표 전체에 하나뿐이라 예약이
    균일하고, 예약하지 않으면 **모든 조각이 상한을 조금씩 넘는다.** 상한을 넘기지
    않으려고 행을 쪼갠 직후에 머리말로 다시 넘기면 앞의 노력이 무의미해진다.

    `(표 99/99)` 로 재는 것은 조각 수를 아직 모르기 때문이다 — 실제보다 넉넉하게
    잡을지언정 모자라게 잡지 않는다.
    """
    pieces = []
    if title and not block.outline_path:
        pieces.append(title)
    if part:
        pieces.append("(표 99/99)")
    sample = " ".join(pieces)
    sample = f"{sample}\n" if sample else ""
    if options.outline_prefix and block.outline_path:
        sample = f"{_OUTLINE_SEPARATOR.join(block.outline_path)}\n\n{sample}"
    return _length(options, sample) if sample else 0


def _table_chunks(block: Block, options: ChunkOptions, title: str = "") -> list:
    if _length(options, block.text) + _table_prefix_reserve(
        block, options, title, part=False
    ) <= options.max_chars:
        return [
            Chunk(
                text=block.text,
                section=block.section,
                kind="table",
                table_title=title,
                outline_path=block.outline_path,
            )
        ]

    budget = options.max_chars - _table_prefix_reserve(block, options, title, part=True)
    if budget >= options.max_chars // 2:
        # 머리말이 상한의 절반을 먹을 만큼 길면 예약을 포기한다 — 그 지경이면 본문이
        # 밀려 조각이 표 몇 줄짜리가 되고, 그게 상한을 지키는 것보다 나쁘다.
        options = replace(options, max_chars=budget)

    parts = _split_html_table(block.text, options)

    total = len(parts)
    return [
        Chunk(
            text=part,
            section=block.section,
            kind="table",
            table_part=(index, total),
            table_title=title,
            outline_path=block.outline_path,
        )
        for index, part in enumerate(parts)
    ]


def _table_title_of(block: Block, options: ChunkOptions) -> str:
    """이 문단을 뒤따르는 표의 제목으로 볼 수 있나. 아니면 빈 문자열.

    제목은 **한 줄짜리 짧은 문단**만 인정한다. 본문 문단을 제목으로 삼으면 표 조각마다
    본문이 통째로 반복돼 임베딩이 표가 아니라 그 본문 쪽으로 끌려간다.
    """
    text = block.text.strip()
    if not text or "\n" in text or _length(options, text) > _TABLE_TITLE_MAX_CHARS:
        return ""
    return text


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
    읽기 어려워진다. 구역(section)이 바뀔 때도 끊는다 — 청크가 두 구역에 걸치면
    `i_section` 이 둘 중 하나만 가리켜 출처가 틀린다.

    블록에 조문 위계가 매겨져 있으면(`annotate_outline`) **조 이상의 제목에서도 끊는다.**
    한 조가 여러 청크에 흩어지면 "제5조가 무엇을 정하는가" 에 답할 수 없고, 두 조가 한
    청크에 붙으면 검색이 엉뚱한 조를 근거로 든다. 항·호·목에서는 끊지 않는다 — 그 단위로
    쪼개면 조문 하나가 문장 조각들로 부서진다. 조가 상한을 넘을 때만 기존 길이 기준이
    안에서 작동하고, 그때 경계는 자연히 항(`①`) 문단 머리에 떨어진다.
    """
    options = options or ChunkOptions()
    chunks: list = []
    buffer = ""
    buffer_section = 0
    buffer_path: tuple = ()
    # 바로 앞 문단 = 다음 표의 제목 후보. 표를 지나면 비운다(표 뒤의 표는 앞 표를
    # 제목으로 삼으면 안 된다).
    table_title = ""

    def flush():
        nonlocal buffer
        if buffer.strip():
            chunks.append(
                Chunk(
                    text=buffer.strip(),
                    section=buffer_section,
                    kind="paragraph",
                    outline_path=buffer_path,
                )
            )
        buffer = ""

    def start(block: Block):
        """버퍼가 비었을 때 그 청크의 출처(섹션·조문 줄기)를 첫 블록에서 가져온다."""
        nonlocal buffer_section, buffer_path
        buffer_section = block.section
        buffer_path = block.outline_path

    for block in blocks:
        if block.is_table:
            flush()
            chunks.extend(_table_chunks(block, options, title=table_title))
            table_title = ""
            continue

        table_title = _table_title_of(block, options)

        if buffer and block.section != buffer_section:
            # 구역(`Contents/sectionN.xml`)이 바뀌면 끊는다. 안 끊으면 뒤 구역의 첫
            # 문단이 앞 구역 청크 꼬리에 붙고, 그 청크의 `i_section` 은 앞 구역을
            # 가리켜 **출처가 틀린다.** 예전에는 구역 경계에 표가 있어 우연히 끊겼을
            # 뿐이라 드러나지 않았다.
            flush()

        if (
            options.outline_break_level
            and block.outline_level
            and block.outline_level <= options.outline_break_level
        ):
            # 조 이상의 제목 = 하드 경계. 겹침도 넘기지 않는다 — 앞 조의 꼬리가 다음 조
            # 청크 머리에 붙으면 그 청크가 어느 조의 내용인지 흐려진다.
            flush()

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
                start(block)
            else:
                if not buffer:
                    # 옛 코드는 `not chunks and not buffer_section` 으로 첫 청크에서만
                    # 섹션을 잡았다 — 두 번째 청크부터 `i_section` 이 앞 청크 값에
                    # 얼어붙어, 섹션이 여럿인 문서에서 출처가 틀리게 실렸다.
                    start(block)
                buffer = candidate

    flush()
    return _apply_outline_prefix(
        _apply_table_prefix(_drop_heading_only_chunks(_merge_tiny(chunks, options))),
        options,
    )


def _merge_tiny(chunks: list, options: ChunkOptions) -> list:
    """너무 짧은 **문단** 청크를 앞에 붙인다.

    표 청크는 건드리지 않는다 — 짧아도 그 자체가 의미 단위이고, 문단에 붙이면 표가
    문단 꼬리에 섞여 버린다. **조문 줄기나 구역이 다르면 붙이지 않는다** — 붙이면 방금
    끊은 경계가 되돌려져 두 조(또는 두 구역)가 한 청크에 섞인다. 짧은 쪽이 앞 청크에
    흡수되는 모양이라, 경계를 세워 둔 코드만 읽어서는 왜 안 끊기는지 알 수 없다.
    """
    merged: list = []
    for chunk in chunks:
        if (
            chunk.kind == "paragraph"
            and merged
            and merged[-1].kind == "paragraph"
            and merged[-1].outline_path == chunk.outline_path
            # 구역·조 경계에서 끊어 놓고 여기서 도로 붙이면 경계가 없던 것이 된다.
            and merged[-1].section == chunk.section
            and _length(options, chunk.text) < options.min_chars
        ):
            previous = merged.pop()
            merged.append(
                Chunk(
                    text=f"{previous.text}\n\n{chunk.text}",
                    section=previous.section,
                    kind="paragraph",
                    outline_path=previous.outline_path,
                )
            )
        else:
            merged.append(chunk)
    return merged


def _drop_heading_only_chunks(chunks: list) -> list:
    """제목 하나뿐인 청크를 버린다 — **뒤 청크가 그 제목을 머리말로 이고 갈 때만.**

    `제2장 총칙` 처럼 제목만 있는 문단은 조 경계에서 끊기고 나면 홀로 남는데, 그 여섯
    글자로는 검색에서 아무것도 답하지 못하면서 자리만 차지한다. 그렇다고 무조건 버리면
    본문이 사라질 수 있으므로, **본문이 자기 이름표와 글자까지 같고**(= 제목 외에 아무
    내용이 없고) **다음 청크의 줄기가 그 제목을 포함**할 때만 버린다. 그 두 조건이면
    글자가 다음 청크의 머리말로 그대로 살아남으므로 무손실이다.
    """
    kept: list = []
    for index, chunk in enumerate(chunks):
        following = chunks[index + 1] if index + 1 < len(chunks) else None
        if (
            chunk.kind == "paragraph"
            
            and chunk.outline_path
            and chunk.text == chunk.outline_path[-1]
            and following is not None
            and following.outline_path[: len(chunk.outline_path)] == chunk.outline_path
        ):
            continue
        kept.append(chunk)
    return kept


def _table_prefix_for(chunk: Chunk) -> str:
    """표 청크 앞에 붙일 머리말. 붙일 게 없으면 빈 문자열.

    **왜 메타데이터가 아니라 본문에 넣나.** `table_part`·`table_title` 은 레코드에도
    싣지만, 검색 결과가 LLM 에게 갈 때의 봉투(`<doc file_name=… security_level=…>`)에는
    그 필드가 실리지 않는다 — 실물 결과에서 확인했다. 그래서 3번째 조각이 "3번 항목부터
    시작하는 표" 로 보이고, 앞의 1~2번이 어디 있는지도, 이게 표의 일부라는 것도 알 수
    없다. **조각이 혼자서도 해석 가능해야** 하므로 조문 머리말과 같은 이유로 본문에 넣는다.

    제목은 조문 줄기가 있을 때는 붙이지 않는다 — 그쪽은 `_apply_outline_prefix` 가
    이미 `제2장 총칙 > 제5조(목적)` 을 붙이고 있어 머리말이 두 겹이 된다.
    """
    if chunk.kind != "table":
        return ""
    pieces = []
    if chunk.table_title and not chunk.outline_path:
        pieces.append(chunk.table_title)
    if chunk.table_part is not None:
        index, total = chunk.table_part
        pieces.append(f"(표 {index + 1}/{total})")
    return " ".join(pieces)


def _apply_table_prefix(chunks: list) -> list:
    """표 청크 본문 앞에 `제목 (표 2/10)` 한 줄을 붙인다.

    조문 머리말과 마찬가지로 **길이 계산이 끝난 뒤에** 붙는다 — 머리말까지 상한 안에
    넣으려 하면 제목 길이에 따라 조각 크기가 들쭉날쭉해진다.
    """
    prefixed: list = []
    for chunk in chunks:
        prefix = _table_prefix_for(chunk)
        prefixed.append(replace(chunk, text=f"{prefix}\n{chunk.text}") if prefix else chunk)
    return prefixed


def _outline_prefix_for(chunk: Chunk) -> str:
    """청크 앞에 붙일 위계 머리말. 붙일 게 없으면 빈 문자열.

    **이미 본문이 이고 있는 제목은 빼고 붙인다.** 조 제목 문단으로 시작하는 청크에
    `제5조(목적) > 제5조(목적) …` 처럼 겹쳐 붙으면 임베딩에 같은 문구가 두 번 실린다.
    """
    path = chunk.outline_path
    if path and chunk.text.startswith(path[-1]):
        path = path[:-1]
    return _OUTLINE_SEPARATOR.join(path)


def _apply_outline_prefix(chunks: list, options: ChunkOptions) -> list:
    """청크 본문 앞에 조문 줄기를 붙인다 (`outline_path` 자체는 그대로 남긴다).

    길이 계산이 끝난 뒤에 붙는다 — 머리말까지 `max_chars` 안에 넣으려 하면 조가 깊을수록
    본문이 밀려나고, 같은 문서에서 조마다 청크 크기가 들쭉날쭉해진다. 머리말은 조문
    위계가 있을 때만 붙으므로 일반 문서는 옛 동작 그대로다.
    """
    if not options.outline_prefix:
        return chunks

    prefixed: list = []
    for chunk in chunks:
        prefix = _outline_prefix_for(chunk)
        prefixed.append(replace(chunk, text=f"{prefix}\n\n{chunk.text}") if prefix else chunk)
    return prefixed


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
        if chunk.table_title:
            # 본문 머리말과 **따로** 싣는다(조문 줄기와 같은 규약) — 머리말은 임베딩되라고
            # 있는 것이고, 이 값은 검색 결과에 "무슨 표인가" 를 표시하는 데 쓴다.
            record["table_title"] = chunk.table_title
        if chunk.outline_path:
            # 본문 머리말과 **따로** 싣는다. 머리말은 임베딩되라고 있는 것이고, 이 둘은
            # 검색 결과에 출처를 표시하거나 조 단위로 거르는 데 쓴다.
            record["outline_path"] = list(chunk.outline_path)
            record["outline_title"] = chunk.outline_path[-1]
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
        mode = kwargs.get("outline_mode") or _OUTLINE_AUTO
        blocks = annotate_outline(document.blocks, str(mode).strip().lower())
        chunks = chunk_blocks(blocks, options)
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
