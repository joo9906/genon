"""Office 문서 번역 코드 서빙 진입점 (리팩토링).

[변경 사항]
1. (보안/안정성) 입력 크기 제한 추가 — nodes 개수와 총 문자수 상한.
   기존에는 무제한이라 초대형 요청 한 건이 LLM 예산과 pod 메모리를 잠식할 수 있었다.
   상한 초과는 3.9.5절 형식({error_code, msg})의 400으로 반환.
2. (가이드 준수 강화) TranslationRequestError의 str(exc)를 응답에 그대로 싣던 것을
   유지하되, 이 예외는 pipeline 내부에서 우리가 만든 고정 문구만 담도록 계약을
   명시했다(외부 라이브러리 예외가 이 타입으로 새어 들어올 수 없음).
   그 외 모든 예외는 기존대로 ERR_INTERNAL.user_msg 고정 문구만 노출.
3. /health, 0.0.0.0:$PORT bind, 오류 응답 형식 등 기존 준수 사항은 그대로 유지.
"""

import logging
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from translation_pipeline.common.error_codes import ERR_INPUT, ERR_INTERNAL
from translation_pipeline.office.pipeline import (
    TranslationRequestError,
    run_markdown_translation_job,
    run_translation_job,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
_log = logging.getLogger(__name__)

app = FastAPI(title="office-translation-service")

# 입력 상한 (운영 정책에 맞게 환경변수로 조정)
MAX_NODES = int(os.environ.get("TRANSLATE_MAX_NODES", "2000"))
MAX_TOTAL_CHARS = int(os.environ.get("TRANSLATE_MAX_TOTAL_CHARS", "500000"))


class TranslateRequest(BaseModel):
    nodes: list[dict] = Field(..., description="문서에서 추출한 노드 목록")
    target_lang: str = Field(..., min_length=1, max_length=32)
    translator_mode: str | None = None  # "llm" | "mock" | "noop"
    style_options: dict | None = None


class TranslateMarkdownRequest(BaseModel):
    markdown: str = Field(..., min_length=1, description="전처리기가 변환한 마크다운 본문")
    target_lang: str = Field(..., min_length=1, max_length=32)
    translator_mode: str | None = None  # "llm" | "mock" | "noop"


def _input_error_response(msg: str) -> JSONResponse:
    _log.warning(
        "translation input error",
        extra={"error_code": ERR_INPUT.code, "error_type": ERR_INPUT.error_type},
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

    Args:
        body.nodes: 문서에서 추출한 노드(dict) 목록. 각 노드는 최소한
            `text`, `type` 키를 포함해야 한다.
        body.target_lang: 번역 대상 언어 코드 (예: "en", "ja").
        body.translator_mode: 번역기 동작 모드. 생략 시 환경변수
            AI_TRANSLATION_TRANSLATOR_MODE(기본 "llm") 사용.

    Returns:
        pairs: 노드별 원문/번역 쌍
        text: 번역 결과를 이어붙인 전체 텍스트
        translation_error: 실패 시 사유 분류 문자열 (성공 시 빈 문자열)
    """
    # 입력 크기 상한 검증 (LLM 예산/메모리 보호)
    if len(body.nodes) > MAX_NODES:
        return _input_error_response(f"nodes 개수가 상한({MAX_NODES}건)을 초과했습니다.")
    total_chars = sum(len(str(n.get("text", ""))) for n in body.nodes)
    if total_chars > MAX_TOTAL_CHARS:
        return _input_error_response(f"총 텍스트 길이가 상한({MAX_TOTAL_CHARS}자)을 초과했습니다.")

    try:
        artifacts = await run_translation_job(
            nodes=body.nodes,
            target_lang=body.target_lang,
            translator_mode=body.translator_mode,
            style_options=body.style_options,
        )
    except TranslationRequestError as exc:
        # 계약: 이 예외의 메시지는 pipeline.py에서 우리가 만든 고정 안내문만 담는다.
        return _input_error_response(str(exc))
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
        _log.error(
            "translation internal error",
            extra={"error_code": ERR_INTERNAL.code, "error_type": type(exc).__name__},
        )
        return JSONResponse(
            status_code=ERR_INTERNAL.http_status,
            content={"error_code": ERR_INTERNAL.code, "msg": ERR_INTERNAL.user_msg},
        )

    return {
        "pairs": artifacts.pairs,
        "text": artifacts.text,
        "translation_error": artifacts.translation_error,
    }


@app.post("/translate/markdown")
async def translate_markdown(body: TranslateMarkdownRequest):
    """전처리기(docx/pdf/hwpx → 마크다운) 산출물을 구조 보존 방식으로 번역한다.

    표 파이프·제목·목록·코드펜스는 코드가 스켈레톤으로 보존하고 텍스트 내용만
    LLM 에 보낸다. 응답 markdown 의 구조는 입력과 항상 동일하다.

    Returns:
        markdown: 번역된 마크다운 (구조 원본 동일)
        pairs: 유닛별 원문/번역 쌍 (검수용)
        translation_error: 실패 시 사유 분류 문자열 (성공 시 빈 문자열)
    """
    if len(body.markdown) > MAX_TOTAL_CHARS:
        return _input_error_response(
            f"총 텍스트 길이가 상한({MAX_TOTAL_CHARS}자)을 초과했습니다."
        )

    try:
        artifacts = await run_markdown_translation_job(
            markdown=body.markdown,
            target_lang=body.target_lang,
            translator_mode=body.translator_mode,
        )
    except TranslationRequestError as exc:
        # 계약: 이 예외의 메시지는 pipeline.py에서 우리가 만든 고정 안내문만 담는다.
        return _input_error_response(str(exc))
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
        _log.error(
            "markdown translation internal error",
            extra={"error_code": ERR_INTERNAL.code, "error_type": type(exc).__name__},
        )
        return JSONResponse(
            status_code=ERR_INTERNAL.http_status,
            content={"error_code": ERR_INTERNAL.code, "msg": ERR_INTERNAL.user_msg},
        )

    return {
        "markdown": artifacts.markdown,
        "pairs": artifacts.pairs,
        "translation_error": artifacts.translation_error,
    }
