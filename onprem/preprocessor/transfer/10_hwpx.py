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
    "id_ref",
)
def _emit_log(level: int, message: str, *, event: str, **fields: Any) -> None:
    extra: dict = {"event": event}
    dropped = []
    for key, value in fields.items():
        if key == "event" or key not in _ALLOWED_LOG_FIELDS:
            dropped.append(key)
            continue
        if value is not None:
            extra[key] = value
    if dropped:
        message = f"{message} [dropped_fields={','.join(sorted(dropped))}]"
    _log.log(level, message, extra=extra)
def _log_info(message: str, *, event: str, **fields: Any) -> None:
    _emit_log(logging.INFO, message, event=event, **fields)
def _log_warning(message: str, *, event: str, **fields: Any) -> None:
    _emit_log(logging.WARNING, message, event=event, **fields)
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
_HEADER_ENTRY = "Contents/header.xml"
_DRAW_TEXT = f"{{{HP_NS}}}drawText"
_CAPTION = f"{{{HP_NS}}}caption"
_FOOT_NOTE = f"{{{HP_NS}}}footNote"
_END_NOTE = f"{{{HP_NS}}}endNote"
_PAGE_HEADER = f"{{{HP_NS}}}header"
_PAGE_FOOTER = f"{{{HP_NS}}}footer"
_HIDDEN_COMMENT = f"{{{HP_NS}}}hiddenComment"
_MEMO = f"{{{HP_NS}}}memo"
_BOX_LABELS = {
    _DRAW_TEXT: "",
    _CAPTION: "",
    _FOOT_NOTE: "[각주] ",
    _END_NOTE: "[미주] ",
    _PAGE_HEADER: "[머리말] ",
    _PAGE_FOOTER: "[꼬리말] ",
    _HIDDEN_COMMENT: "[숨은 설명] ",
    _MEMO: "[메모] ",
}
_SUBLIST = f"{{{HP_NS}}}subList"
_EQUATION = f"{{{HP_NS}}}equation"
_SCRIPT = f"{{{HP_NS}}}script"
_INLINE_CHARS = {
    f"{{{HP_NS}}}tab": "\t",
    f"{{{HP_NS}}}lineBreak": "\n",
    f"{{{HP_NS}}}hyphen": "-",
    f"{{{HP_NS}}}nbSpace": " ",
    f"{{{HP_NS}}}fwSpace": "　",
}
_NEWLINE_REPLACEMENT = " "
_CELL_LINE_BREAK = "<br>"
_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s+")
_OUTLINE_OFF = "off"
_OUTLINE_AUTO = "auto"
_OUTLINE_STATUTE = "statute"
_OUTLINE_DOCUMENT = "document"
_OUTLINE_MODES = (_OUTLINE_AUTO, _OUTLINE_STATUTE, _OUTLINE_DOCUMENT, _OUTLINE_OFF)
_LEVEL_ARTICLE = 5
_LEVEL_PATH_MAX = _LEVEL_ARTICLE
_MOK_LETTERS = "가나다라마바사아자차카타파하"
_NOT_CITED = r"(?![가-힣])"
_STATUTE_RULES = (
    (1, re.compile(rf"^제\s*\d+\s*편{_NOT_CITED}")),
    (2, re.compile(rf"^제\s*\d+\s*장{_NOT_CITED}")),
    (2, re.compile(r"^부\s*칙(?=[\s(<[]|$)")),
    (3, re.compile(rf"^제\s*\d+\s*절{_NOT_CITED}")),
    (4, re.compile(rf"^제\s*\d+\s*관{_NOT_CITED}")),
    (_LEVEL_ARTICLE, re.compile(rf"^제\s*\d+\s*조(?:\s*의\s*\d+)?{_NOT_CITED}")),
    (6, re.compile(r"^[①-⑳]")),
    (7, re.compile(r"^\d{1,2}\.(?=\s)")),
    (8, re.compile(rf"^[{_MOK_LETTERS}]\.(?=\s)")),
)
_ARTICLE_RE = next(pattern for level, pattern in _STATUTE_RULES if level == _LEVEL_ARTICLE)
_AUTO_ARTICLE_MIN = 2
_ROMAN_UPPER = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"
_DOCUMENT_RULES = (
    (1, re.compile(rf"^[{_ROMAN_UPPER}][.．](?=\s|$)")),
    (1, re.compile(rf"^제\s*\d+\s*장{_NOT_CITED}")),
    (2, re.compile(r"^\d{1,2}[.．](?=\s|[가-힣A-Za-z])")),
    (3, re.compile(rf"^[{_MOK_LETTERS}][.．](?=\s|[가-힣A-Za-z])")),
    (4, re.compile(r"^\d{1,2}[)）](?=\s|[가-힣A-Za-z])")),
    (5, re.compile(rf"^[{_MOK_LETTERS}][)）](?=\s|[가-힣A-Za-z])")),
    (6, re.compile(r"^[(（]\d{1,2}[)）](?=\s|[가-힣A-Za-z])")),
    (7, re.compile(r"^[①-⑳]")),
)
_DOC_HEADING_MAX_CHARS = 40
_DOC_SENTENCE_END = ("다.", "요.", "다)", "요)", "임.", "함.")
_DOC_MIN_HITS = 2
_DOC_FIRST_ORDINAL = 1
_DOC_BREAK_LEVEL = 2
_DOC_PATH_MAX = 3
_LABEL_MAX_CHARS = 40
_OUTLINE_SEPARATOR = " > "
class HwpxParseError(ValueError):
    pass
@dataclass(frozen=True)
class Block:
    kind: str
    text: str
    section: int
    outline_level: int = 0
    outline_path: tuple = ()
    origin: tuple = ()
    @property
    def is_table(self) -> bool:
        return self.kind == "table"
@dataclass(frozen=True)
class HwpxDocument:
    blocks: list = field(default_factory=list)
    section_count: int = 0
    @property
    def paragraph_count(self) -> int:
        return sum(1 for block in self.blocks if block.kind == "paragraph")
    @property
    def table_count(self) -> int:
        return sum(1 for block in self.blocks if block.is_table)
    def to_markdown(self, max_chars: int = 0) -> str:
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
    match = _SECTION_ENTRY_RE.match(entry_name)
    return int(match.group(1)) if match else None
def _iter_section_xml(hwpx_bytes: bytes):
    with _open(hwpx_bytes) as archive:
        names = [n for n in archive.namelist() if _section_order(n) is not None]
        for name in sorted(names, key=_section_order):
            yield name, archive.read(name)
def _read_entry(hwpx_bytes: bytes, name: str) -> bytes:
    with _open(hwpx_bytes) as archive:
        try:
            return archive.read(name)
        except KeyError:
            return b""
def _parse_xml(xml_bytes: bytes):
    try:
        return etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise HwpxParseError("hwpx 본문 XML 을 해석하지 못했습니다.") from exc
def _nearest_para(node):
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _PARA:
            return parent
        parent = parent.getparent()
    return None
def _inline_text(node) -> str:
    pieces = [_INLINE_CHARS.get(node.tag, ""), node.text or ""]
    for child in node:
        pieces.append(_inline_text(child))
        pieces.append(child.tail or "")
    return "".join(pieces)
def _own_text(para) -> str:
    parts = []
    for node in para.iter():
        if node.tag == _TEXT:
            if _nearest_para(node) is para:
                parts.append(_inline_text(node))
        elif node.tag == _EQUATION and _nearest_para(node) is para:
            parts.extend(script.text or "" for script in node.iter(_SCRIPT))
    text = "".join(parts).replace("\r\n", "\n")
    text = text.replace("\n", _NEWLINE_REPLACEMENT)
    text = text.replace("\t", _NEWLINE_REPLACEMENT)
    return text.strip()
def _children(elem, tag: str) -> list:
    return [child for child in elem if child.tag == tag]
def _int_attr(elem, name: str, default: int) -> int:
    if elem is None:
        return default
    try:
        return int((elem.get(name) or "").strip())
    except ValueError:
        return default
HH_NS = "http://www.hancom.co.kr/hwpml/2011/head"
_HEADING = f"{{{HH_NS}}}heading"
_PARA_PR = f"{{{HH_NS}}}paraPr"
_NUMBERING = f"{{{HH_NS}}}numbering"
_PARA_HEAD = f"{{{HH_NS}}}paraHead"
_BULLET = f"{{{HH_NS}}}bullet"
_HEADING_NUMBERED = ("OUTLINE", "NUMBER")
_HEADING_BULLET = "BULLET"
_ID_NONE = "4294967295"
_BULLET_FALLBACK = "-"
_NUMBER_FALLBACK_TEMPLATE = "^{depth}."
_HEAD_TOKEN_RE = re.compile(r"\^(\d+)")
_HANGUL_SYLLABLES = "가나다라마바사아자차카타파하"
_HANGUL_JAMO = "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"
_ROMAN_UNITS = (
    (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
    (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
)
def _cycle(alphabet: str, number: int) -> str:
    if number < 1:
        return ""
    index, repeat = (number - 1) % len(alphabet), (number - 1) // len(alphabet) + 1
    return alphabet[index] * repeat
def _roman(number: int) -> str:
    if number < 1:
        return ""
    out = []
    for value, letters in _ROMAN_UNITS:
        while number >= value:
            out.append(letters)
            number -= value
    return "".join(out)
def _format_number(number: int, num_format: str) -> str:
    if num_format == "HANGUL_SYLLABLE":
        return _cycle(_HANGUL_SYLLABLES, number)
    if num_format == "HANGUL_JAMO":
        return _cycle(_HANGUL_JAMO, number)
    if num_format == "CIRCLED_DIGIT":
        return chr(0x2460 + number - 1) if 1 <= number <= 20 else str(number)
    if num_format == "CIRCLED_HANGUL_SYLLABLE":
        return chr(0x326E + number - 1) if 1 <= number <= 14 else _cycle(_HANGUL_SYLLABLES, number)
    if num_format == "CIRCLED_HANGUL_JAMO":
        return chr(0x3260 + number - 1) if 1 <= number <= 14 else _cycle(_HANGUL_JAMO, number)
    if num_format == "LATIN_CAPITAL":
        return _cycle("ABCDEFGHIJKLMNOPQRSTUVWXYZ", number)
    if num_format == "LATIN_SMALL":
        return _cycle("abcdefghijklmnopqrstuvwxyz", number)
    if num_format == "ROMAN_CAPITAL":
        return _roman(number).upper()
    if num_format == "ROMAN_SMALL":
        return _roman(number)
    return str(number)
class _Markers:
    def __init__(self, header_xml: bytes = b"") -> None:
        self._para_pr: dict = {}
        self._numbering: dict = {}
        self._bullets: dict = {}
        self._counters: dict = {}
        self._reported: set = set()
        if header_xml:
            try:
                self._load(_parse_xml(header_xml))
            except HwpxParseError:
                _log_warning(
                    "hwpx header.xml unreadable; numbering markers are skipped",
                    event="hwpx_header_unreadable",
                )
    def _load(self, root) -> None:
        for para_pr in root.iter(_PARA_PR):
            heading = para_pr.find(_HEADING)
            if para_pr.get("id") is None or heading is None:
                continue
            self._para_pr[para_pr.get("id")] = (
                heading.get("type") or "NONE",
                heading.get("idRef") or "",
                _int_attr(heading, "level", 0),
            )
        for numbering in root.iter(_NUMBERING):
            levels = {}
            for head in numbering.iter(_PARA_HEAD):
                levels[_int_attr(head, "level", 0)] = (
                    head.text or "",
                    head.get("numFormat") or "DIGIT",
                    _int_attr(head, "start", 1),
                )
            self._numbering[numbering.get("id")] = levels
        for bullet in root.iter(_BULLET):
            self._bullets[bullet.get("id")] = bullet.get("char") or ""
    def _report_once(self, event: str, ref: str) -> None:
        if (event, ref) in self._reported:
            return
        self._reported.add((event, ref))
        _log_warning(
            "hwpx marker definition resolved by fallback", event=event, id_ref=ref
        )
    def _resolve(self, table: dict, ref: str, event: str):
        if ref in table:
            return ref, table[ref]
        if ref == _ID_NONE or not ref.isdigit():
            return ref, None
        order = list(table)
        index = int(ref)
        if index < len(order):
            self._report_once(event, ref)
            return order[index], table[order[index]]
        return ref, None
    def advance(self, para) -> str:
        kind, ref, level = self._para_pr.get(para.get("paraPrIDRef"), ("NONE", "", 0))
        if ref == _ID_NONE:
            return ""
        if kind == _HEADING_BULLET:
            _key, char = self._resolve(self._bullets, ref, "hwpx_bullet_ref_by_index")
            return f"{char or _BULLET_FALLBACK} "
        if kind not in _HEADING_NUMBERED:
            return ""
        num_id, levels = self._resolve(self._numbering, ref, "hwpx_numbering_ref_by_index")
        depth, defined = _head_depth(level, levels)
        counters = self._counters.setdefault(num_id, {})
        _text, _fmt, start = defined.get(depth, ("", "DIGIT", 1))
        counters[depth] = counters.get(depth, start - 1) + 1
        for deeper in [key for key in counters if key > depth]:
            del counters[deeper]
        if depth in defined:
            template = defined[depth][0].strip()
        else:
            self._report_once(
                "hwpx_numbering_definition_missing" if levels is None
                else "hwpx_numbering_level_missing",
                ref,
            )
            template = _NUMBER_FALLBACK_TEMPLATE.format(depth=depth)
        if not template:
            return ""
        return f"{_HEAD_TOKEN_RE.sub(lambda m: _expand_head(m, defined, counters), template)} "
def _head_depth(level: int, levels) -> tuple:
    defined = levels or {}
    if not defined:
        return level + 1, {}
    if level + 1 in defined:
        return level + 1, defined
    keys = sorted(defined)
    if 0 <= level < len(keys):
        return keys[level], defined
    return level + 1, defined
def _expand_head(match, levels: dict, counters: dict) -> str:
    depth = int(match.group(1))
    _text, num_format, start = levels.get(depth, ("", "DIGIT", 1))
    return _format_number(counters.get(depth, start), num_format)
def _marker_of(markers, para) -> str:
    return markers.advance(para) if markers is not None else ""
def _is_box(elem) -> bool:
    return elem.find(_SUBLIST) is not None
def _owning_box(node):
    parent = node.getparent()
    while parent is not None:
        if _is_box(parent):
            return parent
        parent = parent.getparent()
    return None
def _owning_object(node):
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _TBL or _is_box(parent):
            return parent
        parent = parent.getparent()
    return None
def _paras_of(box) -> list:
    return [para for para in box.iter(_PARA) if _owning_box(para) is box]
def _owned_objects(para) -> list:
    box = _owning_box(para)
    return [
        node
        for node in para.iter()
        if (node.tag == _TBL or _is_box(node))
        and _nearest_para(node) is para
        and _owning_object(node) is box
    ]
def _captions_of(obj) -> list:
    return [node for node in obj.iter(_CAPTION) if _owning_object(node) is obj]
def _box_parts(box, markers=None, inherited: str = "") -> list:
    label = _BOX_LABELS.get(box.tag, "") or inherited
    parts = []
    for para in _paras_of(box):
        text = _own_text(para)
        if text:
            parts.append(("text", f"{label}{_marker_of(markers, para)}{text}"))
        for obj in _owned_objects(para):
            if obj.tag == _TBL:
                for caption in _captions_of(obj):
                    parts.extend(_box_parts(caption, markers, label))
                parts.append(("table", obj))
            else:
                parts.extend(_box_parts(obj, markers, label))
    return parts
def _cell_parts(tc, markers=None) -> list:
    parts = []
    for node in tc.iter():
        if node.tag != _PARA and node.tag != _TBL and not _is_box(node):
            continue
        if _owning_object(node) is not tc:
            continue
        if node.tag == _PARA:
            text = _own_text(node)
            if text:
                parts.append(("text", f"{_marker_of(markers, node)}{text}"))
        elif node.tag == _TBL:
            for caption in _captions_of(node):
                parts.extend(_box_parts(caption, markers))
            parts.append(("table", node))
        else:
            parts.extend(_box_parts(node, markers))
    return parts
def _cell_html(tc, markers=None) -> str:
    pieces = []
    previous_was_text = False
    for kind, value in _cell_parts(tc, markers):
        if kind == "text":
            if previous_was_text:
                pieces.append(_CELL_LINE_BREAK)
            pieces.append(_html.escape(value, quote=False))
            previous_was_text = True
        else:
            pieces.append("".join(_table_html(value, markers)))
            previous_was_text = False
    return "".join(pieces)
def _table_grid(tbl) -> tuple:
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
def _table_html(tbl, markers=None) -> list:
    anchors, covered, height, width = _table_grid(tbl)
    if not width or not height:
        return []
    lines = ["<table><tbody>"]
    for row in range(height):
        tag = "th" if row == 0 else "td"
        cells = []
        for col in range(width):
            if (row, col) in covered:
                continue
            anchor = anchors.get((row, col))
            if anchor is None:
                cells.append(f"<{tag}></{tag}>")
                continue
            tc, row_span, col_span = anchor
            attrs = ""
            if row_span > 1:
                attrs += f' rowspan="{row_span}"'
            if col_span > 1:
                attrs += f' colspan="{col_span}"'
            cells.append(f"<{tag}{attrs}>{_cell_html(tc, markers)}</{tag}>")
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines.append("</tbody></table>")
    return lines
def _render_table(tbl, markers=None) -> list:
    return _table_html(tbl, markers)
def _vertical_key(tbl):
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
    if len(tables) < 2:
        return tables
    keys = [_vertical_key(tbl) for tbl in tables]
    if any(key is None for key in keys):
        return tables
    order = sorted(zip(keys, range(len(tables)), tables), key=lambda item: item[:2])
    return [tbl for _key, _index, tbl in order]
def _boxed_text(tbl, markers=None):
    anchors, _covered, _height, _width = _table_grid(tbl)
    if len(anchors) != 1:
        return None
    if any(node is not tbl for node in tbl.iter(_TBL)):
        return None
    (tc, _row_span, _col_span), = anchors.values()
    parts = _cell_parts(tc, markers)
    return "\n".join(value for kind, value in parts if kind == "text").strip()
def parse(hwpx_bytes: bytes) -> HwpxDocument:
    blocks: list = []
    section_count = 0
    markers = _Markers(_read_entry(hwpx_bytes, _HEADER_ENTRY))
    for section_index, (_name, xml_bytes) in enumerate(_iter_section_xml(hwpx_bytes)):
        section_count += 1
        root = _parse_xml(xml_bytes)
        for para in list(root.iter(_PARA)):
            if _nearest_para(para) is not None:
                continue
            _emit_paragraph(para, section_index, blocks, markers)
    return HwpxDocument(blocks=blocks, section_count=section_count)
def _emit_paragraph(para, section_index: int, blocks: list, markers, label: str = "") -> None:
    marker = _marker_of(markers, para)
    text = _own_text(para)
    if text:
        blocks.append(
            Block(kind="paragraph", text=f"{label}{marker}{text}", section=section_index)
        )
    for obj in _in_visual_order(_owned_objects(para)):
        if obj.tag == _TBL:
            _emit_table(obj, section_index, blocks, markers, label)
            continue
        for inner in _paras_of(obj):
            _emit_paragraph(
                inner, section_index, blocks, markers, _BOX_LABELS.get(obj.tag, "") or label
            )
def _emit_table(tbl, section_index: int, blocks: list, markers, label: str = "") -> None:
    for caption in _captions_of(tbl):
        for inner in _paras_of(caption):
            _emit_paragraph(
                inner, section_index, blocks, markers, _BOX_LABELS[_CAPTION] or label
            )
    boxed = _boxed_text(tbl, markers)
    if boxed is not None:
        if boxed:
            blocks.append(
                Block(kind="paragraph", text=f"{label}{boxed}", section=section_index)
            )
        return
    lines = _render_table(tbl, markers)
    if lines:
        blocks.append(Block(kind="table", text="\n".join(lines), section=section_index))
def _match_statute(text: str) -> tuple:
    stripped = text.strip()
    if not stripped:
        return 0, ""
    for level, pattern in _STATUTE_RULES:
        match = pattern.match(stripped)
        if match:
            return level, _outline_label(stripped, match)
    return 0, ""
def _outline_label(stripped: str, match) -> str:
    marker = match.group(0).strip()
    rest = stripped[match.end():].lstrip()
    if rest.startswith("("):
        close = rest.find(")")
        if close != -1:
            return f"{marker}{rest[:close + 1]}"
    if len(stripped) <= _LABEL_MAX_CHARS:
        return stripped
    return marker or stripped[:_LABEL_MAX_CHARS].rstrip()
def _doc_candidate(stripped: str) -> bool:
    if not stripped or len(stripped) > _DOC_HEADING_MAX_CHARS:
        return False
    return not stripped.endswith(_DOC_SENTENCE_END)
def _doc_ordinal(marker: str) -> int:
    digits = re.search(r"\d{1,2}", marker)
    if digits:
        return int(digits.group())
    for char in marker:
        if char in _MOK_LETTERS:
            return _MOK_LETTERS.index(char) + 1
        if char in _ROMAN_UPPER:
            return _ROMAN_UPPER.index(char) + 1
        if "①" <= char <= "⑳":
            return ord(char) - 0x2460 + 1
    return 0
def _document_levels(blocks: list) -> frozenset:
    seen: dict = {}
    for block in blocks:
        if block.kind != "paragraph":
            continue
        stripped = block.text.strip()
        if not _doc_candidate(stripped):
            continue
        for level, pattern in _DOCUMENT_RULES:
            match = pattern.match(stripped)
            if match:
                seen.setdefault(level, []).append(_doc_ordinal(match.group(0)))
                break
    return frozenset(
        level for level, ordinals in seen.items()
        if len(ordinals) >= _DOC_MIN_HITS and ordinals[0] == _DOC_FIRST_ORDINAL
    )
def _match_document(text: str, levels: frozenset) -> tuple:
    stripped = text.strip()
    if not _doc_candidate(stripped):
        return 0, ""
    for level, pattern in _DOCUMENT_RULES:
        match = pattern.match(stripped)
        if match:
            if level not in levels:
                return 0, ""
            return level, _outline_label(stripped, match)
    return 0, ""
def _detect_outline_mode(blocks: list) -> str:
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
    if mode not in _OUTLINE_MODES:
        _log_warning(
            "invalid preprocessor parameter, using default",
            event="hwpx_preprocess_param_invalid",
            error_code="05-00020003",
        )
        mode = _OUTLINE_AUTO
    if mode == _OUTLINE_AUTO:
        mode = _detect_outline_mode(blocks)
    if mode == _OUTLINE_OFF:
        return list(blocks)
    doc_rank: dict = {}
    if mode == _OUTLINE_DOCUMENT:
        levels = _document_levels(blocks)
        if not levels:
            return list(blocks)
        doc_rank = {level: rank for rank, level in enumerate(sorted(levels), start=1)}
    path_max = _DOC_PATH_MAX if doc_rank else _LEVEL_PATH_MAX
    trail: dict = {}
    annotated: list = []
    for block in blocks:
        if block.kind != "paragraph":
            level, label = 0, ""
        elif doc_rank:
            level, label = _match_document(block.text, frozenset(doc_rank))
            level = doc_rank.get(level, 0)
        else:
            level, label = _match_statute(block.text)
        if level:
            trail = {depth: name for depth, name in trail.items() if depth < level}
            if level <= path_max:
                trail[level] = label
        annotated.append(
            replace(
                block,
                outline_level=level,
                outline_path=tuple(trail[depth] for depth in sorted(trail)),
            )
        )
    return annotated
_DEFAULT_MAX_CHARS = 1000
_DEFAULT_OVERLAP_CHARS = 100
_DEFAULT_MIN_CHARS = 40
_TABLE_TITLE_MAX_CHARS = 60
_ROW_ANCHOR_MAX_CHARS = 80
_HTML_CELL_RE = re.compile(r"<(td|th)\b([^>]*)>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
_SPAN_ATTR_RE = re.compile(r"\b(?:row|col)span\s*=", re.IGNORECASE)
_ELLIPSIS = "…"
@dataclass(frozen=True)
class Chunk:
    text: str
    section: int
    kind: str
    table_part: tuple | None = None
    table_title: str = ""
    outline_path: tuple = ()
    origin: tuple = ()
@dataclass
class ChunkOptions:
    max_chars: int = _DEFAULT_MAX_CHARS
    overlap_chars: int = _DEFAULT_OVERLAP_CHARS
    min_chars: int = _DEFAULT_MIN_CHARS
    length: object = len
    outline_break_level: int = _LEVEL_ARTICLE
    outline_prefix: bool = True
    def __post_init__(self) -> None:
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
    cells = _HTML_CELL_RE.findall(row)
    if len(cells) < 2 or _render_row(cells, [inner for _t, _a, inner in cells], ()) != row:
        return []
    return cells
def _render_row(cells: list, values: list, long_columns) -> str:
    pieces = []
    for index, ((tag, attrs, _inner), value) in enumerate(zip(cells, values)):
        if not value and index in long_columns:
            value = _ELLIPSIS
        pieces.append(f"<{tag}{attrs}>{value}</{tag}>")
    return "<tr>" + "".join(pieces) + "</tr>"
def _split_wide_row(row: str, prefix: list, suffix: list, options: ChunkOptions) -> list:
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
                current[column] = segment
            else:
                current = candidate
            filled = True
    rows.append(_render_row(cells, current, long_columns))
    return rows
def _split_html_table(text: str, options: ChunkOptions) -> list:
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
def _extend_origin(base: tuple, extra: tuple) -> tuple:
    if not extra:
        return base
    merged = list(base)
    for item in extra:
        if not any(item is seen for seen in merged):
            merged.append(item)
    return tuple(merged)
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
                origin=block.origin,
            )
        ]
    budget = options.max_chars - _table_prefix_reserve(block, options, title, part=True)
    if budget >= options.max_chars // 2:
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
            origin=block.origin,
        )
        for index, part in enumerate(parts)
    ]
def _table_title_of(block: Block, options: ChunkOptions) -> str:
    text = block.text.strip()
    if not text or "\n" in text or _length(options, text) > _TABLE_TITLE_MAX_CHARS:
        return ""
    return text
def _split_long_text(text: str, options: ChunkOptions) -> list:
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
    out: list = []
    for piece in pieces:
        while _length(options, piece) > options.max_chars:
            out.append(piece[: options.max_chars])
            piece = piece[options.max_chars - options.overlap_chars:]
        if piece:
            out.append(piece)
    return out
def _overlap_tail(text: str, options: ChunkOptions) -> str:
    if options.overlap_chars <= 0:
        return ""
    tail = text[-options.overlap_chars:]
    match = _SENTENCE_END.search(tail)
    return tail[match.end():] if match else tail
def chunk_blocks(blocks: list, options: ChunkOptions | None = None) -> list:
    options = options or ChunkOptions()
    chunks: list = []
    buffer = ""
    buffer_section = 0
    buffer_path: tuple = ()
    buffer_origin: tuple = ()
    table_title = ""
    def flush():
        nonlocal buffer, buffer_origin
        if buffer.strip():
            chunks.append(
                Chunk(
                    text=buffer.strip(),
                    section=buffer_section,
                    kind="paragraph",
                    outline_path=buffer_path,
                    origin=buffer_origin,
                )
            )
        buffer = ""
        buffer_origin = ()
    def start(block: Block):
        nonlocal buffer_section, buffer_path, buffer_origin
        buffer_section = block.section
        buffer_path = block.outline_path
        buffer_origin = ()
    def note(block: Block):
        nonlocal buffer_origin
        buffer_origin = _extend_origin(buffer_origin, block.origin)
    for block in blocks:
        if block.is_table:
            flush()
            chunks.extend(_table_chunks(block, options, title=table_title))
            table_title = ""
            continue
        table_title = _table_title_of(block, options)
        if buffer and block.section != buffer_section:
            flush()
        if (
            options.outline_break_level
            and block.outline_level
            and block.outline_level <= options.outline_break_level
        ):
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
                note(block)
            else:
                if not buffer:
                    start(block)
                buffer = candidate
                note(block)
    flush()
    return _apply_outline_prefix(
        _apply_table_prefix(_drop_heading_only_chunks(_merge_tiny(chunks, options))),
        options,
    )
def _merge_tiny(chunks: list, options: ChunkOptions) -> list:
    merged: list = []
    for chunk in chunks:
        if (
            chunk.kind == "paragraph"
            and merged
            and merged[-1].kind == "paragraph"
            and merged[-1].outline_path == chunk.outline_path
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
                    origin=_extend_origin(previous.origin, chunk.origin),
                )
            )
        else:
            merged.append(chunk)
    return merged
def _drop_heading_only_chunks(chunks: list) -> list:
    kept: list = []
    carried: tuple = ()
    for index, chunk in enumerate(chunks):
        following = chunks[index + 1] if index + 1 < len(chunks) else None
        if (
            chunk.kind == "paragraph"
            and chunk.outline_path
            and chunk.text == chunk.outline_path[-1]
            and following is not None
            and following.outline_path[: len(chunk.outline_path)] == chunk.outline_path
        ):
            carried = _extend_origin(carried, chunk.origin)
            continue
        if carried:
            chunk = replace(chunk, origin=_extend_origin(carried, chunk.origin))
            carried = ()
        kept.append(chunk)
    return kept
def _table_prefix_for(chunk: Chunk) -> str:
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
    prefixed: list = []
    for chunk in chunks:
        prefix = _table_prefix_for(chunk)
        prefixed.append(replace(chunk, text=f"{prefix}\n{chunk.text}") if prefix else chunk)
    return prefixed
def _outline_prefix_for(chunk: Chunk) -> str:
    path = chunk.outline_path
    if path and chunk.text.startswith(path[-1]):
        path = path[:-1]
    return _OUTLINE_SEPARATOR.join(path)
def _apply_outline_prefix(chunks: list, options: ChunkOptions) -> list:
    if not options.outline_prefix:
        return chunks
    prefixed: list = []
    for chunk in chunks:
        prefix = _outline_prefix_for(chunk)
        prefixed.append(replace(chunk, text=f"{prefix}\n\n{chunk.text}") if prefix else chunk)
    return prefixed
def _counts(text: str) -> dict:
    return {
        "n_char": len(text),
        "n_word": len(text.split()),
        "n_line": len(text.splitlines()) or 1,
    }
_RECORD_TYPES = {
    "text": (str,),
    "file_name": (str,),
    "file_path": (str,),
    "reg_date": (str,),
    "source_kind": (str,),
    "table_title": (str,),
    "outline_title": (str,),
    "n_char": (int,),
    "n_word": (int,),
    "n_line": (int,),
    "i_chunk_on_doc": (int,),
    "n_chunk_of_doc": (int,),
    "i_section": (int,),
    "n_section": (int,),
    "i_table_part": (int,),
    "n_table_part": (int,),
    "i_page": (int, type(None)),
    "e_page": (int, type(None)),
    "n_page": (int, type(None)),
    "i_chunk_on_page": (int, type(None)),
    "n_chunk_of_page": (int, type(None)),
    "chunk_bboxes": (str, type(None)),
    "media_files": (str, type(None)),
    "outline_path": (list,),
}
def _check_record_types(records: list) -> None:
    reported: set = set()
    for index, record in enumerate(records):
        for key, value in record.items():
            allowed = _RECORD_TYPES.get(key)
            if allowed is None:
                if value is not None and not isinstance(value, str):
                    if key not in reported:
                        reported.add(key)
                        _log_warning(
                            "extra_metadata value is not a string - the vector DB will "
                            "reject it if the property is text (key=%s type=%s)"
                            % (key, type(value).__name__),
                            event="preprocess_extra_metadata_type",
                        )
                continue
            if isinstance(value, bool) and bool not in allowed:
                raise HwpxParseError(
                    "레코드 필드 타입이 계약과 다릅니다(내부 오류): "
                    "%s=bool (레코드 %d)" % (key, index)
                )
            if not isinstance(value, allowed):
                raise HwpxParseError(
                    "레코드 필드 타입이 계약과 다릅니다(내부 오류): "
                    "%s=%s (레코드 %d)" % (key, type(value).__name__, index)
                )
def to_records(
    chunks: list,
    *,
    file_name: str = "",
    file_path: str = "",
    section_count: int = 0,
    reg_date: str = "",
    extra: dict | None = None,
) -> list:
    stamp = reg_date or datetime.now(timezone.utc).astimezone().isoformat()
    total = len(chunks)
    records = []
    for index, chunk in enumerate(chunks):
        record = {
            "text": chunk.text,
            **_counts(chunk.text),
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
            "file_name": file_name,
            "file_path": file_path,
            "i_section": chunk.section,
            "n_section": section_count,
            "source_kind": chunk.kind,
        }
        if chunk.table_part is not None:
            part_index, part_total = chunk.table_part
            record["i_table_part"] = part_index
            record["n_table_part"] = part_total
        if chunk.table_title:
            record["table_title"] = chunk.table_title
        if chunk.outline_path:
            record["outline_path"] = list(chunk.outline_path)
            record["outline_title"] = chunk.outline_path[-1]
        if extra:
            record.update(extra)
        records.append(record)
    return records
def _int_kwarg(value: Any, default: int, name: str) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        _log_warning(
            "invalid preprocessor parameter, using default",
            event="hwpx_preprocess_param_invalid",
            error_code="05-00020003",
        )
        return default
class HwpxDocumentProcessor:
    SUPPORTED_EXTENSIONS = (".hwpx",)
    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = config_path
    async def __call__(self, request: Any, file_path: str, **kwargs: Any) -> list:
        start = time.monotonic()
        try:
            records = self._process(file_path, **kwargs)
        except HwpxParseError as exc:
            _log_warning(
                "hwpx preprocessing rejected input",
                event="hwpx_preprocess_failed",
                error_code="05-00020003",
                error_type=type(exc).__name__,
            )
            raise
        except Exception as exc:
            _log_warning(
                "hwpx preprocessing failed unexpectedly",
                event="hwpx_preprocess_failed",
                error_code="05-00020003",
                error_type=type(exc).__name__,
            )
            raise HwpxParseError(f"hwpx 처리 중 예기치 못한 오류가 발생했습니다: {exc}") from exc
        _log_info(
            "hwpx preprocessed",
            event="hwpx_preprocess_done",
            item_count=len(records),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        _debug_dump(file_path, records)
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
        mode = str(kwargs.get("outline_mode") or _OUTLINE_AUTO).strip().lower()
        options = ChunkOptions(
            max_chars=_int_kwarg(kwargs.get("chunk_size"), _DEFAULT_MAX_CHARS, "chunk_size"),
            overlap_chars=_int_kwarg(
                kwargs.get("chunk_overlap"), _DEFAULT_OVERLAP_CHARS, "chunk_overlap"
            ),
            outline_break_level=(
                _DOC_BREAK_LEVEL if mode == _OUTLINE_DOCUMENT else _LEVEL_ARTICLE
            ),
        )
        blocks = annotate_outline(document.blocks, mode)
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
                raise HwpxParseError("빈 텍스트 청크가 생성되었습니다(내부 오류).")
        _check_record_types(records)
        return records
_DEBUG_TAG = "[GENON-DEBUG]"
_DEBUG_DUMP_CHARS = 200
def _debug_dump(file_path: str, records: Any, *, engine: str = "hwpx") -> None:
    try:
        rows = records if isinstance(records, list) else []
        head = rows[0] if rows and isinstance(rows[0], dict) else {}
        name = str(head.get("file_name") or "") or os.path.basename(str(file_path or ""))
        first = str(head.get("text") or "")
        print(
            f"{_DEBUG_TAG} engine={engine} file={name} chunks={len(rows)}",
            flush=True,
        )
        print(f"{_DEBUG_TAG} first{_DEBUG_DUMP_CHARS}>>>", flush=True)
        print(first[:_DEBUG_DUMP_CHARS], flush=True)
        print(f"{_DEBUG_TAG} <<<", flush=True)
    except Exception:
        pass
