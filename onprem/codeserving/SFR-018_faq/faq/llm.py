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
import time
from dataclasses import dataclass

import httpx

from .config import Config
from .logging_utils import log_info, log_warning

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
    base = Config.GENOS_URL
    prefix = "" if base.endswith("/api/gateway") else "/api/gateway"
    return f"{base}{prefix}/rep/serving/{Config.LLM_SERVING_ID}/v1/chat/completions"


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
    if not Config.GENOS_URL or not Config.LLM_SERVING_ID:
        # 3.7절: 설정 누락은 값을 노출하지 않는 사유로 즉시 실패.
        # 초안은 `model` 이라는 정의되지 않은 이름을 검사해 NameError 로 죽었다.
        log_warning(
            "Gateway 설정이 없어 LLM 을 호출할 수 없다",
            event="llm_config_missing",
            resource_id="llm_gateway",
            error_type="CONFIG_MISSING",
        )
        return LlmResult(content="", error_type="CONFIG_MISSING")

    url = _chat_url()
    headers = {"Authorization": f"Bearer {Config.genos_token()}"}
    body = {
        "model": Config.LLM_MODEL_ID,
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
            last_status = exc.response.status_code
            last_error_type = type(exc).__name__
            last_is_transport = False
            # 4xx = 요청이 잘못된 것이므로 재시도하지 않는다
            retryable = last_status >= 500
        except Exception as exc:  # noqa: BLE001 - 재시도/분류를 위한 통합 처리
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
