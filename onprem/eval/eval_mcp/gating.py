"""`LLM Judge` 게이트 — 어떤 건에만 생성형 판정을 붙일지 결정한다.

README 원칙을 코드로 강제하는 곳이다.
- 결정적(`Text`/`Numeric`/`Structure`) 지표를 통과한 건은 **후보에서 제외**한다.
- 임베딩 유사도가 임계 이상인 건도 제외한다 (스크리닝 통과).
- 남은 후보에서도 샘플링 비율만큼만 고른다. **전건 상시 호출 금지.**
- `opt_in` 이 참이고 서빙 가용성이 확인(`judge_enabled`)돼야 실제 대상이 된다.

이 모듈은 판정 모델을 호출하지 않는다 — 무엇을 판정할지만 정한다.
임베딩/판정 모델 호출은 온프레미스 서빙 가용성 확인 후 별도 도구로 붙인다.
그래서 유사도는 여기서 계산하지 않고 **호출부가 계산해 넘긴 값**을 쓴다.

샘플링은 난수가 아니라 항목 id 해시로 뽑는다 — 같은 입력이면 같은 표본이
나와야 지표를 재현하고 비교할 수 있다.
"""

import hashlib

from .error_codes import (
    ERR_BAD_SAMPLE_RATE,
    ERR_EMPTY_ITEMS,
    ERR_JUDGE_NOT_ENABLED,
    fail,
)
from .logging_utils import log_info, log_warning

DEFAULT_SAMPLE_RATE = 0.1
DEFAULT_SIMILARITY_THRESHOLD = 0.8


def _sampled(identifier: str, sample_rate: float, salt: str) -> bool:
    digest = hashlib.sha256(f"{salt}:{identifier}".encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return bucket < sample_rate


def gate_llm_judge(
    items: list,
    *,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    sample_rate: float = DEFAULT_SAMPLE_RATE,
    opt_in: bool = False,
    judge_enabled: bool = False,
    salt: str = "genon-eval",
) -> dict:
    """게이트 판정.

    items: [{"id": "...", "deterministic_passed": bool, "similarity": float|None}]
      - deterministic_passed: 결정적 지표 통과 여부 (필수)
      - similarity: 임베딩 스크리닝 점수 (없으면 스크리닝 미실시로 본다)

    Returns: 후보 / 표본 / 제외 목록과 차단 사유. 예외를 던지지 않고 사유를
    결과에 담는 이유는, 게이트가 닫혀 있다는 것도 리포트해야 할 정보이기 때문이다.
    """
    if not items:
        fail(ERR_EMPTY_ITEMS, event="gate_empty_items")
    if not 0 <= sample_rate <= 1:
        fail(ERR_BAD_SAMPLE_RATE, event="gate_bad_sample_rate")

    candidates, screened_out, no_screening = [], [], []
    for index, item in enumerate(items):
        ident = str(item.get("id", index))
        if item.get("deterministic_passed") is True:
            similarity = item.get("similarity")
            if similarity is None:
                no_screening.append(ident)
                screened_out.append({"id": ident, "reason": "deterministic_passed"})
                continue
            if float(similarity) >= similarity_threshold:
                screened_out.append({"id": ident, "reason": "embedding_passed"})
                continue
            candidates.append({"id": ident, "reason": "low_similarity", "similarity": float(similarity)})
            continue
        candidates.append({"id": ident, "reason": "deterministic_failed"})

    gate_open = bool(opt_in and judge_enabled)
    sampled = (
        [c for c in candidates if _sampled(c["id"], sample_rate, salt)] if gate_open else []
    )

    # 게이트가 무엇을 걸러내고 무엇을 판정으로 넘겼는지는 운영에서 확인해야 하는
    # 수치다 (전건 호출 금지 원칙이 실제로 지켜지는지의 근거).
    log_info(
        "LLM Judge 게이트 판정",
        event="llm_judge_gate",
        item_count=len(items),
        status=(
            f"candidates={len(candidates)} screened_out={len(screened_out)} "
            f"sampled={len(sampled)} open={gate_open}"
        ),
    )
    if no_screening:
        log_warning(
            "임베딩 스크리닝 없이 결정적 통과로만 판정한 항목이 있다",
            event="embedding_screening_absent",
            item_count=len(no_screening),
        )

    return {
        "items": len(items),
        "candidates": candidates,
        "screened_out": screened_out,
        "sampled_for_judge": sampled,
        "sample_rate": sample_rate,
        "similarity_threshold": similarity_threshold,
        "gate_open": gate_open,
        "blocked_reason": None if gate_open else ERR_JUDGE_NOT_ENABLED,
        "items_without_embedding_screening": no_screening,
        "policy": "결정적·임베딩 통과분은 판정하지 않는다. 전건 호출 금지.",
    }
