"""FAQ 코드 서빙 진입점 (area 03).

엔드포인트
- GET  /health            : 헬스체크 (가이드 필수)
- GET  ""                 : 루트 — 게이트웨이가 경로 없이 베이스를 때리는 경우 대비
- GET  /config            : 관리자 상한·기본 개수·내려받을 수 있는 형식 (UI 가 선택지를 만든다)
- POST /generate          : 마크다운 본문으로 FAQ 생성 (재생성·비대화 경로)
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
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse, Response

from . import txt_output
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
    ERR_API_NO_GROUNDED,
    ERR_API_CONFIG_UNAVAILABLE,
    ERR_API_PROMPT_UNAVAILABLE,
    ERR_API_SESSION_NOT_FOUND,
    ERR_API_UPSTREAM_EXECUTION,
    ERR_API_UPSTREAM_TIMEOUT,
)
from .formatting import rows_to_plain_text, to_export_rows
from .formatting import to_markdown as faq_markdown
from .generator import (
    FAILURE_CONFIG,
    FAILURE_NO_GROUNDED,
    FAILURE_PROMPT,
    FAILURE_TRANSPORT,
    generate_faqs,
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

    `max_count` 는 요구사항 §4 의 관리자 상한이다. 화면은 0~max_count 만 고르게 한다.
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

    payload = result.as_payload()
    payload["markdown"] = faq_markdown(result.items)
    payload["download_ready"] = False

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
