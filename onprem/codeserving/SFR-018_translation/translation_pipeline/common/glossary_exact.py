"""용어사전 정확 매칭 — 임베딩·벡터DB 없이 문자열/토큰 비교만 한다.

`SFR-018/genos-glossary` 실험의 **1단계만** 병합한 것이다 (CLAUDE.md 결정, 2026-08-05).
2단계(`glossary.py`, Weaviate + 임베딩 게이트웨이)는 폐쇄망 임베딩·벡터DB 가용성이
확인되지 않아 보류했다. **여기에는 2단계 폴백이 없다** — 원본 실험 코드의 주석은
"1단계가 꺼지면 2단계가 받는다"고 적혀 있었지만, 이 배포 단위에서는 1단계가 꺼지면
용어사전이 아예 적용되지 않는다. 그래서 비활성화 사실을 호출부·응답까지 올린다
(`is_disabled`) — 조용히 꺼지면 사용자는 용어사전이 적용된 줄 안다.

## 설계 의도

- 용어사전 매칭은 "의미가 비슷한 것"보다 "정확히 그 용어인지"가 훨씬 중요하다.
  명확한 케이스는 문자열 매칭이 더 정확하고 빠르며, 실패 지점(벡터DB·임베딩 API)이 없다.
- 영어 활용형(-s/-es/-ies)을 반영하지 않으면 사전에 "invoice"만 있을 때 원문의
  "invoices"를 못 잡으므로, 토큰을 정규화한 뒤 비교한다.
- 단어 경계 없이 raw substring 으로 찾으면 "cat"이 "category" 안에서 걸리는 오탐이
  생기므로 반드시 토큰 단위로 비교한다.

## 성능 설계 (원본 실험의 실측 근거 — 바꾸지 말 것)

n-gram 슬라이딩(`range(max_words, 0, -1)`)으로 후보를 찾으면, 사전에 긴 복합 용어가
단 한 건이라도 섞이는 순간 모든 배치가 그 단어 수만큼 반복 스캔된다. 실측 기준
8단어 용어 1건 때문에 배치당 1.6ms → 33ms(20배)로 악화되고, 이 비용은 사전 크기와
무관하다. 실무 용어사전에는 긴 조항성 항목이 반드시 섞여 들어온다.
그래서 **"정규화된 첫 단어 → 그 단어로 시작하는 용어들" 역색인**을 만들고, 원문 토큰을
왼쪽에서 한 번만 훑는다. 비용이 O(토큰 수 × 위치별 후보 수)라 사전의 최대 단어 수에
영향받지 않는다.

## 메모리

실측 10만 건 약 31MB, 50만 건 약 150MB. K8s Pod 에서 OOMKill 이 나면 서빙 전체가
죽으므로 `max_cached_terms` 상한을 두고 초과 시 캐시를 포기한다.
"""

import re
from dataclasses import dataclass

from translation_pipeline.common.logging_utils import log_info, log_warning

# 캐시 상한. 초과하면 그 언어의 용어사전 적용을 비활성화한다.
_DEFAULT_MAX_CACHED_TERMS = 300_000

# 용어 하나가 가질 수 있는 최대 단어 수. 이보다 긴 항목은 "용어"가 아니라 문장/조항으로
# 보고 제외한다 — 정확 매칭될 확률이 낮고 오탐만 늘린다.
_MAX_TERM_WORDS = 6


@dataclass(frozen=True, slots=True)
class GlossaryTerm:
    term_source: str
    term_target: str
    domain: str = ""


# 영어 단어를 단수/기본형에 가깝게 되돌리는 규칙. 완전한 표제어 추출은 아니지만
# 용어사전 매칭 목적에는 실용적이다. 순서가 중요하다(구체적인 패턴 먼저).
_EN_SUFFIX_RULES: list = [
    ("ies", "y"),    # categories -> category
    ("ves", "f"),    # knives -> knife
    ("xes", "x"),    # boxes -> box
    ("ches", "ch"),  # matches -> match
    ("shes", "sh"),  # dishes -> dish
    ("s", ""),       # invoices -> invoice (가장 일반적 — 마지막에 검사)
]

# 지원 6개 언어의 글자를 토큰으로 잡는다. 원본 실험은 영어·한국어만 다뤘지만
# 이 배포 단위는 중국어·태국어·베트남어·러시아어 사전도 받는다.
#   - 한글 / 라틴(베트남어 성조 포함) / 키릴 / 한자 / 태국 문자
#   - 태국어·중국어는 띄어쓰기가 없어 토큰이 길게 잡힌다 → 그 언어 사전은
#     사실상 완전 일치만 걸린다 (한계로 문서화).
_TOKEN_RE = re.compile(
    r"[A-Za-zÀ-ɏ]+"      # 라틴 + 확장(베트남어)
    r"|[가-힣]+"            # 한글
    r"|[Ѐ-ԯ]+"            # 키릴(러시아어)
    r"|[一-鿿]+"            # 한자(중국어)
    r"|[฀-๿]+",           # 태국 문자
    re.UNICODE,
)
_ASCII_WORD_RE = re.compile(r"[A-Za-z]+")

# target_lang -> { 정규화된 첫 단어: [(정규화된 전체 단어 튜플, GlossaryTerm), ...] }
# 각 리스트는 단어 수 내림차순 — 같은 첫 단어를 공유하는 후보 중 더 긴 용어
# ("invoice number")가 짧은 용어("invoice")보다 먼저 매칭된다.
_INDEX: dict = {}
_DISABLED_LANGS: set = set()


def _normalize_en(word: str) -> str:
    """영어 단어를 규칙 기반으로 단수/기본형에 가깝게 정규화한다.

    영어가 아닌 토큰은 소문자화만 하고 통과시킨다 (한국어 조사 분리는 형태소 분석기가
    필요한 영역이며 이 모듈의 책임 범위 밖이다).
    """
    if not _ASCII_WORD_RE.fullmatch(word):
        return word.lower()
    lowered = word.lower()
    for suffix, replacement in _EN_SUFFIX_RULES:
        # 과교정 방지: 규칙 적용 후 2자 미만이 되면 적용하지 않는다.
        if lowered.endswith(suffix) and len(lowered) - len(suffix) + len(replacement) >= 2:
            return lowered[: -len(suffix)] + replacement
    return lowered


def load_terms(
    target_lang: str,
    terms: list,
    *,
    max_cached_terms: int = _DEFAULT_MAX_CACHED_TERMS,
) -> bool:
    """용어사전을 첫 토큰 역색인으로 메모리에 캐시한다.

    매 번역 요청마다 부르는 함수가 아니다 — 기동 시 1회, 그리고 관리자가
    `POST /glossary/reload` 를 호출할 때만 부른다.

    Returns:
        캐시 성공 여부. False 면 그 언어는 용어사전 없이 번역된다.
    """
    if len(terms) > max_cached_terms:
        _INDEX.pop(target_lang, None)
        _DISABLED_LANGS.add(target_lang)
        # 3.8절: 용어·언어 값은 메시지에 끼워 넣지 않고 허용 필드로만 남긴다
        log_warning(
            "용어 수가 캐시 상한을 초과해 용어사전 적용을 비활성화",
            event="glossary_disabled_over_limit",
            resource_id=f"glossary:{target_lang}",
            item_count=len(terms),
            status="disabled",
        )
        return False

    index: dict = {}
    skipped_long = 0
    for term in terms:
        if not term.term_source or not term.term_source.strip():
            continue
        words = term.term_source.split()
        if len(words) > _MAX_TERM_WORDS:
            skipped_long += 1
            continue
        normalized = tuple(_normalize_en(word) for word in words)
        index.setdefault(normalized[0], []).append((normalized, term))

    # 같은 첫 단어 안에서 긴 용어를 먼저 검사 (최장 일치 우선)
    for bucket in index.values():
        bucket.sort(key=lambda item: len(item[0]), reverse=True)

    _INDEX[target_lang] = index
    _DISABLED_LANGS.discard(target_lang)
    log_info(
        "용어사전 색인 구성 완료",
        event="glossary_index_built",
        resource_id=f"glossary:{target_lang}",
        item_count=len(terms),
        # 길어서 제외된 항목이 있으면 조용히 넘기지 않는다
        status=f"skipped_long={skipped_long}",
    )
    return True


def is_disabled(target_lang: str) -> bool:
    """상한 초과로 비활성화된 언어인지 (응답·로그에 노출하기 위한 조회)."""
    return target_lang in _DISABLED_LANGS


def term_count(target_lang: str) -> int:
    """색인에 올라간 용어 수 (`GET /glossary` 상태 표시용)."""
    return sum(len(bucket) for bucket in _INDEX.get(target_lang, {}).values())


def clear_terms(target_lang: str = None) -> None:
    """캐시 해제. target_lang 이 None 이면 전체를 비운다 (재적재용)."""
    if target_lang is None:
        _INDEX.clear()
        _DISABLED_LANGS.clear()
    else:
        _INDEX.pop(target_lang, None)
        _DISABLED_LANGS.discard(target_lang)


def contains_phrase(text: str, phrase: str) -> bool:
    """`phrase` 가 `text` 안에 **토큰 단위로** 들어 있는가.

    준수 여부 판정(`glossary_report.py`)이 쓴다. 단순 substring 대신 토큰 비교를 쓰는
    이유는 매칭과 같다 — "cat"이 "category" 안에서 걸리는 오탐을 막는다.
    정규화(`_normalize_en`)를 거치므로 지정 용어가 문장에 맞게 활용돼도
    (`invoice` → `invoices`) 준수로 본다. 사전이 요구하는 것은 "그 용어를 썼는가"이지
    "글자가 똑같은가"가 아니다.
    """
    phrase_tokens = tuple(
        _normalize_en(match.group(0)) for match in _TOKEN_RE.finditer(phrase or "")
    )
    if not phrase_tokens:
        return False
    text_tokens = [_normalize_en(match.group(0)) for match in _TOKEN_RE.finditer(text or "")]
    span = len(phrase_tokens)
    return any(
        tuple(text_tokens[start: start + span]) == phrase_tokens
        for start in range(len(text_tokens) - span + 1)
    )


def phrase_positions(text: str, phrase: str) -> list:
    """`phrase` 가 `text` 안에 나온 **문자 위치** 목록 — `[(start, end), ...]`.

    `contains_phrase` 의 위치 반환판이다(2026-08-14). 판정 규칙이 갈리지 않게 **같은
    토큰화·같은 정규화**를 쓴다 — 여기만 substring 검색으로 바꾸면 `contains_phrase` 는
    "썼다" 인데 위치는 못 찾는(또는 그 반대인) 상태가 생긴다.

    ## 왜 필요한가

    번역문에서 사전 용어가 **어디에** 쓰였는지는 아무도 계산하지 않고 있었다.
    `hits[].spans` 는 **원문** 기준이라(그쪽은 `match_occurrences` 가 낸다) 번역문에
    하이라이트를 입힐 수 없었다.

    ## 활용형은 원래 표기 범위를 돌려준다

    정규화 덕분에 `invoice` 가 번역문의 `invoices` 에 걸린다(사전이 요구하는 것은 "그
    용어를 썼는가" 이지 "글자가 똑같은가" 가 아니다). 이때 돌려주는 구간은 **번역문에
    실제로 적힌 글자**(`invoices`)의 범위다 — 사전 표기를 씌우면 없는 글자를 가리킨다.
    """
    phrase_tokens = tuple(
        _normalize_en(match.group(0)) for match in _TOKEN_RE.finditer(phrase or "")
    )
    if not phrase_tokens or not text:
        return []

    tokens = [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]
    normalized = [_normalize_en(token[0]) for token in tokens]
    span = len(phrase_tokens)

    positions: list = []
    start_index = 0
    while start_index + span <= len(tokens):
        if tuple(normalized[start_index: start_index + span]) == phrase_tokens:
            positions.append((tokens[start_index][1], tokens[start_index + span - 1][2]))
            # 겹치는 매칭을 두 번 세지 않는다 — 하이라이트가 겹치면 태그가 꼬인다.
            start_index += span
            continue
        start_index += 1
    return positions


def match_occurrences(text: str, target_lang: str) -> list:
    """매칭을 **등장 단위로** 돌려준다 — `[(GlossaryTerm, start, end), ...]`.

    ## 왜 갈라 냈나 (2026-08-14)

    스캔 자체는 예전부터 토큰의 문자 위치(`tokens[i][1:3]`)를 알고 있었는데, `exact_match`
    가 그 값을 **`remainder` 를 만드는 데만 쓰고 버렸다.** 그래서 UI 하이라이트가
    "원문에서 이 단어를 찾아라" 는 문자열 검색으로 떨어졌고, 같은 단어가 여러 번 나오면
    **사전이 실제로 걸린 자리와 아닌 자리를 구분할 수 없었다.**

    위치를 여기서 내면 새로 계산할 것이 없다 — 이미 하던 일의 결과를 버리지 않을 뿐이다.

    반환 순서는 **텍스트 등장 순서**다(스캔이 왼쪽에서 오른쪽으로 간다). 하이라이트를
    앞에서부터 입히는 소비자가 다시 정렬할 필요가 없다.
    """
    index = _INDEX.get(target_lang)
    if not index or not text:
        return []

    tokens = [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]
    if not tokens:
        return []

    normalized_tokens = [_normalize_en(token[0]) for token in tokens]

    occurrences: list = []
    position = 0
    token_count = len(tokens)
    while position < token_count:
        bucket = index.get(normalized_tokens[position])
        if not bucket:
            position += 1
            continue

        matched_len = 0
        for normalized_words, term in bucket:  # 긴 후보부터 (최장 일치 우선)
            span_len = len(normalized_words)
            if position + span_len > token_count:
                continue
            if tuple(normalized_tokens[position: position + span_len]) != normalized_words:
                continue
            occurrences.append(
                (term, tokens[position][1], tokens[position + span_len - 1][2])
            )
            matched_len = span_len
            break

        # 매칭된 구간은 건너뛴다 → 같은 토큰이 중복 소비되지 않고 전체가 O(토큰 수)로 유지된다
        position += matched_len if matched_len else 1

    return occurrences


def exact_match(text: str, target_lang: str) -> tuple:
    """활용형(복수형 등)까지 정규화해 사전과 매칭한다.

    첫 토큰 역색인을 쓰므로 사전에 등록된 용어의 최대 단어 수가 커져도 스캔 비용이
    늘지 않는다.

    Returns:
        (매칭된 GlossaryTerm 목록, 매칭 구간이 공백으로 치환된 나머지 텍스트).
        용어 목록은 **용어 단위로 중복이 제거**돼 있다(프롬프트에 실을 목록이라 같은 용어를
        두 번 넣을 이유가 없다). 등장 위치가 필요하면 `match_occurrences` 를 쓴다.
        나머지 텍스트는 지금 쓰이지 않는다 — 2단계(임베딩 후보 추출)의 입력이었고,
        2단계를 병합할 때 그대로 쓰려고 계약을 유지한다.
    """
    occurrences = match_occurrences(text, target_lang)
    if not occurrences:
        return [], text

    found: list = []
    seen: set = set()
    for term, _start, _end in occurrences:
        if term.term_source not in seen:
            seen.add(term.term_source)
            found.append(term)

    remainder = text
    for _term, start, end in sorted(occurrences, key=lambda item: item[1], reverse=True):
        remainder = remainder[:start] + " " + remainder[end:]

    return found, remainder
