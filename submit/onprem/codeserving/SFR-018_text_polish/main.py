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

import asyncio
import json
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from text_polish import file_store, txt_output
from text_polish.config import (
    Config,
    DOC_TYPE_PROMPT_NAME_FORMAT,
    TONE_PROMPT_NAME_FORMAT,
)
from text_polish.error_codes import (
    ERR_CONFIG_MISSING,
    ERR_INPUT_EMPTY,
    ERR_INPUT_TOO_LONG,
    ERR_INTERNAL,
    ERR_UPSTREAM_EXECUTION,
    ERR_UPSTREAM_TIMEOUT,
)
# LLM 호출은 `polisher` 가 조각 단위로 한다 (2026-08-29). 라우트는 더 이상
# `polish_text_async` 를 직접 부르지 않는다 — 몇 번 부를지·실패를 어떻게 셀지가
# 라우트와 그쪽에 나뉘어 있으면 전량/부분 실패 판정이 두 곳으로 갈린다.
from text_polish.llm import STREAM_UNSUPPORTED
from text_polish.polisher import polish_document, polish_document_stream
from text_polish.logging_utils import (
    configure_logging,
    log_error,
    log_info,
    log_warning,
)
from text_polish.prompt_loader import PromptRenderError, render as render_prompt
from text_polish import prompt_library
from text_polish.tone_presets import (
    DEFAULT_DOC_TYPE,
    DEFAULT_TONE,
    doc_type_choices,
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
    # 내려받을 파일 이름에 쓴다 (2026-08-28). 결과를 만들 때 파일까지 굳혀 올리므로
    # 제목이 이 요청에 있어야 한다 — 예전에는 `POST /download` 가 따로 받았다.
    title: str = Field("", max_length=200, description="파일명에 쓸 제목")


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
        "endpoints": [
            "/polish", "/policies", "/policies/reload",
            "/prompts", "/prompts/reload", "/download",
        ],
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


def _policies_payload() -> dict:
    """`GET /policies` 와 `POST /policies/reload` 가 **같은 응답**을 낸다.

    조립을 한 곳에 둔다 — 두 벌로 두면 필드를 늘릴 때 한쪽만 고치게 되고, 그러면
    리로드를 부른 화면만 새 필드를 못 받는다(오류 없이 드롭다운 동작만 달라진다).
    실제로 `forced_tone` 을 더할 때 그 자리가 둘이었다.
    """
    return {
        "doc_types": doc_type_choices(),
        "tones": tone_choices(),
        # 아무것도 안 고르고 실행했을 때 백엔드가 쓰는 값 (`resolve_policy` 의 기본).
        # 화면 초기 선택을 이 값으로 맞추면 "안 고르고 실행" 과 결과가 같아진다 —
        # 화면이 자기 기본값을 정하면 그 둘이 갈리고, 사용자에게는 "고르지 않았을 때만
        # 다른 문체가 나온다" 로 보인다.
        "default_doc_type": DEFAULT_DOC_TYPE,
        "default_tone": DEFAULT_TONE,
    }


@app.get("/policies")
def policies() -> dict:
    """문서유형·톤 목록. UI 가 선택지를 그릴 때 쓴다.

    **목록의 출처는 `tone_presets.py` 표 하나다** (2026-09-07). 관리자가 올린 JSON
    정책 문서를 얹던 경로는 걷어냈고, 라이브러리가 덮는 것은 프롬프트 **문장**뿐이다 —
    어느 문장이 어디서 왔는지는 `GET /prompts` 가 이름마다 답한다.

    그래서 이 응답에 `policy` 블록을 싣지 않는다. 출처가 하나뿐이면 그 필드는 언제나
    같은 값이고, **언제나 같은 값인 필드는 읽는 쪽이 "확인했다" 고 믿게 만든다.**

    문서유형 항목은 `forced_tone`·`allowed_tones` 를 함께 낸다 (2026-09-02) — 화면이
    톤 드롭다운을 잠글 근거다. 근거는 `tone_presets.doc_type_choices`.
    """
    return _policies_payload()


@app.post("/policies/reload")
def policies_reload() -> dict:
    """프롬프트 리비전을 **운영 반영한 뒤** 부른다 — `POST /prompts/reload` 의 별칭이다.

    2026-09-07 부터 정책 전용 캐시가 없다(JSON 경로를 걷어냈다). 톤 전용 프롬프트와
    문서유형 지시문은 **프롬프트 캐시 한 벌**에 들어 있으므로 그것을 비운다 — 캐시가
    두 벌이면 한쪽만 부른 뒤 "톤만 옛 문구" 가 되고, 그 상태는 오류로 드러나지 않는다.

    **옛 이름을 남겨 둔다.** 화면·운영 문서가 이 경로를 쥐고 있고, 없애면 404 가
    "리로드했는데 안 바뀐다" 로 보인다.
    """
    prompt_library.reload()
    return _policies_payload()


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


def _tone_prompt_name(tone_code: str) -> str:
    """이 톤에 쓸 프롬프트 이름. 전용 프롬프트가 없으면 `"system"`.

    **라이브러리에 본문이 실제로 있을 때만** 톤 이름을 쓴다. 이름만 보고 고르면
    `system_polite.txt` 파일이 없어 `PromptRenderError` 가 나고, 그러면 톤 프롬프트를
    아직 안 만든 배포에서 **글다듬이가 통째로 죽는다** — 미설정은 정상 경로여야 한다.
    """
    if not tone_code:
        return "system"
    name = TONE_PROMPT_NAME_FORMAT.format(tone=tone_code)
    return name if prompt_library.body_for(name) is not None else "system"


def _doc_type_instruction(doc_type_code: str, policy) -> str:
    """이 문서유형의 추가 지시문. 라이브러리에 있으면 그것이 이긴다 (2026-09-07).

    이름은 `doc_type_<code>` 이고 본문이 곧 지시문이다 — JSON 을 해석하지 않는다.
    **없으면 내장 표의 값**이고, 그것도 비어 있으면 빈 문자열이다.

    **라벨·강제 톤은 여기로 오지 않는다** — 프롬프트 본문은 문장 하나라 담을 수 없다.
    그 둘은 `tone_presets.DOC_TYPE_POLICIES` 가 계속 들고 있다.
    """
    if not doc_type_code:
        return policy.extra_instruction
    body = prompt_library.body_for(
        DOC_TYPE_PROMPT_NAME_FORMAT.format(doc_type=doc_type_code)
    )
    return body if body is not None else policy.extra_instruction


def _doc_type_block(doc_type_code: str, policy) -> str:
    """`system.txt` 의 `{{ doc_type_block }}` 자리에 들어갈 값.

    **지시문이 없으면 빈 문자열, 있으면 개행으로 끝난다** — 그 규약이라야 뒤따르는
    `[톤: …]` 앞 빈 줄이 두 경우 모두 맞는다(`system.txt` 머리말). 예전에는 템플릿의
    `{% if %}` 가 그 절을 빼 줬는데, 2026-09-07 에 jinja 를 걷어내면서 **넣는가 마는가의
    판단이 코드로 왔다.** 로더는 `{{ name }}` 치환만 한다.
    """
    instruction = (_doc_type_instruction(doc_type_code, policy) or "").strip()
    return f"{instruction}\n" if instruction else ""


@app.post("/polish")
async def polish(request: PolishRequest):
    """문서유형·톤 정책에 맞춰 본문을 다듬는다 (비스트리밍 — `/polish/stream` 의 폴백).

    **반환 타입 주석을 붙이지 않는다** — FastAPI 는 `Response` 서브클래스가 아닌 반환
    주석을 `response_model` 로 삼는데, 성공(dict)과 오류(JSONResponse)로 갈리는 라우트에
    Union 주석을 달면 응답 모델을 만들지 못해 **라우트 등록 단계에서 앱이 죽는다.**

    앞단(입력 검증·정책·프롬프트)과 뒷단(오류 매핑·응답 조립)은 `/polish/stream` 과
    **같은 함수**를 지난다 — 두 라우트가 각자 들고 있으면 갈린다.
    """
    prepared, failed = _prepare_polish(request)
    if failed is not None:
        return failed
    source_text, system_prompt, doc_type_key, tone_key, tone_overridden = prepared

    # 문서를 조각으로 나눠 함께 돌린다 (2026-08-29). timeout + 상한 재시도는 llm.py
    # 안에서 조각마다 처리하고, 실패는 조각 단위로 집계돼 `PolishOutcome` 으로 온다.
    try:
        outcome = await polish_document(system_prompt, source_text)
    except Exception as exc:  # noqa: BLE001 - 예상 밖 오류까지 안전하게 흡수
        return _internal_error("polish_internal_error", exc)

    # **전량 실패만 오류다.** 부분 실패는 결과와 함께 건수로 나간다 — 조각 하나 때문에
    # 다듬어진 문서 전체를 못 보게 할 이유가 없다.
    error_code = _outcome_error_code(outcome)
    if error_code is not None:
        return _error_response(error_code)

    return await _polish_payload(
        outcome, request, doc_type_key, tone_key, tone_overridden
    )


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


@app.get("/prompts")
def prompts() -> dict:
    """프롬프트를 **어디서 받았는지** (2026-09-03).

    관리자가 프롬프트 라이브러리에서 문구를 고쳤는데 반영이 안 될 때 답할 자리다. 이 값이
    없으면 "ID 를 안 넣었다"(`configured: false`)와 "넣었는데 못 읽었다"
    (`reason: fetch_failed_404`)가 **똑같이 옛 문구로** 보인다.

    **본문은 담지 않는다** — 담으면 이 경로가 지시문 유출 경로가 된다 (3.8절).
    """
    return {"prompts": prompt_library.status()}


@app.post("/prompts/reload")
def prompts_reload() -> dict:
    """관리자가 프롬프트 리비전을 **운영 반영한 뒤** 부른다.

    **인증을 걸지 않는다** — 이 단위는 관리자 토큰 자체가 없고(`POST /policies/reload`
    도 같다), 여기서만 새로 요구하면 배포가 단위마다 다른 규약을 갖게 된다.
    """
    return {"prompts": prompt_library.reload()}


# ═══════════════════════════════════════════════════════════════════════════
# 스트리밍 라우트 (2026-09-09)
# ═══════════════════════════════════════════════════════════════════════════
# `POST /polish` 는 문서를 **다 다듬은 뒤** 한 번에 준다. 그래서 스텝이 그 결과를 조각내
# 흘려도 사용자가 기다리는 수십 초 동안은 화면이 비어 있다. 이 라우트는 다듬어지는 대로
# SSE 로 흘린다.
#
# ## 입력 검증·정책·프롬프트는 `_prepare_polish` 하나가 한다
#
# 두 라우트가 같은 앞단을 각자 들고 있으면 갈린다 — 상한 판정이나 톤 강제가 한쪽에만
# 반영되는 식이고, 그 어긋남은 "어떤 경로로 불렀는지" 에 따라 결과가 달라지는 형태로만
# 드러난다(직접 업로드 경로가 MCP 를 지나지 않아 뒷문이 남았던 것과 같은 자리다).
#
# ## 프레임 두 종류뿐이다
#
#   {"type": "delta", "text": "..."}   — 흘릴 글
#   {"type": "done",  ...}             — `/polish` 의 응답 본문과 **같은 값**
#   {"type": "error", "error_code": .., "msg": ..}  — 흘리기 시작한 뒤 실패
#
# **흘리기 전에 실패하면 SSE 가 아니라 평범한 JSON 오류**로 낸다. SSE 는 200 으로 시작
# 하므로, 그 뒤에 오류를 실으면 스텝이 상태코드로 하는 판정(`_upstream_kind`)이 통째로
# 무력해진다 — 재시도 가능 여부가 사라진다.
#
# ## 게이트웨이가 스트리밍을 안 받으면 **여기서** 되돌아간다
#
# 폴백을 스텝에 두지 않는다. 스텝이 두 경로를 알게 되면 캔버스에 등록된 스텝 파일을
# 고쳐야 폴백이 바뀌고, 그 파일은 사본 대조 대상이라 넷을 함께 고치게 된다. 서빙 안에서
# 처리하면 **스텝은 SSE 하나만 알면 된다.**
_SSE_MEDIA_TYPE = "text/event-stream"


def _sse(frame: dict) -> str:
    """SSE 프레임 한 줄. `ensure_ascii=False` 라야 한글이 그대로 간다."""
    return f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"


def _prepare_polish(request: PolishRequest):
    """입력 검증 → 정책 확정 → 시스템 프롬프트 렌더.

    Returns:
        `(준비값, None)` 또는 `(None, 오류응답)`. 준비값은
        `(system_prompt, doc_type_key, tone_key, tone_overridden)` 이다.

    **두 라우트가 이 함수만 지난다** (위 머리말). 여기서 하는 판정을 라우트로 옮기면
    경로마다 다른 검증이 걸린다.
    """
    source_text = (request.text or "").strip()
    if not source_text:
        return None, _error_response(ERR_INPUT_EMPTY)
    if len(source_text) > Config.MAX_INPUT_CHARS:
        # 상한 초과를 조용히 자르지 않는다 — 잘린 문서를 다듬어 돌려주면 뒷부분이
        # 통째로 사라진 결과가 정상 응답처럼 나간다.
        return None, _error_response(ERR_INPUT_TOO_LONG)

    try:
        doc_type_key, tone_key, tone_overridden, policy, tone = resolve_policy(
            request.doc_type, request.tone
        )
    except KeyError as exc:
        # 관리자가 톤을 전부 감춘 경우다. 입력 문제가 아니라 정책 문제다.
        return None, _internal_error("policy_key_missing", exc)

    # 문서 원문은 남기지 않는다 — 유형·톤과 정책 강제 여부, 줄 수만 (3.8절)
    log_info(
        "글다듬이 요청 접수",
        event="polish_started",
        resource_id=f"{doc_type_key}/{tone_key}",
        status="tone_forced" if tone_overridden else "tone_as_requested",
        item_count=len(source_text.splitlines()),
    )

    try:
        system_prompt = render_prompt(
            f"{_tone_prompt_name(tone_key)}.txt",
            doc_type_label=policy.label,
            doc_type_block=_doc_type_block(doc_type_key, policy),
            tone_label=tone.label,
            tone_instruction=tone.instruction,
        )
    except PromptRenderError as exc:
        # 이미지에 프롬프트 디렉토리를 안 넣은 **배포 실수**다 — 재시도로 풀리지 않으므로
        # LLM 실패와 다른 event 로 남긴다(운영이 둘을 갈라 볼 수 있어야 한다).
        return None, _internal_error("prompt_render_failed", exc)

    return (source_text, system_prompt, doc_type_key, tone_key, tone_overridden), None


def _outcome_error_code(outcome):
    """전량 실패를 오류 코드로 옮긴다. 성공이면 `None`.

    `/polish` 와 `/polish/stream` 이 같은 표를 보게 하려고 뗐다 — 갈리면 같은 실패가
    경로에 따라 다른 코드로 나가고, 캔버스의 재시도 판정도 달라진다.
    """
    if outcome.ok:
        return None
    # 설정 부재를 먼저 가른다 — **재시도로 풀리지 않는 배포 문제**라 실행 실패와 같은
    # 502/retryable 로 내보내면 캔버스가 무의미한 재시도를 걸고, 로그에서도 LLM 실패와
    # 구분되지 않는다 (`ERR_CONFIG_MISSING` 머리말 참고).
    if outcome.config_missing:
        return ERR_CONFIG_MISSING
    if outcome.is_transport_error:
        return ERR_UPSTREAM_TIMEOUT
    return ERR_UPSTREAM_EXECUTION


async def _polish_payload(outcome, request: PolishRequest, doc_type_key: str,
                          tone_key: str, tone_overridden: bool) -> dict:
    """성공 응답 본문. **결과 txt 를 여기서 굳혀 올린다.**

    두 라우트가 같은 본문을 내야 한다 — 스텝은 한 가지 모양만 읽는다.
    """
    log_info(
        "글다듬이 완료",
        event="polish_done",
        resource_id=f"{doc_type_key}/{tone_key}",
        item_count=len(outcome.text.splitlines()),
        status=f"chunks={outcome.chunk_count},failed={outcome.failed_chunk_count}",
    )
    polished_text = outcome.text
    download_url = await file_store.upload_bytes(
        txt_output.to_bytes(polished_text),
        txt_output.download_filename(txt_output.safe_stem(request.title, "글다듬이결과")),
        txt_output.MEDIA_TYPE,
    )
    return {
        "polished_text": polished_text,
        "download_url": download_url,
        "doc_type": doc_type_key,
        "tone": tone_key,
        "tone_overridden": tone_overridden,
        "chunk_count": outcome.chunk_count,
        "failed_chunk_count": outcome.failed_chunk_count,
    }


@app.post("/polish/stream")
async def polish_stream(request: PolishRequest):
    """다듬어지는 대로 SSE 로 흘리고, 마지막에 `/polish` 와 같은 본문을 준다.

    **반환 타입 주석을 붙이지 않는다** — `/polish` 와 같은 이유다(성공은
    `StreamingResponse`, 오류는 `JSONResponse` 다).
    """
    prepared, failed = _prepare_polish(request)
    if failed is not None:
        return failed
    source_text, system_prompt, doc_type_key, tone_key, tone_overridden = prepared

    # 흘릴 글을 큐에 넣고, 아래 제너레이터가 꺼내 SSE 로 내보낸다. 다듬기와 전송을
    # 큐로 가르는 이유: `polish_document_stream` 은 `on_text` 를 **직렬화해서** 부르는데
    # (조각들이 함께 돈다), 제너레이터 안에서 직접 부를 수는 없다.
    queue: asyncio.Queue = asyncio.Queue()
    _DONE = object()

    async def _on_text(text: str) -> None:
        await queue.put(text)

    async def _work() -> None:
        # **폴백 사실을 따로 든다.** `outcome` 을 비스트리밍 결과로 덮으면 그 객체의
        # `stream_unsupported` 는 거짓이라 "되돌아갔다" 는 사실이 사라진다 — 실제로 그렇게
        # 만들었고 스모크에서 잡혔다. 값을 만들어 놓고 잃는 자리가 이 저장소의 단골이다.
        fell_back = False
        try:
            outcome = await polish_document_stream(system_prompt, source_text, _on_text)
            # **스트리밍을 안 받는 배포면 비스트리밍으로 되돌아간다** (위 머리말).
            # 한 글자도 안 흘렸을 때만 — 흘린 뒤에 다시 하면 화면에 같은 문서가 겹친다.
            if outcome.stream_unsupported and outcome.streamed_chars == 0:
                fell_back = True
                log_warning(
                    "스트리밍을 쓸 수 없어 비스트리밍으로 다듬는다",
                    event="polish_stream_fallback",
                    resource_id=f"{doc_type_key}/{tone_key}",
                    error_type=STREAM_UNSUPPORTED,
                )
                outcome = await polish_document(system_prompt, source_text)
                if outcome.ok:
                    # 폴백 결과는 한 덩어리로 흘린다 — 스텝은 delta 만 알면 된다.
                    await queue.put(outcome.text)
            error_code = _outcome_error_code(outcome)
            if error_code is not None:
                await queue.put({
                    "type": "error",
                    "error_code": error_code.code,
                    "msg": error_code.user_msg,
                })
                return
            payload = await _polish_payload(
                outcome, request, doc_type_key, tone_key, tone_overridden
            )
            payload["type"] = "done"
            # 스트리밍 고유 사실 둘. **화면에 나간 글과 정본이 어긋난 경우**를 조용히
            # 넘기지 않는다 — 스텝이 안내문으로 낸다.
            payload["stream_diverged"] = outcome.stream_diverged
            payload["stream_fallback"] = fell_back
            await queue.put(payload)
        except Exception as exc:  # noqa: BLE001 - 최종 방어선
            # 흘리기가 이미 시작됐을 수 있어 SSE 프레임으로 낸다. 예외 원문은 싣지
            # 않는다 (3.8절) — `_internal_error` 와 같은 규약이고 로그만 남긴다.
            log_error(
                "글다듬이 스트리밍 중 내부 오류",
                event="polish_stream_internal_error",
                error_code=ERR_INTERNAL.code,
                error_type=type(exc).__name__,
            )
            await queue.put({
                "type": "error",
                "error_code": ERR_INTERNAL.code,
                "msg": ERR_INTERNAL.user_msg,
            })
        finally:
            await queue.put(_DONE)

    async def _frames():
        task = asyncio.ensure_future(_work())
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                if isinstance(item, str):
                    yield _sse({"type": "delta", "text": item})
                else:
                    yield _sse(item)
        finally:
            # 클라이언트가 끊으면 제너레이터가 닫힌다. 다듬기를 그대로 두면 그 요청이
            # LLM 을 계속 부르며 살아 있다 — 취소하고 정리한다.
            if not task.done():
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    return StreamingResponse(
        _frames(),
        media_type=_SSE_MEDIA_TYPE,
        headers={
            # 중간 프록시가 모아서 보내면 스트리밍이 사라진다 — 그 상태는 "한방에 나온다"
            # 로만 보이고 오류가 없다.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
