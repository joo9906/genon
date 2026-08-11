"""번역 스텝 2/2 — 번역 + 숫자 보존 검증 + 응답 (area 02, **마지막 스텝**).

캔버스에서 하는 일:

```
코드서빙 /translate/markdown  (스켈레톤 분해 + LLM + 용어사전 + 재조립)
      ↓ translated
MCP text_guard.numeric_issues  (숫자·자릿수 보존 확인)
      ↓
용어사전 준수율 안내 → 토큰 스트리밍 → event: result
```

## 구조 보존은 코드서빙이 보장한다

마크다운/HTML 표를 **스켈레톤과 셀 텍스트로 분해**해 셀만 번역하고 다시 끼우는 무손실
왕복이 코드서빙 안에 있다. 프롬프트 지시("표를 유지하라")로 처리하지 않는다.
그래서 이 스텝은 구조를 다시 검사하지 않고 **숫자 보존만** 따로 확인한다.

## 숫자 검증을 워크플로우가 부르는 이유

코드서빙 안에도 `numeric_guard` 가 있지만, MCP 로 한 번 더 부르면 **판정 결과가 캔버스에
드러나** 분기를 걸 수 있다(예: 숫자가 어긋나면 사람 검토 노드로). 판정 자체는 같은 규칙이다.
호출이 실패해도 번역 결과 전달은 막지 않는다.

## 문서 출력은 하지 않는다 (요구사항 §3)

원본은 `source_markdown` 으로 함께 내려 UI 가 나란히 보여줄 수 있게 한다.
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

_LOG = logging.getLogger("translate")


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
        "error_type": "TRANSLATE_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "번역 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"{_AREA}-00020002",
        "error_type": "TRANSLATE_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "번역 결과를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "CONFIG_MISSING": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TRANSLATE_CONFIG_MISSING",
        "retryable": False,
        "msg": "서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
    },
    "INTERNAL": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TRANSLATE_INTERNAL",
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

# 문서 단위 번역은 배치 LLM 호출이 여러 번 돈다 (§B 전체 예산 안에서).
_TRANSLATE_READ_TIMEOUT = 180.0
_GUARD_READ_TIMEOUT = 15.0


def _gateway_base() -> str:
    base = (os.environ.get("GENOS_URL") or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("GENOS_URL is not configured")
    return base if base.endswith("/api/gateway") else f"{base}/api/gateway"


async def _post_json(url: str, payload: dict, *, read_timeout: float):
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


async def _post_serving(env_name: str, path: str, payload: dict, *, read_timeout: float):
    serving_id = (os.environ.get(env_name) or "").strip()
    if not serving_id:
        return None, ("config", f"{env_name}_MISSING", None)
    try:
        url = f"{_gateway_base()}/code_serving/{serving_id}/{path.lstrip('/')}"
    except RuntimeError:
        return None, ("config", "GENOS_URL_MISSING", None)
    return await _post_json(url, payload, read_timeout=read_timeout)


async def _mcp_call(env_name: str, tool: str, arguments: dict, *, read_timeout: float):
    serving_id = (os.environ.get(env_name) or "").strip()
    if not serving_id:
        return None, ("config", f"{env_name}_MISSING", None)
    try:
        url = f"{_gateway_base()}/mcp/{serving_id}/mcp"
    except RuntimeError:
        return None, ("config", "GENOS_URL_MISSING", None)

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    body, failure = await _post_json(url, payload, read_timeout=read_timeout)
    if failure is not None:
        return None, failure
    if isinstance(body, dict) and body.get("error"):
        return None, ("execution", "MCP_TOOL_ERROR", None)

    result = (body or {}).get("result") or {}
    contents = result.get("content") or []
    text = "".join(
        str(item.get("text") or "")
        for item in contents
        if isinstance(item, dict) and item.get("type") == "text"
    )
    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        return {"text": text}, None


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
        yield {"event": "result", "data": {**data, "text": error["msg"], "error": error}}

    upstream_error = data.get("error")
    if upstream_error:
        _log_warning(
            "앞 스텝 오류를 사용자에게 전달",
            event="translate_error",
            error_code=str(upstream_error.get("error_code") or ""),
            status="final",
            **log_context,
        )
        async for event in finish_with_error(upstream_error):
            yield event
        return

    source_text = str(data.get("translate_source_text") or "")
    target_lang = str(data.get("translate_target_lang") or "")
    source_lang = str(data.get("translate_source_lang") or "")

    # 1) 번역 — 스켈레톤 분해·LLM·용어사전·재조립이 전부 코드서빙 안에 있다
    body, failure = await _post_serving(
        "TRANSLATION_SERVING_ID",
        "/translate/markdown",
        {
            "markdown": source_text,
            "target_lang": target_lang,
            "source_lang": source_lang,
            "register": str(data.get("translate_register") or ""),
        },
        read_timeout=_TRANSLATE_READ_TIMEOUT,
    )

    if failure is not None:
        kind, error_type, upstream_status = failure
        key = (
            "CONFIG_MISSING" if kind == "config"
            else "UPSTREAM_TIMEOUT" if kind == "transport"
            else "UPSTREAM_EXECUTION"
        )
        error = _error(key)
        _log_warning(
            "번역 호출 실패",
            event="translate_failed",
            error_code=error["error_code"],
            error_type=error_type,
            upstream_status=upstream_status,
            resource_id=f"{source_lang or 'unknown'}->{target_lang}",
            status="retryable" if error["retryable"] else "final",
            **log_context,
        )
        async for event in finish_with_error(error):
            yield event
        return

    result = body or {}
    translated = str(result.get("translated_markdown") or "")
    if not translated:
        error = _error("UPSTREAM_EXECUTION")
        _log_warning(
            "번역 결과가 비어 있음",
            event="translate_empty_result",
            error_code=error["error_code"],
            error_type="EMPTY_RESULT",
            status="retryable",
            **log_context,
        )
        async for event in finish_with_error(error):
            yield event
        return

    glossary = dict(result.get("glossary") or {})
    stats = dict(result.get("stats") or {})

    # 2) 숫자 보존 확인 — 실패해도 번역 결과 전달을 막지 않는다
    numeric_warnings: list = []
    guard, guard_failure = await _mcp_call(
        "TEXT_GUARD_MCP_ID",
        "numeric_issues",
        {"source": source_text, "revised": translated},
        read_timeout=_GUARD_READ_TIMEOUT,
    )
    if guard_failure is not None:
        # 점검이 돌지 않았다는 사실이 로그에 남아야 "경고 없음" 과 구분된다
        _log_warning(
            "숫자 보존 점검 호출 실패 — 결과는 그대로 전달",
            event="numeric_guard_call_failed",
            error_type=guard_failure[1],
            upstream_status=guard_failure[2],
            status="degraded",
            **log_context,
        )
    else:
        numeric_warnings = [str(w) for w in ((guard or {}).get("issues") or [])]
        if numeric_warnings:
            # 어긋난 값은 남기지 않고 개수만 (3.8절)
            _log_warning(
                "번역문 숫자 불일치 감지",
                event="numeric_mismatch",
                item_count=len(numeric_warnings),
                **log_context,
            )

    _log_info(
        "번역 완료",
        event="translate_done",
        resource_id=f"{source_lang or 'unknown'}->{target_lang}",
        item_count=int(stats.get("unit_count") or 0),
        status=(
            f"glossary={glossary.get('source', 'none')}"
            f" compliance={glossary.get('compliance', 'n/a')}"
            f" fallback={stats.get('fallback_rate', 'n/a')}"
            f" numeric={len(numeric_warnings)}"
        ),
        **log_context,
    )

    # 3) 답변 조립
    notice = ""
    for warning in numeric_warnings:
        notice += f"⚠ {warning}\n"
    if numeric_warnings:
        notice += "\n"
    display_text = notice + translated

    for chunk in _stream_chunks(display_text):
        yield await emit_event("token", chunk)

    yield {
        "event": "result",
        "data": {
            **data,
            "text": display_text,
            "translated_markdown": translated,
            # 원본을 함께 낸다 — 문서 출력을 하지 않으므로(요구사항 §3) UI 가 나란히 보여준다
            "source_markdown": source_text,
            "glossary": glossary,
            "translate_stats": stats,
            "numeric_warnings": numeric_warnings,
            "error": None,
        },
    }
