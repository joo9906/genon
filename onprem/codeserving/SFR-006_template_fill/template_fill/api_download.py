"""문서 조립 → 다운로드 응답 — "검증된 값을 파일로 바꾸는" 층.

`main.py` 에서 갈라져 나왔다 (2026-08-11). `api_requests.py` 가 요청을 값으로 바꾸고,
여기서 그 값을 문서로 바꾼다. `main.py` 에는 그 둘을 잇는 배선만 남는다.

## 경계

- **조립 순서(서식 → 채우기 → 블록)는 여기에 없다.** `document.build` 한 곳에만 있다.
  예전에 코드서빙·미리보기·점검 스크립트가 각자 순서를 적고 있었고, 점검이 자기가 검증할
  순서를 스스로 복제해 무의미했다.
- **`document.build` 는 HTTP 를 모른다.** 도메인 예외(`TemplateError`)를 `ApiError` 로
  바꾸는 것이 이 파일의 일이고, 그 경계가 여기다.
- **blocking 작업은 전부 `asyncio.to_thread`** (6.9절). zip 해제·XML 파싱·PDF 변환이
  전부 여기를 지난다 — 이벤트 루프에서 직접 돌리면 헬스체크가 멈춘다.
"""

import asyncio
import urllib.parse

from fastapi.responses import Response

from . import document, pdf_convert, session_view
from .api_errors import ApiError
from .config import Config
from .error_codes import (
    ERR_API_INPUT,
    ERR_API_INTERNAL,
    ERR_API_PDF_FAILED,
    ERR_API_PDF_UNAVAILABLE,
)
from .field_judge import normalize_blocks
from .hwpx_blocks import block_style_names
from .hwpx_fields import TemplateError
from .logging_utils import log_warning
from .pdf_convert import PdfConvertError, PdfUnavailableError


async def resolve_blocks(template_id: str, template_bytes: bytes, raw_blocks) -> list:
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


async def build(template_bytes: bytes, values: dict, blocks: list, label: str):
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


def download_response(content: bytes, built, filename_base: str, fmt: str) -> Response:
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
            "X-Document-Format": fmt,
        },
    )


async def finalize(built, filename_base: str, fmt: str) -> Response:
    """요청 형식에 맞는 다운로드 응답을 만든다 (pdf 면 변환까지).

    변환에 실패하면 `ApiError` 가 올라가므로 **호출부의 세션 종료 코드에 도달하지 않는다** —
    사용자가 형식을 바꿔 다시 시도할 수 있어야 하기 때문이다. 예전에는 이 성질을
    `(응답, 오류)` 튜플과 `if error: return` 으로 지켰는데, 예외가 그 순서를 강제한다.
    """
    if fmt != "pdf":
        return download_response(built.hwpx_bytes, built, filename_base, "hwpx")
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
    return download_response(pdf_bytes, built, filename_base, "pdf")
