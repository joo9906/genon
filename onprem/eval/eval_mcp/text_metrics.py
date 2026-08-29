"""`Text` 도구 — 정규화 후 결정적 문자열 채점.

담당 지표 (README):
- 006 필드 추출 정확도: 필드별 precision / recall / F1, 값 exact / 부분 일치
- 018 용어집 준수율
- 018 FAQ 근거성 1차 스크리닝: n-gram 중복 · 자카드

전부 참조(정답)나 원천 텍스트가 있어야 계산되는 지표다 — 참조가 없으면
호출부가 측정을 건너뛰도록 계약 위반을 예외로 알린다(ERR_GOLD_REQUIRED).
"""

import re

from .error_codes import (
    ERR_BAD_REGEX,
    ERR_EMPTY_ITEMS,
    ERR_GOLD_REQUIRED,
    ERR_NGRAM_SIZE,
    ERR_NOT_A_MAPPING,
    ERR_UNKNOWN_MATCH_MODE,
    fail,
)
from .normalize import normalize, split_sentences, word_ngrams

MATCH_MODES = ("exact", "contains", "regex")


def match_text(
    text: str,
    expected: str,
    *,
    mode: str = "exact",
    drop_punct: bool = False,
    lower: bool = False,
) -> dict:
    """정규화 후 exact / contains / 정규식 매칭 결과."""
    if mode not in MATCH_MODES:
        fail(ERR_UNKNOWN_MATCH_MODE, event="match_unknown_mode")

    if mode == "regex":
        try:
            pattern = re.compile(expected)
        except re.error as exc:
            fail(ERR_BAD_REGEX, event="match_bad_regex", from_exc=exc)
        hit = pattern.search(text or "")
        return {
            "mode": mode,
            "passed": hit is not None,
            "matched": hit.group(0) if hit else "",
        }

    left = normalize(text, drop_punct=drop_punct, lower=lower)
    right = normalize(expected, drop_punct=drop_punct, lower=lower)
    passed = left == right if mode == "exact" else right in left
    return {"mode": mode, "passed": passed, "normalized_text": left, "normalized_expected": right}


# ─────────────────────────────────────────────────────────────
# 006 — 필드 추출 정확도
# ─────────────────────────────────────────────────────────────
def _value_verdict(pred: str, gold: str) -> str:
    """값 일치 판정: exact / partial / wrong."""
    p, g = normalize(pred, drop_punct=True), normalize(gold, drop_punct=True)
    if p == g:
        return "exact"
    if p and g and (p in g or g in p):
        return "partial"
    return "wrong"


def score_extraction_sample(predicted: dict, gold: dict, allowed_names: list | None = None) -> dict:
    """발화 1건의 `{필드명: 값}` 추출을 채점한다.

    - 필드 검출: gold 키 대비 tp / fp / fn
    - 값 정확도: 검출된(tp) 필드에서 exact / partial / wrong
    - 환각: allowed_names(템플릿 스키마 화이트리스트)를 준 경우, 그 밖의 키

    환각은 `Structure` 지표(화이트리스트 기각)와 같은 정의를 쓴다 —
    운영 코드(field_judge.parse_updates)가 이미 기각 건수를 로그로 내보내므로
    평가에서도 같은 기준으로 세어 수치가 어긋나지 않게 한다.
    """
    if not isinstance(predicted, dict) or not isinstance(gold, dict):
        fail(ERR_NOT_A_MAPPING, event="extraction_not_mapping")
    if not gold:
        fail(ERR_GOLD_REQUIRED, event="extraction_gold_missing")

    whitelist = set(allowed_names) if allowed_names else None
    pred_keys, gold_keys = set(predicted), set(gold)

    tp = sorted(pred_keys & gold_keys)
    fp = sorted(pred_keys - gold_keys)
    fn = sorted(gold_keys - pred_keys)

    values = {name: _value_verdict(str(predicted[name]), str(gold[name])) for name in tp}
    hallucinated = sorted(k for k in pred_keys if whitelist is not None and k not in whitelist)

    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "value_verdicts": values,
        "hallucinated_fields": hallucinated,
        "whitelist_applied": whitelist is not None,
    }


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def aggregate_extraction(samples: list) -> dict:
    """여러 발화의 추출 채점을 필드별 / 전체로 집계한다.

    samples: [{"predicted": {...}, "gold": {...}, "allowed_names": [...] (선택)}]
    """
    if not samples:
        fail(ERR_EMPTY_ITEMS, event="extraction_samples_empty")

    per_field: dict = {}
    totals = {"tp": 0, "fp": 0, "fn": 0}
    value_counts = {"exact": 0, "partial": 0, "wrong": 0}
    hallucinated_total = 0
    predicted_keys_total = 0
    whitelisted_samples = 0
    details = []

    for sample in samples:
        scored = score_extraction_sample(
            sample.get("predicted") or {},
            sample.get("gold") or {},
            sample.get("allowed_names"),
        )
        details.append(scored)
        predicted_keys_total += len(sample.get("predicted") or {})
        hallucinated_total += len(scored["hallucinated_fields"])
        whitelisted_samples += 1 if scored["whitelist_applied"] else 0

        for bucket, key in (("true_positive", "tp"), ("false_positive", "fp"), ("false_negative", "fn")):
            for name in scored[bucket]:
                slot = per_field.setdefault(name, {"tp": 0, "fp": 0, "fn": 0, "exact": 0, "partial": 0, "wrong": 0})
                slot[key] += 1
                totals[key] += 1
        for name, verdict in scored["value_verdicts"].items():
            per_field[name][verdict] += 1
            value_counts[verdict] += 1

    matched = sum(value_counts.values())
    return {
        "samples": len(samples),
        "overall": _prf(totals["tp"], totals["fp"], totals["fn"]),
        "per_field": {
            name: {
                **_prf(slot["tp"], slot["fp"], slot["fn"]),
                "value_exact": slot["exact"],
                "value_partial": slot["partial"],
                "value_wrong": slot["wrong"],
            }
            for name, slot in sorted(per_field.items())
        },
        "value_accuracy": {
            "exact_rate": round(value_counts["exact"] / matched, 4) if matched else 0.0,
            "partial_rate": round(value_counts["partial"] / matched, 4) if matched else 0.0,
            "wrong_rate": round(value_counts["wrong"] / matched, 4) if matched else 0.0,
            **value_counts,
        },
        # ── 환각률은 **화이트리스트를 준 표본에서만** 정의된다 (2026-08-30) ──
        #
        # 환각 = "템플릿 스키마에 없는 필드를 지어냈다" 이므로 스키마(`allowed_names`)를
        # 주지 않으면 셀 대상이 없다. 그전에는 그 경우에도 `rate: 0.0` 을 냈고,
        # 스위트 기준이 `hallucination.rate < 0.05` 라 **한 번도 재지 않은 지표가 늘
        # 통과**했다 — eval 규약("미측정을 통과로 보이게 하지 않는다")을 정면으로 어긴다.
        # 이제 `None` 을 내고 `run_suite` 의 `_dig` 가 `not_measured` 로 잡는다.
        "hallucination": {
            "rejected_fields": hallucinated_total,
            "predicted_fields": predicted_keys_total,
            "whitelisted_samples": whitelisted_samples,
            "measurable": whitelisted_samples > 0,
            "rate": (
                round(hallucinated_total / predicted_keys_total, 4)
                if whitelisted_samples and predicted_keys_total
                else None
            ),
        },
        "details": details,
    }


# ─────────────────────────────────────────────────────────────
# 018 — 용어집 준수율
# ─────────────────────────────────────────────────────────────
def glossary_compliance(source: str, target: str, glossary: dict) -> dict:
    """원문에 용어집 용어가 등장한 건에 대해 지정 번역어 사용 비율.

    glossary: {"원문 용어": "지정 번역어"} 또는 {"원문 용어": ["허용어1", "허용어2"]}
    분모는 "원문에 등장한 용어 수"다 — 등장하지 않은 용어는 준수/위반 어느
    쪽으로도 세지 않는다(측정 불가 항목을 점수에 섞지 않는다).
    """
    if not glossary:
        fail(ERR_EMPTY_ITEMS, event="glossary_empty")

    src = normalize(source, lower=True)
    tgt = normalize(target, lower=True)
    applicable, violations = [], []

    for term, expected in glossary.items():
        if normalize(term, lower=True) not in src:
            continue
        allowed = expected if isinstance(expected, (list, tuple)) else [expected]
        applicable.append(term)
        if not any(normalize(str(a), lower=True) in tgt for a in allowed):
            violations.append({"term": term, "expected": [str(a) for a in allowed]})

    total = len(applicable)
    return {
        "applicable_terms": total,
        "violations": violations,
        "compliance_rate": round((total - len(violations)) / total, 4) if total else None,
        "measurable": total > 0,
    }


# ─────────────────────────────────────────────────────────────
# 018 — FAQ 근거성 1차 스크리닝
# ─────────────────────────────────────────────────────────────
def grounding_overlap(answer: str, sources: list, *, ngram: int = 3) -> dict:
    """답변 문장별 원천 문서와의 n-gram 중복률 · 자카드 유사도.

    낮은 점수가 곧 오답은 아니다(재서술 가능) — README 대로 게이트 입력용
    스크리닝 점수만 낸다. 판정은 gating.gate_llm_judge 가 한다.
    """
    if ngram < 1:
        fail(ERR_NGRAM_SIZE, event="grounding_bad_ngram_size")
    if not sources:
        fail(ERR_GOLD_REQUIRED, event="grounding_sources_missing")

    # 자카드 비교 단위는 **원천 문장**이다 (2026-08-30). 원천을 통째로 하나의 집합으로
    # 놓으면 분모가 문서 길이에 비례해, 같은 답변이 긴 문서에서는 낮은 점수를 받는다
    # (실측: 같은 문장이 짧은 원천 1.0 → 200문장 원천 0.2). 문서 길이에 따라 값이
    # 달라지는 지표에는 임계를 걸 수 없다. 문장 대 문장으로 재고 **가장 비슷한 원천
    # 문장의 값**을 쓴다 — "이 답변이 어느 원천 문장에서 왔는가" 가 재려던 것이다.
    source_units = [
        set(word_ngrams(unit, ngram))
        for src in sources
        for unit in (split_sentences(str(src)) or [str(src)])
    ]
    source_units = [unit for unit in source_units if unit]
    source_grams: set = set()
    for grams in source_units:
        source_grams |= grams

    rows = []
    for sentence in split_sentences(answer):
        grams = word_ngrams(sentence, ngram)
        gram_set = set(grams)
        if not gram_set:
            continue
        hit = len(gram_set & source_grams)
        # 가장 비슷한 **원천 문장**과의 자카드 (위 `source_units` 주석 참고).
        best = 0.0
        for grams_of_unit in source_units:
            union = len(gram_set | grams_of_unit)
            if union:
                best = max(best, len(gram_set & grams_of_unit) / union)
        rows.append(
            {
                "sentence": sentence,
                "ngram_overlap": round(hit / len(gram_set), 4),
                "jaccard": round(best, 4),
            }
        )

    if not rows:
        fail(ERR_EMPTY_ITEMS, event="grounding_no_sentences")
    return {
        "ngram": ngram,
        "sentences": rows,
        "mean_ngram_overlap": round(sum(r["ngram_overlap"] for r in rows) / len(rows), 4),
        "min_ngram_overlap": min(r["ngram_overlap"] for r in rows),
    }
