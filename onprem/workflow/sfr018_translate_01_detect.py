"""번역 스텝 1/2 — 원본 확보 + 언어 감지 + 방향 검증 (area 02).

**이 스텝은 신규다.** 번역은 지금 코드서빙 전용이라 캔버스에 노드가 없다.

캔버스에서 하는 일:

```
translate_hwpx_path 있음 → MCP hwpx_text.hwpx_to_markdown   (표 안 수치 보존)
                   없음 → genosUploaded 파싱                (전처리기 산출물)
                   둘 다 없음 → question (사용자가 친 텍스트)
      ↓
MCP lang_policy.validate_direction — 한국어 축 검증
```

## 원본 확보 — hwpx 는 우리 파서를 먼저 쓴다 (2026-08-14 추가)

**이 배선이 없어서 hwpx 업로드가 지능형 전처리기 산출물로만 번역되고 있었다.** 그쪽은
PDF 로 바꾼 뒤 레이아웃 모델이 읽는 경로라 **표 안 수치가 깨진다**(요구사항 §5) — 이
프로젝트가 hwpx 전용 파서를 만든 이유가 바로 그것이다. 코드서빙에 `POST /translate/hwpx`
가 있었지만 **캔버스에서는 닿을 수 없었다**(그 경로는 화면이 코드서빙을 직접 부를 때만
쓰인다). FAQ 스텝 1 은 같은 배선을 이미 갖고 있었고, 번역만 빠져 있었다.

hwpx 파싱이 MCP 인 이유는 `lxml` 이 워크플로우 이미지에 없기 때문이다 (§D.3).
FAQ 와 **같은 도구·같은 폴백**을 쓴다 — 파서가 두 벌이 되면 표 격자 규칙이 갈린다.

**`truncated` 를 반드시 본다.** 상한에서 잘린 문서를 번역하면 뒷부분이 통째로 빠진 채
정상 결과처럼 내려간다 — 사용자는 번역이 끝났다고 믿는다.

## 왜 방향 판정이 LLM 이 아닌가

**거부 판정**이기 때문이다. 사용자의 요청을 막는 판단을 LLM 에 맡기면 같은 입력에 대해
어떤 날은 통과하고 어떤 날은 막힌다. 스크립트(문자 체계) 기반으로 결정적으로 감지한다 —
그래서 MCP 도구(`lang_policy`)로 뺄 수 있었다.

**감지 불가는 거부가 아니다.** 숫자·기호뿐인 입력은 방향 검증만 건너뛰고 번역은 진행한다.

## 용어사전 적용 여부도 여기서 확정된다

`validate_direction` 이 `glossary_applies` 를 함께 낸다 — 용어사전은 **한국어·영어에만**
있고 중국어·태국어·베트남어·러시아어는 LLM 만으로 번역한다(2026-08-14 요구 확정).
거부 판정이 아니라 안내이므로 막지 않고 다음 스텝으로 넘긴다.
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
    # hwpx 경로가 지정됐는데 본문이 비었다면 "첨부 없음" 이 아니라 "읽지 못함" 이다.
    # 둘을 한 코드로 묶으면 사용자가 파일을 다시 올려도 같은 자리에서 막힌다.
    "DOC_INVALID": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TRANSLATE_DOC_INVALID",
        "retryable": False,
        "msg": "문서에서 번역할 내용을 읽지 못했습니다. 다른 파일로 시도해 주세요.",
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

    # ── 원본 확보 — hwpx 는 우리 파서를 먼저 쓴다 (머리말 참고) ──
    hwpx_path = str(variables.get("translate_hwpx_path") or "").strip()
    source_text = ""
    source_kind = "text"

    if hwpx_path:
        parsed, failure = await _mcp_call(
            "HWPX_TEXT_MCP_ID", "hwpx_to_markdown", {"path": hwpx_path}
        )
        if failure is not None:
            # 실패해도 전처리기 산출물로 떨어진다 — 조용히 넘기지 않고 사유를 남긴다
            _log_warning(
                "hwpx 직접 파싱 실패 — 전처리기 산출물로 진행",
                event="translate_hwpx_parse_failed",
                error_type=failure[1],
                upstream_status=failure[2],
                status="degraded",
                **log_context,
            )
        else:
            parsed = parsed or {}
            source_text = str(parsed.get("markdown") or "")
            if source_text:
                source_kind = "hwpx"
                if parsed.get("truncated"):
                    # 잘린 문서를 번역하면 뒷부분이 통째로 빠진 채 정상 결과처럼 내려간다
                    _log_warning(
                        "hwpx 본문이 상한에서 잘렸다 — 뒷부분은 번역되지 않는다",
                        event="translate_hwpx_truncated",
                        item_count=len(source_text),
                        status="degraded",
                        **log_context,
                    )

    if not source_text:
        source_text = _extract_uploaded_markdown(variables.get("genosUploaded") or "")
        if source_text:
            source_kind = "preprocessor"

    if not source_text:
        source_text = question

    if not source_text:
        error = _error("DOC_INVALID" if hwpx_path else "INPUT_EMPTY")
        _log_warning(
            "번역할 원본 없음",
            event="translate_input_empty",
            error_code=error["error_code"],
            resource_id=source_kind,
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

    # 용어사전은 한국어·영어에만 있다. 거부 사유가 아니라 안내다 — 막지 않고 넘긴다.
    glossary_applies = bool(verdict.get("glossary_applies"))

    _log_info(
        "번역 방향 확정",
        event="translate_direction_resolved",
        resource_id=f"{source_lang or 'unknown'}->{target_lang}",
        item_count=len(source_text.splitlines()),
        status=(
            f"{'detected' if detected else 'undetected'},"
            f"source={source_kind},glossary={'on' if glossary_applies else 'off'}"
        ),
        **log_context,
    )

    return {
        **data,
        "translate_source_text": source_text,
        # 원본을 어디서 얻었는지 — hwpx 직접 파싱과 전처리기 산출물은 표 보존 수준이
        # 다르다. 결과가 이상할 때 어느 경로였는지 모르면 원인을 좁힐 수 없다.
        "translate_source_kind": source_kind,
        "translate_source_lang": source_lang,
        "translate_target_lang": target_lang,
        "translate_source_detected": detected,
        "translate_glossary_applies": glossary_applies,
        "translate_register": str(variables.get("translate_register") or ""),
        "error": None,
    }
