"""SFR-006 템플릿 채우기 — 코드 서빙 (area 03).

사용자가 채팅 UI 에서 **다운로드 버튼**을 누르면 호출되는 파일 생성 API.
대화(run_chat.py)가 세션에 누적해 둔 필드 값을 읽어 hwpx 초안을 만들어
바이너리로 반환한다.

엔드포인트
- GET  /health                    : 헬스체크 (가이드 필수)
- GET  /templates                 : 등록된 템플릿 목록
- GET  /fields?template_id=...    : 템플릿 누름틀 스키마
- GET  /status?session_id=...     : 세션 채움 현황 (다운로드 버튼 활성화 판단용)
- POST /generate                  : hwpx 초안 생성 + 다운로드 응답

GenOS 엔지니어 개발가이드 v1.02 반영
- 0.0.0.0:$PORT bind, /health 제공
- 오류 응답은 {error_code, msg} 형식 (3.9.5절), 예외 원문 미노출 (3.8절)
- 부분 초안 허용: 값이 없는 누름틀은 안내문 상태로 남겨 사용자가 한/글에서
  이어서 작성할 수 있게 한다 (missing_fields 를 응답 헤더로 알린다)
"""

import logging
import os
import re
import urllib.parse

from fastapi import FastAPI
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
from .session_store import load_session

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
_log = logging.getLogger(__name__)

app = FastAPI(title="hwpx-template-fill-service")

_TEMPLATE_NAME_RE = re.compile(r"^[\w\-. ()\[\]가-힣]+$")


class GenerateRequest(BaseModel):
    template_id: str | None = Field(None, max_length=256)
    session_id: str | None = Field(None, max_length=256)
    # 세션 없이 값 직접 지정도 허용 (테스트/단발 호출). 세션 값 위에 덮어쓴다.
    values: dict[str, str] | None = None
    filename: str | None = Field(None, max_length=128)


def _error_response(err: ErrorCode, msg: str | None = None) -> JSONResponse:
    _log.warning(
        "template-fill api error",
        extra={"error_code": err.code, "error_type": err.error_type},
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
        session = load_session(session_id)
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


@app.post("/generate")
async def generate(body: GenerateRequest):
    """세션(및 추가 values)으로 hwpx 초안을 생성해 다운로드 응답으로 반환한다."""
    values: dict = {}
    session_template = ""

    if body.session_id:
        try:
            session = load_session(body.session_id)
        except ValueError:
            return _error_response(ERR_API_INPUT, "session_id 가 올바르지 않습니다.")
        values.update(session.get("values") or {})
        session_template = str(session.get("template_id") or "")

    if body.values:
        if len(body.values) > Config.MAX_FIELDS:
            return _error_response(
                ERR_API_INPUT, f"values 개수가 상한({Config.MAX_FIELDS}건)을 초과했습니다."
            )
        values.update(
            {str(k): str(v)[: Config.MAX_VALUE_CHARS] for k, v in body.values.items()}
        )

    if body.session_id and not values and not body.values:
        return _error_response(ERR_API_SESSION_NOT_FOUND)

    template_id = (body.template_id or session_template).strip()
    template_bytes = _load_template_bytes(template_id)
    if template_bytes is None:
        return _error_response(ERR_API_TEMPLATE_NOT_FOUND)

    try:
        result = fill_template(template_bytes, values)
    except TemplateError as exc:
        return _error_response(ERR_API_INPUT, str(exc))
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
        _log.error(
            "template-fill generate internal error",
            extra={"error_code": ERR_API_INTERNAL.code, "error_type": type(exc).__name__},
        )
        return _error_response(ERR_API_INTERNAL)

    filename = (body.filename or f"{template_id}_초안").strip()
    if not filename.endswith(".hwpx"):
        filename += ".hwpx"
    quoted = urllib.parse.quote(filename)  # 한글 파일명 → RFC 5987

    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
        # 부분 초안 여부를 파일과 함께 전달 — 실패/누락을 침묵 처리하지 않는다
        "X-Missing-Fields": urllib.parse.quote(",".join(result.missing_fields)),
        "X-Written-Fields": urllib.parse.quote(",".join(result.written_fields)),
    }
    return Response(
        content=result.hwpx_bytes,
        media_type="application/octet-stream",
        headers=headers,
    )
