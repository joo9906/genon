"""SFR-006 템플릿 채우기 — GenOS 워크플로우 Python 단계 (area 02).

역할: 사용자가 선택한 hwpx 템플릿의 채울 항목(본문 `제목: {고딕, 16pt}` 라벨 항목,
또는 누름틀 필드)을 기준으로,
멀티턴 대화에서 사용자가 제공한 값을 LLM 으로 추출·누적하고
"무엇이 채워졌고 무엇이 부족한지"를 매 턴 안내한다.

파일 생성은 이 단계가 하지 않는다 — 사용자가 다운로드 버튼을 누르면
코드 서빙(main.py)의 POST /generate 가 세션에 누적된 값으로 초안을 만든다.
(대화 단계와 파일 생성 단계는 TEMPLATE_FILL_SESSION_DIR 공유 볼륨으로 연결)

GenOS 엔지니어 개발가이드 v1.02 반영 (부록 C.2 체크리스트)
- 함수명 run 고정, 인자 data: dict 1개 (5.1절)
- 토큰 스트리밍은 async generator, 마지막에 event: result 1회 필수 (5.2절)
- 오류는 예외 대신 data["error"] = {error_code, msg, retryable} (3.9.6절)
- 예외 원문·문서 원문·LLM 응답 전문은 로그/응답에 노출하지 않음 (3.8절)

판정 책임 분리 (CLAUDE.md §5 — LLM 응답을 믿지 않는다):
- LLM: 사용자 발화 → {필드명: 값} 후보 추출까지만
- 코드: 화이트리스트 검증(field_judge) + 채워짐/부족 판정 + ready 결정

톤(문체) 적용 — 워크플로우 변수 `template_fill_tone` 이 있을 때만 동작(opt-in):
- 추출과 분리된 2단계다. 추출은 사용자가 말한 값을 그대로 뽑고, 그 다음
  **서술형 필드만** 골라 문체를 바꾼다 (tone_apply). 이름·날짜 같은 짧은 값은 제외.
- 변환 결과는 숫자·날짜 보존을 결정적으로 검증(value_guard)하고, 어긋나면 원본을 쓴다.
- 원본(raw_values)을 세션에 함께 보존해 매 턴 재변환으로 문체가 중첩되지 않게 한다.
"""

import json
import os

from .config import Config
from .error_codes import (
    ERR_CHAT_INTERNAL,
    ERR_CHAT_NO_FIELDS,
    ERR_CHAT_TEMPLATE_INVALID,
    ERR_CHAT_TEMPLATE_NOT_FOUND,
    ERR_CHAT_UPSTREAM_EXECUTION,
    ERR_CHAT_UPSTREAM_TIMEOUT,
)
from .field_judge import parse_updates
from .hwpx_fields import TemplateError
from .llm import llm_call_async
from .logging_utils import log_info, log_warning
from .prompts import EXTRACT_SYSTEM_PROMPT, build_extract_user_prompt
from .session_store import SessionStoreError, load_session, save_session
from .template_index import get_index
from .tone_apply import apply_tone
from .tone_presets import resolve_tone

_TEMPLATE_ID_RE_STRIP = ("..", "/", "\\")


def _log_context(data) -> dict:
    """로그에 붙일 추적 필드 (3.8절 허용 필드만).

    genos_state 의 trace_id 는 분산추적 키다 — 워크플로우 단계와 코드 서빙 로그를
    한 요청으로 묶으려면 매 로그에 실어야 한다 (CLAUDE.md §4.2).
    """
    state = (data.get("genos_state") or {}) if isinstance(data, dict) else {}
    # resource_id 는 호출부마다 의미가 달라(워크플로우 id / 템플릿 파일명) 여기서 넣지 않는다
    return {"trace_id": state.get("trace_id")}


def _build_error(error_code) -> dict:
    return {
        "error_code": error_code.code,
        "msg": error_code.user_msg,
        "retryable": error_code.retryable,
    }


def _resolve_template_path(template_id: str) -> str:
    """TEMPLATE_DIR 안의 hwpx 경로 확정 (경로 조작 방지)."""
    name = (template_id or "").strip()
    for bad in _TEMPLATE_ID_RE_STRIP:
        name = name.replace(bad, "")
    if not name:
        return ""
    if not name.endswith(".hwpx"):
        name += ".hwpx"
    return os.path.join(Config.TEMPLATE_DIR, name)


def _compose_status_reply(specs, values: dict, accepted: dict, rejected: list, tone_result=None) -> str:
    """이번 턴 반영 결과 + 채움 현황 + 다음 질문을 채팅 답변으로 조립한다."""
    lines = []

    # 톤 적용/기각은 사용자가 알아야 한다 — 문서에 들어갈 문구가 바뀌었기 때문
    if tone_result is not None:
        if tone_result.applied:
            lines.append(
                f"※ 지정된 톤에 맞춰 {len(tone_result.applied)}개 항목의 문체를 다듬었습니다: "
                + ", ".join(tone_result.applied)
            )
        if tone_result.rejected:
            lines.append(
                f"※ {len(tone_result.rejected)}개 항목은 숫자·날짜가 달라져 원문을 그대로 두었습니다: "
                + ", ".join(r["field"] for r in tone_result.rejected)
            )
        if tone_result.llm_error_type:
            lines.append("※ 문체 다듬기에 실패해 입력하신 표현을 그대로 사용했습니다.")
        if lines:
            lines.append("")

    if accepted:
        lines.append("다음 내용을 반영했습니다.")
        for name, value in accepted.items():
            lines.append(f"- **{name}**: {value}")
        lines.append("")
    if rejected:
        lines.append(
            f"※ 템플릿에 없는 항목이라 반영하지 못한 내용이 {len(rejected)}건 있습니다."
        )
        lines.append("")

    filled = [s for s in specs if s.name in values or s.filled]
    missing = [s for s in specs if s.name not in values and not s.filled]

    lines.append(f"**작성 현황** ({len(filled)}/{len(specs)})")
    lines.append("")
    lines.append("| 항목 | 상태 | 내용 |")
    lines.append("|---|---|---|")
    for s in specs:
        value = values.get(s.name) or s.current_value
        if value:
            shown = value if len(value) <= 30 else value[:30] + "…"
            lines.append(f"| {s.name} | ✅ | {shown} |")
        else:
            lines.append(f"| {s.name} | ⬜ 미입력 | {s.guide or ''} |")
    lines.append("")

    if missing:
        next_field = missing[0]
        hint = f" ({next_field.guide})" if next_field.guide else ""
        lines.append(f"이어서 **{next_field.name}**{hint} 내용을 알려주세요.")
        if len(missing) > 1:
            others = ", ".join(s.name for s in missing[1:4])
            more = " 등" if len(missing) > 4 else ""
            lines.append(f"남은 항목: {others}{more}")
    else:
        lines.append(
            "모든 항목이 준비되었습니다. **다운로드 버튼**을 누르면 초안 파일을 생성해 드립니다."
        )
        lines.append("수정하고 싶은 항목이 있으면 말씀해 주세요. (예: 제목을 ○○로 바꿔줘)")

    return "\n".join(lines)


async def run(data: dict):
    # 1) socket.io 세팅 (실시간 토큰 스트리밍용, 모듈이 없으면 조용히 스킵)
    try:
        from main_socketio import sio_server
    except ImportError:
        sio_server = None
    sid = data.get("socketIOClientId") if isinstance(data, dict) else None

    async def emit_event(event_name: str, payload):
        if sio_server and sid:
            await sio_server.emit(event_name, payload, room=sid)
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
            **_log_context(data),
        )
        for ch in error["msg"]:
            yield await emit_event("token", ch)
        yield {"event": "result", "data": {**data, "text": error["msg"], "error": error}}

    # 2) 입력 정규화 (문자열로 넘어오는 경우까지 대응 — text_polish 와 동일 패턴)
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {"question": data}
        sid = data.get("socketIOClientId")

    question = (data.get("question") or data.get("text") or "").strip()
    question = question[: Config.MAX_MESSAGE_CHARS]
    config = data.get("overrideConfig") or {}
    variables = config.get("vars") or {}
    state = data.get("genos_state") or {}
    session_id = str(state.get("session_id") or data.get("sessionId") or "").strip()

    # 3) 세션 로드 + 템플릿 확정 (이번 턴 지정 > 세션에 저장된 것)
    try:
        session = await load_session(session_id) if session_id else {"values": {}, "template_id": ""}
    except ValueError:
        session = {"values": {}, "template_id": ""}
    template_id = str(
        variables.get("template_fill_template_id")
        or session.get("template_id")
        or ""
    ).strip()

    template_path = _resolve_template_path(template_id)
    if not template_path or not os.path.exists(template_path):
        async for event in fail(ERR_CHAT_TEMPLATE_NOT_FOUND):
            yield event
        return

    # 4) 템플릿에서 채울 항목 스키마 확보 (본문 라벨 항목 + 누름틀).
    #    색인 캐시를 경유한다 — 예전에는 매 턴 zip+XML 을 다시 파싱했다.
    #    캐시가 비어 있거나 Redis 가 죽어 있으면 template_index 가 직접 파싱으로 degrade 한다.
    try:
        with open(template_path, "rb") as f:
            template_bytes = f.read()
        index = await get_index(template_id, template_bytes)
    except TemplateError:
        async for event in fail(ERR_CHAT_TEMPLATE_INVALID):
            yield event
        return
    except OSError:
        async for event in fail(ERR_CHAT_TEMPLATE_NOT_FOUND):
            yield event
        return

    specs = index.fields[: Config.MAX_FIELDS]
    if not specs:
        async for event in fail(ERR_CHAT_NO_FIELDS):
            yield event
        return

    allowed_names = {s.name for s in specs}
    values: dict = dict(session.get("values") or {})
    # 세션에 남아 있지만 템플릿이 바뀌어 더는 없는 필드는 버린다
    values = {k: v for k, v in values.items() if k in allowed_names}

    # 템플릿 파일명·필드 개수까지만. 발화 내용과 필드 값은 남기지 않는다 (3.8절).
    log_info(
        "템플릿 항목 스캔 완료",
        event="template_scanned",
        resource_id=os.path.basename(template_path),
        item_count=len(specs),
        # 어떤 방식의 템플릿인지, 그리고 이번 턴이 캐시를 썼는지 운영에서 확인할 수 있게
        status=(
            f"collected={len(values)}"
            f" labels={sum(1 for s in specs if s.source == 'label')}"
            f" fields={sum(1 for s in specs if s.source == 'field')}"
            f" cached={int(index.from_cache)}"
        ),
        **_log_context(data),
    )

    # 5) 사용자 발화에서 필드 값 추출 (LLM)
    accepted: dict = {}
    rejected: list = []
    if question:
        user_prompt = build_extract_user_prompt(specs, values, question)
        try:
            result = await llm_call_async(EXTRACT_SYSTEM_PROMPT, user_prompt)
        except Exception as exc:  # noqa: BLE001 - 클라이언트 초기화 실패 등
            log_warning(
                "LLM 호출 준비 실패",
                event="llm_setup_failed",
                error_type=type(exc).__name__,
                **_log_context(data),
            )
            async for event in fail(ERR_CHAT_INTERNAL):
                yield event
            return
        if not result.ok:
            code = (
                ERR_CHAT_UPSTREAM_TIMEOUT
                if result.is_transport_error
                else ERR_CHAT_UPSTREAM_EXECUTION
            )
            async for event in fail(code):
                yield event
            return
        accepted, rejected = parse_updates(result.content, allowed_names)
        if rejected:
            # 기각 건수는 006 환각률 지표의 원천이다 — 침묵 처리하지 않는다
            log_warning(
                "LLM 응답에서 템플릿에 없는 필드명을 기각",
                event="extraction_keys_rejected",
                item_count=len(rejected),
                **_log_context(data),
            )

    # 6) 톤(문체) 적용 — 이번 턴에 새로 들어온 서술형 값만 변환한다.
    #    누적 값 전체를 매 턴 다시 변환하면 문체 변환이 중첩돼 원문에서 계속 멀어진다.
    #    그래서 원본(raw)을 세션에 따로 보존하고, 변환은 신규 값에만 한 번 적용한다.
    raw_values: dict = dict(session.get("raw_values") or {})
    raw_values = {k: v for k, v in raw_values.items() if k in allowed_names}
    raw_values.update(accepted)

    tone_key = resolve_tone(variables.get("template_fill_tone"))
    tone_result = None
    if tone_key and accepted:
        try:
            tone_result = await apply_tone(
                accepted, tone_key, variables.get("template_fill_tone_fields")
            )
            accepted = dict(tone_result.values)
        except Exception as exc:  # noqa: BLE001 - 톤 적용 실패가 채우기를 막지 않게
            log_warning(
                "톤 적용 단계 예외 — 원본 값으로 계속 진행",
                event="tone_stage_error",
                error_type=type(exc).__name__,
                **_log_context(data),
            )

    # 7) 상태 병합 + 저장 (판정은 코드가 결정적으로 수행)
    values.update(accepted)
    if session_id:
        try:
            await save_session(session_id, template_id, values, raw_values)
        except SessionStoreError as exc:
            # 저장 실패 = 다음 턴에 값이 유실된다 — 침묵 처리하지 않고 실패로 종료
            log_warning(
                "세션 저장 실패 — 이번 턴 값이 다음 턴에 유지되지 않는다",
                event="session_save_failed",
                error_type=type(exc).__name__,
                **_log_context(data),
            )
            async for event in fail(ERR_CHAT_INTERNAL):
                yield event
            return
    else:
        log_warning(
            "session_id 없음 — 이번 턴 값이 다음 턴에 유지되지 않는다",
            event="session_id_missing",
            **_log_context(data),
        )

    # 8) 채움 판정 (코드가 결정적으로)
    filled_names = [s.name for s in specs if s.name in values or s.filled]
    missing_names = [s.name for s in specs if s.name not in values and not s.filled]
    ready = not missing_names

    display_text = _compose_status_reply(specs, values, accepted, rejected, tone_result)

    # 9) 토큰 스트리밍 (UI 실시간 표시)
    for ch in display_text:
        yield await emit_event("token", ch)

    # 10) 최종 결과 확정 — 다운로드 버튼(코드 서빙 /generate)이 쓸 구조화 데이터 포함
    yield {
        "event": "result",
        "data": {
            **data,
            "text": display_text,
            "template_id": template_id,
            "session_id": session_id,
            "field_values": values,
            "fields_filled": filled_names,
            "fields_missing": missing_names,
            "ready_for_download": ready,
            # 템플릿 원본 모양 (색인에 이미 들어 있어 추가 파싱이 없다). UI 가 첫 턴에
            # "이 템플릿은 이렇게 생겼다"를 보여줄 때 쓴다. 값이 채워진 문서 미리보기는
            # 코드 서빙 GET /preview 가 담당한다 — 다운로드와 같은 채우기 경로를 타야 해서다.
            "template_markdown": index.markdown,
            "template_markdown_truncated": index.truncated,
            # 톤 적용 결과 — 무엇이 바뀌고 무엇이 기각됐는지 후속 스텝/검수에 노출
            "tone": tone_key,
            "tone_applied_fields": tone_result.applied if tone_result else [],
            "tone_rejected_fields": tone_result.rejected if tone_result else [],
            "field_values_raw": raw_values,
            "error": None,
        },
    }
