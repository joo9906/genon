"""hwpx 본문을 마크다운으로 직접 뽑는다 (전처리기를 거치지 않는 입력 경로).

## 왜 직접 파싱하는가

docx·pdf 는 전처리기가 마크다운으로 바꿔 주지만 **hwpx 는 직접 파싱해야 한다**
(요구사항 §1). 표를 전처리기에 태우면 안의 수치가 깨지는데, FAQ 는 표에 든
날짜·금액·기한을 그대로 근거로 삼아야 하므로 그 손실을 받을 수 없다.

셀 좌표는 `hp:cellAddr` 이 정본이다. 병합 셀은 **앵커 셀 하나만 존재**하고 이어지는
자리에는 `hp:tc` 가 아예 없다 → 좌표를 무시하고 등장 순서로 채우면 열이 밀린다.

**이 파일은 SFR-006 `hwpx_markdown.py`·SFR-018_translation `hwpx_text.py`·MCP
`genon_hwpx_text.py`·전처리기 `final_preprocessor.py` PART 2 와 같은 규칙의 사본이다**
(배포 단위 간 import 금지). 파싱 규칙을 고칠 때는 다섯을 함께 보고,
`onprem/test/check_table_grid.py` 가 **동작으로** 대조한다.

## 산출물이 곧 FAQ 입력이자 근거 대조 원본이다

여기서 만든 마크다운이 LLM 컨텍스트가 되고, 동시에 `evidence.py` 가 LLM 이 돌려준
근거 문장을 대조하는 원본이 된다. 두 곳이 다른 텍스트를 보면 근거가 있는데도
기각되는 일이 생긴다.

## 글자는 하나도 버리지 않는다 (2026-08-23 — 전처리기에서 옮겨 왔다)

표를 지키려고 만든 파서였는데 **표가 아닌 글자를 네 자리에서 잃고 있었다.** 전처리기
(area 05)가 2026-08-19·08-20 에 고친 그 네 자리이고, 이 사본에는 없었다. FAQ 에서 이
손실은 특히 조용하다 — 빠진 글자는 **원문에 없는 것으로 취급**되므로 그 내용을 근거로
삼은 항목이 `ungrounded` 로 기각되고, 기각 사유는 "LLM 이 지어냈다" 로 보인다.

| 잃던 것 | 왜 | 지금 |
|---|---|---|
| 탭·강제 줄바꿈 **뒤** 글자 | `hp:t` 는 혼합 내용이라 그 글자가 자식의 `tail` 에 있는데 `node.text` 만 읽었다 | `_inline_text` 가 `tail` 까지 훑는다 |
| 글상자·도형·각주·머리말·캡션·메모 안 글 | 중첩 문단(`hp:subList > hp:p`)을 "본문 흐름이 아니다" 로 통째로 건너뛰었다 | `_emit_paragraph` 가 상자로 재귀한다 |
| 개요 번호(`1.`·`가.`)와 글머리표(`-`) | 문단 텍스트가 아니라 `Contents/header.xml` 의 정의에서 나온다 | `_Markers` 가 복원한다 |
| 수식 | `hp:equation > hp:script` 에 있어 `hp:t` 만 보면 안 잡힌다 | `_own_text` 가 함께 읽는다 |

**전처리기와 일부러 다른 것은 표 렌더링 하나다.** 전처리기는 병합이 없는 표도 언제나
HTML 로 내지만(RAG 검색 결과가 프롬프트로 조립될 때 개행이 뭉개진다) 이 경로는 그
조립을 지나지 않으므로 **잃을 것이 없는 표는 마크다운 그대로 둔다**(`_needs_html`).

## 경계 (알고 쓰는 한계)

- 셀 안에 또 표가 있으면 마크다운으로 표현할 수 없어 HTML 로 낸다(`_needs_html`).
- 마크다운에 rowspan 이 없다. 세로 병합이 있는 표도 HTML 로 낸다.
- **읽기 전용이다.** 이 단위는 hwpx 를 쓰지 않는다 — 산출 형식이 txt 하나이기 때문이다
  (2026-08-12). hwpx 를 만들던 경로는 걷어냈고, 이 파일의 역할은 **입력**뿐이다.
"""

import html as _html
import io
import re
import zipfile
from dataclasses import dataclass

from lxml import etree

from .hwpx_xml import (
    BOX_LABELS,
    CAPTION,
    CELL_ADDR,
    CELL_SPAN,
    EQUATION,
    INLINE_CHARS,
    PARA,
    POS,
    SCRIPT,
    TBL,
    TC,
    TEXT,
    TR,
    captions_of,
    is_box,
    nearest_para,
    owned_objects,
    owning_object,
    paras_of,
)
from .logging_utils import log_warning

# 본문은 Contents/sectionN.xml 이다. header.xml 은 서식 정의라 본문이 아니지만,
# 자동 번호·글머리표의 **정의**가 거기 있어 따로 읽는다 (`_Markers`).
_SECTION_ENTRY_RE = re.compile(r"^Contents/section(\d+)\.xml$")
_HEADER_ENTRY = "Contents/header.xml"

# <hp:t> 안의 \n 은 문단 분리가 아니다 — 그대로 두면 마크다운에서 문단이 갈린다
_NEWLINE_REPLACEMENT = " "
# 셀 안 줄바꿈은 마크다운 표를 깨뜨린다 — 표에서만 <br> 로 바꾼다
_CELL_LINE_BREAK = "<br>"


class HwpxParseError(ValueError):
    """hwpx 해석 실패 (ZIP/XML 손상).

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다.
    호출부가 사용자 노출 오류로 그대로 쓴다 (3.8절).
    """


@dataclass(frozen=True)
class HwpxDocument:
    markdown: str
    paragraph_count: int
    table_count: int


def _open(hwpx_bytes: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(hwpx_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise HwpxParseError("hwpx 파일이 아니거나 손상된 파일입니다.") from exc


def _section_order(entry_name: str):
    """본문 섹션이면 섹션 번호, 아니면 None.

    문자열 정렬을 쓰지 않는 이유: `section10` 이 `section2` 앞에 온다. 문단 순서가
    밀리면 근거 대조에서 인용 위치가 어긋난다.
    """
    match = _SECTION_ENTRY_RE.match(entry_name)
    return int(match.group(1)) if match else None


def _iter_section_xml(hwpx_bytes: bytes):
    with _open(hwpx_bytes) as archive:
        names = [n for n in archive.namelist() if _section_order(n) is not None]
        for name in sorted(names, key=_section_order):
            yield name, archive.read(name)


def _read_entry(hwpx_bytes: bytes, name: str) -> bytes:
    """ZIP 안의 항목 하나. **없으면 빈 바이트** — 있어야만 좋아지는 것에 쓴다."""
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


def _inline_text(node) -> str:
    """`hp:t` 한 개가 가진 글자 전부 — **자식 원소의 `tail` 까지.**

    `hp:t` 는 혼합 내용이다. 탭·강제 줄바꿈·묶음 빈칸 같은 조판 문자가 자식 원소로
    들어가고, **그 뒤에 오는 글자는 자식의 `tail`** 에 담긴다. `node.text` 만 읽던 예전
    코드는 조판 문자가 한 번이라도 나오면 **그 뒤 글자를 전부 잃었다** — 남은 앞부분이
    멀쩡한 문장처럼 보여서 무엇이 사라졌는지 드러나지 않는 종류의 손실이다.

    조판 문자 자체도 글자로 되살린다(탭·줄바꿈은 뒤에서 공백으로 정규화된다) — 없애면
    `1.지원대상` 처럼 이름표와 내용이 붙는다.
    """
    pieces = [INLINE_CHARS.get(node.tag, ""), node.text or ""]
    for child in node:
        pieces.append(_inline_text(child))
        pieces.append(child.tail or "")
    return "".join(pieces)


def _own_text(para) -> str:
    """이 문단이 **직접** 가진 텍스트 (중첩 문단 제외 규칙은 `hwpx_xml` 에 있다).

    글자의 출처는 `hp:t` **와 `hp:equation`** 둘이다 — 수식은 `hp:script` 에 원본
    문자열로 들어 있어 `hp:t` 만 보면 수식 하나가 통째로 빠진다.
    """
    parts = []
    for node in para.iter():
        # 태그를 먼저 거른다 — 조상 추적(`nearest_para`)을 모든 노드에 걸면 큰 표
        # 하나가 문단 하나의 글자를 뽑는 데 문서 전체를 훑는 비용이 된다.
        if node.tag == TEXT:
            if nearest_para(node) is para:
                parts.append(_inline_text(node))
        elif node.tag == EQUATION and nearest_para(node) is para:
            parts.extend(script.text or "" for script in node.iter(SCRIPT))
    text = "".join(parts).replace("\r\n", "\n")
    text = text.replace("\n", _NEWLINE_REPLACEMENT)
    text = text.replace("\t", _NEWLINE_REPLACEMENT)
    return text.strip()


def _children(elem, tag: str) -> list:
    """직접 자식만 (중첩 표의 tr/tc 가 섞이지 않게)."""
    return [child for child in elem if child.tag == tag]


def _int_attr(elem, name: str, default: int) -> int:
    if elem is None:
        return default
    try:
        return int((elem.get(name) or "").strip())
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# 자동 번호·글머리표 — **문서에 보이는데 본문 XML 에는 없는 글자**
#
# 한/글의 개요 번호(`1.`, `가.`, `1)`)와 글머리표(`-`, `●`)는 문단 텍스트가 아니라
# **문단 모양(`hh:paraPr > hh:heading`)이 가리키는 번호 매기기 정의**에서 나온다.
# 그래서 `hp:t` 만 읽으면 그 표시가 통째로 사라진다 — 화면에서
#
#     - 사용자가 문서를 업로드한다
#     - 시스템이 문서보안을 해제한다
#
# 이던 것이 FAQ 입력에서는 앞의 `-` 가 없는 두 문장이 되고, **목록이라는 사실과 항목의
# 층위가 함께 없어진다.** 근거 대조도 마찬가지다 — LLM 이 `1. 사업 개요` 를 인용하면
# 원문에는 `사업 개요` 만 있어 표기 차이로 기각될 수 있다.
#
# **왜 지어내는 것이 아닌가.** 번호는 문서가 자기 안에 정의(`Contents/header.xml`)와
# 참조(`hp:p/@paraPrIDRef`)를 둘 다 갖고 있어 **결정적으로 복원된다.** 한/글이 화면에
# 그리는 계산을 그대로 다시 하는 것이지 추측이 아니다. 다만 복원할 수 없는 형식
# (정의에 표시 문자열이 없는 단계 등)은 **비워 둔다** — 틀린 번호를 붙이는 것보다 낫다.
#
# **`@idRef` 는 id 로도 인덱스로도 온다.** 실물 한/글은 개요 번호 문단에
# `<hh:heading type="OUTLINE" idRef="0">` 을 쓰는데 `<hh:numbering id=…>` 은 **1 부터**
# 시작한다 — id 로만 찾으면 `get("0")` 이 `None` 이라 **개요 번호가 붙은 모든 문단에서
# 번호만 사라진다.** 저장소 실물 4벌이 전부 그 모양이었다(`idRef="0"` × 7단계).
#
# 그래서 **id 로 먼저 찾고, 없으면 문서 순서 0-based 인덱스로 본다.** 순서가 이렇게 된
# 이유는 `type="NUMBER"`(문단 번호)가 id 를 그대로 참조하는 경우를 앞의 매치가 지키기
# 때문이다.
#
# 이 층의 정본은 전처리기(`onprem/preprocessor/final_preprocessor.py` PART 2)다.
# ---------------------------------------------------------------------------
HH_NS = "http://www.hancom.co.kr/hwpml/2011/head"

_HEADING = f"{{{HH_NS}}}heading"
_PARA_PR = f"{{{HH_NS}}}paraPr"
_NUMBERING = f"{{{HH_NS}}}numbering"
_PARA_HEAD = f"{{{HH_NS}}}paraHead"
_BULLET = f"{{{HH_NS}}}bullet"

# 번호 매기기를 쓰는 문단 모양 종류. `NONE` 은 번호가 없는 보통 문단이다.
_HEADING_NUMBERED = ("OUTLINE", "NUMBER")
_HEADING_BULLET = "BULLET"

# 한/글이 "없음" 을 뜻하는 32비트 sentinel. 실물 header.xml 이 `charPrIDRef` 에 쓰는
# 그 값이다. 인덱스 폴백이 이것을 번호로 읽으면 **그리지 않는 자리에 번호가 생긴다.**
_ID_NONE = "4294967295"

# 정의를 못 찾은 글머리표에 쓸 글자. **글머리표는 정의를 못 찾아도 화면에는 그려진다** —
# 이미지 글머리표(`@char` 없음)가 그렇다. 비워 두면 목록이라는 사실이 통째로 사라진다.
_BULLET_FALLBACK = "-"

# 번호 정의 자체를 못 찾았을 때 쓸 표시 서식. `^N` 은 `_expand_head` 가 채운다.
# **표시 문자열이 빈 단계와 다른 경우다** — 그쪽은 한/글도 아무것도 그리지 않으므로
# 비워 두는 것이 원문에 맞고, 이쪽은 무언가 그려지는데 무엇인지 모르는 것이다.
_NUMBER_FALLBACK_TEMPLATE = "^{depth}."

# 표시 문자열 안의 `^N` = N 단계의 번호. `(^5)` → `(3)`.
_HEAD_TOKEN_RE = re.compile(r"\^(\d+)")

# 번호 서식. hwpx 가 쓰는 이름 그대로 둔다 — 옮겨 적으면 원문 대조가 안 된다.
_HANGUL_SYLLABLES = "가나다라마바사아자차카타파하"
_HANGUL_JAMO = "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"
_ROMAN_UNITS = (
    (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
    (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
)


def _cycle(alphabet: str, number: int) -> str:
    """`가`…`하` 다음은 `가가` — 한/글이 도는 방식 그대로."""
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
    """번호 하나를 서식에 맞춰 글자로. 모르는 서식은 숫자로 떨어진다."""
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
    """자동 번호·글머리표 복원기. `Contents/header.xml` 을 한 번 읽어 상태를 든다.

    `advance()` 는 **문단마다 정확히 한 번** 불러야 한다 — 번호는 누적 상태라 건너뛰면
    그 뒤 번호가 전부 밀린다. 그래서 글자가 없는 문단에서도 부르고(한/글도 빈 문단에
    번호를 매긴다), 붙이는 것만 글자가 있을 때 한다.
    """

    def __init__(self, header_xml: bytes = b"") -> None:
        self._para_pr: dict = {}
        self._numbering: dict = {}
        self._bullets: dict = {}
        self._counters: dict = {}
        # 폴백을 밟았다는 사실은 **문서마다 한 번만** 남긴다 — 문단마다 남기면 정상
        # 문서 하나가 로그를 수천 줄 채우고, 정작 봐야 할 줄이 그 사이에 묻힌다.
        self._reported: set = set()
        if header_xml:
            try:
                self._load(_parse_xml(header_xml))
            except HwpxParseError:
                # 머리 정의를 못 읽는 것으로 FAQ 생성을 막지 않는다 — 번호만 빠진다.
                log_warning(
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
        # `resource_id` 로 싣는 이유: 3.8절 화이트리스트에 없는 이름(`id_ref` 등)은
        # **값이 버려지고 이름만 남는다.** 그러면 "폴백을 밟았다" 는 사실은 남는데
        # 어느 정의에서 밟았는지가 사라져 진단이 안 된다. 이 값은 문서 안 정의 번호라
        # 본문 내용이 아니다 (전처리기는 화이트리스트가 없어 `id_ref` 로 싣는다).
        log_warning(
            "hwpx marker definition resolved by fallback", event=event, resource_id=ref
        )

    def _resolve(self, table: dict, ref: str, event: str):
        """`@idRef` → 정의. **id 로 먼저, 없으면 문서 순서 0-based 인덱스로.**

        Returns:
            `(키, 정의)`. 어느 쪽으로도 못 찾으면 `(ref, None)`.

        **키를 함께 돌려주는 이유**는 누적 카운터를 그 키로 들기 때문이다: 원본 ref 로
        들면 `idRef="0"` 과 `idRef="1"` 이 같은 정의를 가리키는데도 번호가 따로 세어져
        한 목록이 `1. 1. 2. 2.` 로 나온다.
        """
        if ref in table:
            return ref, table[ref]
        # sentinel 은 "정의 없음" 이다. 인덱스로 읽으면 안 그리는 자리에 표시가 생긴다.
        if ref == _ID_NONE or not ref.isdigit():
            return ref, None
        order = list(table)
        index = int(ref)
        if index < len(order):
            self._report_once(event, ref)
            return order[index], table[order[index]]
        return ref, None

    def advance(self, para) -> str:
        """이 문단 앞에 놓일 표시. 없으면 빈 문자열. **상태를 진행시킨다.**"""
        kind, ref, level = self._para_pr.get(para.get("paraPrIDRef"), ("NONE", "", 0))
        if ref == _ID_NONE:
            return ""
        if kind == _HEADING_BULLET:
            _key, char = self._resolve(self._bullets, ref, "hwpx_bullet_ref_by_index")
            # 글머리표는 정의를 못 찾아도 화면에는 그려진다 — 글자만 모른다.
            return f"{char or _BULLET_FALLBACK} "
        if kind not in _HEADING_NUMBERED:
            return ""
        num_id, levels = self._resolve(self._numbering, ref, "hwpx_numbering_ref_by_index")
        depth, defined = _head_depth(level, levels)
        counters = self._counters.setdefault(num_id, {})
        _text, _fmt, start = defined.get(depth, ("", "DIGIT", 1))
        counters[depth] = counters.get(depth, start - 1) + 1
        # 더 깊은 단계는 되돌린다 — 새 상위 항목이 열리면 하위 번호는 1부터다.
        for deeper in [key for key in counters if key > depth]:
            del counters[deeper]

        if depth in defined:
            # 정의된 단계다. **표시 문자열이 비었으면 비워 두는 것이 원문에 맞다** —
            # 한/글도 그 단계에는 아무것도 그리지 않는다. `strip()` 은 헤더가
            # 줄바꿈·들여쓰기와 함께 저장된 문서 때문이다.
            template = defined[depth][0].strip()
        else:
            # **번호는 그려지는데**(heading 이 OUTLINE/NUMBER 다) 그 단계 서식을 모른다.
            # 빈 문자열을 돌려주면 "번호가 통째로 사라지는데 로그에도 남지 않는" 상태가
            # 된다 — 정의를 찾았고 폴백도 밟지 않으므로 아무 흔적이 없다.
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
    """`hh:heading/@level` → 번호 정의(`hh:paraHead`)의 단계 키. → `(키, 정의 표)`.

    `@level` 은 0-based, `hh:paraHead/@level` 은 1-based 라 보통 `level + 1` 이다.
    그 키가 정의에 없으면 **정의된 단계를 순서대로 늘어놓고 `@level` 을 인덱스로** 본다
    (`@idRef` 를 id → 인덱스 순으로 보는 것과 같은 방식이다).
    """
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
    """`markers` 가 없으면(표만 따로 렌더링할 때) 표시도 없다."""
    return markers.advance(para) if markers is not None else ""


def _box_parts(box, markers=None, inherited: str = "") -> list:
    """상자 안 내용을 `("text", str)`/`("table", elem)` 으로 **문서 순서대로**.

    셀 안에 들어 있는 상자를 셀 글자로 펴는 자리다. 상자 안 표는 표로 남긴다 —
    글자로 펴면 그 수치가 무엇의 값인지 사라진다.
    """
    label = BOX_LABELS.get(box.tag, "") or inherited
    parts = []
    for para in paras_of(box):
        text = _own_text(para)
        if text:
            parts.append(("text", f"{label}{_marker_of(markers, para)}{text}"))
        for obj in owned_objects(para):
            if obj.tag == TBL:
                for caption in captions_of(obj):
                    parts.extend(_box_parts(caption, markers, label))
                parts.append(("table", obj))
            else:
                parts.extend(_box_parts(obj, markers, label))
    return parts


def _cell_parts(tc, markers=None) -> list:
    """셀 내용을 `("text", str)` 과 `("table", elem)` 으로 **문서 순서대로** 나눈다.

    `tc.iter(hp:p)` 를 그대로 쓰면 **중첩 표 안의 문단까지 딸려온다.** 그러면 2열짜리
    표가 `소분류<br>값` 이라는 한 덩어리 텍스트가 되어 구조가 통째로 사라진다.
    소유 개체를 따져 자기 것만 고른다. 셀 안 글상자·캡션·각주는 그 상자를 펴서 셀
    글자에 잇는다.

    **`owning_box` 가 아니라 `owning_object` 로 보는 이유**: 표(`hp:tbl`)는 상자가
    아니라서, 중첩 표의 셀에서 위로 올라가면 표를 지나쳐 **바깥 셀이 소유자로 잡힌다.**
    그러면 그 셀이 중첩 표를 `("table", …)` 로 한 번 내고, 이어서 그 표의 셀들을
    상자로 또 펴서 **같은 글자가 두 번 실린다.** 표가 깨지는 것이 아니라 값이 중복되는
    것이라 눈으로는 정상처럼 보인다.
    """
    parts = []
    for node in tc.iter():
        # 관심 있는 태그인지 **먼저** 본다. 소유 개체 추적을 모든 노드에 걸면 셀 하나에
        # 문서 깊이만큼의 조상 추적이 노드 수만큼 붙는다.
        if node.tag != PARA and node.tag != TBL and not is_box(node):
            continue
        if owning_object(node) is not tc:
            continue
        if node.tag == PARA:
            text = _own_text(node)
            if text:
                parts.append(("text", f"{_marker_of(markers, node)}{text}"))
        elif node.tag == TBL:
            for caption in captions_of(node):
                parts.extend(_box_parts(caption, markers))
            parts.append(("table", node))
        else:
            parts.extend(_box_parts(node, markers))
    return parts


def _cell_text(tc, markers=None) -> str:
    """마크다운 표용 셀 텍스트. 여러 문단은 <br> 로 잇고 파이프는 이스케이프한다.

    파이프를 escape 하지 않으면 셀 내용이 열 경계로 읽혀 표가 밀린다.

    이 경로는 **중첩 표가 없는 표에서만** 쓰인다 (`_needs_html` 이 갈라낸다).
    """
    parts = [value for kind, value in _cell_parts(tc, markers) if kind == "text"]
    return _CELL_LINE_BREAK.join(parts).replace("|", "\\|")


def _cell_html(tc, markers=None) -> str:
    """HTML 표용 셀 내용. 중첩 표는 `<table>` 로 그대로 살린다.

    텍스트는 `html.escape(quote=False)` 로 감싼다 — 지능형 전처리기가 내는 한 줄 HTML
    표와 같은 규약이다. 따옴표는 이스케이프하지 않는다(속성값이 아니라 본문이다).
    """
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
    """hp:tbl → `(anchors, covered, height, width)`.

    `anchors[(row, col)] = (tc, row_span, col_span)` — 셀이 **시작하는** 자리.
    `covered` 는 병합으로 덮인 자리(앵커 제외). 병합 셀은 앵커에만 내용이 있으므로,
    이 둘을 가르지 않으면 아래 행에서 열이 밀린다.
    """
    anchors: dict = {}
    occupied: set = set()
    height = 0
    width = 0

    for row_index, tr in enumerate(_children(tbl, TR)):
        cursor = 0
        for tc in _children(tr, TC):
            addr = tc.find(CELL_ADDR)
            span = tc.find(CELL_SPAN)
            col_span = _int_attr(span, "colSpan", 1)
            row_span = _int_attr(span, "rowSpan", 1)
            if addr is not None:
                row = _int_attr(addr, "rowAddr", row_index)
                col = _int_attr(addr, "colAddr", cursor)
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


def _needs_html(tbl) -> bool:
    """마크다운 표로 **표현할 수 없는** 구조인가.

    둘 중 하나라도 있으면 마크다운은 정보를 잃는다:

    - **병합 셀** — `rowspan`/`colspan` 에 해당하는 문법이 없다. 지금은 빈 칸이 되어
      LLM 이 "머리글이 없는 열" 로 읽는다.
    - **중첩 표** — 마크다운 표는 중첩이 안 된다. 안쪽 표가 텍스트로 뭉개진다.
      (셀 안 **글상자에 든** 표도 여기 걸린다 — `iter` 가 깊이를 가리지 않는다.)

    잃을 것이 없는 단순한 표는 마크다운 그대로 둔다 — 토큰도 적고 사람이 읽기도 낫다.
    **전처리기(area 05)는 이 판정을 쓰지 않는다** — 그쪽은 검색 결과 조립에서 개행이
    뭉개지므로 언제나 HTML 이다. 일부러 다른 자리다.
    """
    if any(node is not tbl for node in tbl.iter(TBL)):
        return True
    for tr in _children(tbl, TR):
        for tc in _children(tr, TC):
            span = tc.find(CELL_SPAN)
            if _int_attr(span, "rowSpan", 1) > 1 or _int_attr(span, "colSpan", 1) > 1:
                return True
    return False


def _table_markdown(tbl, markers=None) -> list:
    """hp:tbl → 마크다운 표 줄 목록 (병합·중첩이 없는 표 전용)."""
    anchors, _covered, height, width = _table_grid(tbl)
    if not width or not height:
        return []

    lines = []
    for row in range(height):
        values = [
            _cell_text(anchors[(row, col)][0], markers) if (row, col) in anchors else ""
            for col in range(width)
        ]
        lines.append("| " + " | ".join(value or " " for value in values) + " |")
        if row == 0:
            # 마크다운 표는 구분선이 필수다. hwpx 는 머리행 표시가 없으므로 첫 행을
            # 머리행으로 본다 (구조를 지어내지 않는 최소 가정).
            lines.append("|" + "---|" * width)
    return lines


def _table_html(tbl, markers=None) -> list:
    """hp:tbl → HTML 표 줄 목록. `rowspan`/`colspan`/중첩을 그대로 살린다.

    형태는 지능형 전처리기가 내는 것과 맞춘다(`<table><tbody><tr><td>…`) — 새 형식을
    만드는 것이 아니라 **이미 지원하는 형식**으로 내는 것이다.

    행마다 한 줄로 끊는다. 한 줄로 몰아도 동작하지만(전처리기가 그렇게 낸다) 사람이
    읽을 수 없고, 표가 크면 진단이 불가능해진다.
    """
    anchors, covered, height, width = _table_grid(tbl)
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
            cells.append(f"<td{attrs}>{_cell_html(tc, markers)}</td>")
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines.append("</tbody></table>")
    return lines


def _render_table(tbl, markers=None) -> list:
    """hp:tbl → 표 줄 목록.

    **병합·중첩이 있으면 HTML, 아니면 마크다운.** 마크다운으로 손실 없이 표현할 수
    있는 표는 그대로 두고, 표현할 수 없는 것만 형식을 바꾼다.
    """
    return _table_html(tbl, markers) if _needs_html(tbl) else _table_markdown(tbl, markers)


def _vertical_key(tbl):
    """같은 문단에 매달린 개체의 **세로 위치**. 비교할 수 없으면 `None`.

    hwpx 의 표·상자는 문단에 매달리고(anchor), **XML 순서가 곧 화면 순서는 아니다.**
    실물에서 드러났다: 제목상자(1칸 표, `treatAsChar="1"`)와 본문 표
    (`treatAsChar="0"`, `vertOffset="5940"`)가 **같은 문단**에 매달려 있는데 XML 에는
    본문 표가 먼저 있어, 문서 제목이 표 **뒤로** 밀렸다.

    - `hp:pos` 가 없으면 흐름 그대로 → 0
    - `treatAsChar="1"`(글자처럼 취급)은 문단 자리에 그대로 온다 → 0
    - 그 외에는 `vertOffset`. 단 **기준이 문단(`vertRelTo="PARA"`)일 때만** 쓴다 —
      페이지·단 기준 오프셋은 문단 기준 값과 크기를 비교할 수 없다.
    """
    found = _children(tbl, POS)
    if not found:
        return 0
    pos = found[0]
    if pos.get("treatAsChar") == "1":
        return 0
    if (pos.get("vertRelTo") or "PARA") != "PARA":
        return None
    return _int_attr(pos, "vertOffset", 0)


def _in_visual_order(tables: list) -> list:
    """한 문단에 매달린 개체들을 화면에 놓이는 순서로. **판정 불가면 문서 순서 그대로.**

    개체가 하나뿐이면(대부분의 문서) 손대지 않는다 — 이 정렬은 한 문단이 둘 이상을
    물고 있을 때만 의미가 있다.
    """
    if len(tables) < 2:
        return tables
    keys = [_vertical_key(tbl) for tbl in tables]
    if any(key is None for key in keys):
        return tables
    # 색인을 두 번째 키로 둬서 **동점이면 문서 순서**를 지킨다(그리고 lxml 프록시끼리
    # 비교되는 일이 없다 — 색인이 유일하므로 튜플 비교가 거기서 끝난다).
    order = sorted(zip(keys, range(len(tables)), tables), key=lambda item: item[:2])
    return [tbl for _key, _index, tbl in order]


def _boxed_text(tbl, markers=None):
    """칸이 하나뿐인 표는 **표가 아니라 제목·강조 상자다** → 그 안의 글을 돌려준다.

    hwpx 는 제목상자·박스형 강조를 1칸 표로 만드는 일이 흔한데(이 저장소의 실물 기술
    협상서 2벌이 그렇다), 그대로 표로 내면 본문 행이 0개인 퇴화된 표가 된다:

        | 『…』 사업 기술협상서 |
        |---|

    글자를 잃지는 않지만 **문서 제목이 표 한 칸으로 나간다.** 번역이면 그 구분선이
    결과물에 그대로 남고, FAQ 면 제목이 표 행으로 인용되며, 미리보기면 제목 자리에
    1행짜리 표가 보인다. 문단으로 내면 셋 다 해소된다.

    Returns:
        문단 텍스트. 칸이 하나가 아니거나 **중첩 표가 들어 있으면 `None`** — 후자는
        문단으로 펴면 안쪽 표를 통째로 잃는다.
    """
    anchors, _covered, _height, _width = _table_grid(tbl)
    if len(anchors) != 1:
        return None

    # 중첩 표가 들어 있으면 문단으로 펼 수 없다 — 안쪽 표를 통째로 잃는다.
    # **`_cell_parts` 결과로 확인하지 않는 이유**(2026-08-23): 그 함수는 자동 번호
    # 카운터를 진행시킨다. 여기서 부르고 나서 표로 되돌아가면 렌더링이 같은 셀을 다시
    # 훑어 **그 셀의 번호가 두 번 세어지고, 그 뒤 문서의 번호가 전부 밀린다.**
    # 번호가 있는데 틀린 상태라 빠진 것보다 알아채기 어렵다.
    if any(node is not tbl for node in tbl.iter(TBL)):
        return None

    (tc, _row_span, _col_span), = anchors.values()
    parts = _cell_parts(tc, markers)
    # 셀 안 여러 문단은 진짜 줄바꿈으로 잇는다 — `<br>` 은 표 한 칸을 지키려고
    # 쓰는 것이라, 표를 벗어난 이 경로에서는 글자로 보일 뿐이다.
    return "\n".join(value for kind, value in parts if kind == "text").strip()


def _emit_paragraph(para, blocks: list, markers, label: str = "") -> None:
    """문단 하나와 거기 매달린 개체들을 블록으로 낸다. 상자 안에서는 재귀한다.

    `label` 은 본문 흐름 **밖에서** 온 글에만 붙는다(각주·머리말 등). 글상자·캡션은
    본문과 같은 글이라 빈 문자열이다 — 라벨은 원문에 없던 글자를 더하는 것이므로,
    출처를 모르면 뜻이 달라지는 자리에만 쓴다.
    """
    # 번호는 누적 상태다 — 글자가 없는 문단에서도 진행시켜야 뒤 번호가 안 밀린다.
    marker = _marker_of(markers, para)
    text = _own_text(para)
    if text:
        blocks.append(("paragraph", f"{label}{marker}{text}"))

    # XML 순서가 아니라 **화면 순서**로 낸다 — 같은 문단에 제목상자와 본문 표가 함께
    # 매달려 있으면 XML 에서는 표가 먼저 나오는 일이 있다(`_in_visual_order`).
    for obj in _in_visual_order(owned_objects(para)):
        if obj.tag == TBL:
            _emit_table(obj, blocks, markers, label)
            continue
        # 자기 라벨이 없는 상자(글상자·캡션)는 **바깥 라벨을 물려받는다** — 각주 안
        # 글상자가 "[각주]" 를 잃으면 그 글이 본문 문장으로 읽힌다.
        for inner in paras_of(obj):
            _emit_paragraph(inner, blocks, markers, BOX_LABELS.get(obj.tag, "") or label)


def _emit_table(tbl, blocks: list, markers, label: str = "") -> None:
    """표 하나를 블록으로. **캡션이 먼저다** (표제는 표 위에 놓인다)."""
    for caption in captions_of(tbl):
        for inner in paras_of(caption):
            _emit_paragraph(inner, blocks, markers, BOX_LABELS[CAPTION] or label)

    boxed = _boxed_text(tbl, markers)
    if boxed is not None:
        # 빈 상자는 아예 내지 않는다 — 표로 내면 글자 없는 블록이 생긴다.
        if boxed:
            blocks.append(("paragraph", f"{label}{boxed}"))
        return

    lines = _render_table(tbl, markers)
    if lines:
        blocks.append(("table", "\n".join(lines)))


def to_markdown(hwpx_bytes: bytes, max_chars: int = 0) -> HwpxDocument:
    """hwpx 본문을 마크다운 문자열로 변환한다.

    Args:
        hwpx_bytes: 업로드된 hwpx 바이트.
        max_chars: 0 보다 크면 그 길이에서 자른다 (LLM 예산 보호는 호출부 책임이지만,
            파싱 산출물 자체를 무제한으로 메모리에 들고 있지 않기 위한 상한).

    Raises:
        HwpxParseError: ZIP/XML 손상.
    """
    blocks: list = []
    markers = _Markers(_read_entry(hwpx_bytes, _HEADER_ENTRY))

    for _, xml_bytes in _iter_section_xml(hwpx_bytes):
        root = _parse_xml(xml_bytes)
        # lxml 프록시는 참조가 끊기면 회수된다. 순회 결과를 리스트로 붙들어 둔 뒤에 쓴다.
        for para in list(root.iter(PARA)):
            # 상자(표 셀·글상자·각주·머리말…) 안 문단은 상위 hp:p 안에 중첩된다.
            # 그 상자를 낼 때 함께 내므로 여기서 건너뛴다 — **버리는 것이 아니다.**
            if nearest_para(para) is not None:
                continue
            _emit_paragraph(para, blocks, markers)

    markdown = "\n\n".join(text for _kind, text in blocks)
    if max_chars > 0 and len(markdown) > max_chars:
        markdown = markdown[:max_chars].rstrip()
    return HwpxDocument(
        markdown=markdown,
        paragraph_count=sum(1 for kind, _ in blocks if kind == "paragraph"),
        table_count=sum(1 for kind, _ in blocks if kind == "table"),
    )
