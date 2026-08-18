"""SFR-018 글다듬이 — 코드 서빙(03) 진입점.

**이 단위는 워크플로우(02)에서 코드 서빙(03)으로 바뀐다.** 이전 진입점은
`text_polish/main.py` 의 `run(data)` 였고, 그 역할은
`onprem/workflow/sfr018_polish_0{1,2}.py` 두 스텝으로 옮겨갔다.

여기 남는 것: **LLM 호출과 프롬프트 렌더.** 워크플로우 단계는 pod 기본 이미지 패키지만
쓸 수 있는데 `jinja2` 가 거기 없다 (가이드 11.5.6 / GENOS_RULES §D.3). 프롬프트를 jinja
파일로 관리하는 규약(`onprem/prompt/SFR-018_text_polish/`)을 유지하려면 렌더가 이쪽에
있어야 한다.

**2026-08-12 에 `POST /download` 가 붙었다.** SFR-018 세 기능의 산출물이 txt 로 통일되면서
(hwpx·pdf·xlsx 폐기) 이 단위도 파일을 낸다. 상태는 여전히 없다 — 화면이 들고 있는 본문을
요청으로 받아 인코딩만 해서 돌려준다.

## 여기 없는 것 — 검증 3종

`markdown_guard`·`fact_guard`·`diff_report` 는 **`genon_text_guard` MCP 서빙으로 옮겼다.**
LLM 을 부르지 않는 순수 함수라 워크플로우가 직접 부를 수 있고, 그러면 판정 결과가
캔버스에 드러나 분기를 걸 수 있다.

이 단위는 **다듬기만 한다.** 다듬은 결과가 원문을 훼손했는지는 워크플로우 스텝 2가
MCP 로 확인한다.

## 가이드 6.2 — 저장소 루트의 `main.py`

Python 은 저장소 루트의 `main.py` 가 있으면 그 파일을 먼저 실행한다. 그래서 진입점을
패키지 안이 아니라 여기 둔다 — 006·FAQ 처럼 패키지 안에 두면 시작(Run) 커맨드 등록이
필수가 된다.
"""

import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from text_polish import txt_output
from text_polish.config import Config
from text_polish.error_codes import (
    ERR_CONFIG_MISSING,
    ERR_INPUT_EMPTY,
    ERR_INPUT_TOO_LONG,
    ERR_INTERNAL,
    ERR_UPSTREAM_EXECUTION,
    ERR_UPSTREAM_TIMEOUT,
)
from text_polish.llm import CONFIG_MISSING, polish_text_async
from text_polish.logging_utils import configure_logging, log_error, log_info
from text_polish.prompt_loader import PromptRenderError, render as render_prompt
from text_polish import policy_store
from text_polish.tone_presets import (
    doc_type_choices,
    policy_source,
    resolve_policy,
    tone_choices,
)

# 006·번역·FAQ 세 코드서빙 단위와 같은 규약으로 맞춘다 — 진입점이 한 번 부른다.
# 부르지 않으면 root logger 기본 수준이 WARNING 이라 `log_info` 가 나가지 않는다.
configure_logging(os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="sfr018-text-polish", version="1.0.0")


class PolishRequest(BaseModel):
    text: str = ""
    doc_type: str = ""
    tone: str = ""


class DownloadRequest(BaseModel):
    """txt 내려받기 (2026-08-12 신규 — SFR-018 산출물이 txt 로 통일됐다).

    **다듬은 본문을 요청으로 받는다.** 이 단위는 상태를 갖지 않는다(Redis 를 쓰지 않는
    유일한 코드서빙 단위다). 저장을 새로 붙이면 "화면의 결과와 파일이 다를 수 있는"
    경로가 생기고, 그 저장소가 없다는 것이 이 단위 requirements 의 전제이기도 하다.

    `polished_text` 를 별칭으로 함께 받는다 — `/polish` 응답 필드 이름이 그것이라
    화면이 방금 받은 값을 그대로 되돌려 보낼 수 있어야 한다.
    """

    text: str = Field("", description="내려받을 본문 (또는 polished_text 필드)")
    polished_text: str = Field("", description="text 의 별칭 — /polish 응답 필드 이름")
    title: str = Field("", max_length=200, description="파일명에 쓸 제목")

    def body(self) -> str:
        return self.text or self.polished_text


@app.get("/health")
def health() -> dict:
    """상태 확인 프로그램이 직접 호출한다. **200 고정 응답** (§E.4)."""
    return {"status": "ok"}


# 게이트웨이가 경로 없이 베이스를 때리는 경우가 있다. `""` 만 등록하면 ASGI path 가
# 최소 `/` 라서 어느 경로에도 매칭되지 않는다 — 둘 다 등록한다 (2026-08-11 교훈).
@app.get("/")
@app.get("")
def index() -> dict:
    return {
        "service": "sfr018-text-polish",
        "endpoints": ["/polish", "/policies", "/policies/reload", "/download"],
    }


def _internal_error(event: str, exc: Exception) -> JSONResponse:
    """내부 오류를 **ERROR 로** 남기고 고정 안내문을 돌려준다 (2026-08-14 통일).

    번역 `internal_error_response`·FAQ `internal_error` 와 같은 모양이다. 그전에는 이
    단위만 라우트마다 `log_warning` 으로 인라인 처리했다 — 운영이 `level >= ERROR` 로
    내부 오류를 거르면 **이 단위만 안 보인다.** 같은 사건은 같은 레벨로 남겨야 한다.

    예외 원문은 응답에 싣지 않는다 (3.8절). 사유는 `error_type` 으로 로그에만 남는다.
    """
    log_error(
        "글다듬이 처리 중 내부 오류",
        event=event,
        error_code=ERR_INTERNAL.code,
        error_type=type(exc).__name__,
    )
    return _error_response(ERR_INTERNAL)


@app.get("/policies")
def policies() -> dict:
    """문서유형·톤 목록. UI 가 선택지를 그릴 때 쓴다.

    **내장 목록 + 관리자가 프롬프트 라이브러리에 등록한 항목**이다 (2026-08-18).
    `policy` 에 출처와 사유를 함께 싣는다 — 없으면 "조회 실패" 와 "아직 아무것도
    등록하지 않음" 이 화면에서 똑같이 내장 목록으로 보이고, 관리자는 자기가 넣은 톤이
    왜 안 뜨는지 알 수 없다.
    """
    return {
        "doc_types": doc_type_choices(),
        "tones": tone_choices(),
        "policy": policy_source(),
    }


@app.post("/policies/reload")
def policies_reload() -> dict:
    """관리자가 정책 프롬프트 리비전을 **운영 반영한 뒤** 부른다.

    없어도 캐시 TTL 이 지나면 반영되지만, 그때까지는 화면과 실제가 다르다.
    용어사전 `POST /glossary/reload` 와 같은 규약이다.

    **반환 타입 주석을 붙이되 dict 하나로만 낸다** — 실패해도 오류 응답이 아니라
    `policy.reason` 에 사유가 담긴 200 이다. 관리자가 JSON 을 잘못 써도 글다듬이는
    내장 기본값으로 계속 돌아야 한다.
    """
    policy_store.reload()
    return {
        "doc_types": doc_type_choices(),
        "tones": tone_choices(),
        "policy": policy_source(),
    }


def _error_response(error_code) -> JSONResponse:
    """가이드 3.9.4 응답 형식. `detail` 은 넣지 않는다.

    예외 원문·LLM 응답·문서 원문이 섞일 여지를 아예 두지 않는다 (3.8절) —
    상세 원인은 같은 `error_code` 와 함께 내부 로그에만 남는다.

    **상태코드는 `ErrorCode` 가 들고 있다** (2026-08-13). 그전에는 호출부가 인자로
    넘겨서, 같은 코드가 자리마다 다른 상태로 나갈 수 있었다(실제로 `ERR_INPUT_EMPTY` 가
    400·422 두 곳에서 쓰였다). 번역·FAQ 단위와 같은 규약이다.
    """
    return JSONResponse(
        status_code=error_code.http_status,
        content={"error_code": error_code.code, "msg": error_code.user_msg},
    )


@app.post("/polish")
async def polish(request: PolishRequest):
    """문서유형·톤 정책에 맞춰 본문을 다듬는다.

    **반환 타입 주석을 붙이지 않는다** — FastAPI 는 `Response` 서브클래스가 아닌 반환
    주석을 `response_model` 로 삼는데, 성공(dict)과 오류(JSONResponse)로 갈리는 라우트에
    Union 주석을 달면 응답 모델을 만들지 못해 **라우트 등록 단계에서 앱이 죽는다.**
    """
    source_text = (request.text or "").strip()
    if not source_text:
        return _error_response(ERR_INPUT_EMPTY)
    if len(source_text) > Config.MAX_INPUT_CHARS:
        # 상한 초과를 조용히 자르지 않는다 — 잘린 문서를 다듬어 돌려주면 뒷부분이
        # 통째로 사라진 결과가 정상 응답처럼 나간다.
        return _error_response(ERR_INPUT_TOO_LONG)

    try:
        doc_type_key, tone_key, tone_overridden, policy, tone = resolve_policy(
            request.doc_type, request.tone
        )
    except KeyError as exc:
        # 관리자가 톤을 전부 감춘 경우다. 입력 문제가 아니라 정책 문제다.
        return _internal_error("policy_key_missing", exc)

    # 문서 원문은 남기지 않는다 — 유형·톤과 정책 강제 여부, 줄 수만 (3.8절)
    log_info(
        "글다듬이 요청 접수",
        event="polish_started",
        resource_id=f"{doc_type_key}/{tone_key}",
        status="tone_forced" if tone_overridden else "tone_as_requested",
        item_count=len(source_text.splitlines()),
    )

    # 프롬프트 렌더 실패는 LLM 실패와 **따로** 잡는다 — 전자는 이미지에 프롬프트
    # 디렉토리를 안 넣은 배포 실수라 운영에서 구분돼야 손을 쓸 수 있다.
    try:
        system_prompt = render_prompt(
            "system.j2",
            doc_type_label=policy.label,
            doc_type_instruction=policy.extra_instruction,
            tone_label=tone.label,
            tone_instruction=tone.instruction,
        )
    except PromptRenderError as exc:
        # 이미지에 프롬프트 디렉토리를 안 넣은 **배포 실수**다 — 재시도로 풀리지 않으므로
        # LLM 실패와 다른 event 로 남긴다(운영이 둘을 갈라 볼 수 있어야 한다).
        return _internal_error("prompt_render_failed", exc)

    # timeout + 상한 재시도는 llm.py 안에서 처리하고, 실패는 LlmResult 로 돌아온다.
    try:
        llm_result = await polish_text_async(system_prompt, source_text)
    except Exception as exc:  # noqa: BLE001 - 예상 밖 오류까지 안전하게 흡수
        return _internal_error("polish_internal_error", exc)

    if not llm_result.ok:
        # 설정 부재를 먼저 가른다 — **재시도로 풀리지 않는 배포 문제**라 실행 실패와
        # 같은 502/retryable 로 내보내면 캔버스가 무의미한 재시도를 걸고, 로그에서도
        # LLM 실패와 구분되지 않는다 (`ERR_CONFIG_MISSING` 머리말 참고).
        if llm_result.error_type == CONFIG_MISSING:
            return _error_response(ERR_CONFIG_MISSING)
        # 예외 타입 기반 분류 — 통신 실패는 00020001(504), 실행 실패는 00020002(502).
        # 상태코드는 `ErrorCode` 가 들고 있다 (`_error_response` 머리말 참고).
        if llm_result.is_transport_error:
            return _error_response(ERR_UPSTREAM_TIMEOUT)
        return _error_response(ERR_UPSTREAM_EXECUTION)

    log_info(
        "글다듬이 완료",
        event="polish_done",
        resource_id=f"{doc_type_key}/{tone_key}",
        item_count=len(llm_result.content.splitlines()),
    )

    return {
        "polished_text": llm_result.content,
        "doc_type": doc_type_key,
        "tone": tone_key,
        "tone_overridden": tone_overridden,
    }


@app.post("/download")
def download(request: DownloadRequest):
    """다듬은 본문을 txt 파일로 내려준다 (2026-08-12 신규).

    **본문을 손대지 않는다.** 마크다운 기호를 평문으로 풀지 않는다 — 이 단위가 다루는
    구조는 **원문에서 온 것**이고(`markdown_guard` 가 훼손 여부를 지문으로 대조하는
    바로 그 구조다), 파일로 낼 때 우리가 풀어 버리면 지켜낸 구조를 마지막 단계에서
    깨뜨리는 셈이다.

    **반환 타입 주석을 붙이지 않는다** — 성공(`Response`)과 오류(`JSONResponse`)로 갈리는
    라우트에 Union 주석을 달면 FastAPI 가 응답 모델을 만들지 못해 앱이 기동하지 못한다
    (같은 이유로 `/polish` 에도 없다).
    """
    text = request.body()
    if not text.strip():
        return _error_response(ERR_INPUT_EMPTY)
    if len(text) > Config.MAX_INPUT_CHARS:
        return _error_response(ERR_INPUT_TOO_LONG)

    stem = txt_output.safe_stem(request.title, "글다듬이결과")
    data = txt_output.to_bytes(text)
    log_info(
        "글다듬이 결과 txt 생성",
        event="download_completed",
        item_count=len(text.splitlines()),
        status=f"bytes={len(data)}",
    )
    return Response(
        content=data,
        media_type=txt_output.MEDIA_TYPE,
        headers=txt_output.headers(stem),
    )


if __name__ == "__main__":
    # 가이드 6.4 — `0.0.0.0` + GenOS 가 주입하는 `$PORT`.
    # 가이드 6.2 — 이 블록이 없으면 모듈만 로드되고 서버가 뜨지 않는다.
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
