"""`Numeric` 도구 — 수치 추출 후 임계 비교, 사실 정보 교차 대조, chrF.

담당 지표 (README):
- 임계 비교(`<`,`>`,`=`,`between`) — 006 E2E 성공률·턴 수 등 수치 합불
- 018 의미·사실 보존성 1차 방어선: 숫자·날짜·단위·고유명사 원문↔결과 교차 대조
- 018 번역 품질(참조 있는 테스트셋): chrF (한국어에서 BLEU 보다 안정적)

BERTScore 는 여기 없다 — 사전학습 모델 서빙이 필요해 온프레미스 가용성
확인 전에는 켜지 않는다(README 게이트 원칙). 참조 기반 지표를 chrF 만으로
운영할 때는 그 사실을 리포트에 함께 적는다.
"""

import re
from collections import Counter

from .error_codes import (
    ERR_BETWEEN_BOUNDS,
    ERR_EMPTY_ITEMS,
    ERR_GOLD_REQUIRED,
    ERR_MISSING_THRESHOLD,
    ERR_NO_NUMBER_FOUND,
    ERR_UNKNOWN_OPERATOR,
    fail,
)
from .normalize import char_ngrams, normalize, split_sentences

OPERATORS = ("lt", "gt", "eq", "between")

_NUMBER_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?")
# 금액·기간·비율 등 문서에서 실제로 쓰이는 단위 (숫자 바로 뒤 표기).
# 한글 단위는 뒤에 조사가 붙으므로 뒤를 제한하지 않고, 라틴 단위는 단어 경계를
# 요구한다 — 그러지 않으면 'GenOS' 의 G 가 그램으로 잡힌다.
_UNIT_KO_RE = re.compile(
    r"(?<=[\d\s])(퍼센트|만원|억원|천원|개월|시간|달러|원|건|명|개|일|주|년|월|분|초|평|%|㎡)"
)
_UNIT_LATIN_RE = re.compile(r"(?<=[\d\s])(USD|KRW|kg|km|cm|mm|g|t|m)(?![A-Za-z])")
_DATE_RES = (
    re.compile(r"\d{4}\s*[-./]\s*\d{1,2}\s*[-./]\s*\d{1,2}"),
    re.compile(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"),
    re.compile(r"\d{4}\s*년\s*\d{1,2}\s*월"),
    re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일"),
)
# 고유명사 후보: 라틴 대문자 시작 토큰/약어. 형태소 분석기 없이 잡히는 범위만.
_LATIN_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z0-9&.\-]{1,}\b")


def _canonical_date(token: str) -> str:
    """날짜 표기를 표준형으로 바꾼다 — '2026년 3월 12일' 과 '2026-03-12' 는 같은 값이다.

    표기 형식은 다듬기·번역에서 바뀔 수 있고 그것은 사실 왜곡이 아니므로,
    값이 같으면 같다고 봐야 한다(표기 차이로 감점하지 않는다).
    """
    parts = [int(p) for p in re.findall(r"\d+", token)]
    if len(parts) == 3:
        return f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}"
    if len(parts) == 2:
        # 연-월(4자리 시작)인지 월-일인지로 구분
        return f"{parts[0]:04d}-{parts[1]:02d}" if parts[0] > 31 else f"{parts[0]:02d}-{parts[1]:02d}"
    return token


def extract_dates(text: str) -> list:
    """날짜를 표준형(YYYY-MM-DD 등)으로 뽑는다."""
    body = normalize(text)
    found, spans = [], []
    for pattern in _DATE_RES:
        for m in pattern.finditer(body):
            if any(start <= m.start() < end for start, end in spans):
                continue  # 더 긴 형식에 이미 포함된 부분 표기
            spans.append((m.start(), m.end()))
            found.append(_canonical_date(m.group(0)))
    return found


def _strip_dates(text: str) -> str:
    """숫자 대조에서 날짜를 뺀다 — 날짜는 extract_dates 가 따로 재므로 이중 계산이자,
    표기 차이(2026-03-12 vs 2026년 3월 12일)가 숫자 불일치로 잘못 잡히는 원인이다."""
    body = normalize(text)
    for pattern in _DATE_RES:
        body = pattern.sub(" ", body)
    return body


def extract_numbers(text: str, *, skip_dates: bool = False) -> list:
    """콤마·소수점을 포함한 수치를 등장 순서대로 뽑는다 (정규화된 문자열)."""
    body = _strip_dates(text) if skip_dates else normalize(text)
    return [m.group(0).replace(",", "") for m in _NUMBER_RE.finditer(body)]


def extract_units(text: str) -> list:
    body = normalize(text)
    hits = [(m.start(), m.group(0)) for m in _UNIT_KO_RE.finditer(body)]
    hits += [(m.start(), m.group(0)) for m in _UNIT_LATIN_RE.finditer(body)]
    return [unit for _, unit in sorted(hits)]


def extract_entities(text: str, extra: list | None = None) -> list:
    """고유명사 후보.

    NER 모델을 쓰지 않는다 — 라틴 대문자 토큰만 자동으로 잡고, 한국어
    고유명사는 호출부가 `extra`(사전/테스트셋에서 온 목록)로 넘긴 것만 센다.
    자동 추출 한계를 숨기지 않기 위해 결과에 출처를 구분해 담는다.
    """
    body = normalize(text)
    auto = sorted(set(_LATIN_ENTITY_RE.findall(body)))
    given = sorted({term for term in (extra or []) if normalize(str(term)) in body})
    return sorted(set(auto) | set(given))


def compare_threshold(
    value: float | str,
    operator: str,
    *,
    threshold: float | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> dict:
    """수치 임계 비교. value 가 문자열이면 첫 수치를 추출해서 쓴다."""
    if operator not in OPERATORS:
        fail(ERR_UNKNOWN_OPERATOR, event="numeric_unknown_operator")

    if isinstance(value, str):
        numbers = extract_numbers(value)
        if not numbers:
            fail(ERR_NO_NUMBER_FOUND, event="numeric_no_number_found")
        number = float(numbers[0])
    else:
        number = float(value)

    if operator == "between":
        if minimum is None or maximum is None:
            fail(ERR_BETWEEN_BOUNDS, event="numeric_between_bounds_missing")
        passed = minimum <= number <= maximum
        bound = {"min": minimum, "max": maximum}
    else:
        if threshold is None:
            fail(ERR_MISSING_THRESHOLD, event="numeric_threshold_missing")
        passed = {"lt": number < threshold, "gt": number > threshold, "eq": number == threshold}[operator]
        bound = {"threshold": threshold}

    return {"value": number, "operator": operator, "passed": passed, **bound}


def cross_check_facts(source: str, result: str, *, entities: list | None = None) -> dict:
    """원문↔결과의 숫자·날짜·단위·고유명사 교차 대조 (1차 방어선).

    다듬기/번역은 문장을 다시 쓰므로 문장 단위 비교는 무의미하다. 사실 정보만
    다중집합으로 비교해 **원문에 있는데 결과에서 사라진 것**(dropped)과
    **결과에만 새로 생긴 것**(added, 환각 후보)을 따로 낸다.
    """
    def diff(kind_source: list, kind_result: list) -> dict:
        remaining = list(kind_result)
        dropped = []
        for item in kind_source:
            if item in remaining:
                remaining.remove(item)
            else:
                dropped.append(item)
        return {"dropped": dropped, "added": remaining}

    # 숫자·단위는 날짜를 뺀 본문에서 센다 — 날짜는 표준형으로 따로 비교하므로
    # 표기 차이(2026년 3월 12일 ↔ 2026-03-12)가 숫자/단위 불일치로 번지지 않게 한다.
    src_body, res_body = _strip_dates(source), _strip_dates(result)
    checks = {
        "numbers": diff(extract_numbers(src_body), extract_numbers(res_body)),
        "dates": diff(extract_dates(source), extract_dates(result)),
        "units": diff(extract_units(src_body), extract_units(res_body)),
        "entities": diff(extract_entities(source, entities), extract_entities(result, entities)),
    }
    penalties = {kind: len(v["dropped"]) + len(v["added"]) for kind, v in checks.items()}
    return {
        "checks": checks,
        "penalty_counts": penalties,
        "passed": sum(penalties.values()) == 0,
        "entity_extraction": "latin_uppercase_and_given_terms",  # NER 모델 미사용 명시
    }


def chrf(candidate: str, reference: str, *, max_n: int = 6, beta: float = 2.0) -> dict:
    """문자 n-gram F-score (chrF). 참조 번역이 있는 테스트셋 전용.

    표준 chrF: n=1..max_n 각 차수의 precision/recall 을 평균한 뒤 F-beta.
    beta=2 는 recall 가중(원문 정보 누락을 더 아프게 본다).
    """
    if not reference or not reference.strip():
        fail(ERR_GOLD_REQUIRED, event="chrf_reference_missing")

    precisions, recalls = [], []
    for size in range(1, max_n + 1):
        cand, ref = char_ngrams(candidate, size), char_ngrams(reference, size)
        if not cand or not ref:
            continue
        # **다중집합 교집합을 Counter 로 센다** (2026-08-30). 그전에는 `list.remove` 를
        # 반복해서 O(n²) 였고, 서로 다른 3천자/5천자 문서 한 쌍에 0.5초가 걸렸다 —
        # 문서가 열 배면 백 배가 되므로 규정집 한 벌로 배치 채점이 멎는다.
        # 계산 결과는 같다(다중집합 교집합의 크기).
        hit = sum((Counter(cand) & Counter(ref)).values())
        precisions.append(hit / len(cand))
        recalls.append(hit / len(ref))

    if not precisions:
        fail(ERR_EMPTY_ITEMS, event="chrf_no_comparable_ngrams")

    precision = sum(precisions) / len(precisions)
    recall = sum(recalls) / len(recalls)
    denom = beta**2 * precision + recall
    score = (1 + beta**2) * precision * recall / denom if denom else 0.0
    return {
        "chrf": round(score, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "beta": beta,
        "max_n": max_n,
        "note_bertscore": "미포함 — 임베딩/모델 서빙 가용성 확인 후 별도 도구로 추가",
    }


def sentence_length_stats(text: str) -> dict:
    """문장 길이 분포 (참고용 지표 — 합불 기준 아님, README 명시)."""
    sentences = split_sentences(text)
    if not sentences:
        fail(ERR_EMPTY_ITEMS, event="length_stats_no_sentences")
    lengths = sorted(len(s) for s in sentences)
    mid = len(lengths) // 2
    return {
        "sentences": len(sentences),
        "mean_chars": round(sum(lengths) / len(lengths), 2),
        "median_chars": lengths[mid] if len(lengths) % 2 else (lengths[mid - 1] + lengths[mid]) / 2,
        "max_chars": lengths[-1],
        "min_chars": lengths[0],
        "advisory_only": True,
    }
