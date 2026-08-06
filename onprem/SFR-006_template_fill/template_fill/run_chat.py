"""SFR-006 템플릿 채우기 — GenOS 워크플로우 Python 단계 (area 02).

멀티턴 대화로 템플릿의 빈 자리를 채워 나간다. 사용자가 말한 내용에서 항목 값을 뽑아
누적하고, 매 턴 "무엇이 채워졌고 무엇이 부족한지" 를 보여준다.
**파일 생성은 여기서 하지 않는다** — 다운로드 버튼이 코드 서빙(`main.py`)의
`POST /generate` 를 부르고, 두 pod 는 **Redis 세션**으로 연결된다.

## 한 턴의 흐름

```
발화
 └→ 1. 세션 로드 + 템플릿 확정        chat_state.load_context / restore_state
    2. LLM 추출 (값·삭제·본문 블록)    prompts + llm
    3. 코드가 판정 (화이트리스트)       field_judge.parse_updates
    4. 글다듬이(톤) — 신규 내용만       chat_state.apply_tone_stage
    5. 상태 병합 + 세션 저장            chat_state.merge_values / merge_blocks
    6. 미리보기 + 답변 조립             chat_state.render_preview / chat_reply
    7. token 스트리밍 → result 1회      (GenOS 계약)
```

## 판정 책임 분리 (루트 CLAUDE.md §5 — LLM 응답을 믿지 않는다)

- **LLM**: 발화 → `{항목명: 값}` + 지울 항목(`clears`) + 본문 블록(`blocks`) 추출까지만.
- **코드**: 화이트리스트 검증(`field_judge`), 채워짐·부족 판정, `ready` 결정,
  숫자·날짜 보존 확인(`value_guard`), 서식 이름 검증. 전부 결정적이다.

## GenOS 계약 (가이드 5.1·5.2·3.9.6)

- 함수명 `run` 고정, 인자 `data: dict` 하나
- async generator 로만 만든다 (단순 return 과 혼용 금지)
- 마지막에 `event: result` 를 **반드시 1회** yield — 오류일 때도 마찬가지다
- 오류는 예외가 아니라 `data["error"] = {error_code, msg, retryable}`
- 예외 원문·문서 원문·LLM 응답 전문은 로그·응답에 남기지 않는다 (3.8절)
"""

import asyncio
import json

from .chat_reply import compose_status_reply, stream_chunks
from .chat_state import (
    apply_tone_stage,
    load_context,
    merge_blocks,
    merge_values,
    render_preview,
    restore_state,
)
from .config import Config
from .error_codes import (
    ApiError,
    ERR_CHAT_INTERNAL,
    ERR_CHAT_UPSTREAM_EXECUTION,
    ERR_CHAT_UPSTREAM_TIMEOUT,
)
from .field_judge import parse_updates
from .hwpx_fields import missing_field_names
from .llm import llm_call_async
from .logging_utils import log_info, log_warning
from .prompts import EXTRACT_SYSTEM_PROMPT, build_extract_user_prompt
from .session_store import SessionStoreError, load_session, save_session
from .tone_presets import resolve_tone


def _log_context(data) -> dict:
    """로그에 붙일 추적 필드 (3.8절 허용 필드만).

    `genos_state.trace_id` 는 분산추적 키다 — 워크플로우 단계와 코드 서빙 로그를 한
    요청으로 묶으려면 매 로그에 실어야 한다 (CLAUDE.md §4.2). `resource_id` 는 호출부마다
    의미가 달라(워크플로우 id / 템플릿 파일명) 여기서 넣지 않는다.
    """
    state = (data.get("genos_state") or {}) if isinstance(data, dict) else {}
    return {"trace_id": state.get("trace_id")}


def _build_error(error_code) -> dict:
    return {
        "error_code": error_code.code,
        "msg": error_code.user_msg,
        "retryable": error_code.retryable,
    }


def _normalize_input(data):
    """워크플로우 입력을 dict 로 맞춘다 (문자열로 오는 경우까지 — 018 과 동일 패턴)."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {"question": data}
    return data


def _read_request(data: dict) -> tuple:
    """발화·워크플로우 변수·세션 id 를 꺼낸다."""
    question = (data.get("question") or data.get("text") or "").strip()
    variables = (data.get("overrideConfig") or {}).get("vars") or {}
    state = data.get("genos_state") or {}
    session_id = str(state.get("session_id") or data.get("sessionId") or "").strip()
    return question[: Config.MAX_MESSAGE_CHARS], variables, session_id


async def _extract_intent(question: str, context, state, log_context: dict):
    """발화에서 값·삭제·본문 블록 의도를 뽑아 **코드로 검증한** 결과를 돌려준다.

    Returns:
        `ParsedIntent`.

    Raises:
        ApiError: LLM 호출 실패 (통신 실패와 실행 실패를 다른 코드로 구분한다).
    """
    user_prompt = build_extract_user_prompt(
        context.specs, state.values, question, context.block_styles, state.blocks
    )
    try:
        result = await llm_call_async(EXTRACT_SYSTEM_PROMPT, user_prompt)
    except Exception as exc:  # noqa: BLE001 - 클라이언트 초기화 실패 등
        log_warning(
            "LLM 호출 준비 실패",
            event="llm_setup_failed",
            error_type=type(exc).__name__,
            **log_context,
        )
        raise ApiError(ERR_CHAT_INTERNAL) from exc

    if not result.ok:
        raise ApiError(
            ERR_CHAT_UPSTREAM_TIMEOUT if result.is_transport_error else ERR_CHAT_UPSTREAM_EXECUTION
        )

    intent = parse_updates(
        result.content,
        context.allowed_names,
        allowed_styles=context.block_styles,
        block_count=len(state.blocks),
    )
    if intent.conflicts:
        # 모순 해소는 field_judge 가 한다 (수정 채택). 조용히 넘기지 않고 건수를 남긴다.
        log_warning(
            "같은 항목에 수정·삭제 의도가 함께 와서 수정을 채택",
            event="edit_intent_conflict",
            item_count=len(intent.conflicts),
            **log_context,
        )
    if intent.rejected:
        # 기각 건수는 006 환각률 지표의 원천이다 — 침묵 처리하지 않는다
        log_warning(
            "LLM 응답에서 템플릿에 없는 필드명을 기각",
            event="extraction_keys_rejected",
            item_count=len(intent.rejected),
            **log_context,
        )
    return intent


async def run(data: dict):
    # 1) socket.io 세팅 (실시간 토큰 스트리밍용, 모듈이 없으면 조용히 스킵)
    try:
        from main_socketio import sio_server
    except ImportError:
        sio_server = None

    data = _normalize_input(data)
    sid = data.get("socketIOClientId") if isinstance(data, dict) else None
    log_context = _log_context(data)

    async def emit_event(event_name: str, payload):
        if sio_server and sid:
            await sio_server.emit(event_name, payload, room=sid)
            # WebSocket write buffer flush. 양보하지 않고 emit 을 몰아치면 소켓 쓰기가
            # 버퍼에 쌓여 UI 가 마지막에 한꺼번에 받는다 (가이드 5.2·D.4 '스트리밍이
            # 일괄 반환되는 원인'). 실제 운영 bridge 도 매 emit 뒤에 이걸 넣는다.
            await asyncio.sleep(0)
        return {"event": event_name, "data": payload}

    async def fail(error_code):
        """오류를 사용자 메시지로 스트리밍하고 result 로 마무리하는 공통 경로."""
        error = _build_error(error_code)
        log_warning(
            "템플릿 채우기 오류 응답",
            event="template_fill_error",
            error_code=error["error_code"],
            error_type=error_code.error_type,
            status="retryable" if error_code.retryable else "final",
            **log_context,
        )
        for chunk in stream_chunks(error["msg"]):
            yield await emit_event("token", chunk)
        yield {"event": "result", "data": {**data, "text": error["msg"], "error": error}}

    question, variables, session_id = _read_request(data)

    # 2) 세션 로드 + 템플릿 확정 (이번 턴 지정 > 세션에 저장된 것)
    try:
        session = await load_session(session_id) if session_id else {}
    except ValueError:
        session = {}
    template_id = str(
        variables.get("template_fill_template_id") or session.get("template_id") or ""
    ).strip()

    try:
        context = await load_context(template_id)
    except ApiError as exc:
        async for event in fail(exc.code):
            yield event
        return

    state = restore_state(session, context, log_context)

    # 템플릿 파일명·항목 개수까지만. 발화 내용과 필드 값은 남기지 않는다 (3.8절).
    log_info(
        "템플릿 항목 스캔 완료",
        event="template_scanned",
        resource_id=f"{context.template_id}.hwpx",
        item_count=len(context.specs),
        status=(
            f"collected={len(state.values)}"
            f" labels={sum(1 for s in context.specs if s.source == 'label')}"
            f" fields={sum(1 for s in context.specs if s.source == 'field')}"
            f" blocks={len(state.blocks)}"
            f" cached={int(context.index.from_cache)}"
        ),
        **log_context,
    )

    # 3) 발화에서 값·수정·삭제·본문 추가 의도 추출 (LLM) → 코드가 검증
    accepted: dict = {}
    rejected: list = []
    clears: list = []
    added_blocks: list = []
    clear_indexes: list = []
    if question:
        try:
            intent = await _extract_intent(question, context, state, log_context)
        except ApiError as exc:
            async for event in fail(exc.code):
                yield event
            return
        accepted, clears, rejected = intent.updates, list(intent.clears), intent.rejected
        added_blocks, clear_indexes = list(intent.blocks), list(intent.block_clears)

    # 4) 글다듬이(톤) — 이번 턴 신규 내용에만. 실패해도 진행한다.
    tone_key = resolve_tone(variables.get("template_fill_tone"))
    tone_result = block_tone_result = None
    if tone_key:
        accepted, added_blocks, tone_result, block_tone_result = await apply_tone_stage(
            state,
            accepted,
            added_blocks,
            tone_key,
            variables.get("template_fill_tone_fields"),
            log_context,
        )

    # 5) 상태 병합 + 저장.
    #    이전 값을 남겨 둔다 — 답변에 `이전 → 새 값` 을 보여주려면 필요하고, 대화로 값을
    #    고치는 경로에서 의도치 않은 덮어쓰기를 사용자가 알아채는 유일한 수단이다.
    previous = dict(state.values)
    state.raw_values.update(accepted)
    cleared = merge_values(state, accepted, clears)
    dropped_blocks, overflow = merge_blocks(state, added_blocks, clear_indexes, log_context)
    if overflow:
        rejected = rejected + [f"<blocks: 개수 상한({Config.MAX_BLOCKS}건) 초과>"]

    if session_id:
        try:
            await save_session(
                session_id, context.template_id, state.values, state.raw_values, state.blocks
            )
        except SessionStoreError as exc:
            # 저장 실패 = 다음 턴에 값이 유실된다 — 침묵 처리하지 않고 실패로 종료
            log_warning(
                "세션 저장 실패 — 이번 턴 값이 다음 턴에 유지되지 않는다",
                event="session_save_failed",
                error_type=type(exc).__name__,
                **log_context,
            )
            async for event in fail(ERR_CHAT_INTERNAL):
                yield event
            return
    else:
        log_warning(
            "session_id 없음 — 이번 턴 값이 다음 턴에 유지되지 않는다",
            event="session_id_missing",
            **log_context,
        )

    # 6) 판정(코드가 결정적으로) + 미리보기 + 답변 조립
    missing_names = missing_field_names(context.specs, state.values)
    document_markdown, document_truncated = await render_preview(context, state, log_context)
    display_text = compose_status_reply(
        context.specs,
        state.values,
        accepted,
        rejected,
        tone_result=tone_result,
        block_tone_result=block_tone_result,
        previous=previous,
        cleared=cleared,
        blocks=state.blocks,
        added_blocks=added_blocks,
        dropped_blocks=dropped_blocks,
    )

    # 7) 토큰 스트리밍 → result 1회 (GenOS 계약)
    for chunk in stream_chunks(display_text):
        yield await emit_event("token", chunk)

    yield {
        "event": "result",
        "data": {
            **data,
            "text": display_text,
            "template_id": context.template_id,
            "session_id": session_id,
            # ── 항목 값 ──
            "field_values": state.values,
            "field_values_raw": state.raw_values,
            "fields_filled": [s.name for s in context.specs if s.name not in missing_names],
            "fields_missing": missing_names,
            "ready_for_download": not missing_names,
            # 이번 턴의 편집 결과 — UI 가 "무엇이 바뀌었나" 를 강조 표시할 근거
            "fields_updated": sorted(accepted),
            "fields_cleared": sorted(cleared),
            "fields_rejected": rejected,
            # ── 본문 블록 (템플릿 항목 밖에 이어 쓴 내용) ──
            "blocks": [
                {"text": b.text, "style_ref": b.style_ref, "raw_text": b.raw_text}
                for b in state.blocks
            ],
            "blocks_added": len(added_blocks),
            "blocks_removed": len(dropped_blocks),
            "block_styles": context.block_styles,
            # ── 미리보기 ──
            # 템플릿 원본 모양은 색인에 이미 있어 추가 파싱이 없다. UI 가 첫 턴에
            # "이 템플릿은 이렇게 생겼다" 를 보여줄 때 쓴다.
            "template_markdown": context.index.markdown,
            "template_markdown_truncated": context.index.truncated,
            # 지금 값으로 채운 문서 (매 턴 갱신). UI 문서 창이 이걸 그린다.
            "document_markdown": document_markdown,
            "document_markdown_truncated": document_truncated,
            # ── 글다듬이(톤) 결과 — 무엇이 바뀌고 무엇이 기각됐는지 ──
            "tone": tone_key,
            "tone_applied_fields": tone_result.applied if tone_result else [],
            "tone_rejected_fields": tone_result.rejected if tone_result else [],
            "tone_applied_blocks": block_tone_result.applied if block_tone_result else [],
            "tone_rejected_blocks": block_tone_result.rejected if block_tone_result else [],
            "error": None,
        },
    }
