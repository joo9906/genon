"""`POST /chat` 요청 해석 — 젠포탈이 보내는 `{question, stream}` 을 FAQ 생성 입력으로 바꾼다.

젠포탈은 워크플로우 파이썬 스텝 없이 이 코드서빙을 직접 부른다. 화면이 고른 개수·제목을
따로 실을 칸이 없어서 **`question` 문자열 안에 옵션을 함께 싣는다.** 두 모양을 받는다
(번역 `/chat` 과 같은 규칙이다).

1. 머리말 줄 (권장)

   ```
   faq_count: 5
   title: 휴가 규정 FAQ

   FAQ 를 만들 본문 …
   ```

   - 구분자는 `:` 와 `=` 둘 다 받는다. 키는 대소문자를 가리지 않는다.
   - **맨 앞에서 아는 키가 이어지는 동안만** 머리말이다. 아는 키가 아닌 줄을 만나면
     그 줄부터 본문이다 — 본문 첫 줄이 `제1조: 목적` 이어도 먹히지 않는다.
   - 머리말 바로 뒤의 빈 줄 하나 또는 `---` 한 줄은 구분자로 보고 버린다.

2. JSON 문자열

   ```
   {"faq_count": 5, "text": "본문 …"}
   ```

   본문은 `text` → `markdown` → `body` → `question` 순으로 찾는다.

**최상위 키가 이긴다.** 프론트가 `faq_count` 를 payload 최상위에 직접 실으면 `question`
머리말보다 그 값을 쓴다. 둘 다 없으면 개수는 서빙 기본값(`FAQ_DEFAULT_COUNT`)이다 —
그 판정은 `generator.resolve_count` 한 곳에 있으므로 여기서 기본값을 따로 두지 않는다.

**원문은 첨부 문서다.** 우선순위는 최상위 `genosUploaded`(워크플로우 캔버스와 같은 이름) >
`question` 안 `[입력된 문서]` 표식 뒤 > 표식이 없을 때의 본문이다. 표식이 있으면 그 앞쪽은
머리말(옵션)만 읽고 사용자가 친 글은 원문에 넣지 않는다(워크플로우 스텝 1 이 첨부만 원문으로
삼던 것과 같은 규칙이다). 표식 뒤에 `<doc>` 태그가 있으면 태그 안만 원문이다.

**세션 id 는 최상위 키에서만 읽는다** (`socketIOClientId` → `sessionId` → `session_id`,
`genos_state` 안도 본다). 세션은 `POST /download` 옛 경로가 저장분을 찾는 키일 뿐이라 없어도
생성·`download_url` 은 그대로 나온다.

값 검증(개수 상한·0 개)은 여기서 하지 않는다 — `chat_api` 가 `resolve_max_count` 로 한다.
"""

import json
import re
from dataclasses import dataclass

# 옵션 이름 → 그 이름으로 받아들이는 키. 워크플로우 캔버스 변수 이름(`faq_*`)도 받는다 —
# 같은 화면이 스텝 경로와 이 경로를 오가도 키를 바꾸지 않아도 된다.
_OPTION_KEYS = {
    "count": ("faq_count", "count", "개수"),
    "max_count": ("faq_max_count", "max_count"),
    "title": ("faq_title", "title", "제목"),
}
_KEY_TO_OPTION = {
    alias.lower(): option for option, aliases in _OPTION_KEYS.items() for alias in aliases
}

_HEADER_LINE_RE = re.compile(r"^\s*([A-Za-z_가-힣]+)\s*[:=]\s*(.*?)\s*$")
_SEPARATOR_RE = re.compile(r"^\s*-{3,}\s*$")
_BODY_KEYS = ("text", "markdown", "body", "question")
_QUESTION_KEYS = ("question", "text", "message", "query")
_SESSION_KEYS = ("socketIOClientId", "sessionId", "session_id")
_DOC_TAG_RE = re.compile(r"<doc[^>]*>(.*?)</doc>", re.DOTALL)
_DOC_MARK = "[입력된 문서]"
_TRUE_VALUES = frozenset({"1", "true", "yes", "y", "on"})


@dataclass(frozen=True)
class ChatInput:
    source_text: str
    count: str
    max_count: str
    title: str
    session_id: str
    stream: bool
    # 원문을 어디서 얻었는지 — 로그로만 쓴다 (`uploaded` / `question`)
    source_kind: str


def parse_stream_flag(value) -> bool:
    """`stream` 은 불리언이 정상이지만 문자열 `"true"` 로 오는 배선도 받는다."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_VALUES
    return False


def _options_from_mapping(mapping: dict) -> dict:
    options: dict = {}
    for key, value in mapping.items():
        option = _KEY_TO_OPTION.get(str(key).strip().lower())
        if option and isinstance(value, (str, int, float)) and str(value).strip():
            options[option] = str(value).strip()
    return options


def _parse_json_question(question: str):
    """JSON 객체 문자열이면 (옵션, 본문). 아니면 None."""
    stripped = question.strip()
    if not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    body = ""
    for key in _BODY_KEYS:
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            body = value
            break
    return _options_from_mapping(parsed), body


def _parse_header_question(question: str) -> tuple:
    """맨 앞의 `키: 값` 줄을 옵션으로 떼고 나머지를 본문으로 돌려준다."""
    lines = question.splitlines()
    options: dict = {}
    index = 0
    while index < len(lines):
        match = _HEADER_LINE_RE.match(lines[index])
        if not match:
            break
        option = _KEY_TO_OPTION.get(match.group(1).lower())
        if option is None:
            break
        if match.group(2):
            options[option] = match.group(2)
        index += 1
    if options and index < len(lines) and (
        not lines[index].strip() or _SEPARATOR_RE.match(lines[index])
    ):
        index += 1
    return options, "\n".join(lines[index:])


def parse_question(question: str) -> tuple:
    """`question` 문자열 → (옵션 dict, 본문). 옵션이 없으면 문자열 전체가 본문이다."""
    if not question:
        return {}, ""
    parsed = _parse_json_question(question)
    if parsed is not None:
        return parsed
    return _parse_header_question(question)


def _question(payload: dict) -> str:
    for key in _QUESTION_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _uploaded(value) -> str:
    """최상위 `genosUploaded` — `<doc>` 태그가 있으면 태그 안만 모은다."""
    if not isinstance(value, str) or not value.strip():
        return ""
    docs = [m.strip() for m in _DOC_TAG_RE.findall(value) if m.strip()]
    return "\n\n".join(docs) if docs else value.strip()


def _session_id(payload: dict) -> str:
    state = payload.get("genos_state")
    state = state if isinstance(state, dict) else {}
    for key in _SESSION_KEYS:
        value = payload.get(key) or state.get(key)
        if value:
            return str(value)
    return ""


def split_document(question: str) -> tuple:
    """`question` → (사용자 글, 첨부 문서). 표식이 없으면 문서는 빈 문자열이다."""
    head, mark, tail = question.partition(_DOC_MARK)
    if not mark:
        return question, ""
    tail = tail.replace(_DOC_MARK, "")
    docs = [m.strip() for m in _DOC_TAG_RE.findall(tail) if m.strip()]
    if not docs:
        return head, tail.strip()
    rest = _DOC_TAG_RE.sub("", tail).strip()
    return "\n".join(part for part in (head.rstrip(), rest) if part), "\n\n".join(docs)


def parse_chat_payload(payload: dict) -> ChatInput:
    """요청 본문 전체를 해석한다. 우선순위는 최상위 키 > question 머리말."""
    user_text, document = split_document(_question(payload))
    question_options, body = parse_question(user_text)

    options = {"count": "", "max_count": "", "title": ""}
    options.update(question_options)
    options.update(_options_from_mapping(payload))

    uploaded = _uploaded(payload.get("genosUploaded")) or document
    return ChatInput(
        source_text=uploaded or body.strip(),
        count=options["count"],
        max_count=options["max_count"],
        title=options["title"],
        session_id=_session_id(payload),
        stream=parse_stream_flag(payload.get("stream")),
        source_kind="uploaded" if uploaded else "question",
    )
