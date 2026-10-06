"""hwpx · docx · pdf GenOS 전처리기(area 05) — 표를 HTML 로 살리고 조/항/호로 청킹한다.

**단독 등록 단위다.** 다른 파드에 올라가므로 `final_preprocessor.py` 를 import 하지
않는다 — hwpx 파서·위계 판정·청킹·레코드 조립은 그 파일 PART 2 에서 옮겨 적었다(같은
코드). 그쪽을 고치면 이 파일의 같은 이름 함수도 함께 고친다.

| 형식 | 읽는 법 | 패키지 |
|---|---|---|
| hwpx | zip + XML 직접 파싱 (PART 2 그대로) | lxml |
| docx | zip + XML 직접 파싱 (`parse_docx`) | lxml |
| pdf  | PyMuPDF `find_tables()` + 줄 좌표로 단·문단 복원 (`parse_pdf`) | PyMuPDF |

세 형식 모두 같은 `Block` 을 만들어 `annotate_outline`(조/항/호) → `chunk_blocks`(조
경계·표 머리행 반복·긴 칸 분할) → `to_records` 를 지난다.

kwargs (등록 화면 파라미터, 전부 선택):
    chunk_size      청크 최대 문자 수 (기본 1000)
    chunk_overlap   문단 청크 겹침 문자 수
    outline_mode    auto(기본) · statute · document · off
    file_name       레코드에 실을 파일명 (기본: 파일 경로의 이름)
    save_images     pdf 그림 · 표를 PNG 로 저장해 `media_files` 에 잇는다 (기본 True)
    extra_metadata  모든 레코드에 함께 실을 dict
"""

from __future__ import annotations

import difflib
import html as _html
import io
import json
import logging
import math
import os
import re
import sys
import time
import zipfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from lxml import etree

try:
    # GenOS 런타임이 주입하는 업로드 함수 — 벤더 전처리기와 같은 자리에서 들여온다. 로컬 · 점검
    # 환경에는 없으므로 이미지는 `{파일명}/` 폴더에만 남는다(`event=pdf_media_local`).
    from genos_utils import upload_files  # type: ignore
except ImportError:
    upload_files = None


_log = logging.getLogger(__name__)


class _FieldFormatter(logging.Formatter):
    """GenOS 런타임 로거(`common/logger.py`)와 같은 형식 + 허용 필드.

    그 형식은 `extra` 를 찍지 않으므로 허용 필드를 줄 끝에 붙인다. `_ALLOWED_LOG_FIELDS`
    는 아래에 있지만 포매터는 로그를 낼 때 읽으므로 순서는 상관없다.
    """

    def formatMessage(self, record: logging.LogRecord) -> str:
        line = super().formatMessage(record)
        pairs = [
            f"{key}={' '.join(str(getattr(record, key)).split())}"
            for key in _ALLOWED_LOG_FIELDS
            if getattr(record, key, None) is not None
        ]
        return f"{line} | {' '.join(pairs)}" if pairs else line


if not _log.handlers:
    # 이 파일은 단독 파드로 돈다. stdout 은 플랫폼 전송 채널이라 stderr 로만 낸다.
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(_FieldFormatter("%(levelname)s: %(asctime)s|[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s", "%Y-%m-%d %H:%M:%S %Z"))
    _log.addHandler(_handler)
    _log.setLevel(logging.INFO)
    # 루트로 올리지 않는다 — 런타임이 루트에 핸들러를 달면 같은 줄이 두 번 찍힌다.
    _log.propagate = False


# 3.8절 기록 허용 필드. **선언만 해 두고 강제하지 않으면 없는 것과 같다** — 그래서 모든
# 호출부가 `_emit_log` 하나를 지나게 해 새 필드를 무심코 실을 자리를 두지 않는다 (다른 여덟
# 단위의 `logging_utils` 와 같은 모양이다).
#
# **`id_ref` 가 여기 있는 것은 의도다.** 문서 안 번호 정의를 가리키는 값이지 본문 내용이
# 아니고, 없으면 "폴백을 밟았다" 는 사실은 남는데 **어느 정의에서인지가 사라져** 진단이
# 안 된다 (번역·FAQ 사본은 화이트리스트가 달라 같은 값을 `resource_id` 로 싣는다 —
# `final/preprocessor/CLAUDE.md` "그 층은 코드서빙 사본 셋에도 있다" 절).
_ALLOWED_LOG_FIELDS = (
    "event",
    "trace_id",
    "request_id",
    "resource_id",
    "status",
    "duration_ms",
    "item_count",
    "upstream_status",
    "error_code",
    "error_type",
    "id_ref",
)


def _emit_log(level: int, message: str, *, event: str, **fields: Any) -> None:
    """허용 필드만 `extra` 로 넘긴다. 나머지는 **버리고 이름만** 메시지에 남긴다.

    문서 원문·파일 경로가 로그로 새는 경로를 만들지 않는 것이 목적이다. 버린 사실을
    메시지에 남기는 이유: 조용히 버리면 "로그에 그 값이 왜 없나" 를 추적할 수 없다.
    """
    extra: dict = {"event": event}
    dropped = []
    for key, value in fields.items():
        if key == "event" or key not in _ALLOWED_LOG_FIELDS:
            dropped.append(key)
            continue
        if value is not None:
            extra[key] = value
    if dropped:
        message = f"{message} [dropped_fields={','.join(sorted(dropped))}]"
    _log.log(level, message, extra=extra, stacklevel=3)


def _log_warning(message: str, *, event: str, **fields: Any) -> None:
    _emit_log(logging.WARNING, message, event=event, **fields)


HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"

_PARA = f"{{{HP_NS}}}p"

_TEXT = f"{{{HP_NS}}}t"

_TBL = f"{{{HP_NS}}}tbl"

_TR = f"{{{HP_NS}}}tr"

_TC = f"{{{HP_NS}}}tc"

_CELL_ADDR = f"{{{HP_NS}}}cellAddr"

_CELL_SPAN = f"{{{HP_NS}}}cellSpan"

_POS = f"{{{HP_NS}}}pos"

_SECTION_ENTRY_RE = re.compile(r"^Contents/section(\d+)\.xml$")

_HEADER_ENTRY = "Contents/header.xml"

# ── 문단을 품는 상자들 ────────────────────────────────────────────────────────
#
# **글자를 담는 곳은 표 셀만이 아니다.** 글상자·도형(`hp:drawText`), 캡션, 각주·미주,
# 머리말·꼬리말, 숨은 설명, 메모가 전부 자기 안에 `hp:subList > hp:p` 를 갖는다.
# "본문 흐름이 아니다" 는 이유로 중첩 문단을 건너뛰면 그만큼이 조용히 사라진다 — 표가
# 깨지는 것과 달리 **없어진 자리가 아무 흔적도 남기지 않아** 검색에서 안 나올 때까지
# 드러나지 않는다.
#
# 전부 낸다. 어디서 온 글인지 헷갈리지 않게 라벨만 붙이되, **글상자·캡션은
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
# 목록으로 판정하면 여기 안 적힌 상자(덧말 등 hwpx 가 나중에 늘릴 수 있는 것)가 조용히
# 버려지고, 그 손실은 이름을 빠뜨렸다는 사실을 아무도 모르는 채로 남는다.
# hwpx 에서 문단을 담는 것은 예외 없이 **`hp:subList` 를 직접 자식으로 두는 원소**다
# (표 셀도 그렇다). 그 모양을 기준으로 본다.
_SUBLIST = f"{{{HP_NS}}}subList"

# 수식은 `hp:equation > hp:script` 안에 원본 문자열로 들어 있다. `hp:t` 가 아니므로
# 따로 챙기지 않으면 수식 하나가 통째로 빠져 그 문단의 뜻이 바뀐다.
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

# <hp:t> 안의 \n 은 문단 분리가 아니다 — 그대로 두면 마크다운에서 문단이 갈린다
_NEWLINE_REPLACEMENT = " "

# 셀 안 줄바꿈은 표 한 칸을 여러 줄로 만든다 — 표에서만 <br> 로 바꾼다
_CELL_LINE_BREAK = "<br>"

# 문장 경계 — **구분자를 소비하지 않는 lookbehind 만** 쓴다. `(?<=[다요])\.\s+` 처럼
# 마침표를 소비하는 패턴은 "완료하였습니다. 본 사업은" 을 "완료하였습니다 본 사업은" 으로
# 바꾼다 — 청킹이 본문 글자를 지우는 것이다.
_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s+")

# ── 조문 위계 (편/장/절/관/조/항/호/목) ────────────────────────────────────────
#
# **이 사다리는 추측이 아니라 문법이다.** 법령·행정규칙의 조문 구조는 발행처가 정한
# 표기(조 → 항 `①` → 호 `1.` → 목 `가.`)를 따르므로, 마크다운 표 문법이나 hwpx 슬롯
# 문법과 같은 성격의 결정적 규칙으로 적는다. LLM 에 물을 이유가 없고, 물으면 같은
# 문서가 적재할 때마다 다른 청크로 갈릴 수 있다(청크 경계는 결정적이어야 한다).
#
# **다만 "어느 사다리인가" 는 결정적이지 않다.** 같은 `1.` 이 법령에서는 호(조 아래
# 3단계)이고 공문서에서는 최상위 항목이다. 그래서 사다리를 문서에 무조건 적용하지 않고
# `outline_mode="auto"` 가 조문 표기를 실제로 세어 본 뒤에만 켠다 — 아래 참고.
_OUTLINE_OFF = "off"

_OUTLINE_AUTO = "auto"

_OUTLINE_STATUTE = "statute"

# 공문서 사다리. **`auto` 는 이 값을 절대 내지 않는다** — 같은 `1.` 이 법령에서는
# 호(레벨 7)이고 공문서에서는 최상위라, 자동으로 고르면 어느 쪽이든 문서 절반이 틀린다.
_OUTLINE_DOCUMENT = "document"

_OUTLINE_MODES = (_OUTLINE_AUTO, _OUTLINE_STATUTE, _OUTLINE_DOCUMENT, _OUTLINE_OFF)

# 조 = 5. 청킹은 **이 레벨 이하(편·장·절·관·조)에서만 끊는다** — 항·호·목에서 끊으면
# 조문 하나가 여러 청크로 흩어져 "제5조가 무엇을 정하는가" 에 답할 수 없게 된다.
_LEVEL_ARTICLE = 5

# 제목 줄기(`outline_path`)에는 **구조 제목까지만** 담는다. 항·호·목은 제목이 아니라
# 조문의 **내용**이라, 줄기에 넣으면 머리말이 본문 문장을 통째로 되풀이한다
# (`제5조(목적) > ① 직원은 성실히 근무하여야 한다. > 1. 근무시간을 준수할 것 > …`).
_LEVEL_PATH_MAX = _LEVEL_ARTICLE

# 목(目) 기호는 가나다 순서다. `[가-힣]\.` 로 넓게 잡으면 "완료.", "사업." 같은 본문
# 문단이 목으로 승격된다.
_MOK_LETTERS = "가나다라마바사아자차카타파하"

# 인용과 제목을 가르는 것은 **뒤에 오는 글자**다. `제5조(목적)` 은 제목이고
# `제5조에 따라` 는 본문 인용이다 — 조사(가-힣)가 붙으면 제목이 아니다.
_NOT_CITED = r"(?![가-힣])"

_STATUTE_RULES = (
    (1, re.compile(rf"^제\s*\d+\s*편{_NOT_CITED}")),
    (2, re.compile(rf"^제\s*\d+\s*장{_NOT_CITED}")),
    (2, re.compile(r"^부\s*칙(?=[\s(<[]|$)")),
    (3, re.compile(rf"^제\s*\d+\s*절{_NOT_CITED}")),
    (4, re.compile(rf"^제\s*\d+\s*관{_NOT_CITED}")),
    # 가지조문(`제5조의2`)까지 한 조로 본다. `제5조의무` 는 `의` 뒤에 숫자가 없어
    # 그룹이 안 붙고 `_NOT_CITED` 가 막는다.
    (_LEVEL_ARTICLE, re.compile(rf"^제\s*\d+\s*조(?:\s*의\s*\d+)?{_NOT_CITED}")),
    (6, re.compile(r"^[①-⑳]")),          # 항 ①~⑳
    # 호는 한두 자리로 제한한다 — `2026. 8. 13.` 같은 날짜 문단이 1호로 잡히지 않게.
    (7, re.compile(r"^\d{1,2}\.(?=\s)")),
    (8, re.compile(rf"^[{_MOK_LETTERS}]\.(?=\s)")),
)

_ARTICLE_RE = next(pattern for level, pattern in _STATUTE_RULES if level == _LEVEL_ARTICLE)

# auto 판정 문턱. 1개면 본문에 조문을 한 번 인용한 일반 문서일 수 있다 — 2개부터
# 조문 문서로 본다. **못 미치면 위계를 아예 끄고** 기존 동작 그대로 간다: 일반 문서에
# 사다리를 걸면 `1.` 목록이 전부 제목으로 승격돼 청킹이 지금보다 나빠진다.
_AUTO_ARTICLE_MIN = 2

# 공문서 사다리 (`outline_mode="document"`) — 법령 표와 **레벨이 정면으로 어긋나므로**
# 별도 표다. 법령의 `1.` 은 호(조 아래 3단계)이고 공문서의 `1.` 은 최상위다.
# 한 표에 합치면 두 문서 종류 중 하나가 반드시 틀린다.
_ROMAN_UPPER = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"

_DOCUMENT_RULES = (
    (1, re.compile(rf"^[{_ROMAN_UPPER}][.．](?=\s|$)")),
    (1, re.compile(rf"^제\s*\d+\s*장{_NOT_CITED}")),
    # 뒤가 공백일 것을 요구하면 `1.지원대상` 을 놓치고, 아무것도 요구하지 않으면
    # `1.5배` 가 걸린다. **뒤가 숫자가 아닐 것**으로 가른다.
    (2, re.compile(r"^\d{1,2}[.．](?=\s|[가-힣A-Za-z])")),
    (3, re.compile(rf"^[{_MOK_LETTERS}][.．](?=\s|[가-힣A-Za-z])")),
    (4, re.compile(r"^\d{1,2}[)）](?=\s|[가-힣A-Za-z])")),
    (5, re.compile(rf"^[{_MOK_LETTERS}][)）](?=\s|[가-힣A-Za-z])")),
    (6, re.compile(r"^[(（]\d{1,2}[)）](?=\s|[가-힣A-Za-z])")),
    (7, re.compile(r"^[①-⑳]")),
)

# **오탐의 대가가 법령 쪽과 다르다.** 법령에서 `1.` 은 레벨 7 이라 청크 경계도 제목
# 줄기도 건드리지 않아 틀려도 표기만 어긋났다. 공문서에서 `1.` 은 최상위라 오탐 하나가
# 곧 **잘못된 청크 경계 + 본문을 되풀이하는 머리말**이다. 그래서 표기가 맞아도 아래
# 넷을 통과할 때만 제목으로 올린다.
_DOC_HEADING_MAX_CHARS = 40          # 제목은 짧다. 넘으면 번호 붙은 본문 문단이다.

_DOC_SENTENCE_END = ("다.", "요.", "다)", "요)", "임.", "함.")

_DOC_MIN_HITS = 2                    # 한 번만 나오는 표기는 본문 인용일 수 있다

_DOC_FIRST_ORDINAL = 1               # 3번부터 시작하는 표기는 목록이 아니다

# 청크 경계·제목 줄기 깊이. 법령의 5(조)는 **조문 사다리 전용 값**이라 여기 쓸 수 없다.
# `annotate_outline` 이 문서형 레벨을 관측 순서대로 1..N 으로 다시 매기므로(문서마다
# 최상위가 `Ⅰ.` 인지 `1.` 인지 다르다) 이 두 값은 고정 숫자로 둘 수 있다.
_DOC_BREAK_LEVEL = 2

_DOC_PATH_MAX = 3

# 위계 이름표가 이보다 길면 표기 + 괄호 제목까지만 남긴다. 조문 제목은 본문과 한 문단에
# 붙어 오는 일이 흔하다 (`제5조(목적) 이 규칙은 …`).
_LABEL_MAX_CHARS = 40

# 청크 머리말 구분자. 쉼표로 이으면 본문 문장과 구분이 안 된다.
_OUTLINE_SEPARATOR = " > "


class PreprocessError(ValueError):
    """문서 해석/처리 실패 — ZIP·XML 손상, 미지원 확장자, 빈 문서·스캔 pdf 포함.

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다(문서 원문을
    담지 않는다). `archive/genos-project/docs/GENOS_RULES.md` §A.4 — 전처리기는 오류 dict 를 반환하지 않고
    이 예외를 던진다.
    """


@dataclass(frozen=True)
class Block:
    """문서를 이루는 한 덩어리. **청킹이 이 경계를 지킨다.**

    Attributes:
        kind: `"paragraph"` 또는 `"table"`.
        text: 렌더된 내용. 표는 **한 줄짜리 HTML 표**다 (`_render_table` 이 이유를 적는다).
        section: 몇 번째 `Contents/sectionN.xml` 에서 왔나 (0-based).
        outline_level: 위계 (법령: 1 편 … 5 조 … 8 목). **0 이면 제목이 아니라 본문**이다.
            `outline_mode="document"` 에서는 **문서에 실제로 쓰인 표기를 1..N 으로 다시
            매긴 값**이다 — 최상위가 `Ⅰ.` 인 문서와 `1.` 인 문서가 같은 레벨을 갖는다.
        outline_path: 이 블록을 감싸는 제목 줄기 (`("제2장 총칙", "제5조(목적)")`).
            제목 블록이면 자기 이름표가 마지막 원소다. 표 블록도 줄기를 물려받는다 —
            표만 검색돼 나왔을 때 어느 조의 표인지 알아야 한다.
        origin: **이 파일 밖에서 온 블록의 출처 표식.** hwpx 경로는 채우지 않는다(빈 값).
            벤더 문서(docling)를 블록으로 옮겨 이 청커를 태우는 경로가 쓴다 — 청크가
            어느 원본 항목에서 나왔는지를 잃으면 벤더의 `compose_vectors` 가 bbox·
            이미지 업로드·민감정보 마스킹을 붙일 자리를 못 찾는다. **불투명한 값**이고
            여기서는 실어 나르기만 한다(해석은 넣은 쪽이 한다).

    `parse()` 는 위계 둘을 채우지 않는다(XML 에 없는 정보다). `annotate_outline()` 이
    채운다 — 파싱과 위계 판정을 갈라 둬야 위계를 꺼도 파싱 결과가 같다.
    """

    kind: str
    text: str
    section: int
    outline_level: int = 0
    outline_path: tuple = ()
    origin: tuple = ()

    @property
    def is_table(self) -> bool:
        return self.kind == "table"


@dataclass(frozen=True)
class HwpxDocument:
    """파싱 결과.

    문단·표 개수를 함께 내는 이유는 호출부가 **파싱 품질을 로그에 남기기** 위해서다 —
    0개면 파서가 문서를 못 읽은 것이고, 그 상태로 빈 결과가 정상처럼 흘러가면 안 된다.
    """

    blocks: list = field(default_factory=list)
    section_count: int = 0

    @property
    def paragraph_count(self) -> int:
        return sum(1 for block in self.blocks if block.kind == "paragraph")

    @property
    def table_count(self) -> int:
        return sum(1 for block in self.blocks if block.is_table)

    def to_markdown(self, max_chars: int = 0) -> str:
        """블록 사이 빈 줄로 이은 문자열 (디버깅/미리보기용).

        `max_chars` 가 0 보다 크면 그 길이에서 자른다. **잘렸다는 사실은 여기서 알려주지
        않는다** — 호출부가 길이를 비교해 판단한다.
        """
        markdown = "\n\n".join(block.text for block in self.blocks)
        if max_chars > 0 and len(markdown) > max_chars:
            markdown = markdown[:max_chars].rstrip()
        return markdown


def _open(hwpx_bytes: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(hwpx_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise PreprocessError("hwpx 파일이 아니거나 손상된 파일입니다.") from exc


def _section_order(entry_name: str):
    """본문 섹션이면 섹션 번호, 아니면 None.

    문자열 정렬을 쓰지 않는 이유: `section10` 이 `section2` 앞에 온다. 문단 순서가
    밀리면 청크 순서와 원본 대조가 어긋난다.
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
        raise PreprocessError("hwpx 본문 XML 을 해석하지 못했습니다.") from exc


def _nearest_para(node):
    """이 노드를 직접 담고 있는 문단. 표 안(hp:tc→hp:subList→hp:p)까지 따라간다."""
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _PARA:
            return parent
        parent = parent.getparent()
    return None


def _inline_text(node) -> str:
    """`hp:t` 한 개가 가진 글자 전부 — **자식 원소의 `tail` 까지.**

    `hp:t` 는 혼합 내용이다. 탭·강제 줄바꿈·묶음 빈칸 같은 조판 문자가 자식 원소로
    들어가고, **그 뒤에 오는 글자는 자식의 `tail`** 에 담긴다. `node.text` 만 읽으면
    조판 문자가 한 번이라도 나올 때 **그 뒤 글자를 전부 잃는다** — 남은 앞부분이
    멀쩡한 문장처럼 보여서 무엇이 사라졌는지 드러나지 않는 종류의 손실이다.

    조판 문자 자체도 글자로 되살린다(탭·줄바꿈은 뒤에서 공백으로 정규화된다) — 없애면
    `1.지원대상` 처럼 이름표와 내용이 붙는다.
    """
    pieces = [_INLINE_CHARS.get(node.tag, ""), node.text or ""]
    for child in node:
        pieces.append(_inline_text(child))
        pieces.append(child.tail or "")
    return "".join(pieces)


def _own_text(para) -> str:
    """이 문단이 **직접** 가진 텍스트.

    hwpx 표는 hp:p → hp:run → hp:tbl → … → hp:p 로 중첩된다. `para.iter()` 를 그대로
    쓰면 표 전체가 한 문단으로 붙어 표가 통째로 깨진다.

    글자의 출처는 `hp:t` **와 `hp:equation`** 둘이다 — 수식은 `hp:script` 에 원본
    문자열로 들어 있어 `hp:t` 만 보면 수식 하나가 통째로 빠진다.
    """
    parts = []
    for node in para.iter():
        # 태그를 먼저 거른다 — 조상 추적(`_nearest_para`)을 모든 노드에 걸면 큰 표
        # 하나가 문단 하나의 글자를 뽑는 데 문서 전체를 훑는 비용이 된다.
        if node.tag == _TEXT:
            if _nearest_para(node) is para:
                parts.append(_inline_text(node))
        elif node.tag == _EQUATION and _nearest_para(node) is para:
            parts.extend(script.text or "" for script in node.iter(_SCRIPT))
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


# 자동 번호·글머리표 — **문서에 보이는데 본문 XML 에는 없는 글자**
#
# 한/글의 개요 번호(`1.`, `가.`, `1)`)와 글머리표(`-`, `●`)는 문단 텍스트가 아니라
# **문단 모양(`hh:paraPr > hh:heading`)이 가리키는 번호 매기기 정의**에서 나온다.
# 그래서 `hp:t` 만 읽으면 그 표시가 통째로 사라진다 — 화면에서
#
#     - 사용자가 문서를 업로드한다
#     - 시스템이 문서보안을 해제한다
#
# 이던 것이 적재된 뒤에는 앞의 `-` 가 없는 두 문장이 되고, **목록이라는 사실과 항목의
# 층위가 함께 없어진다.** 조문 위계 판정(`_match_statute`)도 그 표시를 보고 하는 일이라
# 번호가 없으면 항·호가 본문 문단으로 떨어진다.
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
# 텍스트는 `_own_text` 가 따로 뽑으므로 문장은 멀쩡히 남고 번호만 없어져, 표가 깨지는
# 것과 달리 **없어진 자리에 흔적이 남지 않는다.**
#
# 그래서 **id 로 먼저 찾고, 없으면 문서 순서 0-based 인덱스로 본다.** 순서가 이렇게 된
# 이유는 `type="NUMBER"`(문단 번호)가 id 를 그대로 참조하는 경우를 앞의 매치가 지키기
# 때문이다. 한/글이 `idRef` 를 언제나 0-based 로 쓴다면 인덱스만으로도 되지만, 그것을
# 확정할 실물(번호 정의가 2개 이상이면서 둘 다 참조되는 문서)이 아직 없다.
#
# **어긋남의 대가는 크지 않다.** 자동 번호가 만드는 표기는 `_STATUTE_RULES` 에서 항·호·
# 목(레벨 6·7·8)에만 걸리고, 그 레벨은 `outline_break_level`(기본 5)에서 청크를 끊지도
# `_LEVEL_PATH_MAX`(5) 로 제목 줄기에 들지도 않는다. 청킹까지 흔드는 레벨 1~5(`제5조`)는
# 본문 글자에서 나온다. 그래서 **번호가 없는 것이 어긋난 번호보다 나쁘다** — 적재 경로는
# 아무도 눈으로 보지 않으므로, 유실은 그 문장을 물어봤을 때까지 드러나지 않는다.
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
# 이미지 글머리표(`@char` 없음)가 그렇다. 비워 두면 목록이라는 사실이 통째로 사라지고,
# `-` 는 `_STATUTE_RULES` 의 어느 규칙에도 걸리지 않아 위계를 흔들지 않는다.
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
            except PreprocessError:
                # 머리 정의를 못 읽는 것으로 본문 적재를 막지 않는다 — 번호만 빠진다.
                _log_warning(
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
        _log_warning(
            "hwpx marker definition resolved by fallback", event=event, id_ref=ref
        )

    def _resolve(self, table: dict, ref: str, event: str):
        """`@idRef` → 정의. **id 로 먼저, 없으면 문서 순서 0-based 인덱스로.**

        Returns:
            `(키, 정의)`. 어느 쪽으로도 못 찾으면 `(ref, None)`.

        근거는 이 절 머리말에 적었다 — 실물 한/글은 `idRef="0"` 을 쓰는데 `@id` 는 1 부터
        시작한다. **키를 함께 돌려주는 이유**는 누적 카운터를 그 키로 들기 때문이다:
        원본 ref 로 들면 `idRef="0"` 과 `idRef="1"` 이 같은 정의를 가리키는데도 번호가
        따로 세어져 한 목록이 `1. 1. 2. 2.` 로 나온다.
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
            # 줄바꿈·들여쓰기와 함께 저장된 문서 때문이다(그대로 쓰면 번호 앞에 개행이
            # 붙어 문단이 두 줄로 보인다).
            template = defined[depth][0].strip()
        else:
            # **번호는 그려지는데**(heading 이 OUTLINE/NUMBER 다) 그 단계 서식을 모른다.
            # 여기서 빈 문자열을 돌려주던 것이 "번호가 통째로 사라지는데 로그에도 남지
            # 않는" 상태였다 — 정의를 찾았고 폴백도 밟지 않으므로 아무 흔적이 없다.
            # 숫자로 낸다: 층위가 사라지는 것보다 표기가 어긋나는 편이 낫다.
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

    폴백이 필요한 이유: 그 키가 없으면 표시 문자열을 못 찾아 빈 문자열이 되고, 그러면
    **개요 번호가 붙은 문단 전부에서 번호만 조용히 사라진다** — 정의는 찾았고 `_resolve`
    폴백도 밟지 않으므로 로그에도 흔적이 남지 않는다.

    **축을 뒤집어 보지는 않는다.** 표시 문자열의 `^N` 토큰이 정의의 레벨 키를 그대로
    참조하므로(`_expand_head`), 0-based 정의를 가정해 키를 옮기면 `^N` 해석과 어긋나
    번호가 나오는데 다른 단계의 서식·카운터를 쓴다. 그 모양의 실물을 아직 못 봤다.
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
    """이 노드를 담고 있는 **가장 가까운 상자**(표 셀 포함). 중첩을 가르는 기준이다.

    셀(`hp:tc`)만 보면 셀 안 글상자·캡션·각주의 문단이 "이 셀 것이 아니다" 로 떨어져
    **어디에서도 안 나온다** — 셀 렌더링은 자기 것이 아니라고 건너뛰고, 본문 렌더링은
    중첩 문단이라고 건너뛴다.
    """
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
    글상자). "한 겹" 의 기준은 **이 문단과 같은 상자에 들어 있는가** 다 — 문단이 본문에
    있으면 개체도 본문에 있어야 하고, 문단이 글상자 안이면 개체도 그 글상자 것이라야
    한다. `None` 고정으로 두면 글상자 안 표가 통째로 빠진다(실제로 밟았다).
    """
    box = _owning_box(para)
    return [
        node
        for node in para.iter()
        if (node.tag == _TBL or _is_box(node))
        and _nearest_para(node) is para
        and _owning_object(node) is box
    ]


def _captions_of(obj) -> list:
    """이 개체에 **직접** 달린 캡션(표제)."""
    return [node for node in obj.iter(_CAPTION) if _owning_object(node) is obj]


def _box_parts(box, markers=None, inherited: str = "") -> list:
    """상자 안 내용을 `("text", str)`/`("table", elem)` 으로 **문서 순서대로**.

    셀 안에 들어 있는 상자를 셀 글자로 펴는 자리다. 상자 안 표는 표로 남긴다 —
    글자로 펴면 그 수치가 무엇의 값인지 사라진다(이 전처리기를 만든 이유 그대로다).
    """
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

    `tc.iter(hp:p)` 를 그대로 쓰면 **중첩 표 안의 문단까지 딸려온다.** 소유 개체를 따져
    자기 것만 고른다. 셀 안 글상자·캡션·각주는 그 상자를 펴서 셀 글자에 잇는다.

    **`_owning_box` 가 아니라 `_owning_object` 로 보는 이유**: 표(`hp:tbl`)는 상자가
    아니라서, 중첩 표의 셀에서 위로 올라가면 표를 지나쳐 **바깥 셀이 소유자로 잡힌다.**
    그러면 그 셀이 중첩 표를 `("table", …)` 로 한 번 내고, 이어서 그 표의 셀들을
    상자로 또 펴서 **같은 글자가 두 번 실린다**(`구분 | 세부<table>…</table>소분류<br>값`).
    표가 깨지는 것이 아니라 값이 중복되는 것이라 눈으로는 정상처럼 보인다.
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


def _cell_html(tc, markers=None) -> str:
    """HTML 표용 셀 내용. 중첩 표는 `<table>` 로 그대로 살린다."""
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
    `covered` 는 병합으로 덮인 자리(앵커 제외).
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


def _table_html(tbl, markers=None) -> list:
    """hp:tbl → HTML 표 줄 목록. `rowspan`/`colspan`/중첩을 그대로 살린다.

    형태는 지능형 전처리기가 내는 것과 맞춘다(`<table><tbody><tr><th>…`) — 새 형식을
    만드는 것이 아니라 이미 지원되는 형식으로 내는 것이다.

    **첫 행은 `<th>` 다.** 마크다운 표에서 그 일을 하던 구분선(`|---|`)이 없어졌으므로
    (→ `_render_table`) 머리행 표시를 태그가 맡는다. 조각마다 머리행을 반복하는 것이
    이 분할의 요점인데, 표시가 없으면 그 반복이 데이터 행처럼 읽힌다.
    """
    anchors, covered, height, width = _table_grid(tbl)
    if not width or not height:
        return []

    lines = ["<table><tbody>"]
    for row in range(height):
        # hwpx 는 머리행 표시가 없다 — 첫 행을 머리행으로 본다(구조를 지어내지 않는
        # 최소 가정. 마크다운 표에서 구분선을 첫 행 뒤에 넣던 것과 같은 판정이다).
        tag = "th" if row == 0 else "td"
        cells = []
        for col in range(width):
            if (row, col) in covered:
                continue  # 병합으로 덮인 자리 — 칸을 내면 열이 하나 늘어난다
            anchor = anchors.get((row, col))
            if anchor is None:
                cells.append(f"<{tag}></{tag}>")  # 빈 칸도 자리를 지켜야 한다
                continue
            tc, row_span, col_span = anchor
            attrs = ""
            if row_span > 1:
                attrs += f' rowspan="{row_span}"'
            if col_span > 1:
                attrs += f' colspan="{col_span}"'
            cells.append(f"<{tag}{attrs}>{_cell_html(tc, markers)}</{tag}>")
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines.append("</tbody></table>")
    return lines


def _render_table(tbl, markers=None) -> list:
    """hp:tbl → 표 줄 목록. **언제나 HTML 이다.**

    ## 왜 마크다운을 안 쓰나

    병합·중첩이 없는 표까지 HTML 로 내는 이유는 **검색 결과가 LLM 에게 갈 때 개행이
    공백으로 뭉개지기 때문이다.**

        | 순번 | … | 수용<br>여부 | |---|---|---| | 3 | 차기 변제금 …

    마크다운 표는 **행 경계가 개행뿐**이라 이 한 줄에서 표가 아니게 된다 — 구분선이 본문
    줄에 붙고 7열이 뒤섞인다. 수치는 남지만 그 수치가 무엇의 값인지 사라지는 것이고,
    그건 애초에 이 전처리기를 만든 이유(요구사항 §5 "표 깨짐")와 같은 실패다.

    HTML 표는 **행·칸 경계가 태그**라 개행이 없어도 구조가 그대로다. 새 형식도 아니다 —
    지능형 전처리기가 이미 한 줄 HTML 표를 내고 있어 검색·프롬프트 경로가 그 형태를
    이미 받는다. 대가는 토큰 증가(이 문서에서 약 10%)이고, 표가 아니게 되는 것보다
    낫다는 판단이다.
    """
    return _table_html(tbl, markers)


def _vertical_key(tbl):
    """같은 문단에 매달린 개체의 **세로 위치**. 비교할 수 없으면 `None`.

    hwpx 의 표·상자는 문단에 매달리고(anchor), **XML 순서가 곧 화면 순서는 아니다.**
    실물에서 드러났다: 제목상자(1칸 표, `treatAsChar="1"`)와 본문 표
    (`treatAsChar="0"`, `vertOffset="5940"`)가 **같은 문단**에 매달려 있는데 XML 에는
    본문 표가 먼저 있어, 문서 제목이 표 **뒤로** 밀렸다. 그러면 표 조각 어디에도
    제목이 없고, 마지막 청크에서 제목·날짜·서명이 한 덩어리가 된다.

    - `hp:pos` 가 없으면 흐름 그대로 → 0
    - `treatAsChar="1"`(글자처럼 취급)은 문단 자리에 그대로 온다 → 0
    - 그 외에는 `vertOffset`. 단 **기준이 문단(`vertRelTo="PARA"`)일 때만** 쓴다 —
      페이지·단 기준 오프셋은 문단 기준 값과 크기를 비교할 수 없다(0 으로 뭉개면
      순서를 지어내는 셈이라 `None` 을 돌려 정렬 자체를 포기한다).
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

    hwpx 는 제목상자·박스형 강조를 1칸 표로 만드는 일이 흔한데, 그대로 표로 내면 본문
    행이 0개인 퇴화된 표가 된다:

        | 『…』 사업 기술협상서 |
        |---|

    글자를 잃지는 않지만(머리행에 남는다) 표가 아닌 것이 표로 검색되고, 구분선이
    노이즈로 임베딩되며, 조문 위계 판정도 지나쳐 간다. 문단으로 내면 셋 다 해소된다.

    Returns:
        문단 텍스트. 칸이 하나가 아니거나 **중첩 표가 들어 있으면 `None`** — 후자는
        문단으로 펴면 안쪽 표를 통째로 잃는다.
    """
    anchors, _covered, _height, _width = _table_grid(tbl)
    if len(anchors) != 1:
        return None

    # 중첩 표가 들어 있으면 문단으로 펼 수 없다 — 안쪽 표를 통째로 잃는다.
    # **`_cell_parts` 결과로 확인하지 않는 이유**: 그 함수는 자동 번호
    # 카운터를 진행시킨다. 여기서 부르고 나서 표로 되돌아가면 렌더링이 같은 셀을 다시
    # 훑어 **그 셀의 번호가 두 번 세어지고, 그 뒤 문서의 번호가 전부 밀린다.**
    # 번호가 있는데 틀린 상태라 빠진 것보다 알아채기 어렵다.
    if any(node is not tbl for node in tbl.iter(_TBL)):
        return None

    (tc, _row_span, _col_span), = anchors.values()
    parts = _cell_parts(tc, markers)
    # 셀 안 여러 문단은 진짜 줄바꿈으로 잇는다 — `<br>` 은 표 한 칸을 지키려고
    # 쓰는 것이라, 표를 벗어난 이 경로에서는 글자로 보일 뿐이다.
    return "\n".join(value for kind, value in parts if kind == "text").strip()


def parse(hwpx_bytes: bytes) -> HwpxDocument:
    """hwpx 본문을 블록 목록으로 판다.

    Args:
        hwpx_bytes: hwpx 파일 바이트.

    Returns:
        Document — 문단과 표가 **문서 순서대로** 담긴다.

    Raises:
        PreprocessError: ZIP/XML 손상.
    """
    blocks: list = []
    section_count = 0
    markers = _Markers(_read_entry(hwpx_bytes, _HEADER_ENTRY))

    for section_index, (_name, xml_bytes) in enumerate(_iter_section_xml(hwpx_bytes)):
        section_count += 1
        root = _parse_xml(xml_bytes)

        # lxml 프록시는 참조가 끊기면 회수된다. 순회 결과를 리스트로 붙들어 둔 뒤에 쓴다.
        for para in list(root.iter(_PARA)):
            # 상자(표 셀·글상자·각주·머리말…) 안 문단은 상위 hp:p 안에 중첩된다.
            # 그 상자를 낼 때 함께 내므로 여기서 건너뛴다 — **버리는 것이 아니다.**
            if _nearest_para(para) is not None:
                continue
            _emit_paragraph(para, section_index, blocks, markers)

    return HwpxDocument(blocks=blocks, section_count=section_count)


def _emit_paragraph(para, section_index: int, blocks: list, markers, label: str = "") -> None:
    """문단 하나와 거기 매달린 개체들을 블록으로 낸다. 상자 안에서는 재귀한다.

    `label` 은 본문 흐름 **밖에서** 온 글에만 붙는다(각주·머리말 등). 글상자·캡션은
    본문과 같은 글이라 빈 문자열이다 — 라벨은 원문에 없던 글자를 더하는 것이므로,
    출처를 모르면 뜻이 달라지는 자리에만 쓴다.
    """
    # 번호는 누적 상태다 — 글자가 없는 문단에서도 진행시켜야 뒤 번호가 안 밀린다.
    marker = _marker_of(markers, para)
    text = _own_text(para)
    if text:
        blocks.append(
            Block(kind="paragraph", text=f"{label}{marker}{text}", section=section_index)
        )

    # XML 순서가 아니라 **화면 순서**로 낸다 — 같은 문단에 제목상자와 본문 표가 함께
    # 매달려 있으면 XML 에서는 표가 먼저 나오는 일이 있다(`_in_visual_order`).
    for obj in _in_visual_order(_owned_objects(para)):
        if obj.tag == _TBL:
            _emit_table(obj, section_index, blocks, markers, label)
            continue
        # 자기 라벨이 없는 상자(글상자·캡션)는 **바깥 라벨을 물려받는다** — 각주 안
        # 글상자가 "[각주]" 를 잃으면 그 글이 본문 문장으로 읽힌다.
        for inner in _paras_of(obj):
            _emit_paragraph(
                inner, section_index, blocks, markers, _BOX_LABELS.get(obj.tag, "") or label
            )


def _emit_table(tbl, section_index: int, blocks: list, markers, label: str = "") -> None:
    """표 하나를 블록으로. **캡션이 먼저다.**

    캡션을 표 앞에 두면 `_table_title_of` 가 그것을 표 제목으로 집어 조각마다 앞에
    """
    for caption in _captions_of(tbl):
        for inner in _paras_of(caption):
            _emit_paragraph(
                inner, section_index, blocks, markers, _BOX_LABELS[_CAPTION] or label
            )

    boxed = _boxed_text(tbl, markers)
    if boxed is not None:
        # 빈 상자는 아예 내지 않는다 — 표로 내면 글자 없는 청크가 생긴다.
        if boxed:
            blocks.append(
                Block(kind="paragraph", text=f"{label}{boxed}", section=section_index)
            )
        return

    lines = _render_table(tbl, markers)
    if lines:
        blocks.append(Block(kind="table", text="\n".join(lines), section=section_index))


def _match_statute(text: str) -> tuple:
    """문단 첫머리에서 조문 표기를 찾는다. → `(레벨, 이름표)`. 못 찾으면 `(0, "")`.

    **첫머리에서만** 본다. 본문 가운데의 `… 제5조에 따라 …` 는 인용이지 제목이 아니고,
    문단 전체를 훑으면 그 인용이 새 조를 여는 것처럼 보여 청크가 엉뚱하게 끊긴다.
    """
    stripped = text.strip()
    if not stripped:
        return 0, ""
    for level, pattern in _STATUTE_RULES:
        match = pattern.match(stripped)
        if match:
            return level, _outline_label(stripped, match)
    return 0, ""


def _outline_label(stripped: str, match) -> str:
    """제목 줄기에 실을 짧은 이름표.

    조문 제목은 본문과 한 문단에 붙어 오는 일이 흔하다(`제5조(목적) 이 규칙은 …`).
    그대로 쓰면 청크 머리말이 본문을 통째로 되풀이한다. 그래서 순서가 이렇다:

    1. **괄호 제목이 있으면 길이와 무관하게 거기까지** — `제5조(목적)`. 조문 제목의
       정식 표기라, 짧다는 이유로 본문까지 이름표에 넣으면 조마다 이름표 모양이 달라진다.
    2. 괄호가 없고 문단이 짧으면 그대로 (`제2장 총칙` — 제목 줄 하나가 곧 이름표다).
    3. 둘 다 아니면 표기만 (`제5조`).
    """
    marker = match.group(0).strip()
    rest = stripped[match.end():].lstrip()
    if rest.startswith("("):
        close = rest.find(")")
        if close != -1:
            return f"{marker}{rest[:close + 1]}"
    if len(stripped) <= _LABEL_MAX_CHARS:
        return stripped
    return marker or stripped[:_LABEL_MAX_CHARS].rstrip()


def _doc_candidate(stripped: str) -> bool:
    """공문서 제목 후보인가 — 표기를 보기 **전에** 문단 모양으로 먼저 거른다."""
    if not stripped or len(stripped) > _DOC_HEADING_MAX_CHARS:
        return False
    return not stripped.endswith(_DOC_SENTENCE_END)


def _doc_ordinal(marker: str) -> int:
    """표기에서 순서값 하나. 못 읽으면 0.

    **표기 문자열만 넘길 것.** 문단 전체를 넘기면 `가. 2025년 계획` 에서 `20` 을
    집어 "1번부터 시작하는가" 판정이 뒤집힌다.
    """
    digits = re.search(r"\d{1,2}", marker)
    if digits:
        return int(digits.group())
    for char in marker:
        if char in _MOK_LETTERS:
            return _MOK_LETTERS.index(char) + 1
        if char in _ROMAN_UPPER:
            return _ROMAN_UPPER.index(char) + 1
        if "①" <= char <= "⑳":
            return ord(char) - 0x2460 + 1
    return 0


def _document_levels(blocks: list) -> frozenset:
    """이 문서가 **실제로 쓰는** 공문서 레벨. 사다리를 문서마다 확정한다.

    문단 하나만 봐서는 `_DOC_MIN_HITS`·`_DOC_FIRST_ORDINAL` 을 판정할 수 없어
    `annotate_outline` 이 이 함수로 한 번 먼저 훑는다.
    """
    seen: dict = {}
    for block in blocks:
        if block.kind != "paragraph":
            continue
        stripped = block.text.strip()
        if not _doc_candidate(stripped):
            continue
        for level, pattern in _DOCUMENT_RULES:
            match = pattern.match(stripped)
            if match:
                seen.setdefault(level, []).append(_doc_ordinal(match.group(0)))
                break
    return frozenset(
        level for level, ordinals in seen.items()
        if len(ordinals) >= _DOC_MIN_HITS and ordinals[0] == _DOC_FIRST_ORDINAL
    )


def _match_document(text: str, levels: frozenset) -> tuple:
    """공문서 표기 판정. `levels` 에 없는 레벨은 제목으로 올리지 않는다."""
    stripped = text.strip()
    if not _doc_candidate(stripped):
        return 0, ""
    for level, pattern in _DOCUMENT_RULES:
        match = pattern.match(stripped)
        if match:
            if level not in levels:
                return 0, ""
            return level, _outline_label(stripped, match)
    return 0, ""


def _detect_outline_mode(blocks: list) -> str:
    """`auto` 판정 — 조문 표기를 실제로 세어 본다.

    **일반 문서에 사다리를 걸면 지금보다 나빠진다.** `1.`·`가.` 로 시작하는 평범한
    목록이 전부 제목으로 승격돼 청크가 잘게 부서지기 때문이다. 그래서 조 표기가
    `_AUTO_ARTICLE_MIN` 개 이상일 때만 켠다 — `제N조` 는 목록 기호로 쓰이지 않으므로
    이 판정은 오탐이 사실상 없다.
    """
    hits = 0
    for block in blocks:
        if block.kind != "paragraph":
            continue
        if _ARTICLE_RE.match(block.text.strip()):
            hits += 1
            if hits >= _AUTO_ARTICLE_MIN:
                return _OUTLINE_STATUTE
    return _OUTLINE_OFF


def annotate_outline(blocks: list, mode: str = _OUTLINE_AUTO) -> list:
    """블록에 조문 위계를 매긴다. 원본은 건드리지 않고 새 목록을 돌려준다.

    Args:
        blocks: `parse()` 산출물.
        mode: `"auto"`(기본 — 조문 문서로 보일 때만 켠다) / `"statute"`(무조건 켠다) /
            `"document"`(공문서 사다리 — **`auto` 는 절대 이걸 고르지 않는다**) /
            `"off"`(끈다). 알 수 없는 값은 경고 후 `"auto"` 로 떨어진다 — 등록 화면
            오타가 재적재를 막으면 안 된다.

    Returns:
        `outline_level`/`outline_path` 가 채워진 블록 목록. `mode` 가 꺼지면 입력과
        같은 내용(위계 필드는 기본값)이다.
    """
    if mode not in _OUTLINE_MODES:
        _log_warning(
            "invalid preprocessor parameter, using default",
            event="hwpx_preprocess_param_invalid",
            error_code="05-00020003",
        )
        mode = _OUTLINE_AUTO
    if mode == _OUTLINE_AUTO:
        mode = _detect_outline_mode(blocks)
    if mode == _OUTLINE_OFF:
        return list(blocks)

    # 문서형은 사다리를 문서에서 확정하고, **관측 순서대로 1..N 으로 다시 매긴다.**
    # 최상위가 `Ⅰ.` 인 문서와 `1.` 인 문서의 레벨이 같아야 청크 경계·머리말 깊이를
    # 고정 숫자로 둘 수 있다. 쓸 만한 사다리가 없으면 위계를 안 매긴다(끈 것과 같다).
    doc_rank: dict = {}
    if mode == _OUTLINE_DOCUMENT:
        levels = _document_levels(blocks)
        if not levels:
            return list(blocks)
        doc_rank = {level: rank for rank, level in enumerate(sorted(levels), start=1)}
    path_max = _DOC_PATH_MAX if doc_rank else _LEVEL_PATH_MAX

    trail: dict = {}
    annotated: list = []
    for block in blocks:
        if block.kind != "paragraph":
            level, label = 0, ""
        elif doc_rank:
            level, label = _match_document(block.text, frozenset(doc_rank))
            level = doc_rank.get(level, 0)
        else:
            level, label = _match_statute(block.text)
        if level:
            # 같은 레벨이거나 더 깊은 줄기는 여기서 닫힌다. 안 닫으면 제3조의 항이
            # 제5조 청크의 머리말에 남는다.
            trail = {depth: name for depth, name in trail.items() if depth < level}
            if level <= path_max:
                trail[level] = label
        annotated.append(
            replace(
                block,
                outline_level=level,
                outline_path=tuple(trail[depth] for depth in sorted(trail)),
            )
        )
    return annotated


_DEFAULT_MAX_CHARS = 1000

_DEFAULT_OVERLAP_CHARS = 100

_DEFAULT_MIN_CHARS = 40

# 표 바로 앞 문단을 그 표의 제목으로 볼 수 있는 최대 길이. 넘으면 제목이 아니라 본문
# 문단이라고 본다 — 본문을 표 조각마다 반복하면 임베딩이 본문 쪽으로 끌려간다.
_TABLE_TITLE_MAX_CHARS = 60

# 상한을 넘는 행을 쪼갤 때, 이 길이 이하의 셀은 **조각마다 통째로 반복**한다.
# 순번·담당·수용여부처럼 짧은 칸이 여기 해당하고, 그게 있어야 조각이 혼자 해석된다.
_ROW_ANCHOR_MAX_CHARS = 80

# `<tr>` 한 줄에서 칸을 뜯어낼 때. 속성을 **그대로 보존**해야 하므로 따로 잡는다.
_HTML_CELL_RE = re.compile(r"<(td|th)\b([^>]*)>(.*?)</\1>", re.IGNORECASE | re.DOTALL)

# 병합 선언. 이게 걸린 행은 조각마다 되풀이하면 없던 격자를 지어낸다.
_SPAN_ATTR_RE = re.compile(r"\b(?:row|col)span\s*=", re.IGNORECASE)

# 행을 쪼갠 조각에서 "이 칸의 내용은 다른 조각에 있다" 는 표시. 빈칸과 구분돼야 한다.
_ELLIPSIS = "…"


@dataclass(frozen=True)
class Chunk:
    """VDB 에 실릴 한 조각.

    Attributes:
        text: 본문.
        section: 원본 섹션 번호.
        kind: `"paragraph"` / `"table"` — 표 조각인지 알아야 검색 결과 표시가 달라진다.
        table_part: 표를 나눴을 때 `(몇 번째, 총 몇 개)`. 안 나눴으면 `None`.
            **몇 번째는 0-based 다** — 레코드의 `i_table_part` 와 같은 값이고, 사람이
            읽는 본문 머리말(`(표 1/16)`)만 `_table_prefix_for` 가 +1 해서 낸다.
        table_title: 표 바로 앞 문단(= 표 제목). 표 청크에만, 없으면 빈 값.
        outline_path: 이 청크가 속한 조문 줄기. 위계를 껐거나 조문 문서가 아니면 빈 값.
        origin: 이 청크가 덮는 블록들의 `Block.origin` 을 **순서대로 이어 붙인 것**
            (중복 제거). hwpx 경로는 언제나 빈 값이다. 이 값이 없으면 벤더 경로가
            청크를 원본 항목에 되짚지 못한다 — `Block.origin` 설명 참고.
    """

    text: str
    section: int
    kind: str
    table_part: tuple | None = None
    table_title: str = ""
    outline_path: tuple = ()
    origin: tuple = ()


@dataclass
class ChunkOptions:
    """청킹 설정.

    `max_chars` 기본값 1000 은 임베딩 모델 컨텍스트에 맞춰 호출부가 조정한다.
    `length` 는 문자 수 기본값 — 폐쇄망에 토크나이저 파일이 없을 수 있어서다. 토큰
    기준이 필요하면 콜러블을 주입한다.
    """

    max_chars: int = _DEFAULT_MAX_CHARS
    overlap_chars: int = _DEFAULT_OVERLAP_CHARS
    # 이보다 짧은 청크는 앞 청크에 붙인다. 한두 단어짜리 청크는 검색 노이즈만 된다.
    min_chars: int = _DEFAULT_MIN_CHARS
    length: object = len
    # 이 레벨 이하의 제목에서 청크를 끊는다. 기본은 조(5) — 조가 검색 단위다.
    # 0 이면 위계로 끊지 않는다(길이 기준만 쓴다).
    outline_break_level: int = _LEVEL_ARTICLE
    # 청크 본문 앞에 `제2장 총칙 > 제5조(목적)` 머리말을 붙일지. 붙이는 이유는 조각이
    # **혼자서도 해석 가능**해야 하기 때문이다 — 표 조각에 머리행을 반복하는 것과 같은
    # 이유이고, 임베딩되는 문자열 자체에 들어가야 검색에 걸린다.
    outline_prefix: bool = True

    def __post_init__(self) -> None:
        # 문자 분할 예외 경로(`_split_long_text`)는 매 반복마다 `max_chars - overlap_chars`
        # 만큼 전진한다. `overlap_chars >= max_chars` 면 그 값이 0 이하가 되어 같은
        # 조각을 무한히 반복한다 — GenOS 등록 화면에서 파라미터를 잘못 입력해도
        # 재적재가 멈추지 않게 여기서 막는다(`archive/genos-project/docs/GENOS_RULES.md` §F 의 "파라미터
        # 최소·최대/범위 밖" 테스트 요건).
        if self.max_chars < 1:
            self.max_chars = _DEFAULT_MAX_CHARS
        if self.overlap_chars < 0 or self.overlap_chars >= self.max_chars:
            self.overlap_chars = max(0, self.max_chars // 4)
        if self.min_chars < 0:
            self.min_chars = 0
        if self.outline_break_level < 0:
            self.outline_break_level = _LEVEL_ARTICLE


def _length(options: ChunkOptions, text: str) -> int:
    return options.length(text)


def _cell_segments(cell: str, options: ChunkOptions) -> list:
    """셀 내용을 이어붙일 수 있는 조각으로. → `[(앞에 붙일 이음쇠, 글자)]`.

    1차 경계는 셀 안 줄바꿈(`<br>`)이다. 그 한 줄이 혼자 상한을 넘으면 문장 경계로 한 번
    더 나눈다 — 그때 이음쇠는 **공백**이다. `<br>` 로 다시 이으면 원문에 없던 줄바꿈을
    만들어 내는 셈이고, 그 줄바꿈은 되돌릴 수 없다.
    """
    segments: list = []
    for index, line in enumerate(cell.split(_CELL_LINE_BREAK)):
        separator = _CELL_LINE_BREAK if index else ""
        if _length(options, line) <= options.max_chars:
            segments.append((separator, line))
            continue
        for order, sentence in enumerate(s for s in _SENTENCE_END.split(line) if s):
            segments.append((separator if order == 0 else " ", sentence))
    return segments


def _row_cells(row: str) -> list:
    """`<tr>` 한 줄 → `[(태그, 속성, 내용)]`. 모양이 예상과 다르면 빈 목록.

    되돌려 렌더한 것이 원래 줄과 **글자까지 같을 때만** 쪼갠다. 정규식으로 훑는 것이라
    모르는 모양(속성에 `>` 가 들어간 경우 등)에서 조용히 글자를 잃을 수 있는데, 그 손실은
    검색 결과에 아무 흔적도 남기지 않는다.
    """
    cells = _HTML_CELL_RE.findall(row)
    if len(cells) < 2 or _render_row(cells, [inner for _t, _a, inner in cells], ()) != row:
        return []
    return cells


def _render_row(cells: list, values: list, long_columns) -> str:
    """셀 목록 + 값 목록 → `<tr>` 한 줄.

    `long_columns` 에 든 칸이 비어 있으면 생략 표시를 넣는다 — 이 조각에 안 실렸다는
    뜻이지 값이 없다는 뜻이 아니다. 앵커로 반복되는 **진짜 빈칸**과 구분돼야 한다.
    """
    pieces = []
    for index, ((tag, attrs, _inner), value) in enumerate(zip(cells, values)):
        if not value and index in long_columns:
            value = _ELLIPSIS
        pieces.append(f"<{tag}{attrs}>{value}</{tag}>")
    return "<tr>" + "".join(pieces) + "</tr>"


def _split_wide_row(row: str, prefix: list, suffix: list, options: ChunkOptions) -> list:
    """행 **하나**가 상한을 넘을 때 셀 안에서 나눈다. → `<tr>` 줄 목록.

    행 단위로만 쪼개던 때는 여기서 멈췄고, 그 조각은 상한을 넘긴 채 임베딩으로 갔다
    (실물에서 1,929자). 임베딩 컨텍스트가 그보다 짧으면 **뒤쪽이 조용히 잘린다** —
    레코드에는 글자가 그대로 남아 있어서 검색이 왜 실패했는지 아무 데도 안 드러난다.

    나누는 규칙:
    - 짧은 셀(`_ROW_ANCHOR_MAX_CHARS` 이하)은 **조각마다 통째로 반복**한다. 순번·담당·
      수용여부가 그것이고, 그게 있어야 조각만 봐도 몇 번 항목인지 안다(머리행을 반복하는
      것과 같은 이유다).
    - 긴 셀은 `<br>`(그래도 길면 문장) 경계로 나눠 채운다. **열 수는 그대로**라 조각도
      여전히 올바른 표다.
    - 글자는 하나도 버리지 않고 겹치지도 않는다 — 표 안에서 겹치면 같은 수치가 두 번
      나와 합계가 틀린다.

    **손대지 않는 행 셋**(그대로 돌려준다):
    - 중첩 표가 든 행 — 안쪽 표가 조각 사이에서 갈린다.
    - `rowspan`/`colspan` 이 걸린 행 — 조각마다 되풀이하면 **없던 격자를 지어낸다.**
      병합은 "이 칸이 몇 행·몇 열을 덮는다" 는 선언이라 복제되면 뜻이 달라진다.
    - 쪼갤 데가 없는 행 (칸이 하나뿐이거나 긴 칸이 없는 행).
    """
    if "<table" in row.lower():
        return [row]
    cells = _row_cells(row)
    if not cells or any(_SPAN_ATTR_RE.search(attrs) for _tag, attrs, _inner in cells):
        return [row]

    inners = [inner for _tag, _attrs, inner in cells]
    anchors = [
        inner if _length(options, inner) <= _ROW_ANCHOR_MAX_CHARS else "" for inner in inners
    ]
    long_columns = [index for index, value in enumerate(anchors) if not value]
    if not long_columns:
        return [row]

    def fits(values: list) -> bool:
        candidate = prefix + [_render_row(cells, values, long_columns)] + suffix
        return _length(options, "\n".join(candidate)) <= options.max_chars

    rows: list = []
    current = list(anchors)
    filled = False
    for column in long_columns:
        for separator, segment in _cell_segments(inners[column], options):
            candidate = list(current)
            candidate[column] = (
                f"{candidate[column]}{separator}{segment}" if candidate[column] else segment
            )
            if filled and not fits(candidate):
                rows.append(_render_row(cells, current, long_columns))
                current = list(anchors)
                # 새 조각의 첫 글자다 — 앞의 이음쇠는 버린다(칸이 이음쇠로 시작하면
                # 그 조각만 읽었을 때 앞이 잘린 것처럼 보인다).
                current[column] = segment
            else:
                current = candidate
            filled = True
    rows.append(_render_row(cells, current, long_columns))
    return rows


def _split_html_table(text: str, options: ChunkOptions) -> list:
    """HTML 표를 `<tr>` 단위로 나눈다. 첫 행을 머리행으로 보고 반복한다.

    행 하나가 그것만으로 상한을 넘으면 `_split_wide_row` 가 셀 안에서 한 번 더 나눈다.
    """
    lines = text.splitlines()
    rows = [line for line in lines if line.startswith("<tr>")]
    if len(rows) <= 1:
        return [text]

    header_row = rows[0]
    open_tag, close_tag = "<table><tbody>", "</tbody></table>"

    widened: list = []
    for row in rows[1:]:
        if _length(options, "\n".join([open_tag, header_row, row, close_tag])) > options.max_chars:
            widened.extend(_split_wide_row(row, [open_tag, header_row], [close_tag], options))
        else:
            widened.append(row)

    parts: list = []
    current: list = []
    for row in widened:
        candidate = "\n".join([open_tag, header_row] + current + [row, close_tag])
        if current and _length(options, candidate) > options.max_chars:
            parts.append("\n".join([open_tag, header_row] + current + [close_tag]))
            current = [row]
        else:
            current.append(row)
    if current:
        parts.append("\n".join([open_tag, header_row] + current + [close_tag]))
    return parts or [text]


def _table_prefix_reserve(
    block: Block, options: ChunkOptions, title: str, *, part: bool
) -> int:
    """조각에 붙을 머리말이 차지할 자리. **쪼개기 전에 미리 빼 둔다.**

    조문 머리말은 일부러 길이 계산 **뒤**에 붙인다(조가 깊을수록 본문이 밀려 청크
    크기가 들쭉날쭉해지므로). 표는 사정이 다르다 — 제목이 표 전체에 하나뿐이라 예약이
    균일하고, 예약하지 않으면 **모든 조각이 상한을 조금씩 넘는다.** 상한을 넘기지
    않으려고 행을 쪼갠 직후에 머리말로 다시 넘기면 앞의 노력이 무의미해진다.

    `(표 99/99)` 로 재는 것은 조각 수를 아직 모르기 때문이다 — 실제보다 넉넉하게
    잡을지언정 모자라게 잡지 않는다.
    """
    pieces = []
    if title and not block.outline_path:
        pieces.append(title)
    if part:
        pieces.append("(표 99/99)")
    sample = " ".join(pieces)
    sample = f"{sample}\n" if sample else ""
    if options.outline_prefix and block.outline_path:
        sample = f"{_OUTLINE_SEPARATOR.join(block.outline_path)}\n\n{sample}"
    return _length(options, sample) if sample else 0


def _extend_origin(base: tuple, extra: tuple) -> tuple:
    """출처를 순서대로 잇되 이미 있는 것은 다시 넣지 않는다.

    **동일성(`is`)으로 본다.** 이 값은 이 파일 밖에서 온 불투명한 물건이라 해시
    가능한지도, `==` 가 값 비교인지도 알 수 없다 — 벤더 모델이 무거운 `__eq__` 를
    가지면 청킹이 조용히 느려진다. 길이가 한 청크 몫이라 선형 검색으로 충분하다.
    """
    if not extra:
        return base
    merged = list(base)
    for item in extra:
        if not any(item is seen for seen in merged):
            merged.append(item)
    return tuple(merged)


def _table_chunks(block: Block, options: ChunkOptions, title: str = "") -> list:
    if _length(options, block.text) + _table_prefix_reserve(
        block, options, title, part=False
    ) <= options.max_chars:
        return [
            Chunk(
                text=block.text,
                section=block.section,
                kind="table",
                table_title=title,
                outline_path=block.outline_path,
                origin=block.origin,
            )
        ]

    budget = options.max_chars - _table_prefix_reserve(block, options, title, part=True)
    if budget >= options.max_chars // 2:
        # 머리말이 상한의 절반을 먹을 만큼 길면 예약을 포기한다 — 그 지경이면 본문이
        # 밀려 조각이 표 몇 줄짜리가 되고, 그게 상한을 지키는 것보다 나쁘다.
        options = replace(options, max_chars=budget)

    parts = _split_html_table(block.text, options)

    total = len(parts)
    return [
        Chunk(
            text=part,
            section=block.section,
            kind="table",
            table_part=(index, total),
            table_title=title,
            outline_path=block.outline_path,
            # 표를 쪼개도 조각마다 **같은 출처**다 — 원본 항목은 그 표 하나이고, 쪼갠
            # 것은 우리 사정이다. 조각마다 나눠 주면 bbox·이미지가 한 조각에만 붙는다.
            origin=block.origin,
        )
        for index, part in enumerate(parts)
    ]


def _table_title_of(block: Block, options: ChunkOptions) -> str:
    """이 문단을 뒤따르는 표의 제목으로 볼 수 있나. 아니면 빈 문자열.

    제목은 **한 줄짜리 짧은 문단**만 인정한다. 본문 문단을 제목으로 삼으면 표 조각마다
    본문이 통째로 반복돼 임베딩이 표가 아니라 그 본문 쪽으로 끌려간다.
    """
    text = block.text.strip()
    if not text or "\n" in text or _length(options, text) > _TABLE_TITLE_MAX_CHARS:
        return ""
    return text


def _split_long_text(text: str, options: ChunkOptions) -> list:
    """한 문단이 상한을 넘을 때만 쓰는 예외 경로. 문장 → 문자 순으로 내려간다."""
    sentences = [s for s in _SENTENCE_END.split(text) if s.strip()]
    pieces: list = []
    current = ""
    for sentence in sentences or [text]:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and _length(options, candidate) > options.max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)

    # 문장으로도 안 잘리는 경우(한 문장이 통째로 길다) — 마지막 수단으로 문자 분할
    out: list = []
    for piece in pieces:
        while _length(options, piece) > options.max_chars:
            out.append(piece[: options.max_chars])
            piece = piece[options.max_chars - options.overlap_chars:]
        if piece:
            out.append(piece)
    return out


def _overlap_tail(text: str, options: ChunkOptions) -> str:
    """다음 청크 앞에 붙일 꼬리. 문장 경계를 넘지 않게 자른다."""
    if options.overlap_chars <= 0:
        return ""
    tail = text[-options.overlap_chars:]
    match = _SENTENCE_END.search(tail)
    return tail[match.end():] if match else tail


def chunk_blocks(blocks: list, options: ChunkOptions | None = None) -> list:
    """블록 목록 → 청크 목록.

    표는 블록 경계를 넘지 않고, 문단은 상한까지 이어 붙인다. 표를 만나면 쌓아 둔 문단을
    **먼저 끊는다** — 문단과 표를 한 청크에 섞으면 표가 문단 꼬리에 붙어 검색 결과가
    읽기 어려워진다. 구역(section)이 바뀔 때도 끊는다 — 청크가 두 구역에 걸치면
    `i_section` 이 둘 중 하나만 가리켜 출처가 틀린다.

    블록에 조문 위계가 매겨져 있으면(`annotate_outline`) **조 이상의 제목에서도 끊는다.**
    한 조가 여러 청크에 흩어지면 "제5조가 무엇을 정하는가" 에 답할 수 없고, 두 조가 한
    청크에 붙으면 검색이 엉뚱한 조를 근거로 든다. 항·호·목에서는 끊지 않는다 — 그 단위로
    쪼개면 조문 하나가 문장 조각들로 부서진다. 조가 상한을 넘을 때만 기존 길이 기준이
    안에서 작동하고, 그때 경계는 자연히 항(`①`) 문단 머리에 떨어진다.
    """
    options = options or ChunkOptions()
    chunks: list = []
    buffer = ""
    buffer_section = 0
    buffer_path: tuple = ()
    buffer_origin: tuple = ()
    # 바로 앞 문단 = 다음 표의 제목 후보. 표를 지나면 비운다(표 뒤의 표는 앞 표를
    # 제목으로 삼으면 안 된다).
    table_title = ""

    def flush():
        nonlocal buffer, buffer_origin
        if buffer.strip():
            chunks.append(
                Chunk(
                    text=buffer.strip(),
                    section=buffer_section,
                    kind="paragraph",
                    outline_path=buffer_path,
                    origin=buffer_origin,
                )
            )
        buffer = ""
        buffer_origin = ()

    def start(block: Block):
        """버퍼가 비었을 때 그 청크의 출처(섹션·조문 줄기)를 첫 블록에서 가져온다."""
        nonlocal buffer_section, buffer_path, buffer_origin
        buffer_section = block.section
        buffer_path = block.outline_path
        buffer_origin = ()

    def note(block: Block):
        """이 블록의 글자가 지금 버퍼에 들어갔다 — 출처를 잇는다.

        `_split_long_text` 가 한 블록을 여러 조각으로 내면 여기가 여러 번 불리므로
        **중복을 없앤다.** 값이 해시 가능하다고 가정하지 않는다(벤더 경로가 무엇을
        넣을지는 이 파일의 소관이 아니다) — 동일성으로만 본다.
        """
        nonlocal buffer_origin
        buffer_origin = _extend_origin(buffer_origin, block.origin)

    for block in blocks:
        if block.is_table:
            flush()
            chunks.extend(_table_chunks(block, options, title=table_title))
            table_title = ""
            continue

        table_title = _table_title_of(block, options)

        if buffer and block.section != buffer_section:
            # 구역(`Contents/sectionN.xml`)이 바뀌면 끊는다. 안 끊으면 뒤 구역의 첫
            # 문단이 앞 구역 청크 꼬리에 붙고, 그 청크의 `i_section` 은 앞 구역을
            # 가리켜 **출처가 틀린다.**
            flush()

        if (
            options.outline_break_level
            and block.outline_level
            and block.outline_level <= options.outline_break_level
        ):
            # 조 이상의 제목 = 하드 경계. 겹침도 넘기지 않는다 — 앞 조의 꼬리가 다음 조
            # 청크 머리에 붙으면 그 청크가 어느 조의 내용인지 흐려진다.
            flush()

        pieces = (
            [block.text]
            if _length(options, block.text) <= options.max_chars
            else _split_long_text(block.text, options)
        )
        for piece in pieces:
            candidate = f"{buffer}\n\n{piece}" if buffer else piece
            if buffer and _length(options, candidate) > options.max_chars:
                flush()
                tail = _overlap_tail(chunks[-1].text, options) if chunks else ""
                buffer = f"{tail}\n\n{piece}".strip() if tail else piece
                start(block)
                note(block)
            else:
                if not buffer:
                    # 매 청크 시작마다 섹션을 다시 잡는다 — 첫 청크에서만 잡으면
                    # 두 번째 청크부터 `i_section` 이 앞 청크 값에 얼어붙어, 섹션이
                    # 여럿인 문서에서 출처가 틀리게 실린다.
                    start(block)
                buffer = candidate
                note(block)

    flush()
    return _apply_outline_prefix(
        _apply_table_prefix(_drop_heading_only_chunks(_merge_tiny(chunks, options))),
        options,
    )


def _merge_tiny(chunks: list, options: ChunkOptions) -> list:
    """너무 짧은 **문단** 청크를 앞에 붙인다.

    표 청크는 건드리지 않는다 — 짧아도 그 자체가 의미 단위이고, 문단에 붙이면 표가
    문단 꼬리에 섞여 버린다. **조문 줄기나 구역이 다르면 붙이지 않는다** — 붙이면 방금
    끊은 경계가 되돌려져 두 조(또는 두 구역)가 한 청크에 섞인다. 짧은 쪽이 앞 청크에
    흡수되는 모양이라, 경계를 세워 둔 코드만 읽어서는 왜 안 끊기는지 알 수 없다.
    """
    merged: list = []
    for chunk in chunks:
        if (
            chunk.kind == "paragraph"
            and merged
            and merged[-1].kind == "paragraph"
            and merged[-1].outline_path == chunk.outline_path
            # 구역·조 경계에서 끊어 놓고 여기서 도로 붙이면 경계가 없던 것이 된다.
            and merged[-1].section == chunk.section
            and _length(options, chunk.text) < options.min_chars
        ):
            previous = merged.pop()
            merged.append(
                Chunk(
                    text=f"{previous.text}\n\n{chunk.text}",
                    section=previous.section,
                    kind="paragraph",
                    outline_path=previous.outline_path,
                    origin=_extend_origin(previous.origin, chunk.origin),
                )
            )
        else:
            merged.append(chunk)
    return merged


def _drop_heading_only_chunks(chunks: list) -> list:
    """제목 하나뿐인 청크를 버린다 — **뒤 청크가 그 제목을 머리말로 이고 갈 때만.**

    `제2장 총칙` 처럼 제목만 있는 문단은 조 경계에서 끊기고 나면 홀로 남는데, 그 여섯
    글자로는 검색에서 아무것도 답하지 못하면서 자리만 차지한다. 그렇다고 무조건 버리면
    본문이 사라질 수 있으므로, **본문이 자기 이름표와 글자까지 같고**(= 제목 외에 아무
    내용이 없고) **다음 청크의 줄기가 그 제목을 포함**할 때만 버린다. 그 두 조건이면
    글자가 다음 청크의 머리말로 그대로 살아남으므로 무손실이다.

    **출처는 다음 청크로 넘긴다.** 글자는 머리말로 살아남는데 출처만 버리면, 벤더
    경로에서 그 제목 항목의 bbox·이미지가 어느 청크에도 안 붙는다 — 화면에는 제목이
    보이는데 그 자리를 짚어 주는 값이 없는 상태가 되고, 오류로는 드러나지 않는다.
    """
    kept: list = []
    carried: tuple = ()
    for index, chunk in enumerate(chunks):
        following = chunks[index + 1] if index + 1 < len(chunks) else None
        if (
            chunk.kind == "paragraph"
            and chunk.outline_path
            and chunk.text == chunk.outline_path[-1]
            and following is not None
            and following.outline_path[: len(chunk.outline_path)] == chunk.outline_path
        ):
            carried = _extend_origin(carried, chunk.origin)
            continue
        if carried:
            chunk = replace(chunk, origin=_extend_origin(carried, chunk.origin))
            carried = ()
        kept.append(chunk)
    return kept


def _table_prefix_for(chunk: Chunk) -> str:
    """표 청크 앞에 붙일 머리말. 붙일 게 없으면 빈 문자열.

    **왜 메타데이터가 아니라 본문에 넣나.** `i_table_part`·`table_title` 은 레코드에도
    싣지만, 검색 결과가 LLM 에게 갈 때의 봉투(`<doc file_name=… security_level=…>`)에는
    그 필드가 실리지 않는다 — 실물 결과에서 확인했다. 그래서 3번째 조각이 "3번 항목부터
    시작하는 표" 로 보이고, 앞의 1~2번이 어디 있는지도, 이게 표의 일부라는 것도 알 수
    없다. **조각이 혼자서도 해석 가능해야** 하므로 조문 머리말과 같은 이유로 본문에 넣는다.

    제목은 조문 줄기가 있을 때는 붙이지 않는다 — 그쪽은 `_apply_outline_prefix` 가
    이미 `제2장 총칙 > 제5조(목적)` 을 붙이고 있어 머리말이 두 겹이 된다.
    """
    if chunk.kind != "table":
        return ""
    pieces = []
    if chunk.table_title and not chunk.outline_path:
        pieces.append(chunk.table_title)
    if chunk.table_part is not None:
        # 저장값은 0-based(`i_table_part`), 사람이 읽는 자리에서만 1-based 로 낸다.
        index, total = chunk.table_part
        pieces.append(f"(표 {index + 1}/{total})")
    return " ".join(pieces)


def _apply_table_prefix(chunks: list) -> list:
    """표 청크 본문 앞에 `제목 (표 2/10)` 한 줄을 붙인다.

    조문 머리말과 마찬가지로 **길이 계산이 끝난 뒤에** 붙는다 — 머리말까지 상한 안에
    넣으려 하면 제목 길이에 따라 조각 크기가 들쭉날쭉해진다.
    """
    prefixed: list = []
    for chunk in chunks:
        prefix = _table_prefix_for(chunk)
        prefixed.append(replace(chunk, text=f"{prefix}\n{chunk.text}") if prefix else chunk)
    return prefixed


def _outline_prefix_for(chunk: Chunk) -> str:
    """청크 앞에 붙일 위계 머리말. 붙일 게 없으면 빈 문자열.

    **이미 본문이 이고 있는 제목은 빼고 붙인다.** 조 제목 문단으로 시작하는 청크에
    `제5조(목적) > 제5조(목적) …` 처럼 겹쳐 붙으면 임베딩에 같은 문구가 두 번 실린다.
    """
    path = chunk.outline_path
    if path and chunk.text.startswith(path[-1]):
        path = path[:-1]
    return _OUTLINE_SEPARATOR.join(path)


def _apply_outline_prefix(chunks: list, options: ChunkOptions) -> list:
    """청크 본문 앞에 조문 줄기를 붙인다 (`outline_path` 자체는 그대로 남긴다).

    길이 계산이 끝난 뒤에 붙는다 — 머리말까지 `max_chars` 안에 넣으려 하면 조가 깊을수록
    본문이 밀려나고, 같은 문서에서 조마다 청크 크기가 들쭉날쭉해진다. 머리말은 조문
    위계가 있을 때만 붙으므로 일반 문서는 영향을 받지 않는다.
    """
    if not options.outline_prefix:
        return chunks

    prefixed: list = []
    for chunk in chunks:
        prefix = _outline_prefix_for(chunk)
        prefixed.append(replace(chunk, text=f"{prefix}\n\n{chunk.text}") if prefix else chunk)
    return prefixed


# 페이지 숫자의 출처. 렌더링된 페이지가 아니라 hwpx 구역이라는 뜻이고, 이 문자열이
# 레코드에 실려야 나중에 "페이지 수가 실물과 다르다" 를 추적할 수 있다.
_PAGE_BASIS_SECTION = "section"


def _counts(text: str) -> dict:
    """`n_char`/`n_word`/`n_line`. 지능형 전처리기의 `GenOSVectorMeta` 와 같은 이름·같은
    세는 법 — 검색 쪽이 그 이름으로 읽으므로 어긋나면 안 된다."""
    return {
        "n_char": len(text),
        "n_word": len(text.split()),
        "n_line": len(text.splitlines()) or 1,
    }


# 레코드 필드의 **타입 계약**. Weaviate 는 프로퍼티 타입을 처음 본 값으로 굳히므로,
# 같은 키가 문서마다 다른 타입으로 나가면 **나중 문서가 통째로 안 들어간다.** 그 실패는
# 적재 단계에서 `not a string, but float64` 처럼 뜨는데 — Go 가 JSON 숫자를 전부
# `float64` 로 읽는다 — **어느 레코드의 어느 키인지가 메시지에 없다.** 그래서 여기서
# 먼저 잡고 키 이름을 말한다.
#
# 페이지 관련 다섯은 **구역으로 채운다** — `None` 을 허용하지 않는다.
# 비워 두면 GenOS 적재 결과 화면이 청크를 묶지 못해 **아무것도 안 뜨는데 오류도 없다**
# (`_page_fields` 주석). 출처는 `page_basis` 가 말한다.
_RECORD_TYPES = {
    "text": (str,),
    "file_name": (str,),
    "file_path": (str,),
    "reg_date": (str,),
    "source_kind": (str,),
    "table_title": (str,),
    "outline_title": (str,),
    "n_char": (int,),
    "n_word": (int,),
    "n_line": (int,),
    "i_chunk_on_doc": (int,),
    "n_chunk_of_doc": (int,),
    "i_section": (int,),
    "n_section": (int,),
    "i_table_part": (int,),
    "n_table_part": (int,),
    "i_page": (int,),
    "e_page": (int,),
    "n_page": (int,),
    "i_chunk_on_page": (int,),
    "n_chunk_of_page": (int,),
    "chunk_bboxes": (str,),
    "media_files": (str,),
    "page_basis": (str,),
    "outline_path": (list,),
}


def _check_record_types(records: list) -> None:
    """우리가 만든 필드의 타입이 계약과 같은지. 어긋나면 **키 이름을 말하고 세운다.**

    §F 규약대로 오류 객체를 청크 목록에 섞지 않고 예외를 던진다 — 여기까지 오면
    `to_records` 의 불변식이 깨진 것이라 재적재로 풀리지 않는다.

    **`extra_metadata` 는 세우지 않는다.** 그쪽은 등록 화면 입력이고, 이 모듈의 규약이
    "파라미터 입력 실수가 전체 재적재를 막지 않는다" 이기 때문이다. 대신 **키 이름과
    타입 이름을 로그로 낸다** — 값은 남기지 않는다(§3.8). 적재가 그 값 때문에 거절되면
    컨테이너 로그에 어느 키인지가 남아 있어야 손을 쓸 수 있다.
    """
    reported: set = set()
    for index, record in enumerate(records):
        for key, value in record.items():
            allowed = _RECORD_TYPES.get(key)
            if allowed is None:
                # `extra_metadata` 에서 온 키. **문자열과 `None` 만 조용히 통과시킨다** —
                # 숫자·불리언은 컬렉션이 그 프로퍼티를 `text` 로 잡고 있으면 거절되고
                # (`not a string, but float64`), 그 메시지에는 키 이름이 없다.
                if value is not None and not isinstance(value, str):
                    if key not in reported:
                        reported.add(key)
                        _log_warning(
                            "extra_metadata value is not a string - the vector DB will "
                            "reject it if the property is text (key=%s type=%s)"
                            % (key, type(value).__name__),
                            event="preprocess_extra_metadata_type",
                        )
                continue
            # `bool` 은 `int` 의 하위형이라 그냥 두면 int 자리를 통과한다.
            if isinstance(value, bool) and bool not in allowed:
                raise PreprocessError(
                    "레코드 필드 타입이 계약과 다릅니다(내부 오류): "
                    "%s=bool (레코드 %d)" % (key, index)
                )
            if not isinstance(value, allowed):
                raise PreprocessError(
                    "레코드 필드 타입이 계약과 다릅니다(내부 오류): "
                    "%s=%s (레코드 %d)" % (key, type(value).__name__, index)
                )


def _page_fields(chunks: list, section_count: int) -> list:
    """청크별 페이지 필드. **구역(section)을 페이지 자리에 넣는다.**

    Args:
        chunks: `chunk_blocks` 산출물.
        section_count: 문서의 구역 수. 0 이면 청크에서 센다.

    Returns:
        청크와 같은 길이의 dict 목록 —
        `i_page`·`e_page`·`n_page`·`i_chunk_on_page`·`n_chunk_of_page`·`page_basis`.

    hwpx 는 흐름 문서라 렌더링 전에는 페이지가 없다. 그래도 이 필드를 채우는 이유는
    **적재 결과 화면이 이 값으로 청크를 묶어 그리기 때문**이다 — 비워 두면 hwpx 로 넣은
    문서만 화면에 안 뜬다(오류가 아니라 빈 목록이라 아무 데도 안 드러난다).

    - **1-based** 다. 벤더 pdf 경로의 `page_no` 와 같은 기준이라 화면이 "1페이지" 로
      그린다. 0 을 섞으면 같은 컬렉션에서 두 모양이 된다.
    - `i_chunk_on_page` 는 **0-based** 다 — 벤더 `chunk_index_on_page` 가 0 부터 센다.
    - `page_basis` 가 "이 숫자는 렌더링된 페이지가 아니라 구역이다" 를 말한다. 이 값이
      없으면 나중에 누가 페이지 수로 분량을 재고 실물과 안 맞아 원인을 못 찾는다.
    """
    sections = [max(0, int(getattr(chunk, "section", 0) or 0)) for chunk in chunks]
    per_section: dict = {}
    for section in sections:
        per_section[section] = per_section.get(section, 0) + 1

    # 구역 수는 파서가 준 값이 정본이다. 청크에 더 큰 번호가 있으면(부분 처리 등) 그쪽을
    # 쓴다 — `i_page > n_page` 인 레코드는 화면에서 페이지 밖을 가리킨다.
    total_pages = max([section_count] + [value + 1 for value in sections] + [1])

    seen: dict = {}
    fields = []
    for section in sections:
        order = seen.get(section, 0)
        seen[section] = order + 1
        fields.append({
            "i_page": section + 1,
            "e_page": section + 1,
            "n_page": total_pages,
            "i_chunk_on_page": order,
            "n_chunk_of_page": per_section[section],
            "page_basis": _PAGE_BASIS_SECTION,
        })
    return fields


def to_records(
    chunks: list,
    *,
    file_name: str = "",
    file_path: str = "",
    section_count: int = 0,
    reg_date: str = "",
    extra: dict | None = None,
) -> list:
    """청크 목록 → VDB 레코드(dict) 목록.

    Args:
        chunks: `chunk_blocks` 산출물.
        file_name: 원본 파일명 (검색 결과 출처 표시에 쓰인다).
        file_path: 원본 경로.
        section_count: 문서의 섹션 수 (`n_section`).
        reg_date: 적재 일시. 비우면 지금 시각(로컬 타임존)을 쓴다.
        extra: 모든 레코드에 함께 실을 값 (`security_level` 등 배포별 필드).

    Returns:
        `text` 키를 포함한 dict 목록. `i_chunk_on_doc`/`n_chunk_of_doc` 는 여기서
        매긴다 — 호출부가 매기면 문서를 나눠 처리할 때 번호가 겹친다.
    """
    stamp = reg_date or datetime.now(timezone.utc).astimezone().isoformat()
    total = len(chunks)
    records = []
    pages = _page_fields(chunks, section_count)

    for index, chunk in enumerate(chunks):
        record = {
            "text": chunk.text,
            **_counts(chunk.text),
            # 페이지 자리에는 **구역**이 들어간다 — 값의 출처는 `page_basis` 가 말한다.
            # 비워 두면 GenOS 적재 결과 화면에 이 문서가 뜨지 않는다(위 docstring).
            **pages[index],
            "i_chunk_on_doc": index,
            "n_chunk_of_doc": total,
            "reg_date": stamp,
            # 벤더가 좌표·미디어를 못 찾았을 때 내는 값과 **같은 것**을 쓴다
            # (`GenOSVectorMetaBuilder`: 빈 bbox 는 `"[]"`, 미디어 없음은 `""`).
            # `None` 으로 두면 화면이 그 필드를 읽다 멈춘다.
            "chunk_bboxes": "[]",
            "media_files": "",
            # ── 이 경로에만 있는 것 ──
            "file_name": file_name,
            "file_path": file_path,
            "i_section": chunk.section,
            "n_section": section_count,
            # 검색 결과를 표로 보여줄지 문단으로 보여줄지 UI 가 고를 근거
            "source_kind": chunk.kind,
        }
        if chunk.table_part is not None:
            part_index, part_total = chunk.table_part
            # 표가 쪼개졌다는 사실을 숨기지 않는다 — 조각만 보고 "표가 이게 전부" 라고
            # 읽으면 안 된다.
            #
            # **이름이 `i_` 로 시작하는 이유가 값의 규약이다.** `i_page`/`i_section` 과
            # 같은 0-based 이고, 본문 머리말(`(표 1/16)`)만 사람이 읽는 값이라 +1 한다.
            # `i_` 접두어 없이 `table_part` 로 두면 UI 가 `표 {값}/{총}` 을 그대로 찍어
            # **첫 조각이 "표 0/16" 이 되고 16/16 은 영영 안 나온다** — 본문과 레코드가
            # 다른 번호를 말하는데 어느 쪽도 틀린 티가 안 난다.
            record["i_table_part"] = part_index
            record["n_table_part"] = part_total
        if chunk.table_title:
            # 본문 머리말과 **따로** 싣는다(조문 줄기와 같은 규약) — 머리말은 임베딩되라고
            # 있는 것이고, 이 값은 검색 결과에 "무슨 표인가" 를 표시하는 데 쓴다.
            record["table_title"] = chunk.table_title
        if chunk.outline_path:
            # 본문 머리말과 **따로** 싣는다. 머리말은 임베딩되라고 있는 것이고, 이 둘은
            # 검색 결과에 출처를 표시하거나 조 단위로 거르는 데 쓴다.
            record["outline_path"] = list(chunk.outline_path)
            record["outline_title"] = chunk.outline_path[-1]
        if extra:
            record.update(extra)
        records.append(record)

    return records


def _int_kwarg(value: Any, default: int, name: str) -> int:
    """kwargs 로 들어온 값을 int 로. 실패해도 예외를 내지 않고 기본값으로 떨어진다.

    등록 화면 파라미터 입력 실수(빈 문자열, 문자열 숫자, 범위 밖)가 재적재 전체를
    막으면 안 된다 — `ChunkOptions.__post_init__` 이 마지막 안전망으로 한 번 더
    범위를 강제한다.
    """
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        _log_warning(
            "invalid preprocessor parameter, using default",
            event="hwpx_preprocess_param_invalid",
            error_code="05-00020003",
        )
        return default


def _bool_kwarg(value: Any, default: bool, name: str) -> bool:
    """kwargs 로 들어온 값을 bool 로. `"false"` · `"0"` · `"off"` 문자열도 받는다 —
    등록 화면 파라미터는 문자열로 오는 일이 흔하다. 못 읽으면 기본값으로 떨어진다."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    _log_warning(
        "invalid preprocessor parameter, using default",
        event="hwpx_preprocess_param_invalid",
        error_code="05-00020003",
    )
    return default


# ===========================================================================
# 공통 — HTML 표 조립
# ===========================================================================
#
# 세 형식 모두 표를 hwpx `_table_html` 과 **같은 모양**으로 낸다: 여는 태그 · `<tr>` 한
# 줄씩 · 닫는 태그를 줄바꿈으로 잇고, 첫 행은 머리행(`<th>`)이다. `_split_html_table` 이
# `<tr>` 로 시작하는 줄을 행으로 읽어 나누므로, 한 줄로 이으면 긴 표가 영영 안 쪼개진다.

_TABLE_OPEN = "<table><tbody>"
_TABLE_CLOSE = "</tbody></table>"
_PAGE_BASIS_PAGE = "page"
_PAGE_BASIS_DOCUMENT = "document"


def _log_info(message: str, *, event: str, **fields: Any) -> None:
    _emit_log(logging.INFO, message, event=event, **fields)


def _text_cell_html(text: str) -> str:
    """셀 안 개행은 `<br>` 로. 개행을 그대로 두면 표가 한 줄이라는 규약이 깨진다."""
    escaped = _html.escape((text or "").strip(), quote=False)
    for raw in ("\r\n", "\r", "\n"):
        escaped = escaped.replace(raw, _CELL_LINE_BREAK)
    return escaped


def _cell_tag(tag: str, text: str, rowspan: int, colspan: int) -> str:
    attrs = ""
    if rowspan > 1:
        attrs += f' rowspan="{rowspan}"'
    if colspan > 1:
        attrs += f' colspan="{colspan}"'
    return f"<{tag}{attrs}>{_text_cell_html(text)}</{tag}>"


def _join_table(rows: list) -> str:
    return "\n".join([_TABLE_OPEN] + rows + [_TABLE_CLOSE]) if rows else ""


# ===========================================================================
# pdf — PyMuPDF 로 표 격자를 되살린다
# ===========================================================================
#
# 첨부용은 `PyMuPDFLoader` 평문을 문자 수로 잘라 표가 문장으로 풀린다. 여기서는 같은
# PyMuPDF 로 `page.find_tables()` 를 불러 표를 HTML 표 블록으로 만든다.
#
# `Block.section` 은 전부 0 이다 — `chunk_blocks` 가 구역이 바뀔 때 끊으므로 페이지를
# 구역으로 쓰면 페이지를 걸친 조가 반으로 갈린다. 페이지는 `origin` 에 싣는다.
#
# 한계: 괘선 없는 표는 잘 안 잡힌다(`strategy="text"` 는 문단을 표로 오인해 더 나쁘다).
# 스캔 pdf 는 텍스트 레이어가 없어 예외로 세운다. 읽는 순서는 아래 절이 맡는다.

# 문단 블록이 표 영역에 이만큼 겹치면 표 안 글자로 본다(같은 글자가 두 번 실리지 않게).
_IN_TABLE_RATIO = 0.6


def _pdf_module():
    try:
        import pymupdf  # type: ignore
        return pymupdf
    except ImportError:
        import fitz  # type: ignore  # 1.24 이전 판본의 이름
        return fitz


def _find_tables(page) -> list:
    """병합 셀 복원(`refine=True`)을 먼저 쓰고, 그 인자를 모르는 판본이면 기본값으로.
    `find_tables` 자체가 없는 판본(1.23 이전)이면 표 없이 문단만 낸다."""
    finder = getattr(page, "find_tables", None)
    if finder is None:
        return []
    try:
        found = finder(refine=True)
    except TypeError:
        found = finder()
    return list(getattr(found, "tables", None) or [])


# `find_tables` 는 괘선으로 표를 찾으므로 **쪽 테두리 · 레이아웃 상자도 표로 잡는다.** 2단
# 저널의 쪽 테두리가 3열 표(왼 단 · 거터 · 오른 단)로 잡히면 본문 전체가 표 칸 글자가 돼 문단이
# 통째로 사라진다. 그런 "표" 는 쪽 글자를 거의 다 품고 칸에 산문이 든다 — 진짜 표의 칸은
# 짧다(실측 중앙값 4~15자, 레이아웃 상자는 48~1,900자). 긴 칸 **하나**만으로는 가르지 않는다
# — 격자 복원이 틀린 진짜 표는 여러 칸 글이 한 칸에 몰려 수백 자가 된다.
_PDF_TABLE_PAGE_SHARE = 0.85       # 쪽 글자의 이만큼 이상을 품은 표는 칸이 짧을 때만 표다
_PDF_TABLE_SHORT_MEDIAN = 20       # 칸 글자 수 중앙값이 이 이하이면 짧은 칸이다
_PDF_TABLE_PROSE_MEDIAN = 200      # 칸 중앙값이 이보다 길면 글상자다
_PDF_TABLE_BLOB_CELL = 1000        # 칸 하나가 이보다 길고 중앙값도 짧지 않으면 글상자다
_PDF_TABLE_BLOB_MEDIAN = 50


def _pdf_table_plausible(table, lines: list) -> bool:
    """`find_tables` 결과가 진짜 표인가. 아니면 그 영역은 본문으로 읽는다(글자는 잃지 않는다)."""
    try:
        cells = [cell for row in (table.extract() or []) for cell in row if cell]
    except Exception:  # noqa: BLE001 - 칸을 못 읽는 표는 격자도 못 만든다
        return False
    if not cells:
        return False
    lengths = sorted(len(cell) for cell in cells)
    median = lengths[len(lengths) // 2]
    if median > _PDF_TABLE_PROSE_MEDIAN:
        return False
    if lengths[-1] > _PDF_TABLE_BLOB_CELL and median > _PDF_TABLE_BLOB_MEDIAN:
        return False
    total = sum(len(line.text) for line in lines)
    box = tuple(table.bbox)
    inside = sum(
        len(line.text) for line in lines
        if _overlap_ratio((line.x0, line.y0, line.x1, line.y1), box) >= _IN_TABLE_RATIO
    )
    if total and inside >= total * _PDF_TABLE_PAGE_SHARE:
        return median <= _PDF_TABLE_SHORT_MEDIAN
    return True


def pdf_table_html(table) -> str:
    """PyMuPDF `Table` → HTML 표. 못 만들면 빈 문자열.

    `placements`(병합을 복원한 격자, 덮인 칸은 빠져 있다)가 있으면 그대로 옮긴다.
    없는 판본이면 `extract()` 의 `None`(덮인 칸)을 왼쪽·위쪽 칸의 병합으로 되짚는다.
    덮인 자리에는 칸을 내지 않는다 — 내면 그 행만 열이 하나 늘어난다.
    """
    placements = getattr(table, "placements", None)
    rows = []
    if placements:
        for row_idx, cells in enumerate(placements):
            rendered = [
                _cell_tag(
                    getattr(cell, "tag", None) or ("th" if row_idx == 0 else "td"),
                    getattr(cell, "text", "") or "",
                    int(getattr(cell, "rowspan", 1) or 1),
                    int(getattr(cell, "colspan", 1) or 1),
                )
                for cell in cells
            ]
            if rendered:
                rows.append("<tr>" + "".join(rendered) + "</tr>")
        return _join_table(rows)

    grid = table.extract() or []
    if not any(any(cell for cell in row) for row in grid):
        return ""
    width = max(len(row) for row in grid)
    owner: dict = {}  # (행, 열) → 앵커 (행, 열)
    spans: dict = {}  # 앵커 → [rowspan, colspan]
    for i, row in enumerate(grid):
        for j in range(width):
            if (i, j) in owner:
                continue
            cell = row[j] if j < len(row) else None
            if cell is None:
                left = owner.get((i, j - 1))
                if left is not None and left[0] == i:
                    spans[left][1] += 1  # 같은 행에서 시작한 앵커의 오른쪽 → 가로 병합
                    owner[(i, j)] = left
                    continue
                above = owner.get((i - 1, j))
                if above is not None and above[1] == j and above[0] + spans[above][0] == i:
                    spans[above][0] += 1  # 위 앵커의 첫 열 → 세로 병합, 덮는 열 전체를 차지
                    for d in range(spans[above][1]):
                        owner[(i, j + d)] = above
                    continue
            owner[(i, j)] = (i, j)
            spans[(i, j)] = [1, 1]
    for i, row in enumerate(grid):
        tag = "th" if i == 0 else "td"
        rendered = []
        for j in range(width):
            if owner.get((i, j)) != (i, j):
                continue
            rowspan, colspan = spans[(i, j)]
            text = row[j] if j < len(row) and row[j] else ""
            rendered.append(_cell_tag(tag, text, rowspan, colspan))
        rows.append("<tr>" + "".join(rendered) + "</tr>")
    return _join_table(rows)


def _overlap_ratio(box, area) -> float:
    x0, y0, x1, y1 = box
    ax0, ay0, ax1, ay1 = area
    width = min(x1, ax1) - max(x0, ax0)
    height = min(y1, ay1) - max(y0, ay0)
    size = (x1 - x0) * (y1 - y0)
    if width <= 0 or height <= 0 or size <= 0:
        return 0.0
    return (width * height) / size


# ---------------------------------------------------------------------------
# pdf 읽는 순서 — 다단 조판 · 문단 · 머리말
# ---------------------------------------------------------------------------
#
# PyMuPDF 가 주는 것은 **화면의 줄**이다. 그대로 쓰면 세 가지가 깨진다:
#
# 1. **다단이 섞인다.** 줄을 (y, x) 로 정렬하면 같은 높이의 왼쪽 단 줄과 오른쪽 단 줄이
#    번갈아 나온다. 그래서 줄 좌표로 단 사이의 빈 세로띠(거터)를 찾고, 거터를 가로지르는
#    줄·표(제목·초록·전폭 표)를 띠 경계로 삼아 **띠 안에서는 단 순서대로** 읽는다.
# 2. **문단이 없다.** 줄 끝은 단 폭에서 강제로 바뀐 것이라 줄 하나가 문단이 아니다.
#    간격·들여쓰기·짧게 끝난 줄·글자 크기·조문/목록 표기로 문단을 다시 묶고, 단이나
#    페이지를 넘어 이어지는 문단도 잇는다.
# 3. **머리말·쪽번호가 본문 사이에 끼어든다.** 단이 바뀌는 자리에서 문장 한가운데 들어간다.
#    위·아래 띠에서 여러 페이지에 되풀이되는 줄과 쪽번호 모양 줄을 뺀다.
#
# 조문 위계는 그대로 선다 — `제5조`·`①`·`1.`·글머리표로 시작하는 줄은 **언제나 새 문단**을
# 연다(`_pdf_marker_line`). `_match_statute` 가 보는 "줄 머리" 가 문단 머리로 남는다.
#
# 한국어는 줄 끝에서 낱말 가운데가 끊기는 일이 흔한데(`기 / 업의`), 끊긴 자리가 낱말
# 경계인지는 좌표로 알 수 없다. **공백으로 잇는다** — 공백을 빼면 낱말 경계에서 끊긴
# 줄이 `공공연구소와대학의` 처럼 붙고, 검색에는 그쪽이 더 해롭다.

# 머리말·꼬리말 후보 띠 (페이지 높이 비율).
_PDF_HEADER_BAND = 0.12
_PDF_FOOTER_BAND = 0.10

# 되풀이 판정. OCR 텍스트 레이어는 같은 머리말도 쪽마다 글자가 조금씩 다르다
# (`地理學論叢` / `地理學說훌훌`) — 그래서 같음이 아니라 유사도로 본다. 홀·짝 쪽 머리말이
# 번갈아 나오는 조판도 걸리게 문턱은 전체 쪽의 1/4 이다.
_PDF_RUNNING_SIMILARITY = 0.6
_PDF_RUNNING_MIN_PAGES = 3
_PDF_RUNNING_PAGE_RATIO = 0.25
_PDF_RUNNING_MIN_KEY = 2
_PDF_MARGIN_GAP = 1.5              # 머리말 · 꼬리말은 본문과 줄 높이의 이 배 넘게 떨어져 있다

# 쪽번호 모양: `3` · `- 3 -` · `(3)` · `3 / 29` · `Page 3 of 29`. 띠 안에서만 본다.
_PDF_PAGE_NO_RE = re.compile(
    r"^[-–—(\[\s]*(?:page\s*)?\d{1,4}(?:\s*(?:/|of)\s*\d{1,4})?[-–—)\]\s]*$", re.IGNORECASE
)

# 거터 탐지. 본문 폭의 60% 보다 좁은 줄만 단 후보로 세고, 그 줄들이 비워 둔 세로띠를
# 찾는다. 가운데 70% 밖(여백 쪽)에서는 찾지 않는다.
_PDF_NARROW_RATIO = 0.6
_PDF_GUTTER_SEARCH = 0.15
_PDF_MIN_GUTTER = 6.0              # pt
# 본문 가운데 정렬 줄(그림 · 표 캡션, 가운데 제목)은 거터 위에 걸치는 게 정상이다 — 전폭
# 요소로 띠를 가를 뿐 단 판정의 잡음으로 세지 않는다. 가운데에서 본문 폭의 이만큼 안이면 가운데다.
_PDF_CENTERED = 0.05
# 거터를 가로지르는 좁은 줄은 이 비율(적어도 `_PDF_GUTTER_NOISE_MIN` 줄)까지 허용한다 —
# 표 · 그림 캡션과 출처 줄이 가운데에 걸친다. 표가 있는 쪽은 본문 줄이 적어 비율만으로는
# 캡션 두 줄에 거터가 막힌다.
_PDF_GUTTER_NOISE = 0.1
_PDF_GUTTER_NOISE_MIN = 2
_PDF_MIN_COLUMN_LINES = 3
_PDF_MIN_COLUMN_SHARE = 0.15
# 단 안 줄의 중앙 폭이 단 폭의 절반은 돼야 단이다. 짧은 라벨·값 목록(`성명   홍길동`)을
# 두 단으로 읽으면 라벨만 줄줄이 나온 뒤 값이 따로 나온다.
_PDF_MIN_COLUMN_FILL = 0.5
_PDF_SPAN_TOLERANCE = 1.0          # 거터를 이만큼 넘어야 가로지르는 것으로 본다
_PDF_GUTTER_MATCH = 8.0            # pt — 쪽마다 찾은 거터를 같은 조판으로 묶는 거리
_PDF_BORROW_MAX_WIDE = 0.5         # 전폭 줄이 이보다 많은 쪽에는 문서 거터를 빌려 주지 않는다
# 같은 행 조각을 한 줄로 합치는 최대 간격(글자 크기 배수). 단을 못 찾은 쪽에서 좌 · 우 단의
# 같은 높이 줄이 한 줄로 붙지 않게 하는 마지막 방어선이다.
_PDF_ROW_JOIN_GAP = 2.0
_PDF_FRAGMENT_CHARS = 2            # 그림 속 글자처럼 한두 자짜리 줄이 이어지면 한 덩어리로 싣는다

# 문단 판정.
_PDF_GAP_FACTOR = 1.6              # 단 안 줄 간격 중앙값의 이 배를 넘으면 문단이 바뀐다
_PDF_GAP_SLACK = 1.0               # pt — 간격이 아주 좁은 조판에서 반올림 차이로 끊기지 않게
_PDF_SHORT_LINE = 0.3              # 단 폭의 이만큼 못 미쳐 끝난 줄은 문단 끝이다
_PDF_SHORT_SENTENCE = 0.08         # 문장이 끝났으면 이만큼만 모자라도 문단 끝이다
# 글자 크기 변화는 **줄 간격도 함께 벌어졌을 때만** 제목/본문 경계로 본다. OCR 텍스트
# 레이어는 같은 문단 안에서도 줄마다 크기가 5.7~8.9pt 로 흔들려, 크기만 보면 문장 한가운데서
# 끊는다. 진짜 제목은 대개 앞뒤로 간격을 두고, 아니어도 짧은 줄 · 번호 표기가 잡는다.
_PDF_SIZE_RATIO = 1.2
_PDF_SIZE_GAP_FACTOR = 1.2
_PDF_INDENT_MIN = 2.0              # pt — 첫 줄 들여쓰기 최소 폭
_PDF_SENTENCE_END_RE = re.compile(r"[.!?。:;][\"'”’」』)\]]*$")
_PDF_BULLET_RE = re.compile(r"^[•·∙◦○●□■▪▫◆◇▶►※*\-–—]\s")
_PDF_HYPHEN_RE = re.compile(r"[A-Za-z]-$")
# 목 표기(`다.`)와 모양이 같은 어미 — 단 끝 `…담고 있` 다음 단 첫 줄 `다. 공공기관…`.
_PDF_ENDING_MARKER_RE = re.compile(rf"^[{_MOK_LETTERS}][.．]")

_PDF_WIDE = -1                     # 거터를 가로지르는 줄·표의 단 번호
_PDF_OTHER = "other"               # 세로쓰기 · 기울어진 줄의 group 표식 — 앞뒤와 잇지 않는다


@dataclass(frozen=True)
class _PdfLine:
    """화면의 줄 하나. `group` 은 같은 단의 연속 구간 표식(`_pdf_order` 가 매긴다)."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    size: float
    bold: bool
    group: tuple = ()


def _pdf_page_lines(page, page_no: int) -> tuple:
    """(가로 줄 목록, 가로가 아닌 줄 목록). 표 영역 안 줄은 `parse_pdf` 가 뺀다."""
    horizontal: list = []
    other: list = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type", 0) != 0:
            continue  # 이미지 블록
        for line in block.get("lines", []):
            spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
            if not spans:
                continue
            text = re.sub(r"\s+", " ", "".join(span.get("text", "") for span in line["spans"]))
            text = text.strip()
            box = tuple(line["bbox"])
            # 줄의 글자 크기·굵기는 가장 긴 조각 것으로 — 각주 번호 같은 작은 조각에 끌리지 않게.
            main = max(spans, key=lambda span: len(span["text"].strip()))
            item = _PdfLine(
                page=page_no,
                x0=box[0],
                y0=box[1],
                x1=box[2],
                y1=box[3],
                text=text,
                size=round(float(main.get("size", 0.0)), 1),
                bold=bool(int(main.get("flags", 0)) & 16),
            )
            dx, dy = line.get("dir", (1.0, 0.0))
            (horizontal if dx > 0.9 and abs(dy) < 0.1 else other).append(item)
    return horizontal, other


def _pdf_extent(lines: list) -> tuple:
    """줄들이 차지하는 가로 범위 `(왼쪽 끝, 오른쪽 끝)`. 빈 목록이면 부르지 않는다."""
    return min(line.x0 for line in lines), max(line.x1 for line in lines)


def _pdf_same_row(a: _PdfLine, b: _PdfLine) -> bool:
    """두 줄이 같은 높이에 걸쳤는가 — 겹친 높이가 낮은 쪽 줄 높이의 절반을 넘는다."""
    return min(a.y1, b.y1) - max(a.y0, b.y0) > 0.5 * min(a.y1 - a.y0, b.y1 - b.y0)


def _pdf_lines_by_group(elements: list) -> dict:
    """읽는 순서의 요소 중 줄만 group 별로, 순서를 지켜 모은다."""
    by_group: dict = {}
    for element in elements:
        if element[0] == "line":
            by_group.setdefault(element[1].group, []).append(element[1])
    return by_group


def _pdf_margin_ids(lines: list, height: float) -> set:
    """머리말 · 꼬리말 **후보** 줄의 id — 위 · 아래 띠 안에 있고 본문과 떨어져 있는 줄.

    띠 안에 있다는 것만으로는 모자란다. 위 여백이 좁은 조판은 본문 첫 줄이 위 띠에 들고,
    그 줄이 쪽마다 비슷하면(서식 문서 · 반복 양식) 머리말로 오인돼 본문이 사라진다. 그래서
    **다음 줄(꼬리말은 앞 줄)과 줄 높이의 `_PDF_MARGIN_GAP` 배 넘게 떨어진 줄**만 후보다.
    **쪽 맨 위 · 맨 아래 행은 간격과 무관하게 후보다** — 저널 머리말은 바로 밑 캡션 · 표에
    붙어 있기도 하다. 후보에 붙어 있다는 이유로 후보가 되지는 않는다 — 머리말 밑 `TABLE 1.`
    캡션이 쪽마다 비슷해 머리말로 딸려 지워진다.
    """
    ids: set = set()

    def scan(candidates: list, neighbours) -> None:
        for line in candidates:
            near = neighbours(line)
            if near is None:
                ids.add(id(line))
                continue
            if near[1] >= (line.y1 - line.y0) * _PDF_MARGIN_GAP:
                ids.add(id(line))

    def below(line: _PdfLine):
        rest = [(other, other.y0 - line.y1) for other in lines
                if other is not line and not _pdf_same_row(other, line) and other.y0 > line.y0]
        return min(rest, key=lambda item: item[1], default=None)

    def above(line: _PdfLine):
        rest = [(other, line.y0 - other.y1) for other in lines
                if other is not line and not _pdf_same_row(other, line) and other.y1 < line.y1]
        return min(rest, key=lambda item: item[1], default=None)

    top = [line for line in lines if line.y1 <= height * _PDF_HEADER_BAND]
    bottom = [line for line in lines if line.y0 >= height * (1 - _PDF_FOOTER_BAND)]
    if top:
        first = min(top, key=lambda line: line.y0)
        ids.update(id(line) for line in top if line is first or _pdf_same_row(line, first))
    if bottom:
        last = max(bottom, key=lambda line: line.y1)
        ids.update(id(line) for line in bottom if line is last or _pdf_same_row(line, last))
    scan(top, below)
    scan(bottom, above)
    return ids


def _pdf_running_key(text: str) -> str:
    """쪽마다 바뀌는 숫자를 지운 비교 열쇠 — `제41호 (2003.3) 5` 와 `… 6` 이 같아진다."""
    return re.sub(r"\d+", "#", re.sub(r"\s+", "", text))


def _pdf_similar(left: str, right: str) -> bool:
    if left == right:
        return True
    matcher = difflib.SequenceMatcher(None, left, right)
    return (
        matcher.real_quick_ratio() >= _PDF_RUNNING_SIMILARITY
        and matcher.quick_ratio() >= _PDF_RUNNING_SIMILARITY
        and matcher.ratio() >= _PDF_RUNNING_SIMILARITY
    )


def _pdf_running_keys(pages: list) -> list:
    """여러 페이지 위·아래 띠에 되풀이되는 줄의 열쇠. `pages` 는 `(높이, 줄 목록)` 목록.

    쪽이 적으면 되풀이를 판정할 수 없어 아무것도 빼지 않는다 — 1~2쪽 문서의 첫 줄이
    머리말로 오인돼 사라지는 쪽이 머리말 한 줄이 남는 것보다 나쁘다.
    """
    if len(pages) < _PDF_RUNNING_MIN_PAGES:
        return []
    per_page = []
    for height, lines in pages:
        margin = _pdf_margin_ids(lines, height)
        per_page.append({
            key
            for key in (_pdf_running_key(line.text) for line in lines if id(line) in margin)
            if len(key) >= _PDF_RUNNING_MIN_KEY
        })
    distinct = sorted(set().union(*per_page))
    threshold = max(_PDF_RUNNING_MIN_PAGES, math.ceil(len(pages) * _PDF_RUNNING_PAGE_RATIO))
    running = []
    for key in distinct:
        similar = {other for other in distinct if _pdf_similar(key, other)}
        if sum(1 for keys in per_page if keys & similar) >= threshold:
            running.append(key)
    return running


def _pdf_is_running(line: _PdfLine, margin: set, running: list) -> bool:
    if id(line) not in margin:
        return False
    if _PDF_PAGE_NO_RE.match(line.text):
        return True
    key = _pdf_running_key(line.text)
    return any(_pdf_similar(key, other) for other in running)


def _pdf_narrow_lines(lines: list) -> list:
    """단 판정에 쓰는 줄 — 본문 폭보다 충분히 좁고, 가운데 정렬이 아닌 줄.

    가운데에 걸친 줄이라도 **왼쪽 끝을 여러 줄과 함께 쓰면** 캡션이 아니라 단의 줄이다 —
    3단 조판의 가운데 단은 줄마다 쪽 가운데에 걸친다. 그 단을 빼면 가운데 단 한복판이
    빈 띠로 보여 거터가 거기 하나만 잡힌다.
    """
    left, right = _pdf_extent(lines)
    width = right - left
    middle = (left + right) / 2
    narrow = [line for line in lines if line.x1 - line.x0 < width * _PDF_NARROW_RATIO]
    edges: dict = {}
    for line in narrow:
        edges[round(line.x0)] = edges.get(round(line.x0), 0) + 1
    return [
        line
        for line in narrow
        if not (
            line.x0 < middle < line.x1
            and abs((line.x0 + line.x1) / 2 - middle) <= width * _PDF_CENTERED
            and edges[round(line.x0)] < _PDF_MIN_COLUMN_LINES
        )
    ]


def _pdf_column_fill(lines: list, lo: float, hi: float) -> bool:
    """`lo..hi` 구간이 글 단인가 — 줄이 충분히 많고, 줄이 구간 폭을 절반 이상 채운다."""
    width = hi - lo
    if len(lines) < _PDF_MIN_COLUMN_LINES or width <= 0:
        return False
    widths = sorted(line.x1 - line.x0 for line in lines)
    return widths[len(widths) // 2] >= width * _PDF_MIN_COLUMN_FILL


def _pdf_gutters(lines: list) -> list:
    """단 사이 거터의 x 좌표(가운데) 목록. 1단이면 빈 목록.

    좁은 줄들의 x 점유를 1pt 칸으로 세어, 거의 비어 있는 세로띠를 거터 후보로 삼는다.
    후보 양쪽 구간이 **글 단처럼 보일 때만** 남긴다 — 그렇지 않은 후보를 빼고 나면
    이웃 구간이 넓어지므로 더 빠지는 것이 없을 때까지 다시 본다.
    """
    if not lines:
        return []
    left, right = _pdf_extent(lines)
    width = right - left
    if width <= 0:
        return []
    narrow = _pdf_narrow_lines(lines)
    if len(narrow) < 2 * _PDF_MIN_COLUMN_LINES:
        return []

    cells = int(width) + 2
    coverage = [0] * (cells + 1)
    for line in narrow:
        first = max(0, int(line.x0 - left) + 1)
        last = min(cells, int(line.x1 - left))
        if first <= last:
            coverage[first] += 1
            coverage[last + 1] -= 1
    allowed = max(_PDF_GUTTER_NOISE_MIN, int(len(narrow) * _PDF_GUTTER_NOISE))
    search_lo = int(width * _PDF_GUTTER_SEARCH)
    search_hi = int(width * (1 - _PDF_GUTTER_SEARCH))
    candidates = []
    running_count = 0
    start = None
    for cell in range(cells):
        running_count += coverage[cell]
        empty = search_lo <= cell <= search_hi and running_count <= allowed
        if empty and start is None:
            start = cell
        elif not empty and start is not None:
            if cell - start >= _PDF_MIN_GUTTER:
                candidates.append(left + (start + cell) / 2)
            start = None

    while candidates:
        edges = [left] + candidates + [right]
        keep = []
        for index, gutter in enumerate(candidates):
            lo, hi = edges[index], edges[index + 2]
            left_lines = [l for l in narrow if l.x0 >= lo - 1 and l.x1 <= gutter]
            right_lines = [l for l in narrow if l.x0 >= gutter and l.x1 <= hi + 1]
            share = len(narrow) * _PDF_MIN_COLUMN_SHARE
            if (
                len(left_lines) >= share
                and len(right_lines) >= share
                and _pdf_column_fill(left_lines, lo, gutter)
                and _pdf_column_fill(right_lines, gutter, hi)
            ):
                keep.append(gutter)
        if keep == candidates:
            break
        candidates = keep
    return candidates


def _pdf_document_gutters(per_page: list) -> list:
    """쪽마다 찾은 거터 중 **가장 많은 쪽이 쓰는 조판**. 한 쪽뿐이면 빈 목록."""
    tally: list = []  # [대표 거터, 쪽 수]
    for gutters in per_page:
        if not gutters:
            continue
        for entry in tally:
            same = len(entry[0]) == len(gutters) and all(
                abs(a - b) <= _PDF_GUTTER_MATCH for a, b in zip(entry[0], gutters)
            )
            if same:
                entry[1] += 1
                break
        else:
            tally.append([gutters, 1])
    best = max(tally, key=lambda entry: entry[1], default=None)
    return list(best[0]) if best and best[1] >= 2 else []


def _pdf_gutters_fit(lines: list, gutters: list) -> bool:
    """문서 거터를 이 쪽에 써도 되는가 — 거터를 가로지르는 좁은 줄이 허용치 이내다.

    표 · 그림이 큰 쪽은 본문 줄이 단마다 두어 줄뿐이라 거터를 스스로 못 찾는다. 그런
    쪽을 1단으로 읽으면 같은 높이의 좌 · 우 줄이 번갈아 나온다. 반대로 표지 · 초록처럼
    줄 대부분이 거터를 가로지르는 쪽은 정말 1단이다 — 거기 거터를 씌우면 전폭 줄 사이에
    낀 짧은 줄만 단으로 떨어져 나가 문단이 조각난다.
    """
    if not lines or not gutters:
        return False
    wide = sum(1 for line in lines if _pdf_column_of(line.x0, line.x1, gutters) == _PDF_WIDE)
    if wide > len(lines) * _PDF_BORROW_MAX_WIDE:
        return False
    narrow = _pdf_narrow_lines(lines)
    crossing = sum(1 for line in narrow if _pdf_column_of(line.x0, line.x1, gutters) == _PDF_WIDE)
    allowed = max(_PDF_GUTTER_NOISE_MIN, int(len(narrow) * _PDF_GUTTER_NOISE))
    return crossing <= allowed


def _pdf_column_of(x0: float, x1: float, gutters: list) -> int:
    for gutter in gutters:
        if x0 < gutter - _PDF_SPAN_TOLERANCE and x1 > gutter + _PDF_SPAN_TOLERANCE:
            return _PDF_WIDE
    center = (x0 + x1) / 2
    return sum(1 for gutter in gutters if center > gutter)


def _pdf_rows(items: list) -> list:
    """y 순서로 두되 **같은 높이에 걸친 것은 한 행으로 묶어 x 순서로** — 한 단 안에서
    나란히 놓인 두 줄(`성명` · `홍길동`)의 y0 가 반올림 차이로 뒤집히지 않게. → 행 목록."""
    ordered = sorted(items, key=lambda item: (item[1][1], item[1][0]))
    rows: list = []
    for item in ordered:
        y0, y1 = item[1][1], item[1][3]
        if rows:
            row_y0, row_y1 = rows[-1][0], rows[-1][1]
            overlap = min(y1, row_y1) - max(y0, row_y0)
            if overlap > 0.5 * min(y1 - y0, row_y1 - row_y0):
                rows[-1][2].append(item)
                rows[-1][1] = max(row_y1, y1)
                continue
        rows.append([y0, y1, [item]])
    return [sorted(row, key=lambda it: it[1][0]) for _, _, row in rows]


def _pdf_merge_row(lines: list) -> list:
    """한 행의 줄 조각 중 **가까이 붙은 것끼리** 한 줄로. OCR 텍스트 레이어는 한 줄을 여러
    조각으로 내는 일이 잦고(`3월` · `1 일부터 시행`), 조각마다 줄로 두면 짧게 끝난 줄로 보여
    문단이 끊긴다. 멀리 떨어진 조각(다른 단 · 표 칸)은 따로 둔다."""
    runs: list = []
    for line in lines:
        if runs and line.x0 - runs[-1][-1].x1 <= _PDF_ROW_JOIN_GAP * max(line.size, runs[-1][-1].size, 1.0):
            runs[-1].append(line)
        else:
            runs.append([line])
    merged = []
    for run in runs:
        if len(run) == 1:
            merged.append(run[0])
            continue
        main = max(run, key=lambda line: len(line.text))
        merged.append(replace(
            main,
            x0=min(line.x0 for line in run),
            y0=min(line.y0 for line in run),
            x1=max(line.x1 for line in run),
            y1=max(line.y1 for line in run),
            text=" ".join(line.text for line in run),
        ))
    return merged


def _pdf_join_fragments(lines: list, gutters: list) -> list:
    """같은 행의 가까운 조각을 **단을 가르기 전에** 한 줄로 합친다. 사이에 거터가 있으면
    합치지 않는다(그건 좌 · 우 단의 같은 높이 줄이다).

    가운데 정렬 캡션이 `TABLE 1.` · `Model setup …` 두 조각으로 오면, 앞 조각만 왼쪽 단에
    들어 앞 문단 끝에 붙고 캡션은 반쪽이 된다.
    """
    rows: list = []
    for line in sorted(lines, key=lambda line: (line.y0, line.x0)):
        if rows and _pdf_same_row(line, rows[-1][0]):
            rows[-1].append(line)
            continue
        rows.append([line])
    joined = []
    for row in rows:
        row.sort(key=lambda line: line.x0)
        runs = [[row[0]]]
        for line in row[1:]:
            previous = runs[-1][-1]
            gap = line.x0 - previous.x1
            close = gap <= _PDF_ROW_JOIN_GAP * max(line.size, previous.size, 1.0)
            if close and not any(previous.x1 <= gutter <= line.x0 for gutter in gutters):
                runs[-1].append(line)
            else:
                runs.append([line])
        joined.extend(_pdf_merge_row(run)[0] if len(run) > 1 else run[0] for run in runs)
    return joined


def _pdf_order(page_no: int, lines: list, tables: list, figures: list, gutters: list) -> list:
    """한 페이지를 읽는 순서로. → 요소 목록.

    요소는 `("line", _PdfLine)` 또는 `(kind, 글, page, media)` 다(`kind` 는 `table` · `figure`).
    `tables` · `figures` 는 `(상자, 글, media)` 목록이다. 줄에는 `group` 을 매긴다 —
    같은 띠 · 같은 단의 연속 구간이 한 group 이고, 문단 판정이 group 안에서 간격을 잰다.
    """
    items = [("line", (line.x0, line.y0, line.x1, line.y1), line) for line in lines]
    items += [("table", box, (text, media)) for box, text, media in tables]
    items += [("figure", box, (text, media)) for box, text, media in figures]
    tagged = [
        (kind, box, payload, _pdf_column_of(box[0], box[2], gutters))
        for kind, box, payload in items
    ]
    tagged.sort(key=lambda item: (item[1][1], item[1][0]))

    elements: list = []
    band: list = []
    counter = [0]

    def emit(members: list, column: int) -> None:
        if not members:
            return
        counter[0] += 1
        group = (page_no, counter[0], column)
        for row in _pdf_rows(members):
            pending: list = []
            for kind, _box, payload, _column in row:
                if kind != "line":
                    for merged in _pdf_merge_row(pending):
                        elements.append(("line", replace(merged, group=group)))
                    pending = []
                    elements.append((kind, payload[0], page_no, payload[1]))
                else:
                    pending.append(payload)
            for merged in _pdf_merge_row(pending):
                elements.append(("line", replace(merged, group=group)))

    def flush_band() -> None:
        for column in range(len(gutters) + 1):
            emit([item for item in band if item[3] == column], column)
        band.clear()

    wide: list = []
    for item in tagged:
        if item[3] == _PDF_WIDE:
            if band:
                flush_band()
            wide.append(item)
            continue
        if wide:
            emit(wide, _PDF_WIDE)
            wide = []
        band.append(item)
    flush_band()
    emit(wide, _PDF_WIDE)
    return elements


@dataclass(frozen=True)
class _PdfGeometry:
    left: float
    right: float
    gap: float


def _pdf_geometries(elements: list) -> dict:
    """group 마다 왼쪽 여백(가장 흔한 x0) · 오른쪽 끝 · 줄 간격 중앙값."""
    members = _pdf_lines_by_group(elements)
    all_gaps = []
    raw: dict = {}
    for group, lines in members.items():
        counts: dict = {}
        for line in lines:
            counts[round(line.x0)] = counts.get(round(line.x0), 0) + 1
        mode = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]
        gaps = [b.y0 - a.y1 for a, b in zip(lines, lines[1:]) if b.y0 - a.y1 > 0]
        all_gaps.extend(gaps)
        raw[group] = (mode, max(line.x1 for line in lines), gaps)
    fallback = sorted(all_gaps)[len(all_gaps) // 2] if all_gaps else 2.0
    geometries = {}
    for group, (left, right, gaps) in raw.items():
        # 줄이 셋 미만인 group 은 간격 표본이 없다 — 문서 전체 중앙값을 쓴다.
        gap = sorted(gaps)[len(gaps) // 2] if len(gaps) >= 2 else fallback
        geometries[group] = _PdfGeometry(left=left, right=right, gap=gap)
    return geometries


def _pdf_marker_line(text: str) -> bool:
    """조문 · 공문서 번호 · 글머리표로 시작하는 줄 — 언제나 새 문단을 연다."""
    stripped = text.strip()
    if _PDF_BULLET_RE.match(stripped):
        return True
    return any(pattern.match(stripped) for _, pattern in _STATUTE_RULES + _DOCUMENT_RULES)


def _pdf_indent_starts(elements: list, geometries: dict) -> set:
    """첫 줄 들여쓰기로 문단을 여는 줄의 id.

    **다음 줄이 왼쪽 여백으로 돌아올 때만** 들여쓰기로 본다. 그렇지 않으면 내어쓰기
    (`① …` 다음 줄들이 안으로 들어간 모양)의 둘째 줄마다 문단이 끊긴다.
    """
    starts = set()
    for group, lines in _pdf_lines_by_group(elements).items():
        geometry = geometries[group]
        for index, line in enumerate(lines):
            tolerance = max(_PDF_INDENT_MIN, line.size * 0.3)
            if line.x0 <= geometry.left + tolerance:
                continue
            following = lines[index + 1] if index + 1 < len(lines) else None
            if following is not None and following.x0 > geometry.left + tolerance:
                continue
            previous = lines[index - 1] if index > 0 else None
            if previous is not None and (
                previous.x0 > geometry.left + tolerance or _pdf_marker_line(previous.text)
            ):
                continue
            starts.add(id(line))
    return starts


def _pdf_marker_is_ending(previous: _PdfLine, line: _PdfLine, geometries: dict) -> bool:
    """`line` 머리의 `다.` 가 목 표기가 아니라 앞 줄에서 넘어온 어미인가.

    앞 줄이 한글 글자로 끝나고 문장이 안 끝났는데 자기 단을 거의 채웠으면 그 줄은 폭에서
    강제로 꺾인 것이다. 목 항목은 앞 항목이 문장으로 끝나거나 짧게 끝난 뒤에 온다. 이
    판정이 없으면 줄 · 단 · 쪽이 `…있` / `다.` 에서 꺾일 때마다 문장이 반으로 갈린다.
    """
    if not _PDF_ENDING_MARKER_RE.match(line.text.strip()):
        return False
    if _PDF_SENTENCE_END_RE.search(previous.text) or not re.search(r"[가-힣]$", previous.text):
        return False
    geometry = geometries[previous.group]
    width = geometry.right - geometry.left
    return width > 0 and geometry.right - previous.x1 <= width * _PDF_SHORT_SENTENCE


def _pdf_breaks(previous: _PdfLine, line: _PdfLine, geometries: dict, indent_starts: set) -> bool:
    """`previous` 다음에 `line` 이 오면 문단이 바뀌는가."""
    if _PDF_OTHER in (line.group[1], previous.group[1]):
        return True
    if (
        line.group == previous.group
        and len(line.text) <= _PDF_FRAGMENT_CHARS
        and len(previous.text) <= _PDF_FRAGMENT_CHARS
    ):
        return False  # 그림 속 세로 글자 · 도형 라벨 — 글자마다 문단으로 내면 청크가 부스러기가 된다
    if _pdf_marker_line(line.text) and not _pdf_marker_is_ending(previous, line, geometries):
        return True
    if line.bold != previous.bold:
        return True
    if id(line) in indent_starts:
        return True
    geometry = geometries[previous.group]
    column_width = geometry.right - geometry.left
    room = geometry.right - previous.x1
    sentence_end = bool(_PDF_SENTENCE_END_RE.search(previous.text))
    if column_width > 0:
        if room > column_width * _PDF_SHORT_LINE:
            return True
        if sentence_end and room > column_width * _PDF_SHORT_SENTENCE:
            return True
    if line.group == previous.group:
        gap = line.y0 - previous.y1
        if gap > geometry.gap * _PDF_GAP_FACTOR + _PDF_GAP_SLACK:
            return True
        sizes = sorted((line.size, previous.size))
        if sizes[0] > 0 and sizes[1] / sizes[0] >= _PDF_SIZE_RATIO and gap > geometry.gap * _PDF_SIZE_GAP_FACTOR:
            return True
        return gap < -(previous.y1 - previous.y0) / 2  # 위로 거슬러 올라간 줄
    # 다른 단 · 다른 페이지로 넘어갔다. 문장이 끝났으면 끊는다. 단과 전폭 사이는 이어지지
    # 않는다 — 전폭 줄은 제목 · 초록 · 캡션이고, 단 본문이 그리로 흘러 들어가지 않는다.
    if sentence_end:
        return True
    return (line.group[2] == _PDF_WIDE) != (previous.group[2] == _PDF_WIDE)


def _pdf_join(parts: list) -> str:
    text = parts[0]
    for part in parts[1:]:
        if _PDF_HYPHEN_RE.search(text) and part[:1].islower():
            text = text[:-1] + part  # 영문 줄끝 하이픈 — `trans-` + `fer`
        else:
            text = f"{text} {part}"
    return text


def _pdf_blocks(elements: list) -> list:
    """읽는 순서의 요소 → `Block` 목록. 문단은 여러 단 · 페이지에 걸칠 수 있고,
    그때 `origin` 에 걸친 페이지가 순서대로 모두 실린다(`_PdfSource`). 그림은 문단 블록
    (`[그림] 캡션`)이고, 표 · 그림 블록의 `origin` 이 저장한 이미지를 싣는다."""
    geometries = _pdf_geometries(elements)
    indent_starts = _pdf_indent_starts(elements, geometries)
    blocks: list = []
    parts: list = []
    pages: list = []
    previous = None

    def flush() -> None:
        if parts:
            blocks.append(
                Block(
                    kind="paragraph",
                    text=_pdf_join(parts),
                    section=0,
                    origin=tuple(_PdfSource(page) for page in pages),
                )
            )
        parts.clear()
        pages.clear()

    for element in elements:
        if element[0] != "line":
            kind, text, page, media = element
            flush()
            blocks.append(Block(
                kind="table" if kind == "table" else "paragraph",
                text=text,
                section=0,
                origin=(_PdfSource(page, media),),
            ))
            previous = None
            continue
        line = element[1]
        if previous is None or _pdf_breaks(previous, line, geometries, indent_starts):
            flush()
        parts.append(line.text)
        if line.page not in pages:
            pages.append(line.page)
        previous = line
    flush()
    return blocks


# ---------------------------------------------------------------------------
# pdf 그림 · 표 이미지 — 잘라 저장하고 청크의 `media_files` 에 잇는다
# ---------------------------------------------------------------------------
#
# 글자로는 그림을 실을 수 없고, 표도 격자 복원이 틀릴 수 있다. 그래서 **그 영역을 PNG 로
# 잘라** 원본 옆 `{파일명}/` 폴더(벤더 `get_paths` 와 같은 자리)에 두고, 그 영역에서 나온
# 블록의 `origin` 에 실어 청크 → 레코드 `media_files` 까지 나른다. 업로드는
# `genos_utils.upload_files` 로 한다 — 벤더 첨부용 · 지능형과 같은 함수 · 같은 인자다.
#
# 그림 영역은 두 길로 찾는다:
#
# - **본래 pdf** — 내장 이미지와 벡터 도형 묶음(`cluster_drawings`)의 좌표.
# - **스캔 pdf**(쪽 전체가 이미지 한 장이고 글자는 OCR 레이어) — 그림이 픽셀 속에 있어
#   객체가 없다. 캡션(`〈그림 1)` · `Figure 2`)을 닻으로 삼아, 캡션 위 · 아래로 **본문 줄이
#   나올 때까지의 빈 자리**를 그림으로 본다. 본문 줄은 자기 단 폭을 거의 채우는 줄이다 —
#   그림 속 라벨은 그렇게 길지 않다.
#
# 그림 영역 안의 글자 줄은 본문 흐름에서 빼 그림 블록 글(`[그림] 캡션 라벨…`)로 옮긴다.
# 캡션이 없으면 `[그림]` 과 라벨만 남아 이웃 문단과 한 청크로 묶인다.

_PDF_MEDIA_DPI = 150
_PDF_SCAN_COVER = 0.85             # 쪽 넓이의 이만큼을 덮는 이미지가 있으면 스캔 쪽이다
_PDF_FIGURE_MIN_SIDE = 24.0        # pt — 이보다 작은 이미지 · 도형은 장식(글머리 · 밑줄)이다
_PDF_FIGURE_MIN_AREA = 0.01        # 쪽 넓이 비율
_PDF_FIGURE_MIN_PIXELS = 4         # 내장 이미지의 원본 픽셀 폭 · 높이 — 1×1 은 색 채우기다
_PDF_FRAME_AREA = 0.4              # 쪽 넓이의 이만큼 넘는 도형 묶음은 쪽 테두리 · 배경이다
_PDF_CAPTION_GAP = 36.0            # pt — 그림 · 표와 캡션 사이 최대 거리
_PDF_CAPTION_REGION_MIN = 30.0     # pt — 캡션으로 잡은 빈 자리가 이보다 낮으면 그림이 아니다
_PDF_BODY_LINE_FILL = 0.7          # 자기 단 폭의 이만큼을 채우면 본문 줄이다
_PDF_TEXT_BOX_LINES = 3            # 도형 안에 본문 줄이 이만큼 있으면 그림이 아니라 글상자다
_PDF_IN_FIGURE_RATIO = 0.6
# 단을 못 찾은 쪽에서, 캡션으로 잡은 영역 안에 이 길이 이상인 줄이 `_PDF_TEXT_BOX_LINES` 개
# 넘게 있으면 그림이 아니라 본문이다 — 1단으로 본 쪽은 단 폭이 본문 전체라 2단 본문 줄이
# 본문 줄로 안 걸려 경계가 안 되고, 영역이 본문을 삼킨다. 단이 있으면 본문 줄이 경계다.
_PDF_PROSE_CHARS = 25
_PDF_PROSE_LETTERS = 0.6           # 공백 뺀 글자 중 한글 · 로마자가 이 비율 이상이면 문장이다
_PDF_FIGURE_LABEL_MAX = 300        # 그림 블록에 붙이는 라벨 글 최대 길이
_PDF_FIGURE_CAPTION_RE = re.compile(
    r"^[<〈《(\[【]?\s*(?:그림|도표|사진|차트|Figure|Fig\.?|Chart|Photo)\s*[\dⅠ-Ⅹ]", re.IGNORECASE
)
_PDF_TABLE_CAPTION_RE = re.compile(r"^[<〈《(\[【]?\s*(?:표|Table)\s*[\dⅠ-Ⅹ]", re.IGNORECASE)
_PDF_FIGURE_TAG = "[그림]"
_PDF_TABLE_TAG = "[표]"
_PDF_MEDIA_TYPE = "image"          # 벤더 `set_media_files` 와 같은 값 — 표 이미지도 image 다


@dataclass(frozen=True)
class _PdfMedia:
    """저장한 이미지 하나. `ref` 는 docling 표기(`#/pictures/3`)를 따른다."""

    name: str
    path: str
    ref: str


@dataclass(frozen=True)
class _PdfSource:
    """pdf 블록의 `origin` 원소 — 0-based 페이지와 그 블록이 가리키는 이미지."""

    page: int
    media: tuple = ()


def _origin_page(item) -> int:
    """`origin` 원소의 0-based 페이지. pdf 는 `_PdfSource`, 그 밖은 정수다."""
    return int(getattr(item, "page", item))


def _chunk_media(chunk) -> list:
    """청크가 덮는 블록들이 가리키는 이미지 — 처음 나온 순서, 중복 없이."""
    seen: dict = {}
    for item in chunk.origin or ():
        for media in getattr(item, "media", ()) or ():
            seen.setdefault(media.name, media)
    return list(seen.values())


def _media_files_json(media: list) -> str:
    """레코드 `media_files` — 벤더와 같은 모양(`[{name, type, ref}]`). 없으면 벤더처럼 `""`."""
    if not media:
        return ""
    return json.dumps(
        [{"name": item.name, "type": _PDF_MEDIA_TYPE, "ref": item.ref} for item in media],
        ensure_ascii=False,
    )


def _pdf_media_dir(file_path: str) -> str:
    """벤더 `get_paths` 와 같은 자리 — 원본 옆 `{파일명}/`."""
    folder, name = os.path.split(file_path)
    return os.path.join(folder, os.path.splitext(name)[0])


def _pdf_is_scanned(page) -> bool:
    area = page.rect.width * page.rect.height
    if area <= 0:
        return False
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        if (x1 - x0) * (y1 - y0) >= area * _PDF_SCAN_COVER:
            return True
    return False


def _pdf_box_ok(box, page_area: float) -> bool:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    return (
        width >= _PDF_FIGURE_MIN_SIDE
        and height >= _PDF_FIGURE_MIN_SIDE
        and width * height >= page_area * _PDF_FIGURE_MIN_AREA
        and width * height < page_area * _PDF_SCAN_COVER
    )


def _pdf_union(boxes: list) -> list:
    """겹치는 상자를 하나로 합친다 — 그림 하나가 이미지 여러 장 · 도형 여러 묶음일 때."""
    merged: list = []
    for box in sorted(boxes, key=lambda b: (b[1], b[0])):
        box = tuple(box)
        for index, other in enumerate(merged):
            if box[0] <= other[2] and other[0] <= box[2] and box[1] <= other[3] and other[1] <= box[3]:
                merged[index] = (
                    min(box[0], other[0]), min(box[1], other[1]),
                    max(box[2], other[2]), max(box[3], other[3]),
                )
                break
        else:
            merged.append(box)
    if len(merged) != len(boxes):
        return _pdf_union(merged)
    return merged


def _pdf_segment(gutters: list, left: float, right: float, column: int) -> tuple:
    """단 번호 → 그 단의 x 구간. 전폭이면 본문 전체."""
    if column == _PDF_WIDE or not gutters:
        return left, right
    edges = [left] + list(gutters) + [right]
    return edges[column], edges[column + 1]


def _pdf_is_body_line(line: _PdfLine, gutters: list, left: float, right: float) -> bool:
    lo, hi = _pdf_segment(gutters, left, right, _pdf_column_of(line.x0, line.x1, gutters))
    return hi > lo and (line.x1 - line.x0) >= (hi - lo) * _PDF_BODY_LINE_FILL


def _pdf_line_box(line: _PdfLine) -> tuple:
    return (line.x0, line.y0, line.x1, line.y1)


def _pdf_is_prose(line: _PdfLine) -> bool:
    """문장 줄인가 — 충분히 길고 글자(한글 · 로마자)가 대부분이다. 그래프 축 눈금
    (`275 280 285 …`)이나 범례는 길어도 문장이 아니다."""
    text = re.sub(r"\s+", "", line.text)
    if len(line.text) < _PDF_PROSE_CHARS or not text:
        return False
    letters = sum(1 for char in text if char.isalpha())
    return letters >= len(text) * _PDF_PROSE_LETTERS


def _pdf_object_regions(page, lines: list, tables: list, gutters: list) -> list:
    """본래 pdf 의 그림 영역 — 내장 이미지 · 도형 묶음. 표 · 글상자 · 쪽 테두리는 뺀다.

    글상자 판정은 **합치기 전에 상자마다** 한다. 쪽 테두리 도형과 그 안의 그래프 이미지를
    먼저 합치면 쪽 전체가 한 상자가 되고, 그 상자가 본문을 품어 글상자로 빠지면서 그래프까지
    함께 사라진다.
    """
    area = page.rect.width * page.rect.height
    boxes = []
    for info in page.get_image_info():
        if min(int(info.get("width", 0)), int(info.get("height", 0))) < _PDF_FIGURE_MIN_PIXELS:
            continue
        boxes.append(tuple(info["bbox"]))
    clusterer = getattr(page, "cluster_drawings", None)
    if clusterer is not None:
        try:
            clusters = [tuple(rect) for rect in clusterer()]
        except Exception:  # noqa: BLE001 - 도형 묶기는 덤이다. 실패해도 본문 · 표는 그대로 간다
            clusters = []
        boxes.extend(
            box for box in clusters
            if (box[2] - box[0]) * (box[3] - box[1]) < area * _PDF_FRAME_AREA
        )
    boxes = [box for box in boxes if _pdf_box_ok(box, area)]
    boxes = [
        box for box in boxes
        if not any(_overlap_ratio(box, table_box) >= _IN_TABLE_RATIO for table_box, _ in tables)
    ]
    if lines:
        left, right = _pdf_extent(lines)

        def text_box(box) -> bool:
            prose = [
                line for line in lines
                if _overlap_ratio(_pdf_line_box(line), box) >= _PDF_IN_FIGURE_RATIO
                and _pdf_is_body_line(line, gutters, left, right)
                and _pdf_is_prose(line)
            ]
            return len(prose) >= _PDF_TEXT_BOX_LINES  # 테두리 친 글상자다 — 글은 본문으로 읽는다

        boxes = [box for box in boxes if not text_box(box)]
    return _pdf_union(boxes)


def _pdf_is_caption(line: _PdfLine, gutters: list, left: float, right: float):
    """캡션 줄이면 `"figure"` · `"table"`, 아니면 `None`.

    단 폭을 채우는 줄은 캡션이 아니다 — 본문이 `〈그림 1) 은 …을 나타낸 것이다` 처럼
    그림을 가리키는 문장으로 시작하는 일이 흔하다.
    """
    text = line.text.strip()
    if _PDF_FIGURE_CAPTION_RE.match(text):
        kind = "figure"
    elif _PDF_TABLE_CAPTION_RE.match(text):
        kind = "table"
    else:
        return None
    if _pdf_is_body_line(line, gutters, left, right):
        return None
    return kind


def _pdf_caption_regions(page, lines: list, tables: list, gutters: list, taken: list) -> list:
    """스캔 pdf 의 그림 영역 — 캡션 위 · 아래로 본문 줄이 나올 때까지의 빈 자리.
    → `(상자, 종류)` 목록. 종류는 `"figure"` · `"table"` 이다.

    - 객체(이미지 · 도형)로 이미 찾은 그림 옆 캡션은 건너뛴다.
    - **표 캡션은 찾은 표가 같은 단에 있으면 영역을 만들지 않는다.** 캡션과 표 사이의
      빈 자리는 대개 `find_tables` 가 놓친 음영 머리행이다(`_pdf_table_image_box` 가 표
      이미지를 캡션까지 넓힌다).
    - 본문 줄 · 다른 캡션 · 이미 잡은 영역이 경계다. 위 · 아래 중 **더 높은 빈 자리**를
      고른다 — 한국 논문은 그림 캡션이 아래, 표 캡션이 위인 조판이 흔하지만 반대도 있다.
    """
    if not lines:
        return []
    height = page.rect.height
    left, right = _pdf_extent(lines)
    top_limit = height * _PDF_HEADER_BAND
    bottom_limit = height * (1 - _PDF_FOOTER_BAND)
    occupied = list(taken)
    captions = [(line, _pdf_is_caption(line, gutters, left, right)) for line in lines]
    captions = [(line, kind) for line, kind in captions if kind is not None]
    caption_ids = {id(line) for line, _ in captions}
    regions = []
    for caption, kind in sorted(captions, key=lambda item: item[0].y0):
        column = _pdf_column_of(caption.x0, caption.x1, gutters)
        centered = abs((caption.x0 + caption.x1) / 2 - (left + right) / 2) <= (right - left) * _PDF_CENTERED
        lo, hi = _pdf_segment(gutters, left, right, _PDF_WIDE if centered else column)
        if kind == "table" and any(box[0] < hi and lo < box[2] for box, _ in tables):
            continue
        near = any(
            box[0] < caption.x1 and caption.x0 < box[2]
            and (0 <= caption.y0 - box[3] <= _PDF_CAPTION_GAP or 0 <= box[1] - caption.y1 <= _PDF_CAPTION_GAP)
            for box in taken
        )
        if near:
            continue  # 객체로 찾은 그림의 캡션이다 — 캡션 영역끼리는 서로 경계일 뿐이다
        stoppers = [
            (line.y0, line.y1) for line in lines
            if line is not caption
            and line.x0 < hi and lo < line.x1
            and (id(line) in caption_ids or _pdf_is_body_line(line, gutters, left, right))
        ]
        stoppers += [
            (box[1], box[3]) for box in occupied + [box for box, _ in tables]
            if box[0] < hi and lo < box[2]
        ]
        above_top = max([y1 for _, y1 in stoppers if y1 <= caption.y0] + [top_limit])
        below_bottom = min([y0 for y0, _ in stoppers if y0 >= caption.y1] + [bottom_limit])
        above = (lo, above_top, hi, caption.y0)
        below = (lo, caption.y1, hi, below_bottom)
        best = max((above, below), key=lambda box: box[3] - box[1])
        if best[3] - best[1] < _PDF_CAPTION_REGION_MIN:
            continue
        prose = [
            line for line in lines
            if _pdf_is_prose(line)
            and _overlap_ratio(_pdf_line_box(line), best) >= _PDF_IN_FIGURE_RATIO
        ]
        if not gutters and len(prose) >= _PDF_TEXT_BOX_LINES:
            continue
        regions.append((best, kind))
        occupied.append(best)
    return regions


def _pdf_caption_of(box, lines: list, pattern) -> _PdfLine | None:
    """영역 바로 위 · 아래의 캡션 줄. 가까운 쪽."""
    best = None
    best_distance = None
    for line in lines:
        if not pattern.match(line.text.strip()):
            continue
        if not (line.x0 < box[2] and box[0] < line.x1):
            continue
        distance = min(abs(line.y0 - box[3]), abs(box[1] - line.y1))
        if distance <= _PDF_CAPTION_GAP and (best_distance is None or distance < best_distance):
            best, best_distance = line, distance
    return best


def _pdf_media_names(page_no: int, kind: str, counters: dict) -> tuple:
    """다음 이미지의 `(파일 이름, ref)`. 번호는 종류(`figure` · `table`)마다 문서 전체로 센다.

    `ref` 는 docling 표기(`#/pictures/N` · `#/tables/N`, 0-based)를 따른다.
    """
    counters[kind] += 1
    index = counters[kind]
    collection = "pictures" if kind == "figure" else "tables"
    return f"page{page_no + 1:03d}_{kind}{index:02d}.png", f"#/{collection}/{index - 1}"


def _pdf_render(page, box, media_dir: str | None, name: str, ref: str) -> tuple:
    """영역을 PNG 로 저장. → `(_PdfMedia,)` 또는 `()`(저장을 끈 경우 · 실패)."""
    if media_dir is None:
        return ()
    path = os.path.join(media_dir, name)
    try:
        os.makedirs(media_dir, exist_ok=True)
        clip = type(page.rect)(*box) & page.rect
        page.get_pixmap(clip=clip, dpi=_PDF_MEDIA_DPI).save(path)
    except Exception as exc:  # noqa: BLE001 - 이미지 하나 때문에 문서 적재를 세우지 않는다
        _log_warning(
            "pdf media render failed",
            event="pdf_media_failed",
            error_type=type(exc).__name__,
            id_ref=ref,
        )
        return ()
    return (_PdfMedia(name=name, path=path, ref=ref),)


def _pdf_figures(page, page_no: int, lines: list, tables: list, gutters: list,
                 media_dir: str | None, counters: dict) -> tuple:
    """한 쪽의 그림. → (그림 목록, 남은 본문 줄). 그림은 `(상자, 블록 글, media)` 다.

    캡션으로 잡은 **표** 영역(스캔 pdf 에서 `find_tables` 가 못 찾은 표)도 여기서 이미지로
    낸다 — 블록 글은 `[표] 캡션` 이고 격자는 없다.
    """
    scanned = _pdf_is_scanned(page)
    regions = []
    if not scanned:
        regions = [(box, "figure") for box in _pdf_object_regions(page, lines, tables, gutters)]
    regions += _pdf_caption_regions(page, lines, tables, gutters, [box for box, _ in regions])

    figures = []
    used: set = set()
    for box, kind in sorted(regions, key=lambda item: (item[0][1], item[0][0])):
        inside = [
            line for line in lines
            if id(line) not in used and _overlap_ratio(_pdf_line_box(line), box) >= _PDF_IN_FIGURE_RATIO
        ]
        pattern = _PDF_FIGURE_CAPTION_RE if kind == "figure" else _PDF_TABLE_CAPTION_RE
        caption = _pdf_caption_of(box, [line for line in lines if id(line) not in used], pattern)
        used.update(id(line) for line in inside)
        parts = [_PDF_FIGURE_TAG if kind == "figure" else _PDF_TABLE_TAG]
        if caption is not None:
            used.add(id(caption))
            parts.append(caption.text)
        # 그림 속 라벨(`총 장` · `연구처`)은 검색어가 된다. 스캔 쪽은 OCR 부스러기가 섞이지만
        # 버리면 조직도 · 흐름도의 이름이 통째로 사라진다 — 길이만 묶어 싣는다. 표 영역의 글은
        # 표 내용 자체라 자르지 않는다.
        label = " ".join(line.text for line in inside)
        if kind == "figure":
            label = label[:_PDF_FIGURE_LABEL_MAX]
        label = label.strip()
        if label:
            parts.append(label)
        media = _pdf_render(page, box, media_dir, *_pdf_media_names(page_no, kind, counters))
        figures.append((box, " ".join(parts), media))
    rest = [line for line in lines if id(line) not in used]
    return figures, rest


def _pdf_table_image_box(box, lines: list, gutters: list) -> tuple:
    """표 이미지 영역 — 바로 위 · 아래 캡션까지 넓힌다(사이에 본문 줄이 없을 때).

    `find_tables` 는 괘선으로 표를 찾아 **음영만 있고 괘선 없는 머리행**을 자주 놓친다.
    격자는 되돌릴 수 없지만 이미지에는 머리행이 들어가야 표를 읽을 수 있다.
    """
    if not lines:
        return box
    left, right = _pdf_extent(lines)
    x0, y0, x1, y1 = box
    for line in lines:
        if not (line.x0 < x1 and x0 < line.x1 and _PDF_TABLE_CAPTION_RE.match(line.text.strip())):
            continue
        if line.y1 <= box[1]:
            lo, hi = line.y1, box[1]
        elif line.y0 >= box[3]:
            lo, hi = box[3], line.y0
        else:
            continue
        between = [
            other for other in lines
            if other.x0 < x1 and x0 < other.x1 and other.y0 >= lo and other.y1 <= hi
            and _pdf_is_body_line(other, gutters, left, right)
        ]
        if not between:
            y0, y1 = min(y0, lo), max(y1, hi)
    return (x0, y0, x1, y1)


def _pdf_table_media(page, page_no: int, tables: list, lines: list, gutters: list,
                     media_dir: str | None, counters: dict) -> list:
    """표마다 이미지를 붙인다. → `(상자, html, media)` 목록. 격자 복원이 틀려도 원형이 남는다."""
    result = []
    for box, html_text in tables:
        media = _pdf_render(
            page, _pdf_table_image_box(box, lines, gutters), media_dir,
            *_pdf_media_names(page_no, "table", counters),
        )
        result.append((box, html_text, media))
    return result


def parse_pdf(file_path: str, media_dir: str | None = None) -> tuple:
    """pdf → (`Block` 목록, 페이지 수, 저장한 이미지 목록).

    블록의 `origin` 은 `_PdfSource` 들이다. `media_dir` 가 `None` 이면 이미지를 저장하지
    않는다(그림 영역 안 글자를 본문에서 빼는 것은 그대로 한다).
    """
    module = _pdf_module()
    with module.open(file_path) as pdf:
        page_count = pdf.page_count
        pages = []
        for page_no in range(page_count):
            page = pdf[page_no]
            all_lines, other = _pdf_page_lines(page, page_no)
            tables = []
            for table in _find_tables(page):
                if not _pdf_table_plausible(table, all_lines):
                    continue
                html_text = pdf_table_html(table)
                if html_text:
                    tables.append((tuple(table.bbox), html_text))
            lines = [
                line for line in all_lines
                if not any(_overlap_ratio(_pdf_line_box(line), box) >= _IN_TABLE_RATIO for box, _ in tables)
            ]
            pages.append((page.rect.height, lines, other, tables))

        running = _pdf_running_keys([(height, lines) for height, lines, _, _ in pages])
        bodies = []
        for height, lines, _, _ in pages:
            margin = _pdf_margin_ids(lines, height)
            bodies.append([line for line in lines if not _pdf_is_running(line, margin, running)])
        per_page = [_pdf_gutters(body) for body in bodies]
        document_gutters = _pdf_document_gutters(per_page)
        elements: list = []
        saved: list = []
        counters = {"figure": 0, "table": 0}
        multi_column = 0
        for page_no, (body, gutters, (_, _, other, tables)) in enumerate(zip(bodies, per_page, pages)):
            if not gutters and _pdf_gutters_fit(body, document_gutters):
                gutters = document_gutters
            multi_column += bool(gutters)
            body = _pdf_join_fragments(body, gutters)
            page = pdf[page_no]
            figures, body = _pdf_figures(page, page_no, body, tables, gutters, media_dir, counters)
            with_media = _pdf_table_media(page, page_no, tables, body, gutters, media_dir, counters)
            for _, _, media in figures + with_media:
                saved.extend(media)
            elements.extend(_pdf_order(page_no, body, with_media, figures, gutters))
            # 세로쓰기 · 기울어진 줄(여백 도장 등)은 단 흐름에 넣지 않고 그 페이지 끝에 따로 싣는다.
            for index, line in enumerate(other):
                elements.append(("line", replace(line, group=(page_no, _PDF_OTHER, index))))

    _log_info(
        "pdf layout resolved",
        event="pdf_layout",
        item_count=multi_column,
    )
    _log_info(
        "pdf media extracted",
        event="pdf_media",
        item_count=len(saved),
    )
    return _pdf_blocks(elements), page_count, saved


# ===========================================================================
# docx — zip 안의 WordprocessingML 을 lxml 로 직접 읽는다
# ===========================================================================
#
# hwpx 와 같은 방식이다(새 의존성 없음). 표는 `w:gridSpan`(가로)·`w:vMerge`(세로)로
# 병합을 되살리고, 자동 번호(`w:numPr`)는 `word/numbering.xml` 정의로 복원한다 —
# 규정 문서의 `①`·`1.`·`가.` 가 자동 번호면 본문 XML 에 글자가 없어서, 복원하지 않으면
# 항·호를 못 읽어 청크 경계가 달라진다.
#
# 한계: 스타일에서 물려받는 번호는 `basedOn` 사슬까지만 따라간다. 머리말·꼬리말·각주는
# 본문 흐름이 아니라 읽지 않는다. 변경 추적의 삭제분(`w:delText`)은 싣지 않는다.

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_DOCX_MAX_ENTRY_BYTES = 200 * 1024 * 1024  # zip 폭탄 방어


def _w(tag: str) -> str:
    return f"{{{_W_NS}}}{tag}"


def _w_val(node, tag: str, default: str = "") -> str:
    if node is None:
        return default
    child = node.find(_w(tag))
    if child is None:
        return default
    return child.get(_w("val"), default)


# hwpx 쪽 `_format_number` 와 서식 이름·인자 순서가 다르다. 같은 이름이면 뒤엣것이
# 앞엣것을 덮어 hwpx 자동 번호가 `DIGIT.` 로 나온다 — 그래서 `_docx_` 접두어다.
# 글자 표(가나다·자음·로마 숫자)는 hwpx 쪽 것을 같이 쓴다.
def _docx_format_number(fmt: str, number: int) -> str:
    if fmt in ("decimalEnclosedCircle", "decimalEnclosedCircleChinese") and 1 <= number <= 20:
        return chr(0x2460 + number - 1)  # ①..⑳
    if fmt == "ganada" and 1 <= number <= len(_HANGUL_SYLLABLES):
        return _HANGUL_SYLLABLES[number - 1]
    if fmt == "chosung" and 1 <= number <= len(_HANGUL_JAMO):
        return _HANGUL_JAMO[number - 1]
    if fmt == "upperRoman":
        return _roman(number).upper()
    if fmt == "lowerRoman":
        return _roman(number)
    if fmt in ("upperLetter", "lowerLetter") and number >= 1:
        letter = chr(ord("A") + (number - 1) % 26)
        return letter if fmt == "upperLetter" else letter.lower()
    # 정의를 모르는 형식은 숫자로 낸다 — 비우면 그 자리가 사라진다.
    return str(number)


class _DocxNumbering:
    """`word/numbering.xml` 정의 + 문서 순서대로 진행하는 카운터."""

    def __init__(self, numbering_xml: bytes, styles_xml: bytes) -> None:
        self._levels: dict = {}      # abstractNumId → {ilvl: (fmt, lvlText, start)}
        self._num_to_abs: dict = {}  # numId → abstractNumId
        self._counters: dict = {}    # abstractNumId → {ilvl: 현재 값}
        self._style_num: dict = {}   # styleId → (numId, ilvl)
        self._style_based: dict = {}  # styleId → basedOn
        if numbering_xml:
            root = etree.fromstring(numbering_xml)
            for abstract in root.findall(_w("abstractNum")):
                levels = {}
                for lvl in abstract.findall(_w("lvl")):
                    ilvl = int(lvl.get(_w("ilvl"), "0") or 0)
                    start = int(_w_val(lvl, "start", "1") or 1)
                    levels[ilvl] = (_w_val(lvl, "numFmt", "decimal"), _w_val(lvl, "lvlText", ""), start)
                self._levels[abstract.get(_w("abstractNumId"))] = levels
            for num in root.findall(_w("num")):
                self._num_to_abs[num.get(_w("numId"))] = _w_val(num, "abstractNumId")
        if styles_xml:
            root = etree.fromstring(styles_xml)
            for style in root.findall(_w("style")):
                style_id = style.get(_w("styleId"))
                based = _w_val(style, "basedOn")
                if based:
                    self._style_based[style_id] = based
                num_pr = style.find(f"{_w('pPr')}/{_w('numPr')}")
                if num_pr is not None:
                    self._style_num[style_id] = (
                        _w_val(num_pr, "numId"), int(_w_val(num_pr, "ilvl", "0") or 0)
                    )

    def _style_numbering(self, style_id: str):
        seen = set()
        while style_id and style_id not in seen:
            seen.add(style_id)
            if style_id in self._style_num:
                return self._style_num[style_id]
            style_id = self._style_based.get(style_id, "")
        return None

    def label(self, paragraph) -> str:
        """이 문단의 자동 번호 표기. 번호가 없으면 빈 문자열. **호출 순서가 곧 문서 순서다.**"""
        ppr = paragraph.find(_w("pPr"))
        num_pr = ppr.find(_w("numPr")) if ppr is not None else None
        if num_pr is not None:
            num_id, ilvl = _w_val(num_pr, "numId"), int(_w_val(num_pr, "ilvl", "0") or 0)
        else:
            found = self._style_numbering(_w_val(ppr, "pStyle")) if ppr is not None else None
            if found is None:
                return ""
            num_id, ilvl = found
        if not num_id or num_id == "0":  # numId 0 은 "번호 없음"
            return ""
        abstract = self._num_to_abs.get(num_id)
        levels = self._levels.get(abstract)
        if not levels or ilvl not in levels:
            return ""
        counters = self._counters.setdefault(abstract, {})
        fmt, text, start = levels[ilvl]
        counters[ilvl] = counters.get(ilvl, start - 1) + 1
        for deeper in [key for key in counters if key > ilvl]:
            del counters[deeper]  # 윗 단계가 진행하면 아랫 단계는 처음부터 다시 센다
        if fmt == "bullet":
            return "-"
        if fmt == "none":
            return ""

        def fill(match) -> str:
            level = int(match.group(1)) - 1
            if level not in levels:
                return ""
            level_fmt, _, level_start = levels[level]
            return _docx_format_number(level_fmt, counters.get(level, level_start))

        return re.sub(r"%(\d)", fill, text).strip()


def _docx_text(node) -> str:
    """문단(또는 셀) 안 글자를 문서 순서대로. 탭은 `\\t`, 줄바꿈은 `\\n`."""
    parts = []
    for element in node.iter(_w("t"), _w("tab"), _w("br"), _w("cr")):
        if element.tag == _w("t"):
            parts.append(element.text or "")
        elif element.tag == _w("tab"):
            parts.append("\t")
        else:
            parts.append("\n")
    return "".join(parts)


def _docx_cell_text(tc, numbering: _DocxNumbering) -> str:
    """셀 안 문단을 줄바꿈으로 잇는다. 셀 안 중첩 표는 행을 ` | ` 로 펴서 글자로 싣는다."""
    lines = []
    for child in tc:
        if child.tag == _w("p"):
            label = numbering.label(child)
            text = _docx_text(child).strip()
            if label or text:
                lines.append(f"{label} {text}".strip())
        elif child.tag == _w("tbl"):
            for tr in child.iter(_w("tr")):
                cells = [_docx_text(cell).strip() for cell in tr.findall(_w("tc"))]
                if any(cells):
                    lines.append(" | ".join(cells))
        elif child.tag == _w("sdt"):
            content = child.find(_w("sdtContent"))
            if content is not None:
                inner = _docx_cell_text(content, numbering)
                if inner:
                    lines.append(inner)
    return "\n".join(lines)


def _docx_table_html(tbl, numbering: _DocxNumbering) -> str:
    """`w:tbl` → HTML 표. `gridSpan` 은 colspan, `vMerge restart…continue` 는 rowspan."""
    grid = []  # 행마다 [(열, colspan, vmerge, text)]
    for tr in tbl.findall(_w("tr")):
        col = 0
        row = []
        for tc in tr.findall(_w("tc")):
            tc_pr = tc.find(_w("tcPr"))
            span = int(_w_val(tc_pr, "gridSpan", "1") or 1)
            vmerge_node = tc_pr.find(_w("vMerge")) if tc_pr is not None else None
            if vmerge_node is None:
                vmerge = ""
            else:
                # 값 없이 `<w:vMerge/>` 만 있으면 "위 칸에 이어진다" 이다.
                vmerge = vmerge_node.get(_w("val"), "continue")
            row.append((col, span, vmerge, _docx_cell_text(tc, numbering)))
            col += span
        grid.append(row)

    rows = []
    for r, row in enumerate(grid):
        tag = "th" if r == 0 else "td"
        rendered = []
        for col, span, vmerge, text in row:
            if vmerge == "continue":
                continue  # 위 앵커가 덮는 자리 — 칸을 내지 않는다
            rowspan = 1
            if vmerge == "restart":
                for below in grid[r + 1:]:
                    if any(c == col and v == "continue" for c, _, v, _ in below):
                        rowspan += 1
                    else:
                        break
            rendered.append(_cell_tag(tag, text, rowspan, span))
        if rendered:
            rows.append("<tr>" + "".join(rendered) + "</tr>")
    return _join_table(rows)


def _docx_body_blocks(container, numbering: _DocxNumbering, blocks: list) -> None:
    for child in container:
        if child.tag == _w("p"):
            label = numbering.label(child)
            text = _docx_text(child)
            lines = [line.strip() for line in text.split("\n")]
            lines = [line for line in lines if line]
            if label:
                if lines:
                    lines[0] = f"{label} {lines[0]}"
                else:
                    lines = [label]
            # 줄 단위로 넣는다 — 조 표기를 줄 머리에서 읽는다(pdf 와 같은 이유).
            for line in lines:
                blocks.append(Block(kind="paragraph", text=line, section=0))
        elif child.tag == _w("tbl"):
            html_text = _docx_table_html(child, numbering)
            if html_text:
                blocks.append(Block(kind="table", text=html_text, section=0))
        elif child.tag == _w("sdt"):
            content = child.find(_w("sdtContent"))
            if content is not None:
                _docx_body_blocks(content, numbering, blocks)


def _docx_read(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return b""
    if info.file_size > _DOCX_MAX_ENTRY_BYTES:
        raise PreprocessError(f"docx 내부 파일이 너무 큽니다: {name}")
    return archive.read(name)


def parse_docx(data: bytes) -> list:
    """docx 바이트 → `Block` 목록."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PreprocessError("docx 파일이 손상되었거나 docx 가 아닙니다.") from exc
    with archive:
        document_xml = _docx_read(archive, "word/document.xml")
        if not document_xml:
            raise PreprocessError("docx 본문(word/document.xml)을 찾지 못했습니다.")
        numbering = _DocxNumbering(
            _docx_read(archive, "word/numbering.xml"), _docx_read(archive, "word/styles.xml")
        )
    try:
        root = etree.fromstring(document_xml)
    except etree.XMLSyntaxError as exc:
        raise PreprocessError("docx 본문 XML 을 읽지 못했습니다.") from exc
    body = root.find(_w("body"))
    blocks: list = []
    if body is not None:
        _docx_body_blocks(body, numbering, blocks)
    return blocks


# ===========================================================================
# 페이지 필드
# ===========================================================================


def _override_page_fields(records: list, chunks: list, page_count: int, basis: str) -> None:
    """hwpx 는 `to_records` 가 구역을 페이지 자리에 넣는다. pdf 는 **실제 페이지**로,
    docx 는 렌더링 전 페이지가 없어 **문서 하나**로 덮는다. 1-based 페이지 · 0-based 순번 —
    벤더 pdf 경로와 같은 기준이다. 여러 페이지를 걸친 청크는 시작 페이지에 달린다."""
    starts = [min(map(_origin_page, chunk.origin)) if chunk.origin else 0 for chunk in chunks]
    ends = [max(map(_origin_page, chunk.origin)) if chunk.origin else 0 for chunk in chunks]
    per_page: dict = {}
    for page in starts:
        per_page[page] = per_page.get(page, 0) + 1
    seen: dict = {}
    for record, start, end in zip(records, starts, ends):
        order = seen.get(start, 0)
        seen[start] = order + 1
        record.update({
            "i_page": start + 1,
            "e_page": end + 1,
            "n_page": max(page_count, end + 1),
            "i_chunk_on_page": order,
            "n_chunk_of_page": per_page[start],
            "page_basis": basis,
        })
        # 구역이 없는 형식이다 — 0 을 실으면 "0번 구역" 으로 읽힌다.
        record.pop("i_section", None)
        record.pop("n_section", None)


# ===========================================================================
# GenOS 등록 단위 진입점
# ===========================================================================


class DocumentProcessor:
    """hwpx · docx · pdf 전처리기(area 05).

    인자 없이 생성되고 `__call__` 은 비동기이며 `text` 키를 가진 dict 목록을 돌려주거나
    예외를 던진다. 등록 화면에서 받을 확장자를 `hwpx`·`docx`·`pdf` 로 건다.
    """

    SUPPORTED_EXTENSIONS = (".hwpx", ".docx", ".pdf")

    def __init__(self, config_path: str | None = None) -> None:
        # 다른 전처리기와 생성자 시그니처를 맞추려고 받아 둔다. 조정 값은 전부 kwargs 다.
        self._config_path = config_path

    async def __call__(self, request: Any, file_path: str, **kwargs: Any) -> list:
        start = time.monotonic()
        try:
            records, media = self._process(file_path, **kwargs)
        except PreprocessError as exc:
            _log_warning(
                "preprocessing rejected input",
                event="preprocess_failed",
                error_code="05-00020003",
                error_type=type(exc).__name__,
            )
            raise
        except Exception as exc:
            # 예상 못한 실패도 예외로 올린다 — 삼키면 빈 결과로 적재 성공한 것처럼 보인다.
            _log_warning(
                "preprocessing failed unexpectedly",
                event="preprocess_failed",
                error_code="05-00020003",
                error_type=type(exc).__name__,
            )
            raise PreprocessError(f"문서 처리 중 예기치 못한 오류가 발생했습니다: {exc}") from exc
        await self._upload_media(request, media)
        _log_info(
            "document preprocessed",
            event="preprocess_done",
            item_count=len(records),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return records

    @staticmethod
    async def _upload_media(request: Any, media: list) -> None:
        """레코드가 가리키는 이미지를 올린다. 벤더와 같은 함수 · 같은 인자(`[{path, name}]`)다.

        실패는 삼키지 않는다 — 올라가지 않은 이미지를 `media_files` 가 가리키면 화면에서
        깨진 링크로만 드러난다. 업로드 함수가 없는 환경(로컬 · 점검)에서는 `{파일명}/` 폴더에
        남긴 사실을 로그로 남긴다.
        """
        if not media:
            return
        if upload_files is None:
            _log_info("pdf media kept locally", event="pdf_media_local", item_count=len(media))
            return
        await upload_files([{"path": item.path, "name": item.name} for item in media], request=request)

    def _read_blocks(self, file_path: str, ext: str, base_name: str, media_dir: str | None) -> tuple:
        """(블록, 구역 수, 페이지 수, 페이지 기준). 페이지 기준이 None 이면 `to_records` 값
        그대로. 올릴 이미지는 저장 목록이 아니라 청크의 `origin` 에서 다시 모은다(`_process`)."""
        if ext == ".pdf":
            blocks, page_count, _saved = parse_pdf(file_path, media_dir)
            return blocks, 0, page_count, _PAGE_BASIS_PAGE
        try:
            with open(file_path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            raise PreprocessError(f"파일을 읽지 못했습니다: {base_name}") from exc
        if not data:
            raise PreprocessError(f"빈 파일입니다: {base_name}")
        if ext == ".docx":
            return parse_docx(data), 0, 1, _PAGE_BASIS_DOCUMENT
        document = parse(data)
        return list(document.blocks), document.section_count, 0, None

    def _process(self, file_path: str, **kwargs: Any) -> tuple:
        """(레코드, 레코드가 가리키는 이미지)."""
        base_name = os.path.basename(file_path)
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            # 확장자 매핑을 잘못 건 것이 드러나야 한다 — 빈 결과로 넘기지 않는다.
            raise PreprocessError(f"지원하지 않는 확장자입니다: '{ext or base_name}'")
        if not os.path.exists(file_path):
            raise PreprocessError(f"파일을 찾지 못했습니다: {base_name}")

        save_images = _bool_kwarg(kwargs.get("save_images"), True, "save_images")
        media_dir = _pdf_media_dir(file_path) if save_images else None
        blocks, section_count, page_count, basis = self._read_blocks(
            file_path, ext, base_name, media_dir
        )
        if not blocks:
            # 빈 결과로 적재 성공하면 그 문서가 검색에서 조용히 사라진다.
            raise PreprocessError(
                f"본문 글자를 찾지 못했습니다(스캔 pdf 이거나 빈 문서): {base_name}"
            )

        mode = str(kwargs.get("outline_mode") or _OUTLINE_AUTO).strip().lower()
        options = ChunkOptions(
            max_chars=_int_kwarg(kwargs.get("chunk_size"), _DEFAULT_MAX_CHARS, "chunk_size"),
            overlap_chars=_int_kwarg(
                kwargs.get("chunk_overlap"), _DEFAULT_OVERLAP_CHARS, "chunk_overlap"
            ),
            # 기본값 5(조)는 조문 사다리 전용이다. 공문서 사다리에 쓰면 항목마다 끊긴다.
            outline_break_level=(
                _DOC_BREAK_LEVEL if mode == _OUTLINE_DOCUMENT else _LEVEL_ARTICLE
            ),
        )
        chunks = chunk_blocks(annotate_outline(blocks, mode), options)
        if not chunks:
            raise PreprocessError(f"청크를 만들지 못했습니다: {base_name}")

        extra = kwargs.get("extra_metadata")
        records = to_records(
            chunks,
            file_name=kwargs.get("file_name") or base_name,
            file_path=file_path,
            section_count=section_count,
            extra=extra if isinstance(extra, dict) else None,
        )
        if basis is not None:
            _override_page_fields(records, chunks, page_count, basis)
        # 올리는 것은 **레코드가 가리키는 이미지만**이다. 저장했지만 어느 청크에도 안 실린
        # 이미지는 없어야 정상이고, 있어도 가리키는 곳이 없으니 올릴 이유가 없다.
        referenced: dict = {}
        for record, chunk in zip(records, chunks):
            media = _chunk_media(chunk)
            record["media_files"] = _media_files_json(media)
            for item in media:
                referenced.setdefault(item.name, item)
        for record in records:
            if not record.get("text"):
                raise PreprocessError("빈 텍스트 청크가 생성되었습니다(내부 오류).")
        _check_record_types(records)
        _log_info(
            "document chunked",
            event="preprocess_chunked",
            status=ext.lstrip("."),
            item_count=sum(1 for block in blocks if block.is_table),
        )
        return records, list(referenced.values())
