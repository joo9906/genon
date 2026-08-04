"""공용 LLM 호출 런타임 (리팩토링).

[변경 사항]
1. (버그 수정) _LAST_LLM_ERROR 전역 변수 제거.
   기존 코드는 asyncio.gather로 여러 배치를 동시에 돌릴 때 마지막에 실패한
   코루틴이 전역값을 덮어써서, 어떤 배치가 왜 실패했는지 오염되는 레이스 컨디션이
   있었다. → 호출 결과를 LlmResult(content, error_type)로 반환해 호출자 스코프에
   격리한다.
2. (분류 개선) timeout/연결 실패(00020001)와 실행 실패(00020002)를 예외 타입으로
   판별해 error_type에 담는다. 기존에는 문자열 "Timeout" in ... 휴리스틱이었다.
3. 나머지 원칙 유지: Gateway 경로만 사용(10.2절), timeout 명시(3.6절),
   상한 있는 재시도(10.2절), 예외 원문 미노출(3.8절).
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List

import httpx
import openai
from openai import AsyncOpenAI

from config import Config
from translation_pipeline.common.logging_utils import log_info, log_warning

_CLIENT: AsyncOpenAI | None = None

# 통신 자체 실패로 분류할 예외 (00020001 계열)
_TRANSPORT_ERRORS = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    httpx.TimeoutException,
    httpx.ConnectError,
    asyncio.TimeoutError,
)


@dataclass(frozen=True)
class LlmResult:
    """단일 LLM 호출 결과. 전역 상태 대신 호출자에게 그대로 반환한다."""

    content: str          # 성공 시 응답 본문, 실패 시 ""
    error_type: str       # 실패 시 예외 클래스명, 성공 시 ""
    is_transport_error: bool = False  # True면 00020001(통신), False면 00020002(실행)

    @property
    def ok(self) -> bool:
        return bool(self.content)


def _resolve_client() -> AsyncOpenAI:
    """GenOS Gateway 경로 하나만 사용한다 (10.2절)."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    if not Config.GENOS_URL or not Config.LLM_SERVING_ID:
        raise RuntimeError("GENOS_URL / LLM_SERVING_ID가 설정되지 않았습니다.")
    _CLIENT = AsyncOpenAI(
        base_url=f"{Config.GENOS_URL}/rep/serving/{Config.LLM_SERVING_ID}/v1",
        api_key=Config.genos_token(),
        timeout=Config.RES_TIMEOUT,
    )
    return _CLIENT


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


async def llm_call_async(
    sem: asyncio.Semaphore,
    system_prompt: str,
    user_text: str,
) -> LlmResult:
    """LLM chat completion 호출. 예외를 밖으로 던지지 않고 LlmResult로 반환한다.

    Args:
        sem: 동시성 제어 세마포어.
        system_prompt: 시스템 프롬프트.
        user_text: 사용자 입력 텍스트.

    Returns:
        LlmResult. 실패 시 content=""이고 error_type에 사유 분류가 담긴다.
    """
    if not user_text:
        return LlmResult(content="", error_type="EMPTY_INPUT")

    client = _resolve_client()
    retry_count = max(1, Config.LLM_RETRY_COUNT)  # 상한 있는 재시도만 허용

    kwargs: Dict[str, Any] = {
        "model": Config.LLM_MODEL_ID,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": Config.MODEL_TEMP,
    }
    if Config.MAX_TOKENS > 0:
        kwargs["max_tokens"] = Config.MAX_TOKENS

    last_error_type = ""
    last_is_transport = False
    last_upstream_status = None
    started = time.monotonic()

    async with sem:
        for attempt in range(retry_count):
            try:
                response = await client.chat.completions.create(
                    timeout=Config.RES_TIMEOUT, **kwargs
                )
                choice = response.choices[0] if response.choices else None
                message = getattr(choice, "message", None) if choice else None
                content = _extract_content(getattr(message, "content", "") if message else "")
                if not content:
                    raise RuntimeError("EMPTY_LLM_RESPONSE")
                return LlmResult(
                    content=content.replace("```json", "").replace("```", "").strip(),
                    error_type="",
                )
            except Exception as exc:  # noqa: BLE001 - 재시도/분류를 위한 통합 처리
                last_error_type = type(exc).__name__
                last_is_transport = isinstance(exc, _TRANSPORT_ERRORS)
                # 응답 본문은 남기지 않고 HTTP 상태코드만 (3.8절)
                last_upstream_status = getattr(
                    getattr(exc, "response", None), "status_code", last_upstream_status
                )
                if attempt < retry_count - 1:
                    log_info(
                        "번역 LLM 호출 재시도",
                        event="llm_retry",
                        resource_id="llm_gateway",
                        error_type=last_error_type,
                        upstream_status=last_upstream_status,
                        item_count=attempt + 1,
                    )
                    await asyncio.sleep(0.3 * (attempt + 1))

    log_warning(
        "번역 LLM 호출 실패 — 재시도 상한 도달",
        event="llm_call_failed",
        resource_id="llm_gateway",
        error_type=last_error_type,
        upstream_status=last_upstream_status,
        item_count=retry_count,
        status="transport" if last_is_transport else "execution",
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return LlmResult(content="", error_type=last_error_type, is_transport_error=last_is_transport)
