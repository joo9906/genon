"""SFR-006 스텝 3/3 — 문서 자동 채움·병합·저장·미리보기·응답 (area 02, **마지막 스텝**).

캔버스에서 하는 일: (문서가 있으면) 업로드 문서로 빈 항목을 자동 채우며 그 진행 상황을
흘리고, 앞 스텝이 뽑아 둔 발화 값을 세션에 병합·저장한 뒤, 지금 값으로 채운 문서
미리보기와 답변 문구를 받아 **토큰 스트리밍 후 `event: result` 1회**로 마무리한다.

## 여기만 async generator 다

중간 스텝(`01_context`·`02_extract`)은 `dict` 를 돌려주고, 스트리밍이 필요한 이 스텝만
generator 로 만든다 (§D.1 — 네 시그니처를 섞지 않는다). `event: result` 는 **오류일 때도
반드시 1회** 보낸다. 안 보내면 이전 `data` 가 그대로 흐르고 답변이 완결되지 않는다.

## 문서 자동 채움 호출도 여기로 옮겼다 (2026-09-22)

그전에는 스텝 1(`01_context`)이 `POST /chat/prefill` 을 blocking 으로 불렀다. 문서가
길면 조각마다 LLM 호출이 걸려 최대 180초가 걸리는데, 스텝 1 은 중간 스텝이라 그 시간
동안 **소켓에 아무것도 흘릴 수 없었다**(§D.1) — 사용자는 화면이 빈 채로 기다렸다.

**이 스텝만 소켓을 쥐고 있으므로**, 진행 상황을 보여주려면 호출 자체가 여기 와야 한다.
`/chat/commit`(병합·저장·답변)을 부르기 **전에** `/chat/prefill/stream` 을 먼저 불러
조각 진행 문구를 토큰으로 흘리고, 그 결과(`fields_prefilled`·`source_doc_hash`·
`prefill_failed`·`prefill_skipped_reason`)를 `/chat/commit` 요청에 그대로 싣는다 —
스텝 1 이 계산해 넘겨주던 값을 이제 이 스텝이 직접 계산한다.

**대가: 스텝 1 의 `fields_missing`/`ready_for_download` 가 문서 반영분을 못 본다.**
그 값은 여전히 "지금까지 대화로 모인 값" 만 보고, 문서가 채울 항목까지 알려면 프리필을
스텝 1 에서 미리 돌려야 하는데 그러면 스트리밍을 옮긴 의미가 없어진다. 캔버스에 "다
채워졌으면 다운로드로" 분기가 걸려 있다면, 문서만으로 완성되는 턴에서 그 분기가 이번
턴에는 못 타고 **다음 턴부터** 정확해진다 — 상세는 `sfr006_01_context.py` 머리말.

## 스트리밍 규약 (onprem/README "워크플로우 스트리밍 규약" / 가이드 5.2·D.4)

- `sio_server.emit` 뒤에 **`await asyncio.sleep(0)`** — 양보하지 않고 몰아치면 소켓 쓰기가
  버퍼에 쌓여 UI 가 마지막에 한꺼번에 받는다.
- 전송 단위는 글자가 아니라 **청크(32자)**. 글자 단위면 emit 이 수천 회가 되고 오히려 늦다.
- 문서 자동 채움 진행 문구는 **서빙이 짓는다**(`chat_api._prefill_progress_text`) — 이
  스텝은 서빙이 `/chat/prefill/stream` 으로 흘린 `text` 를 그대로 토큰으로 옮길 뿐이다
  (018 세 스텝이 다듬은 글·번역문을 그대로 옮기는 것과 같은 경계).

## 파일 생성은 여기서 하지 않는다

다운로드 버튼이 코드서빙 `POST /generate` 를 직접 부른다. 두 pod 는 **Redis 세션**으로
연결되고, 이 스텝은 세션 저장까지만 책임진다.
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

_LOGGER_NAME = "sfr006_commit"
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
        "error_type": "TPL_COMMIT_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "문서 작성 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"ERR-{_AREA}-00020002",
        "error_type": "TPL_COMMIT_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "입력하신 내용을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.",
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
        "error_type": "TPL_COMMIT_INTERNAL",
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


# ─────────────────────────────────────────────────────────────
# 서빙 스트리밍 읽기 (2026-09-22 — 문서 자동 채움 진행 상황)
# ─────────────────────────────────────────────────────────────
#
# 018 세 스텝(글다듬이·번역·FAQ)의 `_stream_serving` 과 **같은 이름·같은 코드**다.
# `check_deploy_contract` 의 사본 일치 판정이 이름이 같은 함수는 본문도 같아야 통과시킨다
# — 스텝은 자기완결이라 공용 모듈로 뺄 수 없고, 여기서만 다르게 고치면 그 어긋남은
# 오류로 드러나지 않는다.
_SSE_DATA_PREFIX = "data:"


async def _stream_serving(env_name: str, path: str, payload: dict, *, read_timeout: float):
    """코드서빙의 **SSE 라우트**를 읽으며 `("token", 글)` 을 내고, 끝에 결과를 낸다.

    `_post_serving` 의 스트리밍 짝이다 — 인자 모양을 맞춰 뒀다. **네 스텝(글다듬이·
    번역·FAQ·006)이 같은 이름으로 같은 코드를 들고 있어야** `check_deploy_contract` 의
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


# ─────────────────────────────────────────────────────────────
# 스트리밍
# ─────────────────────────────────────────────────────────────
# 조각 크기는 글 길이에 따라 늘린다 (2026-09-01, 018 두 스텝과 사본을 맞췄다).
# 32자 고정이면 emit 수가 글 길이에 비례해 긴 글에서 소켓 메시지 수가 그대로 부하가
# 된다. **이 스텝의 답변은 대개 짧아 동작이 바뀌지 않는다** — 12,800자 미만에서는
# `max(32, ceil(len/400))` 이 32 라 예전과 같은 조각이 나온다. 사본 셋을 갈라 두면
# 한쪽만 고쳐지고, 그 어긋남은 오류로 드러나지 않는다.
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
    # 1) socket.io (모듈이 없으면 조용히 스킵 — 로컬·비대화 실행 경로)
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

        `{**data}` 는 앞 스텝이 넣은 값을 전부 실어 나른다(`field_names`·`block_styles`·
        `fields_updated` …). 스텝 3 에서 필드를 빼도 그것들이 그대로 프론트에 가므로,
        **"화면이 보는 값만 싣는다" 가 겉모양만 지켜진다.** 그래서 여기서 뼈대를 새로
        만든다. 마지막 스텝이라 다음 스텝에 넘길 `data` 도 없다.

        남기는 것은 화면 밖 두 가지다:
        - `genos_state` — 플랫폼 추적(`trace_id`). 잃으면 로그가 요청 간에 안 이어진다.
        - `session_id`·`template_id` — **다운로드 버튼이 `POST /generate` 를 부를 때**
          쓴다. 화면에 보이지는 않지만 버튼이 동작하려면 있어야 한다.
        """
        payload: dict = {}
        state = data.get("genos_state")
        if state is not None:
            payload["genos_state"] = state
        for key in ("session_id", "template_id"):
            value = data.get(key)
            if value:
                payload[key] = value
        return payload

    async def finish_with_error(error: dict):
        """오류 문구를 스트리밍하고 result 로 마무리한다. 마지막 스텝의 의무다."""
        for chunk in _stream_chunks(error["msg"]):
            yield await emit_event("token", chunk)
        yield {"event": "result", "data": {**_base_payload(), "text": error["msg"], "error": error}}

    # 2) 앞 스텝이 실패했으면 그 오류를 사용자에게 전달하고 끝낸다.
    #    중간 스텝은 스트리밍을 하지 않으므로 **여기서 말해 주지 않으면 화면이 빈 채로 끝난다.**
    upstream_error = data.get("error")
    if upstream_error:
        _log_warning(
            "앞 스텝 오류를 사용자에게 전달",
            event="template_fill_error",
            error_code=str(upstream_error.get("error_code") or ""),
            status="final",
            **log_context,
        )
        async for event in finish_with_error(upstream_error):
            yield event
        return

    # 3) 업로드 문서 자동 채움 — **진행 상황을 흘리며** 부른다 (2026-09-22 이전엔
    #    스텝 1 이 blocking 으로 불렀다). 조각마다 LLM 호출이 걸려 최대 180초가 걸릴 수
    #    있는 구간이라, 이 스텝(소켓을 쥔 유일한 스텝)이 직접 불러 진행 문구를 그 동안
    #    흘린다 — 그래야 화면이 빈 채로 기다리지 않는다.
    #
    # 문서가 없으면(이번 턴에 업로드가 없었다) 아무것도 부르지 않는다 — 기존과 동일하게
    # 빈 값으로 커밋에 들어간다.
    document = str(data.get("document") or "")
    prefilled: dict = {}
    source_doc_hash = ""
    prefill_failed = False
    prefill_skipped_reason = ""
    if document:
        prefill_body = None
        prefill_failure = None
        streamed_progress = 0
        prefill_payload = {
            "session_id": str(data.get("session_id") or ""),
            "template_id": str(data.get("template_id") or ""),
            "document": document,
        }
        async for stream_kind, stream_value in _stream_serving(
            "TEMPLATE_FILL_SERVING_ID",
            "/chat/prefill/stream",
            prefill_payload,
            # 조각마다 LLM 을 부르므로 넉넉해야 한다 — 상한을 짧게 두면 긴 문서에서
            # 늘 실패한다(스텝 1 이 blocking 으로 부르던 시절과 같은 값이다).
            read_timeout=180.0,
        ):
            if stream_kind == "token":
                streamed_progress += len(stream_value)
                yield await emit_event("token", stream_value)
            elif stream_kind == "done":
                prefill_body = stream_value
            else:
                prefill_failure = stream_value

        # **흘리기 전에 실패했으면 비스트리밍으로 되돌아간다** (서빙 판본이 스트리밍
        # 라우트를 안 들고 있거나 게이트웨이·프록시가 SSE 를 막는 경우). 흘린 뒤라면
        # 되돌릴 수 없으므로 그대로 실패로 둔다 — 진행 문구가 이미 나갔는데 다시 불러
        # 같은 진행을 반복하면 화면에 중복된 문구가 남는다.
        if prefill_failure is not None and streamed_progress == 0:
            _log_warning(
                "문서 자동 채움 스트리밍 실패 — 비스트리밍으로 되돌아간다",
                event="template_prefill_stream_fallback",
                error_type=prefill_failure[1],
                upstream_status=prefill_failure[2],
                **log_context,
            )
            prefill_body, prefill_failure = await _post_serving(
                "TEMPLATE_FILL_SERVING_ID",
                "/chat/prefill",
                prefill_payload,
                read_timeout=180.0,
            )

        if prefill_failure is not None:
            prefill_failed = True
            kind, error_type, upstream_status = prefill_failure
            _log_warning(
                "문서 자동 채움 실패 — 대화로 채우기는 그대로 진행",
                event="template_prefill_failed",
                error_type=error_type,
                upstream_status=upstream_status,
                status="degraded",
                **log_context,
            )
        else:
            prefill = prefill_body or {}
            prefilled = dict(prefill.get("fields_prefilled") or {})
            source_doc_hash = str(prefill.get("source_doc_hash") or "")
            prefill_failed = bool(prefill.get("prefill_failed"))
            prefill_skipped_reason = str(prefill.get("skipped_reason") or "")
            # 항목 값은 남기지 않는다 (3.8절) — 개수와 사유만.
            _log_info(
                "문서 자동 채움 결과",
                event="template_prefill_done",
                resource_id=f"{data.get('template_id')}.hwpx",
                item_count=len(prefilled),
                status=(
                    f"applied={int(bool(prefill.get('applied')))}"
                    f" skipped={prefill.get('skipped_reason') or '-'}"
                    f" chunks={prefill.get('chunks_called') or 0}"
                    f"/{prefill.get('chunk_count') or 0}"
                    f" failed={int(prefill_failed)}"
                ),
                **log_context,
            )

    # 4) 병합·저장·미리보기 — 세 가지가 한 요청이다.
    #    나누면 저장은 됐는데 미리보기에서 실패한 중간 상태가 캔버스에 생긴다.
    body, failure = await _post_serving(
        "TEMPLATE_FILL_SERVING_ID",
        "/chat/commit",
        {
            "session_id": str(data.get("session_id") or ""),
            "template_id": str(data.get("template_id") or ""),
            "fields_updated": data.get("fields_updated") or {},
            "fields_cleared": data.get("fields_cleared") or [],
            "fields_rejected": data.get("fields_rejected") or [],
            "blocks_added": data.get("blocks_added") or [],
            "block_clears": data.get("block_clears") or [],
            # 문서 자동 채움분 (2026-08-31, 2026-09-22 부터 이 스텝이 직접 부른다).
            # **여기서 처음 저장된다** — 위 3) 은 뽑기만 하고 저장은 이 요청 한 곳에서
            # 한다(한 턴에 두 곳에서 저장하면 순서에 따라 서로를 덮는다).
            # `source_doc_hash` 를 빠뜨리면 세션 표식이 지워져 **다음 턴에 같은 문서를
            # 또 태우고 사용자가 지운 값이 되살아난다** — 저장이 덮어쓰기라 그렇다.
            "fields_prefilled": prefilled,
            "source_doc_hash": source_doc_hash,
            "prefill_failed": prefill_failed,
            # 건너뛴 사유 (2026-09-02). 답변 문구가 여기서 갈린다 — 빼면 "파일을 올렸는데
            # 아무 일도 일어나지 않는" 턴이 생긴다(항목을 다 채운 뒤 올린 경우).
            "prefill_skipped_reason": prefill_skipped_reason,
        },
        read_timeout=30.0,
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
            "병합·저장 실패 — 이번 턴 값이 다음 턴에 유지되지 않는다",
            event="commit_failed",
            error_code=error["error_code"],
            error_type=error_type,
            upstream_status=upstream_status,
            status="retryable" if error["retryable"] else "final",
            **log_context,
        )
        async for event in finish_with_error(error):
            yield event
        return

    result = body or {}
    display_text = str(result.get("text") or "")

    # ── 미리보기를 **채팅 본문 아래에 붙인다** (2026-09-08 요구 변경) ────────────
    #
    # 그전에는 `document_markdown` 을 payload 의 별도 필드로 냈고 "문서 창이 따로
    # 그린다" 고 적어 뒀다. **그 창이 없다** — 006 은 전용 UI 가 없고 채팅이 곧 화면이다.
    # 그래서 그 값은 아무 데도 그려지지 않은 채 계약에만 남아 있었다.
    #
    # 본문에 넣으면 **흘러가는 토큰에도 함께 실려** 사용자가 매 턴 "파일이 지금 어떻게
    # 채워졌는지" 를 그 자리에서 본다 — 요구가 말한 그것이다.
    preview = str(result.get("document_markdown") or "").strip()
    if preview:
        display_text = f"{display_text}\n\n---\n\n**미리보기**\n\n{preview}"
    fields_missing = list(result.get("fields_missing") or [])

    _log_info(
        "턴 마무리",
        event="template_fill_turn_done",
        resource_id=f"{data.get('template_id')}.hwpx",
        item_count=len(result.get("field_values") or {}),
        status=f"missing={len(fields_missing)} ready={int(not fields_missing)}",
        **log_context,
    )

    # 5) 토큰 스트리밍 → result 1회 (GenOS 계약)
    for chunk in _stream_chunks(display_text):
        yield await emit_event("token", chunk)

    # ── payload 는 **사용자가 눈으로 보는 값만** 담는다 (2026-08-28) ────────
    #
    # 이 기능은 앞의 셋과 방향이 반대다. **전용 UI 가 없고 채팅이 곧 화면**이라
    # `text` 를 뺄 수 없다 — `chat_reply` 가 조립하는 그 문장이 이 기능의 출력이다.
    # 그리고 그 문장이 **이미 다 말한다**: 새로 채운 항목과 `이전 → 새 값`, 기각 건수,
    # 본문 추가 번호 목록, 남은 항목, 다음에 할 일.
    #
    # 그래서 같은 내용을 배열로 한 번 더 싣던 값들을 뺐다. 폼처럼 항목 칸을 나열하는
    # 화면이 생기면 `field_values`·`fields_filled` 를 되살린다 — 그때는 안내문이
    # 아니라 칸마다 현재 값이 필요하다.
    #
    #   `field_values` / `fields_filled` / `fields_missing` → 안내문이 말한다
    #   `fields_cleared` / `fields_rejected`               → 안내문이 말한다
    #   `blocks` / `blocks_removed`                        → 안내문이 번호를 붙여 나열한다
    #   `field_values_raw`                                 → 정규화 **전** 원값. 화면에 쓸 자리가 없다
    #   `document_markdown_truncated`                      → 미리보기 길이 상한 표시(내부)
    #
    # **`text` 는 지운다** — `{**data}` 가 실어 나르는 그 값은 **사용자 질문**이라
    # 아래에서 이번 턴 답변으로 덮는다(세 기능은 아예 안 싣지만 여기는 답변이 곧 text 다).
    yield {
        "event": "result",
        "data": {
            **_base_payload(),
            # 채팅 답변 + **미리보기**(위에서 아래에 붙였다). 006 은 전용 UI 가 없어
            # 이 문자열이 곧 화면이다.
            "text": display_text,
            # 다 채웠을 때만 링크가 온다. **`ready_for_download` 플래그는 뺐다**
            # (2026-09-08) — 링크가 있으면 받을 수 있고 없으면 못 받는다. 두 값을 두면
            # 어긋날 자리가 생기고, 그때 화면은 버튼을 켜 놓고 받을 수 없는 상태가 된다
            # (FAQ 의 `faq_download_ready` 를 뺀 것과 같은 판단).
            "download_url": result.get("download_url") or None,
        },
    }
    # ── 2026-09-08 에 더 뺀 것 ──────────────────────────────────────────────
    #   `document_markdown` → **`text` 안으로 들어갔다.** 별도 필드일 때는 그릴 창이
    #                         없어 아무 데도 안 그려졌다
    #   `ready_for_download` → `download_url` 의 유무가 같은 것을 말한다
    #   `error: None`        → 정상 응답에 `error: null` 을 싣지 않는다. 세 기능과 같은
    #                         규약이었는데 이 스텝만 어긋나 있었다(읽는 쪽이 분기를 두
    #                         벌 갖게 된다)
