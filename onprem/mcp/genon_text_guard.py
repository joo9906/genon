# =====================================================================================
# genon_text_guard — 되쓰기 안전장치 MCP 도구 (area 01)
#
# **이 파일 하나가 등록 단위다.** GenOS MCP 는 소스 파일 한 개를 받아 실행하며,
# `mcp` 객체를 런타임이 전역으로 주입한다. 그래서 패키지로 쪼갤 수 없다.
#
# **모든 최상위 심볼에 `TG` 접두어를 붙였다.** 한 서버에 다른 도구 파일이 함께 로드될 수
# 있어서다 — `ToolError`·`TOOL_SPECS` 같은 흔한 이름을 그대로 두면 나중에 로드된 쪽이
# 앞엣것을 덮어쓴다.
#
# ## 이 서빙의 존재 이유
#
# LLM 이 글을 되쓰거나 번역하면 **구조와 사실이 조용히 망가질 수 있다.** 표 행이 사라지고,
# 숫자가 바뀌고, 근거라며 문서에 없는 문장을 지어낸다. 그 결과는 **형식상 정상 응답**이라
# 프롬프트 지시("표를 유지하라")만으로는 잡히지 않는다.
#
# 그래서 여기 있는 판정은 전부 **코드가 결정적으로** 한다. LLM 을 부르지 않으므로 같은
# 입력에 항상 같은 결과가 나오고, 판정 자체가 또 틀릴 여지가 없다.
#
# 비표준 패키지를 쓰지 않는다 (stdlib 만). 그래서 부팅 시 설치 절차가 없다.
# =====================================================================================

import difflib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import List, TypedDict

# ── markdown_guard.py ─────────────────────────────
_TGFENCE_RE = re.compile(r"^\s*(```|~~~)")
_TGHEADING_RE = re.compile(r"^(#{1,6})\s")
_TGTABLE_SEP_RE = re.compile(r"^\s*\|?(\s*:?-+:?\s*\|)+\s*:?-*:?\s*\|?\s*$")
_TGUNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")
_TGHTML_TABLE_REGION_RE = re.compile(r"<table\b.*?</table\s*>", re.IGNORECASE | re.DOTALL)
_TGHTML_TR_RE = re.compile(r"<tr\b", re.IGNORECASE)
_TGHTML_CELL_RE = re.compile(r"<t[dh]\b", re.IGNORECASE)


@dataclass
class _TGFingerprint:
    headings: list = field(default_factory=list)   # 제목 레벨 순서 [1, 2, 2, ...]
    table_rows: list = field(default_factory=list)  # 행별 열 수 (구분 행 제외)
    separator_rows: int = 0                          # 표 구분 행(|---|) 수
    fences: int = 0                                  # 코드펜스 줄 수
    html_tables: list = field(default_factory=list)  # HTML 표별 (행 수, 셀 수)


def _TGfingerprint(text: str) -> _TGFingerprint:
    fp = _TGFingerprint()
    # HTML 표 구간을 먼저 지문화하고 제거 — 남은 텍스트만 줄 단위 점검
    # (한 줄짜리 HTML 표 안의 텍스트가 마크다운 규칙에 잘못 걸리지 않게)
    for region in _TGHTML_TABLE_REGION_RE.findall(text):
        fp.html_tables.append(
            (len(_TGHTML_TR_RE.findall(region)), len(_TGHTML_CELL_RE.findall(region)))
        )
    text = _TGHTML_TABLE_REGION_RE.sub("", text)

    in_code = False
    for line in text.splitlines():
        if _TGFENCE_RE.match(line):
            fp.fences += 1
            in_code = not in_code
            continue
        if in_code:
            continue
        heading = _TGHEADING_RE.match(line.strip())
        if heading:
            fp.headings.append(len(heading.group(1)))
            continue
        if line.lstrip().startswith("|"):
            if _TGTABLE_SEP_RE.match(line):
                fp.separator_rows += 1
            else:
                fp.table_rows.append(len(_TGUNESCAPED_PIPE_RE.findall(line)) - 1)
    return fp


def tgfind_structure_issues(original: str, polished: str) -> list:
    """구조 지문을 비교해 훼손 항목의 고정 안내문 목록을 반환한다 (없으면 빈 리스트)."""
    before, after = _TGfingerprint(original), _TGfingerprint(polished)
    issues = []
    if before.table_rows != after.table_rows or before.separator_rows != after.separator_rows:
        issues.append("표 구조(행/열)가 원문과 다르게 변형되었습니다.")
    if before.html_tables != after.html_tables:
        issues.append("HTML 표 구조(행/셀)가 원문과 다르게 변형되었습니다.")
    if before.headings != after.headings:
        issues.append("제목(#) 구성이 원문과 다르게 변형되었습니다.")
    if before.fences != after.fences:
        issues.append("코드블록(```) 구성이 원문과 다르게 변형되었습니다.")
    return issues


# ── fact_guard.py ─────────────────────────────
_TGfact_guard_NUMBER_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?")
# 날짜 표기 네 가지. 긴 형식을 먼저 두어 부분 표기가 중복으로 잡히지 않게 한다.
_TGDATE_RES = (
    re.compile(r"\d{4}\s*[-./]\s*\d{1,2}\s*[-./]\s*\d{1,2}"),
    re.compile(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"),
    re.compile(r"\d{4}\s*년\s*\d{1,2}\s*월"),
    re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일"),
)
# 경고에 나열할 값의 최대 개수. 표가 든 문서에서 수십 개가 어긋나면 안내문이 답변을
# 덮는다 — 앞의 몇 개만 보이고 나머지는 개수로 알린다.
_TGSAMPLE_LIMIT = 5


def _TGnormalize(text: str) -> str:
    """공백을 하나로 접는다. 다듬기는 줄바꿈·들여쓰기를 자유롭게 바꾼다."""
    return re.sub(r"\s+", " ", text or "")


def _TGcanonical_date(token: str) -> str:
    """날짜 표기를 표준형으로. 표기 차이는 사실 왜곡이 아니다."""
    parts = [int(p) for p in re.findall(r"\d+", token)]
    if len(parts) == 3:
        return f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}"
    if len(parts) == 2:
        # 연-월(4자리 시작)인지 월-일인지로 구분한다
        return f"{parts[0]:04d}-{parts[1]:02d}" if parts[0] > 31 else f"{parts[0]:02d}-{parts[1]:02d}"
    return token.strip()


def tgextract_dates(text: str) -> list:
    """날짜를 표준형으로, 등장 순서대로."""
    body = _TGnormalize(text)
    found: list = []
    spans: list = []
    for pattern in _TGDATE_RES:
        for match in pattern.finditer(body):
            if any(start <= match.start() < end for start, end in spans):
                continue  # 더 긴 형식에 이미 포함된 부분 표기
            spans.append((match.start(), match.end()))
            found.append(_TGcanonical_date(match.group(0)))
    return found


def _TGstrip_dates(text: str) -> str:
    """숫자 대조에서 날짜 구간을 뺀다.

    날짜는 따로 재므로 이중 계산이고, 표기가 바뀌면(`2026-03-12` ↔ `2026년 3월 12일`)
    구성 숫자의 개수가 달라져 숫자 불일치로 잘못 번진다.
    """
    body = _TGnormalize(text)
    for pattern in _TGDATE_RES:
        body = pattern.sub(" ", body)
    return body


def tgextract_numbers(text: str) -> list:
    """날짜를 뺀 본문의 수치. 자릿수 구분 콤마는 제거해 `1,250` 과 `1250` 을 같게 본다."""
    return [m.group(0).replace(",", "") for m in _TGfact_guard_NUMBER_RE.finditer(_TGstrip_dates(text))]


def _TGdiff(source: list, result: list) -> tuple:
    """다중집합 차이 — (원문에서 사라진 것, 결과에만 새로 생긴 것).

    집합이 아니라 다중집합이다. `47명 중 47명` 이 `47명 중 12명` 이 되는 경우처럼
    **개수가 줄어든 것도 손실**이라 집합 비교로는 놓친다.
    """
    remaining = list(result)
    dropped = []
    for item in source:
        if item in remaining:
            remaining.remove(item)
        else:
            dropped.append(item)
    return dropped, remaining


def _TGdescribe(kind: str, dropped: list, added: list) -> str:
    """어긋난 값을 담은 한 줄 안내문."""
    parts = []
    if dropped:
        shown = ", ".join(dropped[:_TGSAMPLE_LIMIT])
        more = f" 외 {len(dropped) - _TGSAMPLE_LIMIT}건" if len(dropped) > _TGSAMPLE_LIMIT else ""
        parts.append(f"원문에 있던 {kind} {shown}{more} 이(가) 결과에 없습니다.")
    if added:
        shown = ", ".join(added[:_TGSAMPLE_LIMIT])
        more = f" 외 {len(added) - _TGSAMPLE_LIMIT}건" if len(added) > _TGSAMPLE_LIMIT else ""
        parts.append(f"원문에 없던 {kind} {shown}{more} 이(가) 결과에 생겼습니다.")
    return " ".join(parts)


def tgfind_fact_issues(original: str, polished: str) -> list:
    """숫자·날짜 보존을 대조해 안내문 목록을 반환한다 (없으면 빈 리스트).

    `markdown_guard.find_structure_issues` 와 같은 계약이다 — 판정만 하고 결과를
    바꾸지 않는다. 되돌릴지 다시 요청할지는 호출부와 사용자가 정한다.
    """
    issues = []
    for kind, source, result in (
        ("숫자", tgextract_numbers(original), tgextract_numbers(polished)),
        ("날짜", tgextract_dates(original), tgextract_dates(polished)),
    ):
        dropped, added = _TGdiff(source, result)
        if dropped or added:
            issues.append(_TGdescribe(kind, dropped, added))
    return issues


def tgfact_issue_counts(original: str, polished: str) -> dict:
    """로그용 — 값 없이 종류별 개수만 (3.8절)."""
    counts = {}
    for kind, source, result in (
        ("numbers", tgextract_numbers(original), tgextract_numbers(polished)),
        ("dates", tgextract_dates(original), tgextract_dates(polished)),
    ):
        dropped, added = _TGdiff(source, result)
        counts[kind] = len(dropped) + len(added)
    return counts


# ── numeric_guard.py ─────────────────────────────
# 숫자 덩어리 = 숫자로 시작해 숫자로 끝나는, 구분기호가 섞일 수 있는 구간
_TGnumeric_guard_NUMBER_RE = re.compile(r"[0-9０-９](?:[0-9０-９.,'  ]*[0-9０-９])?")
_TGSEPARATORS = str.maketrans("", "", ".,'  ")
_TGFULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")

# 검증 모드 — 운영에서 바꿀 수 있는 정책
TGMODE_WARN = "warn"      # 번역문을 그대로 쓰고 경고만 노출 (기본)
TGMODE_REVERT = "revert"  # 이탈한 유닛은 원문으로 되돌린다


def tgfingerprint(text: str) -> Counter:
    """텍스트에 담긴 숫자들의 정규화 지문."""
    numbers = []
    for match in _TGnumeric_guard_NUMBER_RE.finditer(text or ""):
        normalized = match.group(0).translate(_TGFULLWIDTH).translate(_TGSEPARATORS)
        if normalized:
            numbers.append(normalized.lstrip("0") or "0")
    return Counter(numbers)


def tgfind_numeric_drift(source: str, translated: str) -> dict:
    """원문에 있던 숫자가 번역문에서 사라지거나 새로 생겼는지 본다.

    Returns:
        `{"missing": [...], "added": [...]}`. 둘 다 비어 있으면 이탈 없음.
        값 자체를 담는 이유: 호출부가 사용자에게 "어떤 수가 어긋났는지" 보여줘야
        확인이 가능하다. **로그에는 싣지 않는다** — 문서 내용이다 (3.8절).
    """
    source_numbers = tgfingerprint(source)
    translated_numbers = tgfingerprint(translated)
    missing = source_numbers - translated_numbers
    added = translated_numbers - source_numbers
    return {
        "missing": sorted(missing.elements()),
        "added": sorted(added.elements()),
    }


def tghas_drift(drift: dict) -> bool:
    return bool(drift["missing"] or drift["added"])


# ── diff_report.py ─────────────────────────────
_TGSENT_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)\s+")


class TGChangeItem(TypedDict):
    before: str
    after: str


def _TGsplit_units(text: str) -> List[str]:
    """마크다운 친화적 비교 단위: 줄 → 문장 순으로 분해."""
    units: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 마크다운 구조 줄(heading, 표, 리스트 마커만 있는 줄)은 통째로 하나의 단위
        if line.startswith(("#", "|", "```")):
            units.append(line)
            continue
        parts = [p.strip() for p in _TGSENT_SPLIT_RE.split(line) if p.strip()]
        units.extend(parts if parts else [line])
    return units


def tgbuild_change_list(original: str, polished: str, max_items: int = 50) -> List[TGChangeItem]:
    """원문/수정문을 비교해 실제로 바뀐 문장 쌍만 추출한다.

    Args:
        original: 다듬기 전 텍스트.
        polished: 다듬은 후 텍스트.
        max_items: 응답 크기 제한 (문서가 매우 길 때 result payload 폭주 방지).

    Returns:
        [{"before": ..., "after": ...}, ...] — 변경된 항목만 포함.
    """
    src = _TGsplit_units(original)
    dst = _TGsplit_units(polished)
    matcher = difflib.SequenceMatcher(a=src, b=dst, autojunk=False)

    changes: List[TGChangeItem] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        before = " ".join(src[i1:i2]).strip()
        after = " ".join(dst[j1:j2]).strip()
        if before == after:
            continue
        changes.append({"before": before, "after": after})
        if len(changes) >= max_items:
            break
    return changes


def tgformat_changes_markdown(changes: List[TGChangeItem]) -> str:
    """채팅 답변 하단에 붙일 변경 내역 마크다운."""
    if not changes:
        return "\n\n---\n**변경 내역**: 수정된 문장이 없습니다."
    lines = ["\n\n---\n**변경 내역** (총 {}건)".format(len(changes)), ""]
    lines.append("| 원문 | 수정문 |")
    lines.append("|---|---|")
    for item in changes:
        before = item["before"].replace("|", "\\|").replace("\n", " ")
        after = item["after"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {before} | {after} |")
    return "\n".join(lines)


# ── evidence.py ─────────────────────────────
# 마크다운/HTML 꾸밈 제거 — 원문과 근거가 같은 문장인데 표기만 다른 경우를 흡수한다
_TGHTML_TAG_RE = re.compile(r"<[^>]+>")
_TGMD_DECOR_RE = re.compile(r"[*_`~#>|\\]+")
_TGWHITESPACE_RE = re.compile(r"\s+")

_TGNGRAM = 3


@dataclass(frozen=True)
class TGEvidenceVerdict:
    grounded: bool
    ratio: float   # 근거 3-gram 중 문서에 있는 비율 (완전 포함이면 1.0)


def tgnormalize(text: str) -> str:
    """대조용 정규화. 문서 쪽과 근거 쪽에 **같은 함수**를 쓴다."""
    cleaned = _TGHTML_TAG_RE.sub(" ", text or "")
    cleaned = _TGMD_DECOR_RE.sub(" ", cleaned)
    return _TGWHITESPACE_RE.sub(" ", cleaned).strip().casefold()


def _TGngrams(text: str) -> set:
    if len(text) < _TGNGRAM:
        return {text} if text else set()
    return {text[i: i + _TGNGRAM] for i in range(len(text) - _TGNGRAM + 1)}


class TGEvidenceChecker:
    """문서 하나에 대해 여러 근거를 대조한다.

    문서 정규화·n-gram 집합을 한 번만 만들어 재사용한다. 항목마다 다시 만들면
    FAQ 10개 × 수만 자 문서에서 같은 계산을 열 번 한다.
    """

    def __init__(self, document: str):
        self._document = tgnormalize(document)
        self._document_ngrams = _TGngrams(self._document)

    def check(self, evidence: str, min_ratio: float) -> TGEvidenceVerdict:
        normalized = tgnormalize(evidence)
        if not normalized:
            return TGEvidenceVerdict(grounded=False, ratio=0.0)
        if normalized in self._document:
            return TGEvidenceVerdict(grounded=True, ratio=1.0)

        evidence_ngrams = _TGngrams(normalized)
        if not evidence_ngrams:
            return TGEvidenceVerdict(grounded=False, ratio=0.0)
        overlap = len(evidence_ngrams & self._document_ngrams) / len(evidence_ngrams)
        return TGEvidenceVerdict(grounded=overlap >= min_ratio, ratio=round(overlap, 4))


# ── tools.py ─────────────────────────────
class TGToolError(ValueError):
    """도구 인자가 계약과 다르다. 사용자 노출 문구는 담지 않는다 — 호출부가 만든다."""

    def __init__(self, error_type: str):
        super().__init__(error_type)
        self.error_type = error_type


# 인자 길이 상한. 없으면 한 번의 호출이 서빙을 오래 붙든다 (LLM 이 부를 수도 있다).
_TGMAX_TEXT_CHARS = 400_000
_TGMAX_EVIDENCE_ITEMS = 100


def _TGtext_arg(arguments: dict, name: str, *, required: bool = True) -> str:
    value = arguments.get(name)
    if value is None:
        if required:
            raise TGToolError(f"MISSING_ARG_{name.upper()}")
        return ""
    if not isinstance(value, str):
        raise TGToolError(f"INVALID_TYPE_{name.upper()}")
    if len(value) > _TGMAX_TEXT_CHARS:
        raise TGToolError(f"TOO_LONG_{name.upper()}")
    return value


def _TGratio_arg(arguments: dict, name: str, default: float) -> float:
    value = arguments.get(name, default)
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        raise TGToolError(f"INVALID_TYPE_{name.upper()}") from None
    if not 0.0 <= ratio <= 1.0:
        raise TGToolError(f"OUT_OF_RANGE_{name.upper()}")
    return ratio


# ─────────────────────────────────────────────────────────────
# 도구 구현 — 전부 `dict` 를 돌려준다 (JSON 직렬화 가능만, §I)
# ─────────────────────────────────────────────────────────────
def _TGmarkdown_structure_issues(arguments: dict) -> dict:
    source = _TGtext_arg(arguments, "source")
    revised = _TGtext_arg(arguments, "revised")
    issues = tgfind_structure_issues(source, revised)
    return {"ok": True, "issues": list(issues), "issue_count": len(issues)}


def _TGfact_issues(arguments: dict) -> dict:
    source = _TGtext_arg(arguments, "source")
    revised = _TGtext_arg(arguments, "revised")
    issues = tgfind_fact_issues(source, revised)
    return {
        "ok": True,
        "issues": list(issues),
        "issue_count": len(issues),
        # 숫자·날짜를 나눠 센다 — 호출부가 어느 쪽이 문제인지 로그에 남길 수 있게
        "counts": dict(tgfact_issue_counts(source, revised)),
    }


def _TGnumeric_issues(arguments: dict) -> dict:
    """번역문 숫자 보존. 자릿수 구분 기호를 떼고 비교하므로 `1,000` ↔ `1.000` 은 오탐이 아니다."""
    source = _TGtext_arg(arguments, "source")
    revised = _TGtext_arg(arguments, "revised")
    drift = tgfind_numeric_drift(source, revised)

    issues = []
    if drift["missing"]:
        issues.append(f"원문의 숫자가 결과에서 빠졌습니다: {', '.join(drift['missing'][:10])}")
    if drift["added"]:
        issues.append(f"원문에 없던 숫자가 결과에 있습니다: {', '.join(drift['added'][:10])}")

    return {
        "ok": True,
        "issues": issues,
        "issue_count": len(issues),
        "has_drift": tghas_drift(drift),
        # 값 자체를 돌려준다 — 사용자에게 "어떤 수가 어긋났는지" 보여줘야 확인이 된다.
        # 호출부는 이 값을 **로그에 싣지 않는다** (문서 내용이다, 3.8절).
        "drift": drift,
    }


def _TGdiff_changes(arguments: dict) -> dict:
    source = _TGtext_arg(arguments, "source")
    revised = _TGtext_arg(arguments, "revised")
    max_items = arguments.get("max_items", 50)
    try:
        max_items = int(max_items)
    except (TypeError, ValueError):
        raise TGToolError("INVALID_TYPE_MAX_ITEMS") from None
    if not 1 <= max_items <= 500:
        raise TGToolError("OUT_OF_RANGE_MAX_ITEMS")

    changes = tgbuild_change_list(source, revised, max_items=max_items)
    return {"ok": True, "changes": [dict(item) for item in changes], "change_count": len(changes)}


def _TGevidence_check(arguments: dict) -> dict:
    """근거가 문서에 실제로 있는지 대조한다 (FAQ 의 핵심 계약).

    문서 정규화·n-gram 집합을 **한 번만** 만들어 모든 근거에 재사용한다.
    항목마다 다시 만들면 근거 10개 × 수만 자 문서에서 같은 계산을 열 번 한다.
    """
    document = _TGtext_arg(arguments, "document")
    evidences = arguments.get("evidences")
    if not isinstance(evidences, list):
        raise TGToolError("INVALID_TYPE_EVIDENCES")
    if len(evidences) > _TGMAX_EVIDENCE_ITEMS:
        raise TGToolError("TOO_MANY_EVIDENCES")
    min_ratio = _TGratio_arg(arguments, "min_ratio", 0.8)

    checker = TGEvidenceChecker(document)
    results = []
    for index, evidence in enumerate(evidences):
        if not isinstance(evidence, str):
            raise TGToolError("INVALID_TYPE_EVIDENCES")
        verdict = checker.check(evidence, min_ratio)
        results.append({"index": index, "grounded": verdict.grounded, "ratio": verdict.ratio})

    grounded_count = sum(1 for item in results if item["grounded"])
    return {
        "ok": True,
        "results": results,
        "grounded_count": grounded_count,
        # 기각 건수를 노출한다 — 조용히 버리면 왜 5개 요청에 3개만 나왔는지 알 수 없다
        "rejected_count": len(results) - grounded_count,
    }


# ─────────────────────────────────────────────────────────────
# 도구 표 — MCP `tools/list` 가 그대로 내보낸다
# ─────────────────────────────────────────────────────────────
_TGTEXT_PAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "source": {"type": "string", "description": "원문"},
        "revised": {"type": "string", "description": "되쓴 결과(다듬기·번역 등)"},
    },
    "required": ["source", "revised"],
}

TGTOOL_SPECS = [
    {
        "name": "markdown_structure_issues",
        "description": (
            "원문과 되쓴 결과의 마크다운/HTML 구조를 대조해 훼손을 찾는다. "
            "표 행·열 수, 제목 단계, 코드펜스 지문을 비교한다. 되돌리지 않고 경고만 낸다."
        ),
        "inputSchema": _TGTEXT_PAIR_SCHEMA,
    },
    {
        "name": "fact_issues",
        "description": (
            "원문의 숫자·날짜가 되쓴 결과에서 사라지거나 바뀌었는지 다중집합으로 대조한다. "
            "날짜는 표기가 달라도 같은 날이면 같은 것으로 본다."
        ),
        "inputSchema": _TGTEXT_PAIR_SCHEMA,
    },
    {
        "name": "numeric_issues",
        "description": (
            "번역문의 숫자 보존을 확인한다. 자릿수 구분 기호를 제거하고 비교하므로 "
            "`1,000` 과 `1.000` 을 다르다고 보지 않는다."
        ),
        "inputSchema": _TGTEXT_PAIR_SCHEMA,
    },
    {
        "name": "diff_changes",
        "description": "원문과 되쓴 결과의 문장 단위 변경 내역을 낸다. LLM 에 되묻지 않고 difflib 으로 산출한다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "원문"},
                "revised": {"type": "string", "description": "되쓴 결과"},
                "max_items": {"type": "integer", "description": "최대 변경 건수 (1~500, 기본 50)"},
            },
            "required": ["source", "revised"],
        },
    },
    {
        "name": "evidence_check",
        "description": (
            "LLM 이 제시한 근거 문장이 원본 문서에 실제로 있는지 대조한다. "
            "완전 포함이면 1.0, 아니면 3-gram 겹침 비율로 판정한다. 검증 없이 표시하면 "
            "지어낸 답변에 그럴듯한 출처가 붙어 더 위험하다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "document": {"type": "string", "description": "원본 문서 전문"},
                "evidences": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "대조할 근거 문장들 (최대 100개)",
                },
                "min_ratio": {
                    "type": "number",
                    "description": "부분 일치로 인정할 최소 겹침 비율 (0~1, 기본 0.8)",
                },
            },
            "required": ["document", "evidences"],
        },
    },
]

_TGHANDLERS = {
    "markdown_structure_issues": _TGmarkdown_structure_issues,
    "fact_issues": _TGfact_issues,
    "numeric_issues": _TGnumeric_issues,
    "diff_changes": _TGdiff_changes,
    "evidence_check": _TGevidence_check,
}


def tgcall_tool(name: str, arguments: dict) -> dict:
    handler = _TGHANDLERS.get(name)
    if handler is None:
        raise TGToolError("UNKNOWN_TOOL")
    return handler(arguments)


# =====================================================================================
# 로컬 단독 실행 대비: 런타임이 주입하는 전역 `mcp` 가 없으면 최소 shim 을 쓴다.
# =====================================================================================
try:
    mcp  # noqa: F821
except NameError:
    class _TGLocalMCP:
        def tool(self, *args, **kwargs):
            def _decorator(fn):
                return fn
            return _decorator

    mcp = _TGLocalMCP()
    print("[BOOT] 로컬 테스트용 shim 사용")


def _tg_run(name: str, arguments: dict) -> str:
    """도구 본문을 부르고 JSON 문자열로 돌려준다.

    **입력 오류를 예외로 올리지 않는다** — MCP 도구가 예외로 죽으면 호출부(워크플로우
    스텝)에 오는 것은 전송 실패와 구분되지 않는다. `ok=false` + `error_type` 으로 내려야
    스텝이 "재시도 무의미" 로 다루고 사용자에게 고정 안내문을 보여줄 수 있다.
    """
    try:
        result = tgcall_tool(name, arguments)
    except TGToolError as exc:
        result = {"ok": False, "error_type": exc.error_type}
    except Exception as exc:  # noqa: BLE001 - 최종 방어선. 원문은 응답에 싣지 않는다 (3.8절)
        print(f"[ERROR] {name} 실패: {type(exc).__name__}")
        result = {"ok": False, "error_type": "TOOL_EXECUTION_FAILED"}
    return json.dumps(result, ensure_ascii=False)


# =====================================================================================
# MCP Tools
#
# GenOS 는 값이 없을 때 None 이 아니라 **빈 문자열("")** 을 주입한다. 그래서 숫자 인자는
# `int | str | None` 으로 받고 본문에서 캐스팅한다 — `int` 로만 선언하면 MCP 가 본문
# 전에 타입 검증을 하다가 "" 에서 검증 에러를 낸다.
# =====================================================================================

@mcp.tool()
async def markdown_structure_issues(source: str = "", revised: str = "") -> str:
    """[언제 쓰나] LLM 이 되쓴 글이 원문의 **표·제목·코드블록 구조를 망가뜨렸는지** 확인할 때.
    → 다듬기·번역 직후에 부른다. 되돌리지는 않고 경고만 낸다.

    원문과 되쓴 결과의 마크다운/HTML 구조를 대조한다. 표 행·열 수, 제목 단계,
    코드펜스 지문을 비교한다.

    Args:
        source: 원문.
        revised: 되쓴 결과.

    Returns:
        JSON 문자열 `{"ok": true, "issues": [...], "issue_count": n}`.
    """
    return _tg_run("markdown_structure_issues", {"source": source, "revised": revised})


@mcp.tool()
async def fact_issues(source: str = "", revised: str = "") -> str:
    """[언제 쓰나] 되쓴 글에서 **숫자·날짜가 사라지거나 바뀌었는지** 확인할 때.

    다중집합으로 대조한다. **날짜는 표기가 달라도 같은 날이면 같은 것으로 본다** —
    `2026. 8. 3.` 과 `2026-08-03` 을 다르다고 하면 정상적인 표기 정리가 전부 오탐이 된다.

    Args:
        source: 원문.
        revised: 되쓴 결과.

    Returns:
        JSON 문자열 `{"ok": true, "issues", "issue_count", "counts"}`.
        `counts` 는 숫자/날짜를 나눠 센 값이다 — 호출부가 어느 쪽이 문제인지 로그에 남긴다.
    """
    return _tg_run("fact_issues", {"source": source, "revised": revised})


@mcp.tool()
async def numeric_issues(source: str = "", revised: str = "") -> str:
    """[언제 쓰나] **번역문**의 숫자 보존을 확인할 때.

    자릿수 구분 기호를 제거하고 비교하므로 `1,000` 과 `1.000` 을 다르다고 보지 않는다
    (언어마다 천 단위 기호가 달라서, 안 그러면 정상 번역이 전부 경고가 된다).

    Args:
        source: 원문.
        revised: 번역 결과.

    Returns:
        JSON 문자열 `{"ok": true, "issues", "issue_count", "has_drift", "drift"}`.
        `drift` 는 어긋난 값 자체다 — 사용자에게 보여줘야 확인이 된다.
        **호출부는 이 값을 로그에 싣지 않는다** (문서 내용이다, 3.8절).
    """
    return _tg_run("numeric_issues", {"source": source, "revised": revised})


@mcp.tool()
async def diff_changes(source: str = "", revised: str = "", max_items: int | str | None = None) -> str:
    """[언제 쓰나] 사용자에게 **무엇이 어떻게 바뀌었는지** 보여줄 때.

    문장 단위 변경 내역을 낸다. **LLM 에 되묻지 않고 difflib 으로 산출한다** —
    되물으면 모델이 실제 변경과 다른 요약을 지어낼 수 있고, 그 결과는 검증할 방법이 없다.

    Args:
        source: 원문.
        revised: 되쓴 결과.
        max_items: 최대 변경 건수 (1~500, 기본 50).

    Returns:
        JSON 문자열 `{"ok": true, "changes": [...], "change_count": n}`.
    """
    arguments = {"source": source, "revised": revised}
    if max_items is not None and max_items != "":
        arguments["max_items"] = max_items
    return _tg_run("diff_changes", arguments)


@mcp.tool()
async def evidence_check(
    document: str = "",
    evidences: list | str = "",
    min_ratio: float | str | None = None,
) -> str:
    """[언제 쓰나] LLM 이 제시한 **근거 문장이 원본에 실제로 있는지** 확인할 때 (FAQ 핵심 계약).

    완전 포함이면 1.0, 아니면 3-gram 겹침 비율로 판정한다.
    **검증 없이 표시하면 지어낸 답변에 그럴듯한 출처가 붙어 더 위험하다.**

    Args:
        document: 원본 문서 전문.
        evidences: 검증할 근거 문장 목록. JSON 배열 문자열도 받는다.
        min_ratio: 통과 기준 겹침 비율 (기본 0.8).

    Returns:
        JSON 문자열 `{"ok": true, "results": [{"index", "grounded", "ratio"}, ...]}`.
    """
    if isinstance(evidences, str):
        # GenOS 가 배열을 JSON 문자열로 넘기는 경우가 있다. 빈 문자열은 "안 넘김" 이다.
        try:
            evidences = json.loads(evidences) if evidences.strip() else []
        except json.JSONDecodeError:
            return json.dumps(
                {"ok": False, "error_type": "INVALID_TYPE_EVIDENCES"}, ensure_ascii=False
            )
    arguments = {"document": document, "evidences": evidences}
    if min_ratio is not None and min_ratio != "":
        arguments["min_ratio"] = min_ratio
    return _tg_run("evidence_check", arguments)
