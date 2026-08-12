"""SFR-006 스텝 2/3 — 발화에서 값·삭제·본문 블록 추출 (area 02).

캔버스에서 하는 일: 사용자 발화를 코드서빙에 넘겨 **LLM 추출 + 코드 판정**을 받는다.
결과는 `fields_updated`/`fields_rejected` 로 캔버스에 드러난다.

## 판정 책임 분리는 그대로다

- **LLM**: 발화 → `{항목명: 값}` + 지울 항목 + 본문 블록 추출까지만.
- **코드(코드서빙)**: 화이트리스트 검증, 값 보존 확인, 서식 이름 검증. 전부 결정적이다.

**LLM 호출과 프롬프트 렌더는 코드서빙에 있다.** 프롬프트 jinja 파일(`onprem/prompt/`)과
`jinja2` 가 그쪽에만 있기 때문이고(§D.3), 이 스텝은 그 결과를 받기만 한다.
지금 구현도 LLM 응답을 **전부 받은 뒤** 청크로 잘라 emit 했으므로 UI 동작은 달라지지 않는다.

## 발화가 비어 있으면 LLM 을 부르지 않는다

첫 진입(템플릿만 고르고 아직 말하지 않은 턴)이 그렇다. 그때는 추출 결과를 빈 값으로 두고
다음 스텝이 현재 상태만 보여준다 — 빈 발화로 LLM 을 부르면 항목을 지어낸다.
"""

import asyncio
import json
import logging
import os

import httpx

# ─────────────────────────────────────────────────────────────
# 로깅 (§C / 가이드 3.8)
# ─────────────────────────────────────────────────────────────
_ALLOWED_LOG_FIELDS = frozenset({
    "event", "trace_id", "request_id", "resource_id", "status",
    "duration_ms", "item_count", "upstream_status", "error_code", "error_type",
})

_LOG = logging.getLogger("sfr006_extract")


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
        "error_type": "TPL_EXTRACT_UPSTREAM_TIMEOUT",
        "retryable": True,
        "msg": "문서 작성 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    },
    "UPSTREAM_EXECUTION": {
        "error_code": f"{_AREA}-00020002",
        "error_type": "TPL_EXTRACT_UPSTREAM_EXECUTION_FAILED",
        "retryable": True,
        "msg": "말씀하신 내용을 항목으로 정리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "CONFIG_MISSING": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TPL_CONFIG_MISSING",
        "retryable": False,
        "msg": "서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
    },
    "INTERNAL": {
        "error_code": f"{_AREA}-00020003",
        "error_type": "TPL_EXTRACT_INTERNAL",
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
_CONNECT_TIMEOUT = 3.0
_ATTEMPTS = 2

# LLM 이 뒤에 있으므로 컨텍스트 조회보다 길게 잡는다. 전체 처리시간 안에서
# 개별 호출 제한을 잡는 규칙(§B)에 따라 60s 를 넘기지 않는다.
_EXTRACT_READ_TIMEOUT = 60.0


def _gateway_base() -> str:
    base = (os.environ.get("GENOS_URL") or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("GENOS_URL is not configured")
    return base if base.endswith("/api/gateway") else f"{base}/api/gateway"


async def _post_serving(path: str, payload: dict, *, read_timeout: float):
    serving_id = (os.environ.get("TEMPLATE_FILL_SERVING_ID") or "").strip()
    if not serving_id:
        return None, ("config", "TEMPLATE_FILL_SERVING_ID_MISSING", None)
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


_EMPTY_EXTRACTION = {
    "fields_updated": {},
    "fields_cleared": [],
    "fields_rejected": [],
    "blocks_added": [],
    "block_clears": [],
}


def _log_context(data: dict) -> dict:
    state = data.get("genos_state") or {}
    return {"trace_id": state.get("trace_id")}


async def run(data: dict) -> dict:
    if not isinstance(data, dict):
        data = {"question": str(data)}
    log_context = _log_context(data)

    # 앞 스텝(컨텍스트 확정)이 실패했으면 그대로 통과 (§A.4)
    if data.get("error"):
        return data

    question = (data.get("question") or "").strip()
    template_id = str(data.get("template_id") or "").strip()
    session_id = str(data.get("session_id") or "").strip()

    # 발화가 없는 턴 — LLM 을 부르지 않는다. 빈 발화로 부르면 항목을 지어낸다.
    if not question:
        _log_info(
            "발화 없음 — 추출을 건너뛴다",
            event="extract_skipped_no_question",
            resource_id=f"{template_id}.hwpx",
            status="skipped",
            **log_context,
        )
        return {**data, **_EMPTY_EXTRACTION, "error": None}

    body, failure = await _post_serving(
        "/chat/extract",
        {
            "session_id": session_id,
            "template_id": template_id,
            "question": question,
        },
        read_timeout=_EXTRACT_READ_TIMEOUT,
    )

    if failure is not None:
        kind, error_type, upstream_status = failure
        if kind == "config":
            key = "CONFIG_MISSING"
        elif kind == "transport":
            key = "UPSTREAM_TIMEOUT"
        else:
            key = "UPSTREAM_EXECUTION"
        error = _error(key)
        _log_warning(
            "발화 추출 실패",
            event="extract_failed",
            error_code=error["error_code"],
            error_type=error_type,
            upstream_status=upstream_status,
            status="retryable" if error["retryable"] else "final",
            **log_context,
        )
        return {**data, "error": error}

    result = body or {}
    updated = dict(result.get("fields_updated") or {})
    rejected = list(result.get("fields_rejected") or [])
    cleared = list(result.get("fields_cleared") or [])
    added_blocks = list(result.get("blocks_added") or [])

    if rejected:
        # 기각 건수는 006 환각률 지표의 원천이다 — 침묵 처리하지 않는다.
        # 기각된 **이름**은 남기지 않는다(LLM 출력이다). 개수만 (3.8절).
        _log_warning(
            "템플릿에 없는 항목명을 기각",
            event="extraction_keys_rejected",
            item_count=len(rejected),
            **log_context,
        )

    _log_info(
        "발화 추출 완료",
        event="extract_done",
        resource_id=f"{template_id}.hwpx",
        item_count=len(updated),
        status=f"cleared={len(cleared)} blocks={len(added_blocks)} rejected={len(rejected)}",
        **log_context,
    )

    return {
        **data,
        "fields_updated": updated,
        "fields_cleared": cleared,
        "fields_rejected": rejected,
        "blocks_added": added_blocks,
        "block_clears": list(result.get("block_clears") or []),
        "error": None,
    }
