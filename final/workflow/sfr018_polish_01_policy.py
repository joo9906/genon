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

_LOGGER_NAME = "text_polish_policy"
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
        "error_type": "POLICY_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "설정 확인 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"ERR-{_AREA}-00020002",
        "error_type": "POLICY_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "문서 종류와 톤 설정을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "INPUT_EMPTY": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "POLISH_INPUT_EMPTY",
        "retryable": False,
        "msg": "다듬을 문서나 텍스트를 입력해 주세요.",
    },
    "CONFIG_MISSING": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "POLICY_CONFIG_MISSING",
        "retryable": False,
        "msg": "서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
    },
    "UPSTREAM_FINAL": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "POLICY_UPSTREAM_FINAL",
        "retryable": False,
        "msg": "요청을 처리하지 못했습니다. 관리자에게 문의해 주세요.",
    },
    "SCAN_OCR_TIMEOUT": {
        "error_code": f"ERR-{_AREA}-00020001",
        "error_type": "POLICY_SCAN_OCR_TIMEOUT",
        "retryable": True,
        "msg": "스캔 문서의 글자 인식이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "SCAN_OCR_FAILED": {
        "error_code": f"ERR-{_AREA}-00020002",
        "error_type": "POLICY_SCAN_OCR_FAILED",
        "retryable": True,
        "msg": "스캔 문서의 글자를 읽지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "SCAN_SOURCE_MISSING": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "POLICY_SCAN_SOURCE_MISSING",
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
# MCP 호출 (§H — `{GENOS_URL}/api/gateway/mcp/<id>/mcp`, JSON-RPC tools/call)
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
# MCP 전송 규약
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
                    # 4xx 는 재시도하지 않는다 (§B)
                    return None, (
                        _upstream_kind(response),
                        "HTTPStatusError",
                        response.status_code,
                    )
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
    body, failure = await _post_json(
        url, payload, read_timeout=read_timeout, extra_headers=_MCP_HEADERS
    )
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
# 스캔 쪽 OCR — 첨부 전처리기가 남긴 표식을 MCP `genon_ocr` 로 채운다
# ─────────────────────────────────────────────────────────────
# 첨부 전처리기(`dev_preprocessor.py`, `ocr_defer=True`)는 스캔 pdf 쪽을 읽지 않고 쪽
# 이미지(NFS)와 표식(`[[GENON_SCAN page=N image=…]]`)만 남긴다. 여기서 표식을 찾아
# `ocr_scan_pages` 로 읽고 표식을 그 글로 바꾼다.
#
# - **실패하면 요청을 세운다.** 표식을 지우고 넘기면 그 쪽 본문이 결과에서 조용히 빠지고,
#   표식을 남기면 LLM 이 그 문자열을 본문으로 읽는다.
# - **한 문서의 연속한 쪽을 한 번에 보낸다.** 쪽마다 되풀이되는 머리말을 빼고 쪽을 넘는
#   문단을 잇는 일이 쪽들을 함께 봐야 된다. 사이에 텍스트 쪽이 끼면 나눠 보낸다.
# - 원본은 NFS 보관 정책(한 달)으로 지워진다 — 오래된 대화를 다시 돌리면
#   `IMAGE_NOT_FOUND` 가 오고, 다시 올려 달라고 안내한다(재시도로는 안 낫는다).
_SCAN_MARK_RE = re.compile(r"\[\[GENON_SCAN page=(\d+) image=([^\]\n]+)\]\]")
_OCR_BATCH_PAGES = 16              # MCP 한 호출 상한과 같다
_OCR_PAGE_SECONDS = 20.0           # 쪽당 응답 대기 예산 — MCP 가 4쪽씩 겹쳐 OCR 한다
_OCR_TOOL_ERRORS = {
    "IMAGE_NOT_FOUND": "SCAN_SOURCE_MISSING",
    "NFS_ROOT_MISSING": "CONFIG_MISSING",
    "PATH_OUTSIDE_ROOT": "CONFIG_MISSING",
    "OCR_TRANSPORT_FAILED": "SCAN_OCR_TIMEOUT",
}


def _scan_batches(text: str) -> list:
    """표식 → MCP 한 번에 보낼 이미지 묶음. 같은 문서 폴더의 연속한 쪽끼리 묶는다."""
    pages: dict = {}
    for match in _SCAN_MARK_RE.finditer(text):
        pages.setdefault(match.group(2).strip(), int(match.group(1)))
    batches: list = []
    for image, page in pages.items():
        folder = image.rsplit("/", 1)[0] if "/" in image else ""
        last = batches[-1] if batches else None
        if (last and last["folder"] == folder and last["page"] == page - 1
                and len(last["images"]) < _OCR_BATCH_PAGES):
            last["page"] = page
            last["images"].append(image)
        else:
            batches.append({"folder": folder, "page": page, "images": [image]})
    return [batch["images"] for batch in batches]


async def _ocr_scanned_pages(text: str, log_context: dict):
    """(표식을 OCR 글로 바꾼 본문, 오류 dict 또는 None). 표식이 없으면 그대로 돌려준다."""
    batches = _scan_batches(text)
    if not batches:
        return text, None
    recognized: dict = {}
    for images in batches:
        body, failure = await _mcp_call(
            "OCR_MCP_ID",
            "ocr_scan_pages",
            {"image_paths": images},
            read_timeout=_OCR_PAGE_SECONDS * len(images) + 30.0,
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
                if isinstance(page, dict) and page.get("image_path") in images:
                    recognized[page["image_path"]] = str(page.get("text") or "")
            if any(image not in recognized for image in images):
                error_type, key = "OCR_PAGES_MISSING", "SCAN_OCR_FAILED"
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
            return text, error
    _log_info(
        "스캔 쪽 OCR 완료",
        event="scan_ocr_resolved",
        item_count=len(recognized),
        **log_context,
    )
    return _SCAN_MARK_RE.sub(lambda match: recognized[match.group(2).strip()], text), None


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


# 최상위 키 → 캔버스 변수 이름. 프론트는 `overrideConfig.vars` 로 감싸지 않고 최상위에
# 바로 싣는다(`{"text": …, "polish_doc_type": …}`). 적힌 이름만 읽는 이유는 플랫폼이 최상위에
# 넣는 키(`genos_state`·`socketIOClientId` …)가 변수로 섞이지 않게 하려는 것이다.
_VAR_KEYS = {
    "polish_doc_type": "polish_doc_type",
    "polish_tone": "polish_tone",
    "genosUploaded": "genosUploaded",
}


# 캔버스 변수 → 기본값 환경변수. 프론트도 `vars` 도 값을 안 줬을 때만 쓴다.
# 값 검증은 여기서 하지 않는다 — 목록 밖 값은 받는 쪽(MCP `lang_policy`·코드서빙)이 고른
# 값과 똑같이 판정한다. 호출마다 읽으므로 스텝을 다시 등록하지 않고 바꿀 수 있다.
_ENV_DEFAULTS = {
    "polish_doc_type": "POLISH_DEFAULT_DOC_TYPE",
    "polish_tone": "POLISH_DEFAULT_TONE",
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

    # 업로드 문서 우선, 없으면 채팅 텍스트
    source_text, error = await _ocr_scanned_pages(
        _extract_uploaded_markdown(variables.get("genosUploaded") or ""), log_context
    )
    if error is not None:
        return {**data, "error": error}
    source_text = source_text or question
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
            # 서빙이 재시도 불가로 못 박은 응답은 그 판정을 그대로 따른다
            # (`_upstream_kind` 머리말 참고).
            else "UPSTREAM_FINAL" if kind == "upstream_final"
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
