"""글다듬이 스텝 2/2 — 다듬기 + 결정적 검증 + 응답 (area 02, **마지막 스텝**).

캔버스에서 하는 일:

```
코드서빙 /polish  (LLM + 프롬프트)
      ↓ polished
MCP text_guard  ── markdown_structure_issues  (표·제목·코드펜스 훼손)
                ── fact_issues                (숫자·날짜 누락)
                ── diff_changes               (어느 낱말이 바뀌었나 + `<mark>` 사본)
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
경고문과 `<mark>` 이 섞인 `text`(화면 표시용)가 아니다 — 파일에 "⚠ …" 나 태그가
들어가면 사용자가 메모장에서 그것들을 지워야 한다.

## 변경 표시는 본문 하이라이트다 (2026-08-27)

답변 끝에 변경 내역 목록을 붙이던 것을 뗐다. 근거는 `_format_changes` 가 있던 자리의
주석에 있다.
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
    "UPSTREAM_FINAL": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "POLISH_UPSTREAM_FINAL",
        "retryable": False,
        "msg": "요청을 처리하지 못했습니다. 관리자에게 문의해 주세요.",
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


# ── 토큰 스트리밍은 없앴다 (2026-08-28) ─────────────────────────
#
# 전용 UI 가 결과를 한 번에 그리므로 채팅용 조립 문자열이 필요 없다. 그때
# `_stream_chunks`·`_STREAM_CHUNK_CHARS` 를 **지우지 않고 남겨 뒀는데** 부르는 곳이
# 0건이었다 — 018 마지막 스텝 셋 전부 그랬다(2026-08-30 정리).
#
# **006 은 다르다.** 그쪽은 전용 UI 가 없어 채팅이 곧 화면이라 스트리밍을 유지한다
# (`sfr006_03_commit.py`). 018 에 다시 붙일 일이 생기면 그 파일에서 옮겨 적는다 —
# 스텝은 자기완결이라 공용 모듈로 뺄 수 없다.


def _log_context(data: dict) -> dict:
    state = data.get("genos_state") or {}
    return {"trace_id": state.get("trace_id")}


# ── 변경 내역을 답변 끝에 목록으로 붙이지 않는다 (2026-08-27) ──────────
#
# 그전에는 `_format_changes` 가 `---` + "주요 변경 내역" + `- \`before\` → \`after\``
# 목록을 본문 뒤에 이어 붙였다. 요구가 반대였다 — **바뀐 낱말을 본문 그 자리에서**
# 보여 달라는 것이다(웹 번역기 방식). 목록은 세 가지가 나빴다:
#
#   - 본문을 다 읽고 아래로 내려가 대조해야 한다. 어느 문장의 이야기인지가 목록에 없다.
#   - 문장 단위라 어느 낱말이 손질됐는지가 묻힌다.
#   - 파일에 섞이면 안 되므로 `text`/`polished_text` 를 가르는 이유가 이 목록이었다.
#     (그 구분 자체는 남는다 — 경고문과 `<mark>` 태그가 파일에 들어가면 안 된다.)
#
# 지금은 MCP `diff_changes` 가 `highlighted`(`<mark>` 를 입힌 표시용 사본)를 내고
# 이 스텝은 그것을 화면에 흘린다. `changes[].span` 도 payload 에 그대로 실어 보내
# 프론트가 자기 방식으로 칠할 수 있게 한다.


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
        # `error` 는 **오류일 때만** 나간다 (2026-08-28). 정상 응답에 `error: null` 을
        # 넣지 않는다 — 있으나 없으나 같은 뜻이라 읽는 쪽이 분기를 두 벌 갖게 된다.
        # `msg` 가 화면 문구이고 `retryable` 은 캔버스가 재시도를 정하는 값이다.
        yield {"event": "result", "data": {**_base_payload(), "error": error}}

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
        # `title` 은 서빙이 결과 txt 를 굳혀 올릴 때 파일명이 된다 (2026-08-28).
        {
            "text": source_text,
            "doc_type": doc_type,
            "tone": tone,
            "title": str(data.get("polish_title") or ""),
        },
        read_timeout=_POLISH_READ_TIMEOUT,
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
    # 서빙이 미리 굳혀 올린 txt 링크. 못 올렸으면 빈 값이고 payload 에는 `None` 으로 간다.
    download_url = str((body or {}).get("download_url") or "") or None
    # 조각 수 (2026-08-29). 서빙이 문서를 나눠 다듬으므로 **일부 조각만 실패**할 수 있고,
    # 그 자리에는 원문이 그대로 들어 있다. 전량 실패는 서빙이 오류로 내므로 여기까지
    # 오지 않는다 — 여기서 보는 것은 언제나 부분 실패다.
    failed_chunk_count = int((body or {}).get("failed_chunk_count") or 0)
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
    # 바뀐 낱말에 `<mark>` 가 입혀진 **표시용 사본 둘**. 화면이 원문과 다듬은 글을 좌우로
    # 놓고 비교하므로 양쪽 다 필요하다 (2026-08-28). 점검이 실패하면 정본을 그대로
    # 쓴다 — 하이라이트를 못 얻었다고 다듬은 글을 못 보여줄 이유는 없다.
    highlighted = ""
    source_highlighted = ""
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
            highlighted = str(payload.get("highlighted") or "")
            source_highlighted = str(payload.get("source_highlighted") or "")

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
        status=(
            f"structure={len(structure_warnings)} fact={len(fact_warnings)}"
            f" failed_chunks={failed_chunk_count}"
        ),
        **log_context,
    )

    # ── 안내문 (2026-08-29) ────────────────────────────────────────────────
    #
    # 2026-08-28 에는 "disclaimer 가 확정되면 붙인다" 며 **판정만 하고 화면에는 아무것도
    # 내보내지 않는** 상태로 뒀다. 그 공백을 payload 의 `notice` 로 메운다 — 판정값은
    # 그대로이고, 사용자가 볼 수 없던 것을 볼 수 있게 만드는 것뿐이다.
    #
    # 문구는 **이 파일 안 고정 한국어 문장**이다 (3.8절). 어긋난 값 자체(어느 숫자가
    # 다른지)는 싣지 않고 **건수만** 말한다 — 값은 문서 내용이다.
    notices: list = []
    if failed_chunk_count:
        notices.append(
            f"문서 일부 구간({failed_chunk_count}곳)을 다듬지 못해 원문 그대로 두었습니다."
            " 다시 시도해 주세요."
        )
    if structure_warnings:
        notices.append(
            f"표·제목 등 문서 구조가 원문과 달라진 곳이 {len(structure_warnings)}곳 있습니다."
            " 결과를 확인해 주세요."
        )
    if fact_warnings:
        notices.append(
            f"숫자·날짜가 원문과 다른 곳이 {len(fact_warnings)}곳 있습니다."
            " 결과를 확인해 주세요."
        )

    # 토큰 스트리밍은 없앴다 (2026-08-28) — 화면이 좌우 비교를 한 번에 그린다.
    yield {
        "event": "result",
        "data": {
            **_base_payload(),
            # ── 좌우 비교 두 값 (2026-08-28) ────────────────────────────────
            # 화면은 이 둘을 나란히 놓고 그린다. **양쪽 다 `<mark>` 가 입혀져 있다** —
            # 삭제된 낱말은 원문에만, 새로 들어온 낱말은 다듬은 글에만 자리가 있다.
            #
            # **이름에 `_highlighted` 를 붙이지 않는다** (2026-08-28). 그 접미어는 정본과
            # 사본이 **둘 다** payload 에 있던 시절의 구분이었다. 정본이 빠진 지금은
            # 한 벌뿐이라, 접미어가 붙은 쪽만 사본처럼 읽혀 `original_text` 와 어긋난다.
            "original_text": source_highlighted or source_text,
            "polished_text": highlighted or polished,
            # 미리 굳혀 올린 txt 링크. 올리지 못했으면 `None` 이고, 화면은 "파일로 받을
            # 수 없다" 를 말할 수 있어야 한다.
            "download_url": download_url,
            # **있을 때만** 실린다 (`error` 와 같은 규약) — 늘 있는 빈 배열은 읽는 쪽이
            # "확인했다" 고 믿게 만든다.
            **({"notice": notices} if notices else {}),
        },
    }

    # ── payload 는 **사용자가 눈으로 보는 값만** 담는다 (2026-08-28) ────────
    #
    # 내부 판정·검증·진단은 우리가 로그로 갖는다. 프론트에 실어 보내면 화면이 그 값을
    # 어떻게 쓸지 각자 정하게 되고, 쓰지 않는 값은 **아무도 안 읽는 채로 계약에 남아**
    # 나중에 바꿀 때 발이 묶인다.
    #
    #   `polished_text`(정본)  → 파일이 됐다. 서빙이 굳혀 올리고 링크만 온다
    #   `changes`              → 사본을 만드는 **입력**이다. 운영 소비자가 0건이었다
    #   `structure_warnings`   → **`text` 에 `⚠` 줄로 이미 들어 있다.** 배열은 프론트가
    #   `fact_warnings`          자기 UI 로 그릴 때를 위한 것이었는데 그 소비자가 없다.
    #                            건수는 `event=structure_damaged`·`fact_mismatch` 로그가 갖는다
    #   `tone_overridden`      → 안내문이 `text` 머리에 이미 붙어 있다
    #   `tone_notice`
