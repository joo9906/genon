"""용어사전 1단계 - 정확 매칭 (임베딩 없이 문자열/토큰 비교).

설계 의도
- 용어사전 매칭은 "의미가 비슷한 것"보다 "정확히 그 용어인지"가 훨씬 중요하다.
  애매한 동의어/오탈자 케이스에만 임베딩(2단계, glossary.py)이 필요하고,
  명확한 케이스는 문자열 매칭이 더 정확하고 빠르며 실패 지점(Weaviate/임베딩 API)이 없다.
- 영어 복수형(-s/-es/-ies 등) 같은 활용형을 반영하지 않으면 사전에 "invoice"만
  등록돼 있을 때 원문의 "invoices"를 못 잡으므로, 토큰을 정규화한 뒤 비교한다.
- 단어 경계 없이 raw substring으로 찾으면 "cat"이 "category" 안에서도 걸리는
  오탐이 생기므로, 반드시 토큰 단위로 비교한다.

성능 설계 (중요)
- 후보를 n-gram 슬라이딩(range(max_words, 0, -1))으로 찾으면, 사전에 긴 복합 용어가
  단 한 건이라도 섞이는 순간 모든 배치가 그 단어 수만큼 반복 스캔된다. 실측 기준
  8단어 용어 1건 때문에 배치당 1.6ms -> 33ms(20배)로 악화되며, 이 비용은 사전 크기와
  무관하게 발생한다. 실무 용어사전에는 긴 조항성 항목이 반드시 섞여 들어온다.
- 따라서 "정규화된 첫 단어 -> 그 단어로 시작하는 용어들" 역색인을 만들고, 원문 토큰을
  왼쪽에서 한 번만 훑으면서 각 위치에서 해당 첫 단어를 가진 후보만 검사한다.
  전체 비용이 O(토큰 수 x 위치별 후보 수)가 되어 사전의 최대 단어 수에 영향받지 않는다.

메모리 설계
- 실측: 10만 건 약 31MB, 50만 건 약 150MB. 문자열 dict은 생각보다 가벼워서
  일반적인 사내 용어사전 규모에서는 메모리가 병목이 아니다.
- 다만 K8s Pod에서 OOMKill이 나면 서빙 전체가 죽으므로, max_cached_terms 상한을 두고
  초과 시 캐시를 포기하고 로그를 남긴다. 1단계를 못 쓰더라도 2단계(벡터 검색)로
  번역은 계속 동작한다 -- 침묵 실패가 아니라 명시적 degradation.
- dataclass에 slots=True를 주어 인스턴스당 __dict__ 오버헤드를 제거한다.
"""

import re
from dataclasses import dataclass

from translation_pipeline.common.logging_utils import log_info, log_warning

# 캐시 상한. 초과하면 1단계를 비활성화하고 2단계(벡터)에만 의존한다.
# 실측 기준 50만 건 약 150MB이므로, Pod 메모리 여유에 맞춰 호출부에서 조정한다.
_DEFAULT_MAX_CACHED_TERMS = 300_000

# 용어 하나가 가질 수 있는 최대 단어 수. 이보다 긴 항목은 "용어"가 아니라 문장/조항으로
# 보고 1단계에서 제외한다(2단계 벡터 검색이 담당). 첫 토큰 인덱스 덕분에 성능 문제는
# 없지만, 지나치게 긴 항목은 어차피 정확 매칭될 확률이 낮고 오탐만 늘린다.
_MAX_TERM_WORDS = 6


@dataclass(frozen=True, slots=True)
class GlossaryTerm:
    term_source: str
    term_target: str
    domain: str = ""


# 영어 단어를 단수/기본형에 가깝게 되돌리는 간단한 규칙. 완벽한 표제어 추출(lemmatization)은
# 아니지만 용어사전 매칭 목적으로는 실용적인 수준. 순서가 중요하다(구체적인 패턴 먼저).
_EN_SUFFIX_RULES: list[tuple[str, str]] = [
    ("ies", "y"),    # categories -> category
    ("ves", "f"),    # knives -> knife
    ("xes", "x"),    # boxes -> box
    ("ches", "ch"),  # matches -> match
    ("shes", "sh"),  # dishes -> dish
    ("s", ""),       # invoices -> invoice (가장 일반적인 케이스, 마지막에 체크)
]

_TOKEN_RE = re.compile(r"[A-Za-z]+|[가-힣]+", re.UNICODE)
_ASCII_WORD_RE = re.compile(r"[A-Za-z]+")


def _normalize_en(word: str) -> str:
    """영어 단어를 규칙 기반으로 단수/기본형에 가깝게 정규화한다.

    한국어 토큰은 소문자화만 하고 그대로 통과시킨다(조사 분리는 별도 형태소 분석기가
    필요한 영역이며, 이 모듈의 책임 범위 밖이다).
    """
    if not _ASCII_WORD_RE.fullmatch(word):
        return word.lower()
    w = word.lower()
    for suf, repl in _EN_SUFFIX_RULES:
        # 과교정 방지: 규칙 적용 후 결과가 너무 짧아지면(2자 미만) 적용하지 않는다.
        if w.endswith(suf) and len(w) - len(suf) + len(repl) >= 2:
            return w[: -len(suf)] + repl
    return w


# target_lang -> { 정규화된 첫 단어: [(정규화된 전체 단어 튜플, GlossaryTerm), ...] }
# 각 리스트는 단어 수 내림차순으로 정렬해두어, 같은 첫 단어를 공유하는 후보 중
# 더 긴 용어("invoice number")가 짧은 용어("invoice")보다 먼저 매칭되게 한다.
_INDEX: dict[str, dict[str, list[tuple[tuple[str, ...], GlossaryTerm]]]] = {}
_DISABLED_LANGS: set[str] = set()


def load_terms(
    target_lang: str,
    terms: list[GlossaryTerm],
    *,
    max_cached_terms: int = _DEFAULT_MAX_CACHED_TERMS,
) -> bool:
    """용어사전을 첫 토큰 역색인 형태로 메모리에 캐시한다.

    Weaviate에서 주기적으로 전체 용어를 긁어와 이 함수로 갱신하는 방식을 전제로 한다
    (매 번역 요청마다 호출하지 않음).

    Args:
        target_lang: 이 용어 목록이 속한 번역 대상 언어 코드.
        terms: 용어 목록. term_source가 비어 있거나 _MAX_TERM_WORDS를 넘는 항목은 제외한다.
        max_cached_terms: 캐시 상한. 초과하면 캐시하지 않고 False를 반환한다.

    Returns:
        캐시 성공 여부. False면 이 언어의 1단계 매칭이 비활성화되며,
        해당 언어는 2단계(벡터 검색)만으로 동작한다.
    """
    if len(terms) > max_cached_terms:
        _INDEX.pop(target_lang, None)
        _DISABLED_LANGS.add(target_lang)
        log_warning(
            f"[GLOSSARY] 용어 수가 캐시 상한을 초과해 1단계(정확 매칭) 비활성화: "
            f"target_lang={target_lang} item_count={len(terms)} limit={max_cached_terms} "
            f"-> 2단계(벡터 검색)만 사용"
        )
        return False

    index: dict[str, list[tuple[tuple[str, ...], GlossaryTerm]]] = {}
    skipped_long = 0
    for t in terms:
        if not t.term_source or not t.term_source.strip():
            continue
        words = t.term_source.split()
        if len(words) > _MAX_TERM_WORDS:
            skipped_long += 1
            continue
        normalized = tuple(_normalize_en(w) for w in words)
        index.setdefault(normalized[0], []).append((normalized, t))

    # 같은 첫 단어 안에서 긴 용어를 먼저 검사하도록 정렬 (최장 일치 우선)
    for bucket in index.values():
        bucket.sort(key=lambda item: len(item[0]), reverse=True)

    _INDEX[target_lang] = index
    _DISABLED_LANGS.discard(target_lang)
    log_info(
        f"[GLOSSARY] 1단계 캐시 구성 완료: target_lang={target_lang} "
        f"item_count={len(terms)} first_token_keys={len(index)} skipped_long={skipped_long}"
    )
    return True


def has_terms(target_lang: str) -> bool:
    return bool(_INDEX.get(target_lang))


def is_disabled(target_lang: str) -> bool:
    """상한 초과로 1단계가 비활성화된 언어인지 여부 (호출부 로깅/판단용)."""
    return target_lang in _DISABLED_LANGS


def clear_terms(target_lang: str | None = None) -> None:
    """캐시 해제. target_lang이 None이면 전체를 비운다 (테스트/재적재용)."""
    if target_lang is None:
        _INDEX.clear()
        _DISABLED_LANGS.clear()
    else:
        _INDEX.pop(target_lang, None)
        _DISABLED_LANGS.discard(target_lang)


def exact_match(text: str, target_lang: str) -> tuple[list[GlossaryTerm], str]:
    """활용형(복수형 등)까지 정규화해서 사전과 매칭한다.

    첫 토큰 역색인을 사용하므로, 사전에 등록된 용어의 최대 단어 수가 커져도
    스캔 비용이 늘지 않는다.

    Args:
        text: 검색 대상 원문(문장 또는 배치 전체를 이어붙인 텍스트).
        target_lang: 번역 대상 언어 코드. 이 언어로 load_terms()가 성공한 적 없으면
            바로 (빈 리스트, 원본 텍스트)를 반환한다.

    Returns:
        (매칭된 용어 목록, 매칭된 부분이 공백으로 치환된 나머지 텍스트).
        나머지 텍스트는 2단계(임베딩 기반 유사 매칭)의 후보 추출 입력으로 쓰인다.
    """
    index = _INDEX.get(target_lang)
    if not index or not text:
        return [], text

    tokens = [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]
    if not tokens:
        return [], text

    normalized_tokens = [_normalize_en(tok[0]) for tok in tokens]

    found: list[GlossaryTerm] = []
    seen: set[str] = set()
    consumed_spans: list[tuple[int, int]] = []

    i = 0
    n_tokens = len(tokens)
    while i < n_tokens:
        bucket = index.get(normalized_tokens[i])
        if not bucket:
            i += 1
            continue

        matched_len = 0
        for normalized_words, term in bucket:  # 긴 후보부터 (최장 일치 우선)
            span_len = len(normalized_words)
            if i + span_len > n_tokens:
                continue
            if tuple(normalized_tokens[i: i + span_len]) != normalized_words:
                continue
            if term.term_source not in seen:
                seen.add(term.term_source)
                found.append(term)
            consumed_spans.append((tokens[i][1], tokens[i + span_len - 1][2]))
            matched_len = span_len
            break

        # 매칭된 구간은 건너뛴다 -> 같은 토큰이 중복 소비되지 않고, 전체가 O(토큰 수)로 유지된다.
        i += matched_len if matched_len else 1

    remainder = text
    for start, end in sorted(consumed_spans, reverse=True):
        remainder = remainder[:start] + " " + remainder[end:]

    return found, remainder
