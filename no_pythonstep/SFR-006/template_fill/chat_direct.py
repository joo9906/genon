"""`POST /chat` — 젠포탈이 이 코드서빙을 **직접** 부르는 진입점 (워크플로우 파이썬 스텝 미사용).

워크플로우 경로의 스텝 세 개가 하던 일을 이 라우트 하나가 한 요청 안에서 한다:

```
스텝 1  템플릿 확정            → chat_api._load_turn
스텝 2  발화 추출              → chat_api.extract_turn
스텝 3  문서 자동 채움(조건부)  → chat_api.prefill_turn (진행 문구를 token 으로 흘린다)
        병합·저장·답변          → chat_api.commit_turn
```

**판정은 하나도 다시 적지 않는다.** 세 단계는 기존 `/chat/*` 라우트와 같은 모듈 함수를
HTTP 없이 부른다 — 순서(추출 → 자동 채움 → 커밋)와 그 사이에 넘기는 값만 여기 있다.
추출이 자동 채움보다 먼저인 이유는 스텝 경로와 같다: 발화가 "문서 내용으로 바꿔줘" 이면
(`use_document`) 자동 채움을 덮어쓰기로 불러야 한다.

## 응답 — 화면에 보일 것과 값으로만 갈 것을 이벤트로 가른다

`stream: true` 면 SSE 다. 프레임은 전부 `{"event", "data"}` 한 모양이다:

```
data: {"event": "heartbeat", "data": {"elapsed_seconds": 0}}  ← 시작 1회 + 조용한 동안 반복
data: {"event": "token",    "data": "✔ 제목: …\n"}            ← 자동 채움 진행 (문서가 있을 때)
data: {"event": "token",    "data": "답변 + 미리보기 조각"}    ← 채팅에 보인다
data: {"event": "complete", "data": {"session_id", "template_id", "download_url"}}
data: {"event": "end",      "data": ""}
```

- **채팅에 보일 글은 전부 `token` 이다** — 진행 문구, 답변(`chat_reply`), 미리보기, 오류
  문구까지. 결과 프레임에는 `text` 를 싣지 않는다(채팅이 같은 글을 한 번 더 그리지 않게).
- 결과 프레임의 값은 스텝 3 의 `event: result` 와 같다 — 다운로드 버튼이 `POST /generate`
  를 부를 때 쓰는 `session_id`·`template_id`, 다 채웠을 때만 오는 `download_url`.
- 이벤트 이름·heartbeat 는 번역 시범(`no_pythonstep/SFR-018-translate/chat_api.py`)과 같은
  환경변수로 바꾼다: `CHAT_TOKEN_EVENT`·`CHAT_RESULT_EVENT`·`CHAT_END_EVENT`(빈 값이면 end
  프레임을 내지 않는다)·`CHAT_HEARTBEAT_SECONDS`(기본 5, 0 이면 끈다)·`CHAT_HEARTBEAT_EVENT`.
- **오류도 SSE 로 낸다** (HTTP 200). 스트리밍을 요청한 화면은 SSE 만 읽는다.

`stream: false` 면 JSON 한 덩어리 — 흘릴 데가 없으므로 **`text` 를 싣는다.** 오류는
`ApiError` 의 상태코드와 함께 `{"text", "error"}`.

## 세션 — 이 경로의 가장 큰 미확정

006 은 여러 턴에 걸쳐 값을 모으는 대화라 **턴을 잇는 세션 id 가 있어야** 한다. 지금까지
본 직접 호출 payload 는 `{question, stream}` 뿐이었다. 세션 id 를 찾는 순서는
`chat_input.parse_chat_payload` 머리말에 있다.

**세션 id 가 없으면 이번 턴만 처리하고, 이어지지 않는다는 사실을 답변 끝에 밝힌다.**
요청을 세우면 문서 한 번에 다 채우는 쓰임(첫 턴에 끝나는 대화)까지 막히고, 말없이 넘기면
사용자는 다음 턴에 값이 사라진 것을 "고장" 으로만 본다. 워크플로우 스텝 1 도 세션 id 가
없을 때 요청을 세우지 않았다(로그 경고만).

## 스캔 쪽

전처리기가 스캔 쪽 자리에 남긴 표식(`[[GENON_SCAN`)은 워크플로우 경로에서 MCP `genon_ocr`
로 읽었다. 이 경로에는 그 호출이 없다 — **문서 자동 채움만 건너뛰고** 그 사실을 답변에
밝힌다. 자동 채움은 부가 기능이라 대화 자체를 세우지 않는다(`prefill_turn` 의 실패 규약과
같다). 표식을 그대로 LLM 에 넣으면 표식 문자열을 항목 값으로 읽는다.
"""

import asyncio
import json
import os
import time

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from .chat_api import (
    CommitRequest,
    ExtractRequest,
    PrefillRequest,
    _load_turn,
    _prefill_progress_text,
    commit_turn,
    extract_turn,
    prefill_turn,
)
from .chat_input import ChatInput, parse_chat_payload
from .error_codes import ERR_API_INPUT, ERR_CHAT_INTERNAL, ApiError
from .logging_utils import log_error, log_info, log_warning
from .session_store import SessionStoreError, load_session

_SSE_HEADERS = {
    # 중간 프록시가 모아서 보내면 스트리밍이 사라진다 — 오류 없이 "한방에 나온다" 로만 보인다.
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}

# 사용자 노출 문구 — 이 파일 안 고정 한국어 문장만 쓴다 (3.8절)
_MSG_BAD_BODY = "요청 형식이 올바르지 않습니다."
_MSG_NO_SESSION = (
    "대화 정보를 받지 못해 이번에 입력한 내용이 다음 질문에 이어지지 않습니다."
    " 한 번에 모두 입력하거나 관리자에게 문의해 주세요."
)
_MSG_SCANNED = (
    "첨부 문서에 스캔한 쪽이 있어 문서로 자동 채우기를 하지 못했습니다."
    " 내용을 직접 입력해 주세요."
)

# 전처리기가 스캔 쪽 자리에 남기는 표식 (`high_preprocessor.py`, `ocr_defer=True`)
_SCAN_MARK = "[[GENON_SCAN"

# 템플릿을 아무도 정하지 않았을 때. 워크플로우 스텝 1 의 PoC 고정값과 같은 이름·같은 값이다 —
# 스텝 경로에서 이 단위로 옮겨도 같은 템플릿이 잡혀야 한다.
_DEFAULT_TEMPLATE_ID = (os.environ.get("TEMPLATE_FILL_DEFAULT_TEMPLATE_ID") or "abc").strip()

# 답변을 token 으로 나눠 보낼 때의 단위. 워크플로우 스텝 3 과 같다(글자 단위면 프레임이
# 수천 개가 되고 오히려 늦다).
_STREAM_CHUNK_CHARS = 32
_STREAM_MAX_EMITS = 400


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


def _chunks(text: str):
    size = max(_STREAM_CHUNK_CHARS, -(-len(text) // _STREAM_MAX_EMITS))
    for start in range(0, len(text), size):
        yield text[start: start + size]


def _error(exc: ApiError) -> dict:
    return {"error_code": exc.code.code, "msg": exc.msg}


async def _resolve_template(chat: ChatInput) -> str:
    """명시된 템플릿 > 세션에 저장된 템플릿 > 기본값.

    세션 단계를 건너뛰면 대화 중간에 바꾼 템플릿이 다음 턴에 기본값으로 되돌아간다
    (워크플로우 스텝 1 이 기본값을 늘 채워 넣어 생긴 문제 — 그쪽 `run` 주석).
    """
    if chat.template_id:
        return chat.template_id
    if chat.session_id:
        try:
            session = await load_session(chat.session_id)
        except (ValueError, SessionStoreError):
            session = {}
        saved = str(session.get("template_id") or "").strip()
        if saved:
            return saved
    return _DEFAULT_TEMPLATE_ID


async def _run_turn(chat: ChatInput, on_text) -> dict:
    """대화 한 턴. 채팅에 보일 글을 `on_text` 로 흘리고 결과 값을 돌려준다.

    `ApiError` 는 그대로 올린다 — 호출부가 SSE/JSON 오류로 바꾼다.
    """
    started = time.monotonic()
    template_id = await _resolve_template(chat)
    # 템플릿 확정(스텝 1). 템플릿 없음·해석 불가는 여기서 `ApiError` 로 선다 — LLM 을 부르기 전에.
    context, _state, _session = await _load_turn(chat.session_id, template_id)
    template_id = context.template_id

    # 발화 추출(스텝 2). 빈 발화면 `extract_turn` 이 LLM 을 부르지 않고 빈 결과를 낸다.
    extraction = await extract_turn(
        ExtractRequest(session_id=chat.session_id, template_id=template_id, question=chat.question)
    )
    overwrite = extraction.get("use_document") is True

    # 문서 자동 채움(스텝 3 앞부분). 실패는 대화를 세우지 않는다 — 답변에 한 줄로 나간다.
    document = chat.document.strip()
    scanned = _SCAN_MARK in document
    prefill: dict = {}
    prefill_failed = False
    skipped_reason = ""
    if scanned:
        document = ""
    if overwrite and not document and not scanned:
        skipped_reason = "no_document"
    if document:
        async def _on_progress(event: dict) -> None:
            text = _prefill_progress_text(event)
            if text:
                await on_text(text)

        try:
            prefill = await prefill_turn(
                PrefillRequest(
                    session_id=chat.session_id,
                    template_id=template_id,
                    document=document,
                    overwrite=overwrite,
                ),
                on_progress=_on_progress,
            )
        except Exception as exc:  # noqa: BLE001 - 자동 채움은 부가 기능이다
            prefill_failed = True
            log_warning(
                "문서 자동 채움 실패 — 대화로 채우기는 그대로 진행",
                event="chat_direct_prefill_failed",
                resource_id=f"{template_id}.hwpx",
                error_type=type(exc).__name__,
                status="degraded",
            )

    # 병합·저장·미리보기·답변(스텝 3)
    committed = await commit_turn(
        CommitRequest(
            session_id=chat.session_id,
            template_id=template_id,
            fields_updated=extraction.get("fields_updated") or {},
            fields_cleared=extraction.get("fields_cleared") or [],
            fields_rejected=extraction.get("fields_rejected") or [],
            blocks_added=extraction.get("blocks_added") or [],
            block_clears=extraction.get("block_clears") or [],
            fields_prefilled=prefill.get("fields_prefilled") or {},
            source_doc_hash=str(prefill.get("source_doc_hash") or ""),
            prefill_failed=prefill_failed or bool(prefill.get("prefill_failed")),
            prefill_skipped_reason=skipped_reason or str(prefill.get("skipped_reason") or ""),
            prefill_overwrite=overwrite,
        )
    )

    # 채팅이 곧 화면이다 — 답변 아래에 미리보기를 붙인다(스텝 3 과 같은 모양).
    text = str(committed.get("text") or "")
    preview = str(committed.get("document_markdown") or "").strip()
    if preview:
        text = f"{text}\n\n---\n\n**미리보기**\n\n{preview}"
    notices = []
    if scanned:
        notices.append(_MSG_SCANNED)
    if not chat.session_id:
        notices.append(_MSG_NO_SESSION)
    if notices:
        text += "\n\n" + "\n\n".join(f"> ⚠ {notice}" for notice in notices)
    await on_text(text)

    missing = list(committed.get("fields_missing") or [])
    log_info(
        "채팅 템플릿 채우기 턴 완료",
        event="chat_direct_turn_done",
        resource_id=f"{template_id}.hwpx",
        item_count=len(committed.get("field_values") or {}),
        status=(
            f"session={chat.session_source} document={int(bool(chat.document))}"
            f" scanned={int(scanned)} prefilled={len(prefill.get('fields_prefilled') or {})}"
            f" missing={len(missing)} ready={int(not missing)}"
        ),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    result = {"template_id": template_id, "download_url": committed.get("download_url") or None}
    if chat.session_id:
        result["session_id"] = chat.session_id
    return result


def _log_rejected(chat: ChatInput | None, error: dict) -> None:
    log_warning(
        "채팅 템플릿 채우기 오류 응답",
        event="chat_direct_error_response",
        error_code=error["error_code"],
        resource_id=(chat.session_source if chat else "unparsed"),
        status="final",
    )


def _internal_error(exc: Exception) -> ApiError:
    log_error(
        "채팅 템플릿 채우기 내부 오류",
        event="chat_direct_internal_error",
        error_type=type(exc).__name__,
    )
    return ApiError(ERR_CHAT_INTERNAL)


# ── 비스트리밍 ───────────────────────────────────────────────────────────────
async def _respond_json(chat: ChatInput):
    pieces: list = []

    async def _collect(text: str) -> None:
        pieces.append(text)

    try:
        result = await _run_turn(chat, _collect)
    except ApiError as exc:
        error = _error(exc)
        _log_rejected(chat, error)
        return JSONResponse(
            status_code=exc.code.http_status, content={"text": error["msg"], "error": error}
        )
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
        error = _error(_internal_error(exc))
        return JSONResponse(
            status_code=ERR_CHAT_INTERNAL.http_status,
            content={"text": error["msg"], "error": error},
        )
    # 흘릴 데가 없으니 채팅이 그릴 글을 여기 싣는다
    return {"text": "".join(pieces), **result}


# ── 스트리밍 ─────────────────────────────────────────────────────────────────
async def _stream_frames(chat: ChatInput):
    token_event, result_event, end_event = _event_names()
    heartbeat_event, heartbeat_interval = _heartbeat()
    started = time.monotonic()

    # 턴과 전송을 큐로 가른다 — 자동 채움은 진행 콜백을 직렬로 부르므로 제너레이터 안에서
    # 직접 yield 할 수 없다.
    queue: asyncio.Queue = asyncio.Queue()
    done = object()

    async def _on_text(text: str) -> None:
        await queue.put(text)

    async def _work() -> None:
        try:
            await queue.put(("result", await _run_turn(chat, _on_text)))
        except ApiError as exc:
            await queue.put(("error", _error(exc)))
        except Exception as exc:  # noqa: BLE001 - 최종 방어선
            await queue.put(("error", _error(_internal_error(exc))))
        finally:
            await queue.put(done)

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
                for piece in _chunks(item):
                    yield _sse(token_event, piece)
                continue
            kind, value = item
            if kind == "error":
                _log_rejected(chat, value)
                # 문구는 token 으로 흘려 채팅에 보이게 하고, 결과 프레임에는 값으로 싣는다
                yield _sse(token_event, value["msg"])
                yield _sse(result_event, {"error": value})
            else:
                yield _sse(result_event, value)
            if end_event:
                yield _sse(end_event, "")
    finally:
        # 클라이언트가 끊으면 턴도 멈춘다 — 그대로 두면 LLM 을 계속 부른다
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


def install(app) -> None:
    """FastAPI 앱에 `POST /chat` 을 등록한다. 기존 `/chat/*` 라우트와 따로다."""

    @app.post("/chat")
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
            error = _error(ApiError(ERR_API_INPUT, _MSG_BAD_BODY))
            _log_rejected(None, error)
            return JSONResponse(
                status_code=ERR_API_INPUT.http_status,
                content={"text": error["msg"], "error": error},
            )

        chat_input = parse_chat_payload(payload)
        if not chat_input.session_id:
            log_warning(
                "session_id 없음 — 이번 턴 값이 다음 턴에 유지되지 않는다",
                event="session_id_missing",
            )
        if chat_input.stream:
            return StreamingResponse(
                _stream_frames(chat_input), media_type="text/event-stream", headers=_SSE_HEADERS
            )
        return await _respond_json(chat_input)
