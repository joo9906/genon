"""SFR-018 내보내기 코드 서빙 (area 03).

글다듬이·번역·FAQ 산출물을 파일로 내려준다. 이 단위는 LLM 을 호출하지 않는다 —
다듬기·번역은 이미 끝난 결과를 세션에서 받아 파일로만 만든다. 내보내기 시점에
LLM 을 다시 부르면 화면에 보인 문장과 파일 속 문장이 달라지기 때문이다.

## 흐름 (hwpx 원본)

    대화 시작   POST /prepare        원본 hwpx → 문단 배열 + 지문 → 세션 저장
    대화 중     POST /results        워크플로우가 다듬은 문단을 세션에 누적
    다운로드    POST /export/hwpx    원본 + session_id → 지문 대조 → 되쓰기
                POST /export/pdf     위 결과를 전처리기로 PDF 변환

전처리기 마크다운을 쓰지 않고 우리가 직접 파싱한 문단을 기준으로 삼는다 —
전처리기 산출물은 표를 마크다운 한 덩어리로 직렬화하고 페이지 마커·표 설명을
끼워 넣어서 원본 hwpx 문단과 1:1 이 아니고, 그대로 되쓰면 엉뚱한 문단이 바뀐다.

## 흐름 (docx·pdf 원본, FAQ)

되쓸 원본이 없으므로 hwpx 를 제공하지 않는다. 다듬은 마크다운을 그대로 렌더링한다.

    POST /export/pdf/markdown    마크다운 → PDF
    POST /export/xlsx            FAQ 질문/답변 → 엑셀

가이드 6장 준수:
- `0.0.0.0` + GenOS 가 주입하는 `$PORT` 에 bind (실행 커맨드는 README)
- `GET /health` 는 200 고정 응답
- async 핸들러에서 동기 blocking 작업(XML 파싱·외부 변환기)은 `asyncio.to_thread`
- 3.9.6절: 예외를 던지지 않고 오류 **객체**를 반환한다
"""

import asyncio
import time
import urllib.parse

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from config import Config
from export_pipeline import error_codes as ec
from export_pipeline import pdf_export, session_store, xlsx_export
from export_pipeline.hwpx_rewrite import (
    HwpxExportError,
    extract_paragraphs,
    fingerprint,
    rewrite_paragraphs,
)
from export_pipeline.logging_utils import configure_logging, log_info, log_warning
from export_pipeline.session_store import SessionStoreError

configure_logging(Config.LOG_LEVEL)

app = FastAPI(title="SFR-018 내보내기", docs_url=None, redoc_url=None)

# 지원 원본 형식. hwpx·docx 는 둘 다 ZIP 이라 확장자만으로는 구분할 수 없다.
KIND_HWPX = "hwpx"
KIND_DOCX = "docx"
KIND_PDF = "pdf"


# ─────────────────────────────────────────────────────────────
# 공통
# ─────────────────────────────────────────────────────────────
def _error(error: ec.ErrorCode, *, trace_id: str = "") -> JSONResponse:
    log_warning(
        "내보내기 요청 실패",
        event="export_failed",
        error_code=error.code,
        error_type=error.error_type,
        trace_id=trace_id or None,
        upstream_status=error.http_status,
    )
    return JSONResponse(status_code=error.http_status, content=ec.to_payload(error))


def _detect_kind(data: bytes) -> str:
    """매직 헤더로 원본 형식을 판정한다.

    확장자를 믿지 않는다 — hwpx 와 docx 는 둘 다 ZIP(`PK\\x03\\x04`)이라 헤더만으로도
    구분되지 않으므로 ZIP 안의 엔트리로 갈라야 한다.
    """
    if data[:5] == b"%PDF-":
        return KIND_PDF
    if data[:4] != b"PK\x03\x04":
        return ""
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        return ""
    if any(name.startswith("Contents/section") for name in names):
        return KIND_HWPX
    if "word/document.xml" in names:
        return KIND_DOCX
    return ""


async def _read_upload(upload: UploadFile) -> tuple:
    """업로드 파일을 읽고 크기·형식을 검증한다.

    Returns:
        (bytes, kind, None) 또는 (None, "", ErrorCode)
    """
    if upload is None:
        return None, "", ec.ERR_INPUT
    data = await upload.read()
    if not data:
        return None, "", ec.ERR_FILE_EMPTY
    # 전량을 메모리에서 XML 파싱하므로 상한이 필요하다. read() 후 검사이므로
    # 상한을 넘는 파일도 일단 메모리에 올라온다 — 상한값을 보수적으로 둔 이유다.
    if len(data) > Config.MAX_UPLOAD_BYTES:
        return None, "", ec.ERR_FILE_TOO_LARGE
    kind = _detect_kind(data)
    if not kind:
        return None, "", ec.ERR_UNSUPPORTED_FORMAT
    return data, kind, None


def _download(content: bytes, filename: str, extra_headers: dict | None = None) -> Response:
    """파일 다운로드 응답. 한글 파일명은 RFC 5987 로 인코딩한다.

    SFR-006 `_document_response` 와 같은 관례를 따른다.
    """
    quoted = urllib.parse.quote(filename)
    headers = {"Content-Disposition": "attachment; filename*=UTF-8''" + quoted}
    headers.update(extra_headers or {})
    return Response(content=content, media_type="application/octet-stream", headers=headers)


def _with_ext(name: str, ext: str, default: str) -> str:
    stem = (name or default).strip() or default
    return stem if stem.lower().endswith(ext) else stem + ext


@app.get("/health")
async def health():
    """6.3절: 200 고정 응답. 의존 인프라(Redis·변환기)를 여기서 확인하지 않는다."""
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────
# 대화 준비 / 결과 누적
# ─────────────────────────────────────────────────────────────
@app.post("/prepare")
async def prepare(
    original: UploadFile = File(...),
    session_id: str = Form(...),
):
    """원본 문서를 받아 다듬을 문단 배열을 낸다 (hwpx 전용).

    문단 index 는 이 응답이 유일한 기준이다 — 워크플로우는 이 배열을 다듬어
    `/results` 로 돌려주고, 내보내기는 같은 index 로 되쓴다.

    docx·pdf 는 되쓰기 대상이 아니므로 여기서 받지 않는다 (PDF 만 제공).
    """
    started = time.monotonic()
    data, kind, error = await _read_upload(original)
    if error is not None:
        return _error(error)
    if kind != KIND_HWPX:
        return _error(ec.ERR_HWPX_ONLY)

    try:
        extracted = await asyncio.to_thread(extract_paragraphs, data)
    except HwpxExportError:
        return _error(ec.ERR_DOCUMENT_INVALID)
    except Exception as exc:
        log_warning("문단 추출 실패", event="prepare_failed", error_type=type(exc).__name__)
        return _error(ec.ERR_INTERNAL)

    paragraphs = extracted["paragraphs"]
    if len(paragraphs) > Config.MAX_PARAGRAPHS:
        return _error(ec.ERR_TOO_MANY_PARAGRAPHS)
    if sum(len(item["text"]) for item in paragraphs) > Config.MAX_TOTAL_CHARS:
        return _error(ec.ERR_TOO_MANY_PARAGRAPHS)

    try:
        await session_store.save_session(
            session_id,
            source_kind=kind,
            fingerprint=extracted["fingerprint"],
            paragraphs=paragraphs,
        )
    except (SessionStoreError, ValueError):
        return _error(ec.ERR_SESSION_SAVE)

    log_info(
        "내보내기 준비 완료",
        event="prepare_completed",
        item_count=len(paragraphs),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return {
        "source_kind": kind,
        "fingerprint": extracted["fingerprint"],
        "paragraph_count": extracted["paragraph_count"],
        "paragraphs": paragraphs,
    }


class ResultsRequest(BaseModel):
    session_id: str
    # {문단 index: 다듬은 텍스트}. 부분 갱신을 허용한다 (턴마다 일부만 올 수 있다).
    results: dict


@app.post("/results")
async def save_results(body: ResultsRequest):
    """워크플로우가 다듬은 문단을 세션에 누적한다.

    화면에 보여준 결과와 파일에 들어갈 결과가 같아야 하므로, 워크플로우는 LLM 결과를
    화면에 쓰는 것과 **같은 값**을 여기 보낸다.
    """
    state = await session_store.load_session(body.session_id)
    if not state.get("paragraphs"):
        return _error(ec.ERR_SESSION_NOT_FOUND)

    merged = session_store.results_as_mapping(state)
    known = {item["index"] for item in state["paragraphs"]}
    unknown = []
    for key, value in (body.results or {}).items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            return _error(ec.ERR_INPUT)
        if index not in known:
            unknown.append(index)  # 조용히 버리지 않고 응답으로 알린다
            continue
        merged[index] = str(value)

    try:
        await session_store.save_session(
            body.session_id,
            source_kind=state.get("source_kind", ""),
            fingerprint=state.get("fingerprint", ""),
            paragraphs=state["paragraphs"],
            results=merged,
        )
    except (SessionStoreError, ValueError):
        return _error(ec.ERR_SESSION_SAVE)
    return {
        "stored_count": len(merged),
        "paragraph_count": len(state["paragraphs"]),
        "unknown_indexes": sorted(unknown),
        "ready_for_download": bool(merged),
    }


@app.get("/paragraphs")
async def paragraphs(session_id: str):
    """세션에 준비된 문단 배열을 돌려준다 (글다듬이·번역 호출부용).

    워크플로우(02)는 원본 파일 바이트를 받지 못하므로 `/prepare` 를 직접 호출할 수 없다.
    원본 업로드는 클라이언트가 `/prepare` 로 하고, 워크플로우는 `session_id` 로 여기서
    문단을 가져가 다듬은 뒤 `/results` 로 돌려준다.

    아직 준비되지 않았으면 `found: false` 를 준다 — 404 가 아니라 정상 응답이다.
    호출부는 이 경우 기존 마크다운 경로로 진행하면 되고, 오류가 아니다.
    """
    state = await session_store.load_session(session_id)
    items = state.get("paragraphs") or []
    return {
        "found": bool(items),
        "source_kind": state.get("source_kind", ""),
        "fingerprint": state.get("fingerprint", ""),
        "paragraph_count": len(items),
        "paragraphs": items,
    }


@app.get("/status")
async def status(session_id: str):
    """다운로드 버튼 활성화 판단용 (SFR-006 `/status` 와 같은 역할)."""
    state = await session_store.load_session(session_id)
    stored = session_store.results_as_mapping(state)
    return {
        "found": bool(state.get("paragraphs")),
        "source_kind": state.get("source_kind", ""),
        "paragraph_count": len(state.get("paragraphs") or []),
        "stored_count": len(stored),
        "ready_for_download": bool(stored),
        "hwpx_available": state.get("source_kind") == KIND_HWPX,
    }


# ─────────────────────────────────────────────────────────────
# 내보내기
# ─────────────────────────────────────────────────────────────
async def _rewrite_from_session(original: UploadFile, session_id: str) -> tuple:
    """원본 업로드 + 세션 결과로 되쓴 hwpx 를 만든다.

    Returns:
        (RewriteResult, None) 또는 (None, ErrorCode)
    """
    data, kind, error = await _read_upload(original)
    if error is not None:
        return None, error
    if kind != KIND_HWPX:
        return None, ec.ERR_HWPX_ONLY

    state = await session_store.load_session(session_id)
    if not state.get("paragraphs"):
        return None, ec.ERR_SESSION_NOT_FOUND
    results = session_store.results_as_mapping(state)
    if not results:
        return None, ec.ERR_SESSION_NOT_FOUND

    expected = state.get("fingerprint") or ""
    if expected and expected != fingerprint(data):
        # 원본이 바뀌면 index 가 밀려 엉뚱한 문단에 값이 들어간다 — 쓰기 전에 막는다
        return None, ec.ERR_FINGERPRINT_MISMATCH

    try:
        result = await asyncio.to_thread(
            rewrite_paragraphs, data, results, expected_fingerprint=expected or None
        )
    except HwpxExportError:
        return None, ec.ERR_DOCUMENT_INVALID
    except Exception as exc:
        log_warning("되쓰기 실패", event="rewrite_failed", error_type=type(exc).__name__)
        return None, ec.ERR_INTERNAL
    return result, None


def _rewrite_headers(result) -> dict:
    """손실·오류를 파일과 함께 전달한다 (침묵 처리 금지 컨벤션).

    `X-Style-Simplified-Paragraphs`: 문단 내 부분 강조가 첫 run 서식으로 통일된 문단 수.
    `X-Unknown-Paragraphs`: 원본에 없는 index (호출부 오류).
    """
    return {
        "X-Rewritten-Paragraphs": str(len(result.rewritten_indexes)),
        "X-Unchanged-Paragraphs": str(len(result.unchanged_indexes)),
        "X-Style-Simplified-Paragraphs": str(len(result.style_simplified_indexes)),
        "X-Unknown-Paragraphs": str(len(result.unknown_indexes)),
    }


@app.post("/export/hwpx")
async def export_hwpx(
    original: UploadFile = File(...),
    session_id: str = Form(...),
    filename: str = Form(""),
):
    """원본 hwpx 에 다듬은 문단을 되쓴 hwpx 를 내려준다 (원본 서식 유지)."""
    started = time.monotonic()
    result, error = await _rewrite_from_session(original, session_id)
    if error is not None:
        return _error(error)
    log_info(
        "hwpx 내보내기 완료",
        event="export_hwpx_completed",
        item_count=len(result.rewritten_indexes),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return _download(
        result.hwpx_bytes, _with_ext(filename, ".hwpx", "문서"), _rewrite_headers(result)
    )


@app.post("/export/pdf")
async def export_pdf(
    original: UploadFile = File(...),
    session_id: str = Form(...),
    filename: str = Form(""),
):
    """원본 hwpx 에 되쓴 뒤 전처리기 변환기로 PDF 를 만든다 (원본 서식 유지)."""
    started = time.monotonic()
    result, error = await _rewrite_from_session(original, session_id)
    if error is not None:
        return _error(error)
    try:
        # 외부 변환기 호출은 blocking 이다 (임시 파일 + 외부 프로세스)
        pdf_bytes = await asyncio.to_thread(pdf_export.hwpx_to_pdf, result.hwpx_bytes)
    except pdf_export.PdfConverterUnavailable:
        return _error(ec.ERR_PDF_CONVERTER_MISSING)
    except pdf_export.PdfConversionError:
        return _error(ec.ERR_PDF_CONVERSION_FAILED)
    log_info(
        "PDF 내보내기 완료",
        event="export_pdf_completed",
        item_count=len(result.rewritten_indexes),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return _download(pdf_bytes, _with_ext(filename, ".pdf", "문서"), _rewrite_headers(result))


class MarkdownPdfRequest(BaseModel):
    markdown: str
    title: str = ""
    filename: str = ""


@app.post("/export/pdf/markdown")
async def export_pdf_markdown(body: MarkdownPdfRequest):
    """다듬은 마크다운을 PDF 로 만든다 (docx·pdf 원본, FAQ 용).

    원본 서식이 아니라 마크다운 렌더링 서식이 된다 — 되쓸 원본이 없기 때문이다.
    """
    if not (body.markdown or "").strip():
        return _error(ec.ERR_INPUT)
    if len(body.markdown) > Config.MAX_TOTAL_CHARS:
        return _error(ec.ERR_TOO_MANY_PARAGRAPHS)
    try:
        pdf_bytes = await asyncio.to_thread(
            pdf_export.markdown_to_pdf, body.markdown, title=body.title
        )
    except pdf_export.PdfConverterUnavailable:
        return _error(ec.ERR_PDF_CONVERTER_MISSING)
    except pdf_export.PdfConversionError:
        return _error(ec.ERR_PDF_CONVERSION_FAILED)
    log_info("마크다운 PDF 내보내기 완료", event="export_pdf_markdown_completed")
    return _download(pdf_bytes, _with_ext(body.filename, ".pdf", "문서"))


class FaqXlsxRequest(BaseModel):
    items: list
    sheet_title: str = "FAQ"
    filename: str = ""


@app.post("/export/xlsx")
async def export_xlsx(body: FaqXlsxRequest):
    """FAQ 질문/답변을 엑셀로 만든다."""
    try:
        content = await asyncio.to_thread(
            xlsx_export.build_faq_xlsx, body.items, body.sheet_title
        )
    except xlsx_export.XlsxExportError:
        return _error(ec.ERR_INPUT)
    except Exception as exc:
        log_warning("엑셀 생성 실패", event="export_xlsx_failed", error_type=type(exc).__name__)
        return _error(ec.ERR_INTERNAL)
    log_info("엑셀 내보내기 완료", event="export_xlsx_completed", item_count=len(body.items))
    return _download(content, _with_ext(body.filename, ".xlsx", "FAQ"))
