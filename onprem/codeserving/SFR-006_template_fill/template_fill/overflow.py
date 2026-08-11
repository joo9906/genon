"""표 셀 슬롯의 **값 넘침** 판정 — 채우기 전에 잰다.

**왜.** 006 은 값이 자리에 들어가는지를 한 번도 재지 않았다. 표 안 슬롯은 채울 항목으로
그대로 인식되고 LLM 이 값을 만들어 넣는데, 셀 폭보다 긴 값이 들어가면 줄이 늘고 행이
자라 **뒷장 전체가 밀린다.** 화면 미리보기는 마크다운이라 이게 보이지 않고, 사용자는
한/글에서 열어 보고서야 안다.

**무엇을 쓰나.** 측정 코어는 벤더 사본 `_vendor/hwpx/form_fit/measure.py` 다. 셀 폭에서
좌우 여백과 인라인 개체 폭을 빼고, 글꼴 크기·줄간격으로 값의 예상 폭·줄 수를 낸다.
폭 추정은 한/글 자신의 `lineSeg/@horzsize` 와 대조해 맞춘 모델이라(±10 HWPUNIT, 셀 82%)
우리가 다시 만들 이유가 없는 부분이다. 사본을 둔 이유는 `_vendor/README.md` 에 있다.

**문서 모델은 우리 것이다.** 상류 `resolve_slot_metrics` 는 셀·문서를 duck-typing 으로
받으므로(`cell.width`/`cell.element`/`cell.paragraphs`, `document.char_property`),
그 자리에 이 파일의 얇은 lxml 어댑터를 끼운다. 상류 `HwpxDocument` 를 쓰면 문서 모델
40k 줄이 통째로 따라오는데, 우리는 이미 `hwpx_fields` 로 같은 문서를 파싱하고 있다.
**슬롯 판정은 `hwpx_fields.slot_occurrences` 하나뿐이다** — 넘침을 재는 자리와 값을 채우는
자리가 어긋나지 않는다.

**본문 문단 슬롯은 재지 않는다.** 문단은 넘치면 다음 줄로 흐를 뿐 레이아웃이 깨지지
않는다. 재는 대상은 폭이 고정된 표 셀이다.

**절대 막지 않는다 — 경고만.** 추정에는 불확실 구간(`confidence`)이 있고, 폰트 대체나
자간 설정에 따라 실제 결과가 다를 수 있다. 값이 길다는 이유로 문서 생성을 거절하면
"긴 제목을 못 쓰는 기능"이 된다. 판정은 사용자·UI 에 넘긴다.

측정 실패도 마찬가지로 넘침 없음으로 돌린다 — 이 검사는 부가 정보이고, 여기서 예외가
올라가면 문서 생성 전체가 값 길이 때문에 죽는다. 대신 그 사실을 로그로 드러낸다.
"""

from dataclasses import dataclass

from lxml import etree

from ._vendor.hwpx.form_fit import measure, resolve_slot_metrics
from .hwpx_fields import (
    HP_NS,
    open_hwpx,
    parse_xml,
    section_order,
    slot_occurrences,
)
from .hwpx_style import HEADER_ENTRY, HH_NS
from .logging_utils import log_warning

# 표 셀 슬롯은 한 줄에 들어가는 것을 기준으로 본다. 셀이 여러 줄을 허용해도, 템플릿이
# 한 줄로 설계한 칸에 두 줄이 들어가면 그 행이 자라 아래가 밀린다 — 그 순간을 잡는 것이
# 이 검사의 목적이다.
_MAX_LINES = 1

_PARA = f"{{{HP_NS}}}p"
_RUN = f"{{{HP_NS}}}run"
_TEXT = f"{{{HP_NS}}}t"
_TBL = f"{{{HP_NS}}}tbl"
_CELL = f"{{{HP_NS}}}tc"
# `hp:tbl` 의 직속 셀만. `table.iter(_CELL)` 로 훑으면 중첩 표의 셀을 부모 표에서 한 번 더
# 잡는데, `root.iter(_TBL)` 이 그 중첩 표 자체를 이미 따로 주므로 같은 셀을 두 번 재게 된다.
_CELL_ROW_PATH = f"{{{HP_NS}}}tr/{{{HP_NS}}}tc"
_CELL_SZ = f"{{{HP_NS}}}cellSz"
_CELL_SPAN = f"{{{HP_NS}}}cellSpan"

_CHAR_PR = f"{{{HH_NS}}}charPr"
_PARA_PR = f"{{{HH_NS}}}paraPr"
_LINE_SPACING = f"{{{HH_NS}}}lineSpacing"


@dataclass
class OverflowWarning:
    """값이 자리를 넘칠 것으로 추정되는 항목 하나."""

    field: str            # 항목명 (슬롯 따옴표 안 문자열)
    lines: int            # 예상 줄 수
    ratio: float          # 필요 폭 / 사용 가능 폭 (1.0 초과면 넘침)
    confidence: str       # 측정기의 추정 신뢰도 (high / low)

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "lines": self.lines,
            "ratio": round(self.ratio, 3),
            "confidence": self.confidence,
        }


# ── 벤더 측정기에 물릴 어댑터 ────────────────────────────────
# 상류 `resolve_slot_metrics` 가 duck-typing 으로 요구하는 표면만 채운다. 필드 이름은
# 상류 계약이므로 바꾸지 않는다 — 여기가 어긋나면 측정이 조용히 기본값으로 떨어진다
# (상류가 `getattr(..., 기본값)` 으로 방어하기 때문에 예외가 나지 않는다).
@dataclass(frozen=True)
class _CharProperty:
    attributes: dict


@dataclass(frozen=True)
class _LineSpacing:
    value: str | None
    spacing_type: str | None


@dataclass(frozen=True)
class _ParaProperty:
    line_spacing: object | None


@dataclass(frozen=True)
class _RunView:
    char_pr_id_ref: str | None


@dataclass(frozen=True)
class _ParaView:
    para_pr_id_ref: str | None
    runs: list


class _StyleBook:
    """header.xml 의 서식 정의 조회 — 상류의 `document` 자리에 들어간다."""

    def __init__(self, head) -> None:
        self._char: dict = {}
        self._para: dict = {}
        for elem in head.iter(_CHAR_PR):
            key = elem.get("id")
            if key is not None:
                self._char[key] = _CharProperty(attributes=dict(elem.attrib))
        for elem in head.iter(_PARA_PR):
            key = elem.get("id")
            if key is None:
                continue
            spacing = elem.find(_LINE_SPACING)
            self._para[key] = _ParaProperty(
                line_spacing=(
                    None
                    if spacing is None
                    else _LineSpacing(
                        value=spacing.get("value"),
                        spacing_type=spacing.get("type"),
                    )
                )
            )

    def char_property(self, ref):
        return self._char.get(str(ref))

    def paragraph_property(self, ref):
        return self._para.get(str(ref))


class _CellView:
    """`hp:tc` 하나를 상류 측정기가 기대하는 셀 모양으로 감싼다."""

    def __init__(self, cell, paragraphs: list) -> None:
        self.element = cell
        size = cell.find(_CELL_SZ)
        self.width = _to_float(size.get("width")) if size is not None else 0.0
        self.height = _to_float(size.get("height")) if size is not None else 0.0
        span = cell.find(_CELL_SPAN)
        # (rowSpan, colSpan) — 상류는 [0](행 병합)만 본다. 병합 셀의 cellSz.height 는
        # 병합된 전체가 아니라 한 행 조각이라 세로 예산으로 쓸 수 없다는 판정에 쓰인다.
        self.span = (
            _to_int(span.get("rowSpan"), 1) if span is not None else 1,
            _to_int(span.get("colSpan"), 1) if span is not None else 1,
        )
        self.paragraphs = [
            _ParaView(
                para_pr_id_ref=para.get("paraPrIDRef"),
                runs=[
                    _RunView(char_pr_id_ref=run.get("charPrIDRef"))
                    for run in para.iterfind(_RUN)
                ],
            )
            for para in paragraphs
        ]


def _to_float(raw) -> float:
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def _to_int(raw, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# ── 문서 순회 ────────────────────────────────────────────────
def _nearest_cell(node):
    """이 노드를 직접 담고 있는 표 셀 (중첩 표면 안쪽 셀)."""
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _CELL:
            return parent
        parent = parent.getparent()
    return None


def _own_paragraphs(cell) -> list:
    """이 셀이 **직접** 가진 문단만 — 중첩 표 안 문단은 그 표의 셀 것이다.

    `hwpx_fields.own_nodes` 가 문단 소유를 판정하는 것과 같은 이유다. 중첩 문단을 섞으면
    안쪽 표의 값을 바깥 셀 폭으로 재게 된다 (안쪽이 더 좁으므로 넘침을 놓친다).
    """
    return [para for para in cell.iter(_PARA) if _nearest_cell(para) is cell]


def _slot_font_pt(occurrence, styles: _StyleBook) -> float | None:
    """슬롯이 **자기 run 에** 걸고 있는 글꼴 크기(pt). 못 찾으면 None.

    셀의 첫 run 을 쓰면 안 된다. 이 검사는 `document.build` 에서 **서식 적용 뒤**
    템플릿을 받으므로(`styled_template`), 슬롯 run 에는 이미 `{'제목', 16pt}` 가 만든
    charPr 이 걸려 있다. 같은 셀 첫 run 은 대개 라벨(`제 목 : `)의 10pt 라, 그것으로
    재면 16pt 값을 10pt 로 재어 넘침을 놓친다.
    """
    offset = 0
    for node in occurrence.text_nodes:
        length = len(node.text or "")
        if offset <= occurrence.start < offset + length:
            run = node.getparent()
            if run is not None and run.tag == _RUN:
                prop = styles.char_property(run.get("charPrIDRef"))
                height = prop.attributes.get("height") if prop is not None else None
                try:
                    return int(height) / 100.0 if height else None
                except (TypeError, ValueError):
                    return None
            return None
        offset += length
    return None


def _check_cell(cell, styles: _StyleBook, values: dict) -> list:
    """셀 하나 안의 슬롯들을 잰다.

    한 셀에 슬롯이 둘 이상이면(`{'소속'} {'성명'}`) **합친 길이**로 재야 맞지만, 지금은
    항목별로 잰다 — 어느 항목이 문제인지 알려 주는 쪽이 사용자에게 쓸모 있고, 합산은
    "둘 다 짧은데 합쳐서 넘침" 이라는 보고할 곳 없는 경고를 만든다. 같은 이유로 라벨
    (`제 목 : `)이 차지하는 폭도 빼지 않는다. 한 칸에 여러 항목을 두는 템플릿이 실제로
    나오면 그때 합산 경고를 따로 붙인다.
    """
    paragraphs = _own_paragraphs(cell)
    if not paragraphs:
        return []

    occurrences: list = []
    for para in paragraphs:
        occurrences.extend(slot_occurrences(para))
    if not occurrences:
        return []

    view = _CellView(cell, paragraphs)
    found: list = []
    for occurrence in occurrences:
        value = values.get(occurrence.name)
        if not isinstance(value, str) or not value.strip():
            continue
        slot = resolve_slot_metrics(
            view,
            styles,
            max_lines=_MAX_LINES,
            font_pt=_slot_font_pt(occurrence, styles),
        )
        result = measure(value, slot)
        if result.fits:
            continue
        found.append(
            OverflowWarning(
                field=occurrence.name,
                lines=result.lines,
                ratio=result.ratio,
                confidence=result.confidence,
            )
        )
    return found


def check(template_bytes: bytes, values: dict, label: str = "") -> list:
    """템플릿의 표 셀 슬롯에 값을 넣었을 때 넘치는 항목을 낸다.

    **채우기 전 템플릿**을 본다 — 채운 뒤에는 `{…}` 가 사라져 어느 셀이 어느 항목이었는지
    알 수 없다(`document.build` 의 서식·채우기 순서와 같은 이유).
    """
    if not values:
        return []

    try:
        archive = open_hwpx(template_bytes)
    except Exception as exc:  # noqa: BLE001 - 측정 실패가 문서 생성을 막지 않게
        log_warning(
            "넘침 측정을 위해 템플릿을 열지 못했다 — 측정 없이 진행",
            event="overflow_open_failed",
            resource_id=label,
            error_type=type(exc).__name__,
        )
        return []

    warnings: list = []
    try:
        with archive:
            styles = _StyleBook(parse_xml(archive.read(HEADER_ENTRY)))
            for name in archive.namelist():
                if section_order(name) is None:  # 본문만 (판정은 hwpx_fields 가 정본)
                    continue
                root = parse_xml(archive.read(name))
                # `root.iter` 는 중첩 표까지 평평하게 준다. 중첩 셀은 부모 셀 폭에 갇혀
                # 오히려 더 좁으므로, 빼면 가장 넘치기 쉬운 자리를 놓친다.
                for table in root.iter(_TBL):
                    for cell in table.iterfind(_CELL_ROW_PATH):
                        warnings.extend(_check_cell(cell, styles, values))
    except (KeyError, etree.XMLSyntaxError, ValueError, OSError) as exc:
        log_warning(
            "넘침 측정 중 예외 — 측정 없이 진행",
            event="overflow_measure_failed",
            resource_id=label,
            error_type=type(exc).__name__,
        )
        return []

    if warnings:
        log_warning(
            "표 셀에 값이 넘칠 것으로 추정되는 항목이 있다",
            event="overflow_detected",
            resource_id=label,
            item_count=len(warnings),
        )
    return warnings
