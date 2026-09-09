"""글다듬이 LLM 호출 런타임.

**2026-09-07 — `openai` SDK 를 걷어내고 `httpx` 로 직접 부른다.**

실환경에서 SDK 때문에 호출이 실패했다. 게이트웨이는 **OpenAI 호환 경로**를 내주므로
SDK 가 하는 일은 `POST {base}/chat/completions` 한 번과 응답 dict 에서 본문을 꺼내는
것뿐이고, 그 둘은 이 파일이 이미 하고 있었다(`_extract_content`). **FAQ·006 두 단위는
처음부터 `httpx` 였다** — 이 변경은 네 단위를 같은 모양으로 맞추는 것이고, 그쪽
(`faq/llm.py`)이 이 파일의 기준이다.

같이 얻은 것 둘:

- **4xx 를 재시도하지 않는다.** SDK 판은 모든 예외를 같은 칸에 넣어 요청 자체가 잘못된
  경우(400·401·404)도 `LLM_RETRY_COUNT` 만큼 두드렸다 — 같은 결과가 나오는 호출을
  반복하면서 사용자 대기시간만 늘고, 로그에서도 일시적 장애와 구분되지 않았다.
- **전역 커넥션이 없어졌다.** SDK 판은 `AsyncOpenAI` 를 모듈 전역에 캐시했다(§D.2 가
  금지하는 모양이고, 그래서 캐시 키를 설정값으로 잡는 방어 코드가 따로 필요했다).
  지금은 호출마다 클라이언트를 열고 닫으므로 **토큰이 회전돼도 다음 호출부터 새 값**이고
  그 방어 코드 자체가 필요 없다.

## 가이드 / GENOS_RULES 반영

- **§H(10.2)**: Gateway 표준 경로만 쓴다.
    `{GENOS_URL}/api/gateway/rep/serving/{LLM_SERVING_ID}/v1/chat/completions`
  경로 조립은 `_chat_url()` **한 곳에서만** 한다. f-string 으로 base 를 직접 이어붙이면
  `/api/gateway` prefix 를 빠뜨린다 — 018 두 단위가 실제로 그래서 게이트웨이를 지나지
  않고 있었다(2026-08-05 수정).
- **§D.2**: 전역 커넥션 금지 — 호출마다 `AsyncClient` 를 열고 닫는다.
- **§3.6**: 모든 외부 호출에 timeout 을 명시하고, connect/read 를 나눠 잡는다 —
  연결은 빨리 포기하고 생성은 길게 기다린다.
- **§10.2**: 재시도는 상한이 있다(`LLM_RETRY_COUNT`).
- **§3.8**: 실패 사유는 `error_type` 과 HTTP 상태코드만 남긴다. 응답 본문·프롬프트·
  **액세스 토큰을 로그에 남기지 않는다.**

전역 오류 상태를 두지 않는다 — asyncio 동시 실행(`polisher` 가 조각을 함께 돈다)에서
레이스가 생기므로 호출 결과를 `LlmResult` 값 객체로 호출자 스코프에 격리한다.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Config
from .logging_utils import debug_echo, log_info, log_warning

# 설정 부재 사유. **호출부가 이 값으로 분기하므로 문자열을 양쪽에 적지 않는다** —
# 리터럴을 두 곳에 두면 한쪽만 고쳐도 예외 없이 조용히 분기가 죽는다(그 상태에서는
# 배포 설정 문제가 다시 "잠시 후 다시 시도" 로 나간다).
CONFIG_MISSING = "CONFIG_MISSING"

# 통신 자체 실패로 분류할 예외 (00020001 계열).
# 그 외(HTTP 상태 오류, 응답 파싱 실패 등)는 실행 실패(00020002).
#
# **`openai.APITimeoutError`·`APIConnectionError` 가 여기 있었다** — SDK 를 걷어내며
# 빠졌다. 그 둘은 내부적으로 `httpx` 예외를 감싼 것이라 아래 목록이 같은 사건을 덮는다.
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
    error_type: str       # 실패 시 예외 클래스명, 성공 시 ""
    is_transport_error: bool = False  # True면 00020001(통신), False면 00020002(실행)

    @property
    def ok(self) -> bool:
        return bool(self.content)


def _chat_url() -> str:
    """가이드 §H 표준 경로 — `/api/gateway` prefix 를 반드시 지난다.

    prefix 가 빠지면 게이트웨이가 아니라 존재하지 않는 경로를 때려 404 로 죽는다.
    운영 `GENOS_URL` 이 이미 prefix 를 포함해 주입되는 배포도 있어 중복을 피한다.

    **SDK 판은 `/v1` 까지만 만들고 뒤를 SDK 가 붙였다.** 지금은 우리가 끝까지 만든다 —
    그래서 이 함수의 반환값이 `.../v1/chat/completions` 로 길어졌다(FAQ·006 과 같다).
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
    """응답 스키마를 검증하며 본문을 꺼낸다 (**LLM 응답을 믿지 않는다**).

    SDK 는 이 검증을 해 주고 없으면 `AttributeError` 로 죽었다 — 직접 부르는 지금은
    모양이 어긋나면 빈 문자열을 내고 호출부가 `EMPTY_LLM_RESPONSE` 로 세운다.
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


async def polish_text_async(system_prompt: str, user_text: str) -> LlmResult:
    """글다듬이 LLM 호출. 예외를 밖으로 던지지 않고 `LlmResult` 로 반환한다.

    호출부(`polisher.polish_document`)는 `result.ok` 가 False 면 `is_transport_error` 로
    00020001(통신)/00020002(실행)을 구분해 처리하고, `CONFIG_MISSING` 은 조각을 더
    두드리지 않고 그 자리에서 끝낸다.
    """
    if not user_text.strip():
        return LlmResult(content="", error_type="EMPTY_INPUT")

    if not Config.genos_url() or not Config.llm_serving_id():
        # **이 함수는 예외를 던지지 않는다** (위 계약). 예전에는 설정 부재만
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

    url = _chat_url()
    headers = {"Authorization": f"Bearer {Config.genos_token()}"}
    body = {
        # `model` 을 싣지 않는다 (2026-09-07) — 서빙 경로가 이미 모델을 결정한다.
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": Config.MODEL_TEMP,
        # 명시한다 — 게이트웨이 기본값이 스트리밍이면 응답 모양이 통째로 달라진다.
        "stream": False,
    }
    retry_count = max(1, Config.LLM_RETRY_COUNT)  # 상한 있는 재시도만 허용 (10.2절)

    last_error_type = ""
    last_is_transport = False
    last_upstream_status = None
    started = time.monotonic()

    for attempt in range(retry_count):
        retryable = True
        try:
            # 호출마다 클라이언트를 열고 닫는다 (전역 커넥션 금지 — §D.2).
            # connect/read 를 나눠 잡는다 (§3.6): 연결은 빨리 포기하고 생성은 길게 기다린다.
            timeout = httpx.Timeout(
                connect=3.0, read=Config.RES_TIMEOUT, write=5.0, pool=3.0
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            content = _content_from_payload(response.json())
            if not content:
                raise RuntimeError("EMPTY_LLM_RESPONSE")
            log_info(
                "글다듬이 LLM 호출 성공",
                event="llm_call_succeeded",
                resource_id="llm_gateway",
                upstream_status=response.status_code,
                item_count=attempt + 1,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return LlmResult(content=content.strip(), error_type="")
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
            # 응답 본문은 남기지 않고 HTTP 상태코드만 (3.8절)
            last_upstream_status = exc.response.status_code
            last_error_type = type(exc).__name__
            last_is_transport = False
            # **4xx 는 재시도하지 않는다** — 요청 자체가 잘못된 것이라 반복해도 같은
            # 결과다. SDK 판은 이 구분이 없어 401·404 도 상한만큼 두드렸다.
            retryable = last_upstream_status >= 500
        except Exception as exc:  # noqa: BLE001 - 재시도/분류를 위한 통합 처리
            debug_echo("LLM 호출 예외", event="llm_exception", exc=repr(exc))
            last_error_type = type(exc).__name__
            last_is_transport = isinstance(exc, _TRANSPORT_ERRORS)

        if not retryable:
            log_warning(
                "글다듬이 LLM 호출 실패 — 4xx 는 재시도하지 않는다",
                event="llm_call_rejected",
                resource_id="llm_gateway",
                error_type=last_error_type,
                upstream_status=last_upstream_status,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return LlmResult(content="", error_type=last_error_type, is_transport_error=False)

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
