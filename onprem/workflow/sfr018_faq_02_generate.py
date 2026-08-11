"""FAQ 스텝 2/2 — 생성 + 다운로드용 저장 + 응답 (area 02, **마지막 스텝**).

캔버스에서 하는 일: 코드서빙 `POST /generate` 로 FAQ 를 만들고(LLM + 근거 검증 + 중복 제거),
같은 요청에서 세션에 저장한 뒤 마크다운을 스트리밍한다.

## 생성과 저장을 한 요청으로 묶는다

**화면에서 본 FAQ 와 내려받는 파일이 같아야 한다**는 것이 이 기능의 계약이다. 워크플로우가
생성 후 별도 호출로 저장하면 그 사이에서 실패했을 때 "화면엔 있는데 다운로드는 없는" 상태가
캔버스에 생긴다. 코드서빙 한 요청 안에서 저장까지 끝낸다.

## 기각 건수를 전부 노출한다

`schema` / `ungrounded` / `duplicate` 세 사유의 기각 건수가 `faq_stats` 로 올라온다.
조용히 버리면 왜 5개 요청에 3개만 나왔는지 알 수 없다. 캔버스에서 이 값으로 분기할 수 있다
(예: 근거 기각이 많으면 사람 확인 노드로).

## 저장 실패는 결과 전달을 막지 않는다

채팅으로는 이미 볼 수 있기 때문이다. 대신 **다운로드가 안 된다는 사실을 안내에 덧붙인다**.
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

_LOG = logging.getLogger("faq_generate")


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
        "error_type": "FAQ_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "FAQ 생성 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"{_AREA}-00020002",
        "error_type": "FAQ_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "FAQ 를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "NO_GROUNDED": {
        "error_code": f"{_AREA}-00020002",
        "error_type": "FAQ_NO_GROUNDED_ITEMS",
        "retryable": True,
        "msg": "문서에서 근거를 찾은 FAQ 가 없습니다. 내용이 더 담긴 문서로 다시 시도해 주세요.",
    },
    "CONFIG_MISSING": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "FAQ_CONFIG_MISSING",
        "retryable": False,
        "msg": "서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
    },
    "INTERNAL": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "FAQ_INTERNAL",
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

# FAQ 는 부족분 재요청까지 포함해 LLM 을 여러 번 부를 수 있다 (§B 전체 예산 안에서).
_GENERATE_READ_TIMEOUT = 120.0


def _gateway_base() -> str:
    base = (os.environ.get("GENOS_URL") or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("GENOS_URL is not configured")
    return base if base.endswith("/api/gateway") else f"{base}/api/gateway"


async def _post_serving(path: str, payload: dict, *, read_timeout: float):
    serving_id = (os.environ.get("FAQ_SERVING_ID") or "").strip()
    if not serving_id:
        return None, ("config", "FAQ_SERVING_ID_MISSING", None)
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
        for chunk in _stream_chunks(error["msg"]):
            yield await emit_event("token", chunk)
        yield {
            "event": "result",
            "data": {**data, "text": error["msg"], "faq_items": [], "error": error},
        }

    upstream_error = data.get("error")
    if upstream_error:
        _log_warning(
            "앞 스텝 오류를 사용자에게 전달",
            event="faq_error",
            error_code=str(upstream_error.get("error_code") or ""),
            status="final",
            **log_context,
        )
        async for event in finish_with_error(upstream_error):
            yield event
        return

    source_text = str(data.get("faq_source_text") or "")
    count = int(data.get("faq_count") or 0)
    session_id = str(data.get("faq_session_id") or "")

    if not session_id:
        # 치명적이지 않다 — 채팅에는 나오지만 다운로드가 안 된다. 안내에 반영된다.
        _log_warning(
            "session_id 없음 — 다운로드 불가 상태로 진행",
            event="faq_session_id_missing",
            **log_context,
        )

    # 생성 + 세션 저장을 한 요청으로. 나누면 "화면엔 있는데 다운로드는 없는" 상태가 생긴다.
    body, failure = await _post_serving(
        "/generate",
        {
            # 키 이름은 코드서빙 `GenerateRequest` 를 따른다 — `markdown` 이 필수 필드다.
            # `text` 로 보내면 pydantic 이 422 를 내는데, 그 실패는 "LLM 오류" 로 보여
            # 원인을 찾기 어렵다.
            "markdown": source_text,
            # 상한 안으로 이미 깎은 값이다(스텝 01). 코드서빙은 배포 상한으로 한 번 더
            # 깎으므로 여기서 상한을 함께 보낼 필요가 없다 — 상한을 요청 값으로 받으면
            # 캔버스가 배포 상한을 넘길 수 있게 된다.
            "count": count,
            "session_id": session_id,
            "title": str(data.get("faq_title") or ""),
        },
        read_timeout=_GENERATE_READ_TIMEOUT,
    )

    if failure is not None:
        kind, error_type, upstream_status = failure
        if kind == "config":
            key = "CONFIG_MISSING"
        elif kind == "transport":
            key = "UPSTREAM_TIMEOUT"
        elif upstream_status == 422:
            # 근거를 찾은 항목이 하나도 없을 때 코드서빙이 422 를 낸다
            key = "NO_GROUNDED"
        else:
            key = "UPSTREAM_EXECUTION"
        error = _error(key)
        _log_warning(
            "FAQ 생성 실패",
            event="faq_generate_failed",
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
    items = list(result.get("items") or [])
    stats = dict(result.get("stats") or {})
    download_ready = bool(result.get("download_ready"))
    display_text = str(result.get("markdown") or "")

    if not download_ready:
        display_text = (
            "※ 이번 결과는 파일로 내려받을 수 없습니다. 화면 내용을 복사해 사용해 주세요.\n\n"
            + display_text
        )

    _log_info(
        "FAQ 생성 완료",
        event="faq_done",
        resource_id=str(data.get("faq_source_kind") or ""),
        item_count=len(items),
        status=(
            f"requested={count}"
            f" schema={stats.get('rejected_schema', 0)}"
            f" ungrounded={stats.get('rejected_ungrounded', 0)}"
            f" duplicate={stats.get('rejected_duplicate', 0)}"
            f" download={int(download_ready)}"
        ),
        **log_context,
    )

    for chunk in _stream_chunks(display_text):
        yield await emit_event("token", chunk)

    yield {
        "event": "result",
        "data": {
            **data,
            "text": display_text,
            "faq_items": items,
            "faq_stats": stats,
            "faq_download_ready": download_ready,
            "error": None,
        },
    }
