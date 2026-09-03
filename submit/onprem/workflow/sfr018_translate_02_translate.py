"""번역 스텝 2/2 — 번역 + 숫자 보존 검증 + 응답 (area 02, **마지막 스텝**).

캔버스에서 하는 일:

```
코드서빙 /translate/markdown  (스켈레톤 분해 + LLM + 용어사전 + 재조립)
      ↓ translated (정본) + `<mark>` 사본 두 벌
MCP text_guard.numeric_issues  (숫자·자릿수 보존 확인)  ← 먼저 띄우고 그 동안 흘린다
      ↓
event: token × N   ← **정본을 흘린다.** 원시 마크다운이 보여도 된다
      ↓
event: result      ← 좌우 하이라이트 비교 + 용어사전 안내로 **갈아 끼운다**
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

**내려받기는 txt 하나다** (2026-08-12). 파일은 이 스텝이 만들지 않는다 — 화면의
내려받기 버튼이 코드서빙 `POST /download` 를 직접 부른다(006 다운로드와 같은 배선).
그래서 이 스텝이 낼 것은 `translated_markdown` 까지이고, 그 값이 그대로 파일이 된다.
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
    "UPSTREAM_FINAL": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TRANSLATE_UPSTREAM_FINAL",
        "retryable": False,
        "msg": "요청을 처리하지 못했습니다. 관리자에게 문의해 주세요.",
    },
    "INTERNAL": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TRANSLATE_INTERNAL",
        "retryable": False,
        "msg": "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    # 유닛이 **전량** 원문으로 폴백된 상태. 코드서빙은 200 을 내지만(부분 실패도 같은
    # 경로라) 그 본문은 번역이 아니라 **원문 그대로**다 — 그대로 흘려보내면 사용자는
    # 자기가 넣은 글을 번역문으로 받는다. 아래 "전량 폴백" 주석 참고.
    "ALL_FALLBACK": {
        "error_code": f"{_AREA}-00020002",
        "error_type": "TRANSLATE_ALL_UNITS_FAILED",
        "retryable": True,
        "msg": "번역에 실패해 원문이 그대로 남았습니다. 잠시 후 다시 시도해 주세요.",
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
# 토큰 스트리밍 (2026-09-01 되살림)
# ─────────────────────────────────────────────────────────────
#
# 2026-08-28 에 없앴다가 요구가 바뀌어 되살렸다 — **번역문이 "AI 가 주루룩 답변하는"
# 것처럼 보여야 한다.** 근거와 규약은 글다듬이 스텝과 같고, 여기만 다른 것이 하나 있다.
#
# ## 여기서는 사본이 **이미 와 있다** — 그래도 정본을 흘린다
#
# 번역은 `<mark>` 사본을 코드서빙이 응답에 함께 실어 준다(글다듬이는 MCP 를 한 번 더
# 불러야 생긴다). 그래서 사본을 흘릴 수도 있지만 **흘리지 않는다**:
#
#   - 태그가 조각 경계에서 갈리면 화면에 `<ma` 같은 부스러기가 남는다.
#   - 흘리는 것과 `result` 가 같아지면 **하이라이트가 스트리밍 중에 이미 나타나** 요구가
#     말한 순서("스트리밍부터 하고 끝나면 한 번에 하이라이트")와 어긋난다.
#   - 두 단위가 다른 것을 흘리면 규약이 갈리고, 그 어긋남은 오류로 드러나지 않는다.
#
# ## 흘리는 시점 — **되돌릴 수 없게 된 뒤에만**
#
# 전량 폴백 판정(아래)까지 끝난 뒤에 흘린다. 그 판정은 응답이 200 이고 본문도 비어
# 있지 않은데 **사용자 원문이 그대로 돌아온** 경우를 오류로 세우는 자리다 — 그 앞에서
# 흘리면 원문을 번역문인 양 화면에 뿌린 뒤 오류로 갈아엎게 된다.
#
# ## 조각 크기는 문서 길이에 따라 늘린다
#
# 32자 고정이면 긴 문서에서 소켓 메시지 수가 문서 길이에 비례한다. 총 emit 수에 상한을
# 두고 조각을 키운다.
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

        `{**data}` 는 앞 스텝이 넣은 값과 캔버스 입력을 전부 실어 나른다. 여기서 필드를
        빼도 그것들이 그대로 프론트에 가므로 **"화면이 보는 값만 싣는다" 가 겉모양만
        지켜진다.** 마지막 스텝이라 다음 스텝에 넘길 `data` 도 없다.

        남기는 것은 `genos_state` 하나 — 플랫폼 추적(`trace_id`)이라 잃으면 로그가
        요청 간에 안 이어진다. 내려받기는 `download_url` 이라 세션 값이 필요 없다.
        """
        state = data.get("genos_state")
        return {"genos_state": state} if state is not None else {}

    async def finish_with_error(error: dict):
        # `error` 는 **오류일 때만** 나간다 (2026-08-28) — 글다듬이 스텝과 같은 규약.
        yield {"event": "result", "data": {**_base_payload(), "error": error}}

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
            # 서빙이 결과 txt 를 굳혀 올릴 때 파일명이 된다 (2026-08-28).
            "title": str(data.get("translate_title") or ""),
        },
        read_timeout=_TRANSLATE_READ_TIMEOUT,
    )

    if failure is not None:
        kind, error_type, upstream_status = failure
        key = (
            "CONFIG_MISSING" if kind == "config"
            else "UPSTREAM_TIMEOUT" if kind == "transport"
            # 서빙이 재시도 불가로 못 박은 응답은 그 판정을 그대로 따른다
            # (`_upstream_kind` 머리말 참고).
            else "UPSTREAM_FINAL" if kind == "upstream_final"
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
    # 코드서빙 `api_contract.markdown_payload` 의 필드 이름은 `markdown` 이다.
    # 2026-08-12 까지 `translated_markdown` 을 읽고 있었고 그 키는 응답에 없다 —
    # **번역이 매번 "결과가 비어 있음" 으로 끝나고 있었다.** 옛 이름도 함께 보는 이유는
    # 캔버스에 옛 스텝 사본이 남아 있을 수 있어서다(읽기는 공짜이고 쓰기는 아래에서 둘 다 낸다).
    translated = str(result.get("markdown") or result.get("translated_markdown") or "")
    # 사전 용어에 `<mark>` 이 입혀진 **표시용 사본** (2026-08-14). 없으면 정본을 쓴다 —
    # 옛 리비전의 코드서빙이 이 키를 안 낼 수 있고, 그때 화면이 비면 안 된다.
    highlighted = str(result.get("markdown_highlighted") or translated)
    # 원문 사본 (2026-08-28) — 화면이 원문과 번역문을 좌우로 놓고 비교하므로 **양쪽에**
    # 칠한다. 없으면 원문 그대로 쓴다(옛 리비전의 서빙이 이 키를 안 낼 수 있다).
    source_highlighted = str(result.get("source_markdown_highlighted") or "")
    download_url = str(result.get("download_url") or "") or None
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

    # ── 전량 폴백을 성공으로 흘려보내지 않는다 (2026-08-14) ──
    #
    # 번역이 실패한 유닛은 **원문이 그대로 남는다**(코드서빙의 설계다 — 한 문장 실패로
    # 문서 전체를 버리지 않기 위해서다). 그래서 LLM 이 통째로 죽어도 응답은 200 이고
    # `markdown` 은 비어 있지 않다. 이 스텝은 그 둘만 보고 있었으므로 **사용자가 자기가
    # 넣은 글을 번역문으로 돌려받았고, 화면 어디에도 실패했다는 표시가 없었다.**
    # `translation_error` 는 응답에 계속 실려 있었지만 아무도 읽지 않았다.
    #
    # 전량 실패는 오류로, 부분 실패는 안내문으로 가른다 — 부분 실패까지 오류로 만들면
    # 한 문장 때문에 번역된 문서 전체를 못 보게 된다.
    translation_error = str(result.get("translation_error") or "")
    unit_count = int(stats.get("unit_count") or 0)
    failed_unit_count = int(stats.get("failed_unit_count") or 0)

    if translation_error and unit_count and failed_unit_count >= unit_count:
        # 설정 부재는 몇 번을 다시 눌러도 같은 자리에서 실패한다 — 재시도를 권하지 않는다
        key = "CONFIG_MISSING" if translation_error == "CONFIG_MISSING" else "ALL_FALLBACK"
        error = _error(key)
        _log_warning(
            "번역 유닛 전량 폴백 — 원문을 번역문으로 내보내지 않는다",
            event="translate_all_units_failed",
            error_code=error["error_code"],
            error_type=translation_error,
            item_count=unit_count,
            status="retryable" if error["retryable"] else "final",
            **log_context,
        )
        async for event in finish_with_error(error):
            yield event
        return

    # 2) 숫자 보존 확인 — 실패해도 번역 결과 전달을 막지 않는다.
    #
    # **먼저 띄워 두고 그 동안 토큰을 흘린다** (2026-09-01). 순서대로 하면 스트리밍이
    # 순수한 연출이 되고 전체 시간만 늘어난다.
    numeric_warnings: list = []
    guard_task = asyncio.ensure_future(
        _mcp_call(
            "TEXT_GUARD_MCP_ID",
            "numeric_issues",
            {"source": source_text, "revised": translated},
            read_timeout=_GUARD_READ_TIMEOUT,
        )
    )

    # 3) 토큰 스트리밍 — **정본을 흘린다** (사본이 아니다. 위 머리말 참고).
    # 여기까지 왔으면 전량 폴백 판정이 끝났으므로 흘린 뒤 오류로 갈아엎을 일이 없다.
    for chunk in _stream_chunks(translated):
        yield await emit_event("token", chunk)

    guard, guard_failure = await guard_task
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

    # `glossary.source` 는 dict 다. 통째로 찍으면 로그 한 칸에 중괄호가 들어가 검색이
    # 어렵다 — 왜 안 붙었는지를 말하는 `reason` 만 뽑는다(`not_applicable`(중·태·베·러)
    # 과 `file_not_found`(관리자가 손쓸 일)를 이 값으로 가른다).
    glossary_reason = str((glossary.get("source") or {}).get("reason") or "unknown")
    # 번역문이 **쓰지 않은** 사전 용어 수. 준수율(`compliance`)만으로는 "지킬 것이
    # 없어서 1.0" 과 "다 지켜서 1.0" 이 구분되지 않는다 — 건수가 그 둘을 가른다.
    unapplied_count = len(dict(glossary.get("term_map_unapplied") or {}))

    _log_info(
        "번역 완료",
        event="translate_done",
        resource_id=f"{source_lang or 'unknown'}->{target_lang}",
        item_count=int(stats.get("unit_count") or 0),
        status=(
            f"source={data.get('translate_source_kind') or 'unknown'}"
            f" glossary={glossary_reason}"
            f" compliance={glossary.get('compliance', 'n/a')}"
            f" unapplied={unapplied_count}"
            f" fallback={stats.get('fallback_rate', 'n/a')}"
            f" numeric={len(numeric_warnings)}"
        ),
        **log_context,
    )

    # ── 안내문 (2026-08-29) ────────────────────────────────────────────────
    #
    # 2026-08-28 에는 "disclaimer 가 확정되면 붙인다" 며 **판정만 하고 화면에는 아무것도
    # 내보내지 않는** 상태로 뒀다. 그 공백을 payload 의 `notice` 로 메운다.
    #
    # **용어사전 미준수는 우리가 다시 번역하지 않는다** (요구 확정, 2026-08-29). 자동
    # 재번역은 사용자가 고르지 않은 LLM 호출을 한 번 더 쓰면서 결과가 나아진다는 보장이
    # 없고, 화면의 좌우 하이라이트가 이미 **어느 용어가 반영되지 않았는지**를 보여 준다
    # (원문 쪽에만 형광이 남는다). 그래서 사실을 말하고 **다시 번역할지는 사용자가
    # 정한다.**
    #
    # 문구는 **이 파일 안 고정 한국어 문장**이다 (3.8절). 어느 용어인지·어느 문장인지는
    # 싣지 않고 **건수만** 말한다 — 용어와 본문은 문서 내용이고, 자리는 화면의 형광이
    # 이미 가리키고 있다.
    notices: list = []
    if unapplied_count:
        notices.append(
            f"용어사전 용어 {unapplied_count}개가 번역문에 반영되지 않았습니다"
            " (원문에서 형광으로 표시된 자리입니다)."
            " 다시 번역하면 반영될 수 있습니다."
        )
    if failed_unit_count:
        notices.append(
            f"문장 {failed_unit_count}개를 번역하지 못해 원문 그대로 두었습니다."
            " 다시 번역해 주세요."
        )
    if numeric_warnings:
        notices.append(
            f"원문과 번역문의 숫자·날짜가 {len(numeric_warnings)}곳 다릅니다."
            " 결과를 확인해 주세요."
        )

    # 흘린 정본을 **좌우 비교로 갈아 끼운다** (2026-09-01). 스트리밍 중에는 원시
    # 마크다운이 보이고, 이 이벤트가 오면 화면이 그 자리를 하이라이트 두 벌로 바꾼다.
    yield {
        "event": "result",
        "data": {
            **_base_payload(),
            # ── 좌우 비교 두 값 (2026-08-28) ────────────────────────────────
            # 화면은 이 둘을 나란히 놓고 그린다. **양쪽 다 `<mark>` 가 입혀져 있다.**
            # 이름에 `_highlighted` 를 붙이지 않는 이유는 글다듬이 스텝과 같다 — 정본이
            # payload 에서 빠져 사본이 한 벌뿐이라 구분할 대상이 없다.
            # 원문 쪽은 매칭된 용어를 전부 칠하므로, 오른쪽 짝이 비어 있으면
            # "사전 용어인데 번역이 그 말을 안 썼다" 가 화면에 그대로 보인다.
            "original_text": source_highlighted or source_text,
            "translated_text": highlighted,
            # 미리 굳혀 올린 txt 링크. 못 올렸으면 `None`.
            "download_url": download_url,
            # **있을 때만** 실린다 (`error` 와 같은 규약) — 늘 있는 빈 배열은 읽는 쪽이
            # "확인했다" 고 믿게 만든다.
            **({"notice": notices} if notices else {}),
        },
    }

    # ── payload 는 **사용자가 눈으로 보는 값만** 담는다 (2026-08-28) ────────
    #
    # 진단·지표는 우리가 로그로 갖는다 — 위 `event=translate_done` 이 원본 경로·용어사전
    # 사유·준수율·폴백률·숫자 경고 건수를 전부 싣는다. 프론트에 실어 보내면 화면이 그
    # 값을 어떻게 쓸지 각자 정하게 되고, 쓰지 않는 값은 아무도 안 읽는 채로 계약에 남는다.
    #
    #   `translated_markdown`(정본) → 파일이 됐다. 서빙이 굳혀 올리고 링크만 온다
    #   `source_markdown`           → `original_text` 로 이름을 맞췄다 (세 기능 공통)
    #   `translate_pairs`           → 좌우 비교가 **문서 전체 단위**라 유닛을 되짚을 일이
    #                                 없다. 문단별 정렬 비교로 가면 되살린다
    #   `translate_source_kind`     → 진단값. 로그의 `source=` 가 갖는다
    #   `translate_stats`           → 진단값. 로그의 `fallback=` 이 갖는다
    #   `glossary`                  → 준수율·미적용 사유는 **검수용**이다. 사용자가 보는
    #                                 것은 본문의 형광뿐이고, 로그의 `glossary=`·
    #                                 `compliance=` 가 운영 질문에 답한다
    #   `numeric_warnings`          → **`text` 에 `⚠` 줄로 이미 들어 있다.** 건수는 로그의
    #                                 `numeric=` 이 갖는다
