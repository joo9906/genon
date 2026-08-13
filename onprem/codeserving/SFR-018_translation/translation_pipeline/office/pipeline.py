"""번역 오케스트레이션 — 언어·문체 해석 → 분해 → 번역 → 용어사전 검증 → 조립.

[설계]
1. **옵션 해석은 여기서 한 번만** 한다 (`_resolve_options`). 언어 코드/문체 문자열을
   단계마다 다시 해석하면 같은 요청 안에서 판정이 갈릴 수 있다.
2. `trans_map` 은 참고용이다. 같은 원문이 문서에 여러 번 등장하면(예: 반복 머리글)
   dict 키가 충돌하므로, 위치 정확도가 필요한 소비자는 반드시 `pairs`(node_id·unit_id
   기준)를 쓴다.
3. `TranslationRequestError` 에는 우리가 작성한 고정 안내문만 담는다
   (main.py 가 이 메시지를 API 응답 msg 로 그대로 쓴다).
4. **원본을 함께 돌려준다** — 요구사항 §2 가 UI 에 원문·번역본을 나란히 보여주라고
   요구한다. 화면이 원본을 따로 들고 있게 하면 번역 요청 전후로 원본이 갈릴 수 있다.
"""

import asyncio

from config import Config

from translation_pipeline.common import glossary_store
from translation_pipeline.common.prompt_loader import PromptRenderError

from .glossary_report import build_report
from .languages import LanguageNotSupported, glossary_applies, resolve_direction
from .markdown_units import rebuild_markdown, split_markdown
from .registers import resolve_register
from .translation_modes import translate_units
from .types import (
    MarkdownTranslationArtifacts,
    OfficeTranslationArtifacts,
    TranslationOptions,
)
from .units import build_pairs, build_translation_units


class TranslationRequestError(ValueError):
    """입력값 오류 (형식·지원 밖 언어 등). 03-00020003 으로 처리한다.

    계약: 이 예외의 메시지는 사용자에게 그대로 노출되므로, 반드시 이 파일 또는
    `languages.py`/`prompt_loader.py` 처럼 **우리가 문구를 작성한 모듈**의 고정
    한국어 안내문만 담는다. 외부 라이브러리 예외를 감싸서 str(exc) 를 넣지 않는다.
    """


def _resolve_options(
    *, target_lang: str, source_lang: str, register: str, sample_text: str
) -> TranslationOptions:
    """언어 방향과 문체를 확정한다.

    Raises:
        TranslationRequestError: 지원 밖 언어이거나 한국어가 없는 쌍.
    """
    try:
        source, target = resolve_direction(target_lang, source_lang, sample_text)
    except LanguageNotSupported as exc:
        # LanguageNotSupported 의 메시지도 우리가 작성한 고정 안내문이다 (그 파일 계약)
        raise TranslationRequestError(str(exc)) from exc

    resolved_register, fell_back = resolve_register(register)
    return TranslationOptions(
        target_code=target.code,
        target_label=target.label,
        target_korean_label=target.korean_label,
        source_code=source.code if source else "",
        source_label=source.label if source else "the source language",
        source_detected=bool(source) and not (source_lang or "").strip(),
        register_key=resolved_register.key,
        register_label=resolved_register.label,
        register_instruction=resolved_register.instruction,
        register_fell_back=fell_back,
    )


def _options_payload(options: TranslationOptions) -> dict:
    """응답에 싣는 확정 옵션.

    감지로 정한 값(`source_lang_detected`)과 알 수 없는 값이라 기본값으로 떨어뜨린
    문체(`register_fell_back`)를 함께 노출한다 — 사용자가 고른 것과 실제로 적용된 것이
    다를 수 있고, 그걸 알아챌 수단이 이 필드뿐이다.
    """
    return {
        "target_lang": options.target_code,
        "target_lang_label": options.target_korean_label,
        "source_lang": options.source_code,
        "source_lang_detected": options.source_detected,
        "register": options.register_key,
        "register_fell_back": options.register_fell_back,
    }


async def _run(units: list, options: TranslationOptions) -> tuple:
    """공통 실행부 — 두 진입점(노드 배열 / 마크다운)이 같은 경로를 탄다.

    Raises:
        TranslationRequestError: 프롬프트 템플릿을 찾지 못함(배포 구성 오류).
    """
    sem = asyncio.Semaphore(Config.LLM_CONCURRENCY)
    try:
        translated, translation_error, stats, numeric_warnings = await translate_units(
            sem,
            units,
            options,
            max_chars_per_batch=Config.MAX_CHARS_PER_BATCH,
            max_items_per_batch=Config.MAX_ITEMS_PER_BATCH,
            dedup=Config.DEDUPE_UNITS,
            numeric_mode=Config.NUMERIC_GUARD,
        )
    except PromptRenderError as exc:
        # 프롬프트가 없으면 LLM 에 아무 지시 없이 보내지 않고 요청을 세운다.
        # 메시지는 prompt_loader 가 만든 고정 안내문이다.
        raise TranslationRequestError(str(exc)) from exc

    report = build_report(units, translated, options.target_code, options.source_code)
    glossary_payload = report.as_payload()
    glossary_payload["applies"] = glossary_applies(options.source_code, options.target_code)
    glossary_payload["source"] = _glossary_source_status(options)
    return translated, translation_error, stats, numeric_warnings, glossary_payload


def _glossary_source_status(options: TranslationOptions) -> dict:
    """응답의 `glossary.source` — 왜 용어사전이 안 붙었는지까지 말한다.

    **"적용 대상 아님" 과 "적용 대상인데 파일이 없음" 은 다른 사건이다.** 전자는 설계대로고
    (중·태·베·러는 LLM 만으로 번역한다), 후자는 관리자가 손을 써야 하는 상태다. 둘 다
    `available: false` 로만 내려가면 운영에서 구분할 방법이 없다 — 그래서 준수율이 1.0 인
    이유를 물었을 때 답이 갈린다.
    """
    if not glossary_applies(options.source_code, options.target_code):
        return {"available": False, "reason": "not_applicable", "term_count": 0}
    return glossary_store.language_status(options.target_code)


async def run_translation_job(
    *,
    nodes: list,
    target_lang: str,
    source_lang: str = "",
    register: str = "",
) -> OfficeTranslationArtifacts:
    if not nodes:
        raise TranslationRequestError("nodes가 비어 있습니다.")
    if not target_lang or not target_lang.strip():
        raise TranslationRequestError("target_lang이 비어 있습니다.")

    units = build_translation_units(nodes)
    options = _resolve_options(
        target_lang=target_lang,
        source_lang=source_lang,
        register=register,
        sample_text=" ".join(unit.text for unit in units[:50]),
    )

    translated, translation_error, stats, numeric_warnings, glossary = await _run(units, options)

    pairs = build_pairs(units, translated)
    text = "\n".join(pair["translated"] for pair in pairs)

    return OfficeTranslationArtifacts(
        pairs=pairs,
        text=text,
        trans_map={
            unit.text: translated.get(unit.translation_unit_id, unit.text) for unit in units
        },
        translated_by_unit_id=translated,
        translation_error=translation_error,
        stats=stats,
        glossary=glossary,
        numeric_warnings=numeric_warnings,
        options=_options_payload(options),
    )


async def run_markdown_translation_job(
    *,
    markdown: str,
    target_lang: str,
    source_lang: str = "",
    register: str = "",
) -> MarkdownTranslationArtifacts:
    """전처리기 산출물 또는 hwpx 직접 파싱 결과를 구조 보존 방식으로 번역한다.

    표 파이프·HTML 태그·제목·목록·코드펜스 등 구조 문법은 `markdown_units.split_markdown`
    이 스켈레톤으로 분리해 코드가 보존하고, LLM 에는 셀/문장 텍스트만 보낸다.
    → 재조립(`rebuild_markdown`) 결과의 구조는 LLM 출력과 무관하게 원본과 동일.
    실패 유닛은 원문이 유지되고 `translation_error` 로 상위에 노출된다.
    """
    if not markdown or not markdown.strip():
        raise TranslationRequestError("markdown이 비어 있습니다.")
    if not target_lang or not target_lang.strip():
        raise TranslationRequestError("target_lang이 비어 있습니다.")

    segments, units = split_markdown(markdown)
    options = _resolve_options(
        target_lang=target_lang,
        source_lang=source_lang,
        register=register,
        sample_text=markdown,
    )

    if not units:
        # 번역할 텍스트가 전혀 없는 문서(숫자 표 등)는 원문 그대로 반환한다.
        # 언어 검증은 위에서 이미 마쳤다 — 통과했는데 내용이 없는 것과, 지원 밖
        # 언어라 거부되는 것은 다른 사건이다.
        return MarkdownTranslationArtifacts(
            markdown=markdown,
            source_markdown=markdown,
            pairs=[],
            translation_error="",
            options=_options_payload(options),
        )

    translated, translation_error, stats, numeric_warnings, glossary = await _run(units, options)

    return MarkdownTranslationArtifacts(
        markdown=rebuild_markdown(segments, units, translated),
        source_markdown=markdown,
        pairs=build_pairs(units, translated),
        translation_error=translation_error,
        stats=stats,
        glossary=glossary,
        numeric_warnings=numeric_warnings,
        options=_options_payload(options),
    )
