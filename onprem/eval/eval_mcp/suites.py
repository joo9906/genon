"""기능별 지표 묶음 — 네 기능은 서로 다른 지표로 평가한다.

README 는 006(템플릿 채우기)과 018 의 세 기능(글다듬이 / 번역 / FAQ)에 각각 다른
지표를 적는다. 개별 도구만 있으면 "이 기능은 무엇으로 합불하는가"가 호출자 머릿속에만
남으므로, 그 묶음을 여기 선언적으로 고정한다.

- `SUITES[기능]["metrics"]`: 그 기능의 지표 목록과 필요한 입력 키
- `SUITES[기능]["targets"]`: 운영 합불 기준 (임계값은 payload 로 덮어쓸 수 있다)
- `run_suite(기능, payload)`: 입력이 있는 지표만 실행하고, **없는 지표는 건너뛴 이유를
  같이 돌려준다** — 측정 공백을 통과로 위장하지 않는다.

합불 판정도 임계 비교 도구(numeric_metrics.compare_threshold)를 재사용한다.
기능마다 다른 것은 "무엇을 재는가"와 "기준값"이고, 재는 방식은 공통이어야 한다.
"""

import time

from . import numeric_metrics, scenario_metrics, structure_metrics, text_metrics, tone_metrics
from .error_codes import ERR_UNKNOWN_FEATURE, EvalInputError, fail
from .pairs import pair_id, pair_texts
from .gating import DEFAULT_SAMPLE_RATE, DEFAULT_SIMILARITY_THRESHOLD, gate_llm_judge
from .logging_utils import log_info, log_warning

# ─────────────────────────────────────────────────────────────
# 기능별 선언
#   needs: payload 에서 요구하는 키 (없으면 그 지표는 건너뛴다)
#   role : operational(운영 합불) / advisory(추세 관찰) / screening(게이트 입력)
# ─────────────────────────────────────────────────────────────
SUITES: dict = {
    "template_fill": {
        "label": "006 HWPX 템플릿 채우기",
        "metrics": [
            {"tool": "field_extraction_score", "tag": "Text", "needs": ["extraction_samples"], "role": "operational"},
            {"tool": "hwpx_fill_roundtrip", "tag": "Structure", "needs": ["hwpx_before", "hwpx_after"], "role": "operational"},
            {"tool": "hwpx_document_integrity", "tag": "Structure", "needs": ["hwpx_before", "hwpx_after"], "role": "operational"},
            {"tool": "hwpx_text_crosscheck", "tag": "Structure", "needs": ["hwpx_before", "hwpx_after"], "role": "operational"},
            {"tool": "multiturn_scenario_score", "tag": "Numeric", "needs": ["scenarios"], "role": "operational"},
        ],
        "targets": [
            {"path": "hwpx_fill_roundtrip.agreement_rate", "operator": "eq", "value": 1.0},
            {"path": "hwpx_document_integrity.passed", "expect": True},
            # 교차검증은 python-hwpx 가 있을 때만 값이 나온다. 없으면 `_dig` 가 None 을
            # 돌려 `not_measured` 로 남는다 — 미측정이 통과로 보이지 않는다.
            {"path": "hwpx_text_crosscheck.no_paragraph_loss", "expect": True},
            {"path": "multiturn_scenario_score.session_accuracy_rate", "operator": "eq", "value": 1.0},
            {"path": "multiturn_scenario_score.completion_rate", "operator": "gt", "value": 0.9},
            {"path": "field_extraction_score.overall.f1", "operator": "gt", "value": 0.8},
            {"path": "field_extraction_score.hallucination.rate", "operator": "lt", "value": 0.05},
        ],
        "note": "LLM 은 발화→{필드명:값} 추출까지만 관여한다. 채움·판정 구간은 결정적이라 회귀로 잡는다.",
    },
    "text_polish": {
        "label": "018 글다듬이",
        "metrics": [
            {"tool": "polish_structure_pass_rate", "tag": "Structure", "needs": ["pairs"], "role": "operational"},
            {"tool": "tone_pass_rate", "tag": "Text", "needs": ["pairs"], "role": "operational"},
            {"tool": "ending_consistency", "tag": "Text", "needs": ["pairs"], "role": "operational"},
            {"tool": "fact_preservation_check", "tag": "Text/Numeric", "needs": ["pairs"], "role": "operational"},
            {"tool": "sentence_length_stats", "tag": "Numeric", "needs": ["pairs"], "role": "advisory"},
        ],
        "targets": [
            {"path": "polish_structure_pass_rate.pass_rate", "operator": "eq", "value": 1.0},
            {"path": "fact_preservation_check.pass_rate", "operator": "eq", "value": 1.0},
            {"path": "tone_pass_rate.pass_rate", "operator": "gt", "value": 0.9},
            {"path": "ending_consistency.consistent_rate", "operator": "gt", "value": 0.9},
        ],
        "note": "톤은 결정적 규칙으로 합불한다 — 자동 LLM 판정을 붙이지 않고, 필요 시 수동 스팟체크.",
    },
    "translation": {
        "label": "018 번역",
        "metrics": [
            {"tool": "translation_structure_health", "tag": "Structure", "needs": ["records"], "role": "operational"},
            {"tool": "fact_preservation_check", "tag": "Text/Numeric", "needs": ["pairs"], "role": "operational"},
            {"tool": "glossary_compliance", "tag": "Text", "needs": ["pairs", "glossary"], "role": "operational"},
            {"tool": "chrf_score", "tag": "Numeric", "needs": ["pairs.reference"], "role": "operational"},
        ],
        "targets": [
            {"path": "translation_structure_health.fallback_rate", "operator": "eq", "value": 0.0},
            {"path": "translation_structure_health.segment_mismatch_rate", "operator": "eq", "value": 0.0},
            {"path": "fact_preservation_check.pass_rate", "operator": "eq", "value": 1.0},
            {"path": "glossary_compliance.mean_compliance_rate", "operator": "gt", "value": 0.95},
        ],
        "note": "참조 번역이 없는 운영 입력은 chrF 를 못 낸다 — 그 구간의 기본 운영 지표는 "
                "임베딩 유사도이며 아직 미구현(호출부가 계산해 게이트에 넘긴다).",
    },
    "faq": {
        "label": "018 FAQ 원천 정합성",
        "metrics": [
            {"tool": "grounding_overlap", "tag": "Text", "needs": ["items"], "role": "screening"},
        ],
        "targets": [],
        "note": "어휘 중복이 낮다고 곧 오답은 아니다(재서술). 그래서 합불 기준을 두지 않고 "
                "낮은 문장만 게이트로 넘긴다.",
    },
}

# 게이트 후보를 만들 때 쓰는 기본 스크리닝 임계 (payload.thresholds 로 덮어쓴다)
DEFAULT_GROUNDING_MIN = 0.3


def list_suites(feature: str | None = None) -> dict:
    """기능별 지표 묶음 정의. feature 를 주면 그 기능만 돌려준다."""
    if feature:
        suite = SUITES.get(feature)
        if suite is None:
            fail(ERR_UNKNOWN_FEATURE, event="suite_unknown_feature")
        return {"feature": feature, **suite}
    return {"features": list(SUITES), "suites": SUITES}


# ─────────────────────────────────────────────────────────────
# 묶음 실행 — 기능별 조립 (계산 로직은 metrics 모듈 것을 그대로 쓴다)
# ─────────────────────────────────────────────────────────────
def _aggregate_facts(pairs: list, entities: list | None) -> dict:
    """항목별 사실 보존 검사를 통과율로 집계한다.

    키 해석은 `pairs.pair_texts` 한 곳에서 한다 — 원문이 없으면 **예외다**
    (빈 문자열끼리 비교해 만점을 주지 않는다).
    """
    failures = []
    for index, pair in enumerate(pairs):
        source, result = pair_texts(pair, index)
        checked = numeric_metrics.cross_check_facts(
            source, result, entities=pair.get("entities") or entities
        )
        if not checked["passed"]:
            failures.append(
                {"index": index, "id": pair_id(pair, index), "checks": checked["checks"],
                 "penalty_counts": checked["penalty_counts"]}
            )
    total = len(pairs)
    return {
        "items": total,
        "pass_rate": round((total - len(failures)) / total, 4),
        "failures": failures,
    }


def _aggregate_glossary(pairs: list, glossary: dict) -> dict:
    rows, measurable = [], 0
    for index, pair in enumerate(pairs):
        source, target = pair_texts(pair, index)
        result = text_metrics.glossary_compliance(
            source, target, pair.get("glossary") or glossary
        )
        if result["measurable"]:
            measurable += 1
            rows.append({"index": index, "id": pair_id(pair, index), **result})
    if not measurable:
        # 용어집 용어가 원문에 없으면 준수율은 정의되지 않는다 — 0점이 아니라 미측정이다
        log_warning(
            "용어집 준수율 측정 불가 (원문에 용어집 용어 없음)",
            event="glossary_not_measurable",
            item_count=len(pairs),
        )
        return {"measurable_items": 0, "mean_compliance_rate": None, "items": rows}
    return {
        "measurable_items": measurable,
        "mean_compliance_rate": round(sum(r["compliance_rate"] for r in rows) / measurable, 4),
        "violations": [r for r in rows if r["violations"]],
    }


def _aggregate_chrf(pairs: list) -> dict:
    scored = [
        {"index": i, "id": p.get("id"), **numeric_metrics.chrf(str(p.get("target", "")), str(p["reference"]))}
        for i, p in enumerate(pairs)
        if p.get("reference")
    ]
    if not scored:
        log_warning(
            "chrF 측정 불가 (참조 번역이 있는 항목 없음)",
            event="chrf_reference_absent",
            item_count=len(pairs),
        )
        return {"items": 0, "mean_chrf": None, "reason": "참조 번역이 있는 항목이 없다"}
    return {
        "items": len(scored),
        "mean_chrf": round(sum(s["chrf"] for s in scored) / len(scored), 4),
        "min_chrf": min(s["chrf"] for s in scored),
        "per_item": scored,
    }


def _aggregate_ending(pairs: list) -> dict:
    """종결어미 일관성 집계 — **잴 수 없는 항목은 분모에서 뺀다.**

    문장이 두어 개뿐인 결과물은 앞뒤 절반 비교가 성립하지 않는다
    (`structure_metrics.ending_consistency` 머리말). 예전에는 그런 항목이 뒤 절반이
    비어 `other` 가 되면서 **무조건 불일치**로 잡혔다 — 짧은 문서만 모으면 이 지표가
    0 이 된다.
    """
    rows, unmeasurable = [], []
    for index, pair in enumerate(pairs):
        _, result = pair_texts(pair, index)
        ident = pair_id(pair, index)
        if not result.strip():
            # 결과물이 없다 = 다듬기 실패. **미측정이 아니라 불일치로 센다.**
            rows.append({"index": index, "id": ident, "consistent": False,
                         "front_dominant": None, "back_dominant": None, "reason": "empty_result"})
            continue
        scored = structure_metrics.ending_consistency(result)
        if not scored.get("measurable", True):
            unmeasurable.append({"id": ident, "reason": scored.get("reason")})
            continue
        rows.append({"index": index, "id": ident, **scored})

    inconsistent = [r for r in rows if not r["consistent"]]
    return {
        "items": len(pairs),
        "measured": len(rows),
        "unmeasurable": unmeasurable,
        # **잰 것 중의 비율**이다. `measured` 와 함께 보지 않으면 1.0 이 전량 일관인지
        # 전량 미측정인지 알 수 없다 (톤 집계의 `scored` 와 같은 규약).
        "consistent_rate": round((len(rows) - len(inconsistent)) / len(rows), 4) if rows else None,
        "inconsistent": [
            {"id": r["id"], "front": r["front_dominant"], "back": r["back_dominant"]}
            for r in inconsistent
        ],
    }


def _aggregate_lengths(pairs: list) -> dict:
    """문장 길이 분포 (참고용). 결과물이 없는 항목은 통계에서 뺀다."""
    rows = []
    for index, pair in enumerate(pairs):
        _, result = pair_texts(pair, index)
        if not result.strip():
            continue
        rows.append(numeric_metrics.sentence_length_stats(result))
    if not rows:
        return {"items": 0, "mean_chars": None, "max_chars": None, "advisory_only": True}
    return {
        "items": len(rows),
        "mean_chars": round(sum(r["mean_chars"] for r in rows) / len(rows), 2),
        "max_chars": max(r["max_chars"] for r in rows),
        "advisory_only": True,
    }


def _has(payload: dict, key: str) -> bool:
    if key == "pairs.reference":
        return any(p.get("reference") for p in payload.get("pairs") or [])
    return bool(payload.get(key))


def _run_template_fill(payload: dict) -> dict:
    metrics = {}
    if payload.get("extraction_samples"):
        metrics["field_extraction_score"] = text_metrics.aggregate_extraction(payload["extraction_samples"])
    if payload.get("hwpx_before") and payload.get("hwpx_after"):
        metrics["hwpx_fill_roundtrip"] = structure_metrics.hwpx_roundtrip(
            payload["hwpx_before"], payload["hwpx_after"], payload.get("written_values")
        )
        metrics["hwpx_document_integrity"] = structure_metrics.hwpx_integrity(
            payload["hwpx_before"], payload["hwpx_after"]
        )
        metrics["hwpx_text_crosscheck"] = structure_metrics.hwpx_text_crosscheck(
            payload["hwpx_before"], payload["hwpx_after"]
        )
    if payload.get("scenarios"):
        metrics["multiturn_scenario_score"] = scenario_metrics.aggregate_scenarios(payload["scenarios"])
    return metrics


def _run_text_polish(payload: dict) -> dict:
    pairs = payload.get("pairs") or []
    if not pairs:
        return {}
    return {
        "polish_structure_pass_rate": structure_metrics.structure_pass_rate(pairs),
        "tone_pass_rate": tone_metrics.tone_pass_rate(
            [
                {
                    "id": pair_id(p, i),
                    "text": pair_texts(p, i)[1],
                    "tone": str(p.get("tone", "")),
                    "doc_type": p.get("doc_type"),
                }
                for i, p in enumerate(pairs)
            ],
            # 조사 검사는 **앞말이 명사임을 아는 자리에서만** 돈다. 목록이 없으면
            # 검사하지 않고 그 사실을 `particle_check.scope` 로 남긴다
            # (`tone_metrics.particle_errors` 머리말 — 넓게 잡으면 `평가`·`증가` 같은
            # 평범한 낱말을 오검출한다).
            payload.get("nouns") or payload.get("glossary_terms"),
        ),
        "ending_consistency": _aggregate_ending(pairs),
        "fact_preservation_check": _aggregate_facts(pairs, payload.get("entities")),
        "sentence_length_stats": _aggregate_lengths(pairs),
    }


def _run_translation(payload: dict) -> dict:
    metrics = {}
    if payload.get("records"):
        metrics["translation_structure_health"] = structure_metrics.translation_fallback_rate(payload["records"])
    pairs = payload.get("pairs") or []
    if pairs:
        metrics["fact_preservation_check"] = _aggregate_facts(pairs, payload.get("entities"))
        if payload.get("glossary") or any(p.get("glossary") for p in pairs):
            metrics["glossary_compliance"] = _aggregate_glossary(pairs, payload.get("glossary") or {})
        if any(p.get("reference") for p in pairs):
            metrics["chrf_score"] = _aggregate_chrf(pairs)
    return metrics


def _run_faq(payload: dict) -> dict:
    """FAQ 근거성 스크리닝.

    **항목 하나가 묶음 전체를 죽이지 않는다** (2026-08-30). 원천이 없거나 답변에
    문장이 없는 항목은 `grounding_overlap` 이 예외를 던지는데, 그러면 나머지 항목의
    채점 결과가 통째로 사라진다. 그런 항목은 `unmeasurable` 로 모아 **드러내고**
    분모에서 뺀다 — 조용히 0점으로 세지도, 통과로 세지도 않는다.
    """
    items = payload.get("items") or []
    if not items:
        return {}
    ngram = int(payload.get("ngram", 3))
    rows, unmeasurable = [], []
    for index, item in enumerate(items):
        ident = item.get("id") if item.get("id") is not None else index
        try:
            scored = text_metrics.grounding_overlap(
                str(item.get("answer", "")), item.get("sources") or [], ngram=ngram
            )
        except EvalInputError as exc:
            unmeasurable.append({"index": index, "id": ident, "reason": str(exc)})
            continue
        rows.append({"index": index, "id": ident, **scored})
    if not rows:
        return {
            "grounding_overlap": {
                "items": 0,
                "unmeasurable": unmeasurable,
                "mean_ngram_overlap": None,
                "per_item": [],
            }
        }
    return {
        "grounding_overlap": {
            "items": len(rows),
            "unmeasurable": unmeasurable,
            "mean_ngram_overlap": round(sum(r["mean_ngram_overlap"] for r in rows) / len(rows), 4),
            "min_ngram_overlap": min(r["min_ngram_overlap"] for r in rows),
            "per_item": rows,
        }
    }


_RUNNERS = {
    "template_fill": _run_template_fill,
    "text_polish": _run_text_polish,
    "translation": _run_translation,
    "faq": _run_faq,
}


# ─────────────────────────────────────────────────────────────
# 합불 판정 + 게이트 후보
# ─────────────────────────────────────────────────────────────
def _dig(metrics: dict, path: str):
    node = metrics
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _judge_candidates(feature: str, metrics: dict, thresholds: dict, payload: dict) -> list:
    """결정적 지표를 통과 못한 항목만 게이트 후보로 만든다 (전건 아님).

    통과분도 `deterministic_passed: True` 로 함께 넘긴다 — 게이트가 "몇 건 중
    몇 건이 스크리닝에서 걸러졌는지"를 리포트할 수 있어야 하기 때문이다.
    """
    candidates = []
    if feature == "faq":
        minimum = float(thresholds.get("grounding_min", DEFAULT_GROUNDING_MIN))
        for row in _dig(metrics, "grounding_overlap.per_item") or []:
            base = row.get("id") if row.get("id") is not None else row["index"]
            for position, sentence in enumerate(row["sentences"]):
                candidates.append(
                    {
                        "id": f"{base}#{position}",
                        "deterministic_passed": sentence["ngram_overlap"] >= minimum,
                        "similarity": None,
                    }
                )
        return candidates

    failures = _dig(metrics, "fact_preservation_check.failures")
    if failures is None:
        return candidates
    failed_ids = {
        str(f.get("id") if f.get("id") is not None else f["index"]) for f in failures
    }
    for index, pair in enumerate(payload.get("pairs") or []):
        # 식별자 해석은 `pairs.pair_id` 한 곳이다 — 두 벌로 두면 게이트 표본과
        # 실패 목록이 서로 다른 id 를 쓰게 되고, 그러면 후보가 엉뚱하게 잡힌다.
        ident = str(pair_id(pair, index))
        candidates.append(
            {"id": ident, "deterministic_passed": ident not in failed_ids, "similarity": None}
        )
    return candidates


def run_suite(
    feature: str,
    payload: dict,
    *,
    judge_opt_in: bool = False,
    judge_enabled: bool = False,
    sample_rate: float = DEFAULT_SAMPLE_RATE,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> dict:
    """기능의 지표 묶음을 실행한다.

    입력이 없는 지표는 실행하지 않고 `skipped` 에 이유를 적는다 — 리포트에서
    "측정 안 함"과 "통과"가 섞이지 않게 하려는 것이다.
    """
    suite = SUITES.get(feature)
    if suite is None:
        fail(ERR_UNKNOWN_FEATURE, event="suite_unknown_feature")
    payload = payload or {}
    thresholds = payload.get("thresholds") or {}

    started = time.monotonic()
    metrics = _RUNNERS[feature](payload)
    skipped = [
        {"tool": spec["tool"], "reason": f"입력 없음: {', '.join(spec['needs'])} (측정 안 함)"}
        for spec in suite["metrics"]
        if spec["tool"] not in metrics and not all(_has(payload, key) for key in spec["needs"])
    ]
    if skipped:
        log_warning(
            "입력이 없어 실행하지 않은 지표가 있다 (미측정)",
            event="suite_metrics_skipped",
            resource_id=feature,
            item_count=len(skipped),
        )

    checks = []
    for target in suite["targets"]:
        actual = _dig(metrics, target["path"])
        if actual is None:
            checks.append({"target": target["path"], "status": "not_measured"})
            continue
        if "expect" in target:
            checks.append(
                {
                    "target": target["path"],
                    "status": "pass" if bool(actual) == target["expect"] else "fail",
                    "actual": actual,
                    "expected": target["expect"],
                }
            )
            continue
        limit = thresholds.get(target["path"], target["value"])
        verdict = numeric_metrics.compare_threshold(actual, target["operator"], threshold=limit)
        checks.append(
            {
                "target": target["path"],
                "status": "pass" if verdict["passed"] else "fail",
                "actual": actual,
                "operator": target["operator"],
                "threshold": limit,
            }
        )

    candidates = _judge_candidates(feature, metrics, thresholds, payload)
    gate = (
        gate_llm_judge(
            candidates,
            similarity_threshold=similarity_threshold,
            sample_rate=sample_rate,
            opt_in=judge_opt_in,
            judge_enabled=judge_enabled,
        )
        if candidates
        else {"items": 0, "candidates": [], "gate_open": False, "blocked_reason": "게이트 후보 없음"}
    )

    failed = [c for c in checks if c["status"] == "fail"]
    measured = [c for c in checks if c["status"] in ("pass", "fail")]
    not_measured = [c["target"] for c in checks if c["status"] == "not_measured"]

    # verdict 는 "측정한 기준에 대한 판정"과 "얼마나 측정했는지"를 분리한다.
    # 기준이 없거나(FAQ) 하나도 못 쟀으면 pass 라고 말하지 않는다.
    if failed:
        verdict = "fail"
    elif not measured:
        verdict = "no_operational_target" if not suite["targets"] else "not_measured"
    elif not_measured:
        verdict = "pass_but_incomplete"
    else:
        verdict = "pass"

    log_info(
        "기능별 지표 묶음 실행 완료",
        event="feature_eval_completed",
        resource_id=feature,
        status=verdict,
        item_count=len(metrics),
        duration_ms=int((time.monotonic() - started) * 1000),
    )

    return {
        "feature": feature,
        "label": suite["label"],
        "note": suite["note"],
        "metrics": metrics,
        "targets": checks,
        "verdict": verdict,
        "passed": verdict == "pass",
        "coverage": {"measured_targets": len(measured), "not_measured_targets": len(not_measured)},
        "failed_targets": failed,
        "not_measured_targets": not_measured,
        "skipped_metrics": skipped,
        "llm_judge_gate": gate,
    }
