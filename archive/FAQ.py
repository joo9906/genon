"""
GenOS 워크플로우 Python 단계 - 업로드 문서(md) 기반 FAQ 5개 생성

동작
1) data['overrideConfig']['vars']['genosUploaded'] 에서 전처리된 markdown을 읽는다.
2) 그 내용만 LLM(GenOS Gateway)에 넣어 FAQ 5개를 생성한다.
3) 생성된 FAQ만 채팅에 토큰 스트리밍으로 노출하고 result로 확정한다.

GenOS 엔지니어 개발가이드 v1.02 반영 사항
- 5장 워크플로우 Python 단계: 함수명은 정확히 run, generator로 event/data yield
- 10.2절 LLM 호출: GenOS Gateway OpenAI 호환 경로만 사용 (외부 SDK 직접 호출 금지)
- 3.6절 timeout 규칙: connect/read 분리, 재시도는 timeout/502/503/504만, 최대 2회
- 3.7절 시크릿은 환경변수로만 관리 (os.environ)
- 3.8절 로깅: print 금지, 문서 원문·LLM 응답 전문 로그 금지, 지정 필드만 기록
- 3.9절 오류: 영역 코드 02(워크플로우) + 공통 오류 코드, 스트리밍 종료 시 error 이벤트
"""

import asyncio
import json
import logging
import os
import time

import httpx

_log = logging.getLogger(__name__)

# 영역 코드 02 = 워크플로우 Python 단계 (3.9.1절)
_ERR_LLM_COMM = "02-00020001"   # LLM 외부 통신 실패 (timeout 등)
_ERR_LLM_FAIL = "02-00020002"   # LLM 실행 실패 응답 (4xx/5xx, 응답 형식 오류)
_ERR_NO_INPUT = "02-00020003"   # 입력(업로드 문서) 없음

_NUM_FAQ = 5
_MAX_CONTEXT_CHARS = 12000      # LLM 입력 한도 보호용 안전 마진
_RETRYABLE_STATUS = {502, 503, 504}


async def run(data: dict):
    # 1) socket.io 세팅 (실시간 스트리밍용)
    try:
        from main_socketio import sio_server
    except ImportError:
        sio_server = None
    sid = data.get('socketIOClientId') if isinstance(data, dict) else None

    async def emit_event(event_name, payload):
        if sio_server and sid:
            await sio_server.emit(event_name, payload, room=sid)
        return {"event": event_name, "data": payload}

    # 2) 입력 처리 (문자열/dict 모두 대응)
    if isinstance(data, str):
        data = json.loads(data)

    config = data.get('overrideConfig') or {}
    variables = config.get('vars') or {}
    docs_val = variables.get('genosUploaded') or ""

    # 업로드 문서가 없으면 error 이벤트로 종료 (빈 답변으로 감추지 않는다)
    if not str(docs_val).strip():
        _log.warning(
            "no uploaded document",
            extra={"event": "workflow_no_input", "error_code": _ERR_NO_INPUT},
        )
        yield await emit_event(
            "error",
            {"error_code": _ERR_NO_INPUT, "msg": "업로드된 문서를 찾을 수 없습니다."},
        )
        return

    # 3) LLM으로 FAQ 생성
    try:
        faqs = await _generate_faqs(str(docs_val))
    except _LLMError as exc:
        _log.error(
            "faq generation failed",
            extra={"event": "workflow_llm_failed", "error_code": exc.error_code},
        )
        yield await emit_event("error", {"error_code": exc.error_code, "msg": exc.msg})
        return

    # 4) FAQ만 사람이 읽기 좋은 형태로 조립
    answer = _format_faqs(faqs)

    # 5) 토큰 단위 스트리밍 (채팅에 실시간으로 찍힘)
    for ch in answer:
        yield await emit_event("token", ch)
        # await asyncio.sleep(0.005)  # 타이핑 효과 원하면 주석 해제

    # 6) 최종 결과 확정 (이게 있어야 답변이 완결됨)
    yield {"event": "result", "data": {"text": answer}}


class _LLMError(Exception):
    def __init__(self, error_code: str, msg: str):
        super().__init__(msg)
        self.error_code = error_code
        self.msg = msg


def _format_faqs(faqs: list) -> str:
    lines = []
    for i, item in enumerate(faqs[:_NUM_FAQ], start=1):
        question = str(item.get("question", "")).strip()
        answer = str(item.get("answer", "")).strip()
        if not question or not answer:
            continue
        lines.append(f"Q{i}. {question}\nA{i}. {answer}")
    return "\n\n".join(lines)


async def _generate_faqs(markdown: str) -> list:
    """genosUploaded(md)만 LLM에 넣어 FAQ 5개를 생성한다 (10.2절 표준 경로)."""
    genos_url = os.environ.get("GENOS_URL", "").rstrip("/")
    print("======================== 현재 제노스 URL은 :", genos_url, "===============================")
    genos_token = os.environ.get("GENOS_TOKEN", "")
    serving_id = os.environ.get("LLM_SERVING_ID", "")
    if not genos_url or not genos_token or not serving_id or not model:
        raise _LLMError(
            _ERR_LLM_FAIL,
            "LLM 설정이 올바르지 않습니다. 관리자에게 문의해 주세요.",
        )

    url = f"{genos_url}/api/gateway/rep/serving/{serving_id}/v1/chat/completions"
    headers = {"Authorization": f"Bearer {genos_token}"}
    context = markdown[:_MAX_CONTEXT_CHARS]

    body = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "당신은 문서를 읽고 핵심 내용을 바탕으로 FAQ를 만드는 어시스턴트입니다. "
                    "반드시 JSON 형식으로만 응답하고 다른 설명은 포함하지 않습니다."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"다음 문서 내용만 참고하여 자주 물어볼 만한 질문과 답변을 정확히 {_NUM_FAQ}개 만들어주세요.\n"
                    "출력은 다음 JSON 스키마를 반드시 따르세요:\n"
                    '{"faqs": [{"question": "...", "answer": "..."}]}\n\n'
                    f"문서 내용:\n{context}"
                ),
            },
        ],
        "stream": False,
        "temperature": 0.3,
    }

    # 3.6절: timeout 분리, 재시도는 timeout/502/503/504만, 최초 호출 포함 최대 2회
    timeout = httpx.Timeout(connect=3.0, read=60.0, write=5.0, pool=3.0)
    max_attempts = 2
    payload = None

    for attempt in range(1, max_attempts + 1):
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=body)
            duration_ms = int((time.monotonic() - start) * 1000)

            if response.status_code in _RETRYABLE_STATUS and attempt < max_attempts:
                _log.warning(
                    "llm upstream retryable status",
                    extra={
                        "event": "workflow_llm_retry",
                        "resource_id": "llm_faq_generation",
                        "error_code": _ERR_LLM_COMM,
                        "upstream_status": response.status_code,
                        "duration_ms": duration_ms,
                    },
                )
                await asyncio.sleep(0.5)
                continue

            response.raise_for_status()
            payload = response.json()
            break

        except httpx.TimeoutException as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            _log.warning(
                "llm request timed out",
                extra={
                    "event": "workflow_llm_timeout",
                    "resource_id": "llm_faq_generation",
                    "error_code": _ERR_LLM_COMM,
                    "error_type": type(exc).__name__,
                    "duration_ms": duration_ms,
                },
            )
            if attempt >= max_attempts:
                raise _LLMError(
                    _ERR_LLM_COMM,
                    "외부 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
                ) from exc
            await asyncio.sleep(0.5)
            continue

        except httpx.HTTPStatusError as exc:
            _log.error(
                "llm returned error status",
                extra={
                    "event": "workflow_llm_error",
                    "resource_id": "llm_faq_generation",
                    "error_code": _ERR_LLM_FAIL,
                    "error_type": type(exc).__name__,
                    "upstream_status": exc.response.status_code,
                },
            )
            raise _LLMError(_ERR_LLM_FAIL, "FAQ 생성에 실패했습니다.") from exc

    if payload is None:
        raise _LLMError(_ERR_LLM_COMM, "FAQ 생성이 반복 실패했습니다.")

    # LLM 응답 전문은 로그에 남기지 않는다 (3.8절)
    try:
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        faqs = parsed["faqs"]
        if not isinstance(faqs, list) or not faqs:
            raise TypeError("faqs must be a non-empty list")
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        _log.error(
            "llm response could not be parsed",
            extra={
                "event": "workflow_llm_parse_error",
                "resource_id": "llm_faq_generation",
                "error_code": _ERR_LLM_FAIL,
                "error_type": type(exc).__name__,
            },
        )
        raise _LLMError(_ERR_LLM_FAIL, "FAQ 응답 형식이 올바르지 않습니다.") from exc

    return faqs
