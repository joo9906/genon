"""번역문의 숫자 보존 검증 — 결정적 도구, LLM 재확인 없음.

루트 `README.md` 018 지표 2절이 "숫자·날짜·단위 추출 후 원문·결과 교차 대조"를
**1차 방어선이자 운영 지표**로 잡고 있는데, 번역 배포 단위에는 그 검사가 없었다
(006 에는 `value_guard.py`, 글다듬이에는 `markdown_guard.py` 가 있다).
이 파일이 그 자리를 메운다.

## 무엇을 잡는가

LLM 이 번역하면서 금액·날짜·수량을 바꾸거나 빠뜨리는 사고. 문장은 그럴듯하게
읽히므로 사람이 훑어서는 못 잡고, 사후에 발견되면 문서를 이미 배포한 뒤다.

## 정규화 규칙 (오탐을 줄이는 쪽으로)

숫자 표기는 언어마다 다르다 — `1,000` / `1.000` / `1 000` 이 모두 같은 수다.
그래서 숫자 덩어리 안의 자릿수 구분 기호(`,` `.` 공백 `'`)를 **전부 제거한** 뒤
비교한다. `1,000` 과 `1.000` 은 같은 지문이 되고, 소수점 표기가 바뀌어도
(`1.5` ↔ `1,5`) 오탐이 나지 않는다. 대신 `1.5` 와 `15` 를 구분하지 못한다 —
자릿수 구분과 소수점을 표기만으로 가를 수 없어서 택한 절충이고, 이쪽 방향의
오검(놓침)이 오탐보다 낫다고 봤다.

전각 숫자(`１２３`)는 반각으로 접어 비교한다.

## 한계 (알고 쓰는 것)

- 한글·한자 수사(`삼십만`, `三十`)는 잡지 않는다. 아라비아 숫자만 본다.
- 번역 대상 언어가 수를 문자로 풀어 쓰면(`3` → `three`) 누락으로 잡힌다.
  프롬프트가 숫자 보존을 지시하고 있으므로 그 경우는 실제로 고쳐야 할 이탈이다.
"""

import re
from collections import Counter

# 숫자 덩어리 = 숫자로 시작해 숫자로 끝나는, 구분기호가 섞일 수 있는 구간
_NUMBER_RE = re.compile(r"[0-9０-９](?:[0-9０-９.,'  ]*[0-9０-９])?")
_SEPARATORS = str.maketrans("", "", ".,'  ")
_FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")

# 검증 모드 — 운영에서 바꿀 수 있는 정책
MODE_WARN = "warn"      # 번역문을 그대로 쓰고 경고만 노출 (기본)
MODE_REVERT = "revert"  # 이탈한 유닛은 원문으로 되돌린다


def fingerprint(text: str) -> Counter:
    """텍스트에 담긴 숫자들의 정규화 지문."""
    numbers = []
    for match in _NUMBER_RE.finditer(text or ""):
        normalized = match.group(0).translate(_FULLWIDTH).translate(_SEPARATORS)
        if normalized:
            numbers.append(normalized.lstrip("0") or "0")
    return Counter(numbers)


def find_numeric_drift(source: str, translated: str) -> dict:
    """원문에 있던 숫자가 번역문에서 사라지거나 새로 생겼는지 본다.

    Returns:
        `{"missing": [...], "added": [...]}`. 둘 다 비어 있으면 이탈 없음.
        값 자체를 담는 이유: 호출부가 사용자에게 "어떤 수가 어긋났는지" 보여줘야
        확인이 가능하다. **로그에는 싣지 않는다** — 문서 내용이다 (3.8절).
    """
    source_numbers = fingerprint(source)
    translated_numbers = fingerprint(translated)
    missing = source_numbers - translated_numbers
    added = translated_numbers - source_numbers
    return {
        "missing": sorted(missing.elements()),
        "added": sorted(added.elements()),
    }


def has_drift(drift: dict) -> bool:
    return bool(drift["missing"] or drift["added"])
