"""번역 실행 — 중복 제거 → 배치 → 단건 폴백 → 숫자 가드.

[설계]
1. 유닛별 실패 여부(`failed_unit_ids`)를 명시적으로 추적한다.
   "전부 원문과 같으면 실패"라는 휴리스틱은 쓰지 않는다 — 숫자·고유명사만 있는
   문서는 번역 결과가 원문과 같아도 정상이기 때문.
2. 배치 실패 시 단건 fallback 을 `asyncio.gather` 병렬로 실행한다(직렬 지연 방지).
3. `llm.py` 의 전역 오류 상태 대신 `LlmResult` 로 오류를 레이스 없이 집계한다.
4. 배치 분할 + 상한 있는 재시도(retry<=2) (10.2절).
5. **같은 원문은 한 번만 호출한다.** 반복 머리글·표의 같은 라벨이 문서마다 수십 번
   나오는데, 예전에는 그 수만큼 LLM 을 불렀다. 대표 유닛 하나만 번역하고 나머지는
   결과를 재사용한다 — 호출 수가 줄 뿐 아니라 **같은 문구가 자리마다 다르게 번역되는
   흔들림도 사라진다.**
6. **숫자 보존을 코드가 검사한다** (`numeric_guard`). 프롬프트가 "숫자를 그대로 두라"고
   지시하지만 지시는 보장이 아니다 — 구조 보존을 스켈레톤으로 처리한 것과 같은 이유.
"""

import asyncio
import json
from dataclasses import dataclass, field

from translation_pipeline.common.llm import LlmResult, llm_call_async
from translation_pipeline.common.logging_utils import log_info, log_warning
from translation_pipeline.common.prompt_builder import (
    PromptContext,
    build_batch_prompts,
    build_single_prompts,
)
from translation_pipeline.common.validation import validate_translation_batch_response

from . import numeric_guard
from .glossary_report import terms_for_batch
from .types import TranslationStats, TranslationUnit

_MAX_BATCH_RETRY = 2  # 상한 있는 재시도 (10.2절)


@dataclass
class TranslationOutcome:
    """번역 실행 결과. 실패를 침묵 처리하지 않고 명시적으로 드러낸다."""

    translated_by_unit_id: dict = field(default_factory=dict)
    failed_unit_ids: set = field(default_factory=set)
    last_error_type: str = ""
    transport_failure: bool = False

    @property
    def translation_error(self) -> str:
        """실패 유닛이 있으면 사유 문자열, 없으면 ""."""
        if not self.failed_unit_ids:
            return ""
        return self.last_error_type or "TRANSLATION_PARTIAL_FAILURE"


def _prompt_context(options) -> PromptContext:
    return PromptContext(
        source_label=options.source_label,
        target_label=options.target_label,
        register_label=options.register_label,
        register_instruction=options.register_instruction,
    )


async def _translate_single(
    sem: asyncio.Semaphore,
    unit: TranslationUnit,
    options,
    outcome: TranslationOutcome,
) -> None:
    """단건 번역. 실패 시 원문을 채택하되 failed_unit_ids 에 기록한다."""
    terms = terms_for_batch([unit.text], options.target_code, options.source_code)
    system, user = build_single_prompts(_prompt_context(options), unit.text, terms)
    result: LlmResult = await llm_call_async(sem, system, user)
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
                return json.loads(raw[start: end + 1])
            except json.JSONDecodeError:
                return None
    return None


async def _translate_batch(
    sem: asyncio.Semaphore,
    batch: list,
    options,
    outcome: TranslationOutcome,
    *,
    retry: int = 0,
) -> None:
    # 이 배치에 실제로 등장한 용어만 프롬프트에 싣는다 (사전 전체를 싣지 않는다).
    # 적용 대상 방향이 아니면 빈 목록이 온다 — 중·태·베·러는 LLM 만으로 번역한다.
    terms = terms_for_batch(
        [unit.text for unit in batch], options.target_code, options.source_code
    )
    pairs = [(unit.translation_unit_id, unit.text) for unit in batch]
    system, user = build_batch_prompts(_prompt_context(options), pairs, terms)
    result: LlmResult = await llm_call_async(sem, system, user)

    if not result.ok:
        if retry < _MAX_BATCH_RETRY:
            await asyncio.sleep(0.5)
            await _translate_batch(sem, batch, options, outcome, retry=retry + 1)
            return
        outcome.last_error_type = result.error_type
        outcome.transport_failure = outcome.transport_failure or result.is_transport_error
        # 배치 통째 실패 → 단건 fallback (병렬 실행으로 지연 최소화)
        await asyncio.gather(
            *[_translate_single(sem, unit, options, outcome) for unit in batch]
        )
        return

    parsed = _parse_json_array(result.content)
    expected = {unit.translation_unit_id: unit.text for unit in batch}
    validation = validate_translation_batch_response(parsed, expected)

    if validation.hard_errors and retry < _MAX_BATCH_RETRY:
        # 사유는 **건수로만** 남긴다 — 응답 원문이 섞여 들어올 경로를 아예 만들지 않는다
        # (3.8절). `skipped` 는 사유별 개수 dict 이고 값은 담기지 않는다
        # (`validation.py` 머리말 참고).
        log_info(
            "번역 배치 응답 검증 실패 — 재시도",
            event="translation_batch_validation_failed",
            item_count=len(validation.hard_errors),
            status=f"retry={retry + 1},skipped={validation.skipped_count}",
        )
        await asyncio.sleep(0.5)
        await _translate_batch(sem, batch, options, outcome, retry=retry + 1)
        return

    outcome.translated_by_unit_id.update(validation.normalized)

    missing = [u for u in batch if u.translation_unit_id not in outcome.translated_by_unit_id]
    if missing:
        log_info(
            "번역 배치 부분 누락 — 단건 재번역",
            event="translation_batch_partial_missing",
            item_count=len(missing),
        )
        await asyncio.gather(
            *[_translate_single(sem, unit, options, outcome) for unit in missing]
        )


def _split_batches(
    pending: list,
    max_chars_per_batch: int,
    max_items_per_batch: int,
) -> list:
    batches: list = []
    current: list = []
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


def _dedupe(pending: list) -> tuple:
    """(대표 유닛 목록, {복제 유닛 id: 대표 유닛 id}).

    같은 원문을 여러 번 번역하지 않는다. 키는 원문 그대로다 — 공백만 다른 문자열을
    같은 것으로 묶으면 재조립 때 앞뒤 공백이 어긋나 구조가 밀린다
    (`markdown_units` 가 앞뒤 공백을 리터럴로 이미 떼어내므로 여기서 또 다듬을 이유도 없다).
    """
    representatives: list = []
    alias_of: dict = {}
    first_by_text: dict = {}
    for unit in pending:
        existing = first_by_text.get(unit.text)
        if existing is None:
            first_by_text[unit.text] = unit.translation_unit_id
            representatives.append(unit)
        else:
            alias_of[unit.translation_unit_id] = existing
    return representatives, alias_of


def _apply_numeric_guard(
    units: list,
    outcome: TranslationOutcome,
    stats: TranslationStats,
    mode: str,
) -> list:
    """숫자 보존 검사. 이탈 유닛을 경고 목록으로 돌려주고, 정책에 따라 되돌린다.

    되돌리기를 기본값으로 두지 않은 이유: 숫자 하나 때문에 문장 전체를 원문으로
    남기면 사용자는 번역이 덜 된 문서를 받는다. 어느 쪽이 나은지는 운영 정책이라
    `TRANSLATE_NUMERIC_GUARD` 로 고른다.
    """
    warnings: list = []
    for unit in units:
        translated = outcome.translated_by_unit_id.get(unit.translation_unit_id)
        if translated is None or translated == unit.text:
            continue  # 원문 유지(폴백)는 정의상 숫자가 보존돼 있다
        drift = numeric_guard.find_numeric_drift(unit.text, translated)
        if not numeric_guard.has_drift(drift):
            continue
        stats.numeric_warning_count += 1
        reverted = mode == numeric_guard.MODE_REVERT
        if reverted:
            outcome.translated_by_unit_id[unit.translation_unit_id] = unit.text
            stats.numeric_reverted_count += 1
        warnings.append(
            {
                "unit_id": unit.translation_unit_id,
                "node_id": unit.node_id,
                "missing": drift["missing"],
                "added": drift["added"],
                "reverted": reverted,
            }
        )
    if warnings:
        # 3.8절: 어떤 수가 어긋났는지는 문서 내용이라 로그에 남기지 않고 건수만 남긴다
        log_warning(
            "번역문 숫자 보존 검사 이탈",
            event="translation_numeric_drift",
            item_count=len(warnings),
            status=mode,
        )
    return warnings


async def translate_units(
    sem: asyncio.Semaphore,
    translation_units: list,
    options,
    *,
    max_chars_per_batch: int = 4000,
    max_items_per_batch: int = 10,
    dedup: bool = True,
    numeric_mode: str = numeric_guard.MODE_WARN,
) -> tuple:
    """번역 단위 목록을 번역한다.

    Args:
        options: `TranslationOptions` — 대상 언어·원문 언어·문체.

    Returns:
        (translated_by_unit_id, translation_error, stats, numeric_warnings).
        translation_error 는 전량 성공 시 빈 문자열, 일부라도 실패 시 사유 분류 문자열.
    """
    outcome = TranslationOutcome()
    stats = TranslationStats(unit_count=len(translation_units))

    pending: list = []
    for unit in translation_units:
        if unit.text.strip():
            pending.append(unit)
        else:
            # 빈 텍스트 유닛은 호출 없이 원문 유지
            outcome.translated_by_unit_id[unit.translation_unit_id] = unit.text

    representatives, alias_of = _dedupe(pending) if dedup else (pending, {})
    stats.llm_unit_count = len(representatives)
    stats.deduped_unit_count = len(pending) - len(representatives)

    batches = _split_batches(representatives, max_chars_per_batch, max_items_per_batch)
    log_info(
        "번역 배치 분할 완료",
        event="translation_batches_prepared",
        item_count=len(representatives),
        status=f"batches={len(batches)},deduped={stats.deduped_unit_count}",
    )

    await asyncio.gather(
        *[_translate_batch(sem, batch, options, outcome) for batch in batches]
    )

    # 대표 유닛의 결과를 같은 원문을 가진 유닛들에 전파한다.
    # 대표가 실패해 원문으로 폴백했다면 복제도 같은 상태이므로 실패로 함께 센다 —
    # 그러지 않으면 fallback 발생률이 실제보다 낮게 보고된다.
    for unit_id, representative_id in alias_of.items():
        if representative_id in outcome.translated_by_unit_id:
            outcome.translated_by_unit_id[unit_id] = outcome.translated_by_unit_id[
                representative_id
            ]
        if representative_id in outcome.failed_unit_ids:
            outcome.failed_unit_ids.add(unit_id)

    stats.failed_unit_count = len(outcome.failed_unit_ids)

    if outcome.failed_unit_ids:
        # 원문 폴백은 침묵 처리하지 않는다 — 018 fallback 발생률 지표의 원천이다
        log_warning(
            "번역 부분 실패 — 해당 단위는 원문 유지",
            event="translation_partial_failure",
            item_count=len(outcome.failed_unit_ids),
            error_type=outcome.last_error_type,
            status="transport" if outcome.transport_failure else "execution",
        )

    numeric_warnings = _apply_numeric_guard(translation_units, outcome, stats, numeric_mode)

    return outcome.translated_by_unit_id, outcome.translation_error, stats, numeric_warnings
