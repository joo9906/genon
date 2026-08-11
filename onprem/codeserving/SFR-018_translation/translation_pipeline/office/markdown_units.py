"""마크다운/HTML 구조 보존 분해/재조립 (전처리기 산출물 입력 경로).

docx/pdf/hwpx 는 회사 전처리기를 거쳐 들어오며, 표 직렬화 형식이
전처리기 유형에 따라 다르다 (genos_files 전처리기 소스 확인 결과):

- 첨부용(attach_processor): 마크다운 표(| a | b |) + 페이지 마커(<!-- PB -->)
- 지능형(intelligence_processor): table_format 설정에 따라 마크다운 표 또는
  **한 줄짜리 HTML 표** — `제목접두, <table><tbody><tr><th colspan="2">…`
  형태이고 셀 텍스트는 html.escape 되어 있다. colspan 은 보존해야 한다.

"표를 유지하라"는 프롬프트 지시는 보장이 없으므로, 여기서는 분해 시점에
구조 문법(표 파이프, HTML 태그, 제목 #, 목록 마커, 인용 >, 코드펜스)을
스켈레톤 리터럴로 분리해 코드가 쥐고 있고, LLM 에는 **텍스트 내용만**
번역 유닛으로 보낸다. 재조립은 스켈레톤에 번역문을 끼워 넣는 것뿐이라
구조는 LLM 출력 품질과 무관하게 항상 원본과 동일하다.

HTML 표 처리 규칙:
- <table>…</table> 구간(여러 줄 포함)은 태그/텍스트로 토큰화한다.
  태그(<tr>, <td colspan="2"> 등)는 전부 리터럴, 텍스트 노드만 유닛.
- 텍스트 노드는 html.unescape 해서 LLM 에 보내고(엔티티가 섞이면 번역이
  오염된다), 재조립 때 html.escape(quote=False) 로 되돌린다.
  → &amp;/&lt;/&gt; 는 바이트 단위 왕복 보존. &quot;/&#x27; 는 의미 동일한
  원문 문자로 정규화된다 (한계로 문서화).

무손실 계약: 모든 유닛의 번역을 원문 그대로 되돌리면(split → rebuild) 결과가
입력과 바이트 단위로 동일하다. 스켈레톤(구조)과 유닛(내용)이 완전히 분리돼
있다는 보장이며, 재조립이 구조를 건드리지 않음을 뜻한다.

마크다운 처리 규칙 (줄 단위):
- 코드펜스(``` / ~~~) 블록: 펜스 포함 전체를 리터럴 (번역 안 함)
  ※ 한계: 코드펜스 안의 <table> 예시 텍스트는 표 구간으로 오인될 수 있다
  (전처리기 산출물에는 코드펜스+표 HTML 조합이 나오지 않는 것을 확인)
- 표 행(| ... |): 파이프는 리터럴, 셀 텍스트만 유닛. 구분 행(|---|)은 통째 리터럴
- 제목(#), 목록(-, *, 1.), 인용(>): 마커는 리터럴, 뒤 텍스트만 유닛
- HTML 주석 줄(<!-- PB --> 페이지 마커)과 태그로만 이루어진 줄: 리터럴
- 글자(isalpha)가 하나도 없는 조각(숫자·기호만): 유닛 생성 없이 리터럴
  (LLM 호출 낭비 + 숫자 변조 위험 제거)
"""

import html as _html
import re
from typing import Dict, List, Tuple

from .types import TranslationUnit

# 스켈레톤 세그먼트: ("lit", 문자열) 또는 ("unit", translation_unit_id)
Segment = Tuple[str, object]

_HTML_TEXT_TYPE = "html_table_text"  # 재조립 시 html.escape 대상 표식
_TABLE_CELL_TYPE = "table_cell"      # 재조립 시 파이프 이스케이프 대상 표식

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_TABLE_SEP_RE = re.compile(r"^\s*\|?(\s*:?-+:?\s*\|)+\s*:?-*:?\s*\|?\s*$")
_HEADING_RE = re.compile(r"^(#{1,6}\s+)(.*)$")
_LIST_RE = re.compile(r"^(\s*(?:[-*+]|\d{1,3}[.)])\s+)(.*)$")
_QUOTE_RE = re.compile(r"^(\s*(?:>\s?)+)(.*)$")
_HTML_TAG_LINE_RE = re.compile(r"^\s*(</?[A-Za-z][^>]*/?>|<!--.*?-->)+\s*$")
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")

# HTML 표 구간: 한 줄짜리(지능형 기본)와 여러 줄 pretty-print 모두 커버
_HTML_TABLE_REGION_RE = re.compile(r"<table\b.*?</table\s*>", re.IGNORECASE | re.DOTALL)
# HTML 구간 토큰화: 태그(주석 포함) vs 텍스트
_HTML_TOKEN_RE = re.compile(r"(<!--.*?-->|<[^>]+>)", re.DOTALL)


def _has_translatable_text(text: str) -> bool:
    """숫자·기호·공백뿐인 조각은 번역 대상이 아니다 (원문 유지)."""
    return any(ch.isalpha() for ch in text)


class _Builder:
    def __init__(self):
        self.segments: List[Segment] = []
        self.units: List[TranslationUnit] = []

    def lit(self, text: str) -> None:
        if text:
            self.segments.append(("lit", text))

    def _add_unit(self, unit_text: str, element_type: str) -> None:
        unit_id = len(self.units)
        self.units.append(
            TranslationUnit(
                translation_unit_id=unit_id,
                node_id=f"md:{unit_id}",
                text=unit_text,
                element_type=element_type,
            )
        )
        self.segments.append(("unit", unit_id))

    def text(self, text: str, element_type: str) -> None:
        """앞뒤 공백은 리터럴로 보존하고 알맹이만 유닛으로 만든다."""
        if not _has_translatable_text(text):
            self.lit(text)
            return
        stripped = text.strip()
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(lead) + len(stripped):]
        self.lit(lead)
        self._add_unit(stripped, element_type)
        self.lit(trail)

    def html_text(self, text: str) -> None:
        """HTML 텍스트 노드: 엔티티를 풀어 유닛으로 만든다 (재조립 때 재escape)."""
        unescaped = _html.unescape(text)
        if not _has_translatable_text(unescaped):
            self.lit(text)  # 원문 그대로 (엔티티 형태 보존)
            return
        stripped = text.strip()
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(lead) + len(stripped):]
        self.lit(lead)
        self._add_unit(_html.unescape(stripped), _HTML_TEXT_TYPE)
        self.lit(trail)


def _split_table_row(builder: _Builder, line: str) -> None:
    """마크다운 표 행: 파이프 경계는 리터럴, 각 셀 내용만 유닛."""
    cells = _UNESCAPED_PIPE_RE.split(line)
    for idx, cell in enumerate(cells):
        if idx > 0:
            builder.lit("|")
        builder.text(cell, _TABLE_CELL_TYPE)


def _split_html_table(builder: _Builder, fragment: str) -> None:
    """HTML 표 구간: 태그는 리터럴, 텍스트 노드만 유닛 (줄 경계 보존)."""
    for token in _HTML_TOKEN_RE.split(fragment):
        if not token:
            continue
        if token.startswith("<"):
            builder.lit(token)
            continue
        pieces = token.split("\n")
        for idx, piece in enumerate(pieces):
            if idx > 0:
                builder.lit("\n")
            builder.html_text(piece)


def _split_markdown_lines(builder: _Builder, text: str) -> None:
    """HTML 표 구간을 제외한 나머지 텍스트의 줄 단위 마크다운 분해."""
    in_code = False
    for line_no, line in enumerate(text.split("\n")):
        if line_no > 0:
            builder.lit("\n")

        if _FENCE_RE.match(line):
            in_code = not in_code
            builder.lit(line)
            continue
        if in_code or not line.strip() or _HTML_TAG_LINE_RE.match(line):
            builder.lit(line)
            continue
        if line.lstrip().startswith("|"):
            if _TABLE_SEP_RE.match(line):
                builder.lit(line)  # 정렬 구분 행은 통째 보존
            else:
                _split_table_row(builder, line)
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            builder.lit(heading.group(1))
            builder.text(heading.group(2), "heading")
            continue
        quote = _QUOTE_RE.match(line)
        if quote:
            builder.lit(quote.group(1))
            builder.text(quote.group(2), "blockquote")
            continue
        list_item = _LIST_RE.match(line)
        if list_item:
            builder.lit(list_item.group(1))
            builder.text(list_item.group(2), "list_item")
            continue

        builder.text(line, "paragraph")


def split_markdown(markdown: str) -> Tuple[List[Segment], List[TranslationUnit]]:
    """마크다운(HTML 표 포함 가능)을 (스켈레톤, 번역 유닛 목록) 으로 분해한다.

    HTML 표 구간을 먼저 떼어내 태그/텍스트로 토큰화하고, 나머지 텍스트만
    줄 단위 마크다운 규칙으로 처리한다. 같은 줄에 접두 텍스트와 <table> 이
    붙은 지능형 전처리기 형식(`제목, <table>…`)도 이 순서 덕분에 커버된다.
    """
    builder = _Builder()
    pos = 0
    for match in _HTML_TABLE_REGION_RE.finditer(markdown):
        _split_markdown_lines(builder, markdown[pos: match.start()])
        _split_html_table(builder, match.group(0))
        pos = match.end()
    _split_markdown_lines(builder, markdown[pos:])
    return builder.segments, builder.units


def rebuild_markdown(
    segments: List[Segment],
    units: List[TranslationUnit],
    translated_by_unit_id: Dict[int, str],
) -> str:
    """스켈레톤에 번역문을 끼워 원문과 동일한 구조의 문서를 만든다.

    번역이 없는 유닛은 원문 유지 (translate_units 폴백 규약과 동일).
    - 번역문의 줄바꿈은 구조(표 행 등)를 깨뜨리므로 공백으로 정규화한다.
    - **마크다운 표 셀의 번역문에 든 `|` 는 이스케이프한다.** 안 하면 그 셀이 두 칸으로
      쪼개져 그 행부터 열이 밀린다. 분해 때는 원문에 파이프가 없다는 보장이 있었지만
      (파이프가 곧 셀 경계였다) 번역문에는 그 보장이 없다 — LLM 이 열거를
      `A | B` 로 옮기는 경우가 실제로 나온다. HTML 표 셀은 escape 경로가 이미
      막고 있어 마크다운 셀만 뚫려 있었다.
    - HTML 텍스트 유닛은 html.escape(quote=False) 로 재이스케이프한다
      (분해 때 unescape 했으므로 왕복 대칭 — 무손실 계약의 근거).

    무손실 계약은 유지된다: 원문 셀에 파이프가 없으므로 "번역 = 원문"을 넣으면
    이스케이프할 대상이 없어 입력과 바이트 단위로 같은 결과가 나온다.
    """
    unit_by_id = {u.translation_unit_id: u for u in units}
    out: List[str] = []
    for kind, value in segments:
        if kind == "lit":
            out.append(value)
            continue
        unit = unit_by_id[value]
        translated = translated_by_unit_id.get(value, unit.text)
        translated = translated.replace("\r\n", "\n").replace("\n", " ")
        if unit.element_type == _HTML_TEXT_TYPE:
            translated = _html.escape(translated, quote=False)
        elif unit.element_type == _TABLE_CELL_TYPE:
            translated = _UNESCAPED_PIPE_RE.sub(r"\\|", translated)
        out.append(translated)
    return "".join(out)
