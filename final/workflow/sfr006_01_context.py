"""SFR-006 스텝 1/3 — 템플릿 컨텍스트 확정 (area 02).

캔버스에서 하는 일: 세션과 워크플로우 변수로 **어느 템플릿인지** 확정하고, 그 템플릿의
항목 목록·지금까지 채워진 값을 가져와 다음 스텝과 캔버스 분기에 넘긴다.

## 왜 이 스텝이 따로 있나

여기서 나오는 `fields_missing` / `ready_for_download` 가 **캔버스 분기의 근거**다.
"다 채워졌으면 다운로드 안내 노드로, 아니면 추출 스텝으로" 를 이 스텝 뒤에 걸 수 있다.
한 덩어리였을 때는 그 판정이 코드 안에 묻혀 있어 캔버스에서 보이지 않았다.

## 업로드 문서로 알아서 채운다 — **호출은 스텝 3 이 한다** (2026-08-31, 2026-09-22 변경)

채팅 시작 시 사용자가 문서를 올리면 그 내용으로 **빈 항목을 자동으로 채운다.** 문서는
캔버스 변수 `genosUploaded`(전처리기 산출물)로 온다 — FAQ 스텝 1 이 쓰는 것과 같은
경로이고, `_uploaded_markdown` 은 그쪽의 **의도된 사본**이다(스텝 파일 간 중복은 §D 규율).

**문서를 `question` 에 넣지 않는다.** 코드서빙이 발화를 `MAX_MESSAGE_CHARS`(2만 자)에서
**조용히 자르고**, 발화 추출 프롬프트는 "이번 턴 사용자가 말한 것" 만 담으라고 못박은
지시문이라 문서를 그 자리에 넣으면 지움 지시를 문서 문장에서 찾아내려 든다.

**2026-09-22 이전에는 이 스텝이 `POST /chat/prefill` 을 직접 불렀다.** 문서가 길면
조각마다 LLM 호출이 걸려 최대 180초가 걸리는데, 이 스텝은 **중간 스텝이라 소켓에 아무것도
흘릴 수 없다**(§D.1 — generator 가 아니다) — 그래서 그 시간 내내 화면이 비어 있었다.
**진행 상황을 흘리려면 소켓을 쥔 스텝(마지막 스텝, `sfr006_03_commit.py`)이 불러야
하므로 호출 자체를 그쪽으로 옮겼다.** 이 스텝은 이제 문서 원문(`document`)만 뽑아
다음 스텝으로 그대로 넘긴다 — 스텝 2(`sfr006_02_extract.py`)는 그 값을 읽지 않고
`{**data}` 로 통과시키기만 한다.

**그 대가로 `fields_missing`/`ready_for_download` 가 문서 반영분을 반영하지 못한다.**
이 값은 여전히 "지금까지 대화로 모인 값" 만 본다 — 문서가 채울 항목까지 계산하려면
프리필을 여기서 미리 돌려야 하는데, 그러면 스트리밍을 옮긴 의미가 없어진다. **캔버스가
이 값으로 "다 채워졌으면 다운로드로" 분기를 걸어 두었다면, 문서만으로 완성되는 턴에서
그 분기가 한 턴 늦게(스텝 3 이 실제로 채운 뒤) 반영된다** — 다음 턴에는 `ready_for_download`
가 정확하다. 스텝 3 의 머리말에 같은 트레이드오프가 적혀 있다.

**스텝을 늘리지 않았다.** 자동 채움 실패는 **오류가 아니다**(대화로 채우는 원래 흐름을
막지 않는다) — 스텝 3 이 그 실패를 답변 문구에 한 줄 싣는다.

## 이 파일이 지키는 것 (GENOS_RULES §D)

- **파일을 더 쪼개지 않는다.** 캔버스 파이썬 스텝은 코드 한 덩어리로 등록되므로
  로깅·오류표·게이트웨이 클라이언트를 공용 모듈로 뺄 수 없다. 스텝 파일 간 중복은 의도한 것이다.
- **쓰는 패키지는 `httpx` 뿐이다** (§D.3 — 워크플로우 이미지에 포함된 것만).
  `lxml`·`redis`·`jinja2` 는 전부 코드서빙 쪽에 있다.
- **중간 스텝이라 generator 가 아니다.** `dict` 를 돌려준다 (§D.1). 스트리밍과
  `event: result` 는 마지막 스텝(`sfr006_03_commit.py`)이 담당한다.
- **오류는 예외가 아니라 `data["error"]`** (§A.4). 다음 스텝이 그걸 보고 통과시킨다.
- **`{**data, ...}` 로 돌려준다.** `data` 를 통째로 갈면 `genos_state`(trace_id)를 잃는다.
"""

import asyncio
import json
import logging
import os
import sys
import re

import httpx

# ─────────────────────────────────────────────────────────────
# 로깅 (§C / 가이드 3.8) — 허용 필드만, 값은 반드시 extra 로.
# 메시지에 f-string 으로 값을 끼워 넣으면 화이트리스트가 무력해진다.
# ─────────────────────────────────────────────────────────────
_ALLOWED_LOG_FIELDS = frozenset({
    "event", "trace_id", "request_id", "resource_id", "status",
    "duration_ms", "item_count", "upstream_status", "error_code", "error_type",
})

_LOGGER_NAME = "sfr006_context"
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
        # 값은 버리고 이름만 남긴다 — 호출부 실수는 드러내되 내용은 새지 않게
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
# 오류표 (§A) — 공통코드는 00020001/2/3 셋만 조합한다. 새 숫자를 만들지 않는다.
# ─────────────────────────────────────────────────────────────
_AREA = "02"

_ERRORS = {
    "UPSTREAM_TIMEOUT": {
        "error_code": f"ERR-{_AREA}-00020001",
        "error_type": "TPL_CONTEXT_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "템플릿 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"ERR-{_AREA}-00020002",
        "error_type": "TPL_CONTEXT_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "템플릿 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "TEMPLATE_MISSING": {
        "error_code": f"ERR-{_AREA}-00020003",
        "error_type": "TPL_TEMPLATE_NOT_SELECTED",
        "retryable": False,
        "msg": "사용할 템플릿이 지정되지 않았습니다. 템플릿을 먼저 선택해 주세요.",
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
        "error_type": "TPL_CONTEXT_INTERNAL",
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
# 게이트웨이 호출 (§B / §H) — K8s DNS 직접 호출 금지, timeout 필수, 재시도 상한 필수
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
    """`/api/gateway` prefix 를 반드시 지난다.

    운영 배포에 따라 `GENOS_URL` 이 이미 prefix 를 포함해 주입되므로 중복시키지 않는다
    (코드서빙 `llm.py` 의 `_base_url()` 과 같은 규칙 — f-string 으로 직접 조립하면
    prefix 를 빠뜨린다).
    """
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
# 입력 읽기
# ─────────────────────────────────────────────────────────────
_MAX_MESSAGE_CHARS = 4000

# 캔버스 변수(`template_fill_template_id`)가 비었을 때 쓸 템플릿. **PoC 용 고정값**이다.
#
# 왜 필요한가: 이 변수가 안 채워지면 빈 문자열이 서빙으로 가고, `safe_id("")` 가 거부한
# 것을 `_existing_path` 가 삼켜 **404 → `TEMPLATE_MISSING`** 이 된다. 즉 "템플릿을 안
# 골랐다" 가 "템플릿 파일이 없다" 와 **같은 안내문**으로 나와, 파일부터 뒤지게 된다.
#
# 값을 바꾸려면 이 줄만 고치거나 `TEMPLATE_FILL_DEFAULT_TEMPLATE_ID` 를 준다 —
# 환경변수를 먼저 보는 이유는 이름이 틀렸을 때 **스텝을 캔버스에 다시 등록하지 않고**
# 고칠 수 있어야 하기 때문이다. 확장자는 있어도 없어도 된다(서빙이 떼고 다시 붙인다).
_DEFAULT_TEMPLATE_ID = (
    os.environ.get("TEMPLATE_FILL_DEFAULT_TEMPLATE_ID") or "abc"
).strip()


def _normalize_input(data):
    """워크플로우 입력을 dict 로 맞춘다 (문자열로 오는 배선까지 대응)."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {"question": data}
    if not isinstance(data, dict):
        data = {"question": str(data)}
    return data


def _log_context(data: dict) -> dict:
    state = data.get("genos_state") or {}
    return {"trace_id": state.get("trace_id")}


# 전처리기가 첨부를 감싸 주는 태그. FAQ·번역 스텝과 같은 정규식이다 (의도된 사본).
_DOC_TAG_RE = re.compile(r"<doc[^>]*>(.*?)</doc>", re.DOTALL | re.IGNORECASE)


def _uploaded_markdown(genos_uploaded: str) -> str:
    """캔버스 첨부(전처리기 산출물)에서 본문만 꺼낸다.

    태그가 없으면 통째로 본문으로 본다 — 배선에 따라 태그 없이 오는 경우가 있고, 그때
    빈 문자열을 돌려주면 **문서를 올렸는데 아무 일도 안 일어난다.**
    """
    if not genos_uploaded:
        return ""
    matches = _DOC_TAG_RE.findall(genos_uploaded)
    if matches:
        return "\n\n".join(m.strip() for m in matches if m.strip())
    return genos_uploaded.strip()


def _session_id(data: dict) -> str:
    """운영 브리지(`genos_files/bridge.py`)의 폴백 순서를 따른다.

    하나만 보면 UI 배선에 따라 세션이 어긋나 다음 턴에 값이 유실된다.
    """
    state = data.get("genos_state") or {}
    for key in ("socketIOClientId", "sessionId", "session_id"):
        value = data.get(key) or state.get(key)
        if value:
            return str(value)
    return ""


async def run(data: dict) -> dict:
    data = _normalize_input(data)
    log_context = _log_context(data)

    # 앞 스텝이 실패했으면 아무것도 하지 않고 통과시킨다 (§A.4 워크플로우 오류 전달)
    if data.get("error"):
        return data

    question = (data.get("question") or data.get("text") or "").strip()[:_MAX_MESSAGE_CHARS]
    variables = (data.get("overrideConfig") or {}).get("vars") or {}
    session_id = _session_id(data)
    # 변수가 비면 고정 템플릿으로 떨어진다 (PoC).
    #
    # **이러면 서빙의 세션 폴백이 죽는다** — `chat_api._load_turn` 은 `이번 턴 > 세션`
    # 순인데 이제 이번 턴이 절대 비지 않기 때문이다. 템플릿이 하나뿐인 PoC 에서는
    # 오히려 예측 가능하지만, 템플릿을 여러 개 쓰게 되면 **대화 중간에 바꾼 템플릿이
    # 다음 턴에 기본값으로 되돌아간다.** 그때는 이 기본값을 걷어내고 캔버스 변수를
    # 채우는 쪽으로 돌아갈 것.
    template_id = (
        str(variables.get("template_fill_template_id") or "").strip()
        or _DEFAULT_TEMPLATE_ID
    )

    if not session_id:
        # 치명적이지는 않다 — 이번 턴은 되지만 다음 턴에 값이 남지 않는다
        _log_warning(
            "session_id 없음 — 이번 턴 값이 다음 턴에 유지되지 않는다",
            event="session_id_missing",
            **log_context,
        )

    body, failure = await _post_serving(
        "TEMPLATE_FILL_SERVING_ID",
        "/chat/context",
        {"session_id": session_id, "template_id": template_id},
        read_timeout=20.0,
    )

    if failure is not None:
        kind, error_type, upstream_status = failure
        if kind == "config":
            key = "CONFIG_MISSING"
        elif kind == "transport":
            key = "UPSTREAM_TIMEOUT"
        elif upstream_status == 404:
            key = "TEMPLATE_MISSING"
        elif kind == "upstream_final":
            # 404 특례보다 **뒤에** 온다 — `ERR_API_TEMPLATE_NOT_FOUND` 도 00020003 이라
            # 앞에 두면 "템플릿을 찾을 수 없습니다" 안내가 통째로 사라진다.
            key = "UPSTREAM_FINAL"
        else:
            key = "UPSTREAM_EXECUTION"
        error = _error(key)
        _log_warning(
            "템플릿 컨텍스트 조회 실패",
            event="template_context_failed",
            error_code=error["error_code"],
            error_type=error_type,
            upstream_status=upstream_status,
            status="retryable" if error["retryable"] else "final",
            **log_context,
        )
        return {**data, "error": error}

    context = body or {}
    resolved_template_id = str(context.get("template_id") or "").strip()
    if not resolved_template_id:
        error = _error("TEMPLATE_MISSING")
        _log_warning(
            "템플릿 미지정",
            event="template_not_selected",
            error_code=error["error_code"],
            error_type=_ERRORS["TEMPLATE_MISSING"]["error_type"],
            status="final",
            **log_context,
        )
        return {**data, "error": error}

    # ── 업로드 문서 — **여기서는 뽑기만 한다** (2026-09-22 변경) ──────────────
    #
    # 실제 자동 채움(`POST /chat/prefill/stream`)은 스텝 3 이 부른다 — 그래야 조각을
    # 확인하는 동안의 진행 상황을 소켓에 흘릴 수 있다(이 스텝은 중간 스텝이라 흘릴 수
    # 없다, §D.1). 여기서 하는 일은 원문을 뽑아 다음 스텝으로 넘기는 것뿐이다.
    document = _uploaded_markdown(str(variables.get("genosUploaded") or ""))
    if document:
        _log_info(
            "업로드 문서 감지 — 자동 채움은 스텝 3 에서 수행",
            event="template_document_forwarded",
            resource_id=f"{resolved_template_id}.hwpx",
            item_count=len(document),
            **log_context,
        )

    fields_missing = list(context.get("fields_missing") or [])

    # 템플릿 파일명·개수까지만. 발화 내용과 필드 값은 남기지 않는다 (3.8절).
    _log_info(
        "템플릿 컨텍스트 확정",
        event="template_context_loaded",
        resource_id=f"{resolved_template_id}.hwpx",
        item_count=len(context.get("field_names") or []),
        status=(
            f"missing={len(fields_missing)}"
            f" blocks={len(context.get('blocks') or [])}"
            f" cached={int(bool(context.get('from_cache')))}"
        ),
        **log_context,
    )

    return {
        **data,
        "question": question,
        "session_id": session_id,
        "template_id": resolved_template_id,
        # ── 다음 스텝이 쓰는 것 ──
        "field_names": list(context.get("field_names") or []),
        "block_styles": list(context.get("block_styles") or []),
        "field_values": dict(context.get("field_values") or {}),
        "blocks": list(context.get("blocks") or []),
        # ── 업로드 문서 원문 ── 스텝 3 이 `/chat/prefill/stream` 을 부를 때 쓴다.
        # 스텝 2(발화 추출)는 이 키를 읽지 않고 `{**data}` 로 그대로 통과시킨다.
        "document": document,
        # ── 캔버스 분기용 ── "다 채웠으면 다운로드 안내로" 를 여기 뒤에 건다.
        # **문서가 채울 항목은 반영돼 있지 않다** (위 머리말) — 스텝 3 이 프리필을
        # 끝낸 뒤에야 정확해진다.
        "fields_missing": fields_missing,
        "ready_for_download": not fields_missing,
        # ── 화면용 ── 첫 턴에 "이 템플릿은 이렇게 생겼다" 를 보여준다
        "template_markdown": context.get("template_markdown") or "",
        "template_markdown_truncated": bool(context.get("template_markdown_truncated")),
        "error": None,
    }
