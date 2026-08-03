"""hwpx 누름틀(CLICK_HERE 필드) 파서/필러 — lxml 기반.

워크플로우(run_chat.py)와 코드 서빙(main.py)이 공유하는 조작 엔진.
GenOS 런타임 의존이 없어 로컬에서 단독 검증 가능하다 (tests/ 참고).

도메인 지식 (CLAUDE.md §3 — 매번 다시 알아내지 말 것):
- hwpx = ZIP + XML. 본문은 Contents/section{N}.xml
- hp 네임스페이스는 태그 식별자일 뿐 네트워크 주소가 아니다 (폐쇄망 접속 금지)
- 문단 id는 전부 중복(2147483648)이라 신뢰 불가 → id 기반 주소 지정 금지.
  누름틀 fieldBegin/fieldEnd 짝은 문서 순서 스택 매칭이 기본이고,
  beginIDRef 가 있으면 보조로만 사용한다.
- mimetype 엔트리는 무압축(STORED) 규약 유지, XML 선언 유지

누름틀의 XML 구조 (OWPML):
    <hp:run><hp:ctrl>
      <hp:fieldBegin id="..." type="CLICK_HERE" name="필드명" ...>
        <hp:parameters><hp:stringParam name="...">안내문</hp:stringParam></hp:parameters>
      </hp:fieldBegin>
    </hp:ctrl></hp:run>
    <hp:run><hp:t>현재 표시 텍스트(미입력이면 안내문과 동일)</hp:t></hp:run>
    <hp:run><hp:ctrl><hp:fieldEnd beginIDRef="..."/></hp:ctrl></hp:run>

"채워짐" 판단: begin~end 사이 텍스트가 비어 있지 않고 안내문과 다르면 채워진 것.

레거시 {{token}} 템플릿(SFR-006/hwpx.py 프로토타입 방식)도 함께 지원한다 —
스칼라 토큰 치환만. 반복 블록 복제는 이 모듈 범위 밖.
"""

import io
import re
import zipfile
from copy import deepcopy
from dataclasses import dataclass, field as dc_field

from lxml import etree

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_FIELD_BEGIN = f"{{{HP_NS}}}fieldBegin"
_FIELD_END = f"{{{HP_NS}}}fieldEnd"
_TEXT = f"{{{HP_NS}}}t"
_RUN = f"{{{HP_NS}}}run"
_STRING_PARAM = f"{{{HP_NS}}}stringParam"

TOKEN_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
CLICK_HERE_TYPE = "CLICK_HERE"
NEWLINE_REPLACEMENT = " "  # <hp:t> 안의 \n 은 문단 분리가 아니므로 치환


class TemplateError(ValueError):
    """템플릿 파일 해석 실패 (ZIP/XML 손상 등).

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다.
    호출부가 사용자 노출 오류(user_msg)로 그대로 쓸 수 있어야 하기 때문.
    """


@dataclass
class FieldOccurrence:
    """섹션 XML 안의 누름틀 1개 (같은 이름이 여러 번 나올 수 있다)."""

    name: str
    guide: str          # 안내문 (stringParam)
    field_type: str     # CLICK_HERE 등
    current_text: str   # begin~end 사이 현재 텍스트
    section: str        # Contents/section0.xml 등
    # 내부용 — 채우기 시 조작할 lxml 노드 (스캔 전용 경로에서는 비어 있음)
    text_nodes: list = dc_field(default_factory=list, repr=False)
    begin_elem: object = dc_field(default=None, repr=False)

    @property
    def filled(self) -> bool:
        text = self.current_text.strip()
        return bool(text) and text != self.guide.strip()


@dataclass(frozen=True)
class FieldSpec:
    """이름 기준으로 합친 필드 스키마 — LLM/사용자에게 보여주는 단위."""

    name: str
    guide: str
    field_type: str
    occurrences: int
    filled: bool        # 모든 occurrence 가 채워졌을 때만 True
    current_value: str  # 채워진 occurrence 의 값 (없으면 "")


@dataclass
class FillResult:
    hwpx_bytes: bytes
    written_fields: list      # 이번에 값이 기록된 필드명
    missing_fields: list      # 값이 없어서 안내문 상태로 남은 필드명
    unknown_keys: list        # 템플릿에 존재하지 않는 values 키
    leftover_tokens: list     # 치환되지 않고 남은 {{token}}


# ─────────────────────────────────────────────────────────────
# XML 파싱
# ─────────────────────────────────────────────────────────────
def _first_string_param_text(begin_elem) -> str:
    """fieldBegin 하위 첫 stringParam 텍스트 = 누름틀 안내문.

    파라미터 name 속성이 한/글 버전에 따라 다를 수 있어(ClickHere 등)
    이름을 고정 매칭하지 않고 첫 stringParam 을 안내문으로 본다.
    """
    for param in begin_elem.iter(_STRING_PARAM):
        return (param.text or "").strip()
    return ""


def _collect_occurrences(root, section_name: str) -> list:
    """섹션 XML 에서 누름틀 occurrence 목록을 문서 순서로 수집한다.

    fieldBegin/fieldEnd 짝은 스택으로 매칭한다 (beginIDRef 는 보조 검증).
    중첩 필드는 텍스트를 모든 열린 필드에 귀속시킨다.
    """
    occurrences: list = []
    stack: list = []  # (begin_elem, record)

    for elem in root.iter():
        if elem.tag == _FIELD_BEGIN:
            record = FieldOccurrence(
                name=(elem.get("name") or "").strip(),
                guide=_first_string_param_text(elem),
                field_type=(elem.get("type") or "").strip(),
                current_text="",
                section=section_name,
                begin_elem=elem,
            )
            stack.append(record)
        elif elem.tag == _FIELD_END:
            if not stack:
                continue  # 짝 없는 fieldEnd — 손상 문서지만 스캔은 계속한다
            begin_id_ref = (elem.get("beginIDRef") or "").strip()
            record = stack.pop()
            begin_id = (record.begin_elem.get("id") or "").strip()
            if begin_id_ref and begin_id and begin_id_ref != begin_id:
                # id 불일치 — 문단 id 중복 문제(§3.2)와 같은 계열이므로
                # 스택(문서 순서) 매칭을 신뢰하고 그대로 진행한다.
                pass
            record.current_text = "".join(
                (t.text or "") for t in record.text_nodes
            ).strip()
            occurrences.append(record)
        elif elem.tag == _TEXT and stack:
            # fieldBegin 을 담은 ctrl 내부의 텍스트는 안내문 파라미터이므로 제외
            for open_record in stack:
                if open_record.begin_elem is not None and _is_descendant(
                    elem, open_record.begin_elem
                ):
                    break
            else:
                for open_record in stack:
                    open_record.text_nodes.append(elem)

    # 이름이 빈 누름틀 → 안내문/순번으로 대체 이름 부여 (LLM 이 지칭할 수 있어야 함)
    unnamed = 0
    for record in occurrences:
        if not record.name:
            unnamed += 1
            record.name = record.guide or f"field_{unnamed}"
    return occurrences


def _is_descendant(elem, ancestor) -> bool:
    parent = elem.getparent()
    while parent is not None:
        if parent is ancestor:
            return True
        parent = parent.getparent()
    return False


def _iter_section_xml(hwpx_bytes: bytes):
    """(엔트리명, xml bytes) 를 순회. ZIP/XML 손상은 TemplateError 로 변환."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(hwpx_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise TemplateError("hwpx 파일이 아니거나 손상된 파일입니다.") from exc
    with zf:
        for name in sorted(zf.namelist()):
            if name.startswith("Contents/") and name.endswith(".xml"):
                yield name, zf.read(name)


def _parse_xml(xml_bytes: bytes, section_name: str):
    try:
        return etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise TemplateError("템플릿 본문 XML 을 해석하지 못했습니다.") from exc


# ─────────────────────────────────────────────────────────────
# 스캔 (읽기 전용)
# ─────────────────────────────────────────────────────────────
def scan_fields(hwpx_bytes: bytes, include_types: tuple = (CLICK_HERE_TYPE,)) -> list:
    """hwpx 전체에서 누름틀 필드 스키마(FieldSpec 목록)를 추출한다.

    Args:
        hwpx_bytes: 템플릿 hwpx 파일 바이트.
        include_types: 노출할 필드 type. 기본은 누름틀(CLICK_HERE)만.

    Returns:
        문서 등장 순서를 유지한 FieldSpec 목록 (이름 기준 dedup).
    """
    merged: dict = {}
    order: list = []
    for section_name, xml_bytes in _iter_section_xml(hwpx_bytes):
        root = _parse_xml(xml_bytes, section_name)
        for occ in _collect_occurrences(root, section_name):
            if include_types and occ.field_type not in include_types:
                continue
            if occ.name not in merged:
                merged[occ.name] = []
                order.append(occ.name)
            merged[occ.name].append(occ)

    specs = []
    for name in order:
        occs = merged[name]
        filled_values = [o.current_text.strip() for o in occs if o.filled]
        specs.append(
            FieldSpec(
                name=name,
                guide=next((o.guide for o in occs if o.guide), ""),
                field_type=occs[0].field_type,
                occurrences=len(occs),
                filled=all(o.filled for o in occs),
                current_value=filled_values[0] if filled_values else "",
            )
        )
    return specs


def scan_tokens(hwpx_bytes: bytes) -> set:
    """레거시 {{token}} 집합 스캔 (hwpx.py 프로토타입 호환)."""
    tokens: set = set()
    for _, xml_bytes in _iter_section_xml(hwpx_bytes):
        tokens.update(TOKEN_RE.findall(xml_bytes.decode("utf-8", errors="replace")))
    return tokens


# ─────────────────────────────────────────────────────────────
# 채우기
# ─────────────────────────────────────────────────────────────
def _normalize_value(value) -> str:
    text = str(value if value is not None else "")
    return text.replace("\r\n", "\n").replace("\n", NEWLINE_REPLACEMENT)


def _write_occurrence(occ: FieldOccurrence, value: str) -> None:
    """begin~end 사이 텍스트를 value 로 교체한다.

    첫 hp:t 에 값을 넣고 나머지는 비운다 (run 서식은 deepcopy 없이 그대로 보존).
    사이에 hp:t 가 하나도 없으면 begin run 을 복제해 새 run/t 를 삽입한다 —
    새 run 을 맨바닥에서 만들면 charPrIDRef 가 빠져 서식이 깨진다 (§3.4 패턴).
    """
    if occ.text_nodes:
        occ.text_nodes[0].text = value
        for t in occ.text_nodes[1:]:
            t.text = ""
        return

    begin_run = occ.begin_elem.getparent().getparent()  # fieldBegin ← ctrl ← run
    if begin_run is None or begin_run.tag != _RUN:
        return
    new_run = deepcopy(begin_run)
    for child in list(new_run):
        new_run.remove(child)
    t = etree.SubElement(new_run, _TEXT)
    t.text = value
    parent = begin_run.getparent()
    parent.insert(parent.index(begin_run) + 1, new_run)


def _fill_scalar_tokens(root, values: dict, written: set) -> None:
    """모든 hp:t 텍스트에서 {{token}} 치환. 값이 없는 토큰은 건드리지 않는다."""
    for t in root.iter(_TEXT):
        if not t.text or "{{" not in t.text:
            continue
        new_text = t.text
        for name in set(TOKEN_RE.findall(new_text)):
            if name not in values:
                continue
            new_text = new_text.replace(
                "{{" + name + "}}", _normalize_value(values[name])
            )
            written.add(name)
        t.text = new_text  # lxml 이 escape 자동 처리


def fill_template(hwpx_bytes: bytes, values: dict) -> FillResult:
    """values 로 누름틀과 {{token}} 을 채운 새 hwpx 바이트를 만든다.

    값이 없는 필드는 안내문 상태 그대로 남긴다 (부분 초안 허용 —
    다운로드 후 사용자가 한/글에서 남은 누름틀을 눌러 이어서 작성)
    Args:
        values: {필드명(또는 토큰명): 값}. 값은 문자열로 정규화된다.

    Raises:
        TemplateError: ZIP/XML 손상.
    """
    str_values = {
        k: _normalize_value(v)
        for k, v in values.items()
        if v is not None and not isinstance(v, (list, dict))
    }

    written: set = set()
    missing: set = set()
    known_names: set = set()

    src_zip = zipfile.ZipFile(io.BytesIO(hwpx_bytes), "r")
    buf = io.BytesIO()
    with src_zip, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src_zip.infolist():
            data = src_zip.read(item.filename)
            if item.filename.startswith("Contents/") and item.filename.endswith(".xml"):
                root = _parse_xml(data, item.filename)
                for occ in _collect_occurrences(root, item.filename):
                    if occ.field_type != CLICK_HERE_TYPE:
                        continue
                    known_names.add(occ.name)
                    if occ.name in str_values:
                        _write_occurrence(occ, str_values[occ.name])
                        written.add(occ.name)
                    elif not occ.filled:
                        missing.add(occ.name)
                _fill_scalar_tokens(root, str_values, written)
                data = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
            compress = (
                zipfile.ZIP_STORED if item.filename == "mimetype"
                else zipfile.ZIP_DEFLATED  # mimetype 무압축 규약 (§3.1)
            )
            dst.writestr(item.filename, data, compress_type=compress)

    out_bytes = buf.getvalue()
    known_names.update(scan_tokens(hwpx_bytes))
    unknown = [k for k in str_values if k not in written and k not in known_names]
    return FillResult(
        hwpx_bytes=out_bytes,
        written_fields=sorted(written),
        missing_fields=sorted(missing),
        unknown_keys=sorted(unknown),
        leftover_tokens=sorted(scan_tokens(out_bytes)),
    )
