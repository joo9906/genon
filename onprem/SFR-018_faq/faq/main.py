"""FAQ 코드 서빙 진입점 (area 03).

엔드포인트
- GET  /health            : 헬스체크 (가이드 필수)
- GET  ""                 : 루트 — 게이트웨이가 경로 없이 베이스를 때리는 경우 대비
- GET  /config            : 관리자 상한·기본 개수·내려받을 수 있는 형식 (UI 가 선택지를 만든다)
- POST /generate          : 마크다운 본문으로 FAQ 생성 (재생성·비대화 경로)
- POST /generate/upload   : **hwpx 업로드 직접 파싱** 후 FAQ 생성 (요구사항 §1)
- GET  /faqs              : 세션에 저장된 FAQ 조회
- POST /download          : hwpx / pdf / xlsx 내려받기 (요구사항 §2)

설계 메모
- **다운로드는 저장된 FAQ 를 내려준다. 다시 생성하지 않는다.** LLM 을 다시 부르면
  화면에서 본 FAQ 와 파일 내용이 달라진다.
- 형식별 가용성은 프로세스당 판별해 `/config` 로 알린다 — UI 는 그걸 보고 버튼을 켠다.
  가용성은 이미지 빌드/설정 시점에 정해지므로 요청마다 다시 볼 이유가 없다
  (SFR-006 PDF 규약과 같다).
- **blocking 작업은 전부 `asyncio.to_thread`** 로 넘긴다 (zip/XML 파싱, 파일 생성,
  외부 변환기 호출). async 핸들러에서 직접 돌리면 이벤트 루프가 멈춘다.
- 오류 응답은 `{error_code, msg}` (3.9.5절), 사용자 노출 문구는 고정 안내문만 (3.8절).
"""

import asyncio
import os
import time
import urllib.parse
from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .config import Config
from .error_codes import (
    ERR_API_ADMIN_FORBIDDEN,
    ERR_API_EXPORT_FAILED,
    ERR_API_EXPORT_UNAVAILABLE,
    ERR_API_INPUT,
    ERR_API_INTERNAL,
    ERR_API_SESSION_NOT_FOUND,
    ERR_API_UPSTREAM_EXECUTION,
    ERR_API_UPSTREAM_TIMEOUT,
)
from .exporters import hwpx_export, pdf_export, xlsx_export
from .exporters.errors import ExportError, ExporterUnavailable
from .formatting import rows_to_markdown, to_export_rows
from .formatting import to_markdown as faq_markdown
from .generator import FAILURE_TRANSPORT, generate_faqs, resolve_max_count
from .hwpx_text import HwpxParseError, to_markdown as hwpx_to_markdown
from .logging_utils import configure_logging, log_error, log_info, log_warning
from .prompt_loader import probe as probe_prompts
from .session_store import SessionStoreError, load_faqs, save_faqs

configure_logging(os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="faq-service")

# 다운로드 형식 → (media type, 확장자)
_FORMATS = {
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
    "hwpx": ("application/octet-stream", "hwpx"),
}


class GenerateRequest(BaseModel):
    markdown: str = Field(..., min_length=1, description="전처리기가 변환한 문서 본문")
    count: int = Field(0, ge=0, le=1000)  # 0 이면 기본 개수. 상한 검증은 generator 가 한다
    session_id: str = Field("", max_length=128)
    title: str = Field("", max_length=200)


class DownloadRequest(BaseModel):
    format: str = Field(..., description="hwpx | pdf | xlsx")
    session_id: str = Field("", max_length=128)
    # 세션 없이 화면이 들고 있는 항목을 그대로 보낼 수도 있다 (재생성 방지)
    items: list[dict] | None = None
    title: str = Field("", max_length=200)


def _json_error(error_code, msg: str = "") -> JSONResponse:
    """`{error_code, msg}` 응답 본문을 만드는 유일한 자리 (3.9.5절).

    형식을 두 곳에서 조립하면 한쪽만 바뀌어 호출자가 필드를 못 찾는 일이 생긴다.
    로그는 사건의 성격이 달라 호출부가 각자 남긴다 (입력 오류=warning, 내부 오류=error).
    """
    return JSONResponse(
        status_code=error_code.http_status,
        content={"error_code": error_code.code, "msg": msg or error_code.user_msg},
    )


def _error_response(error_code, msg: str = "") -> JSONResponse:
    log_warning(
        "FAQ API 오류 응답",
        event="api_error",
        error_code=error_code.code,
        error_type=error_code.error_type,
        status=str(error_code.http_status),
    )
    return _json_error(error_code, msg)


def _internal_error(event: str, exc: Exception) -> JSONResponse:
    # 예외 원문은 응답에 싣지 않는다 — 고정 안내문만 나간다 (3.8절)
    log_error(
        "FAQ 처리 중 내부 오류",
        event=event,
        error_code=ERR_API_INTERNAL.code,
        error_type=type(exc).__name__,
    )
    return _json_error(ERR_API_INTERNAL)


def _available_formats() -> list:
    """지금 이 컨테이너가 만들 수 있는 형식.

    xlsx 는 openpyxl(순수 파이썬)만 있으면 되고, pdf 는 weasyprint, hwpx 는 관리자
    템플릿 등록이 조건이다. 셋 다 확인해서 알린다 — UI 가 못 만드는 형식의 버튼을
    켜두면 사용자는 눌러 보고서야 501 을 받는다.
    """
    formats = []
    try:
        import openpyxl  # noqa: F401 - 가용성 확인만 (실제 사용은 지연 import)

        formats.append("xlsx")
    except ImportError:
        pass
    if pdf_export.markdown_available() or (
        hwpx_export.available() and pdf_export.document_converter_available()
    ):
        formats.append("pdf")
    if hwpx_export.available():
        formats.append("hwpx")
    return formats


# 가용성은 이미지 빌드/설정 시점에 정해진다 — 프로세스당 1회만 판별한다
# (환경이 바뀌면 pod 을 재시작한다).
_FORMATS_CACHE: list = []


@app.on_event("startup")
async def _startup() -> None:
    global _FORMATS_CACHE
    _FORMATS_CACHE = _available_formats()
    log_info(
        "FAQ 서비스 기동",
        event="service_started",
        item_count=len(_FORMATS_CACHE),
        status=",".join(_FORMATS_CACHE) or "none",
    )
    if not Config.ADMIN_TOKEN:
        log_warning(
            "FAQ_ADMIN_TOKEN 미설정 — 관리자 설정 조회가 인증 없이 열려 있다",
            event="admin_token_missing",
            resource_id="faq_admin",
            status="unprotected",
        )
    # 프롬프트 소스 도달 확인. genos 소스면 admin-api 를 실제로 한 번 찔러 본다 —
    # Gateway 경유가 아니라 내부 서비스 직통이라 네트워크가 닿는지는 찔러 봐야 안다.
    # 실패해도 기동은 막지 않는다 (요청 시점 오류로 드러나야 원인이 보인다).
    await probe_prompts(("system", "user", "retry_shortfall"))

    if "hwpx" not in _FORMATS_CACHE:
        log_warning(
            # 기본 템플릿이 배포 단위에 번들돼 있으므로 정상 배포에서는 뜨지 않는다.
            # 어느 쪽이 문제인지 status 로 가른다 — 고칠 곳이 서로 다르다:
            # override 면 환경변수 오타, bundled 면 이미지 빌드에서 faq/assets/ 누락.
            "FAQ hwpx 템플릿 파일을 찾지 못했다 — hwpx 내려받기를 미지원으로 응답한다",
            event="hwpx_template_missing",
            resource_id="faq_hwpx_template",
            status=(
                "override_path_invalid" if Config.HWPX_TEMPLATE_OVERRIDE
                else "bundled_asset_missing"
            ),
        )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("")
async def root() -> dict:
    """게이트웨이가 서빙 베이스를 경로 없이 때리는 배포가 있다 (운영 app.py 대조 결과)."""
    return {"service": "faq-service", "status": "ok"}


@app.get("/config")
async def service_config() -> dict:
    """UI 가 선택지를 만들 때 쓰는 값.

    `max_count` 는 요구사항 §4 의 관리자 상한이다. 화면은 0~max_count 만 고르게 한다.
    """
    return {
        "max_count": resolve_max_count(),
        "default_count": Config.DEFAULT_FAQ_COUNT,
        "formats": _FORMATS_CACHE,
        "evidence_required": Config.EVIDENCE_REJECT,
    }


async def _generate_and_store(source: str, count, session_id: str, title: str):
    """생성 → (성공 시) 세션 저장. 응답 payload 또는 오류 응답을 돌려준다."""
    result = await generate_faqs(source, count)
    if not result.ok:
        if result.failure == FAILURE_TRANSPORT:
            return _error_response(ERR_API_UPSTREAM_TIMEOUT)
        return _error_response(ERR_API_UPSTREAM_EXECUTION)

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
    raw = await document.read()
    if not raw:
        return _error_response(ERR_API_INPUT, "업로드된 파일이 비어 있습니다.")
    if len(raw) > Config.MAX_UPLOAD_BYTES:
        return _error_response(
            ERR_API_INPUT,
            f"파일 크기가 상한({Config.MAX_UPLOAD_BYTES // (1024 * 1024)}MB)을 초과했습니다.",
        )

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
        "formats": _FORMATS_CACHE,
    }


def _build_bytes(fmt: str, items: list, title: str) -> bytes:
    """형식별 생성 — **동기 함수**다. 호출부가 `asyncio.to_thread` 로 감싼다.

    pdf 는 두 경로가 있다: hwpx 템플릿이 있으면 사내 서식 그대로(hwpx→pdf),
    없으면 마크다운 렌더링. 앞쪽을 먼저 시도하는 이유는 배포한 문서의 서식이
    사내 양식과 같아야 하기 때문이고, 변환기가 없으면 뒤쪽으로 떨어진다.
    """
    created_on = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    if fmt == "xlsx":
        return xlsx_export.build_faq_xlsx(items, sheet_title=title or "FAQ")
    if fmt == "hwpx":
        return hwpx_export.build_faq_hwpx(items, title=title, created_on=created_on)
    if fmt == "pdf":
        if hwpx_export.available() and pdf_export.document_converter_available():
            hwpx_bytes = hwpx_export.build_faq_hwpx(items, title=title, created_on=created_on)
            return pdf_export.hwpx_to_pdf(hwpx_bytes)
        return pdf_export.markdown_to_pdf(rows_to_markdown(items), title=title)
    raise ExportError("지원하지 않는 형식입니다.")


@app.post("/download")
async def download(body: DownloadRequest):
    """저장된 FAQ 를 파일로 내려준다 (hwpx / pdf / xlsx).

    다시 생성하지 않는다 — 화면에서 본 것과 같은 내용이어야 한다.
    """
    fmt = (body.format or "").strip().lower()
    if fmt not in _FORMATS:
        return _error_response(ERR_API_INPUT, "지원하지 않는 형식입니다.")

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
        # 파일 생성·외부 변환기 호출은 전부 blocking 이다
        data = await asyncio.to_thread(_build_bytes, fmt, items, title)
    except ExporterUnavailable as exc:
        # "수단 없음" — 재시도해도 소용없다. 다른 형식을 고르게 안내한다.
        return _error_response(ERR_API_EXPORT_UNAVAILABLE, str(exc))
    except ExportError as exc:
        # "생성 실패" — 재시도 가치가 있다.
        return _error_response(ERR_API_EXPORT_FAILED, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _internal_error("faq_download_internal_error", exc)

    media_type, extension = _FORMATS[fmt]
    filename = f"{(title or 'FAQ').strip() or 'FAQ'}.{extension}"
    quoted = urllib.parse.quote(filename)  # 한글 파일명 → RFC 5987
    log_info(
        "FAQ 다운로드 생성 완료",
        event="api_download_completed",
        item_count=len(items),
        resource_id=fmt,
    )
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quoted,
            "X-Faq-Count": str(len(items)),
        },
    )
