"""글다듬이 스텝 2/2 — 다듬기 + 결정적 검증 + 응답 (area 02, **마지막 스텝**).

캔버스에서 하는 일:

```
코드서빙 /polish  (LLM + 프롬프트)
      ↓ polished (정본)
MCP text_guard  ── markdown_structure_issues  (표·제목·코드펜스 훼손)   ┐ 먼저 띄우고
                ── fact_issues                (숫자·날짜 누락)          ┘ 그 동안 토큰을 흘린다
      ↓
event: token × N   ← **정본을 흘린다.**
      ↓
event: result      ← **원문·다듬은 글을 그대로** 낸다 (하이라이트 없음)
```

## 검증을 MCP 로 뺀 이유가 이 스텝에 다 있다

두 검증은 **LLM 을 부르지 않는 순수 함수**다. 그래서 워크플로우가 직접 불러도 안전하고,
캔버스에서 "구조가 깨졌으면 사람 확인 노드로" 같은 분기를 걸 수 있다. 예전에는 이 판정이
`main.py` 안에 묻혀 있어 결과 문자열로만 드러났다.

**두 호출은 `asyncio.gather` 로 동시에 한다.** 서로 독립이고 전부 짧다.

## 변경 하이라이트를 뺐다 (2026-09-17)

`diff_changes`(MCP `genon_text_guard`)를 더는 부르지 않는다. 다듬기가 문장을 크게
다시 쓰는 사례가 흔해 원문-결과 낱말 단위 diff 가 오히려 읽기 어렵다는 판단이다 —
그 경우 형광이 문서 전체를 뒤덮거나(1:1 정렬이 안 서면 옛 `difflib` 경로로 폴백)
접힌 항목만 남아 "무엇이 바뀌었나" 를 오히려 가린다. 그래서 `original_text`·
`polished_text` 는 **`<mark>` 없이 그대로** 나간다. **번역의 용어사전 하이라이트
(`glossary_report`)는 이 결정과 무관하다** — 별개 메커니즘이고 그대로 둔다.
도구 자체(`genon_text_guard.diff_changes`)는 지우지 않았다 — 이 스텝만 호출을 끊었다.

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
import sys

import httpx

# ─────────────────────────────────────────────────────────────
# 로깅 (§C / 가이드 3.8)
# ─────────────────────────────────────────────────────────────
_ALLOWED_LOG_FIELDS = frozenset({
    "event", "trace_id", "request_id", "resource_id", "status",
    "duration_ms", "item_count", "upstream_status", "error_code", "error_type",
})

_LOGGER_NAME = "text_polish"
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
        "error_type": "POLISH_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "문장 다듬기 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"ERR-{_AREA}-00020002",
        "error_type": "POLISH_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "문장 다듬기 결과를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "CONFIG_MISSING": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "POLISH_CONFIG_MISSING",
        "retryable": False,
        "msg": "서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
    },
    "UPSTREAM_FINAL": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "POLISH_UPSTREAM_FINAL",
        "retryable": False,
        "msg": "요청을 처리하지 못했습니다. 관리자에게 문의해 주세요.",
    },
    "INTERNAL": {
        "error_code": f"ERR-{_AREA}-00020003",
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


async def _post_serving(env_name: str, path: str, payload: dict, *, read_timeout: float):
    serving_id = (os.environ.get(env_name) or "").strip()
    if not serving_id:
        return None, ("config", f"{env_name}_MISSING", None)
    try:
        url = f"{_gateway_base()}/code_serving/{serving_id}/{path.lstrip('/')}"
    except RuntimeError:
        return None, ("config", "GENOS_URL_MISSING", None)
    return await _post_json(url, payload, read_timeout=read_timeout)


# ── 서빙 스트리밍 읽기 (2026-09-09) ──────────────────────────────
#
# `POST /polish/stream` 은 다듬어지는 대로 SSE 로 흘려 준다. 그전에는 `POST /polish` 가
# 다 끝난 뒤 한 번에 줬고, 이 스텝은 그 **완성된 글**을 조각내 흘렸다 — 그래서 사용자가
# 기다리는 수십 초 동안 화면이 비어 있었다.
#
# ## 왜 `_post_json` 을 쓰지 않나
#
# 그 함수는 응답을 다 받은 뒤 본문을 해석한다(`_decode_body`). 스트리밍은 받는 도중에
# 흘려야 하므로 읽기 방식 자체가 다르다. **그 함수는 9벌 사본이라 손대지 않는다** —
# 여기만 필요한 동작을 거기 넣으면 나머지 여덟 스텝의 사본이 함께 바뀐다.
#
# ## 재시도하지 않는다
#
# 흘리기 시작한 뒤 다시 부르면 같은 글이 화면에 두 번 나온다. 그리고 흘리기 **전에**
# 실패했다면 `POST /polish` 로 되돌아가면 되는데, 그쪽은 `_post_json` 이 재시도까지
# 해 준다 — 여기서 또 두드릴 이유가 없다.
_POLISH_STREAM_PATH = "/polish/stream"

# SSE 프레임 접두어. 서빙이 `data: {json}` 줄로 보낸다 (`main.py` 의 `_sse`).
_SSE_DATA_PREFIX = "data:"


async def _stream_serving(env_name: str, path: str, payload: dict, *, read_timeout: float):
    """코드서빙의 **SSE 라우트**를 읽으며 `("token", 글)` 을 내고, 끝에 결과를 낸다.

    `_post_serving` 의 스트리밍 짝이다 — 인자 모양을 맞춰 뒀다. **세 스텝(글다듬이·
    번역·FAQ)이 같은 이름으로 같은 코드를 들고 있어야** `check_deploy_contract` 의
    사본 일치 판정이 갈림을 잡는다(스텝은 자기완결이라 공용 모듈로 뺄 수 없다).

    Yields:
        `("token", str)` — 화면에 흘릴 글.
        `("done", dict)` — 서빙이 마지막에 준 결과 프레임.
        `("failure", tuple)` — `_post_json` 과 **같은 모양의** 3-튜플
            `(kind, error_type, upstream_status)`. 호출부가 그대로 오류표에 매핑한다.

    **한 글자도 흘리지 않은 실패**는 `failure` 로만 나간다 — 호출부가 비스트리밍
    경로로 되돌아갈 수 있어야 한다. 흘린 뒤의 실패는 되돌릴 수 없으므로 그대로 오류다.
    **스트리밍 라우트가 없는 서빙 판본**(정본 `onprem/codeserving/`)에서는 404 나
    SSE 아닌 응답이 와서 여기서 `failure` 가 되고, 호출부가 되돌아간다.
    """
    serving_id = (os.environ.get(env_name) or "").strip()
    if not serving_id:
        yield "failure", ("config", f"{env_name}_MISSING", None)
        return
    try:
        url = f"{_gateway_base()}/code_serving/{serving_id}/{path.lstrip('/')}"
    except RuntimeError:
        yield "failure", ("config", "GENOS_URL_MISSING", None)
        return

    headers = {
        "Authorization": f"Bearer {(os.environ.get('GENOS_TOKEN') or '').strip()}",
        # 스트리밍을 받겠다고 밝힌다. MCP 406 건과 같은 자리다 — 서버가 본문을 읽기
        # **전에** Accept 를 보는 구현이 있다.
        "Accept": "text/event-stream",
    }
    timeout = httpx.Timeout(
        connect=_CONNECT_TIMEOUT, read=read_timeout, write=5.0,
        pool=_CONNECT_TIMEOUT,
    )
    _debug_echo(
        "스트리밍 POST 요청",
        event="http_stream_request",
        url=url,
        accept=headers["Accept"],
        payload_keys=",".join(sorted(payload)),
    )

    emitted = 0
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code >= 400:
                    # `stream()` 은 지연 읽기다 — 사유를 보려면 먼저 본문을 읽어야 한다.
                    await response.aread()
                    _debug_echo(
                        "스트리밍 HTTP 오류 응답",
                        event="http_stream_error",
                        url=url,
                        status=response.status_code,
                        content_type=response.headers.get("content-type", ""),
                        body=response.text,
                    )
                    yield "failure", (
                        _upstream_kind(response),
                        "HTTPStatusError",
                        response.status_code,
                    )
                    return
                content_type = str(response.headers.get("content-type", "")).lower()
                if "text/event-stream" not in content_type:
                    # 서빙이 스트리밍 라우트를 안 들고 있는 판본이다(배포 어긋남).
                    # 되돌아갈 수 있게 실패로 낸다 — 여기서 본문을 해석하려 들면
                    # 모양을 가정하게 되고, 어긋나면 조용히 빈손이 된다.
                    await response.aread()
                    _debug_echo(
                        "스트리밍을 요청했는데 SSE 가 아니다",
                        event="http_stream_not_sse",
                        url=url,
                        content_type=content_type,
                    )
                    yield "failure", ("execution", "NotEventStream", response.status_code)
                    return

                async for raw_line in response.aiter_lines():
                    line = raw_line.strip()
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith(_SSE_DATA_PREFIX):
                        continue
                    try:
                        frame = json.loads(line[len(_SSE_DATA_PREFIX):].strip())
                    except (json.JSONDecodeError, ValueError):
                        # 프레임 하나가 깨진 것으로 응답 전체를 버리지 않는다.
                        continue
                    if not isinstance(frame, dict):
                        continue
                    kind = frame.get("type")
                    if kind == "done":
                        yield "done", frame
                        return
                    if kind == "error":
                        # 서빙이 분류해 준 오류다. 상태코드가 아니라 **오류 코드**로
                        # 재시도 여부를 정한다 (`_upstream_kind` 와 같은 규약).
                        code = str(frame.get("error_code") or "")
                        yield "failure", (
                            "upstream_final" if code.endswith("00020003") else "execution",
                            "StreamError",
                            None,
                        )
                        return
                    # **`text` 를 든 프레임은 종류와 무관하게 흘린다.** 단위마다 프레임
                    # 종류가 다르다 — 글다듬이·번역은 `delta` 하나지만 FAQ 는 항목을 열고
                    # 닫는 프레임(`item_open`·`item_close`)도 화면 조각을 들고 온다.
                    # 종류를 여기서 열거하면 단위가 프레임을 하나 더할 때 **세 스텝을 모두**
                    # 고쳐야 하고, 안 고치면 그 조각이 조용히 화면에서 빠진다 — 오류는
                    # 나지 않고 "결과에는 있는데 흐르지 않은 글" 로만 드러난다.
                    text = frame.get("text")
                    if isinstance(text, str) and text:
                        emitted += len(text)
                        yield "token", text
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        _debug_echo("스트리밍 전송 실패", event="http_stream_transport_error",
                    url=url, exc=repr(exc), emitted=emitted)
        yield "failure", ("transport", type(exc).__name__, None)
        return
    except Exception as exc:  # noqa: BLE001 - 읽는 중 끊김까지
        _debug_echo("스트리밍 읽기 실패", event="http_stream_read_error",
                    url=url, exc=repr(exc), emitted=emitted)
        yield "failure", ("execution", type(exc).__name__, None)
        return

    # `done` 도 `error` 도 없이 끝났다 = 서빙이 결과를 못 냈다. 흘린 글이 있어도
    # 결과가 없으면 화면이 하이라이트·다운로드를 못 받으므로 실패다.
    _debug_echo("스트리밍이 결과 프레임 없이 끝났다",
                event="http_stream_no_done", url=url, emitted=emitted)
    yield "failure", ("execution", "NoDoneFrame", None)


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
# 토큰 스트리밍 (2026-09-01 되살림)
# ─────────────────────────────────────────────────────────────
#
# 2026-08-28 에 없앴다가 요구가 바뀌어 되살렸다 — **다듬은 글이 "AI 가 주루룩 답변하는"
# 것처럼 보여야 한다.** 그때 적어 둔 근거("전용 UI 가 한 번에 그리므로 필요 없다")는
# 화면이 **완성된 뒤**를 말한 것이고, 그 전 몇십 초 동안 화면이 비어 있다는 사실은
# 다루지 않았다.
#
# ## 흘리는 것은 **정본**이다 — `result` 와 같은 내용이다 (2026-09-17)
#
# 낱말 diff 하이라이트(`diff_changes`)를 뺀 뒤로는 스트리밍이 끝나도 갈아 끼울 사본이
# 없다. 스트리밍 중에 흘린 조각을 이어 붙인 것과 `result.polished_text` 가 **같다.**
#
# ## 흘리는 시점 — **되돌릴 수 없게 된 뒤에만**
#
# 스트리밍은 서빙이 결과를 준 **뒤에** 시작한다. 그 뒤로 남은 것은 결정적 점검뿐이고
# 그건 실패해도 결과 전달을 막지 않으므로, **흘려 놓고 오류로 갈아엎는 일이 없다.**
# 오류 경로에서는 토큰이 한 개도 나가지 않는다.
#
# ## 대기 시간을 채운다 — 점검과 **겹쳐** 돈다
#
# 점검 2종을 먼저 띄워 두고 그 동안 흘린다. 순서대로 하면 스트리밍이 순수한 연출이 되고
# 전체 시간만 늘어난다.
#
# ## 조각 크기는 문서 길이에 따라 늘린다
#
# 32자 고정이면 20만 자 문서가 emit 6,250회다 — 소켓 메시지 수가 문서 길이에 비례하면
# 긴 문서에서 그 자체가 부하가 된다. 총 emit 수에 상한을 두고 조각을 키운다.
_STREAM_CHUNK_CHARS = 32
_STREAM_MAX_EMITS = 400


def _stream_chunks(text: str):
    size = max(_STREAM_CHUNK_CHARS, -(-len(text) // _STREAM_MAX_EMITS))
    for start in range(0, len(text), size):
        yield text[start: start + size]


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
# **2026-09-17 에 낱말 하이라이트 자체를 뺐다** — 위 "변경 하이라이트를 뺐다" 절.
# 지금은 그 자리를 대신할 표시가 없다: `original_text`·`polished_text` 는 `<mark>`
# 없이 그대로 나간다.


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

    # `title` 은 서빙이 결과 txt 를 굳혀 올릴 때 파일명이 된다 (2026-08-28).
    polish_payload = {
        "text": source_text,
        "doc_type": doc_type,
        "tone": tone,
        "title": str(data.get("polish_title") or ""),
    }

    # 1) 다듬기 — **다듬어지는 대로 흘린다** (2026-09-09). LLM 호출·프롬프트 렌더는
    #    코드서빙에 있고(§D.3), 그쪽이 SSE 로 증분을 준다.
    body = None
    failure = None
    streamed_chars = 0
    async for stream_kind, stream_value in _stream_serving(
        "TEXT_POLISH_SERVING_ID",
        _POLISH_STREAM_PATH,
        polish_payload,
        read_timeout=_POLISH_READ_TIMEOUT,
    ):
        if stream_kind == "token":
            streamed_chars += len(stream_value)
            yield await emit_event("token", stream_value)
        elif stream_kind == "done":
            body = stream_value
        else:
            failure = stream_value

    # **흘리기 전에 실패했으면 비스트리밍으로 되돌아간다.** 서빙 판본이 스트리밍 라우트를
    # 안 들고 있거나(배포 어긋남) 게이트웨이·프록시가 SSE 를 막는 경우다 — 그때 기능이
    # 통째로 죽으면 안 된다. 흘린 뒤라면 되돌릴 수 없으므로 그대로 오류다(같은 글을
    # 두 번 뿌리면 사용자는 그것을 결과물로 읽는다).
    if failure is not None and streamed_chars == 0:
        _log_warning(
            "스트리밍 경로 실패 — 비스트리밍으로 되돌아간다",
            event="polish_stream_fallback",
            error_type=failure[1],
            upstream_status=failure[2],
            **log_context,
        )
        body, failure = await _post_serving(
            "TEXT_POLISH_SERVING_ID",
            "/polish",
            polish_payload,
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

    # 2) 결정적 검증 2종 — 서로 독립이라 동시에 부른다. 실패해도 결과 전달을 막지 않는다.
    #
    # **먼저 띄워 두고 그 동안 토큰을 흘린다** (2026-09-01). 순서대로 하면 스트리밍이
    # 순수한 연출이 되고 전체 시간만 늘어난다 — 지금은 어차피 기다려야 하는 시간을 채운다.
    guard_calls = (
        ("markdown_structure_issues", {"source": source_text, "revised": polished}),
        ("fact_issues", {"source": source_text, "revised": polished}),
    )
    guard_task = asyncio.gather(
        *(
            _mcp_call("TEXT_GUARD_MCP_ID", tool, args, read_timeout=_GUARD_READ_TIMEOUT)
            for tool, args in guard_calls
        )
    )

    # 3) 토큰 스트리밍 — **스트리밍 경로로 왔으면 이미 흘렸다** (2026-09-09). 비스트리밍
    # 으로 되돌아간 경우에만 여기서 조각내 흘린다 — 그 경로에서는 화면이 아직 비어 있다.
    #
    # 어느 쪽이든 흘리는 것은 **정본**이다. 사본은 아직 없고(위 점검이 만든다), 태그가
    # 조각 경계에서 갈리면 화면에 부스러기가 남는다. 원시 마크다운이 보이는 것은 허용된
    # 동작이고, 끝나면 `result` 가 좌우 하이라이트 비교로 갈아 끼운다.
    if streamed_chars == 0:
        for chunk in _stream_chunks(polished):
            yield await emit_event("token", chunk)

    guard_results = await guard_task

    structure_warnings: list = []
    fact_warnings: list = []
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
        else:
            fact_warnings = [str(w) for w in (payload.get("issues") or [])]

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
    # 흘리는 중에 끊긴 구간이 있다 (2026-09-09). 화면에 나갔던 글과 최종 결과가 다르므로
    # **그 사실을 말해 준다** — 조용히 넘기면 사용자는 화면에서 사라진 문장을 찾게 된다.
    if bool((body or {}).get("stream_diverged")):
        notices.append(
            "다듬는 도중 연결이 끊겨 화면에 잠시 보였던 문장이 최종 결과와 다를 수 있습니다."
            " 아래 결과를 확인해 주세요."
        )

    # 흘린 정본을 그대로 좌우에 낸다 (2026-09-17 — 낱말 diff 하이라이트 제거).
    # 스트리밍 중에 흘린 것과 `result` 의 내용이 **같다** — 갈아 끼울 사본이 없다.
    yield {
        "event": "result",
        "data": {
            **_base_payload(),
            # ── 좌우 비교 두 값 ───────────────────────────────────────────────
            # 화면은 이 둘을 나란히 놓고 그린다. `<mark>` 낱말 하이라이트는 없다 —
            # 원문 그대로/다듬은 글 그대로다.
            "original_text": source_text,
            "polished_text": polished,
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
