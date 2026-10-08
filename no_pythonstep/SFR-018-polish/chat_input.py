"""`POST /chat` 요청 해석 — 젠포탈이 보내는 `{question, stream}` 을 다듬기 입력으로 바꾼다.

젠포탈은 워크플로우 파이썬 스텝 없이 이 코드서빙을 직접 부른다. 화면이 고른 문서유형·톤을
따로 실을 칸이 없어서 **`question` 문자열 안에 옵션을 함께 싣는다.** 두 모양을 받는다.

1. 머리말 줄 (권장)

   ```
   doc_type: email
   tone: 격식·정중
   title: 안내 메일

   다듬을 본문 …
   ```

   - 구분자는 `:` 와 `=` 둘 다 받는다. 키는 대소문자를 가리지 않는다.
   - **맨 앞에서 아는 키가 이어지는 동안만** 머리말이다. 아는 키가 아닌 줄을 만나면
     그 줄부터 본문이다 — 본문 첫 줄이 `제목: 분기 보고` 여도 먹히지 않는다.
     그래서 `제목` 은 받는 키에 넣지 않았다(다듬을 글이 그 줄로 시작하는 일이 흔하다).
   - 머리말 바로 뒤의 빈 줄 하나 또는 `---` 한 줄은 구분자로 보고 버린다.

2. JSON 문자열

   ```
   {"doc_type": "email", "tone": "polite", "text": "다듬을 본문 …"}
   ```

   본문은 `text` → `markdown` → `body` → `question` 순으로 찾는다.

**값은 코드(`email`·`polite`)와 화면 라벨(`메일`·`격식·정중`) 둘 다 받는다.** 라벨은
`tone_presets` 표에서 코드로 바꾼다. 표에 없는 값은 그대로 넘기고 `resolve_policy` 가
기본값으로 떨어뜨린다 — 판정 기준을 여기 한 벌 더 두지 않는다.

**최상위 키가 이긴다.** 나중에 프론트가 `doc_type` 을 payload 최상위에 직접 실으면
`question` 머리말보다 그 값을 쓴다. 둘 다 없으면 `POLISH_DEFAULT_*` 환경변수다
(워크플로우 스텝 1 과 같은 이름).

**첨부 문서도 `question` 안에 온다.** 첨부(`genosUploaded`)는 `[입력된 문서]` 표식 뒤에
붙는다. 표식이 있으면 **그 뒤가 원문**이고 앞쪽은 머리말(옵션)만 읽는다 — 사용자가 친 글은
다듬지 않는다(워크플로우 스텝 1 이 첨부가 있으면 발화를 버리던 것과 같은 규칙이다).
표식 뒤에 `<doc>` 태그가 있으면 태그 안만 원문이고 태그 밖 글은 앞쪽과 같이 취급한다.
"""

import json
import os
import re
from dataclasses import dataclass

from text_polish.tone_presets import doc_type_choices, tone_choices

# 옵션 이름 → 그 이름으로 받아들이는 키. 워크플로우 캔버스 변수 이름(`polish_*`)도 받는다.
_OPTION_KEYS = {
    "doc_type": ("doc_type", "polish_doc_type", "문서유형", "문서종류"),
    "tone": ("tone", "polish_tone", "톤", "어조"),
    "title": ("title", "polish_title"),
}
_KEY_TO_OPTION = {
    alias.lower(): option for option, aliases in _OPTION_KEYS.items() for alias in aliases
}

_ENV_DEFAULTS = {
    "doc_type": "POLISH_DEFAULT_DOC_TYPE",
    "tone": "POLISH_DEFAULT_TONE",
}

_HEADER_LINE_RE = re.compile(r"^\s*([A-Za-z_가-힣]+)\s*[:=]\s*(.*?)\s*$")
_SEPARATOR_RE = re.compile(r"^\s*-{3,}\s*$")
_BODY_KEYS = ("text", "markdown", "body", "question")
_QUESTION_KEYS = ("question", "text", "message", "query")
_DOC_TAG_RE = re.compile(r"<doc[^>]*>(.*?)</doc>", re.DOTALL)
_DOC_MARK = "[입력된 문서]"
_TRUE_VALUES = frozenset({"1", "true", "yes", "y", "on"})


@dataclass(frozen=True)
class ChatInput:
    source_text: str
    doc_type: str
    tone: str
    title: str
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


def _code_for(value: str, choices: list) -> str:
    """화면 라벨이면 코드로 바꾼다. 코드·라벨 어느 쪽도 아니면 받은 값 그대로."""
    wanted = value.strip().lower()
    for choice in choices:
        if wanted in (str(choice["code"]).lower(), str(choice["label"]).lower()):
            return choice["code"]
    return value.strip()


def parse_chat_payload(payload: dict) -> ChatInput:
    """요청 본문 전체를 해석한다. 우선순위는 최상위 키 > question 머리말 > 기본값 환경변수."""
    user_text, document = split_document(_question(payload))
    question_options, body = parse_question(user_text)

    options = {
        option: (os.environ.get(env_name) or "").strip()
        for option, env_name in _ENV_DEFAULTS.items()
    }
    options["title"] = ""
    options.update(question_options)
    options.update(_options_from_mapping(payload))

    return ChatInput(
        source_text=document or body.strip(),
        doc_type=_code_for(options["doc_type"], doc_type_choices()) if options["doc_type"] else "",
        tone=_code_for(options["tone"], tone_choices()) if options["tone"] else "",
        title=options["title"],
        stream=parse_stream_flag(payload.get("stream")),
        source_kind="uploaded" if document else "question",
    )
