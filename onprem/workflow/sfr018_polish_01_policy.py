"""글다듬이 스텝 1/2 — 원본 확보 + 문서유형·톤 정책 결정 (area 02).

캔버스에서 하는 일: 다듬을 원본(업로드 문서 또는 채팅 입력)을 확정하고, MCP `lang_policy`
에 물어 **문서유형에 따라 톤이 강제되는지**를 결정한다.

## 왜 톤 결정을 MCP 로 빼는가

톤 프리셋 문구는 지금 **세 벌**(글다듬이 원본 / 006 / eval)로 갈려 있고 실제로 어긋난 적이
있다(`onprem/test/check_tone_policy.py` 가 그래서 존재한다). MCP 한 곳에서만 해석하면
그 대조 자체가 필요 없어진다.

`tone_overridden`(정책상 강제되었는가)이 이 스텝의 출력으로 나오므로 **캔버스에서 분기**
할 수 있다 — 예: 강제된 경우 사용자에게 확인을 먼저 받는 노드로.

## 원본 파싱은 `re` 로 충분하다

전처리기 산출물 `genosUploaded` 는 `<doc file_name="..." temp_doc_id="...">본문</doc>`
문자열이다. 파싱에 추가 패키지가 필요 없어 이 스텝에 남긴다 (§D.3 — 워크플로우는
`asyncio, httpx, json, datetime, re` 만 쓴다).
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

_LOG = logging.getLogger("text_polish_policy")


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
        "error_type": "POLICY_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "설정 확인 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"{_AREA}-00020002",
        "error_type": "POLICY_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "문서 종류와 톤 설정을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "INPUT_EMPTY": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "POLISH_INPUT_EMPTY",
        "retryable": False,
        "msg": "다듬을 문서나 텍스트를 입력해 주세요.",
    },
    "CONFIG_MISSING": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "POLICY_CONFIG_MISSING",
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
# MCP 호출 (§H — `{GENOS_URL}/api/gateway/mcp/<id>/mcp`, JSON-RPC tools/call)
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
                    # 4xx 는 재시도하지 않는다 (§B)
                    return None, ("execution", "HTTPStatusError", response.status_code)
            if attempt < _ATTEMPTS - 1:
                await asyncio.sleep(0.3 * (attempt + 1))
    return None, failure


async def _mcp_call(env_name: str, tool: str, arguments: dict, *, read_timeout: float = 15.0):
    """MCP 도구 1회 호출. 결과 `content` 의 text 를 JSON 으로 되돌린다.

    MCP 는 텍스트 콘텐츠를 돌려주는 계약이므로, 구조화 결과는 JSON 문자열로 싣는다.
    JSON 이 아니면 `{"text": ...}` 로 감싸 호출부가 형태를 예측할 수 있게 한다.
    """
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
        # JSON-RPC 오류 본문은 남기지 않는다 (3.8절) — 분류만 올린다
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


def _extract_uploaded_markdown(genos_uploaded: str) -> str:
    """`genosUploaded` 의 `<doc ...>마크다운</doc>` 블록에서 본문만 뽑는다."""
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

    # 업로드 문서 우선, 없으면 채팅 텍스트
    source_text = _extract_uploaded_markdown(variables.get("genosUploaded") or "") or question
    if not source_text:
        error = _error("INPUT_EMPTY")
        _log_warning(
            "다듬을 원본 없음",
            event="polish_input_empty",
            error_code=error["error_code"],
            error_type=_ERRORS["INPUT_EMPTY"]["error_type"],
            status="final",
            **log_context,
        )
        return {**data, "error": error}

    # 문서유형·톤 결정 — 정책 강제 여부까지 MCP 가 판정한다
    policy, failure = await _mcp_call(
        "LANG_POLICY_MCP_ID",
        "resolve_tone",
        {
            "doc_type": str(variables.get("polish_doc_type") or ""),
            "tone": str(variables.get("polish_tone") or ""),
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
            "톤 정책 조회 실패",
            event="tone_policy_failed",
            error_code=error["error_code"],
            error_type=error_type,
            upstream_status=upstream_status,
            status="retryable" if error["retryable"] else "final",
            **log_context,
        )
        return {**data, "error": error}

    policy = policy or {}
    doc_type = str(policy.get("doc_type") or "")
    tone = str(policy.get("tone") or "")
    tone_overridden = bool(policy.get("tone_overridden"))

    # 문서 원문은 남기지 않는다 — 유형·톤과 강제 여부, 줄 수만 (3.8절)
    _log_info(
        "글다듬이 정책 확정",
        event="polish_policy_resolved",
        resource_id=f"{doc_type}/{tone}",
        status="tone_forced" if tone_overridden else "tone_as_requested",
        item_count=len(source_text.splitlines()),
        **log_context,
    )

    return {
        **data,
        "polish_source_text": source_text,
        "polish_doc_type": doc_type,
        "polish_tone": tone,
        # 캔버스 분기용 — 정책상 톤이 바뀐 경우 사용자 확인 노드로 보낼 수 있다
        "tone_overridden": tone_overridden,
        "tone_notice": str(policy.get("notice") or ""),
        "error": None,
    }
