"""FAQ 생성 워크플로우 Python 단계 (area 02).

역할: 사용자가 업로드한 문서(전처리기가 마크다운으로 바꾼 `genosUploaded`)에서
FAQ 를 만들어 채팅에 스트리밍하고, 다운로드용으로 세션에 저장한다.

초안(`archive/FAQ.py`) 대비 고친 것
- `print()` 로 GENOS_URL 을 찍던 줄 제거 (§C 이중 위반: print 금지 + 접속 정보 노출).
- 정의되지 않은 `model` 을 검사해 `NameError` 로 죽던 설정 검증 → `llm.py` 로 이관.
- **글자 하나씩 emit** → 청크(32자) 단위 + emit 뒤 `await asyncio.sleep(0)`
  (가이드 5.2·D.4 "스트리밍이 일괄 반환되는 원인").
- `yield {"event": "result", "data": {"text": ...}}` → `{**data, ...}`.
  `data` 를 통째로 넘기지 않으면 다음 스텝이 `genos_state`(trace_id 등)를 잃는다.
- FAQ 5개 고정 → **사용자 선택 개수**(관리자 상한 안에서, 요구사항 §4).
- **근거 검증 추가** — LLM 이 준 근거가 문서에 실제로 있는지 대조하고 기각 건수를 노출.
- 오류를 `error` 이벤트로만 끝내던 것 → 사용자 메시지 스트리밍 + `result` 1회 yield
  (5.2절: 마지막에 `event: result` 를 반드시 1회 yield).

가이드 반영
- 함수명 `run` 고정, 인자 `data` 1개 (5.1절) — GenOS 고정 계약이라 바꿀 수 없다.
- 토큰 스트리밍은 async generator 패턴만 사용, 단순 return 과 혼용 금지 (5.2절).
- 오류는 예외 대신 `data["error"] = {error_code, msg, retryable}` (3.9.6절).
- 예외 원문·문서 원문·LLM 응답 전문은 로그/응답에 노출하지 않음 (3.8절).
"""

import asyncio
import json
import re

from .config import Config
from .error_codes import (
    ERR_CHAT_COUNT_ZERO,
    ERR_CHAT_DOC_INVALID,
    ERR_CHAT_INTERNAL,
    ERR_CHAT_NO_GROUNDED_ITEMS,
    ERR_CHAT_NO_INPUT,
    ERR_CHAT_UPSTREAM_EXECUTION,
    ERR_CHAT_UPSTREAM_TIMEOUT,
)
from .formatting import build_notice, to_export_rows, to_markdown
from .generator import (
    FAILURE_NO_GROUNDED,
    FAILURE_PROMPT,
    FAILURE_TRANSPORT,
    generate_faqs,
    resolve_count,
)
from .hwpx_text import HwpxParseError, to_markdown as hwpx_to_markdown
from .logging_utils import log_info, log_warning
from .session_store import SessionStoreError, save_faqs

_DOC_TAG_RE = re.compile(r"<doc[^>]*>(.*?)</doc>", re.DOTALL)

# 토큰 스트리밍 단위. 글자 하나씩 보내면 FAQ 한 장이 emit 수천 회가 되고,
# 그만큼 이벤트 루프 양보가 늘어 오히려 표시가 늦어진다 (onprem/README 스트리밍 규약).
_STREAM_CHUNK_CHARS = 32


def _log_context(data) -> dict:
    """로그 추적 필드 (3.8절 허용 필드만). trace_id 로 단계 간 로그를 묶는다."""
    state = (data.get("genos_state") or {}) if isinstance(data, dict) else {}
    return {"trace_id": state.get("trace_id")}


def _session_id(data: dict) -> str:
    """다운로드가 찾아올 키.

    운영 브리지(`genos_files/bridge.py`)의 폴백 순서를 따른다 —
    `socketIOClientId → sessionId → session_id`. 하나만 보면 UI 배선에 따라
    세션이 어긋나 다운로드가 404 를 낸다.
    """
    state = data.get("genos_state") or {}
    for key in ("socketIOClientId", "sessionId", "session_id"):
        value = data.get(key) or state.get(key)
        if value:
            return str(value)
    return ""


def _extract_uploaded_markdown(genos_uploaded: str) -> str:
    """전처리기 산출물 `genosUploaded` 의 `<doc ...>마크다운</doc>` 블록에서 본문만 추출."""
    if not genos_uploaded:
        return ""
    matches = _DOC_TAG_RE.findall(genos_uploaded)
    if matches:
        return "\n\n".join(m.strip() for m in matches if m.strip())
    return genos_uploaded.strip()


def _read_hwpx_source(path: str) -> str:
    """공유 볼륨의 hwpx 를 직접 파싱한다 (요구사항 §1 — hwpx 는 직접 파싱).

    전처리기를 태우면 표 안 수치가 깨지므로, hwpx 원본에 접근할 수 있는 배포에서는
    이 경로가 우선이다. 경로 변수가 없으면 `genosUploaded` 로 떨어진다.
    """
    with open(path, "rb") as handle:
        return hwpx_to_markdown(handle.read(), Config.MAX_CONTEXT_CHARS).markdown


def _build_error(error_code) -> dict:
    return {
        "error_code": error_code.code,
        "msg": error_code.user_msg,
        "retryable": error_code.retryable,
    }


def _stream_chunks(text: str):
    """긴 답변을 스트리밍용 청크로 자른다 (UI 는 받는 대로 이어붙인다)."""
    for start in range(0, len(text), _STREAM_CHUNK_CHARS):
        yield text[start: start + _STREAM_CHUNK_CHARS]


_FAILURE_TO_ERROR = {
    FAILURE_TRANSPORT: ERR_CHAT_UPSTREAM_TIMEOUT,
    FAILURE_NO_GROUNDED: ERR_CHAT_NO_GROUNDED_ITEMS,
    FAILURE_PROMPT: ERR_CHAT_INTERNAL,
}


async def run(data: dict):
    # 1) socket.io 세팅 (실시간 토큰 스트리밍용, 모듈이 없으면 조용히 스킵)
    try:
        from main_socketio import sio_server
    except ImportError:
        sio_server = None

    # 2) 입력 정규화 (문자열로 넘어오는 경우까지 대응)
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {"question": data}
    sid = data.get("socketIOClientId") if isinstance(data, dict) else None

    async def emit_event(event_name: str, payload):
        if sio_server and sid:
            await sio_server.emit(event_name, payload, room=sid)
            # WebSocket write buffer flush. 양보하지 않고 emit 을 몰아치면 소켓 쓰기가
            # 버퍼에 쌓여 UI 가 마지막에 한꺼번에 받는다 (가이드 5.2·D.4).
            await asyncio.sleep(0)
        return {"event": event_name, "data": payload}

    async def fail(error_code):
        """오류를 사용자 메시지로 스트리밍하고 result 로 마무리하는 공통 경로."""
        error = _build_error(error_code)
        log_warning(
            "FAQ 오류 응답",
            event="faq_error",
            error_code=error["error_code"],
            error_type=error_code.error_type,
            status="retryable" if error_code.retryable else "final",
            **_log_context(data),
        )
        for chunk in _stream_chunks(error["msg"]):
            yield await emit_event("token", chunk)
        yield {
            "event": "result",
            "data": {**data, "text": error["msg"], "faq_items": [], "error": error},
        }

    config = data.get("overrideConfig") or {}
    variables = config.get("vars") or {}

    # 3) 원본 확보: hwpx 직접 파싱 우선, 없으면 전처리기 산출물
    hwpx_path = str(variables.get("faq_hwpx_path") or "").strip()
    source_text = ""
    if hwpx_path:
        try:
            source_text = await asyncio.to_thread(_read_hwpx_source, hwpx_path)
        except (HwpxParseError, OSError) as exc:
            log_warning(
                "hwpx 직접 파싱 실패 — 전처리기 산출물로 진행",
                event="faq_hwpx_parse_failed",
                error_type=type(exc).__name__,
                **_log_context(data),
            )
    if not source_text:
        source_text = _extract_uploaded_markdown(variables.get("genosUploaded") or "")

    if not source_text.strip():
        # 업로드 문서가 없으면 빈 답변으로 감추지 않는다
        async for event in fail(ERR_CHAT_NO_INPUT if not hwpx_path else ERR_CHAT_DOC_INVALID):
            yield event
        return

    # 4) 개수 결정 — 사용자 선택값, 관리자 상한 안으로 깎인다 (요구사항 §4)
    count, maximum, _clamped = resolve_count(
        variables.get("faq_count"), variables.get("faq_max_count")
    )
    if count <= 0:
        async for event in fail(ERR_CHAT_COUNT_ZERO):
            yield event
        return

    # 문서 원문은 남기지 않는다 — 길이와 개수만 (3.8절)
    log_info(
        "FAQ 생성 요청 접수",
        event="faq_started",
        item_count=count,
        resource_id="hwpx" if hwpx_path else "preprocessor",
        status=f"max={maximum},chars={len(source_text)}",
        **_log_context(data),
    )

    # 5) 생성 (스키마 검증·근거 대조·중복 제거는 generator 안에서)
    try:
        result = await generate_faqs(source_text, count, variables.get("faq_max_count"))
    except Exception as exc:  # noqa: BLE001 - 예상 밖 오류까지 안전하게 흡수
        log_warning(
            "FAQ 내부 처리 실패",
            event="faq_internal_error",
            error_type=type(exc).__name__,
            **_log_context(data),
        )
        async for event in fail(ERR_CHAT_INTERNAL):
            yield event
        return

    if not result.ok:
        async for event in fail(
            _FAILURE_TO_ERROR.get(result.failure, ERR_CHAT_UPSTREAM_EXECUTION)
        ):
            yield event
        return

    # 6) 다운로드용 저장 — 화면에서 본 것과 같은 FAQ 를 내려주기 위해서다.
    #    저장 실패는 생성 결과 전달을 막지 않는다(채팅으로는 이미 볼 수 있다).
    #    대신 다운로드가 안 될 수 있다는 사실을 안내에 덧붙인다.
    export_rows = to_export_rows(result.items)
    session_id = _session_id(data)
    download_ready = False
    if session_id:
        try:
            await save_faqs(session_id, export_rows, title=str(variables.get("faq_title") or ""))
            download_ready = True
        except SessionStoreError as exc:
            log_warning(
                "FAQ 세션 저장 실패 — 다운로드 불가 상태로 안내",
                event="faq_session_save_failed",
                error_type=type(exc).__name__,
                **_log_context(data),
            )

    # 7) 채팅 노출용 최종 답변 조립
    notice = build_notice(result)
    if not download_ready:
        notice += "※ 이번 결과는 파일로 내려받을 수 없습니다. 화면 내용을 복사해 사용해 주세요.\n\n"
    display_text = to_markdown(result.items, notice=notice)

    # 8) 토큰 스트리밍 (청크 단위 — 글자 단위 emit 금지)
    for chunk in _stream_chunks(display_text):
        yield await emit_event("token", chunk)

    # 9) 최종 결과 확정. `{**data, ...}` 로 넘겨 genos_state 를 잃지 않는다.
    yield {
        "event": "result",
        "data": {
            **data,
            "text": display_text,            # 채팅에 노출되는 전체 답변
            "faq_items": result.as_payload()["items"],  # 후속 스텝·다운로드 버튼용
            "faq_stats": result.as_payload(),
            "faq_session_id": session_id,
            "faq_download_ready": download_ready,
            "error": None,
        },
    }
