"""공용 LLM 호출 런타임 (SFR-018 FAQ, 온프렘 전용).

가이드 / GENOS_RULES 반영
- **§H(10.2)**: Gateway 표준 경로만 사용한다.
    {GENOS_URL}/api/gateway/rep/serving/{LLM_SERVING_ID}/v1/chat/completions
  경로 조립은 `_chat_url()` 한 곳에서만 한다. f-string 으로 base_url 을 직접 이어붙이면
  `/api/gateway` prefix 를 빠뜨린다 — 018 두 단위가 실제로 그래서 게이트웨이를 지나지
  않고 있었다(2026-08-05 수정).
- **D.3(5.5)**: 워크플로우 단계는 임의 패키지를 추가할 수 없다. 그래서 openai SDK 가
  아니라 `httpx` 로 호출한다 (SFR-006 `llm.py` 와 같은 이유 — 이 패키지도 워크플로우와
  코드 서빙 양쪽에서 쓰인다).
- **D.2**: 전역 커넥션 금지. 호출마다 `AsyncClient` 를 열고 닫는다.
- **셀프체크**: 모든 외부 호출에 timeout 명시, 재시도 상한 있음,
  **4xx 는 재시도에서 제외**(요청 자체가 잘못된 것이라 반복해도 같은 결과).
- **3.8절**: 실패 사유는 error_type / HTTP 상태코드만 남긴다. 응답 본문·프롬프트·
  **액세스 토큰을 로그에 남기지 않는다** (초안 `archive/FAQ.py` 가 GENOS_URL 을
  `print()` 로 찍고 있었다 — 그 경로를 없앴다).

전역 오류 상태를 두지 않는다 — asyncio 동시 실행에서 레이스가 생기므로 호출 결과를
`LlmResult` 값 객체로 호출자 스코프에 격리한다.
"""

import asyncio
import json
import time
from dataclasses import dataclass

import httpx

from .config import Config
from .logging_utils import debug_echo, log_info, log_warning

# 설정 부재 사유. **호출부(`generator._classify_failure`)가 이 값으로 분기하므로**
# 문자열을 양쪽에 적지 않는다 — 리터럴이 두 곳에 있으면 한쪽만 고쳐도 예외 없이
# 조용히 분기가 죽고, 그 상태에서는 배포 설정 문제가 다시 "잠시 후 다시 시도" 로 나간다.
CONFIG_MISSING = "CONFIG_MISSING"

# 통신 자체 실패로 분류할 예외 (00020001 계열).
# 그 외(HTTP 상태 오류, 응답 파싱 실패 등)는 실행 실패(00020002).
_TRANSPORT_ERRORS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    asyncio.TimeoutError,
)


@dataclass(frozen=True)
class LlmResult:
    """단일 LLM 호출 결과. 전역 상태 대신 호출자에게 그대로 반환한다."""

    content: str          # 성공 시 응답 본문, 실패 시 ""
    error_type: str       # 실패 시 예외 클래스명/사유, 성공 시 ""
    is_transport_error: bool = False  # True 면 00020001(통신), False 면 00020002(실행)

    @property
    def ok(self) -> bool:
        return bool(self.content)


def _chat_url() -> str:
    """가이드 §H 표준 경로 — `/api/gateway` prefix 를 반드시 지난다.

    운영 GENOS_URL 이 이미 prefix 를 포함해 주입되는 배포가 있어 중복을 피한다.
    """
    base = Config.genos_url()
    prefix = "" if base.endswith("/api/gateway") else "/api/gateway"
    return f"{base}{prefix}/rep/serving/{Config.llm_serving_id()}/v1/chat/completions"


def _extract_content(message_content) -> str:
    if isinstance(message_content, str):
        return message_content.strip()
    if isinstance(message_content, list):
        parts = [
            str(item.get("text", ""))
            for item in message_content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "".join(parts).strip()
    return ""


def _content_from_payload(payload) -> str:
    """응답 스키마를 검증하며 본문을 꺼낸다 (LLM 응답을 믿지 않는다)."""
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    return _extract_content(message.get("content", ""))


async def llm_call_async(system_prompt: str, user_text: str) -> LlmResult:
    """LLM chat completion 호출. 예외를 밖으로 던지지 않고 LlmResult 로 반환한다."""
    if not user_text or not user_text.strip():
        return LlmResult(content="", error_type="EMPTY_INPUT")
    if not Config.genos_url() or not Config.llm_serving_id():
        # 3.7절: 설정 누락은 값을 노출하지 않는 사유로 즉시 실패.
        # 초안은 `model` 이라는 정의되지 않은 이름을 검사해 NameError 로 죽었다.
        log_warning(
            "Gateway 설정이 없어 LLM 을 호출할 수 없다",
            event="llm_config_missing",
            resource_id="llm_gateway",
            error_type=CONFIG_MISSING,
        )
        return LlmResult(content="", error_type=CONFIG_MISSING)

    url = _chat_url()
    headers = {"Authorization": f"Bearer {Config.genos_token()}"}
    body = {
        # `model` 을 싣지 않는다 (2026-09-07) — 서빙 경로가 이미 모델을 결정한다.
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": Config.MODEL_TEMP,
        "stream": False,
    }
    retry_count = max(1, Config.LLM_RETRY_COUNT)

    last_error_type = ""
    last_is_transport = False
    last_status = None
    started = time.monotonic()

    for attempt in range(retry_count):
        retryable = True
        try:
            # 호출마다 클라이언트를 열고 닫는다 (전역 커넥션 금지 — D.2).
            # connect/read 를 나눠 잡는다 (3.6절): 연결은 빨리 포기하고 생성은 길게 기다린다.
            timeout = httpx.Timeout(
                connect=3.0, read=Config.RES_TIMEOUT, write=5.0, pool=3.0
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            content = _content_from_payload(response.json())
            if not content:
                raise ValueError("EMPTY_LLM_RESPONSE")

            log_info(
                "LLM 호출 성공",
                event="llm_call_succeeded",
                resource_id="llm_faq_generation",
                upstream_status=response.status_code,
                item_count=attempt + 1,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return LlmResult(
                content=content.replace("```json", "").replace("```", "").strip(),
                error_type="",
            )
        except httpx.HTTPStatusError as exc:
            # 디버그 에코 (테스트 기간 한정, 2026-09-07) — **응답 본문은 여기서만 보인다.**
            # 로그에는 3.8절대로 상태코드만 남으므로 게이트웨이가 **왜** 거절했는지가 사라진다:
            # 406·415·422 의 사유는 본문에만 적혀 있다. `GENON_DEBUG=0` 으로 끈다.
            debug_echo(
                "LLM 호출 HTTP 오류",
                event="llm_http_error",
                url=str(exc.request.url),
                status=exc.response.status_code,
                body=exc.response.text,
            )
            last_status = exc.response.status_code
            last_error_type = type(exc).__name__
            last_is_transport = False
            # 4xx = 요청이 잘못된 것이므로 재시도하지 않는다
            retryable = last_status >= 500
        except Exception as exc:  # noqa: BLE001 - 재시도/분류를 위한 통합 처리
            debug_echo("LLM 호출 예외", event="llm_exception", exc=repr(exc))
            last_error_type = type(exc).__name__
            last_is_transport = isinstance(exc, _TRANSPORT_ERRORS)

        if not retryable:
            log_warning(
                "LLM 호출 실패 — 4xx 는 재시도하지 않는다",
                event="llm_call_rejected",
                resource_id="llm_faq_generation",
                error_type=last_error_type,
                upstream_status=last_status,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return LlmResult(content="", error_type=last_error_type, is_transport_error=False)

        if attempt < retry_count - 1:
            log_info(
                "LLM 호출 재시도",
                event="llm_retry",
                resource_id="llm_faq_generation",
                error_type=last_error_type,
                upstream_status=last_status,
                item_count=attempt + 1,
            )
            await asyncio.sleep(0.3 * (attempt + 1))

    log_warning(
        "LLM 호출 실패 — 재시도 상한 도달",
        event="llm_call_failed",
        resource_id="llm_faq_generation",
        error_type=last_error_type,
        upstream_status=last_status,
        item_count=retry_count,
        status="transport" if last_is_transport else "execution",
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return LlmResult(content="", error_type=last_error_type, is_transport_error=last_is_transport)


# ═══════════════════════════════════════════════════════════════════════════
# 스트리밍 호출 — **`httpx` 로 SSE 를 직접 읽는다** (2026-09-11)
# ═══════════════════════════════════════════════════════════════════════════
# 위 `llm_call_async` 는 다 만들어진 뒤 한 번에 준다. FAQ 는 조각을 여럿 돌리므로 그
# 대기가 30~60초이고, 그 동안 화면이 비어 있다.
#
# **`openai` SDK 를 쓰지 않는다.** 게이트웨이는 OpenAI 호환 경로를 내주므로 스트리밍도
# `POST {base}/chat/completions` 에 `"stream": true` 를 실으면 `data: {json}` 줄로
# 온다. SDK 가 들고 있던 층은 그 줄을 잘라 읽는 것 하나뿐이고, 그게 아래
# `_delta_from_frame` + `aiter_lines()` 루프다 — **글다듬이 `polish_stream_async` 와
# 같은 코드**이고 그쪽이 이 함수의 기준이다. SDK 를 쓰면 `model` 을 필수로 싣게 되어
# 2026-09-07 에 없앤 `LLM_MODEL_ID` 가 되살아나고, 사내 mirror 에 패키지 하나가 더
# 있어야 빌드된다.
#
# ## 첫 델타 뒤에는 재시도하지 않는다
#
# 재시도는 **아직 한 글자도 흘리지 않았을 때만** 한다. 델타가 나간 뒤 다시 부르면 그
# 출력이 화면에 **이어붙어** 같은 항목이 두 번 나온다 — 사용자는 그것을 결과물로 읽는다.
#
# ## 게이트웨이가 스트리밍을 받지 않을 수 있다
#
# **폐쇄망에서 `stream: True` 가 되는지 실물로 확인되지 않았다.** 그래서 그 실패를
# `STREAM_UNSUPPORTED` 로 **갈라서** 돌려주고 호출부(`generator.generate_faqs_stream`)
# 가 비스트리밍으로 되돌아간다 — 안 가르면 스트리밍을 받지 않는 배포에서 FAQ 가 통째로
# 죽는다.
STREAM_UNSUPPORTED = "STREAM_UNSUPPORTED"

# SSE 프레임 접두어. 게이트웨이는 OpenAI 호환이라 `data: {json}` 줄로 오고 `[DONE]` 으로
# 끝난다. 주석(`:` 로 시작)과 빈 줄은 버린다.
_SSE_DATA_PREFIX = "data:"
_SSE_DONE = "[DONE]"

# 요청 모양을 거절하는 상태코드. 이 넷은 "스트리밍을 안 받는다" 로 읽고 비스트리밍으로
# 되돌아간다. 5xx 는 일시적 장애일 수 있어 여기 넣지 않는다(재시도 대상이다).
_STREAM_REJECT_STATUS = frozenset({400, 415, 422, 501})


def _delta_from_frame(frame) -> str:
    """SSE 프레임 하나에서 증분 텍스트를 꺼낸다.

    비스트리밍의 `choices[0].message.content` 자리에 스트리밍은 `choices[0].delta.content`
    를 넣는다. **모양이 어긋나면 빈 문자열이다** — 여기서 예외를 올리면 프레임 하나가
    이상하다는 이유로 잘 흐르던 응답이 통째로 실패한다.
    """
    if not isinstance(frame, dict):
        return ""
    choices = frame.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if isinstance(delta, dict):
        text = delta.get("content")
        if isinstance(text, str):
            return text
        # 일부 게이트웨이는 delta 에도 목록 형태를 넣는다 (`_extract_content` 와 같은 모양).
        return _extract_content(text) if text is not None else ""
    # 스트림을 요청했는데 비스트리밍 프레임이 온 배포 — 본문이 통째로 한 프레임에 있다.
    message = first.get("message")
    if isinstance(message, dict):
        return _extract_content(message.get("content", ""))
    return ""


async def faq_stream_async(system_prompt: str, user_text: str, on_delta) -> LlmResult:
    """스트리밍으로 부르고 델타가 올 때마다 `await on_delta(text)` 를 부른다.

    Args:
        system_prompt: 마크다운 구분자 형식을 지시하는 시스템 프롬프트.
        user_text: 조각 본문.
        on_delta: `async def (str) -> None`. **이 함수가 던지는 예외는 삼키지 않는다** —
            소비자 쪽(소켓 끊김 등) 실패를 LLM 실패로 뭉개면 진단이 불가능해진다.
            **직렬화는 호출부 책임이다** — 조각들이 함께 돌므로 여기서 잠그면 조각
            사이 순서를 이 파일이 정하게 된다.

    Returns:
        `LlmResult`. `content` 는 **흘린 델타를 그대로 이은 것**이다. 스트리밍을 받지
        않는 배포에서는 `error_type == STREAM_UNSUPPORTED` 다.

    `llm_call_async` 와 같은 계약을 지킨다: 예외를 밖으로 던지지 않고(단 `on_delta` 의
    예외는 그대로 올린다), 설정 부재는 `CONFIG_MISSING` 으로 즉시 실패한다.
    """
    if not user_text or not user_text.strip():
        return LlmResult(content="", error_type="EMPTY_INPUT")
    if not Config.genos_url() or not Config.llm_serving_id():
        log_warning(
            "Gateway 설정이 없어 LLM 을 호출할 수 없다",
            event="llm_config_missing",
            resource_id="llm_gateway",
            error_type=CONFIG_MISSING,
        )
        return LlmResult(content="", error_type=CONFIG_MISSING)

    url = _chat_url()
    headers = {
        "Authorization": f"Bearer {Config.genos_token()}",
        # 스트리밍 응답을 받겠다고 밝힌다. MCP 406 건과 같은 자리다 — 서버가 본문을 읽기
        # **전에** Accept 를 보는 구현이 있어, 밝히지 않으면 도구에 닿지도 못한다.
        "Accept": "text/event-stream",
    }
    body = {
        # `model` 을 싣지 않는다 (2026-09-07) — 서빙 경로가 이미 모델을 결정한다.
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": Config.MODEL_TEMP,
        "stream": True,
    }
    retry_count = max(1, Config.LLM_RETRY_COUNT)

    last_error_type = ""
    last_is_transport = False
    last_upstream_status = None
    started = time.monotonic()

    for attempt in range(retry_count):
        retryable = True
        emitted = 0          # 이 시도에서 흘린 델타 수 — 0 이 아니면 재시도하지 않는다
        pieces: list = []
        try:
            timeout = httpx.Timeout(
                connect=3.0, read=Config.RES_TIMEOUT, write=5.0, pool=3.0
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, headers=headers, json=body) as response:
                    if response.status_code >= 400:
                        # `stream()` 은 지연 읽기다 — 사유를 보려면 먼저 본문을 읽어야 한다.
                        await response.aread()
                        response.raise_for_status()
                    content_type = str(response.headers.get("content-type", "")).lower()
                    if "text/event-stream" not in content_type:
                        # 200 인데 SSE 가 아니다 = 이 배포는 `stream: True` 를 무시한다.
                        # 통째로 온 JSON 을 버리지 않고 **한 덩어리로 흘려** 결과를 살린다
                        # (여기서 실패로 세우면 잘 만들어진 결과가 사라진다).
                        await response.aread()
                        whole = _content_from_payload(response.json())
                        if not whole:
                            raise RuntimeError("EMPTY_LLM_RESPONSE")
                        debug_echo(
                            "스트림을 요청했는데 SSE 가 아니다 — 한 덩어리로 흘린다",
                            event="llm_stream_not_sse",
                            content_type=content_type,
                        )
                        await on_delta(whole)
                        return LlmResult(content=whole, error_type="")

                    async for raw_line in response.aiter_lines():
                        line = raw_line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith(_SSE_DATA_PREFIX):
                            continue
                        payload_text = line[len(_SSE_DATA_PREFIX):].strip()
                        if payload_text == _SSE_DONE:
                            break
                        try:
                            frame = json.loads(payload_text)
                        except (json.JSONDecodeError, ValueError):
                            # 프레임 하나가 깨진 것으로 응답 전체를 버리지 않는다.
                            continue
                        piece = _delta_from_frame(frame)
                        if not piece:
                            continue
                        pieces.append(piece)
                        emitted += 1
                        await on_delta(piece)

            content = "".join(pieces)
            if not content.strip():
                raise RuntimeError("EMPTY_LLM_RESPONSE")
            log_info(
                "FAQ LLM 스트리밍 성공",
                event="llm_stream_succeeded",
                resource_id="llm_gateway",
                upstream_status=200,
                item_count=emitted,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return LlmResult(content=content, error_type="")
        except httpx.HTTPStatusError as exc:
            debug_echo(
                "LLM 스트리밍 HTTP 오류",
                event="llm_stream_http_error",
                url=str(exc.request.url),
                status=exc.response.status_code,
                body=exc.response.text,
            )
            last_upstream_status = exc.response.status_code
            last_error_type = type(exc).__name__
            last_is_transport = False
            retryable = last_upstream_status >= 500
            if last_upstream_status in _STREAM_REJECT_STATUS:
                # **요청 모양을 거절한 것**이다 = 이 배포는 스트리밍을 받지 않는다.
                # 비스트리밍으로 되돌아갈 수 있게 갈라서 알린다.
                log_warning(
                    "게이트웨이가 스트리밍 요청을 거절했다 — 비스트리밍으로 되돌아간다",
                    event="llm_stream_unsupported",
                    resource_id="llm_gateway",
                    error_type=STREAM_UNSUPPORTED,
                    upstream_status=last_upstream_status,
                )
                return LlmResult(content="", error_type=STREAM_UNSUPPORTED)
        except Exception as exc:  # noqa: BLE001 - 재시도/분류를 위한 통합 처리
            debug_echo("LLM 스트리밍 예외", event="llm_stream_exception", exc=repr(exc))
            last_error_type = type(exc).__name__
            last_is_transport = isinstance(exc, _TRANSPORT_ERRORS)

        if emitted:
            # **이미 흘렸으므로 재시도하지 않는다** (위 머리말). 재시도하면 같은 항목이
            # 화면에 두 번 나온다.
            log_warning(
                "LLM 스트리밍이 흘린 뒤 끊겼다 — 재시도하지 않는다",
                event="llm_stream_broken",
                resource_id="llm_gateway",
                error_type=last_error_type,
                upstream_status=last_upstream_status,
                item_count=emitted,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return LlmResult(
                content="", error_type=last_error_type, is_transport_error=last_is_transport
            )

        if not retryable:
            log_warning(
                "FAQ LLM 스트리밍 실패 — 4xx 는 재시도하지 않는다",
                event="llm_stream_rejected",
                resource_id="llm_gateway",
                error_type=last_error_type,
                upstream_status=last_upstream_status,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return LlmResult(content="", error_type=last_error_type, is_transport_error=False)

        if attempt < retry_count - 1:
            log_info(
                "FAQ LLM 스트리밍 재시도",
                event="llm_stream_retry",
                resource_id="llm_gateway",
                error_type=last_error_type,
                upstream_status=last_upstream_status,
                item_count=attempt + 1,
            )
            await asyncio.sleep(0.3 * (attempt + 1))

    log_warning(
        "FAQ LLM 스트리밍 실패 — 재시도 상한 도달",
        event="llm_stream_failed",
        resource_id="llm_gateway",
        error_type=last_error_type,
        upstream_status=last_upstream_status,
        item_count=retry_count,
        status="transport" if last_is_transport else "execution",
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return LlmResult(content="", error_type=last_error_type, is_transport_error=last_is_transport)
