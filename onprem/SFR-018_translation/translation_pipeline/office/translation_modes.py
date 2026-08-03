"""번역 실행 (배치 + 단건 fallback).

[설계]
1. 유닛별 실패 여부(failed_unit_ids)를 명시적으로 추적한다.
   "전부 원문과 같으면 실패"라는 휴리스틱은 쓰지 않는다 — 숫자·고유명사만
   있는 문서는 번역 결과가 원문과 같아도 정상이기 때문.
2. 배치 실패 시 단건 fallback을 asyncio.gather 병렬로 실행한다(직렬 지연 방지).
3. llm.py의 전역 오류 상태 대신 LlmResult로 translation_error를 레이스 없이 집계.
4. 배치 분할 + 상한 있는 재시도(retry<=2) (10.2절).
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Dict, List, Set

from translation_pipeline.common.llm import LlmResult, llm_call_async
from translation_pipeline.common.logging_utils import log_info, log_warning
from translation_pipeline.common.prompt_builder import (
    build_batch_user_prompt,
    build_single_user_prompt,
    get_single_translation_system_prompt,
    get_translation_system_prompt,
)
from translation_pipeline.common.validation import validate_translation_batch_response

from .types import TranslationUnit

_MAX_BATCH_RETRY = 2  # 상한 있는 재시도 (10.2절)


@dataclass
class TranslationOutcome:
    """번역 실행 결과. 실패를 침묵 처리하지 않고 명시적으로 드러낸다."""

    translated_by_unit_id: Dict[int, str] = field(default_factory=dict)
    failed_unit_ids: Set[int] = field(default_factory=set)
    last_error_type: str = ""
    transport_failure: bool = False

    @property
    def translation_error(self) -> str:
        """실패 유닛이 있으면 사유 문자열, 없으면 ""."""
        if not self.failed_unit_ids:
            return ""
        return self.last_error_type or "TRANSLATION_PARTIAL_FAILURE"


async def _translate_single(
    sem: asyncio.Semaphore,
    unit: TranslationUnit,
    target_lang: str,
    outcome: TranslationOutcome,
) -> None:
    """단건 번역. 실패 시 원문을 채택하되 failed_unit_ids에 기록한다."""
    system = get_single_translation_system_prompt(target_lang)
    user_prompt = build_single_user_prompt(unit.text, target_lang=target_lang)
    result: LlmResult = await llm_call_async(sem, system, user_prompt)
    if result.ok:
        outcome.translated_by_unit_id[unit.translation_unit_id] = result.content
    else:
        outcome.translated_by_unit_id[unit.translation_unit_id] = unit.text
        outcome.failed_unit_ids.add(unit.translation_unit_id)
        outcome.last_error_type = result.error_type
        outcome.transport_failure = outcome.transport_failure or result.is_transport_error


def _parse_json_array(raw: str):
    """LLM 응답에서 JSON 배열을 안전하게 추출한다. 실패 시 None."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


async def _translate_batch(
    sem: asyncio.Semaphore,
    batch: List[TranslationUnit],
    target_lang: str,
    outcome: TranslationOutcome,
    *,
    retry: int = 0,
) -> None:
    system_prompt = get_translation_system_prompt(target_lang)
    pairs = [(unit.translation_unit_id, unit.text) for unit in batch]
    result: LlmResult = await llm_call_async(sem, system_prompt, build_batch_user_prompt(pairs))

    if not result.ok:
        if retry < _MAX_BATCH_RETRY:
            await asyncio.sleep(0.5)
            await _translate_batch(sem, batch, target_lang, outcome, retry=retry + 1)
            return
        outcome.last_error_type = result.error_type
        outcome.transport_failure = outcome.transport_failure or result.is_transport_error
        # 배치 통째 실패 → 단건 fallback (병렬 실행으로 지연 최소화)
        await asyncio.gather(
            *[_translate_single(sem, unit, target_lang, outcome) for unit in batch]
        )
        return

    parsed = _parse_json_array(result.content)
    expected = {unit.translation_unit_id: unit.text for unit in batch}
    validation = validate_translation_batch_response(parsed, expected)

    if validation.hard_errors and retry < _MAX_BATCH_RETRY:
        # hard_errors는 고정 문구만 담기므로 로그에 노출해도 응답 원문이 새지 않는다
        log_info(f"[번역 배치 검증 실패] retry={retry + 1}: {validation.hard_errors[:2]}")
        await asyncio.sleep(0.5)
        await _translate_batch(sem, batch, target_lang, outcome, retry=retry + 1)
        return

    outcome.translated_by_unit_id.update(validation.normalized)

    missing = [u for u in batch if u.translation_unit_id not in outcome.translated_by_unit_id]
    if missing:
        log_info(f"[번역 배치 부분 누락] {len(missing)}건 단건 재번역")
        await asyncio.gather(
            *[_translate_single(sem, unit, target_lang, outcome) for unit in missing]
        )


def _split_batches(
    pending: List[TranslationUnit],
    max_chars_per_batch: int,
    max_items_per_batch: int,
) -> List[List[TranslationUnit]]:
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
    return batches


async def translate_units(
    sem: asyncio.Semaphore,
    translation_units: List[TranslationUnit],
    target_lang: str,
    max_chars_per_batch: int = 4000,
    max_items_per_batch: int = 10,
) -> tuple[Dict[int, str], str]:
    """번역 단위 목록을 배치로 번역한다.

    Returns:
        (translated_by_unit_id, translation_error)
        translation_error는 전량 성공 시 빈 문자열, 일부라도 실패 시 사유 분류 문자열.
    """
    outcome = TranslationOutcome()
    pending = [u for u in translation_units if u.text.strip()]
    # 빈 텍스트 유닛은 호출 없이 원문 유지
    for u in translation_units:
        if not u.text.strip():
            outcome.translated_by_unit_id[u.translation_unit_id] = u.text

    batches = _split_batches(pending, max_chars_per_batch, max_items_per_batch)
    log_info(f"[번역] {len(pending)}개 단위 -> {len(batches)}개 배치")

    await asyncio.gather(
        *[_translate_batch(sem, batch, target_lang, outcome) for batch in batches]
    )

    if outcome.failed_unit_ids:
        log_warning(
            f"[번역 부분 실패] {len(outcome.failed_unit_ids)}건 원문 유지 "
            f"error_type={outcome.last_error_type} transport={outcome.transport_failure}"
        )

    return outcome.translated_by_unit_id, outcome.translation_error
