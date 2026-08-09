"""글다듬이(Text Polish) 워크플로우 Python 단계.

역할: 전처리기가 마크다운으로 변환한 업로드 문서(genosUploaded) 또는 채팅 입력 텍스트를
문서유형(doc_type) 정책과 톤(tone)에 맞춰 LLM으로 다듬고,
다듬어진 결과 + 어떤 문장이 바뀌었는지 변경 내역을 함께 반환한다.

GenOS 엔지니어 개발가이드 v1.02 반영 (부록 C.2 체크리스트)
- 함수명 run 고정, 인자 data: dict 1개 (5.1절)
- 토큰 스트리밍 → async generator 패턴만 사용, 단순 return과 혼용 금지 (5.2절)
- 마지막에 event: result 를 반드시 1회 yield (5.2절)
- 외부 I/O는 timeout 명시 + 상한 있는 재시도 (3.6절/10.2절, llm.py 내부 처리)
- 오류는 예외 대신 data["error"] = {error_code, msg, retryable} (3.9.6절)
- 예외 원문·문서 원문·LLM 응답 전문은 로그/응답에 노출하지 않음 (3.8절)
"""

import asyncio
import json
import re

from .diff_report import build_change_list, format_changes_markdown
from .error_codes import (
    ERR_INPUT_EMPTY,
    ERR_INTERNAL,
    ERR_UPSTREAM_EXECUTION,
    ERR_UPSTREAM_TIMEOUT,
)
from .llm import polish_text_async
from .logging_utils import log_info, log_warning
from .fact_guard import fact_issue_counts, find_fact_issues
from .markdown_guard import find_structure_issues
from .prompt_loader import PromptRenderError, render as render_prompt
from .tone_presets import DOC_TYPE_POLICIES, TONE_PRESETS, resolve_tone

_DOC_TAG_RE = re.compile(r"<doc[^>]*>(.*?)</doc>", re.DOTALL)


def _log_context(data) -> dict:
    """로그 추적 필드 (3.8절 허용 필드만). trace_id 로 단계 간 로그를 묶는다."""
    state = (data.get("genos_state") or {}) if isinstance(data, dict) else {}
    return {"trace_id": state.get("trace_id")}


def _extract_uploaded_markdown(genos_uploaded: str) -> str:
    """전처리기 산출물 genosUploaded 의 <doc ...>마크다운</doc> 블록에서 본문만 추출."""
    if not genos_uploaded:
        return ""
    matches = _DOC_TAG_RE.findall(genos_uploaded)
    if matches:
        return "\n\n".join(m.strip() for m in matches if m.strip())
    return genos_uploaded.strip()


def _build_error(error_code) -> dict:
    return {
        "error_code": error_code.code,
        "msg": error_code.user_msg,
        "retryable": error_code.retryable,
    }


def _build_system_prompt(doc_type_key: str, tone_key: str) -> str:
    """문구는 `onprem/prompt/SFR-018_text_polish/system.j2` 에 있다.

    여기서는 문서유형·톤 정책(`tone_presets.py`)을 템플릿 변수로 옮기기만 한다.

    Raises:
        PromptRenderError: 템플릿 부재·변수 누락. 빈 프롬프트로 넘어가지 않는다 —
            지시 없이 돌린 결과가 정상 응답처럼 내려가는 쪽이 더 위험하다.
    """
    policy = DOC_TYPE_POLICIES[doc_type_key]
    tone = TONE_PRESETS[tone_key]
    return render_prompt(
        "system.j2",
        doc_type_label=policy.label,
        doc_type_instruction=policy.extra_instruction,
        tone_label=tone.label,
        tone_instruction=tone.instruction,
    )


# 토큰 스트리밍 단위. 글자 하나씩 보내면 다듬은 본문 한 장이 emit 수천 회가 되고,
# 그만큼 이벤트 루프 양보가 늘어 오히려 표시가 늦어진다.
_STREAM_CHUNK_CHARS = 32


def _stream_chunks(text: str):
    """긴 답변을 스트리밍용 청크로 자른다 (UI 는 받는 대로 이어붙인다)."""
    for start in range(0, len(text), _STREAM_CHUNK_CHARS):
        yield text[start : start + _STREAM_CHUNK_CHARS]


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
            # WebSocket write buffer flush. 양보하지 않고 emit 을 몰아치면 소켓 쓰기가
            # 버퍼에 쌓여 UI 가 마지막에 한꺼번에 받는다 (가이드 5.2·D.4 '스트리밍이
            # 일괄 반환되는 원인'). 실제 운영 bridge 도 매 emit 뒤에 이걸 넣는다.
            await asyncio.sleep(0)
        return {"event": event_name, "data": payload}

    async def fail(error_code):
        """오류를 사용자 메시지로 스트리밍하고 result로 마무리하는 공통 경로."""
        error = _build_error(error_code)
        log_warning(
            "글다듬이 오류 응답",
            event="text_polish_error",
            error_code=error["error_code"],
            error_type=error_code.error_type,
            status="retryable" if error_code.retryable else "final",
            **_log_context(data),
        )
        for chunk in _stream_chunks(error["msg"]):
            yield await emit_event("token", chunk)
        yield {"event": "result", "data": {**data, "text": error["msg"], "error": error}}

    # 2) 입력 정규화 (문자열로 넘어오는 경우까지 대응)
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {"question": data}
        sid = data.get("socketIOClientId")

    question = (data.get("question") or data.get("text") or "").strip()
    config = data.get("overrideConfig") or {}
    variables = config.get("vars") or {}
    genos_uploaded = variables.get("genosUploaded") or ""

    # 문서유형/톤: 워크플로우 변수로 주입 (관리자 설정 UI → $vars)
    doc_type_key, tone_key, tone_overridden = resolve_tone(
        variables.get("polish_doc_type"),
        variables.get("polish_tone"),
    )

    # 3) 다듬을 원본 결정: 업로드 문서(마크다운) 우선, 없으면 채팅 텍스트
    source_text = _extract_uploaded_markdown(genos_uploaded) or question

    if not source_text:
        async for event in fail(ERR_INPUT_EMPTY):
            yield event
        return

    # 문서 원문은 남기지 않는다 — 문서유형/톤과 정책 강제 여부만 (3.8절)
    log_info(
        "글다듬이 요청 접수",
        event="polish_started",
        resource_id=f"{doc_type_key}/{tone_key}",
        status="tone_forced" if tone_overridden else "tone_as_requested",
        item_count=len(source_text.splitlines()),
        **_log_context(data),
    )

    # 프롬프트 렌더 실패는 LLM 실패와 따로 잡는다 — 전자는 이미지에 프롬프트 디렉토리를
    # 안 넣었다는 배포 실수라 운영에서 구분돼야 손을 쓸 수 있다.
    try:
        system_prompt = _build_system_prompt(doc_type_key, tone_key)
    except PromptRenderError as exc:
        log_warning(
            "프롬프트 생성 실패",
            event="prompt_render_failed",
            error_type=type(exc).__name__,
            **_log_context(data),
        )
        async for event in fail(ERR_INTERNAL):
            yield event
        return

    # 4) LLM 호출 (timeout + 상한 재시도는 llm.py 내부에서 처리, 실패는 LlmResult 로 반환)
    try:
        llm_result = await polish_text_async(system_prompt, source_text)
    except Exception as exc:  # noqa: BLE001 - 예상 밖 오류까지 안전하게 흡수
        log_warning(
            "글다듬이 내부 처리 실패",
            event="polish_internal_error",
            error_type=type(exc).__name__,
            **_log_context(data),
        )
        async for event in fail(ERR_INTERNAL):
            yield event
        return

    if not llm_result.ok:
        # 예외 타입 기반 분류 (llm.py) — 통신 실패면 00020001, 그 외 실행 실패는 00020002
        async for event in fail(
            ERR_UPSTREAM_TIMEOUT if llm_result.is_transport_error else ERR_UPSTREAM_EXECUTION
        ):
            yield event
        return
    polished = llm_result.content

    # 5) 변경 내역 계산 — LLM에 재차 묻지 않고 difflib으로 결정적으로 산출
    #    (LLM이 변경 내역을 지어낼 위험 제거 + 호출 1회 절감)
    try:
        changes = build_change_list(source_text, polished)
    except Exception as exc:  # noqa: BLE001 - diff 실패가 본 결과 전달을 막지 않도록
        log_warning(
            "변경 내역 생성 실패 — 결과는 그대로 전달",
            event="diff_failed",
            error_type=type(exc).__name__,
            **_log_context(data),
        )
        changes = []

    # 6) 마크다운 구조 훼손 자동 점검 — 프롬프트 지시(규칙 3)를 믿지 않고
    #    표 행·열/제목/코드펜스 지문을 결정적으로 대조한다. 훼손 시 결과는
    #    그대로 전달하되 경고를 노출한다 (침묵 처리 금지).
    try:
        structure_warnings = find_structure_issues(source_text, polished)
    except Exception as exc:  # noqa: BLE001 - 점검 실패가 본 결과 전달을 막지 않도록
        log_warning(
            "구조 점검 실패 — 결과는 그대로 전달",
            event="structure_check_failed",
            error_type=type(exc).__name__,
            **_log_context(data),
        )
        structure_warnings = []
    if structure_warnings:
        log_warning(
            "마크다운/HTML 구조 훼손 감지",
            event="structure_damaged",
            item_count=len(structure_warnings),
            **_log_context(data),
        )

    # 6-2) 사실 보존 점검 — 톤 프리셋의 "사실 정보를 생략하지 않는다" 지시를 믿지 않고
    #      숫자·날짜를 다중집합으로 대조한다. 구조 점검과 같은 규율이다: **되돌리지 않고**
    #      경고만 노출한다 (문서 전체를 되돌리면 기능 자체가 사라진다 — fact_guard 참고).
    try:
        fact_warnings = find_fact_issues(source_text, polished)
    except Exception as exc:  # noqa: BLE001 - 점검 실패가 본 결과 전달을 막지 않도록
        log_warning(
            "사실 보존 점검 실패 — 결과는 그대로 전달",
            event="fact_check_failed",
            error_type=type(exc).__name__,
            **_log_context(data),
        )
        fact_warnings = []
    if fact_warnings:
        counts = fact_issue_counts(source_text, polished)
        log_warning(
            "숫자·날짜 불일치 감지",
            event="fact_mismatch",
            # 3.8절: 어긋난 값은 남기지 않고 개수만. 값은 사용자 답변에만 실린다.
            item_count=sum(counts.values()),
            status=f"numbers={counts['numbers']} dates={counts['dates']}",
            **_log_context(data),
        )

    # 7) 채팅 노출용 최종 답변 조립
    notice = ""
    if tone_overridden:
        forced_label = TONE_PRESETS[tone_key].label
        doc_label = DOC_TYPE_POLICIES[doc_type_key].label
        notice = f"※ '{doc_label}' 문서는 정책상 '{forced_label}' 톤이 적용됩니다.\n\n"
    for warning in structure_warnings:
        notice += f"⚠ {warning} 원문과 대조해 확인해 주세요.\n"
    # 사실 경고는 어긋난 값을 이미 담고 있어 "원문과 대조해" 를 덧붙이지 않는다 —
    # 어디를 볼지 안내문 자체가 가리킨다.
    for warning in fact_warnings:
        notice += f"⚠ {warning}\n"
    if structure_warnings or fact_warnings:
        notice += "\n"

    display_text = notice + polished + format_changes_markdown(changes)

    # 8) 토큰 스트리밍 (UI에 실시간 표시)
    for chunk in _stream_chunks(display_text):
        yield await emit_event("token", chunk)

    # 9) 최종 결과 확정 — 다음 스텝은 polished_text / changes 를 구조화 데이터로 사용 가능
    yield {
        "event": "result",
        "data": {
            **data,
            "text": display_text,          # 채팅에 노출되는 전체 답변
            "polished_text": polished,     # 다듬어진 본문만 (후속 스텝용)
            "changes": changes,            # [{"before": ..., "after": ...}]
            "structure_warnings": structure_warnings,  # 표/제목/코드블록 훼손 감지
            "fact_warnings": fact_warnings,            # 숫자·날짜 불일치 감지
            "polish_doc_type": doc_type_key,
            "polish_tone": tone_key,
            "tone_overridden": tone_overridden,
            "error": None,
        },
    }
