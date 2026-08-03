"""번역 모드 분기 및 배치 번역 실행.

- mock/noop: 실제 LLM 호출 없이 파이프라인 구조를 검증하기 위한 모드
  (개발/로컬 테스트/CI에서 비용·지연 없이 흐름을 확인할 수 있게 함)
- llm: 실제 Gateway를 통한 번역

배치가 통째로 실패해도 빈 값을 반환하지 않는다 — 재시도 후에도 실패하면
유닛 단위로 쪼개서 개별 재시도하고, 그마저 실패하면 원문을 그대로 채택한다.
이는 "오류 객체를 chunk 목록에 넣어 반환하지 않는다"(8.5절)와 같은 맥락으로,
번역 실패를 침묵 처리하지 않고 `translation_error`로 드러내기 위함이다.
"""

import asyncio
import json
import os
from typing import Dict, List

from translation_pipeline.common.llm import (
    clear_last_llm_error,
    get_last_llm_error,
    llm_call_async,
)
from translation_pipeline.common.logging_utils import log_info
from translation_pipeline.common.prompt_builder import (
    build_batch_user_prompt,
    build_single_user_prompt,
    get_single_translation_system_prompt,
    get_translation_system_prompt,
)
from translation_pipeline.common.validation import validate_translation_batch_response

from .types import TranslationUnit


def normalize_translator_mode(value: str | None) -> str:
    mode = (value or os.getenv("AI_TRANSLATION_TRANSLATOR_MODE", "llm")).strip().lower()
    return mode if mode in {"llm", "mock", "noop"} else "llm"


async def _translate_single(sem: asyncio.Semaphore, text: str, target_lang: str) -> str:
    system = get_single_translation_system_prompt(target_lang)
    user_prompt = build_single_user_prompt(text, target_lang=target_lang)
    result = await llm_call_async(sem, system, user_prompt)
    return result if result else text


async def _translate_batch(
    sem: asyncio.Semaphore,
    batch: List[TranslationUnit],
    target_lang: str,
    *,
    retry: int = 0,
) -> Dict[int, str]:
    system_prompt = get_translation_system_prompt(target_lang)
    pairs = [(unit.translation_unit_id, unit.text) for unit in batch]
    raw = await llm_call_async(sem, system_prompt, build_batch_user_prompt(pairs))

    if not raw:
        if retry < 2:
            await asyncio.sleep(0.5)
            return await _translate_batch(sem, batch, target_lang, retry=retry + 1)
        return {
            unit.translation_unit_id: await _translate_single(sem, unit.text, target_lang)
            for unit in batch
        }

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("["), raw.rfind("]")
        parsed = None
        if start != -1 and end > start:
            try:
                parsed = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                parsed = None

    expected = {unit.translation_unit_id: unit.text for unit in batch}
    validation = validate_translation_batch_response(parsed, expected)

    if validation.hard_errors and retry < 2:
        log_info(f"[번역 배치 검증 실패] retry={retry + 1}: {validation.hard_errors[:2]}")
        await asyncio.sleep(0.5)
        return await _translate_batch(sem, batch, target_lang, retry=retry + 1)

    result = dict(validation.normalized)
    missing = [unit for unit in batch if unit.translation_unit_id not in result]
    for unit in missing:
        result[unit.translation_unit_id] = await _translate_single(sem, unit.text, target_lang)
    return result


async def translate_units_with_mode(
    sem: asyncio.Semaphore,
    translation_units: List[TranslationUnit],
    target_lang: str,
    translator_mode: str | None = None,
    max_chars_per_batch: int = 4000,
    max_items_per_batch: int = 10,
) -> tuple[Dict[int, str], str]:
    """번역 단위 목록을 선택된 모드로 처리한다.

    Returns:
        (translated_by_unit_id, translation_error)
        translation_error는 성공 시 빈 문자열.
    """
    mode = normalize_translator_mode(translator_mode)

    if mode == "noop":
        return {u.translation_unit_id: u.text for u in translation_units}, ""

    if mode == "mock":
        return {
            u.translation_unit_id: (f"[{target_lang}] {u.text}" if u.text.strip() else u.text)
            for u in translation_units
        }, ""

    clear_last_llm_error()
    pending = [u for u in translation_units if u.text.strip()]
    result: Dict[int, str] = {
        u.translation_unit_id: u.text for u in translation_units if not u.text.strip()
    }

    batches: List[List[TranslationUnit]] = []
    current: List[TranslationUnit] = []
    current_chars = 0
    for unit in pending:
        if current and (
            current_chars + len(unit.text) > max_chars_per_batch
            or len(current) >= max_items_per_batch
        ):
            batches.append(current)
            current, current_chars = [], 0
        current.append(unit)
        current_chars += len(unit.text)
    if current:
        batches.append(current)

    log_info(f"[번역] {len(pending)}개 단위 -> {len(batches)}개 배치")

    batch_results = await asyncio.gather(
        *[_translate_batch(sem, batch, target_lang) for batch in batches]
    )
    for batch_result in batch_results:
        result.update(batch_result)

    translation_error = ""
    if pending and all(result.get(u.translation_unit_id) == u.text for u in pending):
        translation_error = get_last_llm_error()
    return result, translation_error
