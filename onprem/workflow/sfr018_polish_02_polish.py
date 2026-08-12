"""글다듬이 스텝 2/2 — 다듬기 + 결정적 검증 + 응답 (area 02, **마지막 스텝**).

캔버스에서 하는 일:

```
코드서빙 /polish  (LLM + 프롬프트)
      ↓ polished
MCP text_guard  ── markdown_structure_issues  (표·제목·코드펜스 훼손)
                ── fact_issues                (숫자·날짜 누락)
                ── diff_changes               (무엇이 바뀌었나)
      ↓
경고 조립 → 토큰 스트리밍 → event: result
```

## 검증을 MCP 로 뺀 이유가 이 스텝에 다 있다

세 검증은 **LLM 을 부르지 않는 순수 함수**다. 그래서 워크플로우가 직접 불러도 안전하고,
캔버스에서 "구조가 깨졌으면 사람 확인 노드로" 같은 분기를 걸 수 있다. 예전에는 이 판정이
`main.py` 안에 묻혀 있어 결과 문자열로만 드러났다.

**세 호출은 `asyncio.gather` 로 동시에 한다.** 서로 독립이고 전부 짧다.

## 검증 실패가 결과 전달을 막지 않는다

구조·사실 점검은 **되돌리지 않고 경고만** 노출한다 (원본 `fact_guard` 규율 그대로).
문서 전체를 되돌리면 기능 자체가 사라진다. 점검 호출이 실패해도 마찬가지로 진행하되,
**침묵하지 않고** 로그에 남긴다.

## 내려받기 (2026-08-12)

SFR-018 세 기능의 산출물이 txt 로 통일됐다. 파일은 이 스텝이 만들지 않는다 — 화면의
버튼이 코드서빙 `POST /download` 를 직접 부른다. 되돌려 보낼 값은 `polished_text` 이고,
경고·변경내역이 섞인 `text`(화면 표시용)가 아니다 — 파일에 "⚠ …" 나 변경내역 표가
들어가면 사용자가 메모장에서 그 줄들을 지워야 한다.
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

_LOG = logging.getLogger("text_polish")


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
        "error_type": "POLISH_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "문장 다듬기 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"{_AREA}-00020002",
        "error_type": "POLISH_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "문장 다듬기 결과를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "CONFIG_MISSING": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "POLISH_CONFIG_MISSING",
        "retryable": False,
        "msg": "서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
    },
    "INTERNAL": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "POLISH_INTERNAL_UNCLASSIFIED",
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

# LLM 이 뒤에 있는 호출. 전체 처리시간 안에서 개별 제한을 잡는다 (§B).
_POLISH_READ_TIMEOUT = 90.0
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


def _format_changes(changes: list) -> str:
    """변경 내역을 답변 끝에 붙일 마크다운으로 만든다."""
    if not changes:
        return ""
    lines = ["", "---", "", "**주요 변경 내역**", ""]
    for item in changes:
        before = str((item or {}).get("before") or "").strip()
        after = str((item or {}).get("after") or "").strip()
        if before and after:
            lines.append(f"- `{before}` → `{after}`")
    return "\n".join(lines) if len(lines) > 5 else ""


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

    # 앞 스텝 오류를 사용자에게 전달한다 — 중간 스텝은 스트리밍을 하지 않으므로
    # 여기서 말해 주지 않으면 화면이 빈 채로 끝난다.
    upstream_error = data.get("error")
    if upstream_error:
        _log_warning(
            "앞 스텝 오류를 사용자에게 전달",
            event="text_polish_error",
            error_code=str(upstream_error.get("error_code") or ""),
            status="final",
            **log_context,
        )
        async for event in finish_with_error(upstream_error):
            yield event
        return

    source_text = str(data.get("polish_source_text") or "")
    doc_type = str(data.get("polish_doc_type") or "")
    tone = str(data.get("polish_tone") or "")

    # 1) 다듬기 — LLM 호출·프롬프트 렌더는 코드서빙에 있다 (§D.3)
    body, failure = await _post_serving(
        "TEXT_POLISH_SERVING_ID",
        "/polish",
        {"text": source_text, "doc_type": doc_type, "tone": tone},
        read_timeout=_POLISH_READ_TIMEOUT,
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
            "글다듬이 호출 실패",
            event="polish_failed",
            error_code=error["error_code"],
            error_type=error_type,
            upstream_status=upstream_status,
            status="retryable" if error["retryable"] else "final",
            **log_context,
        )
        async for event in finish_with_error(error):
            yield event
        return

    polished = str((body or {}).get("polished_text") or "")
    if not polished:
        error = _error("UPSTREAM_EXECUTION")
        _log_warning(
            "다듬기 결과가 비어 있음",
            event="polish_empty_result",
            error_code=error["error_code"],
            error_type="EMPTY_RESULT",
            status="retryable",
            **log_context,
        )
        async for event in finish_with_error(error):
            yield event
        return

    # 2) 결정적 검증 3종 — 서로 독립이라 동시에 부른다. 실패해도 결과 전달을 막지 않는다.
    guard_calls = (
        ("markdown_structure_issues", {"source": source_text, "revised": polished}),
        ("fact_issues", {"source": source_text, "revised": polished}),
        ("diff_changes", {"source": source_text, "revised": polished}),
    )
    guard_results = await asyncio.gather(
        *(
            _mcp_call("TEXT_GUARD_MCP_ID", tool, args, read_timeout=_GUARD_READ_TIMEOUT)
            for tool, args in guard_calls
        )
    )

    structure_warnings: list = []
    fact_warnings: list = []
    changes: list = []
    for (tool, _args), (result, guard_failure) in zip(guard_calls, guard_results):
        if guard_failure is not None:
            # 점검 실패가 본 결과 전달을 막지 않는다. 다만 침묵 처리하지 않는다 —
            # 점검이 돌지 않았다는 사실이 로그에 남아야 "경고 없음" 과 구분된다.
            _log_warning(
                "결정적 점검 호출 실패 — 결과는 그대로 전달",
                event="text_guard_call_failed",
                resource_id=tool,
                error_type=guard_failure[1],
                upstream_status=guard_failure[2],
                status="degraded",
                **log_context,
            )
            continue
        payload = result or {}
        if tool == "markdown_structure_issues":
            structure_warnings = [str(w) for w in (payload.get("issues") or [])]
        elif tool == "fact_issues":
            fact_warnings = [str(w) for w in (payload.get("issues") or [])]
        else:
            changes = list(payload.get("changes") or [])

    if structure_warnings:
        _log_warning(
            "마크다운/HTML 구조 훼손 감지",
            event="structure_damaged",
            item_count=len(structure_warnings),
            **log_context,
        )
    if fact_warnings:
        # 어긋난 값은 남기지 않고 개수만 (3.8절). 값은 사용자 답변에만 실린다.
        _log_warning(
            "숫자·날짜 불일치 감지",
            event="fact_mismatch",
            item_count=len(fact_warnings),
            **log_context,
        )

    _log_info(
        "글다듬이 완료",
        event="polish_done",
        resource_id=f"{doc_type}/{tone}",
        item_count=len(changes),
        status=f"structure={len(structure_warnings)} fact={len(fact_warnings)}",
        **log_context,
    )

    # 3) 답변 조립
    notice = str(data.get("tone_notice") or "")
    if notice:
        notice = f"{notice}\n\n"
    for warning in structure_warnings:
        notice += f"⚠ {warning} 원문과 대조해 확인해 주세요.\n"
    # 사실 경고는 어긋난 값을 이미 담고 있어 "원문과 대조해" 를 덧붙이지 않는다 —
    # 어디를 볼지 안내문 자체가 가리킨다.
    for warning in fact_warnings:
        notice += f"⚠ {warning}\n"
    if structure_warnings or fact_warnings:
        notice += "\n"

    display_text = notice + polished + _format_changes(changes)

    # 4) 토큰 스트리밍 → result 1회
    for chunk in _stream_chunks(display_text):
        yield await emit_event("token", chunk)

    yield {
        "event": "result",
        "data": {
            **data,
            "text": display_text,
            "polished_text": polished,
            "changes": changes,
            "structure_warnings": structure_warnings,
            "fact_warnings": fact_warnings,
            "error": None,
        },
    }
