"""번역 스텝 1/2 — 원본 확보 + 언어 감지 + 방향 검증 (area 02).

**이 스텝은 신규다.** 번역은 지금 코드서빙 전용이라 캔버스에 노드가 없다.

캔버스에서 하는 일:

```
genosUploaded 파싱 (첨부용 전처리기 산출물 = 원문)
        없으면 → question (사용자가 친 텍스트)
      ↓
MCP lang_policy.validate_direction — 한국어 축 검증
```

## 원본 확보 — 전처리기 산출물 하나다

첨부 문서는 어차피 전처리기를 지나오므로 두 번 파싱할 이유가 없다 — 첨부용 등록을
**`preprocessor/only_me.py`**(파싱 전용, 청킹 없음)로 둔다. 그쪽은 **이어붙이면 원문**을
계약으로 지므로, 검색용 가공을 번역해 결과물에 싣는 일이 생기지 않는다.

**`truncated` 를 반드시 본다.** 상한에서 잘린 문서를 번역하면 뒷부분이 통째로 빠진 채
정상 결과처럼 내려간다 — 사용자는 번역이 끝났다고 믿는다.

## 왜 방향 판정이 LLM 이 아닌가

**거부 판정**이기 때문이다. 사용자의 요청을 막는 판단을 LLM 에 맡기면 같은 입력에 대해
어떤 날은 통과하고 어떤 날은 막힌다. 스크립트(문자 체계) 기반으로 결정적으로 감지한다 —
그래서 MCP 도구(`lang_policy`)로 뺄 수 있었다.

**감지 불가는 거부가 아니다.** 숫자·기호뿐인 입력은 방향 검증만 건너뛰고 번역은 진행한다.

## 용어사전 적용 여부도 여기서 확정된다

`validate_direction` 이 `glossary_applies` 를 함께 낸다 — 용어사전은 **한국어·영어에만**
있고 중국어·태국어·베트남어·러시아어는 LLM 만으로 번역한다(요구 확정).
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
_ALLOWED_LOG_FIELDS = (
    "event", "trace_id", "request_id", "resource_id", "status",
    "duration_ms", "item_count", "upstream_status", "error_code", "error_type",
)

_LOGGER_NAME = "translate_detect"
_LOG = logging.getLogger(_LOGGER_NAME)

# GenOS 런타임 로거(`common/logger.py`)와 같은 형식으로 stdout 에 낸다. 런타임은 루트 레벨을
# WARNING 으로 두므로 여기서 레벨을 정하지 않으면 INFO 가 전부 버려지고, 그 형식은 `extra`
# 를 찍지 않으므로 허용 필드는 포매터가 줄 끝에 붙인다.
_LOG_FORMAT = "%(levelname)s: %(asctime)s|[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S %Z"


class _FieldFormatter(logging.Formatter):
    def formatMessage(self, record: logging.LogRecord) -> str:
        line = super().formatMessage(record)
        pairs = [
            f"{key}={' '.join(str(getattr(record, key)).split())}"
            for key in _ALLOWED_LOG_FIELDS
            if getattr(record, key, None) is not None
        ]
        return f"{line} | {' '.join(pairs)}" if pairs else line


def _log_level() -> int:
    level = logging.getLevelName((os.environ.get("LOG_LEVEL") or "INFO").strip().upper())
    return level if isinstance(level, int) else logging.INFO


if not _LOG.handlers:
    _log_handler = logging.StreamHandler(sys.stdout)
    _log_handler.setFormatter(_FieldFormatter(_LOG_FORMAT, _LOG_DATEFMT))
    _LOG.addHandler(_log_handler)
    # 루트로 올리지 않는다 — 런타임 루트 핸들러가 같은 줄을 한 번 더 찍는다.
    _LOG.propagate = False
_LOG.setLevel(_log_level())


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
    # stacklevel=3 — 줄 머리의 파일·함수가 이 래퍼가 아니라 호출부를 가리키게 한다.
    _LOG.log(level, message, extra=extra, stacklevel=3)


# ─────────────────────────────────────────────────────────────
# 디버그 에코 — **테스트 기간 한정**
# ─────────────────────────────────────────────────────────────
# 3.8절 화이트리스트가 값을 버리기 때문에(허용 목록 밖은 **이름만** 남는다) 로그만으로는
# 무엇이 왜 실패했는지 알 수 없다 — 특히 게이트웨이가 거절한 **사유는 응답 본문에만**
# 적혀 있고 그 본문은 어디에도 남지 않는다(MCP 406 을 찾는 데 걸린 시간이 그것이다).
# 원인을 찾는 동안 표준 로그와 **별도로** 한 줄을 더 뿜는다. 로그 경로는 그대로다 —
# 걷어낼 때 이 블록과 `_debug_echo` 호출만 지우면 원래 규약으로 돌아온다.
#
# - 표준 로그와 섞이지 않게 **stderr** 로 쓴다. 플랫폼은 stdout·stderr 를 둘 다 수집한다.
# - **`GENON_DEBUG=1` 일 때만 낸다(기본 꺼짐).** 허용 필드 밖 값이 남으므로 운영에서
#   켜 두지 않는다.
# - 값은 `_DEBUG_MAX_VALUE` 로 자른다. 문서 원문이 통째로 실리면 이 에코 자체가 유출
#   경로가 된다(3.8절).
_DEBUG_MAX_VALUE = 300


def _debug_echo(message: str, *, event: str = "", **fields) -> None:
    if (os.environ.get("GENON_DEBUG") or "").strip().lower() not in {"1", "true", "on"}:
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
    # 파싱은 첨부용 전처리기가 하고 그 실패는 적재 층에서 예외로 드러나므로 스텝에는
    # "첨부 없음" 과 "읽지 못함" 을 가를 근거가 없다. **낼 수 없는 오류를 표에 남기지
    # 않는다** — 읽는 쪽이 그 사건이 처리된다고 믿게 된다.
    "INPUT_UNUSABLE": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "TRANSLATE_INPUT_UNUSABLE",
        "retryable": False,
        "msg": "입력 내용을 확인해 주세요.",
    },
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
    "SCAN_OCR_TIMEOUT": {
        "error_code": f"ERR-{_AREA}-00020001",
        "error_type": "TRANSLATE_SCAN_OCR_TIMEOUT",
        "retryable": True,
        "msg": "스캔 문서의 글자 인식이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "SCAN_OCR_FAILED": {
        "error_code": f"ERR-{_AREA}-00020002",
        "error_type": "TRANSLATE_SCAN_OCR_FAILED",
        "retryable": True,
        "msg": "스캔 문서의 글자를 읽지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "SCAN_SOURCE_MISSING": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "TRANSLATE_SCAN_SOURCE_MISSING",
        "retryable": False,
        "msg": "첨부한 스캔 문서의 원본을 찾지 못했습니다. 파일을 다시 올려 주세요.",
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
# 서빙이 "재시도해도 같다" 고 말한 응답인가
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
# MCP 전송 규약 — 실환경 406 회피
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
# 스캔 쪽 OCR — 첨부 전처리기가 남긴 표식을 MCP `genon_ocr` 로 채운다
# ─────────────────────────────────────────────────────────────
# 첨부 전처리기(`high_preprocessor.py`, `ocr_defer=True`)는 스캔 pdf 쪽을 읽지 않고 쪽
# 이미지를 CDN(MinIO)에 올려 표식(`[[GENON_SCAN doc=… page=N image=presigned URL]]`)만
# 남긴다. 여기서 표식을 찾아 `ocr_scan_pages` 로 읽고 표식을 그 글로 바꾼다.
#
# - **읽는 동안 진행 상황을 흘린다.** 화면은 `token` 의 `<think>` … `</think>` 를 사고 과정
#   상자로 그린다. 묶음마다 몇 쪽을 읽는지, 기다리는 동안 경과 시간, 끝나면 쪽마다 문단 ·
#   단 수를 싣는다 — 수십 초 동안 화면이 비어 있으면 멈춘 것으로 보인다.
# - **실패하면 요청을 세운다.** 표식을 지우고 넘기면 그 쪽 본문이 결과에서 조용히 빠지고,
#   표식을 남기면 LLM 이 그 문자열을 본문으로 읽는다.
# - **한 문서의 연속한 쪽을 한 번에 보낸다.** 쪽마다 되풀이되는 머리말을 빼고 쪽을 넘는
#   문단을 잇는 일이 쪽들을 함께 봐야 된다. 사이에 텍스트 쪽이 끼면 나눠 보낸다.
#   같은 문서인지는 표식의 `doc` 으로 가린다 — URL 모양(객체 키 배치)은 CDN 이 정한다.
# - presigned URL 은 만료된다 — 오래된 대화를 다시 돌리면 `IMAGE_NOT_FOUND` 가 오고,
#   다시 올려 달라고 안내한다(재시도로는 안 낫는다).
_SCAN_MARK_RE = re.compile(r"\[\[GENON_SCAN doc=(\w+) page=(\d+) image=([^\]\s]+)\]\]")
_OCR_BATCH_PAGES = 16              # MCP 한 호출 상한과 같다
_OCR_PAGE_SECONDS = 20.0           # 쪽당 응답 대기 예산 — MCP 가 4쪽씩 겹쳐 OCR 한다
_OCR_HEARTBEAT_SECONDS = 8.0       # 이만큼 소식이 없으면 경과 시간을 한 줄 흘린다
_THINK_OPEN = "<think>"            # 화면이 이 태그 사이를 사고 과정 상자로 그린다
_THINK_CLOSE = "</think>"
_OCR_TOOL_ERRORS = {
    "IMAGE_NOT_FOUND": "SCAN_SOURCE_MISSING",
    "URL_NOT_ALLOWED": "CONFIG_MISSING",
    "IMAGE_FETCH_FAILED": "SCAN_OCR_FAILED",
    "OCR_TRANSPORT_FAILED": "SCAN_OCR_TIMEOUT",
}


def _scan_batches(text: str) -> list:
    """표식 → MCP 한 번에 보낼 이미지 묶음. 같은 문서(`doc`)의 연속한 쪽끼리 묶는다."""
    pages: dict = {}
    for match in _SCAN_MARK_RE.finditer(text):
        pages.setdefault(match.group(3), (match.group(1), int(match.group(2))))
    batches: list = []
    for image, (doc, page) in pages.items():
        last = batches[-1] if batches else None
        if (last and last["doc"] == doc and last["page"] == page - 1
                and len(last["images"]) < _OCR_BATCH_PAGES):
            last["page"] = page
            last["images"].append(image)
        else:
            batches.append({"doc": doc, "page": page, "images": [image]})
    return [batch["images"] for batch in batches]


async def _no_emit(text: str) -> None:
    return None


def _token_emitter(data: dict):
    """화면에 `token` 이벤트를 흘리는 함수. 소켓이 없거나 세션을 모르면 아무것도 안 한다.

    전송 실패는 삼킨다 — 진행 안내가 못 나간 것 때문에 OCR 결과를 버리지 않는다.
    """
    try:
        from main_socketio import sio_server
    except ImportError:
        return _no_emit
    sid = _session_id(data)
    if not sid:
        return _no_emit

    async def emit(text: str) -> None:
        try:
            await sio_server.emit("token", text, room=sid)
            # WebSocket write buffer flush (가이드 5.2·D.4)
            await asyncio.sleep(0)
        except Exception as exc:  # noqa: BLE001 - 안내 전송 실패가 요청을 세우지 않는다
            _log_warning("진행 안내 전송 실패", event="token_emit_failed", error_type=type(exc).__name__)

    return emit


async def _await_with_heartbeat(awaitable, emit):
    """`awaitable` 을 기다리는 동안 `_OCR_HEARTBEAT_SECONDS` 마다 경과 시간을 흘린다."""
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(awaitable)
    start = loop.time()
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=_OCR_HEARTBEAT_SECONDS)
            if done:
                return task.result()
            await emit(f"  · 인식 중… {int(loop.time() - start)}초\n")
    finally:
        if not task.done():
            task.cancel()


def _scan_page_note(page: dict, number) -> str:
    """OCR 결과 한 쪽의 요약 한 줄. 본문 글자는 싣지 않는다 — 건수만이다."""
    note = f"- {number}쪽: 문단 {int(page.get('paragraph_count') or 0)}개"
    columns = int(page.get("column_count") or 0)
    return note + (f" · {columns}단\n" if columns > 1 else "\n")


async def _ocr_scanned_pages(text: str, log_context: dict, emit=_no_emit):
    """(표식을 OCR 글로 바꾼 본문, 오류 dict 또는 None). 표식이 없으면 그대로 돌려준다.

    읽는 동안 `emit` 으로 진행 상황을 `<think>` … `</think>` 안에 흘린다. 닫는 태그는
    **실패해도 보낸다** — 열린 채 두면 그 뒤에 흘리는 답변까지 사고 과정 상자에 들어간다.
    """
    batches = _scan_batches(text)
    if not batches:
        return text, None
    numbers = {match.group(3): int(match.group(2)) for match in _SCAN_MARK_RE.finditer(text)}
    total = sum(len(images) for images in batches)
    recognized: dict = {}
    await emit(f"{_THINK_OPEN}스캔 PDF를 분석하고 있습니다. 스캔 쪽 {total}개를 Paddle OCR 로 읽습니다.\n")
    try:
        for images in batches:
            first, last = numbers[images[0]], numbers[images[-1]]
            await emit(f"\n{first}쪽 글자 인식 중…\n" if first == last else f"\n{first}~{last}쪽 글자 인식 중…\n")
            body, failure = await _await_with_heartbeat(
                _mcp_call(
                    "OCR_MCP_ID",
                    "ocr_scan_pages",
                    {"image_urls": images},
                    read_timeout=_OCR_PAGE_SECONDS * len(images) + 30.0,
                ),
                emit,
            )
            key = error_type = upstream_status = None
            if failure is not None:
                kind, error_type, upstream_status = failure
                key = (
                    "CONFIG_MISSING" if kind == "config"
                    else "SCAN_OCR_TIMEOUT" if kind == "transport"
                    else "SCAN_OCR_FAILED"
                )
            elif not isinstance(body, dict) or not body.get("ok"):
                error_type = str(body.get("error_type") or "OCR_FAILED") if isinstance(body, dict) else "OCR_FAILED"
                key = _OCR_TOOL_ERRORS.get(error_type, "SCAN_OCR_FAILED")
            else:
                for page in body.get("pages") or []:
                    if isinstance(page, dict) and page.get("image_url") in images:
                        recognized[page["image_url"]] = str(page.get("text") or "")
                        await emit(_scan_page_note(page, numbers[page["image_url"]]))
                if any(image not in recognized for image in images):
                    error_type, key = "OCR_PAGES_MISSING", "SCAN_OCR_FAILED"
                else:
                    running, dropped = int(body.get("running_count") or 0), int(body.get("dropped_count") or 0)
                    if running:
                        await emit(f"  쪽마다 되풀이되는 머리말·꼬리말 {running}종을 뺐습니다.\n")
                    if dropped:
                        await emit(f"  인식 점수가 낮은 글 상자 {dropped}개는 뺐습니다.\n")
            if key is not None:
                error = _error(key)
                _log_warning(
                    "스캔 쪽 OCR 실패",
                    event="scan_ocr_failed",
                    error_code=error["error_code"],
                    error_type=error_type,
                    upstream_status=upstream_status,
                    item_count=len(images),
                    status="retryable" if error["retryable"] else "final",
                    **log_context,
                )
                await emit("\n글자 인식에 실패했습니다.\n")
                return text, error
        await emit(f"\n스캔 쪽 {total}개를 모두 읽었습니다.\n")
    finally:
        await emit(_THINK_CLOSE)
    _log_info(
        "스캔 쪽 OCR 완료",
        event="scan_ocr_resolved",
        item_count=len(recognized),
        **log_context,
    )
    return _SCAN_MARK_RE.sub(lambda match: recognized[match.group(3)], text), None


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


# 최상위 키 → 캔버스 변수 이름. 프론트는 `overrideConfig.vars` 로 감싸지 않고 최상위에
# 바로 싣는다(`{"text": …, "translate_target_lang": …}`). 적힌 이름만 읽는 이유는 플랫폼이 최상위에
# 넣는 키(`genos_state`·`socketIOClientId` …)가 변수로 섞이지 않게 하려는 것이다.
_VAR_KEYS = {
    "translate_target_lang": "translate_target_lang",
    "translate_source_lang": "translate_source_lang",
    "translate_register": "translate_register",
    "genosUploaded": "genosUploaded",
}


# 캔버스 변수 → 기본값 환경변수. 프론트도 `vars` 도 값을 안 줬을 때만 쓴다.
# 값 검증은 여기서 하지 않는다 — 목록 밖 값은 받는 쪽(MCP `lang_policy`·코드서빙)이 고른
# 값과 똑같이 판정한다. 호출마다 읽으므로 스텝을 다시 등록하지 않고 바꿀 수 있다.
_ENV_DEFAULTS = {
    "translate_target_lang": "TRANSLATE_DEFAULT_TARGET_LANG",
    "translate_source_lang": "TRANSLATE_DEFAULT_SOURCE_LANG",
    "translate_register": "TRANSLATE_DEFAULT_REGISTER",
}


def _canvas_vars(data: dict) -> dict:
    """캔버스 변수를 모은다 — 최상위 키 > `overrideConfig.vars` > 기본값 환경변수.

    최상위가 이기는 이유: 값을 고르는 것은 프론트다. 플랫폼이 `vars` 에 캔버스 기본값을
    채워 넣는 배선이면 vars 가 먼저일 때 사용자가 고른 값이 조용히 무시된다.
    빈 값은 없는 것으로 본다.
    """
    variables = dict((data.get("overrideConfig") or {}).get("vars") or {})
    for var_key, env_name in _ENV_DEFAULTS.items():
        default = (os.environ.get(env_name) or "").strip()
        if default and variables.get(var_key) in (None, ""):
            variables[var_key] = default
    for top_key, var_key in _VAR_KEYS.items():
        value = data.get(top_key)
        if value not in (None, ""):
            variables[var_key] = value
    return variables


# 발화를 담는 키. 운영 브리지(`genos_files/bridge.py`)와 같은 이름·순서다 — 캔버스·채팅·
# 외부 호출이 서로 다른 이름으로 싣고, 하나만 보면 **발화가 있는데 빈 입력으로** 끝난다.
_QUESTION_KEYS = ("question", "text", "message", "query")


def _question(data: dict) -> str:
    """발화를 찾는다 — 최상위 키 순서대로, 없으면 중첩 `request_payload` 에서 같은 순서로.

    문자열만 받는다. 플랫폼이 `message` 에 객체를 싣는 배선이면 `str()` 로 떨어뜨린
    파이썬 repr 이 발화로 LLM 에 들어간다.
    """
    nested = data.get("request_payload")
    for source in (data, nested if isinstance(nested, dict) else {}):
        for key in _QUESTION_KEYS:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _log_context(data: dict) -> dict:
    state = data.get("genos_state") or {}
    return {"trace_id": state.get("trace_id")}


def _session_id(data: dict) -> str:
    """운영 브리지(`genos_files/bridge.py`)의 폴백 순서를 따른다.

    하나만 보면 UI 배선에 따라 이벤트가 엉뚱한 방으로 가거나 아예 안 나간다.
    """
    state = data.get("genos_state") or {}
    for key in ("socketIOClientId", "sessionId", "session_id"):
        value = data.get(key) or state.get(key)
        if value:
            return str(value)
    return ""


# ─────────────────────────────────────────────────────────────
# 이번 턴의 첨부 — `file_ids`
# ─────────────────────────────────────────────────────────────
# 세션을 이어 쓰면 플랫폼이 앞 턴에 올린 문서를 `genosUploaded` 에 계속 싣는다. 그대로
# 읽으면 텍스트만 입력한 턴도 예전 파일로 처리된다. **스텝 결과에서 지워도 소용없다** —
# 다음 턴 값은 우리 결과가 아니라 플랫폼이 세션 업로드로 다시 채운다(실측).
#
# 프론트가 이번 턴에 첨부한 파일 id 를 `overrideConfig.file_ids` 로 싣는다. **id 가 하나라도
# 있을 때만 `genosUploaded` 를 읽고, 키가 없거나 비었으면(`[]`·`[""]`) 사용자 입력만 쓴다.**
# 젠포탈은 요청 본문의 `file_ids` 를 `/run/v2` 로 넘기지 않으므로 overrideConfig 에 따로
# 실어야 한다 — 싣지 않으면 첨부가 무시된다.


def _file_ids(data: dict):
    """이번 턴에 첨부한 파일 id 목록. 프론트가 `file_ids` 를 보내지 않았으면 `None`."""
    nested = data.get("request_payload")
    override = data.get("overrideConfig") if isinstance(data.get("overrideConfig"), dict) else {}
    variables = override.get("vars") if isinstance(override.get("vars"), dict) else {}
    for source in (override, variables, data, nested if isinstance(nested, dict) else {}):
        if not isinstance(source, dict) or "file_ids" not in source:
            continue
        value = source["file_ids"]
        if isinstance(value, str):
            raw = value.strip()
            try:
                value = json.loads(raw) if raw.startswith("[") else raw.split(",")
            except json.JSONDecodeError:
                value = [raw]
        if not isinstance(value, (list, tuple)):
            value = [] if value is None else [value]
        return [str(item).strip() for item in value if item is not None and str(item).strip()]
    return None


def _turn_upload(data: dict, variables: dict, log_context: dict) -> str:
    """이번 턴에 읽을 `genosUploaded`. `file_ids` 가 없거나 비었으면 빈 문자열."""
    uploaded = str(variables.get("genosUploaded") or "")
    file_ids = _file_ids(data)
    if not file_ids:
        if uploaded.strip():
            _log_info(
                "이번 턴 file_ids 가 없어 genosUploaded 를 쓰지 않는다",
                event="upload_ignored",
                **log_context,
            )
        return ""
    return uploaded


# ─────────────────────────────────────────────────────────────
# 입력 판단 — 코드서빙 `POST /input/check`
# ─────────────────────────────────────────────────────────────
# 원문을 확정한 뒤 본 기능 전에 묻는다. 뜻을 알 수 없는 입력(낱자모 나열 · 빈 표 틀)을
# 넣으면 LLM 이 거절 문장을 지어내거나 입력을 되뱉고, 그 결과가 정상 응답처럼 나간다.
#
# - **판단은 코드서빙이 한다** — LLM 클라이언트 · 프롬프트 · 판단 모델 지정
#   (`INPUT_CHECK_LLM_SERVING_ID`)이 거기 있다. 이 스텝은 LLM 을 직접 부르지 않는다.
# - **판단을 못 하면 통과시킨다** (서빙 장애 · 이상한 응답). 판단기는 품질 장치라 그것
#   때문에 기능 전체가 서면 안 된다. 서빙도 같은 규약이다(`judged=false`).
# - 앞부분만 보낸다 — 서빙도 같은 길이까지만 판단에 쓴다.
# - 막을 때의 문장은 Disclaimer MCP(`translate_input_unusable`)에서 받고, 못 받으면 고정 문장이다.
_INPUT_CHECK_PATH = "/input/check"
_INPUT_CHECK_CHARS = 2000
_INPUT_CHECK_READ_TIMEOUT = 30.0
_INPUT_CHECK_SERVING_ENV = "TRANSLATION_SERVING_ID"
_INPUT_UNUSABLE_KIND = "translate_input_unusable"


async def _post_serving(env_name: str, path: str, payload: dict, *, read_timeout: float):
    serving_id = (os.environ.get(env_name) or "").strip()
    if not serving_id:
        return None, ("config", f"{env_name}_MISSING", None)
    try:
        url = f"{_gateway_base()}/code_serving/{serving_id}/{path.lstrip('/')}"
    except RuntimeError:
        return None, ("config", "GENOS_URL_MISSING", None)
    return await _post_json(url, payload, read_timeout=read_timeout)


_DISCLAIMER_TOOL = "widget_disclaimer"
_DISCLAIMER_READ_TIMEOUT = 15.0
_DISCLAIMER_DEFAULT_AGENT = "SFR018"


def _disclaimer_ids() -> dict:
    """`DISCLAIMER_IDS` → `{안내 종류: 번호}`. 읽을 수 없는 항목은 버린다."""
    raw = (os.environ.get("DISCLAIMER_IDS") or "").strip()
    pairs: dict = {}
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            pairs = {str(name): str(value) for name, value in parsed.items()}
    else:
        for part in raw.split(","):
            name, sep, value = part.partition("=")
            if sep:
                pairs[name] = value
    return {name.strip(): value.strip() for name, value in pairs.items() if name.strip() and value.strip()}


def _fill_disclaimer(template: str, values: dict) -> str:
    text = template
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    if values and text == template:
        text = f"{next(iter(values.values()))}{text}"
    return text


async def _disclaimer(kind: str, fallback: str, values: dict, log_context: dict) -> str:
    """안내 하나의 화면 문장. 못 받으면 `fallback`."""
    disclaimer_id = _disclaimer_ids().get(kind)
    if not disclaimer_id:
        return fallback
    body, failure = await _mcp_call(
        "DISCLAIMER_MCP_ID",
        _DISCLAIMER_TOOL,
        {
            "agent_id": (os.environ.get("DISCLAIMER_AGENT_ID") or _DISCLAIMER_DEFAULT_AGENT).strip(),
            "disclaimer_id": disclaimer_id,
        },
        read_timeout=_DISCLAIMER_READ_TIMEOUT,
    )
    template = ""
    if failure is None:
        template = str(body.get("text") or "") if isinstance(body, dict) else str(body or "")
    template = template.strip()
    if not template:
        _log_warning(
            "안내 문구를 받지 못해 고정 문장을 쓴다",
            event="disclaimer_fallback",
            resource_id=kind,
            error_type=failure[1] if failure else "EMPTY_TEXT",
            upstream_status=failure[2] if failure else None,
            **log_context,
        )
        return fallback
    return _fill_disclaimer(template, values)


async def _check_input(source_text: str, log_context: dict):
    """못 돌릴 입력이면 오류 dict, 아니면 `None`. 판단 실패는 `None`(통과)이다."""
    body, failure = await _post_serving(
        _INPUT_CHECK_SERVING_ENV,
        _INPUT_CHECK_PATH,
        {"text": source_text[:_INPUT_CHECK_CHARS]},
        read_timeout=_INPUT_CHECK_READ_TIMEOUT,
    )
    if failure is not None or not isinstance(body, dict):
        _log_warning(
            "입력 판단을 못 해 통과시킨다",
            event="input_check_skipped",
            error_type=failure[1] if failure else "InvalidBody",
            upstream_status=failure[2] if failure else None,
            **log_context,
        )
        return None
    if body.get("usable") is not False:
        return None

    error = _error("INPUT_UNUSABLE")
    error["msg"] = await _disclaimer(_INPUT_UNUSABLE_KIND, error["msg"], {}, log_context)
    _log_warning(
        "못 돌릴 입력이라 멈춘다",
        event="input_unusable",
        error_code=error["error_code"],
        error_type=_ERRORS["INPUT_UNUSABLE"]["error_type"],
        resource_id=str(body.get("reason") or ""),
        status="final",
        **log_context,
    )
    return error


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

    question = _question(data)
    variables = _canvas_vars(data)

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
    source_text = _extract_uploaded_markdown(_turn_upload(data, variables, log_context))
    source_kind = "preprocessor" if source_text else "text"
    source_text, error = await _ocr_scanned_pages(source_text, log_context, _token_emitter(data))
    if error is not None:
        return {**data, "error": error}

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

    error = await _check_input(source_text, log_context)
    if error is not None:
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
