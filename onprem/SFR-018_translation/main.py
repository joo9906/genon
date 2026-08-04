"""Office 문서 번역 코드 서빙 진입점 (area 03).

엔드포인트
- GET  /health              : 헬스체크 (가이드 필수)
- POST /translate           : 문서에서 추출한 노드 목록 번역
- POST /translate/markdown  : 전처리기(docx/pdf/hwpx→마크다운/HTML) 산출물 번역

- 입력 크기 상한(nodes 개수/총 문자수)으로 초대형 요청의 LLM 예산·메모리 잠식 방지.
- TranslationRequestError는 pipeline에서 만든 고정 안내문만 담는다(외부 예외 미노출).
  그 외 모든 예외는 ERR_INTERNAL.user_msg 고정 문구만 노출한다(3.8절).
- 0.0.0.0:$PORT bind, 오류 응답 {error_code, msg} 형식(3.9.5절).
"""

import os
import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from translation_pipeline.common.error_codes import ERR_INPUT, ERR_INTERNAL
from translation_pipeline.common.logging_utils import (
    configure_logging,
    log_error,
    log_info,
    log_warning,
)
from translation_pipeline.office.pipeline import (
    TranslationRequestError,
    run_markdown_translation_job,
    run_translation_job,
)

configure_logging(os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="office-translation-service")

# 입력 상한 (운영 정책에 맞게 환경변수로 조정)
MAX_NODES = int(os.environ.get("TRANSLATE_MAX_NODES", "2000"))
MAX_TOTAL_CHARS = int(os.environ.get("TRANSLATE_MAX_TOTAL_CHARS", "500000"))


class TranslateRequest(BaseModel):
    nodes: list[dict] = Field(..., description="문서에서 추출한 노드 목록")
    target_lang: str = Field(..., min_length=1, max_length=32)
    style_options: dict | None = None


class TranslateMarkdownRequest(BaseModel):
    markdown: str = Field(..., min_length=1, description="전처리기가 변환한 마크다운/HTML 본문")
    target_lang: str = Field(..., min_length=1, max_length=32)


def _input_error_response(msg: str) -> JSONResponse:
    # 3.9.5절: 채팅 연계 시 msg 만 전달될 수 있으니 내부 로그에도 같은 코드를 남긴다
    log_warning(
        "번역 입력 오류 응답",
        event="api_input_error",
        error_code=ERR_INPUT.code,
        error_type=ERR_INPUT.error_type,
        status=str(ERR_INPUT.http_status),
    )
    return JSONResponse(
        status_code=ERR_INPUT.http_status,
        content={"error_code": ERR_INPUT.code, "msg": msg},
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/translate")
async def translate(body: TranslateRequest):
    """Office 문서에서 추출한 노드 목록을 번역한다.

    Returns:
        pairs: 노드별 원문/번역 쌍
        text: 번역 결과를 이어붙인 전체 텍스트
        translation_error: 실패 시 사유 분류 문자열 (성공 시 빈 문자열)
    """
    started = time.monotonic()
    if len(body.nodes) > MAX_NODES:
        return _input_error_response(f"nodes 개수가 상한({MAX_NODES}건)을 초과했습니다.")
    total_chars = sum(len(str(n.get("text", ""))) for n in body.nodes)
    if total_chars > MAX_TOTAL_CHARS:
        return _input_error_response(f"총 텍스트 길이가 상한({MAX_TOTAL_CHARS}자)을 초과했습니다.")

    try:
        artifacts = await run_translation_job(
            nodes=body.nodes,
            target_lang=body.target_lang,
        )
    except TranslationRequestError as exc:
        # 계약: 이 예외의 메시지는 pipeline.py에서 우리가 만든 고정 안내문만 담는다.
        return _input_error_response(str(exc))
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
        log_error(
            "번역 처리 중 내부 오류",
            event="translate_internal_error",
            error_code=ERR_INTERNAL.code,
            error_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=ERR_INTERNAL.http_status,
            content={"error_code": ERR_INTERNAL.code, "msg": ERR_INTERNAL.user_msg},
        )

    log_info(
        "노드 번역 완료",
        event="translate_completed",
        item_count=len(artifacts.pairs),
        status=artifacts.translation_error or "ok",
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return {
        "pairs": artifacts.pairs,
        "text": artifacts.text,
        "translation_error": artifacts.translation_error,
    }


@app.post("/translate/markdown")
async def translate_markdown(body: TranslateMarkdownRequest):
    """전처리기(docx/pdf/hwpx → 마크다운/HTML) 산출물을 구조 보존 방식으로 번역한다.

    표 파이프·HTML 태그·제목·목록·코드펜스는 코드가 스켈레톤으로 보존하고 텍스트
    내용만 LLM 에 보낸다. 응답 markdown 의 구조는 입력과 항상 동일하다.

    Returns:
        markdown: 번역된 마크다운/HTML (구조 원본 동일)
        pairs: 유닛별 원문/번역 쌍 (검수용)
        translation_error: 실패 시 사유 분류 문자열 (성공 시 빈 문자열)
    """
    started = time.monotonic()
    if len(body.markdown) > MAX_TOTAL_CHARS:
        return _input_error_response(
            f"총 텍스트 길이가 상한({MAX_TOTAL_CHARS}자)을 초과했습니다."
        )

    try:
        artifacts = await run_markdown_translation_job(
            markdown=body.markdown,
            target_lang=body.target_lang,
        )
    except TranslationRequestError as exc:
        return _input_error_response(str(exc))
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
        log_error(
            "마크다운 번역 처리 중 내부 오류",
            event="translate_markdown_internal_error",
            error_code=ERR_INTERNAL.code,
            error_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=ERR_INTERNAL.http_status,
            content={"error_code": ERR_INTERNAL.code, "msg": ERR_INTERNAL.user_msg},
        )

    log_info(
        "마크다운 번역 완료",
        event="translate_markdown_completed",
        item_count=len(artifacts.pairs),
        status=artifacts.translation_error or "ok",
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return {
        "markdown": artifacts.markdown,
        "pairs": artifacts.pairs,
        "translation_error": artifacts.translation_error,
    }
