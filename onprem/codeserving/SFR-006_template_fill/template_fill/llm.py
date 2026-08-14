"""공용 LLM 호출 런타임 (SFR-006, 온프렘 전용).

GenOS 엔지니어 개발가이드 v1.02 / GENOS_RULES 반영
- **§H(10.2)**: Gateway 표준 경로만 사용한다.
    {GENOS_URL}/api/gateway/rep/serving/{LLM_SERVING_ID}/v1/chat/completions
  외부 SDK/별도 키 우회 경로 없음. LiteLLM 주소 직접 호출 없음.
- **D.3(5.5)**: 워크플로우 단계는 임의 패키지를 추가할 수 없다. 허용 모듈
  (`asyncio, httpx, json, datetime, re, ...`)만 쓰므로 openai SDK 를 쓰지 않는다.
- **D.2**: 전역 커넥션 금지(컨테이너 부팅 시 1회 생성 → 유휴 커넥션 누수, 이벤트 루프
  교체 시 사용 불가). 가이드 §H 예시대로 **호출마다 AsyncClient 를 열고 닫는다.**
- **셀프체크**: 모든 외부 호출에 timeout 명시, 재시도 상한 있음,
  **4xx 는 재시도에서 제외**(요청 자체가 잘못된 것이라 반복해도 같은 결과).
- **3.8절**: 실패 사유는 error_type/HTTP 상태코드만 남기고 응답 본문·프롬프트는 남기지 않음.

전역 오류 상태를 두지 않는다 — asyncio 동시 실행에서 레이스가 생기므로 호출 결과를
LlmResult 값 객체로 호출자 스코프에 격리한다.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Config
from .logging_utils import log_info, log_warning

# 설정 부재 사유. **호출부(`chat_api`)가 이 값으로 분기하므로** 문자열을 양쪽에 적지
# 않는다 — 리터럴이 두 곳에 있으면 한쪽만 고쳐도 예외 없이 조용히 분기가 죽고, 그
# 상태에서는 배포 설정 문제가 다시 "잠시 후 다시 시도" 로 나간다.
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
    is_transport_error: bool = False  # True면 00020001(통신), False면 00020002(실행)

    @property
    def ok(self) -> bool:
        return bool(self.content)


def _chat_url() -> str:
    """가이드 §H 표준 경로.

    ⚠️ 운영 GENOS_URL 이 이미 '/api/gateway' 를 포함하는 배포라면 중복되지 않게
    아래 prefix 를 조정한다 (AUDIT P0 #1 — 배포 환경 GENOS_URL 형태 확인).
    """
    base = Config.genos_url()
    prefix = "" if base.endswith("/api/gateway") else "/api/gateway"
    return f"{base}{prefix}/rep/serving/{Config.llm_serving_id()}/v1/chat/completions"


def _extract_content(message_content: Any) -> str:
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


def _content_from_payload(payload: Any) -> str:
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
        # 3.7절: 설정 누락은 값을 노출하지 않는 사유로 즉시 실패
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
        "model": Config.llm_model_id(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": Config.MODEL_TEMP,
    }
    retry_count = max(1, Config.LLM_RETRY_COUNT)  # 상한 있는 재시도만 허용

    last_error_type = ""
    last_is_transport = False
    last_status = None
    started = time.monotonic()

    for attempt in range(retry_count):
        retryable = True
        try:
            # 호출마다 클라이언트를 열고 닫는다 (전역 커넥션 금지 — D.2)
            async with httpx.AsyncClient(timeout=httpx.Timeout(Config.RES_TIMEOUT)) as client:
                response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            content = _content_from_payload(response.json())
            if not content:
                raise ValueError("EMPTY_LLM_RESPONSE")

            log_info(
                "LLM 호출 성공",
                event="llm_call_succeeded",
                resource_id="llm_gateway",
                upstream_status=response.status_code,
                item_count=attempt + 1,  # 시도 횟수
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
            # 4xx = 요청이 잘못된 것이므로 재시도하지 않는다 (셀프체크 항목)
            retryable = last_status >= 500
        except Exception as exc:  # noqa: BLE001 - 재시도/분류를 위한 통합 처리
            last_error_type = type(exc).__name__
            last_is_transport = isinstance(exc, _TRANSPORT_ERRORS)

        if not retryable:
            log_warning(
                "LLM 호출 실패 — 4xx 는 재시도하지 않는다",
                event="llm_call_rejected",
                resource_id="llm_gateway",
                error_type=last_error_type,
                upstream_status=last_status,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return LlmResult(content="", error_type=last_error_type, is_transport_error=False)

        if attempt < retry_count - 1:
            log_info(
                "LLM 호출 재시도",
                event="llm_retry",
                resource_id="llm_gateway",
                error_type=last_error_type,
                upstream_status=last_status,
                item_count=attempt + 1,
            )
            await asyncio.sleep(0.3 * (attempt + 1))

    log_warning(
        "LLM 호출 실패 — 재시도 상한 도달",
        event="llm_call_failed",
        resource_id="llm_gateway",
        error_type=last_error_type,
        upstream_status=last_status,
        item_count=retry_count,
        status="transport" if last_is_transport else "execution",
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return LlmResult(content="", error_type=last_error_type, is_transport_error=last_is_transport)
