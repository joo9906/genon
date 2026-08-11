"""번역 스텝 1/2 — 언어 감지 + 방향 검증 (area 02).

**이 스텝은 신규다.** 번역은 지금 코드서빙 전용이라 캔버스에 노드가 없다.

캔버스에서 하는 일: 원본 언어를 감지하고 `원본→대상` 쌍이 **한국어 축**을 지나는지 검증한다.
`en→ru` 같은 비한국어 쌍은 여기서 막힌다 (요구사항 §6).

## 왜 이 판정이 LLM 이 아닌가

**거부 판정**이기 때문이다. 사용자의 요청을 막는 판단을 LLM 에 맡기면 같은 입력에 대해
어떤 날은 통과하고 어떤 날은 막힌다. 스크립트(문자 체계) 기반으로 결정적으로 감지한다 —
그래서 MCP 도구(`lang_policy`)로 뺄 수 있었다.

**감지 불가는 거부가 아니다.** 숫자·기호뿐인 입력은 방향 검증만 건너뛰고 번역은 진행한다.

## 원본 확보는 여기서 하지 않는다

번역 입력은 마크다운 텍스트이고 `genosUploaded` 로 온다. hwpx 직접 업로드 경로
(`POST /translate/hwpx`)는 **워크플로우를 지나지 않는다** — 코드서빙을 직접 부르는
업로드 경로라 이 스텝의 관심사가 아니다.
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

_LOG = logging.getLogger("translate_detect")


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
        "error_type": "TRANSLATE_DETECT_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "언어 확인 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"{_AREA}-00020002",
        "error_type": "TRANSLATE_DETECT_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "언어를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "INPUT_EMPTY": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TRANSLATE_INPUT_EMPTY",
        "retryable": False,
        "msg": "번역할 문서나 텍스트를 입력해 주세요.",
    },
    "TARGET_MISSING": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TRANSLATE_TARGET_MISSING",
        "retryable": False,
        "msg": "번역할 언어를 선택해 주세요.",
    },
    "UNSUPPORTED_PAIR": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TRANSLATE_UNSUPPORTED_PAIR",
        "retryable": False,
        "msg": "한국어가 포함된 번역만 지원합니다. 원본 또는 번역 언어를 한국어로 선택해 주세요.",
    },
    "CONFIG_MISSING": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TRANSLATE_CONFIG_MISSING",
        "retryable": False,
        "msg": "서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
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
# MCP 호출 (§H)
# ─────────────────────────────────────────────────────────────
_RETRY_STATUS = frozenset({502, 503, 504})
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
                    return None, ("execution", "HTTPStatusError", response.status_code)
            if attempt < _ATTEMPTS - 1:
                await asyncio.sleep(0.3 * (attempt + 1))
    return None, failure


async def _mcp_call(env_name: str, tool: str, arguments: dict, *, read_timeout: float = 15.0):
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
# 입력
# ─────────────────────────────────────────────────────────────
_DOC_TAG_RE = re.compile(r"<doc[^>]*>(.*?)</doc>", re.DOTALL)

# 방향 검증에 문서 전체를 보낼 필요가 없다. 앞부분만으로 문자 체계는 판정된다 —
# 문서 원문을 게이트웨이로 통째로 흘리는 것도 피한다 (3.8절 취지).
_DETECT_SAMPLE_CHARS = 2000


def _extract_uploaded_markdown(genos_uploaded: str) -> str:
    if not genos_uploaded:
        return ""
    matches = _DOC_TAG_RE.findall(genos_uploaded)
    if matches:
        return "\n\n".join(m.strip() for m in matches if m.strip())
    return genos_uploaded.strip()


def _log_context(data: dict) -> dict:
    state = data.get("genos_state") or {}
    return {"trace_id": state.get("trace_id")}


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

    question = (data.get("question") or data.get("text") or "").strip()
    variables = (data.get("overrideConfig") or {}).get("vars") or {}

    source_text = _extract_uploaded_markdown(variables.get("genosUploaded") or "") or question
    if not source_text:
        error = _error("INPUT_EMPTY")
        _log_warning(
            "번역할 원본 없음",
            event="translate_input_empty",
            error_code=error["error_code"],
            status="final",
            **log_context,
        )
        return {**data, "error": error}

    target_lang = str(variables.get("translate_target_lang") or "").strip()
    if not target_lang:
        error = _error("TARGET_MISSING")
        _log_warning(
            "대상 언어 미지정",
            event="translate_target_missing",
            error_code=error["error_code"],
            status="final",
            **log_context,
        )
        return {**data, "error": error}

    verdict, failure = await _mcp_call(
        "LANG_POLICY_MCP_ID",
        "validate_direction",
        {
            "sample": source_text[:_DETECT_SAMPLE_CHARS],
            "target_lang": target_lang,
            "source_lang": str(variables.get("translate_source_lang") or ""),
        },
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
            "언어 방향 검증 실패",
            event="lang_direction_failed",
            error_code=error["error_code"],
            error_type=error_type,
            upstream_status=upstream_status,
            status="retryable" if error["retryable"] else "final",
            **log_context,
        )
        return {**data, "error": error}

    verdict = verdict or {}
    source_lang = str(verdict.get("source_lang") or "")
    detected = bool(verdict.get("detected"))

    if not verdict.get("allowed", False):
        error = _error("UNSUPPORTED_PAIR")
        _log_warning(
            "지원하지 않는 번역 방향",
            event="translate_pair_rejected",
            error_code=error["error_code"],
            resource_id=f"{source_lang or 'unknown'}->{target_lang}",
            status="final",
            **log_context,
        )
        return {**data, "error": error}

    if not detected:
        # 감지 불가는 거부가 아니다 — 방향 검증만 건너뛰고 진행한다
        _log_warning(
            "원본 언어 감지 불가 — 방향 검증을 건너뛴다",
            event="lang_detect_skipped",
            resource_id=f"unknown->{target_lang}",
            status="degraded",
            **log_context,
        )

    _log_info(
        "번역 방향 확정",
        event="translate_direction_resolved",
        resource_id=f"{source_lang or 'unknown'}->{target_lang}",
        item_count=len(source_text.splitlines()),
        status="detected" if detected else "undetected",
        **log_context,
    )

    return {
        **data,
        "translate_source_text": source_text,
        "translate_source_lang": source_lang,
        "translate_target_lang": target_lang,
        "translate_source_detected": detected,
        "translate_register": str(variables.get("translate_register") or ""),
        "error": None,
    }
