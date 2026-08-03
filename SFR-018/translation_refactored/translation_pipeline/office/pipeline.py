"""Office 문서 번역 오케스트레이션 (리팩토링).

[변경 사항]
1. (버그 수정) trans_map을 unit.text 키의 dict로 만들던 것을 제거.
   같은 문장이 문서에 여러 번 나오면(예: 반복 머리글) dict 키가 충돌해
   마지막 번역만 남는 문제가 있었다. → node_id 키 기반 pairs만 신뢰 소스로 두고,
   trans_map이 꼭 필요하면 "동일 원문 = 동일 번역" 전제일 때만 참고용으로 쓰도록
   docstring에 계약을 명시.
2. TranslationRequestError 메시지 계약 명시: 이 예외에는 우리가 작성한 고정
   안내문만 담는다 (main.py가 이 메시지를 API 응답 msg로 그대로 사용하기 때문).
"""

import asyncio

from config import Config

from .markdown_units import rebuild_markdown, split_markdown
from .translation_modes import translate_units_with_mode
from .types import MarkdownTranslationArtifacts, OfficeTranslationArtifacts
from .units import build_pairs, build_translation_units


class TranslationRequestError(ValueError):
    """입력값 오류 (형식 문제 등). 03-00020003으로 처리한다.

    계약: 이 예외의 메시지는 사용자에게 그대로 노출되므로,
    반드시 이 파일 안에서 작성한 고정 한국어 안내문만 담는다.
    외부 라이브러리 예외를 감싸서 str(exc)를 넣지 않는다.
    """


async def run_translation_job(
    *,
    nodes: list[dict],
    target_lang: str,
    translator_mode: str | None = None,
    style_options: dict | None = None,
) -> OfficeTranslationArtifacts:
    if not nodes:
        raise TranslationRequestError("nodes가 비어 있습니다.")
    if not target_lang or not target_lang.strip():
        raise TranslationRequestError("target_lang이 비어 있습니다.")

    units = build_translation_units(nodes)
    sem = asyncio.Semaphore(Config.LLM_CONCURRENCY)

    translated_by_unit_id, translation_error = await translate_units_with_mode(
        sem,
        units,
        target_lang,
        translator_mode=translator_mode,
        max_chars_per_batch=Config.MAX_CHARS_PER_BATCH,
        max_items_per_batch=Config.MAX_ITEMS_PER_BATCH,
    )

    pairs = build_pairs(units, translated_by_unit_id)
    text = "\n".join(pair["translated"] for pair in pairs)

    # trans_map은 참고용이다. 같은 원문이 여러 번 등장하면 마지막 번역으로
    # 수렴하므로, 위치 정확도가 필요한 소비자는 반드시 pairs(node_id 기준)를 쓴다.
    trans_map = {
        unit.text: translated_by_unit_id.get(unit.translation_unit_id, unit.text)
        for unit in units
    }

    return OfficeTranslationArtifacts(
        pairs=pairs,
        text=text,
        trans_map=trans_map,
        translated_by_unit_id=translated_by_unit_id,
        translation_error=translation_error,
    )


async def run_markdown_translation_job(
    *,
    markdown: str,
    target_lang: str,
    translator_mode: str | None = None,
) -> MarkdownTranslationArtifacts:
    """전처리기 산출물(마크다운)을 구조 보존 방식으로 번역한다.

    표 파이프·제목·목록·코드펜스 등 구조 문법은 markdown_units.split_markdown
    이 스켈레톤으로 분리해 코드가 보존하고, LLM 에는 셀/문장 텍스트만 보낸다.
    → 재조립(rebuild_markdown) 결과의 구조는 LLM 출력과 무관하게 원본과 동일.
    실패 유닛은 원문이 유지되고 translation_error 로 상위에 노출된다.
    """
    if not markdown or not markdown.strip():
        raise TranslationRequestError("markdown이 비어 있습니다.")
    if not target_lang or not target_lang.strip():
        raise TranslationRequestError("target_lang이 비어 있습니다.")

    segments, units = split_markdown(markdown)
    if not units:
        # 번역할 텍스트가 전혀 없는 문서(숫자 표 등)는 원문 그대로 반환
        return MarkdownTranslationArtifacts(markdown=markdown, pairs=[], translation_error="")

    sem = asyncio.Semaphore(Config.LLM_CONCURRENCY)
    translated_by_unit_id, translation_error = await translate_units_with_mode(
        sem,
        units,
        target_lang,
        translator_mode=translator_mode,
        max_chars_per_batch=Config.MAX_CHARS_PER_BATCH,
        max_items_per_batch=Config.MAX_ITEMS_PER_BATCH,
    )

    return MarkdownTranslationArtifacts(
        markdown=rebuild_markdown(segments, units, translated_by_unit_id),
        pairs=build_pairs(units, translated_by_unit_id),
        translation_error=translation_error,
    )
