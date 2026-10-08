"""`POST /chat` — 젠포탈이 이 코드서빙을 **직접** 부르는 진입점 (워크플로우 파이썬 스텝 미사용).

워크플로우 경로에서는 스텝 1(원본 확보·개수 결정)과 스텝 2(생성·저장·결과 조립·안내문)가
하던 일을 이 라우트 하나가 한다. 요청은 `{question, stream}` 이고, 옵션은 `question`
문자열 안에 싣는다(`chat_input.py` 머리말).

## 응답 — 화면에 보일 것과 값으로만 갈 것을 이벤트로 가른다

`stream: true` 면 SSE 다. 프레임 모양은 번역 `/chat` 과 같다:

```
data: {"event": "heartbeat", "data": {"elapsed_seconds": 0}}   ← 시작 1회 + 조용한 동안 반복
data: {"event": "token",     "data": "**Q1. …**\\n\\n답변 조각"}  ← 채팅에 보인다
data: {"event": "complete",  "data": {...결과 값...}}           ← 값만 간다. `text` 가 없다
data: {"event": "end",       "data": ""}                        ← 마지막 1회
```

- **채팅에 보일 글은 전부 `token` 으로 나간다** — 문답 목록, 그 아래 안내문(`notice`)과
  내려받기 링크, 오류 문구까지. 흘리는 글은 `/generate/stream` 과 같은 조각
  (`main._display_text`)이라 이어 붙이면 내려받는 md 의 본문과 같다.
- **결과 프레임은 값만 담는다** — `faq_items`·`download_url`·`notice`·`disclaimer`·`error`.
  워크플로우 스텝 2 의 `result` 와 같은 키다(전용 화면이 목록으로 다시 그릴 때 읽는다).
- 이벤트 이름·heartbeat 는 번역과 같은 환경변수로 바꾼다(`CHAT_TOKEN_EVENT`·
  `CHAT_RESULT_EVENT`·`CHAT_END_EVENT`·`CHAT_HEARTBEAT_SECONDS`·`CHAT_HEARTBEAT_EVENT`).

**기각될 항목은 화면에 나타나지 않는다** — 생성기가 근거 대조·중복 판정을 지난 항목만
프레임으로 내기 때문이다(`/generate/stream` 과 같은 계산을 쓴다).

**오류도 SSE 로 낸다** (입력 오류 포함, HTTP 200). 스트리밍을 요청한 화면은 SSE 만 읽으므로
400 JSON 을 받으면 아무것도 그리지 못한다. 오류 문구는 token 으로 흘리고, 결과 프레임에
`error` 를 싣는다. 결과 프레임에 `faq_items` 를 함께 싣지 않는다 — 빈 목록을 내면 "0건 생성" 과
"실패" 가 같아 보인다.

`stream: false` 면 JSON 한 덩어리다. 흘릴 데가 없으므로 **`text` 를 싣는다** — 채팅이 그릴
것이 그것뿐이다. 오류는 가이드 3.9 대로 상태코드를 함께 낸다.

## 생성·저장은 기존 라우트와 같은 함수를 지난다

`main._store_and_payload`(md 업로드 → `download_url`, 세션 저장)와 `main._FAILURE_ERRORS`
(실패 분류 → 오류 코드)를 그대로 쓴다. 이 파일이 조립을 한 벌 더 가지면 `/chat` 과
`/generate` 가 다른 파일을 내려주게 되고, 그 어긋남은 오류가 아니라 화면에서만 드러난다.
진입 파일(루트 `main.py`)이 끝에서 `install(app, 자기 모듈)` 로 넘겨준다 — 이 파일이 `main` 을
import 하지 않는다(순환 import, `python main.py` 이중 적재).
"""

import asyncio
import json
import os
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .chat_input import ChatInput, parse_chat_payload
from .config import Config
from .error_codes import (
    ERR_API_INPUT,
    ERR_API_INTERNAL,
    ERR_API_UPSTREAM_EXECUTION,
)
from .generator import (
    FAILURE_STREAM_UNSUPPORTED,
    generate_faqs,
    generate_faqs_stream,
    resolve_max_count,
)
from .logging_utils import log_error, log_info, log_warning

router = APIRouter()

_SSE_HEADERS = {
    # 중간 프록시가 모아서 보내면 스트리밍이 사라진다 — 오류 없이 "한방에 나온다" 로만 보인다.
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}

# 사용자 노출 문구 — 이 파일 안 고정 한국어 문장만 쓴다 (3.8절)
_MSG_EMPTY = "FAQ 를 만들 문서를 첨부해 주세요."
_MSG_COUNT_ZERO = "생성할 FAQ 개수를 1개 이상으로 지정해 주세요."
_MSG_TOO_LONG = "문서가 너무 깁니다. 나누어 요청해 주세요."
_MSG_SCANNED = "스캔한 쪽이 포함된 문서는 이 경로에서 아직 FAQ 를 만들 수 없습니다."
_MSG_BAD_BODY = "요청 형식이 올바르지 않습니다."

# 전처리기가 스캔 쪽 자리에 남기는 표식. OCR 은 MCP 가 하는데 이 경로에는 그 호출이 없다 —
# 표식을 그대로 넘기면 LLM 이 표식 문자열을 본문으로 읽으므로 받지 않는다.
_SCAN_MARK = "[[GENON_SCAN"


# 진입 모듈(루트 `main.py`). `install` 이 넣는다 — 이 파일이 `main` 을 import 하면
# `python main.py` 로 띄울 때 진입 파일이 두 번 실린다.
_SERVICE = None


def install(app, service) -> None:
    """`/chat` 라우터를 붙이고, 조립·분류 함수를 꺼낼 진입 모듈을 기억한다."""
    global _SERVICE
    _SERVICE = service
    app.include_router(router)


def _service():
    return _SERVICE


def _event_names() -> tuple:
    return (
        os.environ.get("CHAT_TOKEN_EVENT", "token").strip() or "token",
        os.environ.get("CHAT_RESULT_EVENT", "complete").strip() or "complete",
        os.environ.get("CHAT_END_EVENT", "end").strip(),
    )


def _heartbeat() -> tuple:
    """(이벤트 이름, 간격 초). 간격이 0 이하이거나 숫자가 아니면 heartbeat 를 끈다."""
    try:
        interval = float(os.environ.get("CHAT_HEARTBEAT_SECONDS", "5"))
    except ValueError:
        interval = 0.0
    name = os.environ.get("CHAT_HEARTBEAT_EVENT", "heartbeat").strip() or "heartbeat"
    return name, max(interval, 0.0)


def _sse(event: str, data) -> str:
    return "data: " + json.dumps(
        {"event": event, "data": data}, ensure_ascii=False, default=str
    ) + "\n\n"


def _error(code, msg: str = "") -> dict:
    return {"error_code": code.code, "msg": msg or code.user_msg}


def _as_int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _count(chat: ChatInput) -> int:
    """생성할 총 개수 — 배포 상한 안에서 `max_count` 로 낮추기만 허용 (워크플로우 스텝 1 과 같다)."""
    maximum = resolve_max_count(chat.max_count or None)
    return max(0, min(_as_int(chat.count, Config.DEFAULT_FAQ_COUNT), maximum))


def _validate(chat: ChatInput, count: int):
    """생성 전에 걸러야 하는 입력. 문제가 없으면 None."""
    if not chat.source_text:
        return _error(ERR_API_INPUT, _MSG_EMPTY)
    if _SCAN_MARK in chat.source_text:
        return _error(ERR_API_INPUT, _MSG_SCANNED)
    if _service()._too_long(chat.source_text):
        return _error(ERR_API_INPUT, _MSG_TOO_LONG)
    if count <= 0:
        return _error(ERR_API_INPUT, _MSG_COUNT_ZERO)
    return None


def _failure_error(result) -> tuple:
    """생성 실패 → (오류 코드 객체, 응답 dict). 분류표는 `main._FAILURE_ERRORS` 한 곳이다."""
    code = _service()._FAILURE_ERRORS.get(result.failure, ERR_API_UPSTREAM_EXECUTION)
    return code, _error(code)


def _notices(payload: dict) -> list:
    """결과는 냈지만 사용자가 알아야 하는 것 (워크플로우 스텝 2 와 같은 판정·문구)."""
    items = payload.get("items") or []
    source_chunks = int(payload.get("source_chunks") or 0)
    chunks_planned = int(payload.get("chunks_planned") or 0)
    chunks_used = int(payload.get("chunks_used") or 0)
    requested = int(payload.get("requested_count") or 0)
    notices: list = []
    if chunks_planned and chunks_used < chunks_planned:
        notices.append(
            "문서 일부 구간에서 FAQ 를 만들지 못했습니다. 다시 시도하면 더 나올 수 있습니다."
        )
    if payload.get("coverage_capped") and source_chunks:
        notices.append(
            f"문서가 길어 전체 {source_chunks}개 구간 중 {chunks_planned}개 구간에서"
            " 나눠 만들었습니다. 나머지 구간 내용은 반영되지 않았습니다."
        )
    if payload.get("source_truncated"):
        notices.append("문서가 매우 길어 뒷부분은 FAQ 생성에서 제외했습니다.")
    if requested and len(items) < requested:
        notices.append(
            f"요청하신 {requested}개 중 {len(items)}개만 문서에서 근거를 확인했습니다."
        )
    return notices


def _disclaimer(payload: dict):
    """개수 미달 전용 값 — 화면이 이 필드 하나로 부족분을 읽는 계약 (스텝 2 와 같다)."""
    requested = int(payload.get("requested_count") or 0)
    shortfall = requested - len(payload.get("items") or [])
    return f"{shortfall}개를 생성하지 못하였습니다." if requested and shortfall > 0 else None


def _tail_text(notices: list, download_url) -> str:
    """문답 목록 **아래에** 이어 붙일 채팅용 글 — 안내문과 내려받기 링크."""
    lines = [f"> ⚠ {notice}" for notice in notices]
    if download_url:
        lines.append(f"[FAQ 내려받기 (.md)]({download_url})")
    return ("\n\n---\n\n" + "\n\n".join(lines)) if lines else ""


def _result_payload(payload: dict, notices: list) -> dict:
    """결과 프레임의 값. **`text` 는 넣지 않는다** — 채팅에 보일 글은 token 으로 이미 나갔다."""
    result = {
        "faq_items": list(payload.get("items") or []),
        "download_url": payload.get("download_url") or None,
    }
    if notices:
        result["notice"] = notices
    disclaimer = _disclaimer(payload)
    if disclaimer:
        result["disclaimer"] = disclaimer
    return result


def _log_done(chat: ChatInput, payload: dict, notices: list, *, stream: bool,
              fell_back: bool, started: float) -> None:
    rejected = dict(payload.get("rejected") or {})
    log_info(
        "채팅 FAQ 생성 완료",
        event="chat_faq_completed",
        resource_id=chat.source_kind,
        item_count=len(payload.get("items") or []),
        status=(
            f"stream={int(stream)},fallback={int(fell_back)}"
            f",requested={payload.get('requested_count')}"
            f",chunks={payload.get('chunks_used')}/{payload.get('chunks_planned')}"
            f"of{payload.get('source_chunks')}"
            f",schema={rejected.get('schema', 0)},ungrounded={rejected.get('ungrounded', 0)}"
            f",duplicate={rejected.get('duplicate', 0)}"
            f",download={int(bool(payload.get('download_url')))}"
            f",session={int(bool(chat.session_id))},notice={len(notices)}"
        ),
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _log_rejected(chat: ChatInput | None, error: dict) -> None:
    log_warning(
        "채팅 FAQ 오류 응답",
        event="chat_faq_error_response",
        error_code=error["error_code"],
        resource_id=(chat.source_kind if chat else "unparsed"),
        status="final",
    )


# ═══════════════════════════════════════════════════════════════════════════
# 라우트
# ═══════════════════════════════════════════════════════════════════════════
@router.post("/chat")
async def chat(request: Request):
    """젠포탈 직접 호출 진입점. `stream` 값에 따라 SSE 또는 JSON 을 돌려준다.

    **반환 타입 주석을 붙이지 않는다** — `StreamingResponse`/`JSONResponse`/`dict` 로
    갈리고, Union 주석이면 FastAPI 가 라우트 등록 단계에서 앱을 죽인다(공통 규약).
    """
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = None
    if isinstance(payload, str):
        # 본문 전체가 문자열 하나로 오는 배선 — 그 문자열을 question 으로 본다
        payload = {"question": payload}

    if not isinstance(payload, dict):
        error = _error(ERR_API_INPUT, _MSG_BAD_BODY)
        _log_rejected(None, error)
        return JSONResponse(
            status_code=ERR_API_INPUT.http_status, content={"text": error["msg"], "error": error}
        )

    chat_input = parse_chat_payload(payload)
    if not chat_input.session_id:
        # 치명적이지 않다 — `download_url` 로 내려받는다. `POST /download` 옛 경로만 못 쓴다.
        log_info("세션 id 없음 — 세션 저장 없이 진행", event="chat_faq_session_missing",
                 resource_id=chat_input.source_kind)
    if chat_input.stream:
        return StreamingResponse(
            _stream_frames(chat_input), media_type="text/event-stream", headers=_SSE_HEADERS
        )
    return await _respond_json(chat_input)


# ── 비스트리밍 ───────────────────────────────────────────────────────────────
async def _respond_json(chat_input: ChatInput):
    def _fail(code, error: dict):
        _log_rejected(chat_input, error)
        return JSONResponse(
            status_code=code.http_status, content={"text": error["msg"], "error": error}
        )

    count = _count(chat_input)
    error = _validate(chat_input, count)
    if error is not None:
        return _fail(ERR_API_INPUT, error)

    started = time.monotonic()
    try:
        result = await generate_faqs(chat_input.source_text, count, chat_input.max_count or None)
        if not result.ok:
            return _fail(*_failure_error(result))
        payload = await _service()._store_and_payload(
            result, chat_input.session_id, chat_input.title
        )
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
        log_error("채팅 FAQ 내부 오류", event="chat_faq_internal_error",
                  error_type=type(exc).__name__)
        return _fail(ERR_API_INTERNAL, _error(ERR_API_INTERNAL))

    notices = _notices(payload)
    _log_done(chat_input, payload, notices, stream=False, fell_back=False, started=started)
    return {
        # 흘릴 데가 없으니 채팅이 그릴 글을 여기 싣는다
        "text": str(payload.get("markdown") or "")
        + _tail_text(notices, payload.get("download_url")),
        **_result_payload(payload, notices),
    }


# ── 스트리밍 ─────────────────────────────────────────────────────────────────
async def _stream_frames(chat_input: ChatInput):
    token_event, result_event, end_event = _event_names()

    def _end():
        return [_sse(end_event, "")] if end_event else []

    def _error_frames(error: dict) -> list:
        # 문구는 token 으로 흘려 채팅에 보이게 하고, 결과 프레임에는 값으로 싣는다
        return [
            _sse(token_event, error["msg"]),
            _sse(result_event, {"error": error}),
            *_end(),
        ]

    count = _count(chat_input)
    try:
        error = _validate(chat_input, count)
    except Exception as exc:  # noqa: BLE001 - 최종 방어선
        log_error("채팅 FAQ 입력 판정 오류", event="chat_faq_validate_error",
                  error_type=type(exc).__name__)
        error = _error(ERR_API_INTERNAL)
    if error is not None:
        _log_rejected(chat_input, error)
        for frame in _error_frames(error):
            yield frame
        return

    started = time.monotonic()
    # 생성과 전송을 큐로 가른다 — 생성기는 `on_frame` 을 직렬화해서 부르므로
    # 제너레이터 안에서 직접 yield 할 수 없다.
    queue: asyncio.Queue = asyncio.Queue()
    done = object()

    async def _work() -> None:
        try:
            await queue.put(await _generate_streaming(chat_input, count, queue.put, started))
        except Exception as exc:  # noqa: BLE001 - 최종 방어선
            log_error("채팅 FAQ 스트리밍 내부 오류", event="chat_faq_stream_internal_error",
                      error_type=type(exc).__name__)
            await queue.put(("error", _error(ERR_API_INTERNAL)))
        finally:
            await queue.put(done)

    heartbeat_event, heartbeat_interval = _heartbeat()

    def _beat() -> str:
        return _sse(heartbeat_event, {"elapsed_seconds": round(time.monotonic() - started)})

    task = asyncio.ensure_future(_work())
    try:
        if heartbeat_interval:
            yield _beat()
        while True:
            if heartbeat_interval:
                try:
                    item = await asyncio.wait_for(queue.get(), heartbeat_interval)
                except TimeoutError:
                    yield _beat()
                    continue
            else:
                item = await queue.get()
            if item is done:
                break
            if isinstance(item, str):
                yield _sse(token_event, item)
                continue
            kind, value = item
            if kind == "error":
                for frame in _error_frames(value):
                    yield frame
            else:
                tail, payload = value
                if tail:
                    yield _sse(token_event, tail)
                yield _sse(result_event, payload)
                for frame in _end():
                    yield frame
    finally:
        # 클라이언트가 끊으면 생성도 멈춘다 — 그대로 두면 LLM 을 계속 부른다
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


async def _generate_streaming(chat_input: ChatInput, count: int, emit, started: float):
    """생성 → 저장 → 안내문. `("result", (꼬리 글, 결과 값))` 또는 `("error", 오류)` 를 돌려준다."""
    service = _service()
    streamed_chars = 0

    async def _on_frame(frame: dict) -> None:
        nonlocal streamed_chars
        text = service._display_text(frame)
        if text:
            streamed_chars += len(text)
            await emit(text)

    admin_max = chat_input.max_count or None
    fell_back = False
    result = await generate_faqs_stream(
        chat_input.source_text, count, admin_max, on_frame=_on_frame
    )
    # 스트리밍을 안 받는 배포면 비스트리밍으로 되돌아간다. 생성기는 한 항목도 흘리지 않았을
    # 때만 이 분류를 내므로 화면에 같은 목록이 겹치지 않는다.
    if result.failure == FAILURE_STREAM_UNSUPPORTED and streamed_chars == 0:
        fell_back = True
        log_warning(
            "스트리밍을 쓸 수 없어 비스트리밍으로 FAQ 를 만든다",
            event="chat_faq_stream_fallback",
            resource_id="llm_gateway",
            error_type=result.failure_type,
        )
        result = await generate_faqs(chat_input.source_text, count, admin_max)

    if not result.ok:
        _code, error = _failure_error(result)
        log_warning(
            "채팅 FAQ 생성 실패",
            event="chat_faq_failed",
            error_code=error["error_code"],
            error_type=result.failure_type or result.failure,
            item_count=streamed_chars,
            status="retryable" if _code.retryable else "final",
        )
        return "error", error

    payload = await service._store_and_payload(result, chat_input.session_id, chat_input.title)
    if fell_back:
        # 되돌아간 경우에만 여기서 흘린다 — 조건을 빼면 같은 목록을 두 번 뿌린다
        await emit(str(payload.get("markdown") or ""))
    notices = _notices(payload)
    _log_done(chat_input, payload, notices, stream=True, fell_back=fell_back, started=started)
    return "result", (_tail_text(notices, payload.get("download_url")),
                      _result_payload(payload, notices))
