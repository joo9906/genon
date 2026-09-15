"""hwpx 파싱 전용 전처리기 — **청킹하지 않는다** (area 05, 2026-09-07 신규).

## 무엇이 다른가

`final_preprocessor.py` 는 **적재(검색)** 용이다. 조문 머리말(`제2장 총칙 > 제5조(목적)`)·
표 조각 머리말(`(표 1/16)` + 머리행 반복)·겹침·짧은 청크 병합이 본문에 들어간다 — 그
값들이 **임베딩되는 문자열에 있어야** 검색에 걸리므로 그 경로에서는 옳다.

이 파일은 **질의 시 첨부** 전용이다. 하는 일은 셋뿐이다:

1. hwpx 를 읽어 문단·표를 판정한다 (파싱 코어는 `final_preprocessor.py` PART 2 와 같다)
2. 문서 **전체**를 한 덩어리로 낸다 — 조각은 플랫폼 레코드 크기 상한 때문에만 자른다
3. `text` 키를 든 레코드로 돌려준다 (§F 계약)

즉 **네 기능(FAQ·번역·글다듬이·006 자동 채움)이 원문을 그대로 받는다.** 그 셋은 받은
텍스트를 LLM 에 직접 던지므로 검색용 가공이 섞이면:

- 번역은 원문에 없던 머리말을 **번역해서 결과물에 싣는다**
- FAQ 는 그 머리말을 원문 문장으로 보고 근거 대조를 한다
- 006 자동 채움은 그것을 문서 내용으로 읽는다

셋 다 오류가 아니라 **결과물의 내용으로만** 드러난다.

## MCP 로 파싱하지 않는다 (이 파일이 생긴 이유)

그전에는 워크플로우가 hwpx 를 **MCP `genon_hwpx_text.hwpx_to_markdown`** 으로 파싱했다.
그 경로에는 문제가 셋 있었다:

- **닿지 않을 수 있다.** 2026-09-07 에 그 호출이 전부 `406` 이었고(Accept 헤더), 실패는
  조용히 전처리기 산출물로 폴백해서 **"표가 깨진 결과" 로만** 드러났다.
- **업로드 원본 경로를 전제한다.** 캔버스 변수(`faq_hwpx_path`·`translate_hwpx_path`)가
  공유 볼륨 경로를 담아 준다는 가정인데, 플랫폼이 그것을 채워 주는지 미확인이다.
- **사본이 하나 더다.** 같은 파싱 규칙이 MCP·번역·FAQ·006·전처리기 다섯 벌이었다.

첨부 문서는 **어차피 전처리기를 지나 `genosUploaded` 로 온다.** 그 산출물을 그대로 쓰면
파싱이 한 번만 일어나고, MCP 왕복도 원본 경로 가정도 사라진다.

**그래서 그 도구 파일은 지웠다** (2026-09-07). 호출부가 0건인 파싱 사본은 갈리기만 하고,
갈린 사실은 오류가 아니라 결과물의 표 모양으로만 드러난다. 되살릴 코드는
`git show HEAD:onprem/mcp/genon_hwpx_text.py` — 다만 그때는 **여기서 옮겨 적는다**
(정본은 `final_preprocessor.py` PART 2 다).

## 등록 (`docs/SERVING_REGISTRY.md` 와 같은 절차)

- **파일 하나가 등록 단위다.** 이 파일만 올리거나 타이핑한다 (1,500줄 남짓 —
  `final_preprocessor.py` 의 청킹·위계·벤더 절반이 전부 빠졌다).
- **받을 확장자는 `hwpx` 만 건다.** 나머지(pdf·docx·txt…)는 **사이트의 기존 첨부용
  등록이 이미 맡는다** — 그쪽을 이 파일로 대체하지 않는다. 벤더 스택(docling·langchain)
  절반을 여기 들고 오면 파일이 네 배가 되고, 그 절반은 GenOS 가 릴리스마다 갱신한다.
- 적재(검색)용 등록은 `final_preprocessor.py` 그대로 둔다. **둘은 다른 등록이다.**

## 계약: 이어붙이면 원문이다

    "\\n\\n".join(r["text"] for r in records) == parse(bytes).to_markdown()

번역이 문서 전체를 쥐어야 성립한다(`markdown_units` 가 스켈레톤을 문서 단위로 만들고
되조립한다). 이 등식이 깨지면 번역 산출물의 구조가 **조용히** 어긋난다. 그래서 블록을
쪼개지 않는다 — 표 하나가 상한을 넘어도 통째로 둔다(쪼개면 그 조각이 표로 보이지 않는다).

## 파싱 코어는 사본이다 (여섯 벌째)

`_own_text`·`_render_table`·`_Markers`·`parse` 는 `final_preprocessor.py` PART 2 와
**같은 코드**다. 배포 단위 간 import 가 금지라(§D.3) 사본이고, 갈리면 같은 문서가 적재
경로와 첨부 경로에서 **다른 텍스트**가 된다 — 오류로는 드러나지 않는다.
`onprem/test/check_table_grid.py` 가 여섯 벌의 출력을 대조한다.

**표는 언제나 한 줄 HTML 이다** — 검색 결과가 프롬프트로 조립될 때 개행이 뭉개져
마크다운 표가 통째로 무너진다(`_render_table` 이 이유를 적는다). 첨부 경로도 같은
조립을 지나므로 규칙을 그대로 둔다.

## 로컬에서 확인하기

    python -c "import asyncio, only_me; \\
        print(asyncio.run(only_me.DocumentProcessor()(None, 'data/파워.hwpx'))[0]['text'][:200])"
"""

import html as _html
import io
import logging
import os
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from lxml import etree

_log = logging.getLogger(__name__)

# 3.8절 기록 허용 필드. **선언만 해 두고 강제하지 않으면 없는 것과 같다** — 2026-08-30
# 까지 이 상수는 참조가 0건이었고, 일곱 개 호출부가 `extra={...}` 를 손으로 적고 있었다.
# 지금은 `_emit_log` 하나를 지나므로 새 필드를 무심코 실을 자리가 없다 (다른 여덟 단위의
# `logging_utils` 와 같은 모양이다).
#
# **`id_ref` 가 여기 있는 것은 의도다.** 문서 안 번호 정의를 가리키는 값이지 본문 내용이
# 아니고, 없으면 "폴백을 밟았다" 는 사실은 남는데 **어느 정의에서인지가 사라져** 진단이
# 안 된다 (번역·FAQ 사본은 화이트리스트가 달라 같은 값을 `resource_id` 로 싣는다 —
# 루트 `CLAUDE.md` "그 층을 사본 넷으로 옮겼다" 절).
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
    _log.log(level, message, extra=extra)


def _log_info(message: str, *, event: str, **fields: Any) -> None:
    _emit_log(logging.INFO, message, event=event, **fields)


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
# 예전에는 "본문 흐름이 아니다" 는 이유로 **중첩 문단을 통째로 버렸는데**, 버린 것이
# 곧 문서에 보이는 글자라 적재된 문서에서 그만큼이 조용히 사라졌다 — 표가 깨지는 것과
# 달리 **없어진 자리가 아무 흔적도 남기지 않아** 검색에서 안 나올 때까지 드러나지 않는다.
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
# 목록으로 판정하면 여기 안 적힌 상자(덧말 등 hwpx 가 나중에 늘릴 수 있는 것)가 예전처럼
# 조용히 버려지고, 그 손실은 이름을 빠뜨렸다는 사실을 아무도 모르는 채로 남는다.
# hwpx 에서 문단을 담는 것은 예외 없이 **`hp:subList` 를 직접 자식으로 두는 원소**다
# (표 셀도 그렇다). 그 모양을 기준으로 본다.
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

# <hp:t> 안의 \n 은 문단 분리가 아니다 — 그대로 두면 마크다운에서 문단이 갈린다
_NEWLINE_REPLACEMENT = " "
# 셀 안 줄바꿈은 표 한 칸을 여러 줄로 만든다 — 표에서만 <br> 로 바꾼다
_CELL_LINE_BREAK = "<br>"

# 문장 경계 — **구분자를 소비하지 않는 lookbehind 만** 쓴다. `(?<=[다요])\.\s+` 를
# 함께 뒀다가 테스트에 걸렸다: 그쪽은 마침표를 소비해 "완료하였습니다. 본 사업은" 이
# "완료하였습니다 본 사업은" 으로 바뀌었다 — 청킹이 본문 글자를 지운 것이다.
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

# ---------------------------------------------------------------------------
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


class HwpxParseError(ValueError):
    """hwpx 해석/처리 실패 — ZIP·XML 손상, 미지원 확장자, 빈 문서 포함.

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다(문서 원문을
    담지 않는다). `docs/GENOS_RULES.md` §A.4 — 전처리기는 오류 dict 를 반환하지 않고
    이 예외를 던진다.
    """


# ---------------------------------------------------------------------------
# 파싱 — hwpx → 구조 블록. **표 규칙의 정본**
#
# 마크다운 한 덩어리로 뭉치지 않는 이유는 청킹이 블록 경계를 알아야 하기 때문이다 —
# 표 한가운데를 자르면 머리행을 잃어 그 청크가 통째로 쓸모없어진다.
# ---------------------------------------------------------------------------


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
        raise HwpxParseError("hwpx 파일이 아니거나 손상된 파일입니다.") from exc


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
        raise HwpxParseError("hwpx 본문 XML 을 해석하지 못했습니다.") from exc


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
    들어가고, **그 뒤에 오는 글자는 자식의 `tail`** 에 담긴다. `node.text` 만 읽던 예전
    코드는 조판 문자가 한 번이라도 나오면 **그 뒤 글자를 전부 잃었다** — 남은 앞부분이
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


# ---------------------------------------------------------------------------
# 자동 번호·글머리표 — **문서에 보이는데 본문 XML 에는 없는 글자**
#
# 한/글의 개요 번호(`1.`, `가.`, `1)`)와 글머리표(`-`, `●`)는 문단 텍스트가 아니라
# **문단 모양(`hh:paraPr > hh:heading`)이 가리키는 번호 매기기 정의**에서 나온다.
# 그래서 `hp:t` 만 읽으면 그 표시가 통째로 사라진다 — 화면에서
#h
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
# **`@idRef` 는 id 로도 인덱스로도 온다** (2026-08-20). 실물 한/글은 개요 번호 문단에
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
            except HwpxParseError:
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

    폴백이 필요한 이유: 그 키가 없을 때 예전 코드는 표시 문자열을 못 찾아 빈 문자열을
    돌려줬고, 그러면 **개요 번호가 붙은 문단 전부에서 번호만 조용히 사라진다** — 정의는
    찾았고 `_resolve` 폴백도 밟지 않으므로 로그에도 흔적이 남지 않는다.

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

    예전에는 셀(`hp:tc`)만 봤다. 그러면 셀 안 글상자·캡션·각주의 문단이 "이 셀 것이
    아니다" 로 떨어져 **어디에서도 안 나온다** — 셀 렌더링은 자기 것이 아니라고 건너뛰고,
    본문 렌더링은 중첩 문단이라고 건너뛴다.
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

    ## 왜 마크다운을 안 쓰나 (2026-08-13 변경)

    예전에는 병합·중첩이 있는 표만 HTML 로 내고 나머지는 마크다운으로 냈다 — 잃을 게
    없는 표까지 바꾸면 토큰만 늘고 사람이 읽기 나쁘다는 이유였다. 실제 검색 결과를 받아
    보고 뒤집었다: **검색 결과가 LLM 에게 갈 때 개행이 공백으로 뭉개진다.**

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
    # **`_cell_parts` 결과로 확인하지 않는 이유**(2026-08-23): 그 함수는 자동 번호
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
        HwpxParseError: ZIP/XML 손상.
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


# ---------------------------------------------------------------------------
# 조문 위계 판정 — 블록 → 블록(+`outline_level`/`outline_path`)
#
# **왜 파싱과 갈라 두나.** hwpx XML 에는 "이 문단이 제5조다" 라는 정보가 없다. 조문
# 위계는 텍스트 표기에서 읽어내는 별개의 층이고, 껐을 때 파싱 결과가 그대로여야
# 위계 규칙을 고쳐도 표·문단 경계는 흔들리지 않는다.
#
# **왜 레이아웃 모델을 쓰지 않나.** 지능형 전처리기는 PDF 로 변환한 뒤 레이아웃(비전)
# 모델이 매긴 `SECTION_HEADER`/`TITLE` 라벨로 구조를 잡는데, 그 라벨은 깊이가 0/1 로
# 평탄화돼 편–장–조–항 4단 위계를 표현하지 못한다. 이 경로는 hwpx 를 직접 읽어 문단
# 텍스트가 그대로 있으므로 표기에서 위계를 바로 읽을 수 있다.
# ---------------------------------------------------------------------------




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




# 블록 사이 구분자. **`HwpxDocument.to_markdown` 과 같은 값이어야 한다** — 다르면
# `split_blocks_raw` 의 무손실 계약(이어붙이면 원문)이 그 자리에서 깨진다.
_BLOCK_SEP = "\n\n"

# raw 모드 조각 상한. **기능이 소비하는 단위가 아니다** — 네 기능은 이 조각을 이어붙인 뒤
# 자기 예산으로 다시 자른다(FAQ 24,000 · 글다듬이 6,000 · 006 12,000 · 번역은 안 자른다).
# 여기서 자르는 유일한 이유는 **플랫폼 레코드 크기 상한**이므로 넉넉히 둔다.
_DEFAULT_RAW_MAX_CHARS = 200_000


def split_blocks_raw(blocks: list, max_chars: int = _DEFAULT_RAW_MAX_CHARS) -> list:
    """블록 목록 → **길이로만** 자른 조각 (질의 시 첨부용, 2026-09-07).

    `chunk_blocks` 와 **다른 함수인 이유**는 그쪽이 검색을 위해 본문을 바꾸기 때문이다 —
    조문 머리말(`제2장 총칙 > 제5조(목적)`)·표 조각 머리말(`(표 1/16)` + 머리행 반복)·
    겹침·짧은 청크 병합이 전부 들어간다. 그 값들은 **임베딩되는 문자열에 있어야** 검색에
    걸리므로 적재 경로에서는 옳다.

    그런데 네 기능(FAQ·번역·글다듬이·006 자동 채움)은 **원문을 LLM 에 그대로 던진다.**
    거기에 검색용 가공이 섞이면:

    - 번역은 원문에 없던 머리말을 **번역해서 결과물에 싣는다**
    - FAQ 는 그 머리말을 원문 문장으로 보고 근거 대조를 한다
    - 006 자동 채움은 그것을 문서 내용으로 읽는다

    셋 다 오류가 아니라 **결과물의 내용으로만** 드러난다.

    ## 계약: 이어붙이면 원문과 같다

        _BLOCK_SEP.join(c.text for c in split_blocks_raw(blocks)) == doc.to_markdown()

    번역이 문서 전체를 쥐어야 하기 때문이다(`markdown_units` 가 스켈레톤을 문서 단위로
    만들고 되조립한다). 이 등식이 깨지면 번역 산출물의 구조가 조용히 어긋난다.
    그래서 **블록을 쪼개지 않는다** — 표 하나가 상한을 넘어도 통째로 둔다(쪼개면 그
    조각이 표로 보이지 않는다).

    Args:
        blocks: `parse()` 산출물. `annotate_outline` 을 지나지 **않은** 것을 준다 —
            위계 필드는 여기서 쓰지 않고, 지나도 결과는 같다.
        max_chars: 조각 하나의 상한. 1 미만이면 기본값으로 떨어진다.

    Returns:
        `Chunk` 목록. `to_records` 가 그대로 받는다.
    """
    if max_chars < 1:
        max_chars = _DEFAULT_RAW_MAX_CHARS

    chunks: list = []
    current: list = []
    current_len = 0
    section = 0

    def flush() -> None:
        nonlocal current, current_len
        if not current:
            return
        chunks.append(
            Chunk(text=_BLOCK_SEP.join(current), section=section, kind="paragraph")
        )
        current, current_len = [], 0

    for block in blocks:
        text = block.text
        # 블록 사이 구분자 두 글자를 예산에 넣는다 — 안 넣으면 이어붙인 길이가 상한을
        # 조금씩 넘고, 그 초과가 플랫폼 상한 바로 아래에서 문제가 된다.
        addition = len(text) + (2 if current else 0)
        if current and current_len + addition > max_chars:
            flush()
            addition = len(text)
        if section != block.section and not current:
            section = block.section
        current.append(text)
        current_len += addition
    flush()
    return chunks




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
# 페이지 관련 다섯은 2026-09-03 부터 **구역으로 채운다** — `None` 을 허용하지 않는다.
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
                raise HwpxParseError(
                    "레코드 필드 타입이 계약과 다릅니다(내부 오류): "
                    "%s=bool (레코드 %d)" % (key, index)
                )
            if not isinstance(value, allowed):
                raise HwpxParseError(
                    "레코드 필드 타입이 계약과 다릅니다(내부 오류): "
                    "%s=%s (레코드 %d)" % (key, type(value).__name__, index)
                )


def _page_fields(chunks: list, section_count: int) -> list:
    """청크별 페이지 필드. **구역(section)을 페이지 자리에 넣는다** (2026-09-03).

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
            # 옛 이름은 `table_part` 였는데, 그 이름으로는 UI 가 `표 {값}/{총}` 을 그대로
            # 찍어 **첫 조각이 "표 0/16" 이 되고 16/16 은 영영 안 나온다** — 본문과 레코드가
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


# ---------------------------------------------------------------------------
# GenOS 등록 단위 진입점
# ---------------------------------------------------------------------------


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




# ===========================================================================
# 진입점 — `DocumentProcessor` 이름은 GenOS 고정 계약이다
# ===========================================================================
SUPPORTED_EXTENSIONS = (".hwpx",)


# `document_text(hwpx_bytes)` 가 여기 있었다 — `parse(...).to_markdown()` 을 감싼
# 겉면이고 "로컬 확인·회귀 점검용" 이라고 적혀 있었는데 **호출부가 0건이었다.**
# `check_table_grid` 는 `parse()` 를 직접 부른다(블록 단위로 대조해야 하므로).
# 2026-09-08 에 지웠다 — 이관이 손 타이핑이라 안 쓰는 줄은 곧 비용이다.


def build_records(
    hwpx_bytes: bytes,
    *,
    file_name: str = "",
    file_path: str = "",
    max_chars: int = _DEFAULT_RAW_MAX_CHARS,
    extra: dict | None = None,
) -> list:
    """hwpx 바이트 → 레코드 목록. **조각은 길이로만** 자른다.

    `__call__` 과 갈라 둔 이유는 이 함수가 **`request` 를 요구하지 않기** 때문이다 —
    회귀 점검이 플랫폼 객체를 흉내내지 않고 이 경로를 그대로 태울 수 있다.
    """
    document = parse(hwpx_bytes)
    if not document.blocks:
        raise HwpxParseError(
            f"본문 내용을 찾지 못했습니다(빈 문서이거나 지원하지 않는 구조): {file_name}"
        )

    chunks = split_blocks_raw(document.blocks, max_chars)
    if not chunks:
        # 여기까지 오면 `split_blocks_raw` 의 불변식이 깨진 것이다 (블록이 있는데 조각이
        # 없다). 조용히 빈 목록을 내면 **첨부한 문서가 없는 것처럼** 흘러간다.
        raise HwpxParseError(f"조각을 만들지 못했습니다: {file_name}")

    records = to_records(
        chunks,
        file_name=file_name,
        file_path=file_path,
        section_count=document.section_count,
        extra=extra,
    )
    for record in records:
        if not record.get("text"):
            # §F: `text` 키는 필수이며 빈 문자열이면 안 된다.
            raise HwpxParseError("빈 텍스트 조각이 생성되었습니다(내부 오류).")
    _check_record_types(records)
    return records


class DocumentProcessor:
    """질의 시 첨부용 hwpx 파서. **인자 없이 생성 가능해야 한다** (§A.4).

    `final_preprocessor.DocumentProcessor` 와 **같은 이름이지만 다른 등록**이다. 한
    서버에 둘을 함께 올리지 않는다 — 올리면 나중에 로드된 것이 앞엣것을 덮고, 그 실패는
    "적재는 되는데 표가 깨진다"(또는 그 반대)로만 드러난다.
    """

    SUPPORTED_EXTENSIONS = SUPPORTED_EXTENSIONS

    async def __call__(self, request: Any, file_path: str, **kwargs: dict) -> list:
        """파일 하나를 파싱해 레코드 목록을 돌려준다.

        Args:
            request: 플랫폼이 넘기는 요청 객체. **이 파일은 쓰지 않는다** — 계약상
                받기만 한다(벤더 처리기는 여기서 사용자·권한을 읽는다).
            file_path: 업로드된 파일의 경로.
            kwargs: `file_name`(원본 파일명), `chunk_size`(조각 상한),
                `extra_metadata`(모든 레코드에 함께 실을 dict). 그 밖의 키는 **무시한다** —
                적재용 손잡이(`outline_mode`·`chunk_overlap`)를 여기 주면 아무 일도
                일어나지 않는 것이 맞다. 청킹을 하지 않는 것이 이 파일의 요점이다.

        Raises:
            HwpxParseError: 확장자·읽기·파싱 실패. **오류 dict 를 돌려주지 않는다** —
                적재/첨부 경로는 예외로 실패를 알린다(§A.4).
        """
        started = time.monotonic()
        base_name = os.path.basename(file_path)
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            # 등록 시 확장자를 잘못 걸었다는 뜻이다. 조용히 빈 목록을 내면 그 문서가
            # **첨부되지 않은 것처럼** 보인다.
            raise HwpxParseError(
                f"hwpx 전용 전처리기입니다 — 지원하지 않는 확장자입니다: '{ext or base_name}'"
            )

        try:
            with open(file_path, "rb") as fh:
                hwpx_bytes = fh.read()
        except OSError as exc:
            raise HwpxParseError(f"파일을 읽지 못했습니다: {base_name}") from exc

        if not hwpx_bytes:
            raise HwpxParseError(f"빈 파일입니다: {base_name}")

        extra = kwargs.get("extra_metadata")
        records = build_records(
            hwpx_bytes,
            file_name=str(kwargs.get("file_name") or base_name),
            file_path=file_path,
            max_chars=_int_kwarg(
                kwargs.get("chunk_size"), _DEFAULT_RAW_MAX_CHARS, "chunk_size"
            ),
            extra=extra if isinstance(extra, dict) else None,
        )

        # 파싱 품질을 남긴다 — 문단·표가 0개면 파서가 문서를 못 읽은 것이고, 그 상태로
        # 빈 결과가 정상처럼 흘러가면 안 된다. **본문은 남기지 않는다** (3.8절).
        _log_info(
            "첨부 문서 파싱 완료",
            event="attach_parsed",
            resource_id=base_name,
            item_count=len(records),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return records
