"""SFR-006 스텝 2/3 — 발화에서 값·삭제·본문 블록 추출 (area 02).

캔버스에서 하는 일: 사용자 발화를 코드서빙에 넘겨 **LLM 추출 + 코드 판정**을 받는다.
결과는 `fields_updated`/`fields_rejected` 로 캔버스에 드러난다.

## 판정 책임 분리는 그대로다

- **LLM**: 발화 → `{항목명: 값}` + 지울 항목 + 본문 블록 추출까지만.
- **코드(코드서빙)**: 화이트리스트 검증, 값 보존 확인, 서식 이름 검증. 전부 결정적이다.

**LLM 호출과 프롬프트 렌더는 코드서빙에 있다.** 프롬프트 jinja 파일(`onprem/prompt/`)과
`jinja2` 가 그쪽에만 있기 때문이고(§D.3), 이 스텝은 그 결과를 받기만 한다.
지금 구현도 LLM 응답을 **전부 받은 뒤** 청크로 잘라 emit 했으므로 UI 동작은 달라지지 않는다.

## 발화가 비어 있으면 LLM 을 부르지 않는다

첫 진입(템플릿만 고르고 아직 말하지 않은 턴)이 그렇다. 그때는 추출 결과를 빈 값으로 두고
다음 스텝이 현재 상태만 보여준다 — 빈 발화로 LLM 을 부르면 항목을 지어낸다.
"""

import asyncio
import json
import logging
import os
import sys

import httpx

# ─────────────────────────────────────────────────────────────
# 로깅 (§C / 가이드 3.8)
# ─────────────────────────────────────────────────────────────
_ALLOWED_LOG_FIELDS = frozenset({
    "event", "trace_id", "request_id", "resource_id", "status",
    "duration_ms", "item_count", "upstream_status", "error_code", "error_type",
})

_LOGGER_NAME = "sfr006_extract"
_LOG = logging.getLogger(_LOGGER_NAME)


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


# ─────────────────────────────────────────────────────────────
# 디버그 에코 — **테스트 기간 한정** (2026-09-07)
# ─────────────────────────────────────────────────────────────
# 3.8절 화이트리스트가 값을 버리기 때문에(허용 목록 밖은 **이름만** 남는다) 로그만으로는
# 무엇이 왜 실패했는지 알 수 없다 — 특히 게이트웨이가 거절한 **사유는 응답 본문에만**
# 적혀 있고 그 본문은 어디에도 남지 않는다(MCP 406 을 찾는 데 걸린 시간이 그것이다).
# 원인을 찾는 동안 표준 로그와 **별도로** 한 줄을 더 뿜는다. 로그 경로는 그대로다 —
# 걷어낼 때 이 블록과 `_debug_echo` 호출만 지우면 원래 규약으로 돌아온다.
#
# - **stdout 이 아니라 stderr 로 쓴다.** stdout 은 스트리밍·MCP 의 전송 채널이라 섞이면
#   프로토콜이 깨진다 (3.10절이 print 를 금지하는 실제 이유다).
# - `GENON_DEBUG=0` 이면 조용해진다. **기본은 켜짐** — 지금은 원인 추적이 목적이다.
# - 값은 `_DEBUG_MAX_VALUE` 로 자른다. 문서 원문이 통째로 실리면 이 에코 자체가 유출
#   경로가 된다(3.8절).
_DEBUG_MAX_VALUE = 300


def _debug_echo(message: str, *, event: str = "", **fields) -> None:
    if (os.environ.get("GENON_DEBUG") or "1").strip().lower() in {"0", "false", "off"}:
        return
    parts = [f"event={event}"] if event else []
    for key, value in fields.items():
        text = str(value)
        if len(text) > _DEBUG_MAX_VALUE:
            text = f"{text[:_DEBUG_MAX_VALUE]}…(+{len(text) - _DEBUG_MAX_VALUE}자)"
        parts.append(f"{key}={text}")
    sys.stderr.write(f"[DEBUG {_LOGGER_NAME}] {message} | {' '.join(parts)}\n")
    sys.stderr.flush()


def _log_info(message: str, *, event: str, **fields) -> None:
    _emit_log(logging.INFO, message, event=event, **fields)


def _log_warning(message: str, *, event: str, **fields) -> None:
    _debug_echo(f"WARNING {message}", event=event, **fields)
    _emit_log(logging.WARNING, message, event=event, **fields)


# ─────────────────────────────────────────────────────────────
# 오류표 (§A)
# ─────────────────────────────────────────────────────────────
_AREA = "02"

_ERRORS = {
    "UPSTREAM_TIMEOUT": {
        "error_code": f"ERR-{_AREA}-00020001",
        "error_type": "TPL_EXTRACT_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "문서 작성 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"ERR-{_AREA}-00020002",
        "error_type": "TPL_EXTRACT_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "말씀하신 내용을 항목으로 정리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "CONFIG_MISSING": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "TPL_CONFIG_MISSING",
        "retryable": False,
        "msg": "서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
    },
    "UPSTREAM_FINAL": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "TPL_UPSTREAM_FINAL",
        "retryable": False,
        "msg": "요청을 처리하지 못했습니다. 관리자에게 문의해 주세요.",
    },
    "INTERNAL": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "TPL_EXTRACT_INTERNAL",
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

# LLM 이 뒤에 있으므로 컨텍스트 조회보다 길게 잡는다. 전체 처리시간 안에서
# 개별 호출 제한을 잡는 규칙(§B)에 따라 60s 를 넘기지 않는다.
_EXTRACT_READ_TIMEOUT = 60.0


def _gateway_base() -> str:
    base = (os.environ.get("GENOS_URL") or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("GENOS_URL is not configured")
    return base if base.endswith("/api/gateway") else f"{base}/api/gateway"


def _decode_body(response):
    """응답 본문을 파이썬 객체로 되돌린다 (실패 시 `json.JSONDecodeError`).

    **MCP 를 부르는 스텝과 같은 사본이다** (`check_deploy_contract` 의 사본 일치 판정).
    그쪽에서 필요한 이유는 이렇다: MCP 는 같은 `tools/call` 에 두 가지 모양으로 답한다 —
    서버가 JSON 응답 모드면 `application/json` 한 덩어리, 기본(스트리머블)이면
    `text/event-stream` 프레임에 담아 준다. `response.json()` 만 쓰면 후자에서
    `InvalidJson` 으로 떨어지는데, 그 상태는 **통신도 되고 도구도 돌았는데 결과만
    사라지는** 형태라 원인이 드러나지 않는다. 코드서빙 응답은 늘 JSON 이라 이 스텝에서는
    첫 분기로 끝난다.
    """
    ctype = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype != "text/event-stream":
        return response.json()

    text = (response.text or "").replace("\r\n", "\n").replace("\r", "\n")
    fallback = None
    for block in text.split("\n\n"):
        data = "\n".join(
            line.split(":", 1)[1].strip()
            for line in block.splitlines()
            if line.startswith("data:")
        ).strip()
        if not data:
            continue
        try:
            frame = json.loads(data)
        except json.JSONDecodeError:
            continue
        # 진행 알림(`method` 를 든 프레임)이 응답보다 **먼저** 실릴 수 있다.
        # 마지막 프레임을 집으면 알림을 응답으로 읽는다 — `result`/`error` 가 응답이다.
        if isinstance(frame, dict) and ("result" in frame or "error" in frame):
            return frame
        fallback = frame
    if fallback is None:
        raise json.JSONDecodeError("no JSON-RPC frame in SSE body", text, 0)
    return fallback


async def _post_json(url: str, payload: dict, *, read_timeout: float,
                     extra_headers: dict | None = None):
    headers = {"Authorization": f"Bearer {(os.environ.get('GENOS_TOKEN') or '').strip()}"}
    if extra_headers:
        headers.update(extra_headers)
    timeout = httpx.Timeout(
        connect=_CONNECT_TIMEOUT, read=read_timeout, write=5.0, pool=_CONNECT_TIMEOUT
    )
    failure = ("transport", "NoAttempt", None)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(_ATTEMPTS):
            _debug_echo(
                "POST 요청",
                event="http_request",
                url=url,
                attempt=attempt + 1,
                accept=headers.get("Accept", "*/*"),
                payload_keys=",".join(sorted(payload)),
            )
            try:
                response = await client.post(url, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                _debug_echo(
                    "전송 실패", event="http_transport_error", url=url, exc=repr(exc)
                )
                failure = ("transport", type(exc).__name__, None)
            else:
                if response.status_code < 400:
                    try:
                        return _decode_body(response), None
                    except (json.JSONDecodeError, ValueError):
                        return None, ("execution", "InvalidJson", response.status_code)
                _debug_echo(
                    "HTTP 오류 응답",
                    event="http_error",
                    url=url,
                    status=response.status_code,
                    content_type=response.headers.get("content-type", ""),
                    body=response.text,
                )
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


_EMPTY_EXTRACTION = {
    "fields_updated": {},
    "fields_cleared": [],
    "fields_rejected": [],
    "blocks_added": [],
    "block_clears": [],
}


def _log_context(data: dict) -> dict:
    state = data.get("genos_state") or {}
    return {"trace_id": state.get("trace_id")}


async def run(data: dict) -> dict:
    if not isinstance(data, dict):
        data = {"question": str(data)}
    log_context = _log_context(data)

    # 앞 스텝(컨텍스트 확정)이 실패했으면 그대로 통과 (§A.4)
    if data.get("error"):
        return data

    question = (data.get("question") or "").strip()
    template_id = str(data.get("template_id") or "").strip()
    session_id = str(data.get("session_id") or "").strip()

    # 발화가 없는 턴 — LLM 을 부르지 않는다. 빈 발화로 부르면 항목을 지어낸다.
    if not question:
        _log_info(
            "발화 없음 — 추출을 건너뛴다",
            event="extract_skipped_no_question",
            resource_id=f"{template_id}.hwpx",
            status="skipped",
            **log_context,
        )
        return {**data, **_EMPTY_EXTRACTION, "error": None}

    body, failure = await _post_serving(
        "TEMPLATE_FILL_SERVING_ID",
        "/chat/extract",
        {
            "session_id": session_id,
            "template_id": template_id,
            "question": question,
        },
        read_timeout=_EXTRACT_READ_TIMEOUT,
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
            "발화 추출 실패",
            event="extract_failed",
            error_code=error["error_code"],
            error_type=error_type,
            upstream_status=upstream_status,
            status="retryable" if error["retryable"] else "final",
            **log_context,
        )
        return {**data, "error": error}

    result = body or {}
    updated = dict(result.get("fields_updated") or {})
    rejected = list(result.get("fields_rejected") or [])
    cleared = list(result.get("fields_cleared") or [])
    added_blocks = list(result.get("blocks_added") or [])

    if rejected:
        # 기각 건수는 006 환각률 지표의 원천이다 — 침묵 처리하지 않는다.
        # 기각된 **이름**은 남기지 않는다(LLM 출력이다). 개수만 (3.8절).
        _log_warning(
            "템플릿에 없는 항목명을 기각",
            event="extraction_keys_rejected",
            item_count=len(rejected),
            **log_context,
        )

    _log_info(
        "발화 추출 완료",
        event="extract_done",
        resource_id=f"{template_id}.hwpx",
        item_count=len(updated),
        status=f"cleared={len(cleared)} blocks={len(added_blocks)} rejected={len(rejected)}",
        **log_context,
    )

    return {
        **data,
        "fields_updated": updated,
        "fields_cleared": cleared,
        "fields_rejected": rejected,
        "blocks_added": added_blocks,
        "block_clears": list(result.get("block_clears") or []),
        "error": None,
    }
