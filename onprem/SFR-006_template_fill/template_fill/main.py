"""SFR-006 템플릿 채우기 — 코드 서빙 (area 03).

사용자가 채팅 UI 에서 **다운로드 버튼**을 누르면 호출되는 파일 생성 API.
대화(run_chat.py)가 세션에 누적해 둔 필드 값을 읽어 hwpx 초안을 만들어
바이너리로 반환한다.

엔드포인트
- GET  /health                    : 헬스체크 (가이드 필수)
- GET  /templates                 : 등록된 템플릿 목록
- GET  /fields?template_id=...    : 템플릿 누름틀 스키마
- GET  /status?session_id=...     : 세션 채움 현황 (다운로드 버튼 활성화 판단용)
- POST /generate                  : 등록된 템플릿으로 초안 생성 + 다운로드 응답
- POST /generate/upload           : **업로드한 hwpx** 로 초안 생성 (multipart)

GenOS 엔지니어 개발가이드 v1.02 반영
- 0.0.0.0:$PORT bind, /health 제공
- 오류 응답은 {error_code, msg} 형식 (3.9.5절), 예외 원문 미노출 (3.8절)
- 부분 초안 허용: 값이 없는 누름틀은 안내문 상태로 남겨 사용자가 한/글에서
  이어서 작성할 수 있게 한다 (missing_fields 를 응답 헤더로 알린다)
"""

import json
import os
import re
import time
import urllib.parse
from dataclasses import replace

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .config import Config
from .error_codes import (
    ERR_API_INPUT,
    ERR_API_INTERNAL,
    ERR_API_SESSION_NOT_FOUND,
    ERR_API_TEMPLATE_NOT_FOUND,
    ErrorCode,
)
from .hwpx_fields import TemplateError, fill_template, scan_fields
from .hwpx_style import apply_styles, collect_style_specs
from .logging_utils import configure_logging, log_error, log_info, log_warning
from .session_store import end_session, load_session

configure_logging(os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="hwpx-template-fill-service")

_TEMPLATE_NAME_RE = re.compile(r"^[\w\-. ()\[\]가-힣]+$")


class GenerateRequest(BaseModel):
    template_id: str | None = Field(None, max_length=256)
    session_id: str | None = Field(None, max_length=256)
    # 세션 없이 값 직접 지정도 허용 (테스트/단발 호출). 세션 값 위에 덮어쓴다.
    values: dict[str, str] | None = None
    filename: str | None = Field(None, max_length=128)


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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/templates")
async def templates() -> dict:
    if not os.path.isdir(Config.TEMPLATE_DIR):
        return {"templates": []}
    names = sorted(
        os.path.splitext(n)[0]
        for n in os.listdir(Config.TEMPLATE_DIR)
        if n.endswith(".hwpx")
    )
    return {"templates": names}


@app.get("/fields")
async def fields(template_id: str):
    template_bytes = _load_template_bytes(template_id)
    if template_bytes is None:
        return _error_response(ERR_API_TEMPLATE_NOT_FOUND)
    try:
        specs = scan_fields(template_bytes)
    except TemplateError as exc:
        # 계약: TemplateError 메시지는 hwpx_fields.py 의 고정 안내문만 담는다
        return _error_response(ERR_API_INPUT, str(exc))
    return {
        "template_id": template_id,
        "fields": [
            {
                "name": s.name,
                "guide": s.guide,
                "occurrences": s.occurrences,
                "filled": s.filled,
                "current_value": s.current_value,
            }
            for s in specs
        ],
    }


@app.get("/status")
async def status(session_id: str, template_id: str | None = None):
    """세션 채움 현황 — UI 가 다운로드 버튼 활성화를 판단할 때 사용."""
    try:
        session = await load_session(session_id)
    except ValueError:
        return _error_response(ERR_API_INPUT, "session_id 가 올바르지 않습니다.")
    resolved_template = (template_id or session.get("template_id") or "").strip()
    template_bytes = _load_template_bytes(resolved_template)
    if template_bytes is None:
        return _error_response(ERR_API_TEMPLATE_NOT_FOUND)
    try:
        specs = scan_fields(template_bytes)
    except TemplateError as exc:
        return _error_response(ERR_API_INPUT, str(exc))

    values = session.get("values") or {}
    missing = [s.name for s in specs if s.name not in values and not s.filled]
    return {
        "template_id": resolved_template,
        "session_id": session_id,
        "values": values,
        "fields_missing": missing,
        "ready_for_download": not missing,
    }


def _build_document(template_bytes: bytes, values: dict, template_label: str):
    """채우기 → 서식 명세 적용까지의 공통 파이프라인 (등록 템플릿/업로드 파일 공용).

    Returns:
        ((FillResult, 서식 적용 필드 목록), None) 또는 (None, 오류 응답).
    """
    try:
        result = fill_template(template_bytes, values)
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


def _document_response(result, style_applied: list, filename_base: str) -> Response:
    """hwpx 바이너리 + 부분 초안/서식 적용 정보를 헤더로 함께 내려준다."""
    filename = (filename_base or "초안").strip()
    if not filename.endswith(".hwpx"):
        filename += ".hwpx"
    quoted = urllib.parse.quote(filename)  # 한글 파일명 → RFC 5987
    disposition = "attachment; filename*=UTF-8''" + quoted
    return Response(
        content=result.hwpx_bytes,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": disposition,
            # 부분 초안 여부를 파일과 함께 전달 — 실패/누락을 침묵 처리하지 않는다
            "X-Missing-Fields": urllib.parse.quote(",".join(result.missing_fields)),
            "X-Written-Fields": urllib.parse.quote(",".join(result.written_fields)),
            # 어떤 필드에 서식 명세를 적용했는지 함께 알린다
            "X-Styled-Fields": urllib.parse.quote(",".join(style_applied)),
        },
    )


def _normalize_values(raw: dict) -> dict:
    return {str(k): str(v)[: Config.MAX_VALUE_CHARS] for k, v in (raw or {}).items()}


@app.post("/generate")
async def generate(body: GenerateRequest):
    """등록된 템플릿(TEMPLATE_DIR)으로 hwpx 초안을 생성해 다운로드 응답으로 반환한다."""
    started = time.monotonic()
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

    # 부분 초안 여부(미입력 필드 수)는 운영에서 봐야 하는 수치다 — 필드명·값은 남기지 않는다
    log_info(
        "hwpx 초안 생성 완료",
        event="generate_succeeded",
        resource_id=template_id,
        item_count=len(result.written_fields),
        status=f"missing={len(result.missing_fields)} styled={len(style_applied)}",
        duration_ms=int((time.monotonic() - started) * 1000),
    )

    # 문서 생성 성공 = 세션 종료. 수집 상태를 즉시 삭제한다(best-effort, TTL 안전망).
    if body.session_id:
        await end_session(body.session_id)

    return _document_response(result, style_applied, body.filename or f"{template_id}_초안")


@app.post("/generate/upload")
async def generate_upload(
    template: UploadFile = File(..., description="채울 hwpx 템플릿 파일"),
    session_id: str | None = Form(None),
    values: str | None = Form(None, description="추가 값 JSON 문자열"),
    filename: str | None = Form(None),
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

    log_info(
        "업로드 템플릿으로 hwpx 초안 생성 완료",
        event="generate_upload_succeeded",
        item_count=len(result.written_fields),
        status=f"missing={len(result.missing_fields)} styled={len(style_applied)}",
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    if session_id:
        await end_session(session_id)

    return _document_response(result, style_applied, filename or f"{label}_초안")
