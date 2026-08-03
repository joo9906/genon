"""다듬기 전/후 마크다운/HTML 구조 훼손 자동 점검.

글다듬이는 문장 문맥이 필요해 문서를 통째로 LLM 에 보내고, 구조 유지는
시스템 프롬프트 지시에 의존한다. 지시는 보장이 아니므로(LLM 응답 불신 원칙),
여기서 다듬기 전/후의 **구조 지문**(표 행·열 수, 제목 수/레벨, 코드펜스 수,
HTML 표의 행/셀 수)을 결정적으로 비교해 훼손이 감지되면 경고를 만든다.

전처리기 유형에 따라 표 형식이 다르다: 첨부용은 마크다운 표(| a | b |),
지능형은 HTML 표(<table><tbody>… 한 줄, colspan 포함) — 둘 다 점검한다.

경고는 차단이 아니라 노출이다 — 결과는 그대로 전달하되 사용자와 로그에
"구조가 변형됐을 수 있음"을 알린다 (실패 침묵 처리 금지 컨벤션).
번역과 달리 원문 폴백을 하지 않는 이유: 다듬기는 문장 재작성이 목적이라
문단 줄 수 변화가 정상이며, 구조 요소만 선별 비교한다.
"""

import re
from dataclasses import dataclass, field

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_HEADING_RE = re.compile(r"^(#{1,6})\s")
_TABLE_SEP_RE = re.compile(r"^\s*\|?(\s*:?-+:?\s*\|)+\s*:?-*:?\s*\|?\s*$")
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")
_HTML_TABLE_REGION_RE = re.compile(r"<table\b.*?</table\s*>", re.IGNORECASE | re.DOTALL)
_HTML_TR_RE = re.compile(r"<tr\b", re.IGNORECASE)
_HTML_CELL_RE = re.compile(r"<t[dh]\b", re.IGNORECASE)


@dataclass
class _Fingerprint:
    headings: list = field(default_factory=list)   # 제목 레벨 순서 [1, 2, 2, ...]
    table_rows: list = field(default_factory=list)  # 행별 열 수 (구분 행 제외)
    separator_rows: int = 0                          # 표 구분 행(|---|) 수
    fences: int = 0                                  # 코드펜스 줄 수
    html_tables: list = field(default_factory=list)  # HTML 표별 (행 수, 셀 수)


def _fingerprint(text: str) -> _Fingerprint:
    fp = _Fingerprint()
    # HTML 표 구간을 먼저 지문화하고 제거 — 남은 텍스트만 줄 단위 점검
    # (한 줄짜리 HTML 표 안의 텍스트가 마크다운 규칙에 잘못 걸리지 않게)
    for region in _HTML_TABLE_REGION_RE.findall(text):
        fp.html_tables.append(
            (len(_HTML_TR_RE.findall(region)), len(_HTML_CELL_RE.findall(region)))
        )
    text = _HTML_TABLE_REGION_RE.sub("", text)

    in_code = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            fp.fences += 1
            in_code = not in_code
            continue
        if in_code:
            continue
        heading = _HEADING_RE.match(line.strip())
        if heading:
            fp.headings.append(len(heading.group(1)))
            continue
        if line.lstrip().startswith("|"):
            if _TABLE_SEP_RE.match(line):
                fp.separator_rows += 1
            else:
                fp.table_rows.append(len(_UNESCAPED_PIPE_RE.findall(line)) - 1)
    return fp


def find_structure_issues(original: str, polished: str) -> list:
    """구조 지문을 비교해 훼손 항목의 고정 안내문 목록을 반환한다 (없으면 빈 리스트)."""
    before, after = _fingerprint(original), _fingerprint(polished)
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
