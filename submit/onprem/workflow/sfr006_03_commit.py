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
    "UPSTREAM_FINAL": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TPL_UPSTREAM_FINAL",
        "retryable": False,
        "msg": "요청을 처리하지 못했습니다. 관리자에게 문의해 주세요.",
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

# ─────────────────────────────────────────────────────────────
# 서빙이 "재시도해도 같다" 고 말한 응답인가 (2026-08-14)
# ─────────────────────────────────────────────────────────────
# **상태코드가 아니라 응답 본문의 `error_code` 분류로 본다** (가이드 3.9.2 — 00020003 은
# 통신 실패(00020001)·실행 실패(00020002)가 아닌 나머지 전부이고, 서빙들은 이 분류에
# `retryable=False` 를 붙여 둔다).
#
# 상태코드만 보면 그 판정이 **경계에서 사라진다.** 서빙이 배포 구성 문제(프롬프트 부재·
# Gateway 설정 부재)를 재시도 불가로 갈라 놨는데, 스텝이 500 을 502 와 같은
# `UPSTREAM_EXECUTION`(retryable=True)으로 뭉치면 캔버스는 그대로 재시도를 걸고 사용자는
# **몇 번을 눌러도 같은 자리에서 실패하는 문제에 "잠시 후 다시 시도해 주세요" 를 반복해서
# 본다.** 스텝이 서빙의 판정을 덮어쓰지 않게 한다.
_FINAL_CODE_SUFFIX = "00020003"


def _upstream_kind(response) -> str:
    """실행 실패(`execution`)인가, 서빙이 못 박은 최종 실패(`upstream_final`)인가."""
    try:
        body = response.json()
    except (ValueError, TypeError):  # json.JSONDecodeError 는 ValueError 하위
        return "execution"
    if not isinstance(body, dict):
        return "execution"
    code = str(body.get("error_code") or "")
    return "upstream_final" if code.endswith(_FINAL_CODE_SUFFIX) else "execution"

_CONNECT_TIMEOUT = 3.0
_ATTEMPTS = 2


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
                    return None, (
                        _upstream_kind(response),
                        "HTTPStatusError",
                        response.status_code,
                    )
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


# ─────────────────────────────────────────────────────────────
# 스트리밍
# ─────────────────────────────────────────────────────────────
# 조각 크기는 글 길이에 따라 늘린다 (2026-09-01, 018 두 스텝과 사본을 맞췄다).
# 32자 고정이면 emit 수가 글 길이에 비례해 긴 글에서 소켓 메시지 수가 그대로 부하가
# 된다. **이 스텝의 답변은 대개 짧아 동작이 바뀌지 않는다** — 12,800자 미만에서는
# `max(32, ceil(len/400))` 이 32 라 예전과 같은 조각이 나온다. 사본 셋을 갈라 두면
# 한쪽만 고쳐지고, 그 어긋남은 오류로 드러나지 않는다.
_STREAM_CHUNK_CHARS = 32
_STREAM_MAX_EMITS = 400


def _stream_chunks(text: str):
    size = max(_STREAM_CHUNK_CHARS, -(-len(text) // _STREAM_MAX_EMITS))
    for start in range(0, len(text), size):
        yield text[start: start + size]


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

    def _base_payload() -> dict:
        """마지막 스텝의 result 뼈대 — **`{**data}` 를 쓰지 않는다** (2026-08-28).

        `{**data}` 는 앞 스텝이 넣은 값을 전부 실어 나른다(`field_names`·`block_styles`·
        `fields_updated` …). 스텝 3 에서 필드를 빼도 그것들이 그대로 프론트에 가므로,
        **"화면이 보는 값만 싣는다" 가 겉모양만 지켜진다.** 그래서 여기서 뼈대를 새로
        만든다. 마지막 스텝이라 다음 스텝에 넘길 `data` 도 없다.

        남기는 것은 화면 밖 두 가지다:
        - `genos_state` — 플랫폼 추적(`trace_id`). 잃으면 로그가 요청 간에 안 이어진다.
        - `session_id`·`template_id` — **다운로드 버튼이 `POST /generate` 를 부를 때**
          쓴다. 화면에 보이지는 않지만 버튼이 동작하려면 있어야 한다.
        """
        payload: dict = {}
        state = data.get("genos_state")
        if state is not None:
            payload["genos_state"] = state
        for key in ("session_id", "template_id"):
            value = data.get(key)
            if value:
                payload[key] = value
        return payload

    async def finish_with_error(error: dict):
        """오류 문구를 스트리밍하고 result 로 마무리한다. 마지막 스텝의 의무다."""
        for chunk in _stream_chunks(error["msg"]):
            yield await emit_event("token", chunk)
        yield {"event": "result", "data": {**_base_payload(), "text": error["msg"], "error": error}}

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
        "TEMPLATE_FILL_SERVING_ID",
        "/chat/commit",
        {
            "session_id": str(data.get("session_id") or ""),
            "template_id": str(data.get("template_id") or ""),
            "fields_updated": data.get("fields_updated") or {},
            "fields_cleared": data.get("fields_cleared") or [],
            "fields_rejected": data.get("fields_rejected") or [],
            "blocks_added": data.get("blocks_added") or [],
            "block_clears": data.get("block_clears") or [],
            # 스텝 1 의 문서 자동 채움분 (2026-08-31). **여기서 처음 저장된다** —
            # 스텝 1 은 뽑기만 하고 저장은 커밋 한 곳에서 한다(한 턴에 두 곳에서
            # 저장하면 순서에 따라 서로를 덮는다). `source_doc_hash` 를 빠뜨리면 세션
            # 표식이 지워져 **다음 턴에 같은 문서를 또 태우고 사용자가 지운 값이
            # 되살아난다** — 저장이 덮어쓰기라 그렇다.
            "fields_prefilled": data.get("fields_prefilled") or {},
            "source_doc_hash": str(data.get("source_doc_hash") or ""),
            "prefill_failed": bool(data.get("prefill_failed")),
            # 건너뛴 사유 (2026-09-02). 답변 문구가 여기서 갈린다 — 빼면 "파일을 올렸는데
            # 아무 일도 일어나지 않는" 턴이 생긴다(항목을 다 채운 뒤 올린 경우).
            "prefill_skipped_reason": str(data.get("prefill_skipped_reason") or ""),
        },
        read_timeout=30.0,
    )

    if failure is not None:
        kind, error_type, upstream_status = failure
        if kind == "config":
            key = "CONFIG_MISSING"
        elif kind == "transport":
            key = "UPSTREAM_TIMEOUT"
        elif kind == "upstream_final":
            # 서빙이 재시도 불가로 못 박은 응답은 그 판정을 그대로 따른다
            # (`_upstream_kind` 머리말 참고).
            key = "UPSTREAM_FINAL"
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

    # ── payload 는 **사용자가 눈으로 보는 값만** 담는다 (2026-08-28) ────────
    #
    # 이 기능은 앞의 셋과 방향이 반대다. **전용 UI 가 없고 채팅이 곧 화면**이라
    # `text` 를 뺄 수 없다 — `chat_reply` 가 조립하는 그 문장이 이 기능의 출력이다.
    # 그리고 그 문장이 **이미 다 말한다**: 새로 채운 항목과 `이전 → 새 값`, 기각 건수,
    # 본문 추가 번호 목록, 남은 항목, 다음에 할 일.
    #
    # 그래서 같은 내용을 배열로 한 번 더 싣던 값들을 뺐다. 폼처럼 항목 칸을 나열하는
    # 화면이 생기면 `field_values`·`fields_filled` 를 되살린다 — 그때는 안내문이
    # 아니라 칸마다 현재 값이 필요하다.
    #
    #   `field_values` / `fields_filled` / `fields_missing` → 안내문이 말한다
    #   `fields_cleared` / `fields_rejected`               → 안내문이 말한다
    #   `blocks` / `blocks_removed`                        → 안내문이 번호를 붙여 나열한다
    #   `field_values_raw`                                 → 정규화 **전** 원값. 화면에 쓸 자리가 없다
    #   `document_markdown_truncated`                      → 미리보기 길이 상한 표시(내부)
    #
    # **`text` 는 지운다** — `{**data}` 가 실어 나르는 그 값은 **사용자 질문**이라
    # 아래에서 이번 턴 답변으로 덮는다(세 기능은 아예 안 싣지만 여기는 답변이 곧 text 다).
    yield {
        "event": "result",
        "data": {
            **_base_payload(),
            "text": display_text,
            # 다운로드 버튼을 켜는 값. 안내문도 "다운로드 버튼을 누르면" 이라고 말하지만,
            # 버튼 활성 여부는 문장이 아니라 이 불리언으로 정해져야 한다.
            "ready_for_download": not fields_missing,
            # 미리보기 — **채팅 문장에는 들어가지 않는다.** 문서 창이 따로 그린다.
            "document_markdown": result.get("document_markdown") or "",
            "error": None,
        },
    }
