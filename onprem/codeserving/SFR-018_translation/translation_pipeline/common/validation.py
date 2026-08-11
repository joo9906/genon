"""LLM 배치 번역 응답 검증.

LLM이 개수를 누락하거나 id를 다르게 돌려주는 경우가 실제로 발생하므로,
그대로 신뢰하지 않고 기대값(expected)과 대조해 정상 항목만 채택한다.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ValidationResult:
    normalized: Dict[int, str] = field(default_factory=dict)
    hard_errors: List[str] = field(default_factory=list)
    soft_warnings: List[str] = field(default_factory=list)


def validate_translation_batch_response(
    parsed_items: Any,
    expected: Dict[int, str],
) -> ValidationResult:
    result = ValidationResult()

    if not isinstance(parsed_items, list):
        result.hard_errors.append("response is not a JSON array")
        return result

    for item in parsed_items:
        if not isinstance(item, dict) or "id" not in item:
            result.soft_warnings.append(f"skipping malformed item: {item!r}")
            continue
        try:
            tid = int(item["id"])
        except (TypeError, ValueError):
            result.soft_warnings.append(f"non-integer id: {item.get('id')!r}")
            continue
        if tid not in expected:
            result.soft_warnings.append(f"unexpected id: {tid}")
            continue
        translated = item.get("t")
        if not isinstance(translated, str) or not translated.strip():
            result.soft_warnings.append(f"empty translation for id={tid}")
            continue
        result.normalized[tid] = translated

    if not result.normalized:
        result.hard_errors.append("no valid items in response")

    return result
