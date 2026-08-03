"""공용 LLM 호출 런타임.

GenOS 엔지니어 개발가이드 v1.02 반영
- 10.2절: GenOS Gateway OpenAI 호환 경로만 사용 (외부 SDK/키 직접 호출 금지)
- 10.2절: 무한 재시도 금지 → LLM_RETRY_COUNT 상한 내에서만 재시도
- 3.6절: 모든 외부 호출에 timeout 명시
- 3.8절: 실패 사유(error_type)만 로그에 남기고 예외 원문/응답 전문은 남기지 않음
"""

import asyncio
import os
from typing import Any

from openai import AsyncOpenAI

from .logging_utils import log_info, log_warning

GENOS_URL = os.environ.get("GENOS_URL", "").rstrip("/")
LLM_SERVING_ID = os.environ.get("LLM_SERVING_ID", "")
LLM_MODEL_ID = os.environ.get("LLM_MODEL_ID", "")
RES_TIMEOUT = float(os.environ.get("RES_TIMEOUT", "60"))
LLM_RETRY_COUNT = int(os.environ.get("LLM_RETRY_COUNT", "2"))
MODEL_TEMP = float(os.environ.get("MODEL_TEMP", "0.3"))

_CLIENT: AsyncOpenAI | None = None
_LAST_LLM_ERROR = ""


def get_last_llm_error() -> str:
    return _LAST_LLM_ERROR


def _resolve_client() -> AsyncOpenAI:
    """GenOS Gateway 경로 하나만 사용한다 (10.2절). 시크릿은 환경변수에서만 읽는다."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    token = os.environ.get("GENOS_TOKEN", "")
    if not GENOS_URL or not LLM_SERVING_ID or not token:
        raise RuntimeError("GENOS_URL / LLM_SERVING_ID / GENOS_TOKEN 환경변수가 필요합니다.")
    _CLIENT = AsyncOpenAI(
        base_url=f"{GENOS_URL}/rep/serving/{LLM_SERVING_ID}/v1",
        api_key=token,
        timeout=RES_TIMEOUT,
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


async def polish_text_async(system_prompt: str, user_text: str) -> str:
    """글다듬이 LLM 호출. 실패 시 예외를 던지지 않고 빈 문자열을 반환한다.

    호출부(main.run)에서 빈 문자열을 받으면 error_codes의 업스트림 오류로 처리한다.
    """
    global _LAST_LLM_ERROR

    if not user_text.strip():
        return ""

    client = _resolve_client()
    retry_count = max(1, LLM_RETRY_COUNT)  # 상한 있는 재시도만 허용 (10.2절)

    for attempt in range(retry_count):
        try:
            response = await client.chat.completions.create(
                model=LLM_MODEL_ID,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                temperature=MODEL_TEMP,
                timeout=RES_TIMEOUT,
            )
            choice = response.choices[0] if response.choices else None
            message = getattr(choice, "message", None) if choice else None
            content = _extract_content(getattr(message, "content", "") if message else "")
            if not content:
                _LAST_LLM_ERROR = "empty LLM response"
                raise RuntimeError(_LAST_LLM_ERROR)
            return content.strip()
        except Exception as exc:  # noqa: BLE001 - 재시도/폴백 판단을 위한 통합 처리
            _LAST_LLM_ERROR = type(exc).__name__
            if attempt < retry_count - 1:
                log_info(f"[글다듬이 LLM 재시도] {attempt + 1}/{retry_count}")
                await asyncio.sleep(0.3 * (attempt + 1))
            else:
                log_warning(
                    f"[글다듬이 LLM 실패] error_type={type(exc).__name__} "
                    f"{retry_count}회 재시도 후 포기"
                )
                return ""
    return ""
