# =====================================================================================
# genon_hwpx_text — hwpx 직접 파싱 MCP 도구 (area 01)
#
# **이 파일 하나가 등록 단위다.** GenOS MCP 는 소스 파일 한 개를 받아 실행하며,
# `mcp` 객체를 런타임이 전역으로 주입한다. 그래서 패키지로 쪼갤 수 없고,
# 여기에 파싱 로직·도구 정의가 전부 들어 있다.
#
# **모든 최상위 심볼에 `HX` 접두어를 붙였다.** 한 서버에 다른 도구 파일이 함께 로드될 수
# 있어서다 — `ToolError`·`to_markdown` 같은 흔한 이름을 그대로 두면 나중에 로드된 쪽이
# 앞엣것을 덮어쓰고, 그 실패는 "도구가 이상한 결과를 낸다" 로만 드러난다.
#
# LLM 을 부르지 않는다. 같은 입력에 항상 같은 결과가 나온다.
# =====================================================================================

import base64
import html as _html
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass


def _hx_ensure_packages():
    """MCP 기본 이미지에 없는 패키지를 기동 시 설치한다.

    `lxml` 하나뿐이다. 표 격자를 `cellAddr` 좌표로 만들려면 XML 트리 순회가 필요한데,
    stdlib `ElementTree` 는 부모 추적이 없어 `_HXnearest_para` 를 구현할 수 없다.
    """
    for pkg, install_name in (("lxml", "lxml"),):
        if not importlib.util.find_spec(pkg):
            print(f"[BOOT] {install_name} 설치 시작")
            subprocess.check_call([sys.executable, "-m", "pip", "install", install_name])
            print(f"[BOOT] {install_name} 설치 완료")


_hx_ensure_packages()

from lxml import etree  # noqa: E402

# ── hwpx_text.py ─────────────────────────────
HXHP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"

_HXPARA = f"{{{HXHP_NS}}}p"
_HXTEXT = f"{{{HXHP_NS}}}t"
_HXTBL = f"{{{HXHP_NS}}}tbl"
_HXTR = f"{{{HXHP_NS}}}tr"
_HXTC = f"{{{HXHP_NS}}}tc"
_HXCELL_ADDR = f"{{{HXHP_NS}}}cellAddr"
_HXCELL_SPAN = f"{{{HXHP_NS}}}cellSpan"

# 본문은 Contents/sectionN.xml 이다. header.xml 등은 서식 정의라 본문이 아니다.
_HXSECTION_ENTRY_RE = re.compile(r"^Contents/section(\d+)\.xml$")

# <hp:t> 안의 \n 은 문단 분리가 아니다 — 그대로 두면 마크다운에서 문단이 갈린다
_HXNEWLINE_REPLACEMENT = " "
# 셀 안 줄바꿈은 마크다운 표를 깨뜨린다 — 표에서만 <br> 로 바꾼다
_HXCELL_LINE_BREAK = "<br>"


class HXHwpxParseError(ValueError):
    """hwpx 해석 실패 (ZIP/XML 손상).

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다.
    호출부가 사용자 노출 오류로 그대로 쓴다 (3.8절).
    """


@dataclass(frozen=True)
class HXHwpxDocument:
    markdown: str
    paragraph_count: int
    table_count: int


def _HXopen(hwpx_bytes: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(hwpx_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise HXHwpxParseError("hwpx 파일이 아니거나 손상된 파일입니다.") from exc


def _HXsection_order(entry_name: str):
    """본문 섹션이면 섹션 번호, 아니면 None.

    문자열 정렬을 쓰지 않는 이유: `section10` 이 `section2` 앞에 온다. 문단 순서가
    밀리면 번역 결과와 원본 대조(하이라이트)가 어긋난다.
    """
    match = _HXSECTION_ENTRY_RE.match(entry_name)
    return int(match.group(1)) if match else None


def _HXiter_section_xml(hwpx_bytes: bytes):
    with _HXopen(hwpx_bytes) as archive:
        names = [n for n in archive.namelist() if _HXsection_order(n) is not None]
        for name in sorted(names, key=_HXsection_order):
            yield name, archive.read(name)


def _HXparse_xml(xml_bytes: bytes):
    try:
        return etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise HXHwpxParseError("hwpx 본문 XML 을 해석하지 못했습니다.") from exc


def _HXnearest_para(node):
    """이 노드를 직접 담고 있는 문단. 표 안(hp:tc→hp:subList→hp:p)까지 따라간다."""
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _HXPARA:
            return parent
        parent = parent.getparent()
    return None


def _HXown_text(para) -> str:
    """이 문단이 **직접** 가진 텍스트.

    hwpx 표는 hp:p → hp:run → hp:tbl → … → hp:p 로 중첩된다. `para.iter()` 를 그대로
    쓰면 표 전체가 한 문단으로 붙어 마크다운이 통째로 깨진다.
    """
    parts = [
        (node.text or "")
        for node in para.iter(_HXTEXT)
        if _HXnearest_para(node) is para
    ]
    text = "".join(parts).replace("\r\n", "\n").replace("\n", _HXNEWLINE_REPLACEMENT)
    return text.strip()


def _HXchildren(elem, tag: str) -> list:
    """직접 자식만 (중첩 표의 tr/tc 가 섞이지 않게)."""
    return [child for child in elem if child.tag == tag]


def _HXint_attr(elem, name: str, default: int) -> int:
    if elem is None:
        return default
    try:
        return int((elem.get(name) or "").strip())
    except ValueError:
        return default


def _HXowning_cell(node):
    """이 노드를 담고 있는 **가장 가까운** 셀. 중첩 표를 가르는 기준이다."""
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _HXTC:
            return parent
        parent = parent.getparent()
    return None


def _HXcell_parts(tc) -> list:
    """셀 내용을 `("text", str)` 과 `("table", elem)` 으로 **문서 순서대로** 나눈다.

    `tc.iter(hp:p)` 를 그대로 쓰면 **중첩 표 안의 문단까지 딸려온다.** 그러면 2열짜리
    표가 `소분류<br>값` 이라는 한 덩어리 텍스트가 되어 구조가 통째로 사라진다 —
    마크다운 출력이 실제로 그랬다. 소유 셀을 따져 자기 것만 고른다.
    """
    parts = []
    for node in tc.iter():
        if node.tag == _HXPARA and _HXowning_cell(node) is tc:
            text = _HXown_text(node)
            if text:
                parts.append(("text", text))
        elif node.tag == _HXTBL and _HXowning_cell(node) is tc:
            parts.append(("table", node))
    return parts


def _HXcell_text(tc) -> str:
    """마크다운 표용 셀 텍스트. 여러 문단은 <br> 로 잇고 파이프는 이스케이프한다.

    파이프를 escape 하지 않으면 셀 내용이 열 경계로 읽혀 표가 밀린다.

    이 경로는 **중첩 표가 없는 표에서만** 쓰인다 (`_HXneeds_html` 이 갈라낸다).
    """
    parts = [value for kind, value in _HXcell_parts(tc) if kind == "text"]
    return _HXCELL_LINE_BREAK.join(parts).replace("|", "\\|")


def _HXcell_html(tc) -> str:
    """HTML 표용 셀 내용. 중첩 표는 `<table>` 로 그대로 살린다.

    텍스트는 `html.escape(quote=False)` 로 감싼다 — 번역 스켈레톤 분해기가 LLM 에
    보낼 때 `unescape` 하고 재조립 때 같은 방식으로 되돌리므로 규약이 맞아야 한다.
    따옴표는 이스케이프하지 않는다(속성값이 아니라 본문이다).
    """
    pieces = []
    previous_was_text = False
    for kind, value in _HXcell_parts(tc):
        if kind == "text":
            if previous_was_text:
                pieces.append(_HXCELL_LINE_BREAK)
            pieces.append(_html.escape(value, quote=False))
            previous_was_text = True
        else:
            pieces.append("".join(_HXtable_html(value)))
            previous_was_text = False
    return "".join(pieces)


def _HXtable_grid(tbl) -> tuple:
    """hp:tbl → `(anchors, covered, height, width)`.

    `anchors[(row, col)] = (tc, row_span, col_span)` — 셀이 **시작하는** 자리.
    `covered` 는 병합으로 덮인 자리(앵커 제외). 병합 셀은 앵커에만 내용이 있으므로,
    이 둘을 가르지 않으면 아래 행에서 열이 밀린다.
    """
    anchors: dict = {}
    occupied: set = set()
    height = 0
    width = 0

    for row_index, tr in enumerate(_HXchildren(tbl, _HXTR)):
        cursor = 0
        for tc in _HXchildren(tr, _HXTC):
            addr = tc.find(_HXCELL_ADDR)
            span = tc.find(_HXCELL_SPAN)
            col_span = _HXint_attr(span, "colSpan", 1)
            row_span = _HXint_attr(span, "rowSpan", 1)
            if addr is not None:
                row = _HXint_attr(addr, "rowAddr", row_index)
                col = _HXint_attr(addr, "colAddr", cursor)
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


def _HXneeds_html(tbl) -> bool:
    """마크다운 표로 **표현할 수 없는** 구조인가.

    셋 중 하나라도 있으면 마크다운은 정보를 잃는다:

    - **병합 셀** — `rowspan`/`colspan` 에 해당하는 문법이 없다. 지금은 빈 칸이 되어
      LLM 이 "머리글이 없는 열" 로 읽는다.
    - **중첩 표** — 마크다운 표는 중첩이 안 된다. 안쪽 표가 텍스트로 뭉개진다.

    잃을 것이 없는 단순한 표는 마크다운 그대로 둔다 — 토큰도 적고 사람이 읽기도 낫다.
    """
    if any(node is not tbl for node in tbl.iter(_HXTBL)):
        return True
    for tr in _HXchildren(tbl, _HXTR):
        for tc in _HXchildren(tr, _HXTC):
            span = tc.find(_HXCELL_SPAN)
            if _HXint_attr(span, "rowSpan", 1) > 1 or _HXint_attr(span, "colSpan", 1) > 1:
                return True
    return False


def _HXtable_markdown(tbl) -> list:
    """hp:tbl → 마크다운 표 줄 목록 (병합·중첩이 없는 표 전용)."""
    anchors, _covered, height, width = _HXtable_grid(tbl)
    if not width or not height:
        return []

    lines = []
    for row in range(height):
        values = [
            _HXcell_text(anchors[(row, col)][0]) if (row, col) in anchors else ""
            for col in range(width)
        ]
        lines.append("| " + " | ".join(value or " " for value in values) + " |")
        if row == 0:
            # 마크다운 표는 구분선이 필수다. hwpx 는 머리행 표시가 없으므로 첫 행을
            # 머리행으로 본다 (구조를 지어내지 않는 최소 가정).
            lines.append("|" + "---|" * width)
    return lines


def _HXtable_html(tbl) -> list:
    """hp:tbl → HTML 표 줄 목록. `rowspan`/`colspan`/중첩을 그대로 살린다.

    형태는 지능형 전처리기가 내는 것과 맞춘다(`<table><tbody><tr><td>…`) —
    번역 스켈레톤 분해기가 이미 그 형태를 태그와 텍스트로 토큰화하므로,
    새 형식을 만드는 것이 아니라 **이미 지원하는 형식**으로 내는 것이다.

    행마다 한 줄로 끊는다. 한 줄로 몰아도 동작하지만(전처리기가 그렇게 낸다) 사람이
    읽을 수 없고, 표가 크면 진단이 불가능해진다.
    """
    anchors, covered, height, width = _HXtable_grid(tbl)
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
            cells.append(f"<td{attrs}>{_HXcell_html(tc)}</td>")
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines.append("</tbody></table>")
    return lines


def _HXrender_table(tbl) -> list:
    """hp:tbl → 표 줄 목록.

    **병합·중첩이 있으면 HTML, 아니면 마크다운.** 마크다운으로 손실 없이 표현할 수
    있는 표는 그대로 두고, 표현할 수 없는 것만 형식을 바꾼다.
    """
    return _HXtable_html(tbl) if _HXneeds_html(tbl) else _HXtable_markdown(tbl)


def hxto_markdown(hwpx_bytes: bytes, max_chars: int = 0) -> HXHwpxDocument:
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

    for _, xml_bytes in _HXiter_section_xml(hwpx_bytes):
        root = _HXparse_xml(xml_bytes)
        # lxml 프록시는 참조가 끊기면 회수되고 id 가 재사용된다 — 순회 결과를 리스트로
        # 붙들어 둔 뒤에 id 로 묶는다 (SFR-006 에서 항목 순서가 뒤섞이는 버그로 드러난 함정).
        paragraphs = list(root.iter(_HXPARA))
        tables = list(root.iter(_HXTBL))
        owned_tables: dict = {}
        for tbl in tables:
            owner = _HXnearest_para(tbl)
            if owner is not None:
                owned_tables.setdefault(id(owner), []).append(tbl)

        for para in paragraphs:
            # 표 셀·머리말·각주의 문단은 상위 hp:p 안에 중첩된다. 표는 소유 문단에서
            # 따로 렌더링하고, 머리말/각주는 본문 흐름이 아니라 제외한다.
            if _HXnearest_para(para) is not None:
                continue
            text = _HXown_text(para)
            if text:
                paragraph_count += 1
                blocks.append(text)
            for tbl in owned_tables.get(id(para), ()):
                lines = _HXrender_table(tbl)
                if lines:
                    table_count += 1
                    blocks.append("\n".join(lines))

    markdown = "\n\n".join(blocks)
    if max_chars > 0 and len(markdown) > max_chars:
        markdown = markdown[:max_chars].rstrip()
    return HXHwpxDocument(
        markdown=markdown,
        paragraph_count=paragraph_count,
        table_count=table_count,
    )


# ── tools.py ─────────────────────────────
class HXToolError(ValueError):
    def __init__(self, error_type: str):
        super().__init__(error_type)
        self.error_type = error_type


# 업로드 상한. 없으면 한 번의 호출이 서빙 메모리를 통째로 쓴다.
_HXMAX_BYTES = 50 * 1024 * 1024
_HXDEFAULT_MAX_CHARS = 200_000


def _HXmax_chars_arg(arguments: dict) -> int:
    value = arguments.get("max_chars", _HXDEFAULT_MAX_CHARS)
    try:
        max_chars = int(value)
    except (TypeError, ValueError):
        raise HXToolError("INVALID_TYPE_MAX_CHARS") from None
    if max_chars < 0:
        raise HXToolError("OUT_OF_RANGE_MAX_CHARS")
    return max_chars


def _HXread_source(arguments: dict) -> tuple:
    """`(bytes, source_kind)` 또는 실패 사유를 담은 `ToolError`.

    `content_base64` 를 `path` 보다 먼저 본다 — 명시적으로 바이트를 준 호출자는
    볼륨 공유를 전제하지 않겠다는 뜻이다.
    """
    encoded = arguments.get("content_base64")
    if encoded:
        if not isinstance(encoded, str):
            raise HXToolError("INVALID_TYPE_CONTENT_BASE64")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except Exception:  # noqa: BLE001 - 디코딩 실패 원문은 남기지 않는다
            raise HXToolError("INVALID_BASE64") from None
        if len(raw) > _HXMAX_BYTES:
            raise HXToolError("FILE_TOO_LARGE")
        return raw, "base64"

    path = arguments.get("path")
    if not path:
        raise HXToolError("MISSING_ARG_SOURCE")
    if not isinstance(path, str):
        raise HXToolError("INVALID_TYPE_PATH")

    # 크기를 먼저 본다 — 다 읽고 나서 재면 상한 밖 메모리를 이미 쓴 뒤다.
    try:
        size = os.path.getsize(path)
    except OSError:
        raise HXToolError("PATH_NOT_READABLE") from None
    if size > _HXMAX_BYTES:
        raise HXToolError("FILE_TOO_LARGE")

    try:
        with open(path, "rb") as handle:
            return handle.read(), "path"
    except OSError:
        # 경로 문자열은 응답에 넣지 않는다 (내부 경로다, 3.8절)
        raise HXToolError("PATH_NOT_READABLE") from None


def _HXhwpx_to_markdown(arguments: dict) -> dict:
    max_chars = _HXmax_chars_arg(arguments)
    raw, source_kind = _HXread_source(arguments)

    try:
        document = hxto_markdown(raw, max_chars)
    except HXHwpxParseError as exc:
        # 메시지는 `hwpx_text.py` 안에서 작성한 고정 한국어 안내문이다 (그 파일의 계약).
        return {"ok": False, "reason": str(exc), "error_type": "HWPX_PARSE_FAILED",
                "source_kind": source_kind}

    return {
        "ok": True,
        "markdown": document.markdown,
        "paragraph_count": document.paragraph_count,
        "table_count": document.table_count,
        # 상한에 걸려 잘렸는지 호출부가 알아야 한다 — 잘린 문서로 FAQ 를 만들면
        # 뒷부분 내용이 통째로 빠진 채 정상 결과처럼 나온다.
        "truncated": bool(max_chars and len(document.markdown) >= max_chars),
        "source_kind": source_kind,
    }


HXTOOL_SPECS = [
    {
        "name": "hwpx_to_markdown",
        "description": (
            "hwpx 문서를 직접 파싱해 마크다운으로 낸다. 표는 cellAddr 좌표로 격자를 만들어 "
            "병합 셀에서도 열이 밀리지 않는다. 전처리기 PDF 변환 경로와 달리 표 안 수치가 "
            "보존된다. 파일은 `content_base64`(권장) 또는 공유 볼륨 `path` 로 준다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content_base64": {
                    "type": "string",
                    "description": "hwpx 파일 바이트의 base64. 볼륨 공유를 전제하지 않는 권장 경로",
                },
                "path": {
                    "type": "string",
                    "description": "공유 볼륨 상의 hwpx 경로. 이 pod 가 같은 볼륨을 보는 배포에서만 동작",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "마크다운 길이 상한 (0 이면 제한 없음, 기본 200000)",
                },
            },
        },
    },
]

_HXHANDLERS = {"hwpx_to_markdown": _HXhwpx_to_markdown}


def hxcall_tool(name: str, arguments: dict) -> dict:
    handler = _HXHANDLERS.get(name)
    if handler is None:
        raise HXToolError("UNKNOWN_TOOL")
    return handler(arguments)


# =====================================================================================
# 로컬 단독 실행 대비: 런타임이 주입하는 전역 `mcp` 가 없으면 최소 shim 을 쓴다.
# 점검 스크립트(`onprem/test/check_mcp_tools.py`)도 이 경로로 도구를 잡아 직접 부른다.
# =====================================================================================
try:
    mcp  # noqa: F821
except NameError:
    class _HXLocalMCP:
        def tool(self, *args, **kwargs):
            def _decorator(fn):
                return fn
            return _decorator

    mcp = _HXLocalMCP()
    print("[BOOT] 로컬 테스트용 shim 사용")


# =====================================================================================
# MCP Tool : hwpx_to_markdown
# =====================================================================================

@mcp.tool()
async def hwpx_to_markdown(
    content_base64: str = "",
    path: str = "",
    # GenOS 는 값이 없을 때 None 이 아니라 **빈 문자열("")** 을 주입한다. MCP 가 본문 전에
    # 타입 검증을 하므로 `int` 로만 선언하면 "" 에서 검증 에러가 난다 → str 도 받고
    # 아래에서 캐스팅한다.
    max_chars: int | str | None = None,
) -> str:
    """[언제 쓰나] hwpx 파일의 본문·표를 그대로 읽어야 할 때. 표 안 수치가 보존된다.
    → 전처리기 PDF 변환 경로는 표가 깨질 수 있으므로, hwpx 원본이 있으면 이 도구를 쓴다.

    hwpx 를 직접 파싱해 마크다운으로 낸다. 표는 `cellAddr` 좌표로 격자를 만든다.

    **표 형식은 손실 여부에 따라 갈린다:**

    - 단순한 표 → 마크다운 표 (`| 항목 | 값 |`). 토큰도 적고 읽기도 쉽다.
    - **병합(`rowSpan`/`colSpan`) 또는 중첩 표 → HTML**
      (`<table><tbody><tr><td rowspan="2">…`).

    마크다운 표에는 병합 문법이 **없다.** 병합 셀을 마크다운으로 내면 빈 칸이 되고,
    LLM 은 "머리글 없는 열" 로 읽는다 — 수치는 남는데 **그 수치가 무엇의 값인지가
    사라진다.** 중첩 표는 아예 한 덩어리 텍스트로 뭉개진다. HTML 은 둘 다 그대로 담는다.

    LLM 을 부르지 않으므로 같은 파일에 항상 같은 결과가 나온다.

    Args:
        content_base64: hwpx 파일 바이트의 base64. **볼륨 공유를 전제하지 않는 권장 경로.**
        path: 공유 볼륨 상의 hwpx 경로. 이 pod 가 같은 볼륨을 보는 배포에서만 동작한다.
            `content_base64` 가 있으면 그쪽이 우선한다.
        max_chars: 마크다운 길이 상한 (0 이면 제한 없음, 기본 200000).

    Returns:
        JSON 문자열. 성공이면
        `{"ok": true, "markdown", "paragraph_count", "table_count", "truncated", "source_kind"}`,
        실패면 `{"ok": false, "reason", "error_type", "source_kind"}`.

        **실패를 예외가 아니라 판정 결과로 낸다** — 호출부(FAQ 스텝 1)가 전처리기 산출물로
        떨어지는 폴백을 갖고 있어서, 재시도 대상인지 폴백 대상인지 구분되어야 한다.
        `truncated` 는 반드시 봐야 한다: 잘린 문서로 FAQ 를 만들면 뒷부분이 통째로 빠진 채
        정상 결과처럼 나온다.
    """
    arguments = {
        "content_base64": content_base64 or None,
        "path": path or None,
    }
    if max_chars is not None and max_chars != "":
        arguments["max_chars"] = max_chars

    try:
        result = _HXhwpx_to_markdown(arguments)
    except HXToolError as exc:
        # 입력이 잘못된 경우. 경로 문자열·예외 원문은 싣지 않는다 (3.8절).
        result = {"ok": False, "error_type": exc.error_type, "reason": ""}
    except Exception as exc:  # noqa: BLE001 - 최종 방어선
        print(f"[ERROR] hwpx_to_markdown 실패: {type(exc).__name__}")
        result = {"ok": False, "error_type": "TOOL_EXECUTION_FAILED", "reason": ""}

    return json.dumps(result, ensure_ascii=False)
