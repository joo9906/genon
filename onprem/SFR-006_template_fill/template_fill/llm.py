"""공용 LLM 호출 런타임 (SFR-006, 온프렘 전용).

SFR-018 translation_refactored/llm.py 의 LlmResult 패턴을 그대로 따른다 —
전역 오류 상태는 asyncio 동시 실행에서 레이스가 생기므로 호출 결과를
값 객체로 호출자 스코프에 격리한다.

GenOS 엔지니어 개발가이드 v1.02 반영
- 10.2절: GenOS Gateway OpenAI 호환 경로만 사용
    {GENOS_URL}/api/gateway/rep/serving/{LLM_SERVING_ID}/v1/chat/completions
  외부 SDK/별도 키 우회 경로 없음. 무한 재시도 금지.
- D.3절(5.5): 컨테이너 허용 모듈(asyncio, httpx, json, ...)만 사용한다.
  openai SDK 는 온프렘/폐쇄망 이미지에 포함되지 않을 수 있어 httpx 로 직접 호출한다.
- 3.6절: 모든 외부 호출에 timeout 명시.
- 3.8절: 실패 사유(error_type)만 로그에 남기고 예외 원문/응답 전문은 남기지 않음.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Config
from .logging_utils import log_info, log_warning

_CLIENT: httpx.AsyncClient | None = None

# 통신 자체 실패로 분류할 예외 (00020001 계열). 그 외(HTTP 상태 오류 등)는 실행 실패(00020002).
_TRANSPORT_ERRORS = (
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


def _resolve_client() -> httpx.AsyncClient:
    """GenOS Gateway 경로 하나만 사용한다 (10.2절)."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    if not Config.GENOS_URL or not Config.LLM_SERVING_ID:
        raise RuntimeError("GENOS_URL / LLM_SERVING_ID가 설정되지 않았습니다.")
    _CLIENT = httpx.AsyncClient(timeout=httpx.Timeout(Config.RES_TIMEOUT))
    return _CLIENT


def _chat_url() -> str:
    """가이드 10.2 표준 경로.

    ⚠️ 운영 GENOS_URL 이 이미 '/api/gateway' 를 포함하는 배포라면 이 prefix 를 빼야 한다.
    (AUDIT P0 #1 — 배포 환경 GENOS_URL 형태를 먼저 확인할 것.)
    """
    return (
        f"{Config.GENOS_URL}/api/gateway/rep/serving/"
        f"{Config.LLM_SERVING_ID}/v1/chat/completions"
    )


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


async def llm_call_async(system_prompt: str, user_text: str) -> LlmResult:
    """LLM chat completion 호출. 예외를 밖으로 던지지 않고 LlmResult 로 반환한다."""
    if not user_text:
        return LlmResult(content="", error_type="EMPTY_INPUT")

    client = _resolve_client()
    retry_count = max(1, Config.LLM_RETRY_COUNT)  # 상한 있는 재시도만 허용 (10.2절)

    url = _chat_url()
    headers = {"Authorization": f"Bearer {Config.genos_token()}"}
    body = {
        "model": Config.LLM_MODEL_ID,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": Config.MODEL_TEMP,
    }

    last_error_type = ""
    last_is_transport = False

    for attempt in range(retry_count):
        try:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices") or []
            message = choices[0].get("message", {}) if choices else {}
            content = _extract_content(message.get("content", ""))
            if not content:
                raise RuntimeError("EMPTY_LLM_RESPONSE")
            return LlmResult(
                content=content.replace("```json", "").replace("```", "").strip(),
                error_type="",
            )
        except Exception as exc:  # noqa: BLE001 - 재시도/분류를 위한 통합 처리
            last_error_type = type(exc).__name__
            last_is_transport = isinstance(exc, _TRANSPORT_ERRORS)
            if attempt < retry_count - 1:
                log_info(f"[LLM 재시도] {attempt + 1}/{retry_count} ({last_error_type})")
                await asyncio.sleep(0.3 * (attempt + 1))

    log_warning(
        f"[LLM 실패] error_type={last_error_type} "
        f"transport={last_is_transport} {retry_count}회 재시도 후 포기"
    )
    return LlmResult(content="", error_type=last_error_type, is_transport_error=last_is_transport)
