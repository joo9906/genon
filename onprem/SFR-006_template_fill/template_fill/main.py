"""SFR-006 템플릿 채우기 — 코드 서빙 (area 03).

사용자가 채팅 UI 에서 **다운로드 버튼**을 누르면 호출되는 파일 생성 API. 대화
(`run_chat.py`)가 세션에 누적해 둔 값·본문을 읽어 hwpx 초안을 만들어 바이너리로 반환한다.

## 이 파일의 역할은 **배선뿐**이다

문서 조립은 `document.py`, 세션·화면 조립은 `session_view.py`, 템플릿 볼륨은
`template_store.py` 가 한다. 여기서는 요청을 받아 그 셋을 부르고 결과를 HTTP 로 바꾼다.
오류는 `ApiError` 예외 하나로 올라와 `api_errors.install()` 이 건 핸들러가 응답으로 바꾼다.

## 엔드포인트
## 엔드포인트

| 경로 | 하는 일 |
|---|---|
| `GET /health` | 헬스체크 (가이드 필수) |
| `GET /templates` | 등록된 템플릿 목록 (+ 색인 상태) |
| `POST /templates` | **관리자** 템플릿 등록 (업로드 + 즉시 색인) |
| `DELETE /templates/{id}` | **관리자** 템플릿 삭제 (+ 색인 폐기) |
| `GET /fields` | 항목 스키마 + 본문 블록 서식 목록 |
| `GET /status` | 세션 채움 현황 (다운로드 버튼 활성화 판단용) |
| `GET /preview` | 채운 결과를 마크다운으로 (표시 전용) |
| `PATCH /values` | 화면에서 고친 항목 값을 세션에 반영 |
| `DELETE /values` | 화면에서 항목 값 비우기 |
| `PUT /blocks` | 본문 추가 내용 목록을 통째로 교체 |
| `POST /generate` | 등록 템플릿으로 초안 생성 + 다운로드 (hwpx/pdf) |
| `POST /generate/upload` | **업로드한 hwpx** 로 초안 생성 (multipart) |

## 가이드 반영 (v1.02)

- 0.0.0.0:$PORT bind, `/health` 제공
- 오류 응답은 `{error_code, msg}` (3.9.5절), 예외 원문 미노출 (3.8절)
- blocking I/O(zip·XML·파일)는 전부 `asyncio.to_thread` (6.9절)
- **부분 초안 허용**: 값이 없는 항목은 그대로(라벨은 `제목:`, 누름틀은 안내문) 남겨
  사용자가 한/글에서 이어서 작성하게 한다. 무엇이 비었는지는 응답 헤더로 알린다.
"""

import asyncio
import json
import os
import time
import urllib.parse

from fastapi import FastAPI, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import document, pdf_convert, session_view, template_store
from .api_errors import ApiError, install as install_error_handler
from .config import Config
from .error_codes import (
    ERR_API_ADMIN_FORBIDDEN,
    ERR_API_INPUT,
    ERR_API_INTERNAL,
    ERR_API_PDF_FAILED,
    ERR_API_PDF_UNAVAILABLE,
    ERR_API_SESSION_NOT_FOUND,
    ERR_API_TEMPLATE_EXISTS,
)
from .field_judge import normalize_blocks
from .hwpx_blocks import block_style_names
from .hwpx_fields import TemplateError
from .logging_utils import configure_logging, log_info, log_warning
from .pdf_convert import PdfConvertError, PdfUnavailableError
from .session_store import end_session, load_session
from .template_index import build_index_async, invalidate, peek_index, store_index

configure_logging(os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="hwpx-template-fill-service")
install_error_handler(app)

_DOCUMENT_FORMATS = ("hwpx", "pdf")

if not Config.ADMIN_TOKEN:
    # 인증 부재를 조용히 넘기지 않는다 — 배포자가 보호되고 있다고 착각하면
    # 누구나 템플릿을 덮어쓸 수 있는 상태로 운영된다.
    log_warning(
        "TEMPLATE_FILL_ADMIN_TOKEN 미설정 — 템플릿 등록/삭제가 인증 없이 열려 있다",
        event="admin_token_missing",
        status="open",
    )


# ─────────────────────────────────────────────────────────────
# 요청 스키마
# ─────────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    template_id: str | None = Field(None, max_length=256)
    session_id: str | None = Field(None, max_length=256)
    # 세션 없이 값 직접 지정도 허용 (테스트/단발 호출). 세션 값 위에 덮어쓴다.
    values: dict[str, str] | None = None
    filename: str | None = Field(None, max_length=128)
    # hwpx(기본) | pdf. PDF 는 전처리기 변환기를 호출하며 환경에 따라 미지원일 수 있다.
    format: str | None = Field(None, max_length=8)
    # 템플릿 항목 밖에 이어 쓸 본문. 생략하면 **세션에 쌓인 것**을 쓴다.
    blocks: list | None = None


class ValuePatchRequest(BaseModel):
    session_id: str = Field(..., max_length=256)
    template_id: str | None = Field(None, max_length=256)
    values: dict[str, str] = Field(default_factory=dict)
    # 응답에 채운 결과 마크다운을 포함할지 (연속 편집이면 끄는 편이 가볍다)
    preview: bool = True


class ValueDeleteRequest(BaseModel):
    session_id: str = Field(..., max_length=256)
    template_id: str | None = Field(None, max_length=256)
    fields: list[str] = Field(default_factory=list)
    preview: bool = True


class BlockPutRequest(BaseModel):
    session_id: str = Field(..., max_length=256)
    template_id: str | None = Field(None, max_length=256)
    # 전체 목록을 그대로 받는다 (부분 갱신이 아니다) — 이유는 PUT /blocks docstring 참고
    blocks: list = Field(default_factory=list)
    preview: bool = True


# ─────────────────────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────────────────────
def _require_admin(token: str | None) -> None:
    """관리자 토큰 검사. 토큰이 설정돼 있지 않으면 검사하지 않는다(기동 시 경고를 남긴다)."""
    if not Config.ADMIN_TOKEN:
        return
    if (token or "").strip() != Config.ADMIN_TOKEN:
        raise ApiError(ERR_API_ADMIN_FORBIDDEN)


def _resolve_format(raw: str | None) -> str:
    fmt = (raw or "hwpx").strip().lower()
    if fmt not in _DOCUMENT_FORMATS:
        raise ApiError(ERR_API_INPUT, "format 은 hwpx 또는 pdf 여야 합니다.")
    return fmt


def _normalize_values(raw: dict) -> dict:
    return {str(k): str(v)[: Config.MAX_VALUE_CHARS] for k, v in (raw or {}).items()}


def _check_value_count(values) -> None:
    if values and len(values) > Config.MAX_FIELDS:
        raise ApiError(
            ERR_API_INPUT, f"values 개수가 상한({Config.MAX_FIELDS}건)을 초과했습니다."
        )


async def _read_upload(template: UploadFile) -> bytes:
    """업로드 파일을 읽고 형식·크기를 검증한다 (등록·즉석 생성 공용)."""
    name = (template.filename or "").strip()
    if not name.lower().endswith(".hwpx"):
        raise ApiError(ERR_API_INPUT, "hwpx 파일만 업로드할 수 있습니다.")
    payload = await template.read()
    if not payload:
        raise ApiError(ERR_API_INPUT, "업로드한 파일이 비어 있습니다.")
    # 전량을 메모리에서 XML 파싱하므로 상한이 필요하다
    if len(payload) > Config.MAX_UPLOAD_BYTES:
        raise ApiError(
            ERR_API_INPUT,
            f"파일 크기가 상한({Config.MAX_UPLOAD_BYTES // (1024 * 1024)}MB)을 초과했습니다.",
        )
    return payload


async def _resolve_blocks(template_id: str, template_bytes: bytes, raw_blocks) -> list:
    """문서 생성 직전에 본문 블록을 검증한다 (`/generate`, `/generate/upload` 공용).

    서식 화이트리스트의 출처가 두 경로에서 다르다 — 등록 템플릿은 색인(캐시)에서,
    업로드 파일은 그 자리에서 파싱해 얻는다. 블록이 없으면 둘 다 하지 않는다
    (블록을 안 쓰는 호출에 파싱·Redis 왕복을 얹지 않는다).
    """
    if not Config.BODY_BLOCKS or not raw_blocks:
        return []
    if template_id:
        _, index = await session_view.load_index(template_id)
        styles = list(index.block_styles)
    else:
        try:
            styles = await asyncio.to_thread(block_style_names, template_bytes)
        except TemplateError as exc:
            raise ApiError(ERR_API_INPUT, str(exc)) from exc

    blocks, rejected = normalize_blocks(raw_blocks, styles)
    if rejected:
        log_warning(
            "본문 블록 일부를 기각했다",
            event="generate_blocks_rejected",
            resource_id=template_id or "upload",
            item_count=len(rejected),
        )
    return blocks


async def _build(template_bytes: bytes, values: dict, blocks: list, label: str):
    """조립 파이프라인을 스레드에서 돌리고 실패를 HTTP 오류로 바꾼다.

    파이프라인 자체(`document.build`)는 HTTP 를 모른다 — 여기가 그 경계다.
    """
    try:
        return await asyncio.to_thread(
            document.build, template_bytes, values, blocks, label=label
        )
    except TemplateError as exc:
        # 계약: TemplateError 메시지는 도메인 모듈이 만든 고정 안내문만 담는다
        raise ApiError(ERR_API_INPUT, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
        log_warning(
            "hwpx 생성 중 내부 오류",
            event="generate_internal_error",
            resource_id=label,
            error_code=ERR_API_INTERNAL.code,
            error_type=type(exc).__name__,
        )
        raise ApiError(ERR_API_INTERNAL) from exc


def _download_response(content: bytes, built, filename_base: str, fmt: str) -> Response:
    """문서 바이너리 + 부분 초안/서식/블록 정보를 헤더로 함께 내려준다."""
    filename = (filename_base or "초안").strip()
    for suffix in (".hwpx", ".pdf"):
        filename = filename.removesuffix(suffix)
    quoted = urllib.parse.quote(f"{filename}.{fmt}")  # 한글 파일명 → RFC 5987
    return Response(
        content=content,
        media_type="application/pdf" if fmt == "pdf" else "application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quoted,
            # 부분 초안 여부를 파일과 함께 전달 — 누락을 침묵 처리하지 않는다
            "X-Missing-Fields": urllib.parse.quote(",".join(built.missing_fields)),
            "X-Written-Fields": urllib.parse.quote(",".join(built.written_fields)),
            "X-Styled-Fields": urllib.parse.quote(",".join(built.styled_fields)),
            "X-Body-Blocks": str(built.appended_blocks),
            # 표 셀을 넘칠 것으로 추정된 항목. 문서는 정상이고 서식만 흐트러질 수 있다 —
            # 막지 않고 알린다 (`overflow.py` 모듈 docstring).
            "X-Overflow-Fields": urllib.parse.quote(
                ",".join(item["field"] for item in built.overflow)
            ),
            # 개봉 안전 검사를 **실제로 했는지**. 0 은 통과가 아니라 미판정이다 —
            # 검사 없이 나간 파일을 검사 통과처럼 보이게 하지 않는다.
            "X-Open-Safety-Checked": "1" if built.open_safety_checked else "0",
            "X-Document-Format": fmt,
        },
    )


async def _finalize(built, filename_base: str, fmt: str) -> Response:
    """요청 형식에 맞는 다운로드 응답을 만든다 (pdf 면 변환까지).

    변환에 실패하면 `ApiError` 가 올라가므로 **호출부의 세션 종료 코드에 도달하지 않는다** —
    사용자가 형식을 바꿔 다시 시도할 수 있어야 하기 때문이다. 예전에는 이 성질을
    `(응답, 오류)` 튜플과 `if error: return` 으로 지켰는데, 예외가 그 순서를 강제한다.
    """
    if fmt != "pdf":
        return _download_response(built.hwpx_bytes, built, filename_base, "hwpx")
    try:
        pdf_bytes = await pdf_convert.to_pdf(built.hwpx_bytes)
    except PdfUnavailableError as exc:
        log_warning(
            "PDF 미지원 환경에서 pdf 요청",
            event="pdf_unavailable",
            error_code=ERR_API_PDF_UNAVAILABLE.code,
            error_type=type(exc).__name__,
        )
        raise ApiError(ERR_API_PDF_UNAVAILABLE) from exc
    except PdfConvertError as exc:
        log_warning(
            "PDF 변환 실패",
            event="pdf_failed",
            error_code=ERR_API_PDF_FAILED.code,
            error_type=type(exc).__name__,
        )
        raise ApiError(ERR_API_PDF_FAILED) from exc
    return _download_response(pdf_bytes, built, filename_base, "pdf")


# ─────────────────────────────────────────────────────────────
# 헬스체크 · 템플릿 관리
# ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/")
@app.get("")
async def root() -> dict:
    """게이트웨이가 서빙 베이스를 경로 없이 때리는 배포가 있다 (운영 app.py 대조 결과).

    거기서 404 가 나면 배선이 잘못된 것처럼 보이므로 최소 정보를 돌려준다.
    018 두 단위와 같은 규약이다.

    **`""` 와 `"/"` 를 둘 다 등록해야 한다** (2026-08-11 수정). `@app.get("")` 만 두면
    **아무 경로에도 매칭되지 않는다** — ASGI 요청의 path 는 최소 `/` 라서 빈 문자열
    라우트는 영영 닿지 않고, `/` 라우트는 등록된 적이 없으니 둘 다 404 다. 2026-08-07 에
    이 라우트를 넣고 "루트 경로를 맞췄다" 고 적었지만 실제로는 동작하지 않았다.
    """
    return {"service": "template-fill-service", "status": "ok"}


@app.get("/templates")
async def templates() -> dict:
    """등록된 템플릿 목록.

    색인 정보는 **캐시에 있는 것만** 붙인다. 목록을 만들 때마다 모든 템플릿을 열어
    파싱하면 목록 조회 한 번이 전체 파싱이 된다. 색인이 없으면 `indexed: false` 로
    정직하게 표시하고, 그 템플릿의 `/fields` 첫 호출이 색인을 만든다.
    """
    names = await template_store.list_ids()
    # 템플릿마다 순차로 await 하면 목록 지연이 (템플릿 수 × Redis 왕복)이 된다
    indexes = await asyncio.gather(*(peek_index(name) for name in names))
    return {
        "templates": names,
        "items": [
            {
                "template_id": name,
                "indexed": index is not None,
                "field_count": len(index.fields) if index else None,
                "table_count": index.table_count if index else None,
                "indexed_at": index.indexed_at if index else None,
            }
            for name, index in zip(names, indexes)
        ],
        "formats": session_view.available_formats(),
    }


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

    **파싱이 먼저, 파일 쓰기가 나중이다.** 순서를 바꾸면 해석 불가 파일이 볼륨에 남는다.
    """
    _require_admin(x_admin_token)
    template_bytes = await _read_upload(template)
    resolved_id = template_store.safe_id(template_id or os.path.basename(template.filename or ""))

    exists = await template_store.exists(resolved_id)
    if exists and not overwrite:
        raise ApiError(ERR_API_TEMPLATE_EXISTS)

    try:
        index = await build_index_async(resolved_id, template_bytes)
    except TemplateError as exc:
        raise ApiError(ERR_API_INPUT, str(exc)) from exc

    await template_store.write(resolved_id, template_bytes)
    await store_index(index)

    log_info(
        "템플릿 등록 완료",
        event="template_registered",
        resource_id=resolved_id,
        item_count=len(index.fields),
        status=(
            f"overwritten={int(exists)} tables={index.table_count} "
            f"bare_braces={len(index.bare_braces)}"
        ),
    )
    if index.bare_braces:
        # 따옴표를 빠뜨린 오타일 수도, 값 안내를 일부러 적은 것일 수도 있다. 코드가
        # 판단하지 않고 등록자에게 보여 준다 — 조용히 넘기면 채워질 줄 알았던 자리가
        # 빈 채로 배포된다 (침묵 처리 금지 규약).
        log_warning(
            "따옴표 없는 중괄호가 있어 채울 자리로 잡히지 않았다",
            event="template_bare_braces",
            resource_id=resolved_id,
            item_count=len(index.bare_braces),
        )
    return JSONResponse(
        status_code=200 if exists else 201,
        content={
            "template_id": resolved_id,
            "overwritten": exists,
            "content_hash": index.content_hash,
            "fields": [session_view.field_payload(s) for s in index.fields],
            "block_styles": list(index.block_styles) if Config.BODY_BLOCKS else [],
            "markdown": index.markdown,
            "markdown_truncated": index.truncated,
            # 채울 자리로 보지 않은 `{…}` — 관리자가 따옴표 누락인지 판단할 근거다.
            "bare_braces": list(index.bare_braces),
        },
    )


@app.delete("/templates/{template_id}")
async def delete_template(template_id: str, x_admin_token: str | None = Header(None)) -> Response:
    """관리자 템플릿 삭제 — 파일과 색인을 함께 없앤다."""
    _require_admin(x_admin_token)
    resolved_id = template_store.safe_id(template_id)
    await template_store.remove(resolved_id)
    # 파일이 사라진 뒤에 색인이 남아 있으면 목록이 유령 템플릿을 보여준다
    await invalidate(resolved_id)
    log_info("템플릿 삭제 완료", event="template_deleted", resource_id=resolved_id)
    return JSONResponse(content={"template_id": resolved_id, "deleted": True})


@app.get("/fields")
async def fields(template_id: str) -> dict:
    _, index = await session_view.load_index(template_id)
    return {
        "template_id": template_id,
        "fields": [session_view.field_payload(s) for s in index.fields],
        # 본문 블록의 서식으로 지정할 수 있는 항목명 — 화면의 선택지가 된다
        "block_styles": list(index.block_styles) if Config.BODY_BLOCKS else [],
        "from_cache": index.from_cache,
    }


# ─────────────────────────────────────────────────────────────
# 세션 상태 조회
# ─────────────────────────────────────────────────────────────
@app.get("/status")
async def status(session_id: str, template_id: str | None = None) -> dict:
    """세션 채움 현황 — UI 가 다운로드 버튼 활성화를 판단할 때 사용.

    마크다운을 만들지 않는 가벼운 경로다(그래서 `/preview` 와 따로 있다). 부족 항목
    판정은 `session_view` 가 쥔 하나를 공유한다 — 각자 적어 두면 다운로드 버튼과 대화가
    서로 다른 `ready` 를 보고한다.
    """
    context = await session_view.load_context(session_id, template_id)
    missing = context.missing
    return {
        "template_id": context.template_id,
        "session_id": session_id,
        "values": context.values,
        "fields_missing": missing,
        # 본문 블록은 `ready_for_download` 에 관여하지 않는다 — 항목이 아니라 **덤**이라
        # 0개여도 문서는 완성이다. 개수만 알려 화면이 표시할 수 있게 한다.
        "block_count": len(context.blocks),
        "ready_for_download": not missing,
        "formats": session_view.available_formats(),
    }


@app.get("/preview")
async def preview(session_id: str | None = None, template_id: str | None = None) -> dict:
    """지금 값으로 **채운 결과**를 마크다운으로 돌려준다 (표시 전용, 파일 생성 아님).

    브라우저는 hwpx 를 렌더링하지 못한다. 그래서 다운로드 전에 확인할 수단이 필요하고,
    미리보기는 다운로드와 **같은 조립 파이프라인**(`document.build`)을 탄다 — 서식만
    건너뛴다(마크다운에 반영할 자리가 없다). 세션은 건드리지 않는다.
    """
    context = await session_view.load_context(session_id, template_id, require_session=False)
    return await session_view.compose_view_async(context)


# ─────────────────────────────────────────────────────────────
# 화면에서 직접 편집 (대화를 거치지 않는 경로)
# ─────────────────────────────────────────────────────────────
@app.patch("/values")
async def patch_values(body: ValuePatchRequest) -> dict:
    """화면에서 고친 항목 값을 세션에 반영한다.

    판정 책임은 대화 경로와 같다 — **코드가 화이트리스트로 검증한다.** 템플릿에 없는
    항목명은 기각하고 건수를 응답·로그에 노출한다(침묵 처리 금지). 값이 빈 문자열이면
    "지움"으로 처리하고 `cleared_fields` 로 알린다 — 화면의 빈 입력칸은 지우겠다는 뜻이고,
    그걸 조용히 무시하면 사용자는 지웠다고 믿은 값을 그대로 다운로드한다.

    톤 변환 원본(`raw_values`)도 함께 갱신한다. 직접 고친 값이 곧 원본이므로, 나중에
    톤 설정이 바뀌어도 옛 문구가 되살아나지 않는다.
    """
    _check_value_count(body.values)
    context = await session_view.load_context(body.session_id, body.template_id)
    allowed = context.field_names

    accepted: dict = {}
    cleared: list = []
    rejected: list = []
    for raw_name, raw_value in body.values.items():
        name = str(raw_name).strip()
        if name not in allowed:
            rejected.append(name)
            continue
        text = str(raw_value or "").strip()[: Config.MAX_VALUE_CHARS]
        if not text:
            context.values.pop(name, None)
            context.raw_values.pop(name, None)
            cleared.append(name)
            continue
        accepted[name] = text

    context.values.update(accepted)
    context.raw_values.update(accepted)
    await session_view.save_state(context)

    if rejected:
        # 템플릿에 없는 항목명을 화면이 보냈다는 뜻 — 스키마 불일치 신호다
        log_warning(
            "템플릿에 없는 항목명을 기각",
            event="values_patch_rejected",
            resource_id=context.template_id,
            item_count=len(rejected),
        )
    log_info(
        "항목 값 직접 수정",
        event="values_patched",
        resource_id=context.template_id,
        item_count=len(accepted),
        status=f"cleared={len(cleared)} rejected={len(rejected)}",
    )

    payload = await session_view.compose_view_async(context, body.preview)
    return {
        **payload,
        "updated_fields": sorted(accepted),
        "cleared_fields": sorted(cleared),
        "rejected_fields": sorted(rejected),
    }


@app.delete("/values")
async def delete_values(body: ValueDeleteRequest) -> dict:
    """화면에서 항목 값을 비운다 (여러 개를 한 번에).

    지우는 대상은 **세션에 모인 값**이다. 템플릿 자체에 이미 적혀 있던 값(`filled=True`)은
    문서에 남으므로, 지운 뒤에도 그 항목은 채워진 상태로 보일 수 있다 — 화면이 그 차이를
    표시할 수 있도록 `still_filled_in_template` 로 함께 알린다.
    """
    context = await session_view.load_context(body.session_id, body.template_id)
    specs = {spec.name: spec for spec in context.index.fields}

    removed: list = []
    unknown: list = []
    still_filled: list = []
    for raw_name in body.fields:
        name = str(raw_name).strip()
        if name not in specs:
            unknown.append(name)
            continue
        if context.values.pop(name, None) is not None:
            removed.append(name)
        context.raw_values.pop(name, None)
        if specs[name].filled:
            still_filled.append(name)

    await session_view.save_state(context)
    log_info(
        "항목 값 삭제",
        event="values_deleted",
        resource_id=context.template_id,
        item_count=len(removed),
        status=f"unknown={len(unknown)} template_filled={len(still_filled)}",
    )

    payload = await session_view.compose_view_async(context, body.preview)
    return {
        **payload,
        "deleted_fields": sorted(removed),
        "rejected_fields": sorted(unknown),
        "still_filled_in_template": sorted(still_filled),
    }


@app.put("/blocks")
async def put_blocks(body: BlockPutRequest) -> dict:
    """본문 블록 목록을 세션에 통째로 반영한다 (대화를 거치지 않는 직접 편집).

    항목 값(`PATCH /values`)과 달리 **배열 통째 교체**인 이유: 블록은 순서가 의미를 갖는
    목록이라 부분 갱신을 하려면 화면과 서버가 같은 인덱스를 공유해야 하고, 한 번만
    어긋나도 다른 문단이 지워진다. 화면이 가진 목록을 그대로 보내면 그 문제가 없다.
    빈 배열이면 전부 삭제.

    서식 이름(`style_ref`)은 템플릿 화이트리스트로 검증하고, 목록에 없으면 기본 서식으로
    떨어뜨린 뒤 `rejected_blocks` 로 알린다 — 이름이 틀렸다고 본문을 버리지 않는다.

    여기서 쓴 본문은 **다듬지 않는다**(톤 미적용). 사용자가 타이핑한 것이 곧 최종이다
    (`PATCH /values` 가 raw=value 로 두는 것과 같은 규칙).
    """
    if not Config.BODY_BLOCKS:
        raise ApiError(ERR_API_INPUT, "본문 추가 기능이 꺼져 있습니다.")

    context = await session_view.load_context(body.session_id, body.template_id)
    blocks, rejected = normalize_blocks(body.blocks, context.index.block_styles)
    context.blocks = blocks
    await session_view.save_state(context)

    if rejected:
        log_warning(
            "본문 블록 일부를 기각했다",
            event="blocks_put_rejected",
            resource_id=context.template_id,
            item_count=len(rejected),
        )
    log_info(
        "본문 블록 직접 수정",
        event="blocks_put",
        resource_id=context.template_id,
        item_count=len(blocks),
        status=f"rejected={len(rejected)}",
    )

    payload = await session_view.compose_view_async(context, body.preview)
    return {**payload, "rejected_blocks": rejected}


# ─────────────────────────────────────────────────────────────
# 문서 생성 (다운로드 버튼)
# ─────────────────────────────────────────────────────────────
@app.post("/generate")
async def generate(body: GenerateRequest) -> Response:
    """등록된 템플릿(TEMPLATE_DIR)으로 초안을 생성해 다운로드 응답으로 반환한다."""
    started = time.monotonic()
    fmt = _resolve_format(body.format)

    values: dict = {}
    session_template = ""
    session_blocks: list = []
    if body.session_id:
        try:
            session = await load_session(body.session_id)
        except ValueError as exc:
            raise ApiError(ERR_API_INPUT, "session_id 가 올바르지 않습니다.") from exc
        values.update(session.get("values") or {})
        session_template = str(session.get("template_id") or "")
        session_blocks = session.get("blocks") or []

    if body.values:
        _check_value_count(body.values)
        values.update(_normalize_values(body.values))

    if body.session_id and not values and not body.values:
        raise ApiError(ERR_API_SESSION_NOT_FOUND)

    template_id = (body.template_id or session_template).strip()
    template_bytes = await template_store.read(template_id)
    raw_blocks = body.blocks if body.blocks is not None else session_blocks
    blocks = await _resolve_blocks(template_id, template_bytes, raw_blocks)

    built = await _build(template_bytes, values, blocks, template_id)
    response = await _finalize(built, body.filename or f"{template_id}_초안", fmt)

    # 부분 초안 여부는 운영에서 봐야 하는 수치다 — 항목명·값은 남기지 않는다
    log_info(
        "초안 생성 완료",
        event="generate_succeeded",
        resource_id=template_id,
        item_count=len(built.written_fields),
        status=(
            f"format={fmt} missing={len(built.missing_fields)}"
            f" styled={len(built.styled_fields)} blocks={built.appended_blocks}"
        ),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    # 생성 성공 = 세션 종료. 변환에 실패했다면 `_finalize` 가 예외를 올려 여기 오지 않는다.
    if body.session_id:
        await end_session(body.session_id)
    return response


@app.post("/generate/upload")
async def generate_upload(
    template: UploadFile = File(..., description="채울 hwpx 템플릿 파일"),
    session_id: str | None = Form(None),
    values: str | None = Form(None, description="추가 값 JSON 문자열"),
    blocks: str | None = Form(None, description="본문 추가 내용 JSON 배열 문자열"),
    filename: str | None = Form(None),
    format: str | None = Form(None, description="hwpx(기본) | pdf"),
) -> Response:
    """업로드한 hwpx 를 그대로 채워 내려준다 (템플릿 사전 등록 없이).

    처리 규칙은 `/generate` 와 **완전히 같다** — 값의 출처와 서식 목록을 얻는 경로만 다르다
    (등록 템플릿은 색인 캐시, 업로드 파일은 그 자리에서 파싱).
    """
    started = time.monotonic()
    fmt = _resolve_format(format)
    template_bytes = await _read_upload(template)

    collected: dict = {}
    session_blocks: list = []
    if session_id:
        try:
            session = await load_session(session_id)
        except ValueError as exc:
            raise ApiError(ERR_API_INPUT, "session_id 가 올바르지 않습니다.") from exc
        collected.update(session.get("values") or {})
        session_blocks = session.get("blocks") or []

    if values:
        parsed = _parse_json_form(values, "values", dict)
        _check_value_count(parsed)
        collected.update(_normalize_values(parsed))

    raw_blocks = _parse_json_form(blocks, "blocks", list) if blocks else session_blocks
    label = os.path.splitext(os.path.basename((template.filename or "").strip()))[0]
    # 업로드 파일은 색인이 없으므로 서식 목록을 그 자리에서 뽑는다 (template_id 는 빈 값)
    body_blocks = await _resolve_blocks("", template_bytes, raw_blocks)

    built = await _build(template_bytes, collected, body_blocks, label)
    response = await _finalize(built, filename or f"{label}_초안", fmt)

    log_info(
        "업로드 템플릿으로 초안 생성 완료",
        event="generate_upload_succeeded",
        item_count=len(built.written_fields),
        status=(
            f"format={fmt} missing={len(built.missing_fields)}"
            f" styled={len(built.styled_fields)} blocks={built.appended_blocks}"
        ),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    if session_id:
        await end_session(session_id)
    return response


def _parse_json_form(raw: str, field_name: str, expected: type):
    """multipart 폼으로 온 JSON 문자열을 파싱한다 (형식이 다르면 400)."""
    shape = "객체" if expected is dict else "배열"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(ERR_API_INPUT, f"{field_name} 는 JSON {shape}이어야 합니다.") from exc
    if not isinstance(parsed, expected):
        raise ApiError(ERR_API_INPUT, f"{field_name} 는 JSON {shape}이어야 합니다.")
    return parsed
