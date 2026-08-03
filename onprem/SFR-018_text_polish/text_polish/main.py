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
from .markdown_guard import find_structure_issues
from .tone_presets import DOC_TYPE_POLICIES, TONE_PRESETS, resolve_tone

_DOC_TAG_RE = re.compile(r"<doc[^>]*>(.*?)</doc>", re.DOTALL)

_BASE_SYSTEM_PROMPT = (
    "당신은 한국어 교정/윤문 전문가입니다. 지시된 문서유형과 톤에 맞춰 입력 글을 다듬습니다.\n"
    "규칙:\n"
    "1) 원문에 없는 사실·수치·이름을 새로 만들어내지 않는다.\n"
    "2) 오탈자, 띄어쓰기, 비문을 교정한다.\n"
    "3) 입력이 마크다운이면 제목(#), 표(|), 목록(-) 등 마크다운 구조를 그대로 유지하고 "
    "본문 문장만 다듬는다.\n"
    "4) 다듬어진 글 전체만 출력한다. 설명, 인사말, 코드블록 표시(```)를 덧붙이지 않는다.\n"
)


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
    policy = DOC_TYPE_POLICIES[doc_type_key]
    tone = TONE_PRESETS[tone_key]
    parts = [
        _BASE_SYSTEM_PROMPT,
        f"[문서유형: {policy.label}]",
    ]
    if policy.extra_instruction:
        parts.append(policy.extra_instruction)
    parts.append(f"[톤: {tone.label}]")
    parts.append(tone.instruction)
    return "\n".join(parts)


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
        """오류를 사용자 메시지로 스트리밍하고 result로 마무리하는 공통 경로."""
        error = _build_error(error_code)
        log_warning(f"[글다듬이] error_code={error['error_code']} error_type={error_code.error_type}")
        for ch in error["msg"]:
            yield await emit_event("token", ch)
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

    log_info(
        f"[글다듬이] doc_type={doc_type_key} tone={tone_key} "
        f"overridden={tone_overridden} 입력 길이={len(source_text)}자"
    )

    system_prompt = _build_system_prompt(doc_type_key, tone_key)

    # 4) LLM 호출 (timeout + 상한 재시도는 llm.py 내부에서 처리, 실패는 LlmResult 로 반환)
    try:
        llm_result = await polish_text_async(system_prompt, source_text)
    except Exception as exc:  # noqa: BLE001 - 예상 밖 오류까지 안전하게 흡수
        log_warning(f"[글다듬이] error_type={type(exc).__name__} (내부 처리 실패)")
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
        log_warning(f"[글다듬이] diff 생성 실패 error_type={type(exc).__name__}")
        changes = []

    # 6) 마크다운 구조 훼손 자동 점검 — 프롬프트 지시(규칙 3)를 믿지 않고
    #    표 행·열/제목/코드펜스 지문을 결정적으로 대조한다. 훼손 시 결과는
    #    그대로 전달하되 경고를 노출한다 (침묵 처리 금지).
    try:
        structure_warnings = find_structure_issues(source_text, polished)
    except Exception as exc:  # noqa: BLE001 - 점검 실패가 본 결과 전달을 막지 않도록
        log_warning(f"[글다듬이] 구조 점검 실패 error_type={type(exc).__name__}")
        structure_warnings = []
    if structure_warnings:
        log_warning(f"[글다듬이] 구조 훼손 감지 {len(structure_warnings)}건")

    # 7) 채팅 노출용 최종 답변 조립
    notice = ""
    if tone_overridden:
        forced_label = TONE_PRESETS[tone_key].label
        doc_label = DOC_TYPE_POLICIES[doc_type_key].label
        notice = f"※ '{doc_label}' 문서는 정책상 '{forced_label}' 톤이 적용됩니다.\n\n"
    for warning in structure_warnings:
        notice += f"⚠ {warning} 원문과 대조해 확인해 주세요.\n"
    if structure_warnings:
        notice += "\n"

    display_text = notice + polished + format_changes_markdown(changes)

    # 8) 토큰 스트리밍 (UI에 실시간 표시)
    for ch in display_text:
        yield await emit_event("token", ch)

    # 9) 최종 결과 확정 — 다음 스텝은 polished_text / changes 를 구조화 데이터로 사용 가능
    yield {
        "event": "result",
        "data": {
            **data,
            "text": display_text,          # 채팅에 노출되는 전체 답변
            "polished_text": polished,     # 다듬어진 본문만 (후속 스텝용)
            "changes": changes,            # [{"before": ..., "after": ...}]
            "structure_warnings": structure_warnings,  # 표/제목/코드블록 훼손 감지
            "polish_doc_type": doc_type_key,
            "polish_tone": tone_key,
            "tone_overridden": tone_overridden,
            "error": None,
        },
    }
