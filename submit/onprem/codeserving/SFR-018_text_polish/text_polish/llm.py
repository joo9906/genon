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
# 캐시를 만들 때 쓴 설정. 값이 바뀌면 다시 만든다 (`_resolve_client` 머리말).
_CLIENT_KEY: tuple | None = None

# 설정 부재 사유. **호출부가 이 값으로 분기하므로 문자열을 양쪽에 적지 않는다** —
# 리터럴을 두 곳에 두면 한쪽만 고쳐도 예외 없이 조용히 분기가 죽는다(그 상태에서는
# 배포 설정 문제가 다시 "잠시 후 다시 시도" 로 나간다).
CONFIG_MISSING = "CONFIG_MISSING"

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
    """GenOS Gateway 경로 하나만 사용한다 (10.2절). 시크릿은 환경변수에서만 읽는다.

    **캐시 키를 설정값으로 잡는다** (2026-08-14). 그냥 `if _CLIENT is not None` 로 두면
    **처음 만들 때의 URL·토큰이 프로세스가 죽을 때까지 고정된다** — 이 단위는 원래부터
    설정을 호출 시점에 읽는데(`Config.genos_url()`) 그 의미가 이 경로에서만 사라지고,
    토큰이 회전돼도 옛 값을 계속 쓴다. 설정이 그대로면 같은 객체를 돌려주므로 커넥션
    재사용은 그대로다. (번역 단위 `llm.py` 와 같은 모양이다.)

    설정 부재는 **호출부(`polish_text_async`)가 먼저 걸러 `LlmResult` 로 돌려준다.**
    여기 남은 `RuntimeError` 는 그 가드를 지나온 뒤에만 닿는 방어선이다.
    """
    global _CLIENT, _CLIENT_KEY
    if not Config.genos_url() or not Config.llm_serving_id():
        raise RuntimeError("GENOS_URL / LLM_SERVING_ID 환경변수가 필요합니다.")
    key = (_base_url(), Config.genos_token(), Config.RES_TIMEOUT)
    if _CLIENT is not None and _CLIENT_KEY == key:
        return _CLIENT
    _CLIENT = AsyncOpenAI(base_url=key[0], api_key=key[1], timeout=key[2])
    _CLIENT_KEY = key
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

    if not Config.genos_url() or not Config.llm_serving_id():
        # **이 함수는 예외를 던지지 않는다** (위 Returns 계약). 예전에는 설정 부재만
        # `_resolve_client()` 의 `RuntimeError` 로 빠져나가 `main.py` 의 `except Exception`
        # 최종 방어선까지 올라갔다 — 사용자는 `POLISH_INTERNAL_UNCLASSIFIED` 로 500 을
        # 받았고 안내는 "잠시 후 다시 시도해 주세요" 였다. **몇 번을 다시 눌러도 같은
        # 자리에서 실패하는 배포 설정 문제**인데 일시적 오류로 보였고, 로그의 error_type
        # 도 다른 내부 오류와 구분되지 않아 원인이 어디에도 드러나지 않았다.
        # 3.7절대로 값은 노출하지 않고 사유만 남긴다. 번역·FAQ·006 이 이미 이 모양이다.
        log_warning(
            "Gateway 설정이 없어 LLM 을 호출할 수 없다",
            event="llm_config_missing",
            resource_id="llm_gateway",
            error_type=CONFIG_MISSING,
        )
        return LlmResult(content="", error_type=CONFIG_MISSING)

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
