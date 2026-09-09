"""FAQ 코드 서빙 진입점 (area 03).

엔드포인트
- GET  /health            : 헬스체크 (가이드 필수)
- GET  ""                 : 루트 — 게이트웨이가 경로 없이 베이스를 때리는 경우 대비
- GET  /config            : 관리자 상한·기본 개수·내려받을 수 있는 형식 (UI 가 선택지를 만든다)
- POST /generate          : 마크다운 본문으로 FAQ 생성 (재생성·비대화 경로)
- POST /generate/stream   : **항목마다 흘린다** (SSE). 검증을 통과한 항목만 나간다
- POST /generate/upload   : **hwpx 업로드 직접 파싱** 후 FAQ 생성 (요구사항 §1)
- GET  /faqs              : 세션에 저장된 FAQ 조회
- POST /download          : **txt 내려받기** (2026-08-12 — hwpx/pdf/xlsx 는 걷어냈다)

설계 메모
- **다운로드는 저장된 FAQ 를 내려준다. 다시 생성하지 않는다.** LLM 을 다시 부르면
  화면에서 본 FAQ 와 파일 내용이 달라진다.
- **형식은 txt 하나다** (2026-08-12). 그래서 형식 가용성 판별·`/config` 의 형식 캐시·
  "수단 없음(501)" 분기가 전부 없어졌다 — txt 는 어느 이미지에서도 만들 수 있으므로
  환경에 따라 켜졌다 꺼졌다 하는 형식이 더는 없다. `/config` 의 `formats` 필드는
  **UI 계약이라 남긴다**(값은 항상 `["txt"]`).
- 파일 본문 조립은 `formatting.rows_to_plain_text`, 인코딩·파일명은 `txt_output` 이 맡는다.
- **blocking 작업은 `asyncio.to_thread`** 로 넘긴다 (zip/XML 파싱). 문자열 조립과 utf-8
  인코딩은 blocking 이 아니므로 스레드로 넘기지 않는다 — 넘겨도 되지만 그 자체가
  "무거운 일이 있다"는 잘못된 신호가 된다.
- 오류 응답은 `{error_code, msg}` (3.9.5절), 사용자 노출 문구는 고정 안내문만 (3.8절).
"""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import file_store, prompt_library, txt_output
from .api_contract import (
    DownloadRequest,
    GenerateRequest,
    error_response as _error_response,
    internal_error as _internal_error,
    read_upload_capped as _read_upload_capped,
)
from .config import Config
from .error_codes import (
    ERR_API_ADMIN_FORBIDDEN,
    ERR_API_INPUT,
    ERR_API_INTERNAL,
    ERR_API_NO_GROUNDED,
    ERR_API_CONFIG_UNAVAILABLE,
    ERR_API_PROMPT_UNAVAILABLE,
    ERR_API_SESSION_NOT_FOUND,
    ERR_API_UPSTREAM_EXECUTION,
    ERR_API_UPSTREAM_TIMEOUT,
)
from .formatting import _flat as _flat_evidence
from .formatting import rows_to_plain_text, to_export_rows
from .formatting import to_markdown as faq_markdown
from .generator import (
    FAILURE_CONFIG,
    FAILURE_NO_GROUNDED,
    FAILURE_PROMPT,
    FAILURE_STREAM_UNSUPPORTED,
    FAILURE_TRANSPORT,
    FRAME_DELTA,
    FRAME_ITEM_CLOSE,
    FRAME_ITEM_OPEN,
    generate_faqs,
    generate_faqs_stream,
    resolve_max_count,
)
from .hwpx_text import HwpxParseError, to_markdown as hwpx_to_markdown
from .logging_utils import configure_logging, log_info, log_warning
from .session_store import SessionStoreError, load_faqs, save_faqs

configure_logging(os.getenv("LOG_LEVEL", "INFO"))

# 내려받을 수 있는 형식. **UI 계약을 유지하려고 목록으로 둔다** — 값은 하나뿐이지만
# `/config`·`/faqs` 가 `formats` 를 배열로 내려주고 있어서, 스칼라로 바꾸면 화면 코드가
# 같이 바뀌어야 한다. 형식을 늘릴 계획은 없다(요구 변경: txt 로 통일).
_FORMATS = [txt_output.EXTENSION]


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """기동 로그 + 설정 부재 경고.

    `@app.on_event("startup")` 은 deprecated 라 `lifespan` 으로 옮겼다 (2026-08-11).
    requirements 에 FastAPI 상한이 없어 상류가 훅을 제거하면 **import 단계에서 죽는다** —
    기동 실패는 로그도 남지 않으므로 미리 옮겨 둔다.

    형식 가용성 판별은 없어졌다 (2026-08-12, txt 통일). 예전에는 여기서 openpyxl·
    weasyprint·hwpx 템플릿을 확인해 캐시에 담았고, 그 결과가 "왜 hwpx 버튼이 없나" 를
    답하는 유일한 기록이었다.
    """
    log_info(
        "FAQ 서비스 기동",
        event="service_started",
        item_count=len(_FORMATS),
        status=",".join(_FORMATS),
    )
    if not Config.ADMIN_TOKEN:
        log_warning(
            "FAQ_ADMIN_TOKEN 미설정 — 관리자 설정 조회가 인증 없이 열려 있다",
            event="admin_token_missing",
            resource_id="faq_admin",
            status="unprotected",
        )
    yield


app = FastAPI(title="faq-service", lifespan=_lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/")
@app.get("")
async def root() -> dict:
    """게이트웨이가 서빙 베이스를 경로 없이 때리는 배포가 있다 (운영 app.py 대조 결과).

    **`""` 와 `"/"` 를 둘 다 등록해야 한다** (2026-08-11 수정) — `@app.get("")` 만으로는
    아무 경로에도 닿지 않는다. 근거는 006 `main.py` 의 같은 라우트 참고.
    """
    return {"service": "faq-service", "status": "ok"}


@app.get("/config")
async def service_config() -> dict:
    """UI 가 선택지를 만들 때 쓰는 값.

    `max_count` 는 요구사항 §4 의 관리자 상한이고 **문서 하나에서 만들 총 개수**
    기준이다 (2026-09-03 요구 확정). 화면은 0~max_count 만 고르게 한다.

    **옛 `total_max_count` 는 없앴다.** 사용자 선택이 곧 총 개수라 "구간당 개수 ↔
    총량" 두 값을 화면이 설명할 일이 없어졌다. 남은 상한(`FAQ_MAX_CHUNK_CALLS`)은
    개수가 아니라 **호출 수**라 화면이 고를 값이 아니다 — 그 상한 때문에 일부 구간만
    태운 사실은 결과의 `coverage_capped` 와 안내문이 말한다.
    """
    return {
        "max_count": resolve_max_count(),
        "default_count": Config.DEFAULT_FAQ_COUNT,
        "formats": list(_FORMATS),
        "evidence_required": Config.EVIDENCE_REJECT,
    }


# 생성 실패 분류(`generator.FAILURE_*`) → HTTP 오류 코드.
#
# **다섯 갈래를 갈라 두는 것이 계약이다** (2026-08-13 넷 → 2026-08-14 설정 부재 추가).
# 사용자가 할 일이 저마다 다르기 때문이다:
#   - 통신 실패      → 잠시 후 다시 (504, 재시도 가능)
#   - 근거 미확보    → 이 문서로는 안 나온다 (422, 스텝이 이 상태코드로 분기한다)
#   - 프롬프트 부재  → **배포 구성 문제**라 재시도가 무의미하다 (500, 재시도 불가)
#   - 설정 부재      → 같은 배포 구성 문제 (500, 재시도 불가). `is_transport_error` 가
#                      False 라는 이유만으로 실행 실패에 뭉쳐 502 로 나가고 있었다.
#   - 그 외 실행 실패 → 잠시 후 다시 (502, 재시도 가능)
# 표에 없는 값은 실행 실패로 떨어진다 — 새 분류를 추가하고 여기 안 적어도 조용히
# 성공으로 넘어가지는 않는다.
_FAILURE_ERRORS = {
    FAILURE_TRANSPORT: ERR_API_UPSTREAM_TIMEOUT,
    FAILURE_NO_GROUNDED: ERR_API_NO_GROUNDED,
    FAILURE_PROMPT: ERR_API_PROMPT_UNAVAILABLE,
    FAILURE_CONFIG: ERR_API_CONFIG_UNAVAILABLE,
}


async def _generate_and_store(source: str, count, session_id: str, title: str):
    """생성 → (성공 시) 세션 저장. 응답 payload 또는 오류 응답을 돌려준다."""
    result = await generate_faqs(source, count)
    if not result.ok:
        return _error_response(_FAILURE_ERRORS.get(result.failure, ERR_API_UPSTREAM_EXECUTION))
    return await _store_and_payload(result, session_id, title)


async def _store_and_payload(result, session_id: str, title: str) -> dict:
    """채택된 결과를 **payload 로 조립하고 세션에 저장한다.**

    **스트리밍·비스트리밍이 같은 함수를 쓴다** (2026-09-09). 각자 조립하게 두면
    `markdown`·`download_url`·`download_ready`·세션 저장 넷 중 하나가 한쪽에만 붙고,
    그 어긋남은 오류가 아니라 **화면에서만** 드러난다(다운로드 버튼이 한 경로에서만
    켜지는 식이다). 이 저장소가 여러 번 밟은 형태다.

    `result.ok` 판정은 **호출부가** 한다 — 스트리밍은 실패를 SSE 프레임으로 내고
    비스트리밍은 상태코드로 내므로, 그 갈림을 이 안에 넣으면 반환형이 둘이 된다.
    """
    payload = result.as_payload()
    markdown = faq_markdown(result.items)
    payload["markdown"] = markdown
    payload["download_ready"] = False
    # 채택분을 **여기서 txt 로 굳혀 올린다** (2026-08-28). 링크가 있으면 화면은
    # 세션을 거치지 않고 바로 받는다. 올리지 못했으면 `None` 이고, 그때는 아래
    # 세션 저장분을 `POST /download` 로 받는 옛 경로가 그대로 폴백이 된다 —
    # **폐쇄망에서 CDN 업로드가 되는지 아직 실물로 확인되지 않았다.**
    payload["download_url"] = await file_store.upload_bytes(
        txt_output.to_bytes(markdown),
        txt_output.download_filename(txt_output.safe_stem(title, "FAQ")),
        txt_output.MEDIA_TYPE,
    ) or None

    if session_id:
        try:
            await save_faqs(session_id, to_export_rows(result.items), title=title)
            payload["download_ready"] = True
        except SessionStoreError:
            # 생성은 성공했으므로 결과는 돌려준다. 다운로드가 안 될 수 있다는 사실만 알린다.
            log_warning(
                "FAQ 세션 저장 실패 — 결과는 반환하되 다운로드 불가",
                event="session_save_failed_on_generate",
                resource_id="redis",
            )
    return payload


@app.post("/generate")
async def generate(body: GenerateRequest):
    """마크다운 본문으로 FAQ 를 만든다 (재생성·비대화 경로)."""
    started = time.monotonic()
    if len(body.markdown) > Config.MAX_CONTEXT_CHARS * 4:
        # 컨텍스트 상한은 generator 가 자르지만, 그 전에 터무니없이 큰 본문을 받아
        # 메모리에 들고 있지는 않는다
        return _error_response(ERR_API_INPUT, "문서가 너무 깁니다. 나누어 요청해 주세요.")
    try:
        payload = await _generate_and_store(
            body.markdown, body.count or Config.DEFAULT_FAQ_COUNT, body.session_id, body.title
        )
    except Exception as exc:  # noqa: BLE001 - 최종 방어선
        return _internal_error("faq_generate_internal_error", exc)
    if isinstance(payload, JSONResponse):
        return payload
    log_info(
        "FAQ 생성 완료(API)",
        event="api_generate_completed",
        item_count=payload["count"],
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return payload


# ═══════════════════════════════════════════════════════════════════════════
# 항목 단위 스트리밍 — `POST /generate/stream`
# ═══════════════════════════════════════════════════════════════════════════
# **라우트 이름이 `/faq/stream` 이 아니다.** 이 단위의 생성 라우트가 `/generate` ·
# `/generate/upload` 라 거기에 붙였다 — 이름을 따로 두면 화면이 "생성 계열" 을 두 군데서
# 찾게 된다.
#
# 프레임은 넷이다. 세 개는 `generator` 가 만들고(`item_open` · `delta` · `item_close`)
# 마지막 `done` 만 이 라우트가 만든다:
#
#   data: {"type":"item_open","index":0,"question":"…"}      ← 검증 통과. 화면에 자리를 연다
#   data: {"type":"delta","index":0,"text":"…"}               ← 그 자리의 답변 토큰
#   data: {"type":"item_close","index":0,"question":…,"answer":…,"evidence":…}
#   data: {"type":"done", …비스트리밍 `/generate` 와 같은 payload…}
#
# **`done` 의 payload 는 `/generate` 와 같은 조립 함수를 지난다**(`_store_and_payload`).
# 화면이 두 경로에서 다른 모양을 받으면 스트리밍만 쓰는 코드와 폴백만 쓰는 코드가
# 갈린다.
_SSE_MEDIA_TYPE = "text/event-stream"


def _display_text(frame: dict) -> str:
    """프레임 하나가 **화면에 더하는 글**. 이어 붙이면 `done` 의 `markdown` 과 같다.

    ## 왜 서빙이 붙이나 (스텝이 조립하지 않는다)

    캔버스 스텝은 이 글을 그대로 흘리기만 한다. 스텝이 `item_open` 을 받아 제목 줄을
    직접 만들면 **FAQ 화면 형식이 워크플로우에도 한 벌 생기고**, 형식을 고칠 때 한쪽만
    고쳐진다 — 그러면 스트리밍으로 본 화면과 최종 결과가 달라지는데 그 어긋남은 오류가
    아니라 **화면에서만** 드러난다.

    ## 형식의 정본은 `formatting._render` 다

    여기는 그것을 조각으로 낸 것이라 **두 곳에 형식이 있다.** 갈리지 않는 근거는 코드가
    한 곳이라는 것이 아니라 **등식**이다 — 흘린 것을 이어 붙이면 `markdown` 과 같아야
    하고, `check_not_units` 가 그 등식을 본다. 형식을 고치면 그 판정이 잡는다.
    """
    kind = frame.get("type")
    if kind == FRAME_ITEM_OPEN:
        index = int(frame.get("index") or 0)
        # 항목 사이 빈 줄은 **여는 쪽**이 낸다 (`_render` 가 블록을 이어 붙이는 자리와
        # 같다). 닫는 쪽이 내면 마지막 항목 뒤에 빈 줄이 남는다.
        lead = "" if index == 0 else "\n\n"
        return f"{lead}**Q{index + 1}. {frame.get('question') or ''}**\n\n"
    if kind == FRAME_DELTA:
        return str(frame.get("text") or "")
    if kind == FRAME_ITEM_CLOSE:
        return f"\n\n> 근거: {_flat_evidence(str(frame.get('evidence') or ''))}"
    return ""


def _sse(frame: dict) -> str:
    """SSE 프레임 한 줄. `ensure_ascii=False` 라야 한글이 그대로 간다."""
    return f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"


@app.post("/generate/stream")
async def generate_stream(body: GenerateRequest):
    """FAQ 를 **항목마다 흘린다** (SSE).

    **반환 타입 주석을 붙이지 않는다** — 성공은 `StreamingResponse`, 흘리기 전 실패는
    `JSONResponse` 다. Union 을 적으면 FastAPI 가 그것을 `response_model` 로 삼아
    **라우트 등록 단계에서 앱이 죽는다**(공통 규약).

    ## 흘리기 전 실패는 SSE 가 아니라 평범한 오류다

    SSE 는 200 으로 시작하므로, 한 글자도 흘리기 전에 실패한 것까지 SSE 로 내면 호출부가
    상태코드로 성공/실패를 가릴 수 없다. 입력 상한은 여기서 걸린다.

    ## 기각될 항목은 화면에 나타나지 않는다

    근거 대조·중복 판정을 **접두어 연산**으로 하므로(`generator` 의 스트리밍 절) 통과한
    항목만 프레임이 된다. "답이 나왔다가 사라진다" 를 만들지 않는 것이 이 설계의 요점이다.
    """
    started = time.monotonic()
    if len(body.markdown) > Config.MAX_CONTEXT_CHARS * 4:
        return _error_response(ERR_API_INPUT, "문서가 너무 깁니다. 나누어 요청해 주세요.")

    count = body.count or Config.DEFAULT_FAQ_COUNT
    # 프레임을 큐로 넘긴다. 생성기는 `on_frame` 을 **직렬화해서** 부르지만(조각들이 함께
    # 돈다) 그 호출을 제너레이터 안에서 직접 할 수는 없다 — 번역 스트리밍과 같은 구조다.
    queue: asyncio.Queue = asyncio.Queue()
    _DONE = object()

    async def _on_frame(frame: dict) -> None:
        # 화면 조각을 프레임에 실어 보낸다 — 받는 쪽(캔버스 스텝)은 `text` 를 흘리기만
        # 하면 되고, 프레임 종류를 알 필요가 없다.
        text = _display_text(frame)
        await queue.put({**frame, "text": text} if text else frame)

    async def _work() -> None:
        fell_back = False
        try:
            result = await generate_faqs_stream(
                body.markdown, count, on_frame=_on_frame
            )
            # **스트리밍을 안 받는 배포면 비스트리밍으로 되돌아간다.** 그때는 한 항목도
            # 흘리지 않았으므로(생성기가 `FAILURE_STREAM_UNSUPPORTED` 를 그 조건에서만
            # 낸다) 겹쳐 보일 일이 없다.
            if result.failure == FAILURE_STREAM_UNSUPPORTED:
                fell_back = True
                log_warning(
                    "스트리밍을 쓸 수 없어 비스트리밍으로 FAQ 를 만든다",
                    event="faq_stream_fallback",
                    resource_id="llm_gateway",
                    error_type=result.failure_type,
                )
                result = await generate_faqs(body.markdown, count)
                if result.ok:
                    # 폴백 결과도 **같은 프레임으로** 흘린다 — 화면은 SSE 하나만 알면
                    # 된다. 되돌아간 사실은 `done` 의 `stream_fallback` 이 말한다.
                    for index, item in enumerate(result.items):
                        await queue.put(
                            {
                                "type": FRAME_ITEM_OPEN,
                                "index": index,
                                "question": item.question,
                            }
                        )
                        await queue.put(
                            {"type": FRAME_DELTA, "index": index, "text": item.answer}
                        )
                        await queue.put(
                            {
                                "type": FRAME_ITEM_CLOSE,
                                "index": index,
                                "question": item.question,
                                "answer": item.answer,
                                "evidence": item.evidence,
                            }
                        )

            if not result.ok:
                # 실패 분류는 비스트리밍과 **같은 표**를 쓴다. 상태코드로는 낼 수 없으므로
                # (이미 200 이다) 코드와 고정 안내문을 프레임에 담는다.
                error = _FAILURE_ERRORS.get(result.failure, ERR_API_UPSTREAM_EXECUTION)
                log_warning(
                    "FAQ 스트리밍 실패",
                    event="faq_stream_failed",
                    error_type=result.failure_type or result.failure,
                    status=error.code,
                )
                await queue.put(
                    {"type": "error", "error_code": error.code, "msg": error.user_msg}
                )
                return

            payload = await _store_and_payload(result, body.session_id, body.title)
            payload["type"] = "done"
            payload["stream_fallback"] = fell_back
            log_info(
                "FAQ 스트리밍 완료(API)",
                event="api_generate_stream_completed",
                item_count=payload["count"],
                status=f"fallback={int(fell_back)}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            await queue.put(payload)
        except Exception as exc:  # noqa: BLE001 - 최종 방어선
            # 흘리기가 이미 시작됐을 수 있어 SSE 프레임으로 낸다. 예외 원문은 싣지
            # 않는다 (3.8절) — 로그만 남긴다.
            log_warning(
                "FAQ 스트리밍 중 내부 오류",
                event="faq_stream_internal_error",
                error_type=type(exc).__name__,
            )
            await queue.put(
                {
                    "type": "error",
                    "error_code": ERR_API_INTERNAL.code,
                    "msg": ERR_API_INTERNAL.user_msg,
                }
            )
        finally:
            await queue.put(_DONE)

    async def _frames():
        task = asyncio.ensure_future(_work())
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                yield _sse(item)
        finally:
            # 클라이언트가 끊으면 제너레이터가 닫힌다. 생성을 그대로 두면 그 요청이
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


@app.post("/generate/upload")
async def generate_upload(
    document: UploadFile = File(..., description="FAQ 를 만들 hwpx 파일"),
    count: int = Form(0),
    session_id: str = Form(""),
    title: str = Form(""),
):
    """업로드한 hwpx 를 **직접 파싱**해 FAQ 를 만든다 (요구사항 §1).

    pdf·docx 는 전처리기가 마크다운으로 바꿔 주므로 `/generate` 로 보내면 된다.
    hwpx 만 여기서 직접 연다 — 전처리기를 태우면 표 안 수치가 깨진다.
    """
    started = time.monotonic()
    raw = await _read_upload_capped(document, Config.MAX_UPLOAD_BYTES)
    if raw is None:
        return _error_response(
            ERR_API_INPUT,
            f"파일 크기가 상한({Config.MAX_UPLOAD_BYTES // (1024 * 1024)}MB)을 초과했습니다.",
        )
    if not raw:
        return _error_response(ERR_API_INPUT, "업로드된 파일이 비어 있습니다.")

    try:
        # zip 해제 + XML 파싱은 blocking 이라 스레드로 넘긴다
        parsed = await asyncio.to_thread(hwpx_to_markdown, raw, Config.MAX_CONTEXT_CHARS)
    except HwpxParseError as exc:
        # 계약: 이 예외의 메시지는 hwpx_text.py 의 고정 안내문이다
        return _error_response(ERR_API_INPUT, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _internal_error("faq_upload_parse_error", exc)

    if not parsed.markdown.strip():
        return _error_response(ERR_API_INPUT, "문서에서 FAQ 를 만들 내용을 찾지 못했습니다.")

    try:
        payload = await _generate_and_store(
            parsed.markdown, count or Config.DEFAULT_FAQ_COUNT, session_id, title
        )
    except Exception as exc:  # noqa: BLE001
        return _internal_error("faq_upload_internal_error", exc)
    if isinstance(payload, JSONResponse):
        return payload

    payload["source"] = {
        "paragraph_count": parsed.paragraph_count,
        "table_count": parsed.table_count,
    }
    log_info(
        "FAQ 생성 완료(hwpx 업로드)",
        event="api_upload_generate_completed",
        item_count=payload["count"],
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return payload


@app.get("/faqs")
async def get_faqs(session_id: str = "", x_admin_token: str = Header("")):
    """세션에 저장된 FAQ 조회 (다운로드 버튼 활성화 판단용)."""
    if Config.ADMIN_TOKEN and x_admin_token and x_admin_token != Config.ADMIN_TOKEN:
        return _error_response(ERR_API_ADMIN_FORBIDDEN)
    if not session_id:
        return _error_response(ERR_API_INPUT, "session_id 가 필요합니다.")
    state = await load_faqs(session_id)
    return {
        "items": state["items"],
        "count": len(state["items"]),
        "title": state.get("title", ""),
        "ready_for_download": bool(state["items"]),
        "formats": list(_FORMATS),
    }


@app.post("/download")
async def download(body: DownloadRequest):
    """저장된 FAQ 를 **txt 파일**로 내려준다 (2026-08-12 — hwpx/pdf/xlsx 폐기).

    다시 생성하지 않는다 — 화면에서 본 것과 같은 내용이어야 한다.

    `format` 은 비워도 되고 `txt` 만 받는다. 옛 형식 이름(`hwpx`/`pdf`/`xlsx`)으로 오는
    요청은 **거절한다** — 조용히 txt 를 내려주면 화면은 xlsx 버튼을 눌렀다고 믿는데
    파일은 txt 인 상태가 되고, 그 어긋남은 아무 로그도 남기지 않는다.
    """
    fmt = (body.format or txt_output.EXTENSION).strip().lower()
    if fmt not in _FORMATS:
        return _error_response(
            ERR_API_INPUT, "txt 형식으로만 내려받을 수 있습니다."
        )

    items = body.items
    title = body.title
    if not items:
        if not body.session_id:
            return _error_response(ERR_API_INPUT, "session_id 또는 items 가 필요합니다.")
        state = await load_faqs(body.session_id)
        items = state["items"]
        title = title or state.get("title", "")
    if not items:
        return _error_response(ERR_API_SESSION_NOT_FOUND)

    try:
        # 문자열 조립 + utf-8 인코딩. blocking 이 아니라 스레드로 넘기지 않는다
        # (외부 변환기·zip 조립이 있던 시절의 to_thread 는 이 경로에서 걷어냈다).
        data = txt_output.to_bytes(rows_to_plain_text(items, title=title))
    except Exception as exc:  # noqa: BLE001
        return _internal_error("faq_download_internal_error", exc)

    stem = txt_output.safe_stem(title, "FAQ")
    log_info(
        "FAQ 다운로드 생성 완료",
        event="api_download_completed",
        item_count=len(items),
        resource_id=fmt,
    )
    return Response(
        content=data,
        media_type=txt_output.MEDIA_TYPE,
        headers=txt_output.headers(stem, **{"X-Faq-Count": str(len(items))}),
    )


@app.get("/prompts")
async def prompts() -> dict:
    """프롬프트를 **어디서 받았는지** (2026-09-03).

    관리자가 프롬프트 라이브러리에서 문구를 고쳤는데 반영이 안 될 때 답할 자리다. 이 값이
    없으면 "ID 를 안 넣었다"(`configured: false`)와 "넣었는데 못 읽었다"
    (`reason: fetch_failed_404`)가 **똑같이 옛 문구로** 보인다.

    **본문은 담지 않는다** — 담으면 이 경로가 지시문 유출 경로가 된다 (3.8절).
    """
    return {"prompts": await asyncio.to_thread(prompt_library.status)}


@app.post("/prompts/reload")
async def prompts_reload(x_admin_token: str = Header("")):
    """**관리자** — 프롬프트 라이브러리를 즉시 다시 읽는다 (TTL 을 기다리지 않는다).

    **반환 타입 주석을 붙이지 않는다** — 성공/오류로 형이 갈리는 라우트는 이 저장소
    세 단위 모두 주석 없이 둔다(Union 반환 주석이면 앱이 기동 단계에서 죽는다).
    """
    if Config.ADMIN_TOKEN and x_admin_token != Config.ADMIN_TOKEN:
        return JSONResponse(
            status_code=403,
            content={"error_code": ERR_API_INPUT.code, "msg": "프롬프트 재적재 권한이 없습니다."},
        )
    return {"prompts": await asyncio.to_thread(prompt_library.reload)}
