"""공용 LLM 호출 런타임.

GenOS 엔지니어 개발가이드 v1.02 반영
- 10.2절: GenOS Gateway OpenAI 호환 경로만 사용 (외부 SDK/키 우회 경로 없음)
- 10.2절 금지: 사용자 코드에 횟수 제한 없는 재시도 반복문 금지
  → LLM_RETRY_COUNT로 상한을 두고, timeout/그 외 예외에서만 재시도
- 3.6절: 모든 외부 호출에 timeout 명시
- 3.8절: 문서 원문/LLM 응답 전문은 로그에 남기지 않고, 실패 사유만 기록
"""

import asyncio
from typing import Any, Dict, List

from openai import AsyncOpenAI

from config import Config
from translation_pipeline.common.error_codes import ERR_UPSTREAM_TIMEOUT
from translation_pipeline.common.logging_utils import log_info, log_warning

_CLIENT: AsyncOpenAI | None = None
_LAST_LLM_ERROR = ""


def clear_last_llm_error() -> None:
    global _LAST_LLM_ERROR
    _LAST_LLM_ERROR = ""


def get_last_llm_error() -> str:
    return _LAST_LLM_ERROR


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
        parts = []
        for item in message_content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts).strip()
    return ""


async def llm_call_async(
    sem: asyncio.Semaphore,
    system_prompt: str,
    user_text: str,
) -> str:
    """LLM chat completion 호출. 실패 시 빈 문자열을 반환한다 (예외를 던지지 않음).

    Args:
        sem: 동시성 제어 세마포어.
        system_prompt: 시스템 프롬프트.
        user_text: 사용자 입력 텍스트.

    Returns:
        모델 응답 문자열. 실패 시 빈 문자열.
    """
    global _LAST_LLM_ERROR

    if not user_text:
        return ""

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
                    _LAST_LLM_ERROR = "empty LLM response"
                    raise RuntimeError(_LAST_LLM_ERROR)
                return content.replace("```json", "").replace("```", "").strip()
            except Exception as exc:  # noqa: BLE001 - 재시도/폴백 판단을 위한 통합 처리
                _LAST_LLM_ERROR = type(exc).__name__
                if attempt < retry_count - 1:
                    log_info(f"[LLM 재시도] {attempt + 1}/{retry_count}")
                    await asyncio.sleep(0.3 * (attempt + 1))
                else:
                    log_warning(
                        f"[LLM 실패] error_code={ERR_UPSTREAM_TIMEOUT.code} "
                        f"error_type={type(exc).__name__} {retry_count}회 재시도 후 포기"
                    )
                    return ""
    return ""
