"""GenOS workflow 입력을 상담사 Code Serving HTTP/SSE 호출로 연결하는 bridge."""
from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Callable
from typing import Any

import httpx

try:
    from main_socketio import sio_server as _sio

    sio_server = _sio
    IS_LOCAL = False
except ImportError:  # 로컬 테스트와 단독 실행에서는 socket 서버가 없을 수 있다.
    sio_server = None
    IS_LOCAL = True


ClientFactory = Callable[..., Any]


def _code_serving_url() -> str:
    """Code Serving JSON 엔드포인트 URL을 환경변수에서 만든다."""
    explicit = os.getenv("GENOS_URL")
    if explicit:
        return explicit

    base_url = (os.getenv("GENOS_BASE_URL") or "").rstrip("/")
    code_serving_id = os.getenv("CODE_SERVING_ID")
    if not base_url or not code_serving_id:
        raise RuntimeError("Set GENOS_URL or both GENOS_BASE_URL and CODE_SERVING_ID.")
    return f"{base_url}/api/gateway/code_serving/{code_serving_id}/json"


def _bearer_token() -> str:
    """Code Serving 인증 토큰을 환경변수에서 읽는다."""
    token = os.getenv("CODE_SERVING_BEARER_TOKEN") or os.getenv("GENOS_TOKEN")
    if not token:
        raise RuntimeError("Set CODE_SERVING_BEARER_TOKEN or GENOS_TOKEN.")
    return token


def build_service_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Workflow 입력 alias를 원격 counselor Code Serving payload로 정규화한다."""
    request_payload = _as_dict(data.get("request_payload"))
    question = _first_present(
        data.get("question"),
        data.get("message"),
        data.get("query"),
        request_payload.get("question"),
        request_payload.get("message"),
        request_payload.get("query"),
        default="",
    )
    session_id = _first_present(
        data.get("session_id"),
        data.get("sessionId"),
        data.get("socketIOClientId"),
        request_payload.get("session_id"),
        request_payload.get("sessionId"),
        default="default",
    )
    chat_id = _first_present(
        data.get("chatId"),
        data.get("chat_id"),
        request_payload.get("chatId"),
        request_payload.get("chat_id"),
    )
    # counselor_info = _normalize_counselor_info(
    #     _as_dict(_first_present(data.get("counselor_info"), request_payload.get("counselor_info"), default={}))
    # )
    customer_info = {
        "name": "김미리",
        "cstMngtNo": data.get("cst_mngt_no",)
    }
    history = _as_list(
        _first_present(
            data.get("turn_history"),
            data.get("history"),
            request_payload.get("turn_history"),
            request_payload.get("history"),
            default=[],
        )
    )

    return {
        "track": "agent",
        "session_id": chat_id or session_id,
        "chat_id": chat_id,
        "question": question,
        "customer_info": customer_info,
        "turn_history": history,
    }


def format_workflow_response(service_response: dict[str, Any]) -> dict[str, Any]:
    """service final 응답 dict를 workflow UI가 표시하기 쉬운 text 중심 응답으로 바꾼다."""
    result: dict[str, Any] = {
        "status": service_response.get("status"),
        "text": _response_text(service_response),
        "answer": service_response.get("answer"),
        "sessionId": service_response.get("session_id"),
        "chatId": service_response.get("chat_id"),
        "final": service_response,
    }
    flow_events = _flow_events(service_response)
    if flow_events:
        result["reasoning"] = [_event_text(event) for event in flow_events]
        result["agentFlowExecutedData"] = [_agent_flow_payload(event) for event in flow_events]
    if service_response.get("reason") is not None:
        result["reason"] = service_response["reason"]
    return result


# ── 고객관리번호 수집 상태 기계 ──────────────────────────────────────────────
_session_states: dict[str, dict[str, Any]] = {}
_MAX_ID_ATTEMPTS = 10
_CST_MNGT_NO_RE = re.compile(r"(?<!\d)\d{11}(?!\d)")
_CONFIRM_YES_RE = re.compile(r"어|엉|응|예|네|맞|확인|ㅇ+|yes|y", re.IGNORECASE)
_CONFIRM_NO_RE = re.compile(r"아니|다시|틀|노|놉|ㄴ+|no|n", re.IGNORECASE)
_CJK_RE = re.compile(r"[぀-ヿ一-鿿㐀-䶿豈-﫿]")


_CST_MNGT_MODE: bool = os.getenv("CST_MNGT_MODE", "0") == "1"

_DEBUG_FOOTER = (
    '<hr style="border:none;border-top:1px solid #30363d;margin:8px 0 6px;">'
    '<span style="color:#6e7681;">'
    "🔬 현재 모드는 <strong>테스트 기간 한정</strong>으로 운영되는 "
    "고객관리번호 직접 수집 모드입니다. "
    "정식 운영 시에는 이 안내가 표시되지 않습니다."
    "</span>"
)


def _debug_html(*lines: str) -> str:
    body = "".join(lines)
    inner = (
        '<div style="font-family:\'Courier New\',Courier,monospace;'
        "background:#0d1117;color:#c9d1d9;padding:14px 18px;"
        "border-radius:6px;border:1px solid #30363d;"
        'font-size:13px;line-height:2.0;display:inline-block;text-align:left;">'
        + body
        + _DEBUG_FOOTER
        + "</div>"
    )
    return (
        '<div style="display:flex;justify-content:center;align-items:center;padding:12px 0;">'
        + inner
        + "</div>"
    )


def _dl(tag: str, msg: str, tag_color: str = "#58a6ff", msg_color: str = "#e6edf3") -> str:
    return (
        f'<span style="color:{tag_color};font-weight:bold;">[{tag}]</span>'
        f' <span style="color:{msg_color};">{msg}</span><br>'
    )


def _mask_cst_id(cst_mngt_no: str) -> str:
    return cst_mngt_no[:3] + "*" * 5 + cst_mngt_no[-3:]


async def _handle_session_state(sid: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """고객관리번호 수집 흐름을 처리한다. 조기 반환이면 dict, httpx로 진행하면 None."""
    state = _session_states.get(sid)

    async def _reply(html: str) -> dict[str, Any]:
        """HTML을 token 이벤트로 스트리밍하고 data["text"]에도 실어 반환한다."""
        await sio_server.emit("token", html, room=sid)
        await asyncio.sleep(0)
        return {"text": html, "reasoning": [], "agentFlowExecutedData": []}

    if state is None:
        _session_states[sid] = {"status": "waiting_id", "attempts": 0, "cst_mngt_no": None, "pending": None}
        data.update(await _reply(_debug_html(
            _dl("SYS", "&#9654; 세션 초기화 완료", tag_color="#3fb950"),
            _dl("INPUT REQUIRED", "고객관리번호(11자리 숫자)를 입력해 주세요.", tag_color="#d29922", msg_color="#ffd700"),
            _dl("INFO", f"최대 {_MAX_ID_ATTEMPTS}회까지 입력 가능 &middot; 인식 불가 시 재입력 안내가 표시됩니다.", tag_color="#8b949e", msg_color="#8b949e"),
        )))
        return data

    if state["status"] == "waiting_id":
        question = str(data.get("question") or "")
        m = _CST_MNGT_NO_RE.search(question)

        if m:
            cst_mngt_no = m.group()
            state["pending"] = cst_mngt_no
            state["status"] = "confirming_id"
            data.update(await _reply(_debug_html(
                _dl("DETECT", f"고객관리번호 감지 &rarr; {cst_mngt_no}", tag_color="#58a6ff"),
                _dl("CONFIRM?", f"이 번호({cst_mngt_no})가 고객관리번호가 맞으신가요?", tag_color="#d29922", msg_color="#ffd700"),
                _dl("INFO", "'예' 또는 '아니오'로 답해 주세요.", tag_color="#8b949e", msg_color="#8b949e"),
            )))
            return data

        state["attempts"] += 1
        remaining = _MAX_ID_ATTEMPTS - state["attempts"]

        if remaining <= 0:
            del _session_states[sid]
            html = _debug_html(
                _dl("ERROR", f"최대 입력 횟수({_MAX_ID_ATTEMPTS}회)를 초과했습니다.", tag_color="#f85149", msg_color="#ffa198"),
                _dl("SYS", "세션을 종료합니다. 다시 연결해 주세요.", tag_color="#8b949e"),
            )
        else:
            html = _debug_html(
                _dl("WARN", f"11자리 숫자를 찾을 수 없습니다. ({state['attempts']}/{_MAX_ID_ATTEMPTS})", tag_color="#d29922"),
                _dl("INPUT REQUIRED", "고객관리번호를 다시 입력해 주세요.", tag_color="#d29922", msg_color="#ffd700"),
                _dl("INFO", f"남은 시도 횟수: {remaining}회", tag_color="#8b949e", msg_color="#8b949e"),
            )
        data.update(await _reply(html))
        return data

    if state["status"] == "confirming_id":
        answer = str(data.get("question") or "").strip()
        pending = state["pending"]
        display_id = pending if pending else "???"

        if _CONFIRM_YES_RE.search(answer):
            state["cst_mngt_no"] = pending
            state["pending"] = None
            state["status"] = "ready"
            data.update(await _reply(_debug_html(
                _dl("CONFIRM", "확인 완료 &#10003;", tag_color="#3fb950"),
                _dl("READY", f"고객관리번호 {display_id} 로 채팅을 시작합니다.", tag_color="#3fb950", msg_color="#aff5b4"),
                _dl("INFO", "이제 궁금하신 내용을 입력해 주세요.", tag_color="#8b949e", msg_color="#8b949e"),
            )))
            return data

        if _CONFIRM_NO_RE.search(answer):
            state["pending"] = None
            state["status"] = "waiting_id"
            state["attempts"] += 1
            remaining = _MAX_ID_ATTEMPTS - state["attempts"]
            if remaining <= 0:
                del _session_states[sid]
                html = _debug_html(
                    _dl("ERROR", f"최대 입력 횟수({_MAX_ID_ATTEMPTS}회)를 초과했습니다.", tag_color="#f85149", msg_color="#ffa198"),
                    _dl("SYS", "세션을 종료합니다. 다시 연결해 주세요.", tag_color="#8b949e"),
                )
            else:
                html = _debug_html(
                    _dl("RETRY", "다시 입력해 주세요.", tag_color="#d29922"),
                    _dl("INPUT REQUIRED", "고객관리번호(11자리 숫자)를 입력해 주세요.", tag_color="#d29922", msg_color="#ffd700"),
                    _dl("INFO", f"남은 시도 횟수: {remaining}회", tag_color="#8b949e", msg_color="#8b949e"),
                )
            data.update(await _reply(html))
            return data

        # 예/아니오 외 불명확한 응답
        data.update(await _reply(_debug_html(
            _dl("WARN", f"입력을 인식하지 못했습니다. 감지된 번호: {display_id}", tag_color="#d29922"),
            _dl("CONFIRM?", "이 번호가 고객관리번호가 맞으신가요?", tag_color="#d29922", msg_color="#ffd700"),
            _dl("INFO", "'예' 또는 '아니오'로 답해 주세요.", tag_color="#8b949e", msg_color="#8b949e"),
        )))
        return data

    # status == "ready": 저장된 cst_mngt_no 주입 후 httpx 호출로 진행
    data["cst_mngt_no"] = state["cst_mngt_no"]
    return None


async def run(
    data: dict[str, Any],
    *,
    client_factory: ClientFactory = httpx.AsyncClient,
) -> dict[str, Any]:
    """Workflow 노드에서 호출되어 부모 bridge와 같은 방식으로 원격 Code Serving SSE를 읽는다."""
    sid = _first_present(data.get("socketIOClientId"), data.get("sessionId"), data.get("session_id"))

    # 고객관리번호 수집 상태 기계 — CST_MNGT_MODE=1 이고 sio_server가 있을 때만 활성화
    if _CST_MNGT_MODE and sid and sio_server:
        early = await _handle_session_state(sid, data)
        if early is not None:
            return early

    request_data = build_service_payload(data)
    if sid is None:
        sid = str(request_data.get("session_id") or "")

    result: dict[str, Any] = {
        "agentFlowExecutedData": [],
        "text": "",
        "reasoning": [],
    }
    text_acc = ""
    emitted_flow_keys: set[tuple[Any, Any, Any, Any, Any]] = set()
    pending_reasoning_parts: list[str] = []
    pending_reasoning_event: dict[str, Any] | None = None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_bearer_token()}",
    }

    async def emit_agent_flow(event: dict[str, Any]) -> None:
        reasoning_text = _event_text(event)
        if not reasoning_text:
            return
        key = _flow_event_key(event)
        if key in emitted_flow_keys:
            return
        emitted_flow_keys.add(key)
        payload = _agent_flow_payload(event)
        result["reasoning"].append(reasoning_text)
        result["agentFlowExecutedData"].append(payload)

        if sid and sio_server:
            await sio_server.emit(
                "agentFlowExecutedData",
                result["agentFlowExecutedData"],
                room=sid,
            )
        await asyncio.sleep(0)  # WebSocket write buffer flush — 이벤트가 빠르게 몰릴 때 실시간 전달 보장

    async def queue_reasoning(event: dict[str, Any]) -> None:
        nonlocal pending_reasoning_event
        text = str(event.get("data") or "")
        if not text:
            return
        if pending_reasoning_event is None:
            pending_reasoning_event = {key: value for key, value in event.items() if key != "data"}
        pending_reasoning_parts.append(text)

    async def flush_reasoning() -> None:
        nonlocal pending_reasoning_event
        if pending_reasoning_event is None or not pending_reasoning_parts:
            return
        event = dict(pending_reasoning_event)
        event["data"] = "".join(pending_reasoning_parts).strip()
        pending_reasoning_event = None
        pending_reasoning_parts.clear()
        await emit_agent_flow(event)

    async def apply_final_event(event_data: dict[str, Any]) -> None:
        await flush_reasoning()
        _apply_final_event(result, event_data)
        for event in _flow_events(event_data):
            await emit_agent_flow(event)

    async with client_factory(timeout=None) as client:
        async with client.stream(
            "POST",
            _code_serving_url(),
            headers=headers,
            json=request_data,
        ) as response:
            response.raise_for_status()

            saw_sse = False
            non_sse_lines: list[str] = []
            async for line in response.aiter_lines():
                if line and not line.startswith("data:"):
                    non_sse_lines.append(line)
                    continue

                parsed = _parse_sse_line(line)
                if parsed is None:
                    continue

                saw_sse = True
                event = parsed.get("event")
                event_data = parsed.get("data")

                if event == "reasoning_token":
                    await queue_reasoning(_event_dict(event, event_data))
                    continue

                # reasoning_token이 아닌 모든 이벤트 → 누적된 reasoning 즉시 flush
                await flush_reasoning()

                if event in {"algorithm_step", "tool_call", "tool_result"}:
                    await emit_agent_flow(_event_dict(event, event_data))
                    continue

                # 상담사 인계 — 사유·상세를 reasoning 패널에 표시 (개발 디버깅용)
                if event == "handoff" and isinstance(event_data, dict):
                    await emit_agent_flow({"event": "handoff", "data": _format_handoff_text(event_data)})
                    continue

                if event in {"token", "answer_token"}:
                    token_text = str(event_data or "")
                    if not token_text:
                        continue
                    text_acc += token_text
                    if sid and sio_server:
                        await sio_server.emit("token", token_text, room=sid)
                        await asyncio.sleep(0)
                    continue

                if event == "final" and isinstance(event_data, dict):
                    await apply_final_event(event_data)
                    continue

            if not saw_sse and non_sse_lines:
                try:
                    parsed_body = json.loads("\n".join(non_sse_lines))
                except json.JSONDecodeError:
                    parsed_body = None
                if isinstance(parsed_body, dict):
                    await apply_final_event(parsed_body)

    await flush_reasoning()
    final_answer = _response_text(result.get("final") if isinstance(result.get("final"), dict) else result)
    _raw = _strip_tool_call_tags(text_acc or final_answer).replace("~", "-").replace("^^", "")
    result["text"] = _CJK_RE.sub("", _raw)
    data.update(result)
    return data


def _flow_events(response: dict[str, Any]) -> list[dict[str, Any]]:
    """service 이벤트 중 workflow flow 패널에 표시할 이벤트만 추린다."""
    events = response.get("reasoning_events")
    if not isinstance(events, list):
        return []

    flow_events: list[dict[str, Any]] = []
    pending_reasoning_parts: list[str] = []
    pending_reasoning_event: dict[str, Any] | None = None

    def flush_reasoning() -> None:
        nonlocal pending_reasoning_event
        if pending_reasoning_event is None or not pending_reasoning_parts:
            return
        event = dict(pending_reasoning_event)
        event["data"] = "".join(pending_reasoning_parts).strip()
        flow_events.append(event)
        pending_reasoning_event = None
        pending_reasoning_parts.clear()

    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("event") not in {"algorithm_step", "tool_call", "tool_result", "reasoning_token"}:
            continue
        text = str(event.get("data") or "") if event.get("event") == "reasoning_token" else _event_text(event)
        if not text:
            continue
        if event.get("event") == "reasoning_token":
            if pending_reasoning_event is None:
                pending_reasoning_event = {key: value for key, value in event.items() if key != "data"}
            pending_reasoning_parts.append(text)
            continue
        flush_reasoning()
        flow_events.append(event)

    flush_reasoning()
    return flow_events


def _flow_event_key(event: dict[str, Any]) -> tuple[Any, Any, Any, Any, Any]:
    """중간 SSE와 final.reasoning_events가 같은 이벤트를 중복 표시하지 않게 식별한다."""
    return (
        event.get("event"),
        event.get("data"),
        event.get("stage"),
        event.get("source"),
        event.get("tool_name"),
    )


def _parse_sse_line(line: str) -> dict[str, Any] | None:
    """SSE data 라인 하나를 JSON 이벤트로 파싱한다."""
    if not line or not line.startswith("data:"):
        return None
    raw = line.replace("data:", "", 1).strip()
    if raw in {"[DONE]", "DONE"}:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _apply_final_event(result: dict[str, Any], event_data: dict[str, Any]) -> None:
    """원격 service final 이벤트를 workflow 결과 dict에 반영한다."""
    result["final"] = event_data
    result["answer"] = event_data.get("answer")
    result["confidence"] = event_data.get("confidence")
    result["turn_history"] = event_data.get("turn_history", [])
    if event_data.get("status") is not None:
        result["status"] = event_data["status"]
    if event_data.get("reason") is not None:
        result["reason"] = event_data["reason"]
    if event_data.get("chat_id") is not None:
        result["chatId"] = event_data.get("chat_id")
    if event_data.get("session_id") is not None:
        result["sessionId"] = event_data.get("session_id")
    if isinstance(event_data.get("evidence_refs"), list):
        result["evidence_refs"] = event_data["evidence_refs"]
    if isinstance(event_data.get("documents"), list):
        result["documents"] = event_data["documents"]
    if isinstance(event_data.get("rag_refs"), list):
        result["rag_refs"] = event_data["rag_refs"]


def _response_text(response: dict[str, Any] | None) -> str:
    """answer 필드에서 workflow UI에 표시할 문자열을 고른다."""
    if not isinstance(response, dict):
        return ""
    answer = response.get("answer")
    if isinstance(answer, str):
        return answer
    if isinstance(answer, dict):
        display_text = answer.get("display_text")
        if isinstance(display_text, str):
            return display_text
        summary = answer.get("summary")
        if isinstance(summary, list):
            return "\n".join(str(item) for item in summary)
    text = response.get("text")
    return str(text) if isinstance(text, str) else ""


_HANDOFF_REASON_LABELS = {
    "customer_request": "고객이 상담사 연결을 직접 요청",
    "out_of_usecase": "지원 범위 밖 문의",
    "out_of_usecase_partial": "문의 중 일부가 지원 범위 밖",
    "low_confidence_streak": "답변 검증 연속 실패",
    "system_error": "시스템(도구) 오류 누적",
}


def _format_handoff_text(event_data: dict[str, Any]) -> str:
    """handoff 이벤트의 사유·상세·issues를 reasoning 패널용 디버그 텍스트로 만든다."""
    ctx = event_data.get("handoff_context") if isinstance(event_data.get("handoff_context"), dict) else {}
    reason = str(ctx.get("reason") or "unknown")
    label = _HANDOFF_REASON_LABELS.get(reason)
    text = f"[상담사 인계] reason={reason}" + (f" ({label})" if label else "")
    detail = ctx.get("detail")
    if detail:
        text += f"\n트리거: {detail}"
    issues = ctx.get("issues")
    if isinstance(issues, list) and issues:
        text += "\nissues: " + "; ".join(str(i) for i in issues)
    return text


def _format_visible_rationale(event_dict: dict[str, Any]) -> str:
    text = _CJK_RE.sub("", _event_text(event_dict).replace("~", "-"))
    ev = event_dict.get("event")
    if ev == "reasoning_token":
        return (
            f'<span style="color:#9ca3af;font-style:italic;white-space:pre-wrap;">🧠 {text}</span>'
        )
    if ev == "tool_call":
        return f'<span style="color:#34d399;">🔧 {text}</span>'
    if ev == "tool_result":
        return f'<span style="color:#60a5fa;">📋 {text}</span>'
    if ev == "handoff":
        return f'<span style="color:#f87171;font-weight:bold;white-space:pre-wrap;">🤝 {text}</span>'
    return text


def _agent_flow_payload(event: dict[str, Any] | str) -> dict[str, Any]:
    """workflow UI의 agent flow 패널이 읽는 계층형 visible_rationale payload를 만든다."""
    event_dict = {"event": "reasoning_token", "data": event} if isinstance(event, str) else event
    source = str(event_dict.get("source") or _event_source(event_dict))
    stage = str(event_dict.get("stage") or "")
    tool_name = event_dict.get("tool_name")
    content = {
        "visible_rationale": _format_visible_rationale(event_dict),
        "source": source,
        "event": event_dict.get("event"),
        "stage": stage,
        "display_label": _display_label(source, event_dict),
    }
    if tool_name:
        content["tool_name"] = str(tool_name)
    return {
        "nodeLabel": _node_label(source, event_dict),
        "data": {
            "output": {
                "content": json.dumps(
                    content,
                    ensure_ascii=False,
                )
            }
        },
    }


def _event_dict(event_name: str, event_data: Any) -> dict[str, Any]:
    """SSE event/data 쌍을 agent-flow helper가 읽는 dict로 만든다."""
    if isinstance(event_data, dict):
        return {"event": event_name, **event_data}
    return {"event": event_name, "data": event_data}


def _event_text(event: dict[str, Any]) -> str:
    """event data를 표시 가능한 문자열로 정규화한다."""
    return str(event.get("data") or "").strip()


def _event_source(event: dict[str, Any]) -> str:
    """이벤트가 직접 source를 갖지 않을 때 기본 출처를 추론한다."""
    event_name = event.get("event")
    if event_name == "reasoning_token":
        return "llm_reasoning"
    if event_name in {"tool_call", "tool_result"}:
        return "tool"
    return "algorithm"


def _node_label(_source: str, _event: dict[str, Any]) -> str:
    """GenOS workflow의 표시 노드명은 작동 중인 customer bridge와 맞춘다."""
    return os.getenv("GENOS_AGENT_FLOW_NODE_LABEL", "Visible Reasoner")


def _display_label(source: str, event: dict[str, Any]) -> str:
    """단일 workflow node 안에서 실제 이벤트 출처를 구분하기 위한 표시용 label."""
    if event.get("event") == "tool_call":
        return "Tool Call"
    if event.get("event") == "tool_result":
        return "Tool Result"
    if event.get("event") == "handoff":
        return "Handoff"
    if source == "llm_reasoning":
        return "LLM Reasoning"
    if source == "customer_answer":
        return "Answer Token"
    return "Algorithm Step"


def _strip_tool_call_tags(text: str) -> str:
    """응답 텍스트에서 tool_call 태그를 제거한다."""
    return re.sub(r"</?tool_call[^>]*>", "", text).strip()


def _normalize_counselor_info(value: dict[str, Any]) -> dict[str, Any]:
    """상담사 정보 alias를 보존하면서 자주 쓰는 표준 key를 채운다."""
    if not value:
        return {}
    normalized = dict(value)
    employee_id = _first_present(
        value.get("employee_id"),
        value.get("employeeId"),
        value.get("id"),
        value.get("user_id"),
    )
    department = _first_present(value.get("department"), value.get("dept"))
    if employee_id is not None:
        normalized["employee_id"] = employee_id
    if department is not None:
        normalized["department"] = department
    return normalized


def _as_dict(value: Any) -> dict[str, Any]:
    """dict 입력만 통과시키고 나머지는 빈 dict로 바꾼다."""
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    """list 입력만 통과시키고 나머지는 빈 list로 바꾼다."""
    return value if isinstance(value, list) else []


def _first_present(*values: Any, default: Any = None) -> Any:
    """None이 아닌 첫 값을 반환한다."""
    for value in values:
        if value is not None:
            return value
    return default
