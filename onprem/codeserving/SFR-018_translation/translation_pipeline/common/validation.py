"""LLM 배치 번역 응답 검증.

LLM이 개수를 누락하거나 id를 다르게 돌려주는 경우가 실제로 발생하므로,
그대로 신뢰하지 않고 기대값(expected)과 대조해 정상 항목만 채택한다.

## 기각 사유를 문자열로 만들지 않는다 (2026-08-13)

예전에는 `soft_warnings` 에 `f"skipping malformed item: {item!r}"` 처럼 **LLM 응답 원문을
그대로 넣은 문자열**을 쌓았다. 아무도 읽지 않는 필드였지만(호출부는 `hard_errors` 의
개수만 본다) 3.8절이 금지하는 것은 로그 출력이 아니라 **그 경로가 존재하는 것**이다 —
누군가 나중에 "디버깅에 도움 되겠다" 며 이 목록을 로그에 흘리면 문서 원문과 번역문이
통째로 로그로 나간다. `translation_modes` 가 검증 실패를 건수로만 남기는 것과 같은 규율이다.

그래서 **사유별 건수만** 센다. 배치가 왜 기각됐는지는 이 숫자들로 충분히 갈린다
(형식 오류인가 / id 가 안 맞나 / 번역문이 비었나).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ValidationResult:
    normalized: Dict[int, str] = field(default_factory=dict)
    hard_errors: List[str] = field(default_factory=list)
    # 사유별 기각 건수. **값이 아니라 수만 담는다** (머리말 참고).
    # 키: malformed(형식 오류) / bad_id(정수 아님·기대 밖) / empty(번역문 없음)
    skipped: Dict[str, int] = field(default_factory=dict)

    def _skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    @property
    def skipped_count(self) -> int:
        return sum(self.skipped.values())


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
            result._skip("malformed")
            continue
        try:
            tid = int(item["id"])
        except (TypeError, ValueError):
            result._skip("bad_id")
            continue
        if tid not in expected:
            result._skip("bad_id")
            continue
        translated = item.get("t")
        if not isinstance(translated, str) or not translated.strip():
            result._skip("empty")
            continue
        result.normalized[tid] = translated

    if not result.normalized:
        result.hard_errors.append("no valid items in response")

    return result
