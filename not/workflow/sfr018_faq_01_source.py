"""FAQ 스텝 1/2 — 원본 확보 + 생성 개수 결정 (area 02).

캔버스에서 하는 일:

```
genosUploaded 파싱 (첨부용 전처리기 산출물 = 원문)
      ↓
서빙 /config 로 배포 상한 확인 → 캔버스 변수로 낮추기만 허용
```

## 원본은 전처리기 산출물 하나다 (2026-09-07 변경)

그전에는 `faq_hwpx_path` 가 있으면 **MCP `hwpx_text.hwpx_to_markdown`** 으로 원본을 다시
파싱했다. 그 경로를 걷어낸 이유는 셋이다:

- **닿지 않을 수 있다.** 실환경에서 그 호출이 전부 `406` 이었다(Accept 헤더를 둘 다
  열거해야 한다 — 남은 스텝의 `_MCP_HEADERS` 머리말). 실패는 조용히 전처리기
  산출물로 폴백해서 **"표가 깨진 결과" 로만** 드러났다.
- **원본 경로를 전제한다.** 플랫폼이 `faq_hwpx_path`(공유 볼륨 경로)를 채워 주는지
  미확인이었다.
- **두 번 파싱한다.** 첨부 문서는 어차피 전처리기를 지나 `genosUploaded` 로 온다.

첨부용 등록을 **`preprocessor/only_me.py`**(hwpx 파싱 전용, **청킹 없음**)로 두면 그 값이
곧 원문이다. 적재용(`final_preprocessor.py`)을 그대로 쓰면 안 되는 이유는 그쪽이 검색을
위해 본문을 바꾸기 때문이다 — 조문 머리말(`제2장 총칙 > 제5조(목적)`)·표 조각 머리말·
겹침이 본문에 들어가고, **FAQ 는 그 머리말을 원문 문장으로 보고 근거 대조를 한다.**

## 개수 상한은 두 층이다

배포 상한(`FAQ_MAX_COUNT`, 코드서빙 환경변수) 안에서만 캔버스 변수(`faq_max_count`)로
**낮출 수** 있다. 캔버스가 상한을 넘길 수 있으면 LLM 예산 상한이 설정 하나로 무력해진다.
그래서 상한 판정은 코드서빙 `/config` 가 하고 이 스텝은 받아 적용만 한다.

**`faq_count` 는 문서 하나에서 만들 총 개수다** (2026-09-03 요구 확정). 사용자는 총
개수만 고르고 **어느 구간에서 몇 개씩 뽑을지는 코드서빙이 배분한다**
(`chunking.plan_quota`). 2026-08-31~09-02 에는 이 값이 구간당 개수여서 **고른 숫자와
받는 개수가 달랐다**(구간이 여섯이면 5를 골라도 30개). 긴 문서에서 구간당 몫이 0 이
되는 것은 코드서빙의 호출 수 상한(`FAQ_MAX_CHUNK_CALLS`)이 막는다 — 이 스텝이 알 값이
아니다.

## 원본을 못 구하면 빈 답변으로 감추지 않는다

업로드가 없으면 여기서 오류로 끝낸다 — FAQ 0건을 정상 응답처럼 내려보내는 쪽이 나쁘다.
"""

import asyncio
import json
import logging
import os
import sys
import re

import httpx

# ─────────────────────────────────────────────────────────────
# 로깅 (§C / 가이드 3.8)
# ─────────────────────────────────────────────────────────────
_ALLOWED_LOG_FIELDS = frozenset({
    "event", "trace_id", "request_id", "resource_id", "status",
    "duration_ms", "item_count", "upstream_status", "error_code", "error_type",
})

_LOGGER_NAME = "faq_source"
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
        "error_type": "FAQ_SOURCE_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "문서 처리 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"ERR-{_AREA}-00020002",
        "error_type": "FAQ_SOURCE_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "문서를 읽지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "NO_INPUT": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "FAQ_NO_INPUT",
        "retryable": False,
        "msg": "FAQ 를 만들 문서를 첨부해 주세요.",
    },
    # `DOC_INVALID`("읽지 못함")은 2026-09-07 에 없앴다 — hwpx 를 스텝이 직접 파싱하던
    # 시절의 코드다. 파싱은 첨부용 전처리기가 하고 그 실패는 적재 층에서 예외로 드러나므로
    # 스텝에는 "첨부 없음" 과 "읽지 못함" 을 가를 근거가 없다. **낼 수 없는 오류를 표에
    # 남기지 않는다** — 읽는 쪽이 그 사건이 처리된다고 믿게 된다.
    "COUNT_ZERO": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "FAQ_COUNT_ZERO",
        "retryable": False,
        "msg": "생성할 FAQ 개수를 1개 이상으로 지정해 주세요.",
    },
    "CONFIG_MISSING": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "FAQ_CONFIG_MISSING",
        "retryable": False,
        "msg": "서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
    },
    "UPSTREAM_FINAL": {
        "error_code": f"ERR-{_AREA}-00020003",
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


def _decode_body(response):
    """응답 본문을 파이썬 객체로 되돌린다 (실패 시 `json.JSONDecodeError`).

    MCP 는 같은 `tools/call` 에 **두 가지 모양**으로 답한다 — 서버가 JSON 응답 모드면
    `application/json` 한 덩어리, 기본(스트리머블)이면 `text/event-stream` 프레임에
    담아 준다. `response.json()` 만 쓰면 후자에서 `InvalidJson` 으로 떨어지는데, 그
    상태는 **통신도 되고 도구도 돌았는데 결과만 사라지는** 형태라 원인이 드러나지 않는다.
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


# `_mcp_call` 은 2026-09-07 에 걷어냈다 — 이 스텝의 유일한 MCP 호출이 hwpx 파싱
# (`hwpx_to_markdown`)이었고, 첨부 문서를 두 번 파싱하지 않기로 하면서 호출부가
# 0건이 됐다. **아무도 안 부르는 사본을 남기지 않는다** — 다섯 스텝에 같은 함수가
# 있고 그중 하나만 옛 모양으로 굳으면 그 사실이 오류로 드러나지 않는다.
# 되살릴 일이 생기면 `git show HEAD:onprem/workflow/sfr018_faq_01_source.py` 다.


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
            _debug_echo("GET 요청", event="http_request", url=url, attempt=attempt + 1)
            try:
                response = await client.get(url, headers=headers)
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
    # 1) 원본 확보 — **전처리기 산출물 하나뿐이다** (2026-09-07).
    #
    # 그전에는 캔버스 변수 `faq_hwpx_path` 가 있으면 MCP `hwpx_to_markdown` 으로 원본을
    # 다시 파싱했다. 걷어낸 이유가 셋이다:
    #
    # - **닿지 않을 수 있다.** 그 호출이 전부 406 이었고(Accept 헤더), 실패는 조용히
    #   전처리기 산출물로 폴백해서 **"표가 깨진 결과" 로만** 드러났다.
    # - **원본 경로를 전제한다.** 플랫폼이 `faq_hwpx_path` 를 채워 주는지 미확인이었다.
    # - **두 번 파싱한다.** 첨부 문서는 어차피 전처리기를 지나 온다.
    #
    # 첨부용 등록을 `preprocessor/only_me.py`(파싱 전용, 청킹 없음)로 두면 이 값이 곧
    # 원문이다 — 조문·표 머리말 같은 검색용 가공이 섞이지 않는다(그게 섞이면 FAQ 는
    # 그 머리말을 원문 문장으로 보고 근거 대조를 한다).
    source_text = _extract_uploaded_markdown(variables.get("genosUploaded") or "")
    source_kind = "preprocessor"

    if not source_text.strip():
        # 첨부가 없거나 전처리기가 본문을 못 낸 것이다. 그 둘을 여기서 가르지 않는다 —
        # 스텝에는 구분할 근거가 없고(전처리기 실패는 적재 층에서 이미 예외로 드러난다)
        # 사용자가 할 일은 어느 쪽이든 같다.
        error = _error("NO_INPUT")
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
