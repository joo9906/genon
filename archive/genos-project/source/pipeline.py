"""Office 문서 번역 오케스트레이션.

main.py는 이 모듈의 run_translation_job()만 알면 되고, 배치 분할/재시도/모드
분기 같은 세부사항은 translation_modes.py 안에 감춰져 있다. 이 계층 분리 덕분에
API 스펙(main.py)과 번역 실행 로직(translation_modes.py)을 독립적으로 바꿀 수 있다.
"""

import asyncio

from config import Config

from .translation_modes import translate_units_with_mode
from .types import OfficeTranslationArtifacts
from .units import build_pairs, build_translation_units


class TranslationRequestError(ValueError):
    """입력값 오류 (형식 문제 등). 통신 실패와 구분해 03-00020003으로 처리한다."""


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
    trans_map = {unit.text: translated_by_unit_id.get(unit.translation_unit_id, unit.text) for unit in units}
    text = "\n".join(pair["translated"] for pair in pairs)

    return OfficeTranslationArtifacts(
        pairs=pairs,
        text=text,
        trans_map=trans_map,
        translated_by_unit_id=translated_by_unit_id,
        translation_error=translation_error,
    )
