# =====================================================================================
# genon_hwpx_text — hwpx 직접 파싱 MCP 도구 (area 01)
#
# **이 파일 하나가 등록 단위다.** GenOS MCP 는 소스 파일 한 개를 받아 실행하며,
# `mcp` 객체를 런타임이 전역으로 주입한다. 그래서 패키지로 쪼갤 수 없고,
# 여기에 파싱 로직·도구 정의가 전부 들어 있다.
#
# **모든 최상위 심볼에 `HX` 접두어를 붙였다.** 한 서버에 다른 도구 파일이 함께 로드될 수
# 있어서다 — `ToolError`·`to_markdown` 같은 흔한 이름을 그대로 두면 나중에 로드된 쪽이
# 앞엣것을 덮어쓰고, 그 실패는 "도구가 이상한 결과를 낸다" 로만 드러난다.
#
# LLM 을 부르지 않는다. 같은 입력에 항상 같은 결과가 나온다.
# =====================================================================================

import base64
import html as _html
import importlib.util
import io
import json
import logging
import os
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass


# ── 로깅 ───────────────────────────────────────────
# **`print()` 를 쓰지 않는다** (GENOS_RULES §C, 가이드 3.10). MCP 는 stdout 이 전송 채널이
# 될 수 있고(stdio 방식), 그러면 로그 한 줄이 프로토콜을 깨뜨린다 — `eval/` 이 stderr 전용
# 로깅을 쓰는 이유와 같다. 값(문서 원문·경로·시크릿)은 메시지에 넣지 않고 예외 **타입**만
# 남긴다(3.8절).
_HXlog = logging.getLogger("genon_hwpx_text")


def _HXsetup_logging() -> None:
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
    if _HXlog.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    _HXlog.addHandler(handler)
    _HXlog.setLevel(logging.INFO)
    # 루트로 올리지 않는다 — 루트에 stdout 핸들러가 붙어 있으면 그리로 새어 나간다.
    _HXlog.propagate = False


_HXsetup_logging()


def _hx_ensure_packages():
    """MCP 기본 이미지에 없는 패키지를 기동 시 설치한다.

    `lxml` 하나뿐이다. 표 격자를 `cellAddr` 좌표로 만들려면 XML 트리 순회가 필요한데,
    stdlib `ElementTree` 는 부모 추적이 없어 `_HXnearest_para` 를 구현할 수 없다.
    """
    for pkg, install_name in (("lxml", "lxml"),):
        if not importlib.util.find_spec(pkg):
            _HXlog.info("의존 패키지 설치 시작", extra={"event": "mcp_dep_install_started"})
            subprocess.check_call([sys.executable, "-m", "pip", "install", install_name])
            _HXlog.info("의존 패키지 설치 완료", extra={"event": "mcp_dep_install_done"})


_hx_ensure_packages()

from lxml import etree  # noqa: E402

# ── hwpx_text.py ─────────────────────────────
HXHP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"

_HXPARA = f"{{{HXHP_NS}}}p"
_HXTEXT = f"{{{HXHP_NS}}}t"
_HXTBL = f"{{{HXHP_NS}}}tbl"
_HXTR = f"{{{HXHP_NS}}}tr"
_HXTC = f"{{{HXHP_NS}}}tc"
_HXCELL_ADDR = f"{{{HXHP_NS}}}cellAddr"
_HXCELL_SPAN = f"{{{HXHP_NS}}}cellSpan"
_HXPOS = f"{{{HXHP_NS}}}pos"

# 본문은 Contents/sectionN.xml 이다. header.xml 은 서식 정의라 본문이 아니지만,
# 자동 번호·글머리표의 **정의**가 거기 있어 따로 읽는다 (`_HXMarkers`).
_HXSECTION_ENTRY_RE = re.compile(r"^Contents/section(\d+)\.xml$")
_HXHEADER_ENTRY = "Contents/header.xml"

# ── 문단을 품는 상자들 ────────────────────────────────────────────────────────
#
# **글자를 담는 곳은 표 셀만이 아니다.** 글상자·도형(`hp:drawText`), 캡션, 각주·미주,
# 머리말·꼬리말, 숨은 설명, 메모가 전부 자기 안에 `hp:subList > hp:p` 를 갖는다.
# 예전에는 "본문 흐름이 아니다" 는 이유로 **중첩 문단을 통째로 버렸는데**, 버린 것이
# 곧 문서에 보이는 글자라, 이 도구를 부른 워크플로우 스텝이 LLM 에 넘기는 본문에서
# 그만큼이 조용히 사라졌다.
#
# 지금은 전부 낸다. 어디서 온 글인지 헷갈리지 않게 라벨만 붙이되, **글상자·캡션은
# 본문과 같은 글이라 라벨이 없다** — 라벨은 본문에 없던 글자를 더하는 것이므로 그 글이
# 본문 흐름 밖에 있을 때만 붙인다.
_HXDRAW_TEXT = f"{{{HXHP_NS}}}drawText"
_HXCAPTION = f"{{{HXHP_NS}}}caption"
_HXFOOT_NOTE = f"{{{HXHP_NS}}}footNote"
_HXEND_NOTE = f"{{{HXHP_NS}}}endNote"
_HXPAGE_HEADER = f"{{{HXHP_NS}}}header"
_HXPAGE_FOOTER = f"{{{HXHP_NS}}}footer"
_HXHIDDEN_COMMENT = f"{{{HXHP_NS}}}hiddenComment"
_HXMEMO = f"{{{HXHP_NS}}}memo"

_HXBOX_LABELS = {
    _HXDRAW_TEXT: "",
    _HXCAPTION: "",
    _HXFOOT_NOTE: "[각주] ",
    _HXEND_NOTE: "[미주] ",
    _HXPAGE_HEADER: "[머리말] ",
    _HXPAGE_FOOTER: "[꼬리말] ",
    _HXHIDDEN_COMMENT: "[숨은 설명] ",
    _HXMEMO: "[메모] ",
}
# **상자인지는 이름표가 아니라 생김새로 판정한다.** 위 표는 "뭐라고 부를까" 만 정한다 —
# 목록으로 판정하면 여기 안 적힌 상자(덧말 등 hwpx 가 나중에 늘릴 수 있는 것)가 예전처럼
# 조용히 버려지고, 그 손실은 이름을 빠뜨렸다는 사실을 아무도 모르는 채로 남는다.
# hwpx 에서 문단을 담는 것은 예외 없이 **`hp:subList` 를 직접 자식으로 두는 원소**다
# (표 셀도 그렇다). 그 모양을 기준으로 본다.
_HXSUBLIST = f"{{{HXHP_NS}}}subList"

# 수식은 `hp:equation > hp:script` 안에 원본 문자열로 들어 있다. `hp:t` 가 아니라서
# 예전 파서에는 아예 안 잡혔다 — 수식 하나가 통째로 빠지면 그 문단의 뜻이 바뀐다.
_HXEQUATION = f"{{{HXHP_NS}}}equation"
_HXSCRIPT = f"{{{HXHP_NS}}}script"

# `hp:t` 는 **혼합 내용**이다. 탭·강제 줄바꿈·묶음 빈칸 같은 조판 문자가 자식 원소로
# 들어가고, **그 뒤에 오는 글자는 자식의 `tail` 에 담긴다.** `node.text` 만 읽으면
# 첫 조판 문자 뒤의 글자를 전부 잃는다 — `가.<hp:tab/>지원 대상` 이 `가.` 만 남는 식이다.
_HXINLINE_CHARS = {
    f"{{{HXHP_NS}}}tab": "\t",
    f"{{{HXHP_NS}}}lineBreak": "\n",
    f"{{{HXHP_NS}}}hyphen": "-",
    f"{{{HXHP_NS}}}nbSpace": " ",
    f"{{{HXHP_NS}}}fwSpace": "　",
}

# <hp:t> 안의 \n 은 문단 분리가 아니다 — 그대로 두면 마크다운에서 문단이 갈린다
_HXNEWLINE_REPLACEMENT = " "
# 셀 안 줄바꿈은 마크다운 표를 깨뜨린다 — 표에서만 <br> 로 바꾼다
_HXCELL_LINE_BREAK = "<br>"


class HXHwpxParseError(ValueError):
    """hwpx 해석 실패 (ZIP/XML 손상).

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다.
    호출부가 사용자 노출 오류로 그대로 쓴다 (3.8절).
    """


@dataclass(frozen=True)
class HXHwpxDocument:
    markdown: str
    paragraph_count: int
    table_count: int


def _HXopen(hwpx_bytes: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(hwpx_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise HXHwpxParseError("hwpx 파일이 아니거나 손상된 파일입니다.") from exc


def _HXsection_order(entry_name: str):
    """본문 섹션이면 섹션 번호, 아니면 None.

    문자열 정렬을 쓰지 않는 이유: `section10` 이 `section2` 앞에 온다. 문단 순서가
    밀리면 문단 순서가 원본과 어긋나고, 이 도구를 쓰는 쪽은 그것을 알 방법이 없다.
    """
    match = _HXSECTION_ENTRY_RE.match(entry_name)
    return int(match.group(1)) if match else None


def _HXiter_section_xml(hwpx_bytes: bytes):
    with _HXopen(hwpx_bytes) as archive:
        names = [n for n in archive.namelist() if _HXsection_order(n) is not None]
        for name in sorted(names, key=_HXsection_order):
            yield name, archive.read(name)


def _HXread_entry(hwpx_bytes: bytes, name: str) -> bytes:
    """ZIP 안의 항목 하나. **없으면 빈 바이트** — 있어야만 좋아지는 것에 쓴다."""
    with _HXopen(hwpx_bytes) as archive:
        try:
            return archive.read(name)
        except KeyError:
            return b""


def _HXparse_xml(xml_bytes: bytes):
    try:
        return etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise HXHwpxParseError("hwpx 본문 XML 을 해석하지 못했습니다.") from exc


def _HXnearest_para(node):
    """이 노드를 직접 담고 있는 문단. 표 안(hp:tc→hp:subList→hp:p)까지 따라간다."""
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _HXPARA:
            return parent
        parent = parent.getparent()
    return None


def _HXinline_text(node) -> str:
    """`hp:t` 한 개가 가진 글자 전부 — **자식 원소의 `tail` 까지.**

    `hp:t` 는 혼합 내용이다. 탭·강제 줄바꿈·묶음 빈칸 같은 조판 문자가 자식 원소로
    들어가고, **그 뒤에 오는 글자는 자식의 `tail`** 에 담긴다. `node.text` 만 읽던 예전
    코드는 조판 문자가 한 번이라도 나오면 **그 뒤 글자를 전부 잃었다** — 남은 앞부분이
    멀쩡한 문장처럼 보여서 무엇이 사라졌는지 드러나지 않는 종류의 손실이다.

    조판 문자 자체도 글자로 되살린다(탭·줄바꿈은 뒤에서 공백으로 정규화된다) — 없애면
    `1.지원대상` 처럼 이름표와 내용이 붙는다.
    """
    pieces = [_HXINLINE_CHARS.get(node.tag, ""), node.text or ""]
    for child in node:
        pieces.append(_HXinline_text(child))
        pieces.append(child.tail or "")
    return "".join(pieces)


def _HXown_text(para) -> str:
    """이 문단이 **직접** 가진 텍스트.

    hwpx 표는 hp:p → hp:run → hp:tbl → … → hp:p 로 중첩된다. `para.iter()` 를 그대로
    쓰면 표 전체가 한 문단으로 붙어 마크다운이 통째로 깨진다.

    글자의 출처는 `hp:t` **와 `hp:equation`** 둘이다 — 수식은 `hp:script` 에 원본
    문자열로 들어 있어 `hp:t` 만 보면 수식 하나가 통째로 빠진다.
    """
    parts = []
    for node in para.iter():
        # 태그를 먼저 거른다 — 조상 추적(`_HXnearest_para`)을 모든 노드에 걸면 큰 표
        # 하나가 문단 하나의 글자를 뽑는 데 문서 전체를 훑는 비용이 된다.
        if node.tag == _HXTEXT:
            if _HXnearest_para(node) is para:
                parts.append(_HXinline_text(node))
        elif node.tag == _HXEQUATION and _HXnearest_para(node) is para:
            parts.extend(script.text or "" for script in node.iter(_HXSCRIPT))
    text = "".join(parts).replace("\r\n", "\n")
    text = text.replace("\n", _HXNEWLINE_REPLACEMENT)
    text = text.replace("\t", _HXNEWLINE_REPLACEMENT)
    return text.strip()


def _HXchildren(elem, tag: str) -> list:
    """직접 자식만 (중첩 표의 tr/tc 가 섞이지 않게)."""
    return [child for child in elem if child.tag == tag]


def _HXint_attr(elem, name: str, default: int) -> int:
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
# 이던 것이 이 도구의 산출물에서는 앞의 `-` 가 없는 두 문장이 되고, **목록이라는 사실과
# 항목의 층위가 함께 없어진다.** 도구를 부른 LLM 은 원문에 목록이 있었다는 것을 알
# 방법이 없다 — 표가 깨지는 것과 달리 **없어진 자리에 흔적이 남지 않는다.**
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
# 이 층의 정본은 전처리기(`onprem/preprocessor/hwpx_preprocessor.py`)다. 고칠 때는
# 다섯 벌(전처리기 + 여기 + FAQ + MCP + 006)을 함께 본다 — `check_table_grid.py` 의
# "누락 방지" 층이 대조한다.
# ---------------------------------------------------------------------------
HXHH_NS = "http://www.hancom.co.kr/hwpml/2011/head"

_HXHEADING = f"{{{HXHH_NS}}}heading"
_HXPARA_PR = f"{{{HXHH_NS}}}paraPr"
_HXNUMBERING = f"{{{HXHH_NS}}}numbering"
_HXPARA_HEAD = f"{{{HXHH_NS}}}paraHead"
_HXBULLET = f"{{{HXHH_NS}}}bullet"

# 번호 매기기를 쓰는 문단 모양 종류. `NONE` 은 번호가 없는 보통 문단이다.
_HXHEADING_NUMBERED = ("OUTLINE", "NUMBER")
_HXHEADING_BULLET = "BULLET"

# 한/글이 "없음" 을 뜻하는 32비트 sentinel. 실물 header.xml 이 `charPrIDRef` 에 쓰는
# 그 값이다. 인덱스 폴백이 이것을 번호로 읽으면 **그리지 않는 자리에 번호가 생긴다.**
_HXID_NONE = "4294967295"

# 정의를 못 찾은 글머리표에 쓸 글자. **글머리표는 정의를 못 찾아도 화면에는 그려진다** —
# 이미지 글머리표(`@char` 없음)가 그렇다. 비워 두면 목록이라는 사실이 통째로 사라진다.
_HXBULLET_FALLBACK = "-"

# 번호 정의 자체를 못 찾았을 때 쓸 표시 서식. `^N` 은 `_HXexpand_head` 가 채운다.
# **표시 문자열이 빈 단계와 다른 경우다** — 그쪽은 한/글도 아무것도 그리지 않으므로
# 비워 두는 것이 원문에 맞고, 이쪽은 무언가 그려지는데 무엇인지 모르는 것이다.
_HXNUMBER_FALLBACK_TEMPLATE = "^{depth}."

# 표시 문자열 안의 `^N` = N 단계의 번호. `(^5)` → `(3)`.
_HXHEAD_TOKEN_RE = re.compile(r"\^(\d+)")

# 번호 서식. hwpx 가 쓰는 이름 그대로 둔다 — 옮겨 적으면 원문 대조가 안 된다.
_HXHANGUL_SYLLABLES = "가나다라마바사아자차카타파하"
_HXHANGUL_JAMO = "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"
_HXROMAN_UNITS = (
    (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
    (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
)


def _HXcycle(alphabet: str, number: int) -> str:
    """`가`…`하` 다음은 `가가` — 한/글이 도는 방식 그대로."""
    if number < 1:
        return ""
    index, repeat = (number - 1) % len(alphabet), (number - 1) // len(alphabet) + 1
    return alphabet[index] * repeat


def _HXroman(number: int) -> str:
    if number < 1:
        return ""
    out = []
    for value, letters in _HXROMAN_UNITS:
        while number >= value:
            out.append(letters)
            number -= value
    return "".join(out)


def _HXformat_number(number: int, num_format: str) -> str:
    """번호 하나를 서식에 맞춰 글자로. 모르는 서식은 숫자로 떨어진다."""
    if num_format == "HANGUL_SYLLABLE":
        return _HXcycle(_HXHANGUL_SYLLABLES, number)
    if num_format == "HANGUL_JAMO":
        return _HXcycle(_HXHANGUL_JAMO, number)
    if num_format == "CIRCLED_DIGIT":
        return chr(0x2460 + number - 1) if 1 <= number <= 20 else str(number)
    if num_format == "CIRCLED_HANGUL_SYLLABLE":
        return chr(0x326E + number - 1) if 1 <= number <= 14 else _HXcycle(_HXHANGUL_SYLLABLES, number)
    if num_format == "CIRCLED_HANGUL_JAMO":
        return chr(0x3260 + number - 1) if 1 <= number <= 14 else _HXcycle(_HXHANGUL_JAMO, number)
    if num_format == "LATIN_CAPITAL":
        return _HXcycle("ABCDEFGHIJKLMNOPQRSTUVWXYZ", number)
    if num_format == "LATIN_SMALL":
        return _HXcycle("abcdefghijklmnopqrstuvwxyz", number)
    if num_format == "ROMAN_CAPITAL":
        return _HXroman(number).upper()
    if num_format == "ROMAN_SMALL":
        return _HXroman(number)
    return str(number)


class _HXMarkers:
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
                self._load(_HXparse_xml(header_xml))
            except HXHwpxParseError:
                # 머리 정의를 못 읽는 것으로 도구 호출을 막지 않는다 — 번호만 빠진다.
                _HXlog.warning(
                    "hwpx header.xml unreadable; numbering markers are skipped",
                    extra={"event": "hwpx_header_unreadable"},
                )

    def _load(self, root) -> None:
        for para_pr in root.iter(_HXPARA_PR):
            heading = para_pr.find(_HXHEADING)
            if para_pr.get("id") is None or heading is None:
                continue
            self._para_pr[para_pr.get("id")] = (
                heading.get("type") or "NONE",
                heading.get("idRef") or "",
                _HXint_attr(heading, "level", 0),
            )
        for numbering in root.iter(_HXNUMBERING):
            levels = {}
            for head in numbering.iter(_HXPARA_HEAD):
                levels[_HXint_attr(head, "level", 0)] = (
                    head.text or "",
                    head.get("numFormat") or "DIGIT",
                    _HXint_attr(head, "start", 1),
                )
            self._numbering[numbering.get("id")] = levels
        for bullet in root.iter(_HXBULLET):
            self._bullets[bullet.get("id")] = bullet.get("char") or ""

    def _report_once(self, event: str, ref: str) -> None:
        if (event, ref) in self._reported:
            return
        self._reported.add((event, ref))
        _HXlog.warning(
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
        if ref == _HXID_NONE or not ref.isdigit():
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
        if ref == _HXID_NONE:
            return ""
        if kind == _HXHEADING_BULLET:
            _key, char = self._resolve(self._bullets, ref, "hwpx_bullet_ref_by_index")
            # 글머리표는 정의를 못 찾아도 화면에는 그려진다 — 글자만 모른다.
            return f"{char or _HXBULLET_FALLBACK} "
        if kind not in _HXHEADING_NUMBERED:
            return ""
        num_id, levels = self._resolve(self._numbering, ref, "hwpx_numbering_ref_by_index")
        depth, defined = _HXhead_depth(level, levels)
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
            template = _HXNUMBER_FALLBACK_TEMPLATE.format(depth=depth)
        if not template:
            return ""
        return f"{_HXHEAD_TOKEN_RE.sub(lambda m: _HXexpand_head(m, defined, counters), template)} "


def _HXhead_depth(level: int, levels) -> tuple:
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


def _HXexpand_head(match, levels: dict, counters: dict) -> str:
    depth = int(match.group(1))
    _text, num_format, start = levels.get(depth, ("", "DIGIT", 1))
    return _HXformat_number(counters.get(depth, start), num_format)


def _HXmarker_of(markers, para) -> str:
    """`markers` 가 없으면(표만 따로 렌더링할 때) 표시도 없다."""
    return markers.advance(para) if markers is not None else ""


def _HXis_box(elem) -> bool:
    """문단을 담는 상자인가 — `hp:subList` 를 직접 자식으로 두는가로 본다.

    표 셀(`hp:tc`)·글상자(`hp:drawText`)·캡션·각주·머리말이 전부 이 모양이다.
    **이름 목록이 아니라 모양으로 보는 이유**는 `_HXBOX_LABELS` 주석에 적었다.
    """
    return elem.find(_HXSUBLIST) is not None


def _HXowning_box(node):
    """이 노드를 담고 있는 **가장 가까운 상자**(표 셀 포함). 중첩을 가르는 기준이다.

    예전에는 셀(`hp:tc`)만 봤다. 그러면 셀 안 글상자·캡션·각주의 문단이 "이 셀 것이
    아니다" 로 떨어져 **어디에서도 안 나온다** — 셀 렌더링은 자기 것이 아니라고 건너뛰고,
    본문 렌더링은 중첩 문단이라고 건너뛴다.
    """
    parent = node.getparent()
    while parent is not None:
        if _HXis_box(parent):
            return parent
        parent = parent.getparent()
    return None


def _HXowning_object(node):
    """이 노드를 담고 있는 가장 가까운 **개체**(표·상자·셀). 없으면 `None`.

    `_HXowned_objects` 가 "한 겹만" 고를 때 쓴다 — 표에 달린 캡션은 표가 낼 몫이지
    문단이 따로 낼 몫이 아니다(따로 내면 캡션이 표에서 떨어져 나온다).
    """
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _HXTBL or _HXis_box(parent):
            return parent
        parent = parent.getparent()
    return None


def _HXparas_of(box) -> list:
    """이 상자가 **직접** 가진 문단들. 안쪽 표·상자의 문단은 뺀다."""
    return [para for para in box.iter(_HXPARA) if _HXowning_box(para) is box]


def _HXowned_objects(para) -> list:
    """이 문단에 매달린 개체들 — 표와 상자. **문서 순서대로, 한 겹만.**

    안쪽 것을 함께 고르면 같은 글자가 두 번 나온다(표 → 그 표의 캡션, 도형 → 그 안의
    글상자). "한 겹" 의 기준은 **이 문단과 같은 상자에 들어 있는가** 다 — 문단이 본문에
    있으면 개체도 본문에 있어야 하고, 문단이 글상자 안이면 개체도 그 글상자 것이라야
    한다. `None` 고정으로 두면 글상자 안 표가 통째로 빠진다.
    """
    box = _HXowning_box(para)
    return [
        node
        for node in para.iter()
        if (node.tag == _HXTBL or _HXis_box(node))
        and _HXnearest_para(node) is para
        and _HXowning_object(node) is box
    ]


def _HXcaptions_of(obj) -> list:
    """이 개체에 **직접** 달린 캡션(표제)."""
    return [node for node in obj.iter(_HXCAPTION) if _HXowning_object(node) is obj]


def _HXbox_parts(box, markers=None, inherited: str = "") -> list:
    """상자 안 내용을 `("text", str)`/`("table", elem)` 으로 **문서 순서대로**.

    셀 안에 들어 있는 상자를 셀 글자로 펴는 자리다. 상자 안 표는 표로 남긴다 —
    글자로 펴면 그 수치가 무엇의 값인지 사라진다.
    """
    label = _HXBOX_LABELS.get(box.tag, "") or inherited
    parts = []
    for para in _HXparas_of(box):
        text = _HXown_text(para)
        if text:
            parts.append(("text", f"{label}{_HXmarker_of(markers, para)}{text}"))
        for obj in _HXowned_objects(para):
            if obj.tag == _HXTBL:
                for caption in _HXcaptions_of(obj):
                    parts.extend(_HXbox_parts(caption, markers, label))
                parts.append(("table", obj))
            else:
                parts.extend(_HXbox_parts(obj, markers, label))
    return parts


def _HXcell_parts(tc, markers=None) -> list:
    """셀 내용을 `("text", str)` 과 `("table", elem)` 으로 **문서 순서대로** 나눈다.

    `tc.iter(hp:p)` 를 그대로 쓰면 **중첩 표 안의 문단까지 딸려온다.** 그러면 2열짜리
    표가 `소분류<br>값` 이라는 한 덩어리 텍스트가 되어 구조가 통째로 사라진다.
    소유 개체를 따져 자기 것만 고른다. 셀 안 글상자·캡션·각주는 그 상자를 펴서 셀
    글자에 잇는다.

    **`_HXowning_box` 가 아니라 `_HXowning_object` 로 보는 이유**: 표(`hp:tbl`)는 상자가
    아니라서, 중첩 표의 셀에서 위로 올라가면 표를 지나쳐 **바깥 셀이 소유자로 잡힌다.**
    그러면 그 셀이 중첩 표를 `("table", …)` 로 한 번 내고, 이어서 그 표의 셀들을
    상자로 또 펴서 **같은 글자가 두 번 실린다.** 표가 깨지는 것이 아니라 값이 중복되는
    것이라 눈으로는 정상처럼 보인다.
    """
    parts = []
    for node in tc.iter():
        # 관심 있는 태그인지 **먼저** 본다. 소유 개체 추적을 모든 노드에 걸면 셀 하나에
        # 문서 깊이만큼의 조상 추적이 노드 수만큼 붙는다.
        if node.tag != _HXPARA and node.tag != _HXTBL and not _HXis_box(node):
            continue
        if _HXowning_object(node) is not tc:
            continue
        if node.tag == _HXPARA:
            text = _HXown_text(node)
            if text:
                parts.append(("text", f"{_HXmarker_of(markers, node)}{text}"))
        elif node.tag == _HXTBL:
            for caption in _HXcaptions_of(node):
                parts.extend(_HXbox_parts(caption, markers))
            parts.append(("table", node))
        else:
            parts.extend(_HXbox_parts(node, markers))
    return parts


def _HXcell_text(tc, markers=None) -> str:
    """마크다운 표용 셀 텍스트. 여러 문단은 <br> 로 잇고 파이프는 이스케이프한다.

    파이프를 escape 하지 않으면 셀 내용이 열 경계로 읽혀 표가 밀린다.

    이 경로는 **중첩 표가 없는 표에서만** 쓰인다 (`_HXneeds_html` 이 갈라낸다).
    """
    parts = [value for kind, value in _HXcell_parts(tc, markers) if kind == "text"]
    return _HXCELL_LINE_BREAK.join(parts).replace("|", "\\|")


def _HXcell_html(tc, markers=None) -> str:
    """HTML 표용 셀 내용. 중첩 표는 `<table>` 로 그대로 살린다.

    텍스트는 `html.escape(quote=False)` 로 감싼다 — 지능형 전처리기가 내는 한 줄 HTML
    표와 같은 규약이고, 번역 단위의 스켈레톤 분해기가 그 규약으로 되돌린다.
    따옴표는 이스케이프하지 않는다(속성값이 아니라 본문이다).
    """
    pieces = []
    previous_was_text = False
    for kind, value in _HXcell_parts(tc, markers):
        if kind == "text":
            if previous_was_text:
                pieces.append(_HXCELL_LINE_BREAK)
            pieces.append(_html.escape(value, quote=False))
            previous_was_text = True
        else:
            pieces.append("".join(_HXtable_html(value, markers)))
            previous_was_text = False
    return "".join(pieces)


def _HXtable_grid(tbl) -> tuple:
    """hp:tbl → `(anchors, covered, height, width)`.

    `anchors[(row, col)] = (tc, row_span, col_span)` — 셀이 **시작하는** 자리.
    `covered` 는 병합으로 덮인 자리(앵커 제외). 병합 셀은 앵커에만 내용이 있으므로,
    이 둘을 가르지 않으면 아래 행에서 열이 밀린다.
    """
    anchors: dict = {}
    occupied: set = set()
    height = 0
    width = 0

    for row_index, tr in enumerate(_HXchildren(tbl, _HXTR)):
        cursor = 0
        for tc in _HXchildren(tr, _HXTC):
            addr = tc.find(_HXCELL_ADDR)
            span = tc.find(_HXCELL_SPAN)
            col_span = _HXint_attr(span, "colSpan", 1)
            row_span = _HXint_attr(span, "rowSpan", 1)
            if addr is not None:
                row = _HXint_attr(addr, "rowAddr", row_index)
                col = _HXint_attr(addr, "colAddr", cursor)
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


def _HXneeds_html(tbl) -> bool:
    """마크다운 표로 **표현할 수 없는** 구조인가.

    셋 중 하나라도 있으면 마크다운은 정보를 잃는다:

    - **병합 셀** — `rowspan`/`colspan` 에 해당하는 문법이 없다. 지금은 빈 칸이 되어
      LLM 이 "머리글이 없는 열" 로 읽는다.
    - **중첩 표** — 마크다운 표는 중첩이 안 된다. 안쪽 표가 텍스트로 뭉개진다.
      (셀 안 **글상자에 든** 표도 여기 걸린다 — `iter` 가 깊이를 가리지 않는다.)

    잃을 것이 없는 단순한 표는 마크다운 그대로 둔다 — 토큰도 적고 사람이 읽기도 낫다.
    **전처리기(area 05)는 이 판정을 쓰지 않는다** — 그쪽은 검색 결과 조립에서 개행이
    뭉개지므로 언제나 HTML 이다. 일부러 다른 자리다.
    """
    if any(node is not tbl for node in tbl.iter(_HXTBL)):
        return True
    for tr in _HXchildren(tbl, _HXTR):
        for tc in _HXchildren(tr, _HXTC):
            span = tc.find(_HXCELL_SPAN)
            if _HXint_attr(span, "rowSpan", 1) > 1 or _HXint_attr(span, "colSpan", 1) > 1:
                return True
    return False


def _HXtable_markdown(tbl, markers=None) -> list:
    """hp:tbl → 마크다운 표 줄 목록 (병합·중첩이 없는 표 전용)."""
    anchors, _covered, height, width = _HXtable_grid(tbl)
    if not width or not height:
        return []

    lines = []
    for row in range(height):
        values = [
            _HXcell_text(anchors[(row, col)][0], markers) if (row, col) in anchors else ""
            for col in range(width)
        ]
        lines.append("| " + " | ".join(value or " " for value in values) + " |")
        if row == 0:
            # 마크다운 표는 구분선이 필수다. hwpx 는 머리행 표시가 없으므로 첫 행을
            # 머리행으로 본다 (구조를 지어내지 않는 최소 가정).
            lines.append("|" + "---|" * width)
    return lines


def _HXtable_html(tbl, markers=None) -> list:
    """hp:tbl → HTML 표 줄 목록. `rowspan`/`colspan`/중첩을 그대로 살린다.

    형태는 지능형 전처리기가 내는 것과 맞춘다(`<table><tbody><tr><td>…`) — 이 도구의
    산출물을 받는 쪽(번역 스켈레톤 분해기·FAQ 근거 대조)이 이미 그 형태를 다루므로,
    새 형식을 만드는 것이 아니라 **이미 지원하는 형식**으로 내는 것이다.

    행마다 한 줄로 끊는다. 한 줄로 몰아도 동작하지만(전처리기가 그렇게 낸다) 사람이
    읽을 수 없고, 표가 크면 진단이 불가능해진다.
    """
    anchors, covered, height, width = _HXtable_grid(tbl)
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
            cells.append(f"<td{attrs}>{_HXcell_html(tc, markers)}</td>")
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines.append("</tbody></table>")
    return lines


def _HXrender_table(tbl, markers=None) -> list:
    """hp:tbl → 표 줄 목록.

    **병합·중첩이 있으면 HTML, 아니면 마크다운.** 마크다운으로 손실 없이 표현할 수
    있는 표는 그대로 두고, 표현할 수 없는 것만 형식을 바꾼다.
    """
    return _HXtable_html(tbl, markers) if _HXneeds_html(tbl) else _HXtable_markdown(tbl, markers)


def _HXvertical_key(tbl):
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
    found = _HXchildren(tbl, _HXPOS)
    if not found:
        return 0
    pos = found[0]
    if pos.get("treatAsChar") == "1":
        return 0
    if (pos.get("vertRelTo") or "PARA") != "PARA":
        return None
    return _HXint_attr(pos, "vertOffset", 0)


def _HXin_visual_order(tables: list) -> list:
    """한 문단에 매달린 개체들을 화면에 놓이는 순서로. **판정 불가면 문서 순서 그대로.**

    개체가 하나뿐이면(대부분의 문서) 손대지 않는다 — 이 정렬은 한 문단이 둘 이상을
    물고 있을 때만 의미가 있다.
    """
    if len(tables) < 2:
        return tables
    keys = [_HXvertical_key(tbl) for tbl in tables]
    if any(key is None for key in keys):
        return tables
    # 색인을 두 번째 키로 둬서 **동점이면 문서 순서**를 지킨다(그리고 lxml 프록시끼리
    # 비교되는 일이 없다 — 색인이 유일하므로 튜플 비교가 거기서 끝난다).
    order = sorted(zip(keys, range(len(tables)), tables), key=lambda item: item[:2])
    return [tbl for _key, _index, tbl in order]


def _HXboxed_text(tbl, markers=None):
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
    anchors, _covered, _height, _width = _HXtable_grid(tbl)
    if len(anchors) != 1:
        return None

    # 중첩 표가 들어 있으면 문단으로 펼 수 없다 — 안쪽 표를 통째로 잃는다.
    # **`_HXcell_parts` 결과로 확인하지 않는 이유**(2026-08-23): 그 함수는 자동 번호
    # 카운터를 진행시킨다. 여기서 부르고 나서 표로 되돌아가면 렌더링이 같은 셀을 다시
    # 훑어 **그 셀의 번호가 두 번 세어지고, 그 뒤 문서의 번호가 전부 밀린다.**
    # 번호가 있는데 틀린 상태라 빠진 것보다 알아채기 어렵다.
    if any(node is not tbl for node in tbl.iter(_HXTBL)):
        return None

    (tc, _row_span, _col_span), = anchors.values()
    parts = _HXcell_parts(tc, markers)
    # 셀 안 여러 문단은 진짜 줄바꿈으로 잇는다 — `<br>` 은 표 한 칸을 지키려고
    # 쓰는 것이라, 표를 벗어난 이 경로에서는 글자로 보일 뿐이다.
    return "\n".join(value for kind, value in parts if kind == "text").strip()


def _HXemit_paragraph(para, blocks: list, markers, label: str = "") -> None:
    """문단 하나와 거기 매달린 개체들을 블록으로 낸다. 상자 안에서는 재귀한다.

    `label` 은 본문 흐름 **밖에서** 온 글에만 붙는다(각주·머리말 등). 글상자·캡션은
    본문과 같은 글이라 빈 문자열이다 — 라벨은 원문에 없던 글자를 더하는 것이므로,
    출처를 모르면 뜻이 달라지는 자리에만 쓴다.
    """
    # 번호는 누적 상태다 — 글자가 없는 문단에서도 진행시켜야 뒤 번호가 안 밀린다.
    marker = _HXmarker_of(markers, para)
    text = _HXown_text(para)
    if text:
        blocks.append(("paragraph", f"{label}{marker}{text}"))

    # XML 순서가 아니라 **화면 순서**로 낸다 — 같은 문단에 제목상자와 본문 표가 함께
    # 매달려 있으면 XML 에서는 표가 먼저 나오는 일이 있다(`_HXin_visual_order`).
    for obj in _HXin_visual_order(_HXowned_objects(para)):
        if obj.tag == _HXTBL:
            _HXemit_table(obj, blocks, markers, label)
            continue
        # 자기 라벨이 없는 상자(글상자·캡션)는 **바깥 라벨을 물려받는다** — 각주 안
        # 글상자가 "[각주]" 를 잃으면 그 글이 본문 문장으로 읽힌다.
        for inner in _HXparas_of(obj):
            _HXemit_paragraph(inner, blocks, markers, _HXBOX_LABELS.get(obj.tag, "") or label)


def _HXemit_table(tbl, blocks: list, markers, label: str = "") -> None:
    """표 하나를 블록으로. **캡션이 먼저다** (표제는 표 위에 놓인다)."""
    for caption in _HXcaptions_of(tbl):
        for inner in _HXparas_of(caption):
            _HXemit_paragraph(inner, blocks, markers, _HXBOX_LABELS[_HXCAPTION] or label)

    boxed = _HXboxed_text(tbl, markers)
    if boxed is not None:
        # 빈 상자는 아예 내지 않는다 — 표로 내면 글자 없는 블록이 생긴다.
        if boxed:
            blocks.append(("paragraph", f"{label}{boxed}"))
        return

    lines = _HXrender_table(tbl, markers)
    if lines:
        blocks.append(("table", "\n".join(lines)))


def hxto_markdown(hwpx_bytes: bytes, max_chars: int = 0) -> HXHwpxDocument:
    """hwpx 본문을 마크다운 문자열로 변환한다.

    Args:
        hwpx_bytes: 업로드된 hwpx 바이트.
        max_chars: 0 보다 크면 그 길이에서 자른다 (LLM 예산 보호는 호출부 책임이지만,
            파싱 산출물 자체를 무제한으로 메모리에 들고 있지 않기 위한 상한).

    Raises:
        HXHwpxParseError: ZIP/XML 손상.
    """
    blocks: list = []
    markers = _HXMarkers(_HXread_entry(hwpx_bytes, _HXHEADER_ENTRY))

    for _, xml_bytes in _HXiter_section_xml(hwpx_bytes):
        root = _HXparse_xml(xml_bytes)
        # lxml 프록시는 참조가 끊기면 회수된다. 순회 결과를 리스트로 붙들어 둔 뒤에 쓴다.
        for para in list(root.iter(_HXPARA)):
            # 상자(표 셀·글상자·각주·머리말…) 안 문단은 상위 hp:p 안에 중첩된다.
            # 그 상자를 낼 때 함께 내므로 여기서 건너뛴다 — **버리는 것이 아니다.**
            if _HXnearest_para(para) is not None:
                continue
            _HXemit_paragraph(para, blocks, markers)

    markdown = "\n\n".join(text for _kind, text in blocks)
    if max_chars > 0 and len(markdown) > max_chars:
        markdown = markdown[:max_chars].rstrip()
    return HXHwpxDocument(
        markdown=markdown,
        paragraph_count=sum(1 for kind, _ in blocks if kind == "paragraph"),
        table_count=sum(1 for kind, _ in blocks if kind == "table"),
    )


# ── tools.py ─────────────────────────────
class HXToolError(ValueError):
    def __init__(self, error_type: str):
        super().__init__(error_type)
        self.error_type = error_type


# 업로드 상한. 없으면 한 번의 호출이 서빙 메모리를 통째로 쓴다.
_HXMAX_BYTES = 50 * 1024 * 1024
_HXDEFAULT_MAX_CHARS = 200_000


def _HXmax_chars_arg(arguments: dict) -> int:
    value = arguments.get("max_chars", _HXDEFAULT_MAX_CHARS)
    try:
        max_chars = int(value)
    except (TypeError, ValueError):
        raise HXToolError("INVALID_TYPE_MAX_CHARS") from None
    if max_chars < 0:
        raise HXToolError("OUT_OF_RANGE_MAX_CHARS")
    return max_chars


def _HXread_source(arguments: dict) -> tuple:
    """`(bytes, source_kind)` 또는 실패 사유를 담은 `ToolError`.

    `content_base64` 를 `path` 보다 먼저 본다 — 명시적으로 바이트를 준 호출자는
    볼륨 공유를 전제하지 않겠다는 뜻이다.
    """
    encoded = arguments.get("content_base64")
    if encoded:
        if not isinstance(encoded, str):
            raise HXToolError("INVALID_TYPE_CONTENT_BASE64")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except Exception:  # noqa: BLE001 - 디코딩 실패 원문은 남기지 않는다
            raise HXToolError("INVALID_BASE64") from None
        if len(raw) > _HXMAX_BYTES:
            raise HXToolError("FILE_TOO_LARGE")
        return raw, "base64"

    path = arguments.get("path")
    if not path:
        raise HXToolError("MISSING_ARG_SOURCE")
    if not isinstance(path, str):
        raise HXToolError("INVALID_TYPE_PATH")

    # 크기를 먼저 본다 — 다 읽고 나서 재면 상한 밖 메모리를 이미 쓴 뒤다.
    try:
        size = os.path.getsize(path)
    except OSError:
        raise HXToolError("PATH_NOT_READABLE") from None
    if size > _HXMAX_BYTES:
        raise HXToolError("FILE_TOO_LARGE")

    try:
        with open(path, "rb") as handle:
            return handle.read(), "path"
    except OSError:
        # 경로 문자열은 응답에 넣지 않는다 (내부 경로다, 3.8절)
        raise HXToolError("PATH_NOT_READABLE") from None


def _HXhwpx_to_markdown(arguments: dict) -> dict:
    max_chars = _HXmax_chars_arg(arguments)
    raw, source_kind = _HXread_source(arguments)

    try:
        document = hxto_markdown(raw, max_chars)
    except HXHwpxParseError as exc:
        # 메시지는 `hwpx_text.py` 안에서 작성한 고정 한국어 안내문이다 (그 파일의 계약).
        return {"ok": False, "reason": str(exc), "error_type": "HWPX_PARSE_FAILED",
                "source_kind": source_kind}

    return {
        "ok": True,
        "markdown": document.markdown,
        "paragraph_count": document.paragraph_count,
        "table_count": document.table_count,
        # 상한에 걸려 잘렸는지 호출부가 알아야 한다 — 잘린 문서로 FAQ 를 만들면
        # 뒷부분 내용이 통째로 빠진 채 정상 결과처럼 나온다.
        "truncated": bool(max_chars and len(document.markdown) >= max_chars),
        "source_kind": source_kind,
    }

# ── 도구 카탈로그는 손으로 적지 않는다 (2026-08-14) ──────────────────
# 예전에는 `HXTOOL_SPECS` 에 JSON-Schema 를 손으로 적어 뒀다 — `/mcp/list` 를 우리가
# 구현하던 시절의 잔재다. 지금은 `@mcp.tool()` 이 시그니처·타입힌트·독스트링에서
# 카탈로그를 만들므로 그 목록은 **아무 데서도 읽히지 않았고**, 고쳐도 노출되는
# 스키마가 바뀌지 않는다 — 고친 사람은 바뀐 줄 안다. 그래서 지웠다.
# 도구 설명을 고칠 곳은 각 `@mcp.tool()` 함수의 독스트링이다.

_HXHANDLERS = {"hwpx_to_markdown": _HXhwpx_to_markdown}


def hxcall_tool(name: str, arguments: dict) -> dict:
    handler = _HXHANDLERS.get(name)
    if handler is None:
        raise HXToolError("UNKNOWN_TOOL")
    return handler(arguments)


def _hx_run(name: str, arguments: dict) -> str:
    """도구 본문을 부르고 JSON 문자열로 돌려준다 (네 MCP 파일 공통 모양).

    **입력 오류를 예외로 올리지 않는다** — MCP 도구가 예외로 죽으면 호출부(워크플로우
    스텝)에 오는 것은 전송 실패와 구분되지 않는다. `ok=false` + `error_type` 으로 내려야
    스텝이 "재시도 무의미" 로 다루고 사용자에게 고정 안내문을 보여줄 수 있다.

    이 파일만 2026-08-14 까지 이 감싸개 없이 도구 함수가 직접 본문을 부르고 예외 처리를
    안에 복제하고 있었다 — 그래서 `hxcall_tool` 이 죽은 코드로 남아 있었다. 네 파일이
    같은 모양이어야 한 서버에 함께 올렸을 때 읽고 대조할 수 있다.
    """
    try:
        result = hxcall_tool(name, arguments)
    except HXToolError as exc:
        # 입력이 잘못된 경우. 경로 문자열·예외 원문은 싣지 않는다 (3.8절).
        result = {"ok": False, "error_type": exc.error_type, "reason": ""}
    except Exception as exc:  # noqa: BLE001 - 최종 방어선. 원문은 응답에 싣지 않는다 (3.8절)
        _HXlog.warning(
            "도구 실행 실패",
            extra={"event": "mcp_tool_failed", "error_type": type(exc).__name__},
        )
        result = {"ok": False, "error_type": "TOOL_EXECUTION_FAILED", "reason": ""}
    return json.dumps(result, ensure_ascii=False)


# =====================================================================================
# 로컬 단독 실행 대비: 런타임이 주입하는 전역 `mcp` 가 없으면 최소 shim 을 쓴다.
# 점검 스크립트(`onprem/test/check_mcp_tools.py`)도 이 경로로 도구를 잡아 직접 부른다.
# =====================================================================================
try:
    mcp  # noqa: F821
except NameError:
    class _HXLocalMCP:
        def tool(self, *args, **kwargs):
            def _decorator(fn):
                return fn
            return _decorator

    mcp = _HXLocalMCP()
    _HXlog.info("로컬 테스트용 shim 사용", extra={"event": "mcp_shim_used"})


# =====================================================================================
# MCP Tool : hwpx_to_markdown
# =====================================================================================

@mcp.tool()
async def hwpx_to_markdown(
    content_base64: str = "",
    path: str = "",
    # GenOS 는 값이 없을 때 None 이 아니라 **빈 문자열("")** 을 주입한다. MCP 가 본문 전에
    # 타입 검증을 하므로 `int` 로만 선언하면 "" 에서 검증 에러가 난다 → str 도 받고
    # 아래에서 캐스팅한다.
    max_chars: int | str | None = None,
) -> str:
    """[언제 쓰나] hwpx 파일의 본문·표를 그대로 읽어야 할 때. 표 안 수치가 보존된다.
    → 전처리기 PDF 변환 경로는 표가 깨질 수 있으므로, hwpx 원본이 있으면 이 도구를 쓴다.

    hwpx 를 직접 파싱해 마크다운으로 낸다. 표는 `cellAddr` 좌표로 격자를 만든다.

    **표 형식은 손실 여부에 따라 갈린다:**

    - 단순한 표 → 마크다운 표 (`| 항목 | 값 |`). 토큰도 적고 읽기도 쉽다.
    - **병합(`rowSpan`/`colSpan`) 또는 중첩 표 → HTML**
      (`<table><tbody><tr><td rowspan="2">…`).

    마크다운 표에는 병합 문법이 **없다.** 병합 셀을 마크다운으로 내면 빈 칸이 되고,
    LLM 은 "머리글 없는 열" 로 읽는다 — 수치는 남는데 **그 수치가 무엇의 값인지가
    사라진다.** 중첩 표는 아예 한 덩어리 텍스트로 뭉개진다. HTML 은 둘 다 그대로 담는다.

    LLM 을 부르지 않으므로 같은 파일에 항상 같은 결과가 나온다.

    Args:
        content_base64: hwpx 파일 바이트의 base64. **볼륨 공유를 전제하지 않는 권장 경로.**
        path: 공유 볼륨 상의 hwpx 경로. 이 pod 가 같은 볼륨을 보는 배포에서만 동작한다.
            `content_base64` 가 있으면 그쪽이 우선한다.
        max_chars: 마크다운 길이 상한 (0 이면 제한 없음, 기본 200000).

    Returns:
        JSON 문자열. 성공이면
        `{"ok": true, "markdown", "paragraph_count", "table_count", "truncated", "source_kind"}`,
        실패면 `{"ok": false, "reason", "error_type", "source_kind"}`.

        **실패를 예외가 아니라 판정 결과로 낸다** — 호출부(FAQ 스텝 1)가 전처리기 산출물로
        떨어지는 폴백을 갖고 있어서, 재시도 대상인지 폴백 대상인지 구분되어야 한다.
        `truncated` 는 반드시 봐야 한다: 잘린 문서로 FAQ 를 만들면 뒷부분이 통째로 빠진 채
        정상 결과처럼 나온다.
    """
    arguments = {
        "content_base64": content_base64 or None,
        "path": path or None,
    }
    if max_chars is not None and max_chars != "":
        arguments["max_chars"] = max_chars

    return _hx_run("hwpx_to_markdown", arguments)
