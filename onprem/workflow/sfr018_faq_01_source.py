"""FAQ 스텝 1/2 — 원본 확보 + 생성 개수 결정 (area 02).

캔버스에서 하는 일:

```
faq_hwpx_path 있음 → MCP hwpx_text.hwpx_to_markdown   (표 안 수치 보존)
             없음 → genosUploaded 파싱                (전처리기 산출물)
      ↓
서빙 /config 로 배포 상한 확인 → 캔버스 변수로 낮추기만 허용
```

## hwpx 직접 파싱이 MCP 로 간 이유

`lxml` 은 워크플로우 이미지에 없다 (§D.3). 그리고 이 파서는 지금 번역(243줄)·FAQ(227줄)에
**사실상 동일한 사본**으로 두 벌 있다 — MCP 한 벌로 합치면 그 중복이 사라진다.

## 개수 상한은 두 층이다

배포 상한(`FAQ_MAX_COUNT`, 코드서빙 환경변수) 안에서만 캔버스 변수(`faq_max_count`)로
**낮출 수** 있다. 캔버스가 상한을 넘길 수 있으면 LLM 예산 상한이 설정 하나로 무력해진다.
그래서 상한 판정은 코드서빙 `/config` 가 하고 이 스텝은 받아 적용만 한다.

**`faq_count` 는 "문서 한 구간에서 뽑을 개수" 다** (2026-08-31 의미 변경). 전체 개수로
두면 긴 문서에서 그 개수를 구간들이 나눠 가져 구간당 몫이 0~1개가 됐다 — 그 구간을
대표하는 FAQ 가 나올 수 없다. 문서 하나의 총량은 코드서빙의 `FAQ_MAX_TOTAL_COUNT`
(기본 30 = 구간당 5개 × 여섯 구간)가 잡고, 그 값은 `/config` 의 `total_max_count` 로
나온다 — 화면이 "5개 요청 → 28개 결과" 를 설명할 수 있어야 한다.

## 원본을 못 구하면 빈 답변으로 감추지 않는다

업로드가 없으면 여기서 오류로 끝낸다 — FAQ 0건을 정상 응답처럼 내려보내는 쪽이 나쁘다.
"""

import asyncio
import json
import logging
import os
import re

import httpx

# ─────────────────────────────────────────────────────────────
# 로깅 (§C / 가이드 3.8)
# ─────────────────────────────────────────────────────────────
_ALLOWED_LOG_FIELDS = frozenset({
    "event", "trace_id", "request_id", "resource_id", "status",
    "duration_ms", "item_count", "upstream_status", "error_code", "error_type",
})

_LOG = logging.getLogger("faq_source")


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
        "error_type": "FAQ_SOURCE_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "문서 처리 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"{_AREA}-00020002",
        "error_type": "FAQ_SOURCE_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "문서를 읽지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "NO_INPUT": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "FAQ_NO_INPUT",
        "retryable": False,
        "msg": "FAQ 를 만들 문서를 첨부해 주세요.",
    },
    "DOC_INVALID": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "FAQ_DOC_INVALID",
        "retryable": False,
        "msg": "첨부한 문서에서 내용을 읽지 못했습니다. 다른 파일로 다시 시도해 주세요.",
    },
    "COUNT_ZERO": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "FAQ_COUNT_ZERO",
        "retryable": False,
        "msg": "생성할 FAQ 개수를 1개 이상으로 지정해 주세요.",
    },
    "CONFIG_MISSING": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "FAQ_CONFIG_MISSING",
        "retryable": False,
        "msg": "서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
    },
    "UPSTREAM_FINAL": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "FAQ_UPSTREAM_FINAL",
        "retryable": False,
        "msg": "요청을 처리하지 못했습니다. 관리자에게 문의해 주세요.",
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


async def _mcp_call(env_name: str, tool: str, arguments: dict, *, read_timeout: float = 30.0):
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


async def _get_serving(env_name: str, path: str, *, read_timeout: float = 10.0):
    """설정 조회는 GET 이다. 재시도 규칙은 POST 와 같다 (§B)."""
    serving_id = (os.environ.get(env_name) or "").strip()
    if not serving_id:
        return None, ("config", f"{env_name}_MISSING", None)
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
                response = await client.get(url, headers=headers)
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


# ─────────────────────────────────────────────────────────────
# 입력
# ─────────────────────────────────────────────────────────────
_DOC_TAG_RE = re.compile(r"<doc[^>]*>(.*?)</doc>", re.DOTALL)


def _extract_uploaded_markdown(genos_uploaded: str) -> str:
    if not genos_uploaded:
        return ""
    matches = _DOC_TAG_RE.findall(genos_uploaded)
    if matches:
        return "\n\n".join(m.strip() for m in matches if m.strip())
    return genos_uploaded.strip()


def _session_id(data: dict) -> str:
    """다운로드가 찾아올 키. 운영 브리지의 폴백 순서를 그대로 따른다."""
    state = data.get("genos_state") or {}
    for key in ("socketIOClientId", "sessionId", "session_id"):
        value = data.get(key) or state.get(key)
        if value:
            return str(value)
    return ""


def _log_context(data: dict) -> dict:
    state = data.get("genos_state") or {}
    return {"trace_id": state.get("trace_id")}


def _as_int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


async def run(data: dict) -> dict:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {"question": data}
    if not isinstance(data, dict):
        data = {"question": str(data)}

    log_context = _log_context(data)

    if data.get("error"):
        return data

    variables = (data.get("overrideConfig") or {}).get("vars") or {}
    hwpx_path = str(variables.get("faq_hwpx_path") or "").strip()

    # 1) 원본 확보 — hwpx 직접 파싱 우선 (요구사항 §5: 전처리기를 태우면 표 안 수치가 깨진다)
    source_text = ""
    source_kind = "preprocessor"
    if hwpx_path:
        parsed, failure = await _mcp_call(
            "HWPX_TEXT_MCP_ID", "hwpx_to_markdown", {"path": hwpx_path}
        )
        if failure is not None:
            # 실패해도 전처리기 산출물로 떨어진다 — 조용히 넘기지 않고 사유를 남긴다
            _log_warning(
                "hwpx 직접 파싱 실패 — 전처리기 산출물로 진행",
                event="faq_hwpx_parse_failed",
                error_type=failure[1],
                upstream_status=failure[2],
                status="degraded",
                **log_context,
            )
        else:
            source_text = str((parsed or {}).get("markdown") or "")
            if source_text:
                source_kind = "hwpx"

    if not source_text:
        source_text = _extract_uploaded_markdown(variables.get("genosUploaded") or "")

    if not source_text.strip():
        # hwpx 경로가 지정됐는데도 비었다면 "첨부 없음" 이 아니라 "읽지 못함" 이다
        error = _error("DOC_INVALID" if hwpx_path else "NO_INPUT")
        _log_warning(
            "FAQ 원본 확보 실패",
            event="faq_source_missing",
            error_code=error["error_code"],
            resource_id=source_kind,
            status="final",
            **log_context,
        )
        return {**data, "error": error}

    # 2) 개수 결정 — 배포 상한은 코드서빙이 정한다. 캔버스는 그 안에서 낮추기만 한다.
    config_body, failure = await _get_serving("FAQ_SERVING_ID", "/config")
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
            "FAQ 설정 조회 실패",
            event="faq_config_failed",
            error_code=error["error_code"],
            error_type=error_type,
            upstream_status=upstream_status,
            status="retryable" if error["retryable"] else "final",
            **log_context,
        )
        return {**data, "error": error}

    deploy_max = _as_int((config_body or {}).get("max_count"), 10)
    default_count = _as_int((config_body or {}).get("default_count"), 5)

    canvas_max = _as_int(variables.get("faq_max_count"), deploy_max)
    effective_max = max(0, min(deploy_max, canvas_max))  # 넘길 수 없고 낮출 수만 있다
    count = _as_int(variables.get("faq_count"), default_count)
    count = max(0, min(count, effective_max))

    if count <= 0:
        error = _error("COUNT_ZERO")
        _log_warning(
            "FAQ 생성 개수가 0",
            event="faq_count_zero",
            error_code=error["error_code"],
            status="final",
            **log_context,
        )
        return {**data, "error": error}

    # 문서 원문은 남기지 않는다 — 길이와 개수만 (3.8절)
    _log_info(
        "FAQ 원본 확보",
        event="faq_source_ready",
        resource_id=source_kind,
        item_count=count,
        status=f"max={effective_max},chars={len(source_text)}",
        **log_context,
    )

    return {
        **data,
        "faq_source_text": source_text,
        "faq_source_kind": source_kind,
        "faq_count": count,
        "faq_effective_max": effective_max,
        "faq_title": str(variables.get("faq_title") or ""),
        "faq_session_id": _session_id(data),
        "error": None,
    }
