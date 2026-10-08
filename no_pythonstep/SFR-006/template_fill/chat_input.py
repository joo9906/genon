"""`POST /chat` 요청 해석 — 젠포탈이 보내는 `{question, stream}` 을 대화 한 턴 입력으로 바꾼다.

젠포탈은 워크플로우 파이썬 스텝 없이 이 코드서빙을 직접 부른다. 템플릿·세션을 따로 실을
칸이 없을 수 있어 **`question` 문자열 안에 옵션을 함께 싣는 모양도 받는다.**

1. 머리말 줄

   ```
   template_id: 보도자료
   session_id: abc-123

   제목은 신제품 출시로 해줘
   ```

   - 구분자는 `:` 와 `=` 둘 다 받는다. 키는 대소문자를 가리지 않는다.
   - **맨 앞에서 아는 키가 이어지는 동안만** 머리말이다. 아는 키가 아닌 줄을 만나면
     그 줄부터 발화다 — `제목: 신제품 출시` 같은 발화 첫 줄은 먹히지 않는다.
   - 머리말 바로 뒤의 빈 줄 하나 또는 `---` 한 줄은 구분자로 보고 버린다.

2. JSON 문자열 — `{"template_id": "보도자료", "text": "발화"}`.
   발화는 `text` → `message` → `question` 순으로 찾는다.

**첨부 문서도 `question` 안에 온다.** 첨부(`genosUploaded`)는 `[입력된 문서]` 표식 뒤에
붙는다. 표식 앞이 사용자 발화(+머리말), 표식 뒤가 문서다. 표식 뒤에 `<doc>` 태그가 있으면
태그 안만 문서이고 태그 밖 글은 발화에 붙인다. **번역과 달리 발화를 버리지 않는다** —
006 은 같은 턴에 "이 문서로 채우고 제목은 A 로" 가 함께 오는 대화다.

**우선순위**: 템플릿은 최상위 키 > 머리말 > 세션에 저장된 템플릿 > 기본값 환경변수
(`TEMPLATE_FILL_DEFAULT_TEMPLATE_ID`). 세션 단계는 `chat_direct` 가 세션을 읽어야 알
수 있어 거기서 정한다. 세션 id 는 최상위 키(운영 브리지 순서) > `genos_state` > 머리말.
"""

import json
import re
from dataclasses import dataclass

# 옵션 이름 → 받아들이는 키. 워크플로우 캔버스 변수 이름(`template_fill_template_id`)도
# 받는다 — 같은 화면이 스텝 경로와 이 경로를 오가도 키를 바꾸지 않아도 된다.
_OPTION_KEYS = {
    "template_id": ("template_id", "template", "template_fill_template_id", "템플릿"),
    "session_id": ("session_id", "sessionid", "socketioclientid", "세션"),
}
_KEY_TO_OPTION = {
    alias.lower(): option for option, aliases in _OPTION_KEYS.items() for alias in aliases
}

# 세션 id 를 싣는 최상위 키. 앞의 셋은 운영 브리지(`genos_files/bridge.py`)·워크플로우 스텝 1
# 과 같은 순서다. 뒤의 넷은 젠포탈 직접 호출 payload 가 대화 id 를 싣는 이름이 아직 확인되지
# 않아 함께 받는다 — 대화 하나에 하나인 값이면 무엇이든 세션 키로 쓸 수 있다.
_SESSION_KEYS = (
    "socketIOClientId", "sessionId", "session_id",
    "chatId", "chat_id", "conversationId", "conversation_id",
)
_TEMPLATE_KEYS = ("template_id", "template_fill_template_id")

_HEADER_LINE_RE = re.compile(r"^\s*([A-Za-z_가-힣]+)\s*[:=]\s*(.*?)\s*$")
_SEPARATOR_RE = re.compile(r"^\s*-{3,}\s*$")
_BODY_KEYS = ("text", "message", "question")
_QUESTION_KEYS = ("question", "text", "message", "query")
_DOC_TAG_RE = re.compile(r"<doc[^>]*>(.*?)</doc>", re.DOTALL | re.IGNORECASE)
_DOC_MARK = "[입력된 문서]"
_TRUE_VALUES = frozenset({"1", "true", "yes", "y", "on"})


@dataclass(frozen=True)
class ChatInput:
    question: str
    document: str
    session_id: str
    # 최상위 키·머리말로 **명시된** 템플릿. 비면 `chat_direct` 가 세션 → 기본값 순으로 정한다.
    template_id: str
    stream: bool
    # 세션 id 를 어디서 얻었는지 — 로그로만 쓴다 (`payload` / `question` / `none`)
    session_source: str


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
    """JSON 객체 문자열이면 (옵션, 발화). 아니면 None."""
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
    """맨 앞의 `키: 값` 줄을 옵션으로 떼고 나머지를 발화로 돌려준다."""
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
    """`question` 문자열 → (옵션 dict, 발화). 옵션이 없으면 문자열 전체가 발화다."""
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


def _payload_value(payload: dict, keys: tuple) -> str:
    state = payload.get("genos_state")
    for source in (payload, state if isinstance(state, dict) else {}):
        for key in keys:
            value = source.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()
    return ""


def parse_chat_payload(payload: dict) -> ChatInput:
    """요청 본문 전체를 해석한다. 최상위 키가 `question` 머리말을 이긴다."""
    user_text, document = split_document(_question(payload))
    options, question = parse_question(user_text)

    session_id = _payload_value(payload, _SESSION_KEYS)
    session_source = "payload" if session_id else ""
    if not session_id and options.get("session_id"):
        session_id, session_source = options["session_id"], "question"

    return ChatInput(
        question=question.strip(),
        document=document,
        session_id=session_id,
        template_id=_payload_value(payload, _TEMPLATE_KEYS) or options.get("template_id", ""),
        stream=parse_stream_flag(payload.get("stream")),
        session_source=session_source or "none",
    )
