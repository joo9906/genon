"""hwpx 본문을 마크다운으로 뽑는다 — **표시 전용 읽기 경로**.

용도: 채팅 UI 가 "지금 문서가 어떤 모양이고 어디에 무엇이 들어갔는지"를 보여줄 때 쓴다.
브라우저는 hwpx 를 렌더링하지 못하고, 다운로드 전에 사용자가 확인할 방법이 필요하다.

이 모듈은 문서를 **읽기만 한다**. 채우기(`hwpx_fields.fill_template`)와 서식
적용(`hwpx_style.apply_styles`)의 어떤 판정에도 개입하지 않는다. 미리보기는
채운 결과 바이트를 그대로 다시 읽어 만들므로(그래서 명세 표기 제거·값 반영이
화면에 그대로 드러난다), 화면과 다운로드 파일이 어긋날 수 없다.

전처리기 규약과 맞춘 점 (CLAUDE.md 전처리기 입력 원칙):
- 표는 **마크다운 표**로 낸다. 첨부형 전처리기가 docx/pdf/hwpx 를 넣을 때 쓰는
  형식과 같아서, LLM 컨텍스트로 재사용해도 표 구조 인식 규칙이 하나로 유지된다.
  **LLM 입력 경로 세 벌(번역·FAQ·MCP)과 일부러 다른 자리다** — 그쪽은 병합·중첩 표를
  HTML 로 내지만 여기는 사람이 보는 화면이라 마크다운을 유지한다
  (`check_table_grid.py` 가 그 차이를 지킨다).

hwpx 표 구조 (domain — 매번 다시 알아내지 말 것):
    hp:p → hp:run → hp:tbl → hp:tr → hp:tc → hp:subList → hp:p → hp:run → hp:t
    <hp:tc><hp:cellAddr colAddr="1" rowAddr="0"/><hp:cellSpan colSpan="2" rowSpan="1"/>
- 셀 좌표는 `cellAddr` 이 정본이다. 병합 셀은 **앵커 셀 하나만 존재**하고 이어지는
  자리에는 hp:tc 가 아예 없다 → 좌표를 무시하고 순서대로 채우면 열이 밀린다.
- 마크다운에는 rowspan 이 없다. 세로 병합은 앵커 행에만 값을 두고 이어지는 행은
  빈 칸으로 남긴다 (구조를 지어내지 않는다).

## 글자는 하나도 버리지 않는다 (2026-08-23 — 전처리기에서 옮겨 왔다)

전처리기(area 05)가 2026-08-19·08-20 에 고친 네 자리가 이 사본에도 있었다. 미리보기는
**사용자가 다운로드 전에 문서를 확인하는 유일한 화면**이라, 여기서 빠진 글자는
"템플릿에 그 내용이 없다" 로 읽힌다 — 실제로는 파일에 있는데 화면에만 없다.

| 잃던 것 | 왜 | 지금 |
|---|---|---|
| 탭·강제 줄바꿈 **뒤** 글자 | `hp:t` 는 혼합 내용이라 그 글자가 자식의 `tail` 에 있는데 `node.text` 만 읽었다 | `_inline_text` 가 `tail` 까지 훑는다 |
| 글상자·도형·각주·머리말·캡션·메모 안 글 | 중첩 문단(`hp:subList > hp:p`)을 "본문 흐름이 아니다" 로 통째로 건너뛰었다 | `_emit_paragraph` 가 상자로 재귀한다 |
| 개요 번호(`1.`·`가.`)와 글머리표(`-`) | 문단 텍스트가 아니라 `Contents/header.xml` 의 정의에서 나온다 | `_Markers` 가 복원한다 |
| 수식 | `hp:equation > hp:script` 에 있어 `hp:t` 만 보면 안 잡힌다 | `_own_text` 가 함께 읽는다 |

**쓰기 경로는 건드리지 않았다.** `hwpx_fields.own_nodes`·`para_text` 는 슬롯 offset 의
기준 문자열을 만드는 함수이고, 거기에 조판 문자나 자동 번호를 끼워 넣으면 **채울 자리의
좌표가 밀린다.** 이 파일이 쓰는 텍스트 조립을 따로 둔 이유가 그것이다 — 미리보기는
"화면에 보이는 것" 을, 채우기는 "본문 XML 에 있는 것" 을 봐야 한다.

경계 (알고 쓰는 한계 — 침묵 처리하지 않기 위해 명시):
- 셀 안에 또 표가 있으면 그 표의 문단 텍스트를 셀 안에 이어 붙인다(구조는 평탄화).
  LLM 입력 경로 세 벌은 이때 HTML 로 바꾸지만, 여기는 화면용이라 평탄화가 맞다.
- 상한(`max_chars`)에 걸려 자른 경우 `MarkdownResult.truncated` 로 알린다.
- 페이지 번호는 복원하지 않는다 — hwpx 본문 XML 에 없다.
"""

import logging
import re
from dataclasses import dataclass

from .document import build as build_document
from .hwpx_fields import (
    HP_NS,
    NEWLINE_REPLACEMENT,
    iter_section_xml,
    nearest_para,
    normalize_text,
    open_hwpx,
    parse_xml,
)

_log = logging.getLogger(__name__)

_PARA = f"{{{HP_NS}}}p"
_TEXT = f"{{{HP_NS}}}t"
_TBL = f"{{{HP_NS}}}tbl"
_TR = f"{{{HP_NS}}}tr"
_TC = f"{{{HP_NS}}}tc"
_CELL_ADDR = f"{{{HP_NS}}}cellAddr"
_CELL_SPAN = f"{{{HP_NS}}}cellSpan"
_POS = f"{{{HP_NS}}}pos"

# 자동 번호·글머리표의 **정의**는 본문이 아니라 여기 있다 (`_Markers`).
_HEADER_ENTRY = "Contents/header.xml"

# 셀 안 줄바꿈은 마크다운 표를 깨뜨린다 — 표에서만 <br> 로 바꾼다
_CELL_LINE_BREAK = "<br>"
_TRUNCATED_MARK = "\n\n…(이후 생략)"

# ── 문단을 품는 상자들 ────────────────────────────────────────────────────────
#
# **글자를 담는 곳은 표 셀만이 아니다.** 글상자·도형(`hp:drawText`), 캡션, 각주·미주,
# 머리말·꼬리말, 숨은 설명, 메모가 전부 자기 안에 `hp:subList > hp:p` 를 갖는다.
# 예전에는 "본문 흐름이 아니다" 는 이유로 **중첩 문단을 통째로 버렸는데**, 버린 것이
# 곧 문서에 보이는 글자라 미리보기에서 그만큼이 조용히 사라졌다.
#
# 지금은 전부 낸다. 어디서 온 글인지 헷갈리지 않게 라벨만 붙이되, **글상자·캡션은
# 본문과 같은 글이라 라벨이 없다** — 라벨은 본문에 없던 글자를 더하는 것이므로 그 글이
# 본문 흐름 밖에 있을 때만 붙인다.
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
# **상자인지는 이름표가 아니라 생김새로 판정한다.** 위 표는 "뭐라고 부를까" 만 정한다 —
# 목록으로 판정하면 여기 안 적힌 상자가 예전처럼 조용히 버려지고, 그 손실은 이름을
# 빠뜨렸다는 사실을 아무도 모르는 채로 남는다. hwpx 에서 문단을 담는 것은 예외 없이
# **`hp:subList` 를 직접 자식으로 두는 원소**다 (표 셀도 그렇다).
_SUBLIST = f"{{{HP_NS}}}subList"

# 수식은 `hp:equation > hp:script` 안에 원본 문자열로 들어 있다. `hp:t` 가 아니라서
# 예전 파서에는 아예 안 잡혔다 — 수식 하나가 통째로 빠지면 그 문단의 뜻이 바뀐다.
_EQUATION = f"{{{HP_NS}}}equation"
_SCRIPT = f"{{{HP_NS}}}script"

# `hp:t` 는 **혼합 내용**이다. 탭·강제 줄바꿈·묶음 빈칸 같은 조판 문자가 자식 원소로
# 들어가고, **그 뒤에 오는 글자는 자식의 `tail` 에 담긴다.** `node.text` 만 읽으면
# 첫 조판 문자 뒤의 글자를 전부 잃는다 — `가.<hp:tab/>지원 대상` 이 `가.` 만 남는 식이다.
_INLINE_CHARS = {
    f"{{{HP_NS}}}tab": "\t",
    f"{{{HP_NS}}}lineBreak": "\n",
    f"{{{HP_NS}}}hyphen": "-",
    f"{{{HP_NS}}}nbSpace": " ",
    f"{{{HP_NS}}}fwSpace": "　",
}


@dataclass(frozen=True)
class MarkdownResult:
    """변환 결과 + 무엇을 얼마나 읽었는지.

    truncated 를 함께 돌려주는 이유: 잘린 미리보기를 문서 전체로 오인하면
    사용자가 빠진 항목을 못 보고 다운로드한다 (미측정을 통과로 보이지 않게 하는
    저장소 원칙과 같은 계열).
    """

    markdown: str
    table_count: int          # `template_index` 가 목록 표시용으로 읽는다
    truncated: bool
    # `paragraph_count` 는 2026-08-14 에 뺐다 — 읽는 코드가 없었다(FAQ·번역의 hwpx 파서는
    # 자기 응답에 싣지만 이 미리보기 경로는 문단 수를 쓰지 않는다).


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


def _read_entry(hwpx_bytes: bytes, name: str) -> bytes:
    """ZIP 안의 항목 하나. **없으면 빈 바이트** — 있어야만 좋아지는 것에 쓴다."""
    with open_hwpx(hwpx_bytes) as archive:
        try:
            return archive.read(name)
        except KeyError:
            return b""


def _inline_text(node) -> str:
    """`hp:t` 한 개가 가진 글자 전부 — **자식 원소의 `tail` 까지.**

    `hp:t` 는 혼합 내용이다. 탭·강제 줄바꿈·묶음 빈칸 같은 조판 문자가 자식 원소로
    들어가고, **그 뒤에 오는 글자는 자식의 `tail`** 에 담긴다. `node.text` 만 읽던 예전
    코드는 조판 문자가 한 번이라도 나오면 **그 뒤 글자를 전부 잃었다** — 남은 앞부분이
    멀쩡한 문장처럼 보여서 무엇이 사라졌는지 드러나지 않는 종류의 손실이다.

    **쓰기 경로(`hwpx_fields.para_text`)는 이 함수를 쓰지 않는다.** 그쪽은 슬롯 offset 의
    기준 문자열이라 본문 XML 에 있는 글자만 담아야 한다 — 조판 문자를 끼우면 채울 자리가
    밀린다. 이 파일의 텍스트 조립이 따로 있는 이유다.
    """
    pieces = [_INLINE_CHARS.get(node.tag, ""), node.text or ""]
    for child in node:
        pieces.append(_inline_text(child))
        pieces.append(child.tail or "")
    return "".join(pieces)


def _own_text(para) -> str:
    """이 문단이 **직접** 가진 텍스트. 표 안 하위 문단 텍스트는 섞지 않는다.

    글자의 출처는 `hp:t` **와 `hp:equation`** 둘이다 — 수식은 `hp:script` 에 원본
    문자열로 들어 있어 `hp:t` 만 보면 수식 하나가 통째로 빠진다.
    """
    parts = []
    for node in para.iter():
        # 태그를 먼저 거른다 — 조상 추적(`nearest_para`)을 모든 노드에 걸면 큰 표
        # 하나가 문단 하나의 글자를 뽑는 데 문서 전체를 훑는 비용이 된다.
        if node.tag == _TEXT:
            if nearest_para(node) is para:
                parts.append(_inline_text(node))
        elif node.tag == _EQUATION and nearest_para(node) is para:
            parts.extend(script.text or "" for script in node.iter(_SCRIPT))
    # 줄바꿈 평탄화는 채우기와 **같은 규칙**을 쓴다(`normalize_text`). 탭은 그쪽이 모른다 —
    # 채우기 경로에는 조판 문자가 오지 않기 때문이다. 미리보기에서만 생기므로 여기서 편다.
    return normalize_text("".join(parts)).replace("\t", NEWLINE_REPLACEMENT).strip()


# ---------------------------------------------------------------------------
# 자동 번호·글머리표 — **문서에 보이는데 본문 XML 에는 없는 글자**
#
# 한/글의 개요 번호(`1.`, `가.`, `1)`)와 글머리표(`-`, `●`)는 문단 텍스트가 아니라
# **문단 모양(`hh:paraPr > hh:heading`)이 가리키는 번호 매기기 정의**에서 나온다.
# 그래서 `hp:t` 만 읽으면 미리보기에서 그 표시가 통째로 사라지고, 사용자는 자기 템플릿의
# 항목 번호가 없어진 화면을 본다 — **파일에는 그대로 있는데 화면에만 없는** 상태다.
#
# **왜 지어내는 것이 아닌가.** 번호는 문서가 자기 안에 정의(`Contents/header.xml`)와
# 참조(`hp:p/@paraPrIDRef`)를 둘 다 갖고 있어 **결정적으로 복원된다.** 한/글이 화면에
# 그리는 계산을 그대로 다시 하는 것이지 추측이 아니다. 복원할 수 없는 형식(정의에 표시
# 문자열이 없는 단계)은 **비워 둔다** — 틀린 번호를 붙이는 것보다 낫다.
#
# **`@idRef` 는 id 로도 인덱스로도 온다.** 실물 한/글은 개요 번호 문단에
# `<hh:heading type="OUTLINE" idRef="0">` 을 쓰는데 `<hh:numbering id=…>` 은 **1 부터**
# 시작한다 — id 로만 찾으면 `get("0")` 이 `None` 이라 **개요 번호가 붙은 모든 문단에서
# 번호만 사라진다.** 그래서 id 로 먼저 찾고, 없으면 문서 순서 0-based 인덱스로 본다.
#
# 이 층의 정본은 전처리기(`onprem/preprocessor/hwpx_preprocessor.py`)다.
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

# 한/글이 "없음" 을 뜻하는 32비트 sentinel. 인덱스 폴백이 이것을 번호로 읽으면
# **그리지 않는 자리에 번호가 생긴다.**
_ID_NONE = "4294967295"

# 정의를 못 찾은 글머리표에 쓸 글자. **글머리표는 정의를 못 찾아도 화면에는 그려진다** —
# 이미지 글머리표(`@char` 없음)가 그렇다. 비워 두면 목록이라는 사실이 통째로 사라진다.
_BULLET_FALLBACK = "-"

# 번호 정의 자체를 못 찾았을 때 쓸 표시 서식. `^N` 은 `_expand_head` 가 채운다.
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
        # 문서 하나가 로그를 수천 줄 채운다.
        self._reported: set = set()
        if header_xml:
            try:
                self._load(parse_xml(header_xml))
            except Exception:
                # 머리 정의를 못 읽는 것으로 미리보기를 막지 않는다 — 번호만 빠진다.
                # `parse_xml` 은 `TemplateError`(사용자 노출용)를 던지는데, 미리보기가
                # 그것 때문에 통째로 실패하면 값 확인 화면 자체가 안 뜬다.
                _log.warning(
                    "hwpx header.xml unreadable; numbering markers are skipped",
                    extra={"event": "hwpx_header_unreadable"},
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
        _log.warning(
            "hwpx marker definition resolved by fallback",
            extra={"event": event, "id_ref": ref},
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
            # 한/글도 그 단계에는 아무것도 그리지 않는다.
            template = defined[depth][0].strip()
        else:
            # **번호는 그려지는데**(heading 이 OUTLINE/NUMBER 다) 그 단계 서식을 모른다.
            # 빈 문자열을 돌려주면 번호가 통째로 사라지는데 로그에도 남지 않는다.
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
    그 키가 정의에 없으면 **정의된 단계를 순서대로 늘어놓고 `@level` 을 인덱스로** 본다.
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


def _is_box(elem) -> bool:
    """문단을 담는 상자인가 — `hp:subList` 를 직접 자식으로 두는가로 본다.

    표 셀(`hp:tc`)·글상자(`hp:drawText`)·캡션·각주·머리말이 전부 이 모양이다.
    **이름 목록이 아니라 모양으로 보는 이유**는 `_BOX_LABELS` 주석에 적었다.
    """
    return elem.find(_SUBLIST) is not None


def _owning_box(node):
    """이 노드를 담고 있는 **가장 가까운 상자**(표 셀 포함). 중첩을 가르는 기준이다."""
    parent = node.getparent()
    while parent is not None:
        if _is_box(parent):
            return parent
        parent = parent.getparent()
    return None


def _owning_object(node):
    """이 노드를 담고 있는 가장 가까운 **개체**(표·상자·셀). 없으면 `None`.

    `_owned_objects` 가 "한 겹만" 고를 때 쓴다 — 표에 달린 캡션은 표가 낼 몫이지
    문단이 따로 낼 몫이 아니다(따로 내면 캡션이 표에서 떨어져 나온다).
    """
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _TBL or _is_box(parent):
            return parent
        parent = parent.getparent()
    return None


def _paras_of(box) -> list:
    """이 상자가 **직접** 가진 문단들. 안쪽 표·상자의 문단은 뺀다."""
    return [para for para in box.iter(_PARA) if _owning_box(para) is box]


def _owned_objects(para) -> list:
    """이 문단에 매달린 개체들 — 표와 상자. **문서 순서대로, 한 겹만.**

    안쪽 것을 함께 고르면 같은 글자가 두 번 나온다(표 → 그 표의 캡션, 도형 → 그 안의
    글상자). "한 겹" 의 기준은 **이 문단과 같은 상자에 들어 있는가** 다.
    """
    box = _owning_box(para)
    return [
        node
        for node in para.iter()
        if (node.tag == _TBL or _is_box(node))
        and nearest_para(node) is para
        and _owning_object(node) is box
    ]


def _captions_of(obj) -> list:
    """이 개체에 **직접** 달린 캡션(표제)."""
    return [node for node in obj.iter(_CAPTION) if _owning_object(node) is obj]


def _box_parts(box, markers=None, inherited: str = "") -> list:
    """상자 안 내용을 `("text", str)`/`("table", elem)` 으로 **문서 순서대로**."""
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
    """셀 내용을 `("text", str)` 과 `("table", elem)` 으로 **문서 순서대로** 나눈다.

    **`_owning_box` 가 아니라 `_owning_object` 로 보는 이유**: 표(`hp:tbl`)는 상자가
    아니라서, 중첩 표의 셀에서 위로 올라가면 표를 지나쳐 **바깥 셀이 소유자로 잡힌다.**
    그러면 같은 글자가 두 번 실린다 — 표가 깨지는 것이 아니라 값이 중복되는 것이라
    눈으로는 정상처럼 보인다.
    """
    parts = []
    for node in tc.iter():
        # 관심 있는 태그인지 **먼저** 본다. 소유 개체 추적을 모든 노드에 걸면 셀 하나에
        # 문서 깊이만큼의 조상 추적이 노드 수만큼 붙는다.
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


def _flatten_table_text(tbl, markers=None) -> list:
    """중첩 표를 **글자로 편다** — 미리보기에는 HTML 경로가 없다.

    LLM 입력 경로 세 벌은 이때 `<table>` 로 바꾸지만(구조를 지켜야 수치가 무엇의
    값인지 남는다), 여기는 사람이 보는 화면이라 마크다운 한 칸 안에 이어 붙인다.
    **구조는 평탄화되지만 내용은 잃지 않는다** — 지우면 셀 안 표가 통째로 사라진다.
    """
    out = []
    for tr in _children(tbl, _TR):
        for tc in _children(tr, _TC):
            for kind, value in _cell_parts(tc, markers):
                if kind == "text":
                    out.append(value)
                else:
                    out.extend(_flatten_table_text(value, markers))
    return out


def _cell_text(tc, markers=None) -> str:
    """셀 텍스트. 여러 문단은 <br> 로 잇고, 파이프는 이스케이프한다.

    파이프를 escape 하지 않으면 셀 내용이 열 경계로 읽혀 표가 밀린다.
    """
    parts = []
    for kind, value in _cell_parts(tc, markers):
        if kind == "text":
            parts.append(value)
        else:
            parts.extend(_flatten_table_text(value, markers))
    # 빈 문단은 버린다 (셀 안 빈 줄이 <br> 로 남아 표가 지저분해지지 않게)
    return _CELL_LINE_BREAK.join(part for part in parts if part).replace("|", "\\|")


def _table_grid(tbl) -> tuple:
    """hp:tbl → `(anchors, height, width)`. `anchors[(row, col)] = tc` — 셀이 **시작하는** 자리.

    격자만 만들고 셀 텍스트는 뽑지 않는다. **`_boxed_text` 가 셀을 세기만 하고 지나갈
    수 있어야 하기 때문**이다 — 텍스트를 함께 뽑으면 그 자리에서 자동 번호 카운터가
    진행되고, 표로 되돌아갔을 때 같은 셀이 두 번 세어진다.
    """
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
                # 좌표가 없는 문서(합성 픽스처 등) — 앞 셀 다음 빈 자리를 쓴다
                row, col = row_index, cursor
                while (row, col) in occupied:
                    col += 1
            anchors[(row, col)] = tc
            for d_row in range(row_span):
                for d_col in range(col_span):
                    occupied.add((row + d_row, col + d_col))
            cursor = col + col_span
            height = max(height, row + row_span)
            width = max(width, col + col_span)

    return anchors, height, width


def _boxed_text(tbl, markers=None):
    """칸이 하나뿐인 표는 **표가 아니라 제목·강조 상자다** → 그 안의 글을 돌려준다.

    hwpx 는 제목상자·박스형 강조를 1칸 표로 만드는 일이 흔한데(이 저장소의 실물 기술
    협상서 2벌이 그렇다), 그대로 표로 내면 본문 행이 0개인 퇴화된 표가 된다:

        | 『…』 사업 기술협상서 |
        |---|

    글자를 잃지는 않지만 미리보기 첫 화면이 **문서 제목 자리에 1행짜리 표**가 된다.
    문단으로 내면 해소된다.

    Returns:
        문단 텍스트. 칸이 하나가 아니거나 **중첩 표가 들어 있으면 `None`** — 후자는
        문단으로 펴면 안쪽 표를 통째로 잃는다.
    """
    anchors, _height, _width = _table_grid(tbl)
    if len(anchors) != 1:
        return None

    # 중첩 표가 들어 있으면 문단으로 펼 수 없다. **`_cell_parts` 결과로 확인하지 않는
    # 이유**: 그 함수는 자동 번호 카운터를 진행시킨다 — 여기서 부르고 표로 되돌아가면
    # 그 셀의 번호가 두 번 세어지고 그 뒤 문서의 번호가 전부 밀린다.
    if any(node is not tbl for node in tbl.iter(_TBL)):
        return None

    (tc,) = anchors.values()
    parts = _cell_parts(tc, markers)
    # 셀 안 여러 문단은 진짜 줄바꿈으로 잇는다 — `<br>` 은 표 한 칸을 지키려고
    # 쓰는 것이라, 표를 벗어난 이 경로에서는 글자로 보일 뿐이다.
    return "\n".join(value for kind, value in parts if kind == "text").strip()


def _render_table(tbl, markers=None) -> list:
    """hp:tbl → 마크다운 표 줄 목록. 셀 좌표(cellAddr)를 정본으로 격자를 만든다."""
    anchors, height, width = _table_grid(tbl)
    if not width or not height:
        return []

    cells = {key: _cell_text(tc, markers) for key, tc in anchors.items()}
    lines = []
    for row in range(height):
        values = [cells.get((row, col), "") for col in range(width)]
        lines.append("| " + " | ".join(v or " " for v in values) + " |")
        if row == 0:
            # 마크다운 표는 구분선이 필수다. hwpx 는 머리행을 표시하지 않으므로
            # 첫 행을 머리행으로 본다 (구조를 지어내지 않는 최소 가정).
            lines.append("|" + "---|" * width)
    return lines


def _vertical_key(tbl):
    """같은 문단에 매달린 개체의 **세로 위치**. 비교할 수 없으면 `None`.

    hwpx 의 표·상자는 문단에 매달리고(anchor), **XML 순서가 곧 화면 순서는 아니다** —
    제목상자와 본문 표가 같은 문단에 매달려 있으면 XML 에는 본문 표가 먼저 있는 일이
    있어 제목이 표 뒤로 밀린다.

    - `hp:pos` 가 없으면 흐름 그대로 → 0
    - `treatAsChar="1"`(글자처럼 취급)은 문단 자리에 그대로 온다 → 0
    - 그 외에는 `vertOffset`. 단 **기준이 문단(`vertRelTo="PARA"`)일 때만** 쓴다.
    """
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
    """한 문단에 매달린 개체들을 화면에 놓이는 순서로. **판정 불가면 문서 순서 그대로.**"""
    if len(tables) < 2:
        return tables
    keys = [_vertical_key(tbl) for tbl in tables]
    if any(key is None for key in keys):
        return tables
    # 색인을 두 번째 키로 둬서 **동점이면 문서 순서**를 지킨다(그리고 lxml 프록시끼리
    # 비교되는 일이 없다 — 색인이 유일하므로 튜플 비교가 거기서 끝난다).
    order = sorted(zip(keys, range(len(tables)), tables), key=lambda item: item[:2])
    return [tbl for _key, _index, tbl in order]


def _emit_paragraph(para, blocks: list, markers, label: str = "") -> None:
    """문단 하나와 거기 매달린 개체들을 블록으로 낸다. 상자 안에서는 재귀한다.

    `label` 은 본문 흐름 **밖에서** 온 글에만 붙는다(각주·머리말 등). 글상자·캡션은
    본문과 같은 글이라 빈 문자열이다.
    """
    # 번호는 누적 상태다 — 글자가 없는 문단에서도 진행시켜야 뒤 번호가 안 밀린다.
    marker = _marker_of(markers, para)
    text = _own_text(para)
    if text:
        blocks.append(("paragraph", f"{label}{marker}{text}"))

    for obj in _in_visual_order(_owned_objects(para)):
        if obj.tag == _TBL:
            _emit_table(obj, blocks, markers, label)
            continue
        # 자기 라벨이 없는 상자(글상자·캡션)는 **바깥 라벨을 물려받는다** — 각주 안
        # 글상자가 "[각주]" 를 잃으면 그 글이 본문 문장으로 읽힌다.
        for inner in _paras_of(obj):
            _emit_paragraph(inner, blocks, markers, _BOX_LABELS.get(obj.tag, "") or label)


def _emit_table(tbl, blocks: list, markers, label: str = "") -> None:
    """표 하나를 블록으로. **캡션이 먼저다** (표제는 표 위에 놓인다)."""
    for caption in _captions_of(tbl):
        for inner in _paras_of(caption):
            _emit_paragraph(inner, blocks, markers, _BOX_LABELS[_CAPTION] or label)

    boxed = _boxed_text(tbl, markers)
    if boxed is not None:
        # 빈 상자는 아예 내지 않는다 — 표로 내면 글자 없는 블록이 생긴다.
        if boxed:
            blocks.append(("paragraph", f"{label}{boxed}"))
        return

    lines = _render_table(tbl, markers)
    if lines:
        blocks.append(("table", "\n".join(lines)))


def render_markdown(hwpx_bytes: bytes, max_chars: int | None = None) -> MarkdownResult:
    """hwpx 본문을 마크다운 문자열로 변환한다.

    Args:
        hwpx_bytes: 원본 또는 **채운 결과** hwpx 바이트.
        max_chars: 출력 상한. 넘으면 자르고 truncated=True 로 알린다.

    Raises:
        TemplateError: ZIP/XML 손상 (hwpx_fields 와 같은 예외·같은 안내문).
    """
    blocks: list = []
    markers = _Markers(_read_entry(hwpx_bytes, _HEADER_ENTRY))

    for _, xml_bytes in iter_section_xml(hwpx_bytes):
        root = parse_xml(xml_bytes)
        # lxml 프록시는 참조가 끊기면 회수된다. 순회 결과를 리스트로 붙들어 둔 뒤에 쓴다.
        for para in list(root.iter(_PARA)):
            # 상자(표 셀·글상자·각주·머리말…) 안 문단은 상위 hp:p 안에 중첩된다.
            # 그 상자를 낼 때 함께 내므로 여기서 건너뛴다 — **버리는 것이 아니다.**
            if nearest_para(para) is not None:
                continue
            _emit_paragraph(para, blocks, markers)

    markdown = "\n\n".join(text for _kind, text in blocks)
    truncated = False
    if max_chars is not None and len(markdown) > max_chars:
        markdown = markdown[:max_chars].rstrip() + _TRUNCATED_MARK
        truncated = True
    return MarkdownResult(
        markdown=markdown,
        table_count=sum(1 for kind, _ in blocks if kind == "table"),
        truncated=truncated,
    )


def render_filled(
    template_bytes: bytes,
    values: dict,
    *,
    max_chars: int | None,
    blocks: list | None = None,
) -> MarkdownResult:
    """지금 값으로 **채운 결과**를 마크다운으로 만든다 (미리보기의 유일한 경로).

    대화(area 02)와 코드 서빙(`GET /preview`, 값 수정 응답)이 모두 이 함수를 쓴다.
    그리고 이 함수는 **다운로드와 같은 조립 파이프라인**(`document.build`)을 부른다 —
    서식만 건너뛸 뿐(`apply_style=False`) 채우기도 블록 삽입도 완전히 같은 코드다.
    서식을 건너뛰는 것이 화면과 파일을 어긋나게 하지 않는 이유: 마크다운에는 글꼴·크기를
    담을 자리가 없고, **명세 표기 제거는 채우기 단계에서 이미 끝난다.**

    미리보기 전용 렌더러를 따로 두던 시절에는 "화면에는 보이는데 파일에는 없는" 상태가
    생길 수 있었다. 지금은 구조상 불가능하다.

    Raises:
        TemplateError: ZIP/XML 손상. 오류를 어떻게 노출할지는 호출부가 정한다
            (대화는 미리보기 없이 진행, API 는 입력 오류로 올린다).
    """
    built = build_document(template_bytes, values, blocks, apply_style=False)
    return render_markdown(built.hwpx_bytes, max_chars=max_chars)
