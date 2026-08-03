"""번역용 시스템/유저 프롬프트 빌더.

프롬프트 문자열을 호출 로직과 분리해두면, 나중에 GenOS Prompt 리소스(10.5절)로
이관하기도 쉽고, 문구 수정 시 코드 리뷰 범위를 좁게 유지할 수 있다.
"""

import json
from typing import Any, Dict, List, Tuple

from translation_pipeline.common.glossary import GlossaryHit


def get_translation_system_prompt(target_lang: str, style_options: Dict[str, Any] | None = None) -> str:
    return (
        f"You are a professional document translator. Translate each item into {target_lang}. "
        "Return a JSON array only: [{\"id\": <int>, \"t\": \"<translated text>\"}, ...]. "
        "Keep the same order and same number of items as the input. No extra text."
    )


def get_single_translation_system_prompt(target_lang: str) -> str:
    return f"Translate the given text into {target_lang}. Return only the translated text."


def build_glossary_block(hits: List[GlossaryHit]) -> str:
    """용어사전 매칭 결과를 프롬프트에 주입할 지시문으로 변환한다.

    매칭이 없으면 빈 문자열을 반환하므로, 호출부는 항상 이 값을 그대로
    build_batch_user_prompt / build_single_user_prompt에 넘기면 된다
    (glossary 조회 실패로 hits가 비어 있어도 프롬프트 구조가 깨지지 않는다).
    """
    if not hits:
        return ""
    lines = [f'- "{h.term_source}" -> "{h.term_target}"' for h in hits]
    return (
        "GLOSSARY (use exactly the target term below whenever the source term appears; "
        "terms not listed here may be translated freely):\n" + "\n".join(lines)
    )


def build_batch_user_prompt(batch: List[Tuple[int, str]], glossary_block: str = "") -> str:
    items = [{"id": tid, "s": text} for tid, text in batch]
    body = json.dumps(items, ensure_ascii=False)
    return f"{glossary_block}\n\n{body}" if glossary_block else body


def build_single_user_prompt(
    text: str,
    *,
    source_label: str = "SOURCE_TEXT",
    target_lang: str = "",
    context_instruction: str = "",
    extra_instruction: str = "",
    style_options: Dict[str, Any] | None = None,
    context_label: str = "CONTEXT",
    context_text: str = "",
    previous_translation: str = "",
    doc_format: str = "",
    element_type: str = "",
    glossary_block: str = "",
) -> str:
    parts = []
    if glossary_block:
        parts.append(glossary_block)
    parts.append(f"{source_label}: {text}")
    if context_text:
        parts.append(f"{context_label}: {context_text}")
    if context_instruction:
        parts.append(context_instruction)
    if extra_instruction:
        parts.append(extra_instruction)
    if previous_translation:
        parts.append(f"PREVIOUS_TRANSLATION: {previous_translation}")
    return "\n".join(parts)
