"""`POST /chat` — 젠포탈이 이 코드서빙을 **직접** 부르는 진입점 (워크플로우 파이썬 스텝 미사용).

워크플로우 경로에서는 스텝 1(원본 확보·문서유형/톤 정책)과 스텝 2(다듬기·결정적 점검·
결과 조립)가 하던 일을 이 라우트 하나가 한다. 요청은 `{question, stream}` 이고, 옵션은
`question` 문자열 안에 싣는다(`chat_input.py` 머리말).

- 톤 정책: 스텝 1 은 MCP `genon_lang_policy` 에 물었다. 여기서는 `/polish` 와 같은
  `resolve_policy`(이 단위의 `tone_presets` 표)를 쓴다 — 다듬기 프롬프트가 이미 그 판정으로
  만들어지므로, MCP 에 한 번 더 물으면 두 판정이 갈릴 자리만 생긴다.
- 결정적 점검: 스텝 2 처럼 MCP `genon_text_guard` 를 부른다(`guard_client.py`).

## 응답 — 화면에 보일 것과 값으로만 갈 것을 이벤트로 가른다

`stream: true` 면 SSE 다. 프레임은 전부 한 모양이다(번역 `/chat` 과 같다):

```
data: {"event": "heartbeat", "data": {"elapsed_seconds": 0}}  ← 시작 1회 + 조용한 동안 반복
data: {"event": "token",    "data": "다듬은 글 조각"}          ← 채팅에 보인다
data: {"event": "complete", "data": {...결과 값...}}          ← 값만 간다. `text` 가 없다
data: {"event": "end",      "data": ""}                       ← 마지막 1회
```

- **채팅에 보일 글은 전부 `token` 으로 나간다** — 다듬은 글, 그 아래 안내문(`notice`)과
  내려받기 링크, 오류 문구까지. 결과 프레임에 `text` 를 싣지 않으므로 채팅이 결과 값을
  한 번 더 그리지 않는다.
- **결과 프레임은 값만 담는다** — `original_text`·`polished_text`(하이라이트 없음, 스텝 2 와
  같다)·`download_url`·`doc_type`·`tone`·`tone_overridden`·`notice`·`error`.
- 이벤트 이름은 `CHAT_TOKEN_EVENT`·`CHAT_RESULT_EVENT`·`CHAT_END_EVENT` 로 바꿀 수 있다.
  `CHAT_END_EVENT` 를 빈 값으로 두면 end 프레임을 내지 않는다.
- heartbeat 는 `CHAT_HEARTBEAT_SECONDS`(기본 5초, `0` 이면 끈다) 동안 보낼 프레임이 없을
  때마다 보낸다(이름은 `CHAT_HEARTBEAT_EVENT`). 개발가이드에는 없는 이벤트이고 실제 화면에서
  본 동작을 근거로 넣었다 — 글자로 찍히면 끈다.

**오류도 SSE 로 낸다** (입력 오류 포함, HTTP 200). 스트리밍을 요청한 화면은 SSE 만 읽는다.
오류 문구는 token 으로 흘리고, 결과 프레임에 `error` 를 싣는다.

`stream: false` 면 JSON 한 덩어리다. 흘릴 데가 없으므로 **`text` 를 싣는다**. 오류는
가이드 3.9 대로 상태코드를 함께 낸다.

## 준비·실패 판정은 `main.py` 것을 주입받는다

입력 검증·정책 확정·프롬프트 렌더(`_prepare_core`)와 전량 실패 → 오류 코드 표
(`_outcome_error_code`)는 `/polish`·`/polish/stream` 과 **같은 함수**를 쓴다. 이 모듈이
`main` 을 import 하지 않고 `build_chat_router` 인자로 받는 이유는 `main.py` 끝 주석에 있다.
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from chat_input import ChatInput, parse_chat_payload
from text_polish import file_store, guard_client, md_output
from text_polish.error_codes import ERR_INPUT_INVALID, ERR_INPUT_SCANNED, ERR_INTERNAL
from text_polish.llm import STREAM_UNSUPPORTED
from text_polish.logging_utils import log_error, log_info, log_warning
from text_polish.polisher import polish_document, polish_document_stream
from text_polish.tone_presets import doc_type_choices, tone_choices

_SSE_HEADERS = {
    # 중간 프록시가 모아서 보내면 스트리밍이 사라진다 — 오류 없이 "한방에 나온다" 로만 보인다.
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}

_SCAN_MARK = "[[GENON_SCAN"


@dataclass(frozen=True)
class _PolishArgs:
    """`_prepare_core` 가 읽는 필드만 가진 요청 — `main.PolishRequest` 와 같은 이름이다."""

    text: str
    doc_type: str
    tone: str
    title: str
    extra_instruction: str = ""


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


def _error(code) -> dict:
    return {"error_code": code.code, "msg": code.user_msg}


def _label(code: str, choices: list) -> str:
    for choice in choices:
        if choice["code"] == code:
            return str(choice["label"])
    return code


async def _upload_result(markdown: str, title: str) -> str:
    """다듬은 글을 md 로 굳혀 올리고 링크를 돌려준다. 실패하면 빈 문자열 (fail-open)."""
    return await file_store.upload_bytes(
        md_output.to_bytes(markdown),
        md_output.download_filename(md_output.safe_stem(title, "글다듬이결과")),
        md_output.MEDIA_TYPE,
    )


def _notices(*, doc_type: str, tone: str, tone_overridden: bool, failed: int,
             structure: int, fact: int, diverged: bool) -> list:
    """결과는 냈지만 사용자가 알아야 하는 것. 문구는 스텝 2 와 같다 (건수만 말한다)."""
    notices: list = []
    if tone_overridden:
        notices.append(
            f"'{_label(doc_type, doc_type_choices())}' 문서는 정책상"
            f" '{_label(tone, tone_choices())}' 톤으로 다듬었습니다."
        )
    if failed:
        notices.append(
            f"문서 일부 구간({failed}곳)을 다듬지 못해 원문 그대로 두었습니다. 다시 시도해 주세요."
        )
    if structure:
        notices.append(
            f"표·제목 등 문서 구조가 원문과 달라진 곳이 {structure}곳 있습니다. 결과를 확인해 주세요."
        )
    if fact:
        notices.append(f"숫자·날짜가 원문과 다른 곳이 {fact}곳 있습니다. 결과를 확인해 주세요.")
    if diverged:
        notices.append(
            "다듬는 도중 연결이 끊겨 화면에 잠시 보였던 문장이 최종 결과와 다를 수 있습니다."
            " 아래 결과를 확인해 주세요."
        )
    return notices


def _tail_text(notices: list, download_url: str) -> str:
    """다듬은 글 **아래에** 이어 붙일 채팅용 글 — 안내문과 내려받기 링크."""
    lines = [f"> ⚠ {notice}" for notice in notices]
    if download_url:
        lines.append(f"[다듬은 결과 내려받기 (.md)]({download_url})")
    return ("\n\n---\n\n" + "\n\n".join(lines)) if lines else ""


def _log_rejected(chat: ChatInput | None, error: dict) -> None:
    log_warning(
        "채팅 글다듬이 오류 응답",
        event="chat_polish_error_response",
        error_code=error["error_code"],
        resource_id=(chat.source_kind if chat else "unparsed"),
        status="final",
    )


def build_chat_router(*, prepare, outcome_error_code) -> APIRouter:
    """`POST /chat` 라우터.

    Args:
        prepare: `main._prepare_core` — `(준비값, None)` 또는 `(None, ErrorCode)`.
        outcome_error_code: `main._outcome_error_code` — 전량 실패면 ErrorCode, 아니면 None.
    """
    router = APIRouter()

    def _prepare(chat_input: ChatInput):
        """(준비값, None) 또는 (None, ErrorCode). 스캔 표식은 정책·프롬프트보다 먼저 거른다."""
        if _SCAN_MARK in chat_input.source_text:
            return None, ERR_INPUT_SCANNED
        return prepare(_PolishArgs(
            text=chat_input.source_text,
            doc_type=chat_input.doc_type,
            tone=chat_input.tone,
            title=chat_input.title,
        ))

    async def _finish(chat_input: ChatInput, prepared, outcome, *, streamed: bool,
                      fell_back: bool, started: float) -> tuple:
        """성공한 다듬기 → (꼬리 글, 결과 값). 점검·업로드는 서로 독립이라 함께 띄운다."""
        source_text, _system, doc_type, tone, tone_overridden = prepared
        polished = outcome.text
        guard, download_url = await asyncio.gather(
            guard_client.check(source_text, polished),
            _upload_result(polished, chat_input.title),
        )
        structure = guard["markdown_structure_issues"]
        fact = guard["fact_issues"]
        if structure:
            log_warning("마크다운/HTML 구조 훼손 감지", event="structure_damaged",
                        item_count=len(structure))
        if fact:
            log_warning("숫자·날짜 불일치 감지", event="fact_mismatch", item_count=len(fact))
        notices = _notices(
            doc_type=doc_type,
            tone=tone,
            tone_overridden=tone_overridden,
            failed=outcome.failed_chunk_count,
            structure=len(structure),
            fact=len(fact),
            diverged=bool(getattr(outcome, "stream_diverged", False)),
        )
        log_info(
            "채팅 글다듬이 완료",
            event="chat_polish_completed",
            resource_id=f"{doc_type}/{tone}",
            item_count=outcome.chunk_count,
            status=(
                f"stream={int(streamed)},source={chat_input.source_kind}"
                f",failed={outcome.failed_chunk_count},fallback={int(fell_back)}"
                f",structure={len(structure)},fact={len(fact)},notice={len(notices)}"
            ),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        payload = {
            "original_text": source_text,
            "polished_text": polished,
            "download_url": download_url or None,
            "doc_type": doc_type,
            "tone": tone,
            "tone_overridden": tone_overridden,
        }
        if notices:
            payload["notice"] = notices
        return _tail_text(notices, download_url), payload

    # ── 라우트 ────────────────────────────────────────────────────────────────
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
            error = _error(ERR_INPUT_INVALID)
            _log_rejected(None, error)
            return JSONResponse(
                status_code=ERR_INPUT_INVALID.http_status,
                content={"text": error["msg"], "error": error},
            )

        chat_input = parse_chat_payload(payload)
        if chat_input.stream:
            return StreamingResponse(
                _stream_frames(chat_input), media_type="text/event-stream", headers=_SSE_HEADERS
            )
        return await _respond_json(chat_input)

    # ── 비스트리밍 ────────────────────────────────────────────────────────────
    async def _respond_json(chat_input: ChatInput):
        def _fail(code):
            error = _error(code)
            _log_rejected(chat_input, error)
            return JSONResponse(status_code=code.http_status,
                                content={"text": error["msg"], "error": error})

        prepared, error_code = _prepare(chat_input)
        if error_code is not None:
            return _fail(error_code)

        started = time.monotonic()
        source_text, system_prompt = prepared[0], prepared[1]
        try:
            outcome = await polish_document(system_prompt, source_text)
            error_code = outcome_error_code(outcome)
            if error_code is not None:
                return _fail(error_code)
            tail, result = await _finish(chat_input, prepared, outcome, streamed=False,
                                         fell_back=False, started=started)
        except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
            log_error("채팅 글다듬이 내부 오류", event="chat_polish_internal_error",
                      error_code=ERR_INTERNAL.code, error_type=type(exc).__name__)
            return _fail(ERR_INTERNAL)
        # 흘릴 데가 없으니 채팅이 그릴 글을 여기 싣는다
        return {"text": result["polished_text"] + tail, **result}

    # ── 스트리밍 ──────────────────────────────────────────────────────────────
    async def _stream_frames(chat_input: ChatInput):
        token_event, result_event, end_event = _event_names()

        def _end():
            return [_sse(end_event, "")] if end_event else []

        def _error_frames(error: dict) -> list:
            # 문구는 token 으로 흘려 채팅에 보이게 하고, 결과 프레임에는 값으로 싣는다
            return [_sse(token_event, error["msg"]), _sse(result_event, {"error": error}), *_end()]

        prepared, error_code = _prepare(chat_input)
        if error_code is not None:
            error = _error(error_code)
            _log_rejected(chat_input, error)
            for frame in _error_frames(error):
                yield frame
            return

        started = time.monotonic()
        # 다듬기와 전송을 큐로 가른다 — `polish_document_stream` 은 `on_text` 를 콜백으로
        # 부르므로 제너레이터 안에서 직접 yield 할 수 없다.
        queue: asyncio.Queue = asyncio.Queue()
        done = object()

        async def _on_text(text: str) -> None:
            await queue.put(text)

        async def _work() -> None:
            try:
                await queue.put(await _polish_streaming(chat_input, prepared, _on_text, started))
            except Exception as exc:  # noqa: BLE001 - 최종 방어선
                log_error("채팅 글다듬이 스트리밍 내부 오류",
                          event="chat_polish_stream_internal_error",
                          error_code=ERR_INTERNAL.code, error_type=type(exc).__name__)
                await queue.put(("error", _error(ERR_INTERNAL)))
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
                    tail, result = value
                    if tail:
                        yield _sse(token_event, tail)
                    yield _sse(result_event, result)
                    for frame in _end():
                        yield frame
        finally:
            # 클라이언트가 끊으면 다듬기도 멈춘다 — 그대로 두면 LLM 을 계속 부른다
            if not task.done():
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _polish_streaming(chat_input: ChatInput, prepared, on_text, started: float):
        """다듬기 → 점검·결과 조립. `("result", (꼬리 글, 결과 값))` 또는 `("error", 오류)`."""
        source_text, system_prompt, doc_type, tone, _overridden = prepared
        fell_back = False
        outcome = await polish_document_stream(system_prompt, source_text, on_text)
        # 스트리밍을 안 받는 배포면 비스트리밍으로 되돌아간다 — 한 글자도 안 흘렸을 때만
        # (흘린 뒤에 다시 하면 화면에 같은 문서가 겹친다).
        if outcome.stream_unsupported and outcome.streamed_chars == 0:
            fell_back = True
            log_warning(
                "스트리밍을 쓸 수 없어 비스트리밍으로 다듬는다",
                event="chat_polish_stream_fallback",
                resource_id=f"{doc_type}/{tone}",
                error_type=STREAM_UNSUPPORTED,
            )
            outcome = await polish_document(system_prompt, source_text)
            if outcome.ok:
                await on_text(outcome.text)

        error_code = outcome_error_code(outcome)
        if error_code is not None:
            log_warning(
                "채팅 글다듬이 전량 실패",
                event="chat_polish_failed",
                error_code=error_code.code,
                error_type=outcome.error_type,
                item_count=outcome.chunk_count,
                status="retryable" if error_code.retryable else "final",
            )
            return "error", _error(error_code)

        return "result", await _finish(chat_input, prepared, outcome, streamed=True,
                                       fell_back=fell_back, started=started)

    return router
