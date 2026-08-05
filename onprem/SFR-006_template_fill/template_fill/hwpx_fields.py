"""hwpx 템플릿 파서/필러 — lxml 기반. 채울 자리를 찾아 값을 쓴다.

워크플로우(run_chat.py)와 코드 서빙(main.py)이 공유하는 조작 엔진.
GenOS 런타임 의존이 없어 로컬에서 단독 검증 가능하다 (tests/ 참고).

채울 자리는 세 방식으로 찾는다. 실제 템플릿이 어떤 방식으로 만들어졌는지에 따라
쓰이는 경로가 다르고, 한 문서에 섞여 있어도 된다:

1. **라벨 항목**(기본, 현장 템플릿의 실제 방식) — 본문에 그냥 텍스트로 적힌
   `제목: {볼드체, 고딕, 16pt}` 형태. 콜론 앞이 항목명, 뒤의 `{…}` 는 서식 명세다.
   값은 라벨을 남기고 그 뒤에 이어 쓰고(`제목: 2026년 상반기 실적 보고`),
   서식 명세 표기는 작성 지시문이므로 산출물에서 지운다.
2. **누름틀**(CLICK_HERE 필드) — 한/글에서 필드를 심어 만든 템플릿용 폴백.
3. **레거시 `{{token}}`** — 프로토타입 호환.

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

# 토큰명에 한글을 허용한다 — 이 저장소의 필드명은 전부 한글이고, 누름틀 필드명과
# 토큰명은 같은 이름 공간을 쓴다(fill_template 이 values 하나로 둘 다 채운다).
# ASCII 전용 패턴은 {{부서}} 를 못 잡아 조용히 치환되지 않는 결함이 있었다.
TOKEN_RE = re.compile(r"\{\{\s*([^{}\r\n]+?)\s*\}\}")
CLICK_HERE_TYPE = "CLICK_HERE"
NEWLINE_REPLACEMENT = " "  # <hp:t> 안의 \n 은 문단 분리가 아니므로 치환

_PARA = f"{{{HP_NS}}}p"

# ── 라벨 항목 인식 규칙 (결정적) ──────────────────────────────
# `제목: {볼드체, 고딕, 16pt}` / `제목:` / `제목: 이미 적힌 값` 을 한 항목으로 본다.
LABEL_FIELD_TYPE = "LABEL"
# 콜론 앞을 항목명으로 쓰되, 문장을 항목명으로 오인하지 않도록 상한을 둔다.
LABEL_MAX_CHARS = 20
LABEL_MAX_WORDS = 3
_LABEL_LINE_RE = re.compile(r"^\s*([^\s:：][^:：]*?)\s*[:：]\s*(.*)$", re.DOTALL)
_SPEC_BLOCK_RE = re.compile(r"\{[^{}]*\}")
# 항목명에 들어갈 수 없는 문자 — 문장이 콜론을 품은 경우를 걸러낸다.
_LABEL_FORBIDDEN = ".!?\t\r\n"


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


@dataclass
class LabelOccurrence:
    """본문에 텍스트로 적힌 라벨 항목 1개 (`제목: {고딕, 16pt}`).

    누름틀과 달리 XML 상의 경계가 없다 — 문단 하나가 항목 하나다.
    """

    name: str
    spec_text: str      # 서식 명세 표기 `{…}` 원문 (없으면 "")
    current_text: str   # 명세 표기를 뺀 현재 값
    section: str
    para: object = dc_field(default=None, repr=False)
    text_nodes: list = dc_field(default_factory=list, repr=False)

    @property
    def field_type(self) -> str:
        return LABEL_FIELD_TYPE

    @property
    def guide(self) -> str:
        # 서식 명세는 작성 지시문이라 사용자 안내문으로 쓰지 않는다.
        return ""

    @property
    def filled(self) -> bool:
        return bool(self.current_text.strip())


@dataclass(frozen=True)
class FieldSpec:
    """이름 기준으로 합친 필드 스키마 — LLM/사용자에게 보여주는 단위."""

    name: str
    guide: str
    field_type: str
    occurrences: int
    filled: bool        # 모든 occurrence 가 채워졌을 때만 True
    current_value: str  # 채워진 occurrence 의 값 (없으면 "")
    source: str = "field"  # "field"(누름틀) | "label"(본문 라벨 항목)


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


def _nearest_para(node):
    """이 텍스트 노드를 직접 담고 있는 문단. 표 안(hp:tc→hp:subList→hp:p)까지 따라간다."""
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _PARA:
            return parent
        parent = parent.getparent()
    return None


def _own_nodes(para, tag: str) -> list:
    """이 문단에 **직접** 속한 노드만 (표 셀 안의 하위 문단 것은 제외).

    hwpx 표는 hp:p → hp:run → hp:tbl → … → hp:p 로 중첩된다. 그래서 단순히
    para.iter() 를 쓰면 표 전체 텍스트가 한 문단 텍스트로 이어져 라벨 인식이 깨진다.
    """
    return [node for node in para.iter(tag) if _nearest_para(node) is para]


def _is_label_name(label: str) -> bool:
    """항목명으로 인정할 토큰인가 — 콜론을 품은 일반 문장을 걸러낸다."""
    if not label or len(label) > LABEL_MAX_CHARS:
        return False
    if any(ch in label for ch in _LABEL_FORBIDDEN):
        return False
    return len(label.split()) <= LABEL_MAX_WORDS


def _collect_label_occurrences(root, section_name: str) -> list:
    """본문에서 `항목명: …` 형태의 라벨 항목을 문서 순서로 수집한다.

    누름틀이 있는 문단과 레거시 `{{token}}` 문단은 각자의 경로가 처리하므로 건너뛴다
    (같은 자리에 두 경로가 값을 쓰면 문서가 이중으로 채워진다).
    그래서 `작성자: {{작성자}}` 같은 줄은 채우기 전에는 토큰으로만 잡히고, 채운 뒤
    (`작성자: 왕주영`)에는 채워진 라벨 항목으로 보인다 — 두 방식을 섞은 템플릿에서만
    생기는 차이이고, 판정은 양쪽 모두 "채워짐" 이라 부족 항목 계산에는 영향이 없다.
    """
    occurrences: list = []
    for para in root.iter(_PARA):
        if _own_nodes(para, _FIELD_BEGIN):
            continue
        nodes = _own_nodes(para, _TEXT)
        if not nodes:
            continue
        text = "".join((n.text or "") for n in nodes)
        if not text.strip() or "{{" in text:
            continue
        match = _LABEL_LINE_RE.match(text)
        if not match:
            continue
        label = match.group(1).strip()
        if not _is_label_name(label):
            continue
        rest = match.group(2)
        spec_hit = _SPEC_BLOCK_RE.search(rest)
        occurrences.append(
            LabelOccurrence(
                name=label,
                spec_text=spec_hit.group(0) if spec_hit else "",
                current_text=_SPEC_BLOCK_RE.sub("", rest).strip(),
                section=section_name,
                para=para,
                text_nodes=nodes,
            )
        )
    return occurrences


def _write_label(occ: LabelOccurrence, value: str) -> None:
    """라벨 문단을 `항목명: 값` 으로 다시 쓴다 (서식 명세 표기는 지운다).

    문단의 첫 hp:t 에 완성된 한 줄을 넣고 나머지 hp:t 를 비운다 — 라벨이 여러 run 에
    쪼개져 있을 수 있어서(`제목` / `: ` / `{…}`) 노드별 부분 치환은 신뢰할 수 없다.
    첫 run 을 그대로 쓰므로 charPrIDRef 가 유지되고, 이후 hwpx_style 이 이 문단에
    서식 명세를 적용한다.
    """
    if not occ.text_nodes:
        return
    # LLM 이 값에 항목명을 다시 붙여 보내도(`제목: 실적 보고`) 문서가 `제목: 제목: …` 이
    # 되지 않게 코드가 떼어낸다 — 프롬프트 지시만으로 보장하지 않는다 (CLAUDE.md §5).
    text = value.strip()
    for separator in (":", "："):
        prefix = occ.name + separator
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    occ.text_nodes[0].text = f"{occ.name}: {text}".rstrip()
    for node in occ.text_nodes[1:]:
        node.text = ""


def _strip_label_spec(occ: LabelOccurrence) -> None:
    """값을 채우지 않는 라벨에서도 서식 명세 표기만 지운다.

    명세는 문서 작성 지시문이라 산출물에 남아선 안 된다 — 부분 초안이어도 마찬가지다.
    """
    if not occ.spec_text or not occ.text_nodes:
        return
    _write_label(occ, occ.current_text)


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
def _ordered_occurrences(root, section_name: str, include_types: tuple, include_labels: bool) -> list:
    """한 섹션의 누름틀·라벨 항목을 문서 등장 순서로 합친다.

    사용자에게 "이어서 ○○ 알려주세요" 로 묻는 순서가 문서 순서와 같아야 하므로,
    두 경로를 따로 붙이지 않고 XML 등장 위치로 정렬한다.
    """
    # 순회 결과를 리스트로 붙들어 둔다 — lxml 프록시는 참조가 끊기면 회수되고 id 가
    # 재사용되므로, 살려두지 않으면 위치 맵이 다른 노드를 가리킨다.
    walked = list(root.iter())
    position = {id(elem): idx for idx, elem in enumerate(walked)}
    items: list = []
    for occ in _collect_occurrences(root, section_name):
        if include_types and occ.field_type not in include_types:
            continue
        items.append((position.get(id(occ.begin_elem), 0), occ))
    if include_labels:
        for occ in _collect_label_occurrences(root, section_name):
            items.append((position.get(id(occ.para), 0), occ))
    items.sort(key=lambda pair: pair[0])
    return [occ for _, occ in items]


def scan_fields(
    hwpx_bytes: bytes,
    include_types: tuple = (CLICK_HERE_TYPE,),
    include_labels: bool = True,
) -> list:
    """hwpx 전체에서 채울 항목 스키마(FieldSpec 목록)를 추출한다.

    Args:
        hwpx_bytes: 템플릿 hwpx 파일 바이트.
        include_types: 노출할 누름틀 field type. 기본은 CLICK_HERE 만.
        include_labels: 본문에 텍스트로 적힌 `항목명: {서식}` 라벨 항목도 포함할지.

    Returns:
        문서 등장 순서를 유지한 FieldSpec 목록 (이름 기준 dedup).
        같은 이름이 누름틀과 라벨로 함께 있으면 누름틀 쪽을 대표로 본다.
    """
    merged: dict = {}
    order: list = []
    for section_name, xml_bytes in _iter_section_xml(hwpx_bytes):
        root = _parse_xml(xml_bytes, section_name)
        for occ in _ordered_occurrences(root, section_name, include_types, include_labels):
            if occ.name not in merged:
                merged[occ.name] = []
                order.append(occ.name)
            merged[occ.name].append(occ)

    specs = []
    for name in order:
        occs = merged[name]
        filled_values = [o.current_text.strip() for o in occs if o.filled]
        click_here = next((o for o in occs if o.field_type == CLICK_HERE_TYPE), None)
        representative = click_here or occs[0]
        specs.append(
            FieldSpec(
                name=name,
                guide=next((o.guide for o in occs if o.guide), ""),
                field_type=representative.field_type,
                occurrences=len(occs),
                filled=all(o.filled for o in occs),
                current_value=filled_values[0] if filled_values else "",
                source="field" if click_here is not None else "label",
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


def fill_template(hwpx_bytes: bytes, values: dict, include_labels: bool = True) -> FillResult:
    """values 로 라벨 항목·누름틀·{{token}} 을 채운 새 hwpx 바이트를 만든다.

    값이 없는 항목은 그대로 남긴다 (부분 초안 허용 — 다운로드 후 사용자가 한/글에서
    이어서 작성). 단 라벨 항목의 **서식 명세 표기는 값이 없어도 지운다** — 명세는
    작성 지시문이라 산출 문서에 남아선 안 된다.

    Args:
        values: {항목명(또는 토큰명): 값}. 값은 문자열로 정규화된다.
        include_labels: 본문 라벨 항목(`항목명: {서식}`)도 채울지.

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

    try:
        src_zip = zipfile.ZipFile(io.BytesIO(hwpx_bytes), "r")
    except zipfile.BadZipFile as exc:
        # 업로드 파일이 hwpx(ZIP)가 아닌 경우 — 내부 오류가 아니라 입력 오류다
        raise TemplateError("hwpx 파일이 아니거나 손상된 파일입니다.") from exc
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
                if include_labels:
                    # 누름틀이 이미 채운 이름은 건너뛴다 — 같은 값을 두 자리에 쓰지 않는다.
                    for label_occ in _collect_label_occurrences(root, item.filename):
                        known_names.add(label_occ.name)
                        if label_occ.name in written:
                            _strip_label_spec(label_occ)
                        elif label_occ.name in str_values:
                            _write_label(label_occ, str_values[label_occ.name])
                            written.add(label_occ.name)
                        else:
                            _strip_label_spec(label_occ)
                            if not label_occ.filled:
                                missing.add(label_occ.name)
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
    # 같은 이름이 여러 자리(누름틀+라벨)에 있을 때, 한 자리라도 채웠으면 부족이 아니다
    missing -= written
    return FillResult(
        hwpx_bytes=out_bytes,
        written_fields=sorted(written),
        missing_fields=sorted(missing),
        unknown_keys=sorted(unknown),
        leftover_tokens=sorted(scan_tokens(out_bytes)),
    )
