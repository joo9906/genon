"""공용 LLM 호출 런타임.

GenOS 엔지니어 개발가이드 v1.02 반영
- 10.2절: GenOS Gateway OpenAI 호환 경로만 사용 (외부 SDK/키 직접 호출 금지)
- 10.2절: 무한 재시도 금지 → LLM_RETRY_COUNT 상한 내에서만 재시도
- 3.6절: 모든 외부 호출에 timeout 명시
- 3.8절: 실패 사유(error_type)만 로그에 남기고 예외 원문/응답 전문은 남기지 않음

[변경 사항 — translation_refactored/llm.py 와 동일 패턴으로 정렬]
1. (버그 수정) _LAST_LLM_ERROR 전역 변수 제거.
   전역 오류 상태는 동시 실행 시 마지막 실패가 덮어쓰는 레이스가 있고,
   글다듬이가 향후 문단 병렬 처리로 확장되면 같은 문제를 그대로 만난다.
   → 호출 결과를 LlmResult(content, error_type, is_transport_error)로
   호출자 스코프에 격리한다.
2. (분류 개선) "Timeout" in 문자열 휴리스틱 대신 예외 타입으로
   통신 실패(00020001) / 실행 실패(00020002)를 판별한다.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx
import openai
from openai import AsyncOpenAI

from .config import Config
from .logging_utils import log_info, log_warning

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


def _base_url() -> str:
    """가이드 §H 표준 경로 — `/api/gateway` prefix 를 반드시 지난다.

    prefix 가 빠지면 게이트웨이가 아니라 존재하지 않는 경로를 때려 404 로 죽는다.
    운영 GENOS_URL 이 이미 prefix 를 포함해 주입되는 배포도 있어 중복을 피한다
    (SFR-006 llm.py 와 같은 규칙).
    """
    base = Config.genos_url()
    prefix = "" if base.endswith("/api/gateway") else "/api/gateway"
    return f"{base}{prefix}/rep/serving/{Config.llm_serving_id()}/v1"


def _resolve_client() -> AsyncOpenAI:
    """GenOS Gateway 경로 하나만 사용한다 (10.2절). 시크릿은 환경변수에서만 읽는다."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    if not Config.genos_url() or not Config.llm_serving_id():
        raise RuntimeError("GENOS_URL / LLM_SERVING_ID 환경변수가 필요합니다.")
    _CLIENT = AsyncOpenAI(
        base_url=_base_url(),
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


async def polish_text_async(system_prompt: str, user_text: str) -> LlmResult:
    """글다듬이 LLM 호출. 예외를 밖으로 던지지 않고 LlmResult 로 반환한다.

    호출부(main.run)는 result.ok 가 False 면 is_transport_error 로
    00020001(통신)/00020002(실행) 오류를 구분해 처리한다.
    """
    if not user_text.strip():
        return LlmResult(content="", error_type="EMPTY_INPUT")

    client = _resolve_client()
    retry_count = max(1, Config.LLM_RETRY_COUNT)  # 상한 있는 재시도만 허용 (10.2절)

    last_error_type = ""
    last_is_transport = False
    last_upstream_status = None
    started = time.monotonic()

    for attempt in range(retry_count):
        try:
            response = await client.chat.completions.create(
                model=Config.llm_model_id(),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                temperature=Config.MODEL_TEMP,
                timeout=Config.RES_TIMEOUT,
            )
            choice = response.choices[0] if response.choices else None
            message = getattr(choice, "message", None) if choice else None
            content = _extract_content(getattr(message, "content", "") if message else "")
            if not content:
                raise RuntimeError("EMPTY_LLM_RESPONSE")
            log_info(
                "글다듬이 LLM 호출 성공",
                event="llm_call_succeeded",
                resource_id="llm_gateway",
                item_count=attempt + 1,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return LlmResult(content=content.strip(), error_type="")
        except Exception as exc:  # noqa: BLE001 - 재시도/분류를 위한 통합 처리
            last_error_type = type(exc).__name__
            last_is_transport = isinstance(exc, _TRANSPORT_ERRORS)
            # 응답 본문은 남기지 않고 HTTP 상태코드만 (3.8절)
            last_upstream_status = getattr(
                getattr(exc, "response", None), "status_code", last_upstream_status
            )
            if attempt < retry_count - 1:
                log_info(
                    "글다듬이 LLM 호출 재시도",
                    event="llm_retry",
                    resource_id="llm_gateway",
                    error_type=last_error_type,
                    upstream_status=last_upstream_status,
                    item_count=attempt + 1,
                )
                await asyncio.sleep(0.3 * (attempt + 1))

    log_warning(
        "글다듬이 LLM 호출 실패 — 재시도 상한 도달",
        event="llm_call_failed",
        resource_id="llm_gateway",
        error_type=last_error_type,
        upstream_status=last_upstream_status,
        item_count=retry_count,
        status="transport" if last_is_transport else "execution",
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return LlmResult(content="", error_type=last_error_type, is_transport_error=last_is_transport)
