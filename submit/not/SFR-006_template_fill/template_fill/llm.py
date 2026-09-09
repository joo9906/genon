"""006 대화 추출 LLM 호출 런타임 — **`openai` SDK 판본** (`not/`).

> **정본(`onprem/`)은 `httpx` 로 직접 부른다.** 이 판본만 SDK 를 쓴다. 기능·응답 모양은
> 같고 **갈리는 것은 전송 계층 하나**다 — 어느 쪽이 실환경에서 뜨는지 확인하려고 둘을
> 나란히 둔 것이지, 이쪽이 더 낫다는 뜻이 아니다.
>
> 정본이 2026-09-07 에 SDK 를 걷어낸 이유는 "실환경에서 SDK 때문에 호출이 실패했다"
> 였다. 그 실패가 SDK 자체 문제였는지 그때의 배선 문제였는지 **가려지지 않았다** —
> 그래서 이 판본은 그때 코드를 되살린 것이 아니라, 정본이 `httpx` 판에서 얻은 것 셋을
> **전부 유지한 채로** SDK 에 얹었다:
>
> 1. **전역 커넥션을 두지 않는다** (§D.2). 옛 SDK 판은 `AsyncOpenAI` 를 모듈 전역에
>    캐시했고, 그래서 토큰이 회전돼도 옛 값을 쓰는 것을 막는 **캐시 키 방어 코드**가
>    따로 필요했다. 여기서는 호출마다 열고 닫으므로 그 방어 자체가 필요 없다.
> 2. **4xx 를 재시도하지 않는다.** 옛 SDK 판은 모든 예외를 같은 칸에 넣어 400·401·404
>    도 상한만큼 두드렸다 — 같은 결과가 나오는 호출을 반복하며 대기시간만 늘고, 로그에서
>    일시적 장애와 구분되지 않았다. `openai.APIStatusError.status_code` 로 가른다.
> 3. **SDK 의 자체 재시도를 끈다** (`max_retries=0`). 켜 두면 우리 재시도와 곱해져
>    한 번의 실패가 최대 `LLM_RETRY_COUNT × (SDK 기본 2회)` 번 두드린다 — 그 추가 호출은
>    **우리 로그에 남지 않는다**(SDK 안에서 일어난다).

## `model` 을 다시 싣는다 — SDK 가 필수로 요구한다

정본은 2026-09-07 에 `LLM_MODEL_ID` 를 없앴다. 게이트웨이의 서빙 경로
(`/rep/serving/{LLM_SERVING_ID}/v1/chat/completions`)가 이미 모델을 결정하므로 본문의
`model` 은 그 위에 얹히는 중복이었다. **그런데 SDK 는 `model` 없이 요청을 만들지
않는다** — 클라이언트 쪽 필수 인자다. 그래서 `Config.llm_model_id()` 를 되살렸고
기본값을 `"default"` 로 뒀다: 게이트웨이가 무시하면 그만이고, 규격대로 검증하는
배포에서는 `LLM_MODEL_ID` 로 채우면 된다. **이 판본과 정본이 갈리는 유일한 설정이다.**

## 가이드 / GENOS_RULES 반영 (정본과 같다)

- **§H(10.2)**: Gateway 표준 경로만 쓴다. `/api/gateway` prefix 조립은 `_base_url()`
  **한 곳에서만** 한다 — f-string 으로 base 를 이어붙이면 prefix 를 빠뜨린다.
  SDK 에는 `/v1` 까지 주고 `/chat/completions` 는 SDK 가 붙인다.
- **§D.2**: 전역 커넥션 금지 — 호출마다 클라이언트를 만든다.
- **§3.6**: 모든 외부 호출에 timeout 명시. connect/read 를 나눠 잡는다 — 연결은 빨리
  포기하고 생성은 길게 기다린다.
- **§10.2**: 재시도는 상한이 있다(`LLM_RETRY_COUNT`).
- **§3.8**: 실패 사유는 `error_type` 과 HTTP 상태코드만 남긴다. 응답 본문·프롬프트·
  **액세스 토큰을 로그에 남기지 않는다.**

전역 오류 상태를 두지 않는다 — 동시 실행에서 레이스가 생기므로 호출 결과를 `LlmResult`
값 객체로 호출자 스코프에 격리한다.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx
import openai
from openai import AsyncOpenAI

from .config import Config
from .logging_utils import debug_echo, log_info, log_warning

# 설정 부재 사유. **호출부가 이 값으로 분기하므로 문자열을 양쪽에 적지 않는다** —
# 리터럴을 두 곳에 두면 한쪽만 고쳐도 예외 없이 조용히 분기가 죽는다(그 상태에서는
# 배포 설정 문제가 다시 "잠시 후 다시 시도" 로 나간다).
CONFIG_MISSING = "CONFIG_MISSING"

# 통신 자체 실패로 분류할 예외 (00020001 계열).
# 그 외(HTTP 상태 오류, 응답 파싱 실패 등)는 실행 실패(00020002).
#
# **SDK 예외를 쓴다.** `openai.APITimeoutError`·`APIConnectionError` 는 내부적으로
# `httpx` 예외를 감싼 것이라 정본의 목록과 같은 사건을 덮는다. `httpx` 쪽도 함께 두는
# 이유는 SDK 를 지나지 않는 자리에서 원본 예외가 그대로 올라올 수 있어서다 — 한쪽만
# 두면 그 경우가 통신 실패인데 실행 실패로 분류된다.
_TRANSPORT_ERRORS = (
    openai.APITimeoutError,
    openai.APIConnectionError,
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


def _base_url() -> str:
    """가이드 §H 표준 경로의 **`/v1` 까지**. 뒤(`/chat/completions`)는 SDK 가 붙인다.

    prefix 가 빠지면 게이트웨이가 아니라 존재하지 않는 경로를 때려 404 로 죽는다.
    운영 `GENOS_URL` 이 이미 prefix 를 포함해 주입되는 배포도 있어 중복을 피한다.
    """
    base = Config.genos_url()
    prefix = "" if base.endswith("/api/gateway") else "/api/gateway"
    return f"{base}{prefix}/rep/serving/{Config.llm_serving_id()}/v1"


def _timeout() -> httpx.Timeout:
    """connect/read 를 나눠 잡는다 (§3.6) — SDK 도 내부는 `httpx` 라 그대로 받는다."""
    return httpx.Timeout(connect=3.0, read=Config.RES_TIMEOUT, write=5.0, pool=3.0)


def _client() -> AsyncOpenAI:
    """**호출마다** 새로 만든다 (§D.2 — 전역 커넥션 금지).

    `max_retries=0` 이 중요하다. SDK 기본값은 2회이고, 그대로 두면 우리 재시도 루프와
    **곱해진다** — 그 추가 호출은 우리 로그에 남지 않아 "왜 이렇게 오래 걸리나" 에
    답할 수 없다.
    """
    return AsyncOpenAI(
        base_url=_base_url(),
        api_key=Config.genos_token(),
        timeout=_timeout(),
        max_retries=0,
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


def _as_dict(response: Any) -> Any:
    """SDK 응답 → dict. `model_dump` 가 없으면(대역 등) 그대로 돌려준다."""
    dump = getattr(response, "model_dump", None)
    return dump() if callable(dump) else response


def _content_from_payload(payload: Any) -> str:
    """응답 스키마를 검증하며 본문을 꺼낸다 (**LLM 응답을 믿지 않는다**).

    SDK 응답 객체를 `_as_dict` 로 편 뒤 정본과 **같은 모양**으로 읽는다. 객체 속성
    (`response.choices[0].message.content`)을 바로 타면 모양이 어긋날 때 `AttributeError`
    나 `IndexError` 로 죽는데, 그건 게이트웨이가 이상한 응답을 준 것이지 우리 버그가
    아니다 — 빈 문자열을 내고 호출부가 `EMPTY_LLM_RESPONSE` 로 세운다.
    """
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    return _extract_content(message.get("content", ""))


def _request_kwargs(system_prompt: str, user_text: str) -> dict:
    """요청 본문. **네 단위가 같은 모양을 보낸다** — 갈리면 한 단위만 다른 요청을 보내고,
    게이트웨이가 그것을 무시하면 아무 일도 일어나지 않는다(정본 `check_unit_endpoints`
    의 사본 대조가 보는 자리다).
    """
    kwargs = {
        # 정본에는 없는 인자다 — SDK 가 필수로 요구한다 (위 머리말).
        "model": Config.llm_model_id(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": Config.MODEL_TEMP,
    }

    return kwargs


def _config_missing() -> LlmResult:
    """설정 부재를 **예외가 아니라 값으로** 돌려준다.

    3.7절대로 값은 노출하지 않고 사유만 남긴다 — 몇 번을 다시 눌러도 같은 자리에서
    실패하는 배포 설정 문제라, 실행 실패와 뭉치면 캔버스가 무의미한 재시도를 걸고
    로그에서도 LLM 실패와 구분되지 않는다.
    """
    log_warning(
        "Gateway 설정이 없어 LLM 을 호출할 수 없다",
        event="llm_config_missing",
        resource_id="llm_gateway",
        error_type=CONFIG_MISSING,
    )
    return LlmResult(content="", error_type=CONFIG_MISSING)


async def _complete(system_prompt: str, user_text: str) -> LlmResult:
    """비스트리밍 호출 + 상한 있는 재시도. 예외를 밖으로 던지지 않는다.

    공개 함수(`llm_call_async`)와 나눠 둔 이유는 세마포어·입력 검증 같은 **호출 규약**이
    단위마다 다르고 전송 규약은 같기 때문이다 — 한 함수에 두면 그 둘이 섞인다.
    """
    kwargs = _request_kwargs(system_prompt, user_text)
    # 명시한다 — 게이트웨이 기본값이 스트리밍이면 응답 모양이 통째로 달라진다.
    kwargs["stream"] = False
    retry_count = max(1, Config.LLM_RETRY_COUNT)  # 상한 있는 재시도만 허용 (10.2절)

    last_error_type = ""
    last_is_transport = False
    last_upstream_status = None
    started = time.monotonic()

    for attempt in range(retry_count):
        retryable = True
        try:
            client = _client()
            try:
                response = await client.chat.completions.create(**kwargs)
            finally:
                await client.close()
            content = _content_from_payload(_as_dict(response))
            if not content:
                raise RuntimeError("EMPTY_LLM_RESPONSE")
            log_info(
                "006 대화 추출 LLM 호출 성공",
                event="llm_call_succeeded",
                resource_id="llm_gateway",
                item_count=attempt + 1,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return LlmResult(content=content.strip(), error_type="")
        except openai.APIStatusError as exc:
            # 디버그 에코 (테스트 기간 한정) — **응답 본문은 여기서만 보인다.** 로그에는
            # 3.8절대로 상태코드만 남으므로 게이트웨이가 **왜** 거절했는지가 사라진다:
            # 406·415·422 의 사유는 본문에만 적혀 있다. `GENON_DEBUG=0` 으로 끈다.
            debug_echo(
                "LLM 호출 HTTP 오류",
                event="llm_http_error",
                url=_base_url(),
                status=exc.status_code,
                body=getattr(getattr(exc, "response", None), "text", ""),
            )
            last_upstream_status = exc.status_code
            last_error_type = type(exc).__name__
            last_is_transport = False
            # **4xx 는 재시도하지 않는다** — 요청 자체가 잘못된 것이라 반복해도 같다.
            retryable = last_upstream_status >= 500
        except Exception as exc:  # noqa: BLE001 - 재시도/분류를 위한 통합 처리
            debug_echo("LLM 호출 예외", event="llm_exception", exc=repr(exc))
            last_error_type = type(exc).__name__
            last_is_transport = isinstance(exc, _TRANSPORT_ERRORS)

        if not retryable:
            log_warning(
                "006 대화 추출 LLM 호출 실패 — 4xx 는 재시도하지 않는다",
                event="llm_call_rejected",
                resource_id="llm_gateway",
                error_type=last_error_type,
                upstream_status=last_upstream_status,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return LlmResult(content="", error_type=last_error_type, is_transport_error=False)

        if attempt < retry_count - 1:
            log_info(
                "006 대화 추출 LLM 호출 재시도",
                event="llm_retry",
                resource_id="llm_gateway",
                error_type=last_error_type,
                upstream_status=last_upstream_status,
                item_count=attempt + 1,
            )
            await asyncio.sleep(0.3 * (attempt + 1))

    log_warning(
        "006 대화 추출 LLM 호출 실패 — 재시도 상한 도달",
        event="llm_call_failed",
        resource_id="llm_gateway",
        error_type=last_error_type,
        upstream_status=last_upstream_status,
        item_count=retry_count,
        status="transport" if last_is_transport else "execution",
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return LlmResult(content="", error_type=last_error_type, is_transport_error=last_is_transport)


async def llm_call_async(system_prompt: str, user_text: str) -> LlmResult:
    """006 대화 추출 LLM 호출. 예외를 밖으로 던지지 않고 `LlmResult` 로 반환한다.

    호출부는 `result.ok` 가 False 면 `is_transport_error` 로 00020001(통신)/
    00020002(실행)을 구분하고, `CONFIG_MISSING` 은 그 자리에서 끝낸다.
    """
    if not user_text.strip():
        return LlmResult(content="", error_type="EMPTY_INPUT")
    if not Config.genos_url() or not Config.llm_serving_id():
        return _config_missing()
    return await _complete(system_prompt, user_text)
