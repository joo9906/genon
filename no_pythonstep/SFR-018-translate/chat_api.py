"""`POST /chat` — 젠포탈이 이 코드서빙을 **직접** 부르는 진입점 (워크플로우 파이썬 스텝 미사용).

워크플로우 경로에서는 스텝 1(입력 해석·언어 검증)과 스텝 2(번역·숫자 점검·결과 조립)가
하던 일을 이 라우트 하나가 한다. 요청은 `{question, stream}` 이고, 옵션은 `question`
문자열 안에 싣는다(`chat_input.py` 머리말).

## 응답 — 화면에 보일 것과 값으로만 갈 것을 이벤트로 가른다

`stream: true` 면 SSE 다. 프레임은 전부 한 모양이다:

```
data: {"event": "token",    "data": "번역문 조각"}        ← 채팅에 보인다
data: {"event": "complete", "data": {...결과 값...}}      ← 값만 간다. `text` 가 없다
data: {"event": "end",      "data": ""}                   ← 마지막 1회
```

- **채팅에 보일 글은 전부 `token` 으로 나간다** — 번역문, 그 아래 안내문(`notice`)과
  내려받기 링크, 오류 문구까지. 결과 프레임에 `text` 를 싣지 않으므로 채팅이 결과 값을
  한 번 더 그리지 않는다.
- **결과 프레임은 값만 담는다** — `original_text`·`translated_text`(둘 다 `<mark>` 사본)·
  `download_url`·`notice`·`error`. 프론트가 좌우 비교 같은 별도 화면을 그릴 때 읽는다.
- 프레임을 `{"event", "data"}` 한 JSON 으로 싣는 이유: 젠포탈이 이 모양을 읽는다(같은
  방식으로 `complete` 를 보내는 다른 단위에서 확인). 기존 `/translate/stream` 의
  `{"type": "delta"}` 모양은 워크플로우 스텝이 읽던 내부 형식이라 젠포탈이 알아보지 못한다.
- 이벤트 이름은 환경변수로 바꿀 수 있다(`CHAT_TOKEN_EVENT`·`CHAT_RESULT_EVENT`·
  `CHAT_END_EVENT`). 젠포탈이 받는 이름이 확정되면 코드를 고치지 않고 맞춘다.
  `CHAT_END_EVENT` 를 빈 값으로 두면 end 프레임을 내지 않는다.

**번역이 시작되면 heartbeat 를 보낸다**:
`data: {"event": "heartbeat", "data": {"elapsed_seconds": 12}}`. 시작할 때 한 번 보내고,
그 뒤로는 `CHAT_HEARTBEAT_SECONDS`(기본 5초) 동안 보낼 프레임이 없을 때마다 보낸다.
조각이 계속 흐르는 동안에는 보내지 않는다. 첫 조각이 나오기 전이나 비스트리밍으로
되돌아간 동안에는 화면이 멈춘 것처럼 보이는데, 이 프레임을 받으면 화면이 진행 표시를
돌린다. 개발가이드에는 없는 이벤트다. 실제 화면에서 본 동작을 근거로 넣었으므로
글자로 찍히면 `CHAT_HEARTBEAT_SECONDS=0` 으로 끈다(이름은 `CHAT_HEARTBEAT_EVENT`).

**오류도 SSE 로 낸다** (입력 오류 포함, HTTP 200). 스트리밍을 요청한 화면은 SSE 만 읽으므로
400 JSON 을 받으면 아무것도 그리지 못한다. 오류 문구는 token 으로 흘리고, 결과 프레임에
`error` 를 싣는다.

`stream: false` 면 JSON 한 덩어리다. 이때는 흘릴 데가 없으므로 **`text` 를 싣는다** —
채팅이 그릴 것이 그것뿐이다. 오류는 가이드 3.9 대로 상태코드를 함께 낸다.

## 번역 경로

- 스트리밍: `stream_pipeline` — 조각 단위 LLM 스트리밍. 구조 보존이 프롬프트에 달려 있어
  끝나고 `structure_diff` 로 대조해 어긋나면 안내문으로 알린다.
- 비스트리밍: `run_markdown_translation_job` — 스켈레톤 분해로 구조를 **코드가 보장**하는
  정본 경로다.
"""

import asyncio
import json
import os
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from chat_input import ChatInput, parse_chat_payload
from config import Config
from translation_pipeline.common import file_store, md_output
from translation_pipeline.common.error_codes import (
    ERR_INPUT,
    ERR_INTERNAL,
    ERR_UPSTREAM_EXECUTION,
    ERR_UPSTREAM_TIMEOUT,
)
from translation_pipeline.common.llm import CONFIG_MISSING
from translation_pipeline.common.logging_utils import log_error, log_info, log_warning
from translation_pipeline.office import stream_pipeline
from translation_pipeline.office.numeric_guard import find_numeric_drift
from translation_pipeline.office.pipeline import (
    TranslationRequestError,
    run_markdown_translation_job,
)

router = APIRouter()

_SSE_HEADERS = {
    # 중간 프록시가 모아서 보내면 스트리밍이 사라진다 — 오류 없이 "한방에 나온다" 로만 보인다.
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}

# 사용자 노출 문구 — 이 파일 안 고정 한국어 문장만 쓴다 (3.8절)
_MSG_EMPTY = "번역할 내용이 없습니다. 본문을 입력하거나 문서를 첨부해 주세요."
_MSG_TARGET_MISSING = "번역할 언어를 선택해 주세요."
_MSG_TOO_LONG = f"총 텍스트 길이가 상한({Config.MAX_TOTAL_CHARS}자)을 초과했습니다."
_MSG_SCANNED = "스캔한 쪽이 포함된 문서는 이 경로에서 아직 번역할 수 없습니다."
_MSG_BAD_BODY = "요청 형식이 올바르지 않습니다."
_MSG_CONFIG_MISSING = "서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요."
_MSG_ALL_FAILED = "번역에 실패했습니다. 잠시 후 다시 시도해 주세요."

# 전처리기가 스캔 쪽 자리에 남기는 표식. OCR 은 MCP 가 하는데 이 경로에는 그 호출이 없다 —
# 표식을 그대로 번역에 넣으면 LLM 이 표식을 번역문으로 바꿔 내므로 받지 않는다.
_SCAN_MARK = "[[GENON_SCAN"


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


def _error(code, msg: str) -> dict:
    return {"error_code": code.code, "msg": msg}


async def _upload_result(markdown: str, title: str) -> str:
    """번역 정본을 md 로 굳혀 올리고 링크를 돌려준다. 실패하면 빈 문자열 (fail-open)."""
    stem = md_output.safe_stem(title, "번역결과")
    return await file_store.upload_bytes(
        md_output.to_bytes(markdown),
        md_output.download_filename(stem),
        md_output.MEDIA_TYPE,
    )


def _notices(*, unapplied: int, failed: int, numeric: int, structure_issues: int) -> list:
    """결과는 냈지만 사용자가 알아야 하는 것. **건수만** 말한다 (용어·본문은 싣지 않는다)."""
    notices: list = []
    if unapplied:
        notices.append(
            f"용어사전 용어 {unapplied}개가 번역문에 반영되지 않았습니다."
            " 다시 번역하면 반영될 수 있습니다."
        )
    if failed:
        notices.append(f"{failed}개 부분을 번역하지 못해 원문 그대로 두었습니다. 다시 번역해 주세요.")
    if numeric:
        notices.append(f"원문과 번역문의 숫자·날짜가 {numeric}곳 다릅니다. 결과를 확인해 주세요.")
    if structure_issues:
        notices.append("표·목록 등 문서 구조가 원문과 다를 수 있습니다. 결과를 확인해 주세요.")
    return notices


def _tail_text(notices: list, download_url: str) -> str:
    """번역문 **아래에** 이어 붙일 채팅용 글 — 안내문과 내려받기 링크."""
    lines = [f"> ⚠ {notice}" for notice in notices]
    if download_url:
        lines.append(f"[번역 결과 내려받기 (.md)]({download_url})")
    return ("\n\n---\n\n" + "\n\n".join(lines)) if lines else ""


def _result_payload(*, original: str, translated: str, download_url: str, notices: list) -> dict:
    """결과 프레임의 값. **`text` 는 넣지 않는다** — 채팅에 보일 글은 token 으로 이미 나갔다."""
    payload = {
        "original_text": original,
        "translated_text": translated,
        "download_url": download_url or None,
    }
    if notices:
        payload["notice"] = notices
    return payload


def _validate(chat: ChatInput):
    """번역 전에 걸러야 하는 입력. 문제가 없으면 None."""
    if not chat.source_text:
        return _error(ERR_INPUT, _MSG_EMPTY)
    if not chat.target_lang:
        return _error(ERR_INPUT, _MSG_TARGET_MISSING)
    if len(chat.source_text) > Config.MAX_TOTAL_CHARS:
        return _error(ERR_INPUT, _MSG_TOO_LONG)
    if _SCAN_MARK in chat.source_text:
        return _error(ERR_INPUT, _MSG_SCANNED)
    return None


def _log_rejected(chat: ChatInput | None, error: dict) -> None:
    log_warning(
        "채팅 번역 오류 응답",
        event="chat_translate_error_response",
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
        error = _error(ERR_INPUT, _MSG_BAD_BODY)
        _log_rejected(None, error)
        return JSONResponse(
            status_code=ERR_INPUT.http_status, content={"text": error["msg"], "error": error}
        )

    chat_input = parse_chat_payload(payload)
    if chat_input.stream:
        return StreamingResponse(
            _stream_frames(chat_input), media_type="text/event-stream", headers=_SSE_HEADERS
        )
    return await _respond_json(chat_input)


# ── 비스트리밍 ───────────────────────────────────────────────────────────────
async def _respond_json(chat_input: ChatInput):
    def _fail(code, msg: str):
        error = _error(code, msg)
        _log_rejected(chat_input, error)
        return JSONResponse(
            status_code=code.http_status, content={"text": msg, "error": error}
        )

    error = _validate(chat_input)
    if error is not None:
        _log_rejected(chat_input, error)
        return JSONResponse(
            status_code=ERR_INPUT.http_status, content={"text": error["msg"], "error": error}
        )

    started = time.monotonic()
    try:
        artifacts = await run_markdown_translation_job(
            markdown=chat_input.source_text,
            target_lang=chat_input.target_lang,
            source_lang=chat_input.source_lang,
            register=chat_input.register,
        )
    except TranslationRequestError as exc:
        # 계약: 이 예외의 메시지는 pipeline·languages 의 고정 안내문이다
        return _fail(ERR_INPUT, str(exc))
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
        log_error("채팅 번역 내부 오류", event="chat_translate_internal_error",
                  error_type=type(exc).__name__)
        return _fail(ERR_INTERNAL, ERR_INTERNAL.user_msg)

    stats = artifacts.stats
    # 실패 유닛은 원문이 그대로 남아 응답이 비지 않는다 — 전량 실패를 성공으로 내보내지 않는다
    if artifacts.translation_error and stats.unit_count and (
        stats.failed_unit_count >= stats.unit_count
    ):
        if artifacts.translation_error == CONFIG_MISSING:
            return _fail(ERR_INTERNAL, _MSG_CONFIG_MISSING)
        return _fail(ERR_UPSTREAM_EXECUTION, _MSG_ALL_FAILED)

    glossary = artifacts.glossary or {}
    notices = _notices(
        unapplied=len(dict(glossary.get("term_map_unapplied") or {})),
        failed=stats.failed_unit_count,
        numeric=len(artifacts.numeric_warnings or []),
        structure_issues=0,  # 스켈레톤 경로는 구조를 코드가 보장한다
    )
    download_url = await _upload_result(artifacts.markdown, chat_input.title)

    log_info(
        "채팅 번역 완료",
        event="chat_translate_completed",
        resource_id=f"{artifacts.options.get('source_lang') or 'unknown'}->{chat_input.target_lang}",
        item_count=stats.unit_count,
        status=f"stream=0,source={chat_input.source_kind},failed={stats.failed_unit_count}"
               f",notice={len(notices)}",
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return {
        # 흘릴 데가 없으니 채팅이 그릴 글을 여기 싣는다
        "text": artifacts.markdown + _tail_text(notices, download_url),
        **_result_payload(
            original=artifacts.source_markdown_highlighted or artifacts.source_markdown,
            translated=artifacts.markdown_highlighted or artifacts.markdown,
            download_url=download_url,
            notices=notices,
        ),
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

    error = _validate(chat_input)
    options = None
    if error is None:
        try:
            # 정본과 같은 판정 — 지원 언어·한국어 축(§6)·문체 폴백
            options = stream_pipeline.resolve_options(
                target_lang=chat_input.target_lang,
                source_lang=chat_input.source_lang,
                register=chat_input.register,
                sample_text=chat_input.source_text,
            )
        except TranslationRequestError as exc:
            error = _error(ERR_INPUT, str(exc))
        except Exception as exc:  # noqa: BLE001 - 최종 방어선
            log_error("채팅 번역 옵션 확정 오류", event="chat_translate_options_error",
                      error_type=type(exc).__name__)
            error = _error(ERR_INTERNAL, ERR_INTERNAL.user_msg)
    if error is not None:
        _log_rejected(chat_input, error)
        for frame in _error_frames(error):
            yield frame
        return

    started = time.monotonic()
    # 번역과 전송을 큐로 가른다 — `translate_document_stream` 은 `on_text` 를 직렬화해서
    # 부르므로 제너레이터 안에서 직접 yield 할 수 없다.
    queue: asyncio.Queue = asyncio.Queue()
    done = object()

    async def _on_text(text: str) -> None:
        await queue.put(text)

    async def _work() -> None:
        try:
            await queue.put(await _translate_streaming(chat_input, options, _on_text, started))
        except Exception as exc:  # noqa: BLE001 - 최종 방어선
            log_error("채팅 번역 스트리밍 내부 오류", event="chat_translate_stream_internal_error",
                      error_type=type(exc).__name__)
            await queue.put(("error", _error(ERR_INTERNAL, ERR_INTERNAL.user_msg)))
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
        # 클라이언트가 끊으면 번역도 멈춘다 — 그대로 두면 LLM 을 계속 부른다
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


async def _translate_streaming(chat_input: ChatInput, options, on_text, started: float):
    """번역 → 마무리 판정. `("result", (꼬리 글, 결과 값))` 또는 `("error", 오류)` 를 돌려준다."""
    source = chat_input.source_text
    fell_back = False
    outcome = await stream_pipeline.translate_document_stream(source, options, on_text)
    # 스트리밍을 안 받는 배포면 비스트리밍으로 되돌아간다 — 한 글자도 안 흘렸을 때만
    # (흘린 뒤에 다시 하면 화면에 같은 문서가 겹친다).
    if outcome.stream_unsupported and outcome.streamed_chars == 0:
        fell_back = True
        log_warning(
            "스트리밍을 쓸 수 없어 비스트리밍으로 번역한다",
            event="chat_translate_stream_fallback",
            resource_id="llm_gateway",
            error_type=outcome.error_type,
        )
        outcome = await stream_pipeline.translate_document_plain(source, options)
        if outcome.ok:
            await on_text(outcome.text)

    if not outcome.ok:
        # 전량 실패에서는 흘린 글이 없다 — 실패 조각의 원문은 최종 판정 뒤에만 풀린다
        if outcome.config_missing:
            error = _error(ERR_INTERNAL, _MSG_CONFIG_MISSING)
        elif outcome.is_transport_error:
            error = _error(ERR_UPSTREAM_TIMEOUT, ERR_UPSTREAM_TIMEOUT.user_msg)
        else:
            error = _error(ERR_UPSTREAM_EXECUTION, _MSG_ALL_FAILED)
        log_warning(
            "채팅 번역 전량 실패",
            event="chat_translate_failed",
            error_code=error["error_code"],
            error_type=outcome.error_type,
            item_count=outcome.chunk_count,
            status="final" if outcome.config_missing else "retryable",
        )
        return "error", error

    translated = outcome.text
    glossary = stream_pipeline.build_document_glossary(source, translated, options)
    structure = stream_pipeline.structure_diff(source, translated)
    drift = find_numeric_drift(source, translated)
    notices = _notices(
        unapplied=len(dict(glossary.get("term_map_unapplied") or {})),
        failed=outcome.failed_chunk_count,
        numeric=len(drift["missing"]) + len(drift["added"]),
        structure_issues=len(structure["issues"]),
    )
    download_url = await _upload_result(translated, chat_input.title)

    log_info(
        "채팅 번역 완료",
        event="chat_translate_completed",
        resource_id=f"{options.source_code or 'unknown'}->{options.target_code}",
        item_count=outcome.chunk_count,
        status=(
            f"stream=1,source={chat_input.source_kind}"
            f",failed={outcome.failed_chunk_count},fallback={int(fell_back)}"
            f",diverged={int(outcome.stream_diverged)},notice={len(notices)}"
        ),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    payload = _result_payload(
        original=stream_pipeline.highlight_document(source, glossary["hits"], span_key="spans"),
        translated=stream_pipeline.highlight_document(
            translated, glossary["hits"], span_key="target_spans"
        ),
        download_url=download_url,
        notices=notices,
    )
    return "result", (_tail_text(notices, download_url), payload)
