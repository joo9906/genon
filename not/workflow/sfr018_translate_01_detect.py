"""번역 스텝 1/2 — 원본 확보 + 언어 감지 + 방향 검증 (area 02).

**이 스텝은 신규다.** 번역은 지금 코드서빙 전용이라 캔버스에 노드가 없다.

캔버스에서 하는 일:

```
genosUploaded 파싱 (첨부용 전처리기 산출물 = 원문)
        없으면 → question (사용자가 친 텍스트)
      ↓
MCP lang_policy.validate_direction — 한국어 축 검증
```

## 원본 확보 — 전처리기 산출물 하나다 (2026-09-07 변경)

그전에는 `translate_hwpx_path` 가 있으면 MCP `hwpx_text.hwpx_to_markdown` 으로 원본을
다시 파싱했다. 실환경에서 그 호출이 전부 `406` 이었고(Accept 헤더), 실패가 조용히 아래
폴백으로 떨어져 **표가 깨진 번역문**으로만 드러났다. 첨부 문서는 어차피 전처리기를 지나
오므로 두 번 파싱할 이유가 없다 — 첨부용 등록을 **`preprocessor/only_me.py`**(파싱 전용,
청킹 없음)로 둔다. 그쪽은 **이어붙이면 원문**을 계약으로 지므로, 검색용 가공을 번역해
결과물에 싣는 일이 생기지 않는다.

아래는 그 배선을 처음 붙일 때(2026-08-14)의 기록이다 — **왜 전처리기 산출물을 그대로
쓰면 안 됐는지**가 적혀 있고, 지금은 첨부용 전처리기가 우리 파서라 그 전제가 바뀌었다.


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

_LOGGER_NAME = "translate_detect"
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
        "error_type": "TRANSLATE_DETECT_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "언어 확인 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"ERR-{_AREA}-00020002",
        "error_type": "TRANSLATE_DETECT_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "언어를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "INPUT_EMPTY": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "TRANSLATE_INPUT_EMPTY",
        "retryable": False,
        "msg": "번역할 문서나 텍스트를 입력해 주세요.",
    },
    # `DOC_INVALID`("읽지 못함")은 2026-09-07 에 없앴다 — hwpx 를 스텝이 직접 파싱하던
    # 시절의 코드다. 파싱은 첨부용 전처리기가 하고 그 실패는 적재 층에서 예외로 드러나므로
    # 스텝에는 "첨부 없음" 과 "읽지 못함" 을 가를 근거가 없다. **낼 수 없는 오류를 표에
    # 남기지 않는다** — 읽는 쪽이 그 사건이 처리된다고 믿게 된다.
    "TARGET_MISSING": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "TRANSLATE_TARGET_MISSING",
        "retryable": False,
        "msg": "번역할 언어를 선택해 주세요.",
    },
    "UNSUPPORTED_PAIR": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "TRANSLATE_UNSUPPORTED_PAIR",
        "retryable": False,
        "msg": "한국어가 포함된 번역만 지원합니다. 원본 또는 번역 언어를 한국어로 선택해 주세요.",
    },
    "CONFIG_MISSING": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "TRANSLATE_CONFIG_MISSING",
        "retryable": False,
        "msg": "서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
    },
    "UPSTREAM_FINAL": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "TRANSLATE_UPSTREAM_FINAL",
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
# MCP 호출 (§H)
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


# ─────────────────────────────────────────────────────────────
# MCP 전송 규약 (2026-09-07 — 실환경 406 수정)
# ─────────────────────────────────────────────────────────────
# MCP 스트리머블 HTTP 서버는 POST 본문을 읽기 **전에 Accept 헤더를 검사한다.**
# `application/json` 과 `text/event-stream` 을 **둘 다** 열거하지 않으면 도구를 부르지도
# 않고 `406 Not Acceptable` 로 끊는다. httpx 기본값은 `Accept: */*` 라 그 검사를
# 통과하지 못한다 — 실환경에서 MCP 경로가 통째로 406 이던 원인이다.
# **코드서빙 POST 에는 붙이지 않는다** (그쪽은 평범한 JSON API 다).
_MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


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
    body, failure = await _post_json(
        url, payload, read_timeout=read_timeout, extra_headers=_MCP_HEADERS
    )
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

    # ── 원본 확보 — **전처리기 산출물이 정본이다** (2026-09-07) ──
    #
    # 그전에는 `translate_hwpx_path` 가 있으면 MCP `hwpx_to_markdown` 으로 원본을 다시
    # 파싱했다. 걷어낸 이유는 FAQ 스텝 1 과 같다 — 그 호출이 실환경에서 전부 406 이었고
    # (Accept 헤더), 실패가 조용히 이 폴백으로 떨어져 **표가 깨진 번역문**으로만
    # 드러났다. 첨부 문서는 어차피 전처리기를 지나 오므로 두 번 파싱할 이유가 없다.
    #
    # 첨부용 등록은 `preprocessor/only_me.py` — 파싱만 하고 **청킹하지 않는다.** 검색용
    # 가공(조문·표 머리말·겹침)이 섞이면 번역은 원문에 없던 머리말을 **번역해서 결과물에
    # 싣는다.** 그 파일이 무손실을 계약으로 지고 있다(이어붙이면 원문).
    source_text = _extract_uploaded_markdown(variables.get("genosUploaded") or "")
    source_kind = "preprocessor" if source_text else "text"

    if not source_text:
        source_text = question

    if not source_text:
        # 첨부도 발화도 비었다. 전처리기가 본문을 못 낸 경우와 가르지 않는다 —
        # 스텝에 구분할 근거가 없고 사용자가 할 일은 어느 쪽이든 같다.
        error = _error("INPUT_EMPTY")
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
            # 서빙이 재시도 불가로 못 박은 응답은 그 판정을 그대로 따른다
            # (`_upstream_kind` 머리말 참고).
            else "UPSTREAM_FINAL" if kind == "upstream_final"
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
    # 사용자가 고른 원문 언어와 문서에서 감지한 언어가 다른데 **통과한** 경우다
    # (대상이 한국어라 §6 축이 성립하는 등). 축이 깨지는 충돌은 서빙이 거부하므로
    # 여기 오지 않는다. 넘기지 않으면 "원문 언어를 잘못 골랐다" 는 사실이 경계에서
    # 사라진다 — `translated_markdown`·`stats` 와 같은 종류의 유실이다.
    source_mismatch = bool(verdict.get("source_mismatch"))
    detected_lang = str(verdict.get("detected_lang") or "")

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

    if source_mismatch:
        # 막지 않는다 — 서빙이 이미 "§6 을 깨는 충돌" 만 거부하고 넘긴 것이다.
        # 다만 결과가 이상할 때 원인을 좁히려면 이 사실이 로그에 있어야 한다.
        _log_warning(
            "선택한 원문 언어와 문서에서 감지한 언어가 다르다",
            event="lang_source_mismatch",
            resource_id=f"{source_lang or 'unknown'}(declared)!={detected_lang or 'unknown'}(detected)",
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
        "translate_source_mismatch": source_mismatch,
        "translate_detected_lang": detected_lang,
        "translate_glossary_applies": glossary_applies,
        "translate_register": str(variables.get("translate_register") or ""),
        "error": None,
    }
