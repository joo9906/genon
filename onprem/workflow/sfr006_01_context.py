"""SFR-006 스텝 1/3 — 템플릿 컨텍스트 확정 (area 02).

캔버스에서 하는 일: 세션과 워크플로우 변수로 **어느 템플릿인지** 확정하고, 그 템플릿의
항목 목록·지금까지 채워진 값을 가져와 다음 스텝과 캔버스 분기에 넘긴다.

## 왜 이 스텝이 따로 있나

여기서 나오는 `fields_missing` / `ready_for_download` 가 **캔버스 분기의 근거**다.
"다 채워졌으면 다운로드 안내 노드로, 아니면 추출 스텝으로" 를 이 스텝 뒤에 걸 수 있다.
한 덩어리였을 때는 그 판정이 코드 안에 묻혀 있어 캔버스에서 보이지 않았다.

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

import httpx

# ─────────────────────────────────────────────────────────────
# 로깅 (§C / 가이드 3.8) — 허용 필드만, 값은 반드시 extra 로.
# 메시지에 f-string 으로 값을 끼워 넣으면 화이트리스트가 무력해진다.
# ─────────────────────────────────────────────────────────────
_ALLOWED_LOG_FIELDS = frozenset({
    "event", "trace_id", "request_id", "resource_id", "status",
    "duration_ms", "item_count", "upstream_status", "error_code", "error_type",
})

_LOG = logging.getLogger("sfr006_context")


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


def _log_info(message: str, *, event: str, **fields) -> None:
    _emit_log(logging.INFO, message, event=event, **fields)


def _log_warning(message: str, *, event: str, **fields) -> None:
    _emit_log(logging.WARNING, message, event=event, **fields)


# ─────────────────────────────────────────────────────────────
# 오류표 (§A) — 공통코드는 00020001/2/3 셋만 조합한다. 새 숫자를 만들지 않는다.
# ─────────────────────────────────────────────────────────────
_AREA = "02"

_ERRORS = {
    "UPSTREAM_TIMEOUT": {
        "error_code": f"{_AREA}-00020001",
        "error_type": "TPL_CONTEXT_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "템플릿 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"{_AREA}-00020002",
        "error_type": "TPL_CONTEXT_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "템플릿 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "TEMPLATE_MISSING": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TPL_TEMPLATE_NOT_SELECTED",
        "retryable": False,
        "msg": "사용할 템플릿이 지정되지 않았습니다. 템플릿을 먼저 선택해 주세요.",
    },
    "CONFIG_MISSING": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TPL_CONFIG_MISSING",
        "retryable": False,
        "msg": "서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
    },
    "UPSTREAM_FINAL": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TPL_UPSTREAM_FINAL",
        "retryable": False,
        "msg": "요청을 처리하지 못했습니다. 관리자에게 문의해 주세요.",
    },
    "INTERNAL": {
        "error_code": f"{_AREA}-00020003",
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
    template_id = str(variables.get("template_fill_template_id") or "").strip()

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
        # ── 캔버스 분기용 ── "다 채웠으면 다운로드 안내로" 를 여기 뒤에 건다
        "fields_missing": fields_missing,
        "ready_for_download": not fields_missing,
        # ── 화면용 ── 첫 턴에 "이 템플릿은 이렇게 생겼다" 를 보여준다
        "template_markdown": context.get("template_markdown") or "",
        "template_markdown_truncated": bool(context.get("template_markdown_truncated")),
        "error": None,
    }
