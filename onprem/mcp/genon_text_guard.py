# =====================================================================================
# genon_text_guard — 되쓰기 안전장치 MCP 도구 (area 01)
#
# **이 파일 하나가 등록 단위다.** GenOS MCP 는 소스 파일 한 개를 받아 실행하며,
# `mcp` 객체를 런타임이 전역으로 주입한다. 그래서 패키지로 쪼갤 수 없다.
#
# **모든 최상위 심볼에 `TG` 접두어를 붙였다.** 한 서버에 다른 도구 파일이 함께 로드될 수
# 있어서다 — `ToolError`·`HANDLERS` 같은 흔한 이름을 그대로 두면 나중에 로드된 쪽이
# 앞엣것을 덮어쓴다.
#
# ## 이 서빙의 존재 이유
#
# LLM 이 글을 되쓰거나 번역하면 **구조와 사실이 조용히 망가질 수 있다.** 표 행이 사라지고
# 숫자가 바뀐다. 그 결과는 **형식상 정상 응답**이라 프롬프트 지시("표를 유지하라")만으로는
# 잡히지 않는다.
#
# 그래서 여기 있는 판정은 전부 **코드가 결정적으로** 한다. LLM 을 부르지 않으므로 같은
# 입력에 항상 같은 결과가 나오고, 판정 자체가 또 틀릴 여지가 없다.
#
# ## 근거 대조(`evidence_check`)는 **뺐다** (2026-08-18)
#
# 도구는 있는데 **운영 호출부가 하나도 없었다** — FAQ 스텝은 `hwpx_to_markdown` 만 부르고,
# 근거 대조는 FAQ 코드서빙이 자기 안에서 한다(`faq/evidence.py`). 그런데 여기 있던 판정부는
# 그 파일과 **줄 단위로 같은 사본**이었고(`_NGRAM = 3`, 같은 정규식 3개, 같은 `check()`),
# **사본 대조 점검도 없었다** — 표 격자는 `check_table_grid`, 톤은 `check_tone_policy` 가
# 보는데 이것만 아무도 안 봤다.
#
# 즉 "아무도 안 쓰는데 갈릴 수 있는 사본" 이었다. 근거 규칙(n-gram 크기·min_ratio)을 고치면
# 이쪽만 옛 판정을 계속 내고, 그걸 부른 LLM 은 서빙과 **다른 답**을 받는다 — 오류로는
# 드러나지 않는다. 다시 필요해지면 `faq/evidence.py` 에서 옮겨 적는다(그쪽이 정본이다).
#
# 비표준 패키지를 쓰지 않는다 (stdlib 만). 그래서 부팅 시 설치 절차가 없다.
# =====================================================================================

import difflib
import json
import logging
import re
import sys
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


# ── 로깅 ───────────────────────────────────────────
# **`print()` 를 쓰지 않는다** (GENOS_RULES §C, 가이드 3.10). MCP 는 stdout 이 전송 채널이
# 될 수 있고(stdio 방식), 그러면 로그 한 줄이 프로토콜을 깨뜨린다 — `eval/` 이 stderr 전용
# 로깅을 쓰는 이유와 같다. 값(문서 원문·경로·시크릿)은 메시지에 넣지 않고 예외 **타입**만
# 남긴다(3.8절).
_TGlog = logging.getLogger("genon_text_guard")


def _TGsetup_logging() -> None:
    """이 파일 전용 **stderr** 핸들러를 붙인다 (2026-08-14).

    두 가지를 동시에 지키려는 것이다:

    - **`print()` 를 쓰지 않는다** (GENOS_RULES §C). MCP 는 stdout 이 전송 채널이 될 수
      있고(stdio 방식), 그러면 로그 한 줄이 프로토콜을 깨뜨린다 — `eval/` 이 stderr 전용
      로깅을 쓰는 이유와 같다.
    - **그렇다고 조용해지지도 않는다.** 로깅 설정이 없는 프로세스에서 `logger.info` 는
      **아무 데도 안 나온다**(기본 최후 핸들러가 WARNING 부터다). 그냥 logger 로 바꾸기만
      하면 부팅·적재 메시지가 소리 없이 사라진다 — 그건 print 보다 나쁘다.

    핸들러가 이미 있으면 아무것도 하지 않는다(런타임이 설정했다면 그쪽을 존중한다).
    """
    if _TGlog.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    _TGlog.addHandler(handler)
    _TGlog.setLevel(logging.INFO)
    # 루트로 올리지 않는다 — 루트에 stdout 핸들러가 붙어 있으면 그리로 새어 나간다.
    _TGlog.propagate = False


_TGsetup_logging()


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
#
# ## 변경 내역은 **답변 아래 목록이 아니라 본문 위 하이라이트**다 (2026-08-27 변경)
#
# 그전에는 `{"before", "after"}` 문장 쌍만 냈고, 워크플로우 스텝이 그것을 답변 끝에
# "주요 변경 내역" 목록으로 붙였다. 요구가 반대였다 — **바뀐 낱말을 본문 그 자리에서**
# 보여 달라는 것이었고(웹 번역기 방식), 그러려면 두 가지가 필요했다:
#
# 1. **문장이 아니라 낱말 단위.** 문장 쌍은 "이 문장이 바뀌었다" 까지만 말한다.
#    `개발함` → `개발하였습니다` 처럼 어느 낱말을 손질했는지가 요구였다.
# 2. **되쓴 글 기준 문자 좌표(`span`).** 그전 구현은 문장으로 쪼갠 뒤 `strip()` 까지
#    걸어서 **원래 어디였는지가 복원 불가**였다. 좌표가 없으면 프론트는 `after`
#    문자열을 본문에서 다시 찾아야 하고, 같은 낱말이 두 번 나오면 어느 쪽을 칠할지
#    결정할 수 없다 — 즉 좌표 없이는 인라인 하이라이트가 성립하지 않는다.
#
# **좌표를 내는 쪽과 칠하는 쪽을 한 함수에 두지 않는다.** `changes[].span` 은 그대로
# 내보내고(프론트가 자기 방식으로 칠할 수 있어야 한다), `<mark>` 를 입힌 **표시용 사본**을
# 함께 낸다. 번역의 `markdown`/`markdown_highlighted` 규약과 같은 모양이다 — 정본은
# 손대지 않는다. 내려받기가 정본을 그대로 파일로 만들기 때문이다.
_TGSENT_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)\s+")
# 낱말 = 공백으로 갈린 토막. **HTML 태그는 따로 끊는다** — 전처리기가 표를 한 줄
# HTML 로 내므로(`<table><tbody>…</table>`) 공백만으로 끊으면 표 한 줄이 통째로 낱말
# 하나가 된다. 그러면 셀 글자 하나가 바뀌어도 span 이 줄 전체를 덮고, 그 span 은 태그에
# 걸치므로 `_TGprotected_regions` 에서 버려진다 — **HTML 표 안 변경은 영영 칠하지 못한다.**
# 태그를 끊어 두면 셀 글자가 자기 낱말이 되어 태그 밖 span 을 얻는다.
_TGWORD_RE = re.compile(r"<[^<>\n]{0,300}>|[^\s<]+|<")

# 표시용 사본에 쓰는 태그. `<strong>`(굵게)이 아니라 `<mark>`(형광)인 이유: 원문이 원래
# 갖고 있던 강조와 구분돼야 하고, "바뀐 자리" 는 강조가 아니라 표시다. 번역의 용어사전
# 하이라이트도 같은 태그를 쓴다 (`glossary_report._OPEN_TAG`).
_TGMARK_OPEN = "<mark>"
_TGMARK_CLOSE = "</mark>"

# 태그를 끼우면 안 되는 구간. 여기 걸치는 span 은 `changes` 에는 남기고 **칠하지만
# 않는다** — 칠하면 눈에 보이는 손상이 된다:
#   - 코드펜스 안: `<mark>` 가 화면에 글자 그대로 나온다.
#   - HTML 태그 안: `<td rowspan="2">` 가운데를 가르면 표가 통째로 깨진다. 전처리기가
#     표를 한 줄 HTML 로 내므로 실제로 생길 수 있는 경우다.
_TGHTML_TAG_RE = re.compile(r"<[^<>\n]{0,300}>")


class TGChangeItem(TypedDict):
    before: str
    after: str
    # 되쓴 글(`revised`) 기준 `[start, end)`. **삭제만 일어난 자리는 `None`** 이다 —
    # 칠할 글자가 없다. 0 을 넣으면 문서 맨 앞이 칠해진다.
    span: object


def _TGsplit_units_with_spans(text: str) -> list:
    """마크다운 친화적 비교 단위 — `(단위 텍스트, start, end)`.

    분해 규칙은 그대로다(줄 → 문장, 구조 줄은 통째로). 달라진 것은 **원문 안 절대
    위치를 함께 낸다**는 것뿐이다. `re.split` 은 위치를 버리므로 `finditer` 로 자른다.
    """
    units: list = []
    pos = 0
    for raw in text.splitlines(keepends=True):
        line_start = pos
        pos += len(raw)
        stripped = raw.strip()
        if not stripped:
            continue
        indent = len(raw) - len(raw.lstrip())
        # 마크다운 구조 줄(heading, 표, 코드펜스)은 통째로 하나의 단위
        if stripped.startswith(("#", "|", "```")):
            units.append((stripped, line_start + indent, line_start + indent + len(stripped)))
            continue
        base = line_start + indent
        prev = 0
        bounds = []
        for match in _TGSENT_SPLIT_RE.finditer(stripped):
            bounds.append((prev, match.start()))
            prev = match.end()
        bounds.append((prev, len(stripped)))
        for start, end in bounds:
            segment = stripped[start:end]
            if not segment.strip():
                continue
            lead = len(segment) - len(segment.lstrip())
            body = segment.strip()
            units.append((body, base + start + lead, base + start + lead + len(body)))
    return units


def _TGwords(units: list) -> list:
    """단위 목록을 `(낱말, start, end)` 로 편다 — 좌표는 문서 전체 기준이다."""
    words: list = []
    for text, start, _end in units:
        for match in _TGWORD_RE.finditer(text):
            words.append((match.group(), start + match.start(), start + match.end()))
    return words


def _TGword_changes(src_units: list, dst_units: list) -> list:
    """바뀐 단위 쌍을 **낱말 단위로 다시 갈라** 변경 항목을 만든다.

    문장 단위로만 보면 "이 문장이 바뀌었다" 까지만 알 수 있어 본문 하이라이트가 문장
    전체를 칠한다. 그러면 어느 낱말을 손질했는지가 오히려 묻힌다.
    """
    before_words = _TGwords(src_units)
    after_words = _TGwords(dst_units)

    if not after_words:
        # 삭제만 — 되쓴 글에 칠할 자리가 없다. 그래도 항목으로는 남긴다.
        before = " ".join(w[0] for w in before_words)
        return [{"before": before, "after": "", "span": None}] if before else []
    if not before_words:
        # 통째로 새로 들어온 구간. 낱말로 갈라도 전부 새것이라 한 항목으로 낸다.
        after = " ".join(w[0] for w in after_words)
        return [{"before": "", "after": after, "span": [after_words[0][1], after_words[-1][2]]}]

    matcher = difflib.SequenceMatcher(
        a=[w[0] for w in before_words], b=[w[0] for w in after_words], autojunk=False
    )
    items: list = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        before = " ".join(w[0] for w in before_words[i1:i2])
        after = " ".join(w[0] for w in after_words[j1:j2])
        if before == after:
            continue
        span = [after_words[j1][1], after_words[j2 - 1][2]] if j2 > j1 else None
        items.append({"before": before, "after": after, "span": span})
    return items


def tgbuild_change_list(original: str, polished: str, max_items: int = 50) -> List[TGChangeItem]:
    """원문/수정문을 비교해 실제로 바뀐 **낱말** 쌍과 그 위치를 낸다.

    Args:
        original: 다듬기 전 텍스트.
        polished: 다듬은 후 텍스트.
        max_items: 응답 크기 제한 (문서가 매우 길 때 result payload 폭주 방지).

    Returns:
        `[{"before", "after", "span"}, ...]` — 바뀐 항목만. `span` 은 `polished` 기준
        `[start, end)` 이고, 삭제만 일어난 자리는 `None` 이다.
    """
    src = _TGsplit_units_with_spans(original)
    dst = _TGsplit_units_with_spans(polished)
    matcher = difflib.SequenceMatcher(
        a=[u[0] for u in src], b=[u[0] for u in dst], autojunk=False
    )

    changes: List[TGChangeItem] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        for item in _TGword_changes(src[i1:i2], dst[j1:j2]):
            changes.append(item)
            if len(changes) >= max_items:
                return changes
    return changes


def _TGprotected_regions(text: str) -> list:
    """태그를 끼우면 손상이 되는 구간 — 코드펜스 안쪽과 HTML 태그."""
    regions: list = []
    pos = 0
    fence_start = None
    for raw in text.splitlines(keepends=True):
        if raw.lstrip().startswith("```"):
            if fence_start is None:
                fence_start = pos
            else:
                regions.append((fence_start, pos + len(raw)))
                fence_start = None
        pos += len(raw)
    if fence_start is not None:
        # 닫히지 않은 펜스는 문서 끝까지 코드로 본다
        regions.append((fence_start, len(text)))
    regions.extend((m.start(), m.end()) for m in _TGHTML_TAG_RE.finditer(text))
    return regions


def tgbuild_highlighted(polished: str, changes: list) -> str:
    """바뀐 자리에 `<mark>` 를 입힌 **표시용 사본**을 만든다. 정본은 손대지 않는다.

    ## 겹침은 병합하고, 뒤에서부터 넣는다

    구간이 겹친 채로 각각 감싸면 `<mark>A<mark>B</mark>C</mark>` 처럼 태그가 교차한다.
    앞에서부터 넣으면 뒤 구간의 좌표가 태그 길이만큼 밀린다. 번역 쪽
    `highlight_translations` 와 같은 규율이다.
    """
    spans: list = []
    for item in changes or []:
        span = (item or {}).get("span")
        if not (isinstance(span, (list, tuple)) and len(span) == 2):
            continue
        start, end = span
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if 0 <= start < end <= len(polished):
            spans.append((start, end))
    if not spans:
        return polished

    protected = _TGprotected_regions(polished)
    spans = [(s, e) for s, e in spans if not any(s < pe and ps < e for ps, pe in protected)]
    if not spans:
        return polished

    merged: list = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    text = polished
    for start, end in reversed(merged):
        text = text[:start] + _TGMARK_OPEN + text[start:end] + _TGMARK_CLOSE + text[end:]
    return text


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
    # `max_items` 로 잘렸으면 뒤쪽 변경은 칠하지 못한다. 그 사실을 응답에 싣는다 —
    # 없으면 "뒷부분은 안 바뀌었다" 와 "상한에 걸려 표시를 못 했다" 가 화면에서 같아 보인다.
    return {
        "ok": True,
        "changes": [dict(item) for item in changes],
        "change_count": len(changes),
        "highlighted": tgbuild_highlighted(revised, changes),
        "truncated": len(changes) >= max_items,
    }


# ── 도구 카탈로그는 손으로 적지 않는다 (2026-08-14) ──────────────────
# 예전에는 `TGTOOL_SPECS` 에 JSON-Schema 를 손으로 적어 뒀다 — `/mcp/list` 를 우리가
# 구현하던 시절의 잔재다. 지금은 `@mcp.tool()` 이 시그니처·타입힌트·독스트링에서
# 카탈로그를 만들므로 그 목록은 **아무 데서도 읽히지 않았고**, 고쳐도 노출되는
# 스키마가 바뀌지 않는다 — 고친 사람은 바뀐 줄 안다. 그래서 지웠다.
# 도구 설명을 고칠 곳은 각 `@mcp.tool()` 함수의 독스트링이다.

_TGHANDLERS = {
    "markdown_structure_issues": _TGmarkdown_structure_issues,
    "fact_issues": _TGfact_issues,
    "numeric_issues": _TGnumeric_issues,
    "diff_changes": _TGdiff_changes,
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
    _TGlog.info("로컬 테스트용 shim 사용", extra={"event": "mcp_shim_used"})


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
        _TGlog.warning("도구 실행 실패", extra={"event": "mcp_tool_failed", "error_type": type(exc).__name__})
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
    """[언제 쓰나] 사용자에게 **어느 낱말이 어떻게 바뀌었는지** 본문 위에서 보여줄 때.

    낱말 단위 변경 내역과 **되쓴 글 기준 문자 위치**를 낸다. **LLM 에 되묻지 않고
    difflib 으로 산출한다** — 되물으면 모델이 실제 변경과 다른 요약을 지어낼 수 있고,
    그 결과는 검증할 방법이 없다.

    Args:
        source: 원문.
        revised: 되쓴 결과.
        max_items: 최대 변경 건수 (1~500, 기본 50).

    Returns:
        JSON 문자열 `{"ok": true, "changes", "change_count", "highlighted", "truncated"}`.
        `changes[]` 는 `{"before", "after", "span"}` 이고 `span` 은 `revised` 기준
        `[start, end)` — 삭제만 일어난 자리는 `null` 이다(칠할 글자가 없다).
        `highlighted` 는 그 자리에 `<mark>` 를 입힌 **표시용 사본**이다. **정본
        `revised` 는 손대지 않는다** — 내려받기가 정본을 그대로 파일로 만든다.
    """
    arguments = {"source": source, "revised": revised}
    if max_items is not None and max_items != "":
        arguments["max_items"] = max_items
    return _tg_run("diff_changes", arguments)
