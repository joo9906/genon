"""SFR-006 스텝 3/3 — 병합·저장·미리보기·응답 (area 02, **마지막 스텝**).

캔버스에서 하는 일: 앞 스텝이 뽑아 둔 값을 세션에 병합·저장하고, 지금 값으로 채운 문서
미리보기와 답변 문구를 받아 **토큰 스트리밍 후 `event: result` 1회**로 마무리한다.

## 여기만 async generator 다

중간 스텝(`01_context`·`02_extract`)은 `dict` 를 돌려주고, 스트리밍이 필요한 이 스텝만
generator 로 만든다 (§D.1 — 네 시그니처를 섞지 않는다). `event: result` 는 **오류일 때도
반드시 1회** 보낸다. 안 보내면 이전 `data` 가 그대로 흐르고 답변이 완결되지 않는다.

## 스트리밍 규약 (onprem/README "워크플로우 스트리밍 규약" / 가이드 5.2·D.4)

- `sio_server.emit` 뒤에 **`await asyncio.sleep(0)`** — 양보하지 않고 몰아치면 소켓 쓰기가
  버퍼에 쌓여 UI 가 마지막에 한꺼번에 받는다.
- 전송 단위는 글자가 아니라 **청크(32자)**. 글자 단위면 emit 이 수천 회가 되고 오히려 늦다.

## 파일 생성은 여기서 하지 않는다

다운로드 버튼이 코드서빙 `POST /generate` 를 직접 부른다. 두 pod 는 **Redis 세션**으로
연결되고, 이 스텝은 세션 저장까지만 책임진다.
"""

import asyncio
import json
import logging
import os

import httpx

# ─────────────────────────────────────────────────────────────
# 로깅 (§C / 가이드 3.8)
# ─────────────────────────────────────────────────────────────
_ALLOWED_LOG_FIELDS = frozenset({
    "event", "trace_id", "request_id", "resource_id", "status",
    "duration_ms", "item_count", "upstream_status", "error_code", "error_type",
})

_LOG = logging.getLogger("sfr006_commit")


def _emit_log(level: int, message: str, *, event: str, **fields) -> None:
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
    _LOG.log(level, message, extra=extra)


def _log_info(message: str, *, event: str, **fields) -> None:
    _emit_log(logging.INFO, message, event=event, **fields)


def _log_warning(message: str, *, event: str, **fields) -> None:
    _emit_log(logging.WARNING, message, event=event, **fields)


# ─────────────────────────────────────────────────────────────
# 오류표 (§A)
# ─────────────────────────────────────────────────────────────
_AREA = "02"

_ERRORS = {
    "UPSTREAM_TIMEOUT": {
        "error_code": f"{_AREA}-00020001",
        "error_type": "TPL_COMMIT_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "문서 작성 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"{_AREA}-00020002",
        "error_type": "TPL_COMMIT_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "입력하신 내용을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "CONFIG_MISSING": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TPL_CONFIG_MISSING",
        "retryable": False,
        "msg": "서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
    },
    "INTERNAL": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TPL_COMMIT_INTERNAL",
        "retryable": False,
        "msg": "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
}


def _error(key: str) -> dict:
    spec = _ERRORS[key]
    return {
        "error_code": spec["error_code"],
        "msg": spec["msg"],
        "retryable": spec["retryable"],
    }


# ─────────────────────────────────────────────────────────────
# 게이트웨이 호출 (§B / §H)
# ─────────────────────────────────────────────────────────────
_RETRY_STATUS = frozenset({502, 503, 504})
_CONNECT_TIMEOUT = 3.0
_ATTEMPTS = 2


def _gateway_base() -> str:
    base = (os.environ.get("GENOS_URL") or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("GENOS_URL is not configured")
    return base if base.endswith("/api/gateway") else f"{base}/api/gateway"


async def _post_serving(path: str, payload: dict, *, read_timeout: float):
    serving_id = (os.environ.get("TEMPLATE_FILL_SERVING_ID") or "").strip()
    if not serving_id:
        return None, ("config", "TEMPLATE_FILL_SERVING_ID_MISSING", None)
    try:
        url = f"{_gateway_base()}/code_serving/{serving_id}/{path.lstrip('/')}"
    except RuntimeError:
        return None, ("config", "GENOS_URL_MISSING", None)

    headers = {"Authorization": f"Bearer {(os.environ.get('GENOS_TOKEN') or '').strip()}"}
    timeout = httpx.Timeout(
        connect=_CONNECT_TIMEOUT, read=read_timeout, write=5.0, pool=_CONNECT_TIMEOUT
    )

    failure = ("transport", "NoAttempt", None)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(_ATTEMPTS):
            try:
                response = await client.post(url, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                failure = ("transport", type(exc).__name__, None)
            else:
                if response.status_code < 400:
                    try:
                        return response.json(), None
                    except json.JSONDecodeError:
                        return None, ("execution", "InvalidJson", response.status_code)
                if response.status_code in _RETRY_STATUS:
                    failure = ("transport", "HTTPStatusError", response.status_code)
                else:
                    return None, ("execution", "HTTPStatusError", response.status_code)
            if attempt < _ATTEMPTS - 1:
                await asyncio.sleep(0.3 * (attempt + 1))
    return None, failure


# ─────────────────────────────────────────────────────────────
# 스트리밍
# ─────────────────────────────────────────────────────────────
_STREAM_CHUNK_CHARS = 32


def _stream_chunks(text: str):
    for start in range(0, len(text), _STREAM_CHUNK_CHARS):
        yield text[start: start + _STREAM_CHUNK_CHARS]


def _log_context(data: dict) -> dict:
    state = data.get("genos_state") or {}
    return {"trace_id": state.get("trace_id")}


async def run(data: dict):
    # 1) socket.io (모듈이 없으면 조용히 스킵 — 로컬·비대화 실행 경로)
    try:
        from main_socketio import sio_server
    except ImportError:
        sio_server = None

    if not isinstance(data, dict):
        data = {"question": str(data)}
    sid = data.get("socketIOClientId")
    log_context = _log_context(data)

    async def emit_event(event_name: str, payload):
        if sio_server and sid:
            await sio_server.emit(event_name, payload, room=sid)
            # WebSocket write buffer flush (가이드 5.2·D.4)
            await asyncio.sleep(0)
        return {"event": event_name, "data": payload}

    async def finish_with_error(error: dict):
        """오류 문구를 스트리밍하고 result 로 마무리한다. 마지막 스텝의 의무다."""
        for chunk in _stream_chunks(error["msg"]):
            yield await emit_event("token", chunk)
        yield {"event": "result", "data": {**data, "text": error["msg"], "error": error}}

    # 2) 앞 스텝이 실패했으면 그 오류를 사용자에게 전달하고 끝낸다.
    #    중간 스텝은 스트리밍을 하지 않으므로 **여기서 말해 주지 않으면 화면이 빈 채로 끝난다.**
    upstream_error = data.get("error")
    if upstream_error:
        _log_warning(
            "앞 스텝 오류를 사용자에게 전달",
            event="template_fill_error",
            error_code=str(upstream_error.get("error_code") or ""),
            status="final",
            **log_context,
        )
        async for event in finish_with_error(upstream_error):
            yield event
        return

    # 3) 병합·저장·미리보기 — 세 가지가 한 요청이다.
    #    나누면 저장은 됐는데 미리보기에서 실패한 중간 상태가 캔버스에 생긴다.
    body, failure = await _post_serving(
        "/chat/commit",
        {
            "session_id": str(data.get("session_id") or ""),
            "template_id": str(data.get("template_id") or ""),
            "fields_updated": data.get("fields_updated") or {},
            "fields_cleared": data.get("fields_cleared") or [],
            "fields_rejected": data.get("fields_rejected") or [],
            "blocks_added": data.get("blocks_added") or [],
            "block_clears": data.get("block_clears") or [],
            "tone_applied_fields": data.get("tone_applied_fields") or [],
            "tone_rejected_fields": data.get("tone_rejected_fields") or [],
            "tone_applied_blocks": data.get("tone_applied_blocks") or [],
            "tone_rejected_blocks": data.get("tone_rejected_blocks") or [],
            # 톤 LLM 실패 사실. 없으면 "적용 0건" 과 구분되지 않아 문체가 그대로인 이유가
            # 사용자에게 전달되지 않는다.
            "tone_llm_error_fields": data.get("tone_llm_error_fields") or "",
            "tone_llm_error_blocks": data.get("tone_llm_error_blocks") or "",
        },
        read_timeout=30.0,
    )

    if failure is not None:
        kind, error_type, upstream_status = failure
        if kind == "config":
            key = "CONFIG_MISSING"
        elif kind == "transport":
            key = "UPSTREAM_TIMEOUT"
        else:
            key = "UPSTREAM_EXECUTION"
        error = _error(key)
        _log_warning(
            "병합·저장 실패 — 이번 턴 값이 다음 턴에 유지되지 않는다",
            event="commit_failed",
            error_code=error["error_code"],
            error_type=error_type,
            upstream_status=upstream_status,
            status="retryable" if error["retryable"] else "final",
            **log_context,
        )
        async for event in finish_with_error(error):
            yield event
        return

    result = body or {}
    display_text = str(result.get("text") or "")
    fields_missing = list(result.get("fields_missing") or [])

    _log_info(
        "턴 마무리",
        event="template_fill_turn_done",
        resource_id=f"{data.get('template_id')}.hwpx",
        item_count=len(result.get("field_values") or {}),
        status=f"missing={len(fields_missing)} ready={int(not fields_missing)}",
        **log_context,
    )

    # 4) 토큰 스트리밍 → result 1회 (GenOS 계약)
    for chunk in _stream_chunks(display_text):
        yield await emit_event("token", chunk)

    yield {
        "event": "result",
        "data": {
            **data,
            "text": display_text,
            # ── 항목 값 ──
            "field_values": dict(result.get("field_values") or {}),
            "field_values_raw": dict(result.get("field_values_raw") or {}),
            "fields_filled": list(result.get("fields_filled") or []),
            "fields_missing": fields_missing,
            "ready_for_download": not fields_missing,
            # ── 본문 블록 ──
            "blocks": list(result.get("blocks") or []),
            "blocks_removed": int(result.get("blocks_removed") or 0),
            # ── 미리보기 (UI 문서 창이 그린다) ──
            "document_markdown": result.get("document_markdown") or "",
            "document_markdown_truncated": bool(result.get("document_markdown_truncated")),
            "error": None,
        },
    }
