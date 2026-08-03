"""번역 모드 분기 및 배치 번역 실행.

- mock/noop: 실제 LLM 호출 없이 파이프라인 구조를 검증하기 위한 모드
  (개발/로컬 테스트/CI에서 비용·지연 없이 흐름을 확인할 수 있게 함)
- llm: 실제 Gateway를 통한 번역

배치가 통째로 실패해도 빈 값을 반환하지 않는다 — 재시도 후에도 실패하면
유닛 단위로 쪼개서 개별 재시도하고, 그마저 실패하면 원문을 그대로 채택한다.
이는 "오류 객체를 chunk 목록에 넣어 반환하지 않는다"(8.5절)와 같은 맥락으로,
번역 실패를 침묵 처리하지 않고 `translation_error`로 드러내기 위함이다.

용어사전(RAG) 조회
- 배치 번역 직전에 glossary.lookup_glossary_terms()로 관련 용어를 찾아 프롬프트에 주입한다.
- 용어사전 조회는 번역의 필수 경로가 아니다(fail-open). 조회가 실패해도 번역 자체는
  그대로 진행하며, translation_error에도 영향을 주지 않는다 — 용어사전 실패와 번역 실패는
  서로 다른 장애 등급이다.
- 용어사전 조회용 세마포어(_GLOSSARY_SEM)는 LLM 세마포어(sem)와 분리한다. 두 자원의
  동시성 상한이 다르고(Weaviate/임베딩 endpoint vs LLM endpoint), 서로 발목 잡지 않게 하기 위함.
- 단건 재시도 경로(_translate_single)는 의도적으로 용어사전 조회를 건너뛴다. 이미 배치가
  실패해 저하된 경로이므로 추가 지연을 두지 않으며, "원문 그대로 채택" 최종 안전망이
  이미 있어 용어 불일치가 전체 실패로 이어지지 않는다.
"""

import asyncio
import json
import os
from typing import Dict, List

from config import Config
from translation_pipeline.common.glossary import GlossaryHit, lookup_glossary_terms
from translation_pipeline.common.llm import (
    clear_last_llm_error,
    get_last_llm_error,
    llm_call_async,
)
from translation_pipeline.common.logging_utils import log_info
from translation_pipeline.common.prompt_builder import (
    build_batch_user_prompt,
    build_glossary_block,
    build_single_user_prompt,
    get_single_translation_system_prompt,
    get_translation_system_prompt,
)
from translation_pipeline.common.validation import validate_translation_batch_response

from .types import TranslationUnit

# LLM 세마포어(sem)와 분리된 용어사전 조회 전용 동시성 제어.
# 모듈 레벨로 두어 pipeline.py/main.py의 호출 시그니처를 바꾸지 않고도 적용된다.
_GLOSSARY_SEM = asyncio.Semaphore(Config.GLOSSARY_CONCURRENCY)


def normalize_translator_mode(value: str | None) -> str:
    mode = (value or os.getenv("AI_TRANSLATION_TRANSLATOR_MODE", "llm")).strip().lower()
    return mode if mode in {"llm", "mock", "noop"} else "llm"


async def _translate_single(sem: asyncio.Semaphore, text: str, target_lang: str) -> str:
    # 용어사전 조회는 여기서 의도적으로 생략한다 (모듈 docstring 참고).
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

    # 용어사전 조회 - 실패해도 예외를 던지지 않고 빈 리스트를 반환한다(glossary.py 계약).
    # 재시도 호출(retry>0)에서는 이미 1차 시도에서 얻은 결과를 재사용해도 되지만,
    # 재시도 자체가 드문 경로이고 구현을 단순하게 유지하기 위해 매번 새로 조회한다.
    glossary_hits: List[GlossaryHit] = await lookup_glossary_terms(
        _GLOSSARY_SEM, [u.text for u in batch], target_lang
    )
    glossary_block = build_glossary_block(glossary_hits)

    raw = await llm_call_async(
        sem, system_prompt, build_batch_user_prompt(pairs, glossary_block=glossary_block)
    )

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
                parsed = json.loads(raw[start: end + 1])
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

    # mock/noop 모드는 용어사전 조회 자체를 타지 않는다 (개발/CI 비용·지연 없음 유지).
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
