"""표 셀 슬롯의 **값 넘침** 판정 — 채우기 전에 잰다.

**왜.** 006 은 값이 자리에 들어가는지를 한 번도 재지 않았다. 표 안 슬롯은 채울 항목으로
그대로 인식되고 LLM 이 값을 만들어 넣는데, 셀 폭보다 긴 값이 들어가면 줄이 늘고 행이
자라 **뒷장 전체가 밀린다.** 화면 미리보기는 마크다운이라 이게 보이지 않고, 사용자는
한/글에서 열어 보고서야 안다.

**무엇을 쓰나.** `python-hwpx` 의 `form_fit` 이다. 셀 폭에서 좌우 여백과 인라인 개체 폭을
빼고, 그 셀 문단의 글꼴 크기·줄간격으로 값의 예상 폭·줄 수를 낸다. 폭 추정은 한/글 자신의
`lineSeg/@horzsize` 와 대조해 맞춘 모델이라(±10 HWPUNIT, 셀 82%), 우리가 다시 만들 이유가
없는 부분이다. 우리 몫은 **어느 자리가 슬롯인가**(`hwpx_fields.iter_slot_matches`)뿐이다.

**본문 문단 슬롯은 재지 않는다.** 문단은 넘치면 다음 줄로 흐를 뿐 레이아웃이 깨지지
않는다. 재는 대상은 폭이 고정된 표 셀이다. `form_fit` 도 셀에서만 치수를 뽑는다.

**절대 막지 않는다 — 경고만.** 추정에는 불확실 구간(`confidence`)이 있고, 폰트 대체나
자간 설정에 따라 실제 결과가 다를 수 있다. 값이 길다는 이유로 문서 생성을 거절하면
"긴 제목을 못 쓰는 기능"이 된다. 판정은 사용자·UI 에 넘긴다.

라이브러리가 없으면 조용히 건너뛴다 — `hwpx_verify` 와 같은 규약이고, 미측정 사실은
로그로 드러낸다(§5).
"""

import io
from dataclasses import dataclass

from .hwpx_fields import iter_slot_matches
from .logging_utils import log_warning

# 표 셀 슬롯은 한 줄에 들어가는 것을 기준으로 본다. 셀이 여러 줄을 허용해도, 템플릿이
# 한 줄로 설계한 칸에 두 줄이 들어가면 그 행이 자라 아래가 밀린다 — 그 순간을 잡는 것이
# 이 검사의 목적이다.
_MAX_LINES = 1
_AVAILABLE: "bool | None" = None


@dataclass
class OverflowWarning:
    """값이 자리를 넘칠 것으로 추정되는 항목 하나."""

    field: str            # 항목명 (슬롯 따옴표 안 문자열)
    lines: int            # 예상 줄 수
    ratio: float          # 필요 폭 / 사용 가능 폭 (1.0 초과면 넘침)
    confidence: str       # form_fit 의 추정 신뢰도 (high / low …)

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "lines": self.lines,
            "ratio": round(self.ratio, 3),
            "confidence": self.confidence,
        }


def _load():
    """측정기를 가져온다. 없으면 None (미설치는 오류가 아니라 상태다)."""
    try:
        from hwpx import HwpxDocument
        from hwpx.form_fit import measure, resolve_slot_metrics
    except ImportError:
        return None
    return HwpxDocument, resolve_slot_metrics, measure


def available() -> bool:
    """이 환경에서 넘침 측정을 할 수 있는가."""
    global _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    _AVAILABLE = _load() is not None
    if not _AVAILABLE:
        log_warning(
            "넘침 측정기(python-hwpx)가 없어 표 셀 값 넘침을 재지 않는다",
            event="overflow_unavailable",
            status="unavailable",
        )
    return _AVAILABLE


def check(template_bytes: bytes, values: dict, label: str = "") -> list:
    """템플릿의 표 셀 슬롯에 값을 넣었을 때 넘치는 항목을 낸다.

    **채우기 전 템플릿**을 본다 — 채운 뒤에는 `{…}` 가 사라져 어느 셀이 어느 항목이었는지
    알 수 없다(`document.build` 의 서식·채우기 순서와 같은 이유).

    측정 실패는 넘침 없음으로 본다. 이 검사는 부가 정보이고, 여기서 예외가 올라가면
    문서 생성 전체가 값 길이 때문에 죽는다.
    """
    loaded = _load()
    if loaded is None:
        available()  # 최초 1회 경고
        return []
    HwpxDocument, resolve_slot_metrics, measure = loaded

    try:
        document = HwpxDocument.open(io.BytesIO(template_bytes))
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
        for table in document.tables.all:
            warnings.extend(
                _walk_table(table, document, values, resolve_slot_metrics, measure)
            )
    except Exception as exc:  # noqa: BLE001 - 위와 같은 이유
        log_warning(
            "넘침 측정 중 예외 — 측정 없이 진행",
            event="overflow_measure_failed",
            resource_id=label,
            error_type=type(exc).__name__,
        )
        return []
    finally:
        document.close()

    if warnings:
        log_warning(
            "표 셀에 값이 넘칠 것으로 추정되는 항목이 있다",
            event="overflow_detected",
            resource_id=label,
            item_count=len(warnings),
        )
    return warnings


def _walk_table(table, document, values: dict, resolve_slot_metrics, measure) -> list:
    """표 하나와 그 안에 중첩된 표까지 훑는다.

    `document.tables.all` 은 본문 최상위 표만 준다. 중첩 표 셀도 폭이 고정된 자리이고
    (오히려 부모 셀 폭에 갇혀 더 좁다), 006 은 표 안 슬롯을 채울 항목으로 인식하므로
    빠뜨리면 가장 넘치기 쉬운 자리를 놓친다.
    """
    found: list = []
    for row in table.rows:
        for cell in row.cells:
            found.extend(_check_cell(cell, document, values, resolve_slot_metrics, measure))
            for nested in cell.tables:
                found.extend(_walk_table(nested, document, values, resolve_slot_metrics, measure))
    return found


def _check_cell(cell, document, values: dict, resolve_slot_metrics, measure) -> list:
    """셀 하나 안의 슬롯들을 잰다.

    한 셀에 슬롯이 둘 이상이면(`{'소속'} {'성명'}`) **합친 길이**로 재야 맞지만, 지금은
    항목별로 잰다 — 어느 항목이 문제인지 알려 주는 쪽이 사용자에게 쓸모 있고, 합산은
    "둘 다 짧은데 합쳐서 넘침" 이라는 보고할 곳 없는 경고를 만든다. 한 칸에 여러 항목을
    두는 템플릿이 실제로 나오면 그때 합산 경고를 따로 붙인다.
    """
    text = cell.text or ""
    names = [name for name, _ in iter_slot_matches(text)]
    if not names:
        return []

    slot = resolve_slot_metrics(cell, document, max_lines=_MAX_LINES)
    found: list = []
    for name in names:
        value = values.get(name)
        if not isinstance(value, str) or not value.strip():
            continue
        result = measure(value, slot)
        if result.fits:
            continue
        found.append(
            OverflowWarning(
                field=name,
                lines=result.lines,
                ratio=result.ratio,
                confidence=result.confidence,
            )
        )
    return found
