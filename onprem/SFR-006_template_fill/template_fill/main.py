"""SFR-006 템플릿 채우기 — 코드 서빙 (area 03).

사용자가 채팅 UI 에서 **다운로드 버튼**을 누르면 호출되는 파일 생성 API.
대화(run_chat.py)가 세션에 누적해 둔 필드 값을 읽어 hwpx 초안을 만들어
바이너리로 반환한다.

엔드포인트
- GET    /health                    : 헬스체크 (가이드 필수)
- GET    /templates                 : 등록된 템플릿 목록 (+ 색인 상태)
- POST   /templates                 : **관리자** 템플릿 등록 (업로드 + 즉시 색인)
- DELETE /templates/{template_id}   : **관리자** 템플릿 삭제 (+ 색인 폐기)
- GET    /fields?template_id=...    : 템플릿 항목 스키마 (라벨 항목 + 누름틀, source 로 구분)
- GET    /status?session_id=...     : 세션 채움 현황 (다운로드 버튼 활성화 판단용)
- GET    /preview?session_id=...    : 채운 결과를 마크다운으로 (표시 전용, 파일 생성 아님)
- POST   /generate                  : 등록된 템플릿으로 초안 생성 + 다운로드 응답(hwpx/pdf)
- POST   /generate/upload           : **업로드한 hwpx** 로 초안 생성 (multipart)

템플릿 파싱은 `template_index` 를 경유한다 — 등록 시점에 한 번 파싱해 Redis 에 두고
`/fields`·`/status`·대화의 매 턴이 그걸 읽는다 (예전에는 요청마다 zip+XML 을 다시 풀었다).

GenOS 엔지니어 개발가이드 v1.02 반영
- 0.0.0.0:$PORT bind, /health 제공
- 오류 응답은 {error_code, msg} 형식 (3.9.5절), 예외 원문 미노출 (3.8절)
- 부분 초안 허용: 값이 없는 항목은 그대로(라벨 항목은 `제목:`, 누름틀은 안내문 상태)
  남겨 사용자가 한/글에서 이어서 작성할 수 있게 한다 (missing_fields 를 응답 헤더로 알린다)
"""

import asyncio
import json
import os
import re
import time
import urllib.parse
from dataclasses import replace

from fastapi import FastAPI, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import pdf_convert
from .config import Config
from .error_codes import (
    ERR_API_ADMIN_FORBIDDEN,
    ERR_API_INPUT,
    ERR_API_INTERNAL,
    ERR_API_PDF_FAILED,
    ERR_API_PDF_UNAVAILABLE,
    ERR_API_SESSION_NOT_FOUND,
    ERR_API_TEMPLATE_EXISTS,
    ERR_API_TEMPLATE_NOT_FOUND,
    ErrorCode,
)
from .hwpx_fields import TemplateError, fill_template
from .hwpx_markdown import render_markdown
from .hwpx_style import apply_styles, collect_style_specs
from .logging_utils import configure_logging, log_error, log_info, log_warning
from .pdf_convert import PdfConvertError, PdfUnavailableError
from .session_store import end_session, load_session
from .template_index import (
    build_index,
    get_index,
    invalidate,
    peek_index,
    store_index,
)

configure_logging(os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="hwpx-template-fill-service")

_TEMPLATE_NAME_RE = re.compile(r"^[\w\-. ()\[\]가-힣]+$")
_DOCUMENT_FORMATS = ("hwpx", "pdf")

if not Config.ADMIN_TOKEN:
    # 인증 부재를 조용히 넘기지 않는다 — 배포자가 보호되고 있다고 착각하면
    # 누구나 템플릿을 덮어쓸 수 있는 상태로 운영된다.
    log_warning(
        "TEMPLATE_FILL_ADMIN_TOKEN 미설정 — 템플릿 등록/삭제가 인증 없이 열려 있다",
        event="admin_token_missing",
        status="open",
    )


class GenerateRequest(BaseModel):
    template_id: str | None = Field(None, max_length=256)
    session_id: str | None = Field(None, max_length=256)
    # 세션 없이 값 직접 지정도 허용 (테스트/단발 호출). 세션 값 위에 덮어쓴다.
    values: dict[str, str] | None = None
    filename: str | None = Field(None, max_length=128)
    # hwpx(기본) | pdf. PDF 는 전처리기 변환기를 호출하며 환경에 따라 미지원일 수 있다.
    format: str | None = Field(None, max_length=8)


def _error_response(err: ErrorCode, msg: str | None = None) -> JSONResponse:
    # 3.9.5절: 채팅 연계 시 msg 만 전달될 수 있으니 내부 로그에도 같은 코드를 남긴다
    log_warning(
        "코드 서빙 오류 응답",
        event="api_error",
        error_code=err.code,
        error_type=err.error_type,
        status=str(err.http_status),
    )
    return JSONResponse(
        status_code=err.http_status,
        content={"error_code": err.code, "msg": msg or err.user_msg},
    )


def _resolve_template_path(template_id: str) -> str | None:
    """TEMPLATE_DIR 안의 hwpx 만 허용 (경로 조작 방지)."""
    name = (template_id or "").strip()
    if not name:
        return None
    if not name.endswith(".hwpx"):
        name += ".hwpx"
    if not _TEMPLATE_NAME_RE.match(name.removesuffix(".hwpx") or "_"):
        return None
    path = os.path.join(Config.TEMPLATE_DIR, name)
    if not os.path.exists(path):
        return None
    return path


def _load_template_bytes(template_id: str) -> bytes | None:
    path = _resolve_template_path(template_id)
    if path is None:
        return None
    with open(path, "rb") as f:
        return f.read()


def _admin_denied(token: str | None) -> JSONResponse | None:
    """관리자 토큰 검사. 토큰이 설정돼 있지 않으면 검사하지 않는다(기동 시 경고를 남긴다)."""
    if not Config.ADMIN_TOKEN:
        return None
    if (token or "").strip() != Config.ADMIN_TOKEN:
        return _error_response(ERR_API_ADMIN_FORBIDDEN)
    return None


def _resolve_format(raw: str | None) -> tuple[str, JSONResponse | None]:
    fmt = (raw or "hwpx").strip().lower()
    if fmt not in _DOCUMENT_FORMATS:
        return "", _error_response(
            ERR_API_INPUT, "format 은 hwpx 또는 pdf 여야 합니다."
        )
    return fmt, None


def _safe_template_id(raw: str) -> str | None:
    """등록·삭제에 쓸 템플릿 id 검증. 부적합하면 None.

    `_TEMPLATE_NAME_RE` 는 점을 허용하므로 `..` 같은 이름이 통과한다 —
    경로 상위 탈출은 여기서 따로 막는다.
    """
    name = (raw or "").strip().removesuffix(".hwpx")
    if not name or name.startswith(".") or ".." in name:
        return None
    if any(sep in name for sep in ("/", "\\")):
        return None
    if not _TEMPLATE_NAME_RE.match(name):
        return None
    return name


def _field_payload(spec) -> dict:
    return {
        "name": spec.name,
        "guide": spec.guide,
        "occurrences": spec.occurrences,
        "filled": spec.filled,
        "current_value": spec.current_value,
        # 라벨 항목인지 누름틀인지 — 템플릿 제작 방식 확인용
        "source": spec.source,
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/templates")
async def templates() -> dict:
    """등록된 템플릿 목록.

    색인 정보는 **캐시에 있는 것만** 붙인다. 목록을 만들 때마다 모든 템플릿을 열어
    파싱하면 목록 조회 한 번이 전체 파싱이 된다. 색인이 없으면 `indexed: false` 로
    정직하게 표시하고, 그 템플릿의 `/fields` 첫 호출이 색인을 만든다.
    """
    if not os.path.isdir(Config.TEMPLATE_DIR):
        return {"templates": [], "formats": _available_formats()}
    names = sorted(
        os.path.splitext(n)[0]
        for n in os.listdir(Config.TEMPLATE_DIR)
        if n.endswith(".hwpx")
    )
    items = []
    for name in names:
        index = await peek_index(name)
        items.append(
            {
                "template_id": name,
                "indexed": index is not None,
                "field_count": len(index.fields) if index else None,
                "table_count": index.table_count if index else None,
                "indexed_at": index.indexed_at if index else None,
            }
        )
    return {"templates": names, "items": items, "formats": _available_formats()}


def _available_formats() -> list:
    """지금 환경에서 실제로 내려줄 수 있는 형식 (UI 버튼 노출 판단용)."""
    formats = ["hwpx"]
    if pdf_convert.available():
        formats.append("pdf")
    return formats


@app.post("/templates")
async def register_template(
    template: UploadFile = File(..., description="등록할 hwpx 템플릿 파일"),
    template_id: str | None = Form(None, description="생략하면 업로드 파일명을 쓴다"),
    overwrite: bool = Form(False, description="같은 이름이 있을 때 덮어쓸지"),
    x_admin_token: str | None = Header(None),
) -> Response:
    """관리자 템플릿 등록 — 파일을 볼륨에 두고 **그 자리에서 색인까지** 만든다.

    등록 시점에 파싱하는 이유가 두 가지다:
    - 깨진 템플릿을 등록 단계에서 막는다 (대화 중에 터지면 사용자가 손쓸 수 없다).
    - 첫 대화 턴이 파싱 비용을 물지 않는다.

    파싱이 먼저, 파일 쓰기가 나중이다. 순서를 바꾸면 해석 불가 파일이 볼륨에 남는다.
    """
    denied = _admin_denied(x_admin_token)
    if denied is not None:
        return denied

    upload_name = (template.filename or "").strip()
    if not upload_name.lower().endswith(".hwpx"):
        return _error_response(ERR_API_INPUT, "hwpx 파일만 등록할 수 있습니다.")

    resolved_id = _safe_template_id(template_id or os.path.basename(upload_name))
    if resolved_id is None:
        return _error_response(ERR_API_INPUT, "템플릿 이름에 쓸 수 없는 문자가 있습니다.")

    template_bytes = await template.read()
    if not template_bytes:
        return _error_response(ERR_API_INPUT, "업로드한 파일이 비어 있습니다.")
    if len(template_bytes) > Config.MAX_UPLOAD_BYTES:
        return _error_response(
            ERR_API_INPUT,
            f"파일 크기가 상한({Config.MAX_UPLOAD_BYTES // (1024 * 1024)}MB)을 초과했습니다.",
        )

    target = os.path.join(Config.TEMPLATE_DIR, f"{resolved_id}.hwpx")
    exists = os.path.exists(target)
    if exists and not overwrite:
        return _error_response(ERR_API_TEMPLATE_EXISTS)

    try:
        index = build_index(resolved_id, template_bytes)
    except TemplateError as exc:
        # 계약: TemplateError 메시지는 hwpx_fields.py 의 고정 안내문만 담는다
        return _error_response(ERR_API_INPUT, str(exc))

    try:
        await asyncio.to_thread(_write_template_file, target, template_bytes)
    except OSError as exc:
        log_error(
            "템플릿 파일 저장 실패",
            event="template_write_failed",
            resource_id=resolved_id,
            error_code=ERR_API_INTERNAL.code,
            error_type=type(exc).__name__,
        )
        return _error_response(ERR_API_INTERNAL, "템플릿을 저장하지 못했습니다.")

    await store_index(index)
    log_info(
        "템플릿 등록 완료",
        event="template_registered",
        resource_id=resolved_id,
        item_count=len(index.fields),
        status=f"overwritten={int(exists)} tables={index.table_count}",
    )
    return JSONResponse(
        status_code=200 if exists else 201,
        content={
            "template_id": resolved_id,
            "overwritten": exists,
            "content_hash": index.content_hash,
            "fields": [_field_payload(s) for s in index.fields],
            "markdown": index.markdown,
            "markdown_truncated": index.truncated,
        },
    )


def _write_template_file(target: str, payload: bytes) -> None:
    """임시 파일에 쓴 뒤 교체한다 — 덮어쓰는 중에 다른 요청이 반쪽 파일을 읽지 않게."""
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    tmp_path = f"{target}.tmp"
    with open(tmp_path, "wb") as handle:
        handle.write(payload)
    os.replace(tmp_path, target)


@app.delete("/templates/{template_id}")
async def delete_template(
    template_id: str, x_admin_token: str | None = Header(None)
) -> Response:
    """관리자 템플릿 삭제 — 파일과 색인을 함께 없앤다."""
    denied = _admin_denied(x_admin_token)
    if denied is not None:
        return denied

    resolved_id = _safe_template_id(template_id)
    if resolved_id is None:
        return _error_response(ERR_API_INPUT, "템플릿 이름에 쓸 수 없는 문자가 있습니다.")
    path = _resolve_template_path(resolved_id)
    if path is None:
        return _error_response(ERR_API_TEMPLATE_NOT_FOUND)

    try:
        await asyncio.to_thread(os.remove, path)
    except OSError as exc:
        log_error(
            "템플릿 파일 삭제 실패",
            event="template_delete_failed",
            resource_id=resolved_id,
            error_code=ERR_API_INTERNAL.code,
            error_type=type(exc).__name__,
        )
        return _error_response(ERR_API_INTERNAL, "템플릿을 삭제하지 못했습니다.")

    # 파일이 사라진 뒤에 색인이 남아 있으면 목록이 유령 템플릿을 보여준다
    await invalidate(resolved_id)
    log_info("템플릿 삭제 완료", event="template_deleted", resource_id=resolved_id)
    return JSONResponse(content={"template_id": resolved_id, "deleted": True})


async def _load_index(template_id: str):
    """템플릿 파일 + 색인을 함께 얻는다 (색인은 캐시 경유).

    Returns:
        ((template_bytes, TemplateIndex), None) 또는 (None, 오류 응답).
    """
    template_bytes = _load_template_bytes(template_id)
    if template_bytes is None:
        return None, _error_response(ERR_API_TEMPLATE_NOT_FOUND)
    try:
        index = await get_index(template_id, template_bytes)
    except TemplateError as exc:
        # 계약: TemplateError 메시지는 hwpx_fields.py 의 고정 안내문만 담는다
        return None, _error_response(ERR_API_INPUT, str(exc))
    return (template_bytes, index), None


@app.get("/fields")
async def fields(template_id: str):
    loaded, error = await _load_index(template_id)
    if error is not None:
        return error
    _, index = loaded
    return {
        "template_id": template_id,
        "fields": [_field_payload(s) for s in index.fields],
        "from_cache": index.from_cache,
    }


@app.get("/status")
async def status(session_id: str, template_id: str | None = None):
    """세션 채움 현황 — UI 가 다운로드 버튼 활성화를 판단할 때 사용."""
    try:
        session = await load_session(session_id)
    except ValueError:
        return _error_response(ERR_API_INPUT, "session_id 가 올바르지 않습니다.")
    resolved_template = (template_id or session.get("template_id") or "").strip()
    loaded, error = await _load_index(resolved_template)
    if error is not None:
        return error
    _, index = loaded

    values = session.get("values") or {}
    missing = [s.name for s in index.fields if s.name not in values and not s.filled]
    return {
        "template_id": resolved_template,
        "session_id": session_id,
        "values": values,
        "fields_missing": missing,
        "ready_for_download": not missing,
        "formats": _available_formats(),
    }


@app.get("/preview")
async def preview(session_id: str | None = None, template_id: str | None = None):
    """지금 값으로 **채운 결과**를 마크다운으로 돌려준다 (표시 전용, 파일 생성 아님).

    브라우저는 hwpx 를 렌더링하지 못한다. 그래서 다운로드 전에 확인할 수단이 필요하고,
    미리보기는 다운로드와 **같은 채우기 경로**를 타야 한다 — 별도 렌더러를 두면 화면과
    실제 파일이 어긋난다. 그래서 여기서도 `fill_template` 을 쓴다.

    서식(글꼴·크기)은 적용하지 않는다. 마크다운에는 반영할 자리가 없고, 명세 표기 제거는
    채우기 단계에서 이미 끝난다. 세션은 건드리지 않는다(다운로드만 세션을 종료한다).
    """
    session: dict = {}
    if session_id:
        try:
            session = await load_session(session_id)
        except ValueError:
            return _error_response(ERR_API_INPUT, "session_id 가 올바르지 않습니다.")
    resolved_template = (template_id or session.get("template_id") or "").strip()
    loaded, error = await _load_index(resolved_template)
    if error is not None:
        return error
    template_bytes, index = loaded

    values = _normalize_values(session.get("values") or {})
    try:
        result = fill_template(template_bytes, values, include_labels=Config.LABEL_FIELDS)
        rendered = render_markdown(result.hwpx_bytes, max_chars=Config.MAX_PREVIEW_CHARS)
    except TemplateError as exc:
        return _error_response(ERR_API_INPUT, str(exc))
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
        log_error(
            "미리보기 생성 중 내부 오류",
            event="preview_internal_error",
            resource_id=resolved_template,
            error_code=ERR_API_INTERNAL.code,
            error_type=type(exc).__name__,
        )
        return _error_response(ERR_API_INTERNAL, "미리보기를 만들지 못했습니다.")

    missing = [s.name for s in index.fields if s.name not in values and not s.filled]
    return {
        "template_id": resolved_template,
        "session_id": session_id or "",
        "markdown": rendered.markdown,
        # 잘린 미리보기를 문서 전체로 오인하면 빠진 항목을 못 보고 다운로드한다
        "truncated": rendered.truncated,
        "fields": [
            {**_field_payload(s), "value": values.get(s.name, "")} for s in index.fields
        ],
        "fields_missing": missing,
        "ready_for_download": not missing,
        "formats": _available_formats(),
    }


def _build_document(template_bytes: bytes, values: dict, template_label: str):
    """채우기 → 서식 명세 적용까지의 공통 파이프라인 (등록 템플릿/업로드 파일 공용).

    Returns:
        ((FillResult, 서식 적용 필드 목록), None) 또는 (None, 오류 응답).
    """
    try:
        result = fill_template(template_bytes, values, include_labels=Config.LABEL_FIELDS)
    except TemplateError as exc:
        # 계약: TemplateError 메시지는 hwpx_fields.py 의 고정 안내문만 담는다
        return None, _error_response(ERR_API_INPUT, str(exc))
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
        log_error(
            "hwpx 생성 중 내부 오류",
            event="generate_internal_error",
            error_code=ERR_API_INTERNAL.code,
            error_type=type(exc).__name__,
        )
        return None, _error_response(ERR_API_INTERNAL)

    # 템플릿(업로드 파일 포함)에 적힌 서식 명세를 반영한다. 명세가 없으면 아무 일도 없다.
    style_applied: list = []
    if Config.APPLY_STYLE_SPEC:
        try:
            styles = collect_style_specs(template_bytes)
            if styles:
                styled = apply_styles(result.hwpx_bytes, styles, scope=Config.STYLE_SCOPE)
                result = replace(result, hwpx_bytes=styled.hwpx_bytes)
                style_applied = styled.applied_fields
        except TemplateError:
            # 서식 적용 실패가 문서 생성을 막지 않는다 — 서식 없는 초안이라도 내려준다
            log_warning(
                "서식 명세를 적용하지 못했다 — 서식 미적용 문서로 진행",
                event="style_apply_failed",
                resource_id=template_label,
            )
        except Exception as exc:  # noqa: BLE001 - 서식은 부가 기능, 본 기능을 막지 않게
            log_warning(
                "서식 적용 중 예상 밖 오류 — 서식 미적용 문서로 진행",
                event="style_apply_error",
                resource_id=template_label,
                error_type=type(exc).__name__,
            )

    # 기록되지 않은 값·치환되지 않은 토큰은 침묵 처리하지 않는다 — 사용자가 말한 값이
    # 문서에 안 들어간 경우이므로 운영에서 잡아야 한다.
    if result.unknown_keys:
        log_warning(
            "템플릿에 없는 키가 있어 기록하지 못했다",
            event="generate_unknown_keys",
            resource_id=template_label,
            item_count=len(result.unknown_keys),
        )
    if result.leftover_tokens:
        log_warning(
            "치환되지 않은 토큰이 남았다",
            event="generate_leftover_tokens",
            resource_id=template_label,
            item_count=len(result.leftover_tokens),
        )
    return (result, style_applied), None


def _document_response(
    content: bytes, result, style_applied: list, filename_base: str, fmt: str
) -> Response:
    """문서 바이너리 + 부분 초안/서식 적용 정보를 헤더로 함께 내려준다."""
    filename = (filename_base or "초안").strip()
    for suffix in (".hwpx", ".pdf"):
        filename = filename.removesuffix(suffix)
    filename = f"{filename}.{fmt}"
    quoted = urllib.parse.quote(filename)  # 한글 파일명 → RFC 5987
    disposition = "attachment; filename*=UTF-8''" + quoted
    return Response(
        content=content,
        media_type="application/pdf" if fmt == "pdf" else "application/octet-stream",
        headers={
            "Content-Disposition": disposition,
            # 부분 초안 여부를 파일과 함께 전달 — 실패/누락을 침묵 처리하지 않는다
            "X-Missing-Fields": urllib.parse.quote(",".join(result.missing_fields)),
            "X-Written-Fields": urllib.parse.quote(",".join(result.written_fields)),
            # 어떤 필드에 서식 명세를 적용했는지 함께 알린다
            "X-Styled-Fields": urllib.parse.quote(",".join(style_applied)),
            "X-Document-Format": fmt,
        },
    )


async def _finalize_document(result, style_applied: list, filename_base: str, fmt: str):
    """요청 형식에 맞는 다운로드 응답을 만든다 (pdf 면 변환까지).

    Returns:
        (Response, None) 또는 (None, 오류 응답). 변환 실패를 성공 응답으로 감싸지 않으려고
        호출부에서 성공 여부를 구분할 수 있게 튜플로 돌려준다 — /generate 는 성공한
        경우에만 세션을 종료해야 한다 (실패 후 세션이 사라지면 사용자가 다시 시도할 수 없다).
    """
    if fmt != "pdf":
        return _document_response(
            result.hwpx_bytes, result, style_applied, filename_base, "hwpx"
        ), None
    try:
        pdf_bytes = await pdf_convert.to_pdf(result.hwpx_bytes)
    except PdfUnavailableError as exc:
        # 계약: 메시지는 pdf_convert.py 의 고정 안내문만 담는다
        log_warning(
            "PDF 미지원 환경에서 pdf 요청",
            event="pdf_unavailable",
            error_code=ERR_API_PDF_UNAVAILABLE.code,
            error_type=type(exc).__name__,
        )
        return None, _error_response(ERR_API_PDF_UNAVAILABLE)
    except PdfConvertError as exc:
        log_warning(
            "PDF 변환 실패",
            event="pdf_failed",
            error_code=ERR_API_PDF_FAILED.code,
            error_type=type(exc).__name__,
        )
        return None, _error_response(ERR_API_PDF_FAILED)
    return _document_response(
        pdf_bytes, result, style_applied, filename_base, "pdf"
    ), None


def _normalize_values(raw: dict) -> dict:
    return {str(k): str(v)[: Config.MAX_VALUE_CHARS] for k, v in (raw or {}).items()}


@app.post("/generate")
async def generate(body: GenerateRequest):
    """등록된 템플릿(TEMPLATE_DIR)으로 초안을 생성해 다운로드 응답으로 반환한다 (hwpx/pdf)."""
    started = time.monotonic()
    fmt, format_error = _resolve_format(body.format)
    if format_error is not None:
        return format_error
    values: dict = {}
    session_template = ""

    if body.session_id:
        try:
            session = await load_session(body.session_id)
        except ValueError:
            return _error_response(ERR_API_INPUT, "session_id 가 올바르지 않습니다.")
        values.update(session.get("values") or {})
        session_template = str(session.get("template_id") or "")

    if body.values:
        if len(body.values) > Config.MAX_FIELDS:
            return _error_response(
                ERR_API_INPUT, f"values 개수가 상한({Config.MAX_FIELDS}건)을 초과했습니다."
            )
        values.update(_normalize_values(body.values))

    if body.session_id and not values and not body.values:
        return _error_response(ERR_API_SESSION_NOT_FOUND)

    template_id = (body.template_id or session_template).strip()
    template_bytes = _load_template_bytes(template_id)
    if template_bytes is None:
        return _error_response(ERR_API_TEMPLATE_NOT_FOUND)

    built, error = _build_document(template_bytes, values, template_id)
    if error is not None:
        return error
    result, style_applied = built

    response, error = await _finalize_document(
        result, style_applied, body.filename or f"{template_id}_초안", fmt
    )
    if error is not None:
        # 변환 실패 시 세션을 남긴다 — 사용자가 형식을 바꿔 다시 시도할 수 있어야 한다
        return error

    # 부분 초안 여부(미입력 필드 수)는 운영에서 봐야 하는 수치다 — 필드명·값은 남기지 않는다
    log_info(
        "초안 생성 완료",
        event="generate_succeeded",
        resource_id=template_id,
        item_count=len(result.written_fields),
        status=(
            f"format={fmt} missing={len(result.missing_fields)}"
            f" styled={len(style_applied)}"
        ),
        duration_ms=int((time.monotonic() - started) * 1000),
    )

    # 문서 생성 성공 = 세션 종료. 수집 상태를 즉시 삭제한다(best-effort, TTL 안전망).
    if body.session_id:
        await end_session(body.session_id)

    return response


@app.post("/generate/upload")
async def generate_upload(
    template: UploadFile = File(..., description="채울 hwpx 템플릿 파일"),
    session_id: str | None = Form(None),
    values: str | None = Form(None, description="추가 값 JSON 문자열"),
    filename: str | None = Form(None),
    format: str | None = Form(None, description="hwpx(기본) | pdf"),
):
    """업로드한 hwpx 를 그대로 채워 내려준다 (템플릿 사전 등록 없이).

    TEMPLATE_DIR 에 미리 올려둔 템플릿이 아니라 이번 요청에 첨부된 파일을 쓴다.
    파일 안에 적힌 서식 명세(제목: {함초롬돋움, 16pt, bold})도 같은 파이프라인으로
    반영한다 — 업로드 경로만 다르고 처리 규칙은 동일하다.

    값의 출처 (둘 다 선택):
    - session_id: 대화(run_chat)에서 누적한 값
    - values: 이번 요청에서 직접 지정한 값 (세션 값 위에 덮어쓴다)
    """
    started = time.monotonic()
    fmt, format_error = _resolve_format(format)
    if format_error is not None:
        return format_error
    name = (template.filename or "").strip()
    if not name.lower().endswith(".hwpx"):
        return _error_response(ERR_API_INPUT, "hwpx 파일만 업로드할 수 있습니다.")

    # 크기 상한: 전량을 메모리에서 XML 파싱하므로 상한이 필요하다
    template_bytes = await template.read()
    if not template_bytes:
        return _error_response(ERR_API_INPUT, "업로드한 파일이 비어 있습니다.")
    if len(template_bytes) > Config.MAX_UPLOAD_BYTES:
        return _error_response(
            ERR_API_INPUT,
            f"파일 크기가 상한({Config.MAX_UPLOAD_BYTES // (1024 * 1024)}MB)을 초과했습니다.",
        )

    collected: dict = {}
    if session_id:
        try:
            session = await load_session(session_id)
        except ValueError:
            return _error_response(ERR_API_INPUT, "session_id 가 올바르지 않습니다.")
        collected.update(session.get("values") or {})

    if values:
        try:
            parsed = json.loads(values)
        except json.JSONDecodeError:
            return _error_response(ERR_API_INPUT, "values 는 JSON 객체여야 합니다.")
        if not isinstance(parsed, dict):
            return _error_response(ERR_API_INPUT, "values 는 JSON 객체여야 합니다.")
        if len(parsed) > Config.MAX_FIELDS:
            return _error_response(
                ERR_API_INPUT, f"values 개수가 상한({Config.MAX_FIELDS}건)을 초과했습니다."
            )
        collected.update(_normalize_values(parsed))

    label = os.path.splitext(os.path.basename(name))[0]
    built, error = _build_document(template_bytes, collected, label)
    if error is not None:
        return error
    result, style_applied = built

    response, error = await _finalize_document(
        result, style_applied, filename or f"{label}_초안", fmt
    )
    if error is not None:
        return error

    log_info(
        "업로드 템플릿으로 초안 생성 완료",
        event="generate_upload_succeeded",
        item_count=len(result.written_fields),
        status=(
            f"format={fmt} missing={len(result.missing_fields)}"
            f" styled={len(style_applied)}"
        ),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    if session_id:
        await end_session(session_id)

    return response
