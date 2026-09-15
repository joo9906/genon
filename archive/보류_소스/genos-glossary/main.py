"""Office 문서 번역 코드 서빙 진입점.

GenOS 엔지니어 개발가이드 v1.02 6장 반영
- 6.4절: 서버는 0.0.0.0과 PORT(GenOS 주입)에 bind
- 6.4절: GET /health는 HTTP 200 고정 응답
- 6.9절 잘못된 예 3: 동기 blocking 작업을 async 핸들러 안에서 직접 실행하지 않음
- 3.9.5절: 코드 서빙은 HTTP 상태 + {error_code, msg, detail} 형식으로 오류 반환

용어사전 캐시
- 서버 시작 시 1회 + 이후 GLOSSARY_REFRESH_INTERVAL_SEC 주기로 Weaviate에서 용어
  전체를 읽어와 1단계(정확 매칭) 캐시를 채운다 (glossary.start_periodic_refresh).
- 이 백그라운드 태스크가 실패해도 서버 부팅/health check는 영향받지 않는다
  (glossary.refresh_glossary_cache 자체가 예외를 삼키는 fail-open 설계).
"""

import asyncio
import logging
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import Config
from translation_pipeline.common.error_codes import ERR_INPUT, ERR_INTERNAL
from translation_pipeline.common.glossary import close_clients, start_periodic_refresh
from translation_pipeline.office.pipeline import (
    TranslationRequestError,
    run_translation_job,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
_log = logging.getLogger(__name__)

app = FastAPI(title="office-translation-service")

_glossary_refresh_task: asyncio.Task | None = None


class TranslateRequest(BaseModel):
    nodes: list[dict]
    target_lang: str
    translator_mode: str | None = None  # "llm" | "mock" | "noop"
    style_options: dict | None = None


@app.on_event("startup")
async def _start_glossary_refresh() -> None:
    global _glossary_refresh_task
    if not Config.WEAVIATE_URL:
        _log.info("WEAVIATE_URL이 설정되지 않아 용어사전 캐시 갱신을 건너뜁니다.")
        return
    _glossary_refresh_task = asyncio.create_task(
        start_periodic_refresh(Config.GLOSSARY_TARGET_LANGS, Config.GLOSSARY_REFRESH_INTERVAL_SEC)
    )


@app.on_event("shutdown")
async def _stop_glossary_refresh() -> None:
    if _glossary_refresh_task is not None:
        _glossary_refresh_task.cancel()
    await close_clients()


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
        translation_error: 실패 시 메시지 (성공 시 빈 문자열)
    """
    try:
        artifacts = await run_translation_job(
            nodes=body.nodes,
            target_lang=body.target_lang,
            translator_mode=body.translator_mode,
            style_options=body.style_options,
        )
    except TranslationRequestError as exc:
        _log.warning(
            "translation input error",
            extra={"error_code": ERR_INPUT.code, "error_type": ERR_INPUT.error_type, "detail": str(exc)},
        )
        return JSONResponse(
            status_code=ERR_INPUT.http_status,
            content={"error_code": ERR_INPUT.code, "msg": str(exc)},
        )
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그에만
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
