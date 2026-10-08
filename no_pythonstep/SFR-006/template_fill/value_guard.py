"""톤 변환 결과 검증 — 문서 값의 사실 정보가 보존됐는지 결정적으로 확인한다.

톤 변환은 LLM 이 값을 다시 쓰는 단계다. 프롬프트로 "수치를 유지하라"고 지시하는 것은
보장이 아니므로(LLM 응답을 믿지 않는다 — CLAUDE.md §5), 변환 전/후에서
**숫자·날짜를 뽑아 다중집합으로 대조**하고 어긋나면 그 필드는 원본 값을 유지한다.

여기서 재는 기준은 018 평가지표의 '의미·사실 보존성' 1차 방어선과 같다
(eval/eval_mcp/numeric_metrics.cross_check_facts). 지표와 운영 코드가 같은 정의를
쓰지 않으면 "평가는 통과인데 운영은 깨진" 상태가 생긴다.

톤 변환에서 어떤 필드도 값을 잃지 않게 하는 것이 목적이므로, 판정은 보수적이다 —
의심스러우면 변환을 버리고 원본을 남긴다.
"""

import re

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_DATE_RES = (
    re.compile(r"\d{4}\s*[-./]\s*\d{1,2}\s*[-./]\s*\d{1,2}"),
    re.compile(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"),
    re.compile(r"\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?"),
)


def _canonical_dates(text: str) -> list:
    """날짜를 표준형(YYYY-MM-DD)으로. '2026. 8. 4.' 과 '2026년 8월 4일' 은 같은 값이다."""
    found, spans = [], []
    for pattern in _DATE_RES:
        for match in pattern.finditer(text):
            if any(start <= match.start() < end for start, end in spans):
                continue
            spans.append((match.start(), match.end()))
            parts = [int(p) for p in re.findall(r"\d+", match.group(0))]
            if len(parts) == 3:
                found.append(f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}")
    return sorted(found)


def _numbers_outside_dates(text: str) -> list:
    """날짜 구간을 뺀 본문의 숫자. 날짜는 따로 비교하므로 이중 계산하지 않는다."""
    body = text
    for pattern in _DATE_RES:
        body = pattern.sub(" ", body)
    return sorted(m.group(0).replace(",", "") for m in _NUMBER_RE.finditer(body))


def fact_diff(original: str, converted: str) -> list:
    """사실 정보 불일치 항목을 낸다 (빈 리스트면 보존됨).

    Returns:
        불일치 종류 목록 — "numbers" / "dates" / "empty_result".
    """
    if not converted.strip():
        return ["empty_result"]
    issues = []
    if _numbers_outside_dates(original) != _numbers_outside_dates(converted):
        issues.append("numbers")
    if _canonical_dates(original) != _canonical_dates(converted):
        issues.append("dates")
    return issues
