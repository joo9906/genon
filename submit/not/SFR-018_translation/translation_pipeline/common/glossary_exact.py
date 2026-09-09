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

# ── 한국어 조사 절단 (2026-08-28) ──────────────────────────────────────────
#
# ## 왜 필요한가 — 하이라이트보다 앞단이 깨져 있었다
#
# 토큰이 `[가-힣]+` 라 `가맹점을` 이 한 덩어리다. 그래서 사전의 `가맹점` 과 매칭되지
# 않았고, 그 실패가 **세 자리에서 서로 다른 얼굴로** 나타났다:
#
# | 방향 | 어디서 깨지나 | 증상 |
# |---|---|---|
# | ko→en | `match_occurrences` 가 0건 | **그 용어가 프롬프트에 실리지 않는다** — LLM 은
# |       |                            | "가맹점 → merchant" 를 들은 적이 없다.
# |       |                            | 준수율은 `matched_count=0` 이라 **1.0** 이다 |
# | en→ko | `contains_phrase` 가 False | 번역이 `신용회복위원회를` 로 제대로 옮겼는데
# |       |                            | **준수율 0.0** 이고 양쪽 하이라이트가 안 붙는다 |
#
# 즉 표시 문제가 아니라 **프롬프트·지표·표시가 함께 틀리는** 문제였다.
#
# ## 형태소 분석기는 필요 없다
#
# 이 파일 머리말은 조사 분리를 "형태소 분석기가 필요한 영역" 이라고 적어 두었는데,
# 여기서 필요한 것은 그만큼이 아니다. **사전 용어는 대부분 명사이고 그 뒤에 붙는
# 조사는 닫힌 목록**이라, 영어 `_EN_SUFFIX_RULES` 와 같은 구조로 끝난다.
#
# ## 색인이 아니라 **조회할 때** 뗀다
#
# 색인 키에 절단을 걸면 안 된다 — 사전 표제어는 이미 기본형이고, `신용도` 같은 항목이
# `신용` 으로 굳어 **원래 용어가 사라진다.** 문서 쪽 토큰만, 그것도 **정확히 일치하는
# 것을 먼저 찾아보고 없을 때만** 뗀다.
#
# ## 남는 한계 (문서화)
#
# 절단 결과가 2자 이상일 때만 적용하므로 `추가`→`추` 같은 과절단은 막힌다. 다만
# **`신용도` 처럼 3자 이상이면서 조사 글자로 끝나는 용어**는 사전에 `신용` 만 있을 때
# 그쪽으로 걸린다. 사전에 `신용도` 가 함께 있으면 정확 일치가 먼저 이기므로 실무에서
# 문제가 되는 경우는 좁다.
_KO_PARTICLES: tuple = (
    # 긴 것부터 — `으로` 를 `로` 보다 먼저 봐야 `으` 가 남지 않는다
    "에게서", "으로는", "에서는", "이라고", "라고는",
    "에게", "에서", "으로", "이라", "라고", "부터", "까지", "마다", "조차",
    "처럼", "만큼", "밖에", "이나", "이란", "로서", "로써", "한테", "보다", "대로",
    "께서", "이며", "이고",
    "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "만",
    "로", "랑", "야", "아",
)
_HANGUL_WORD_RE = re.compile(r"[가-힣]+")


def strip_ko_particle(word: str) -> str:
    """한글 토큰 뒤에 붙은 조사를 뗀다. 뗄 수 없으면 **원래 값 그대로** 돌려준다.

    호출부는 "정확히 일치하는 것을 먼저 찾고, 없을 때만" 이 값을 쓴다 (머리말 참고).
    """
    if not _HANGUL_WORD_RE.fullmatch(word):
        return word
    for particle in _KO_PARTICLES:
        # 과절단 방지: 떼고 나서 2자 미만이면 적용하지 않는다 (`추가` → `추` 금지).
        if word.endswith(particle) and len(word) - len(particle) >= 2:
            return word[: -len(particle)]
    return word


def _token_eq(text_token: str, term_token: str) -> bool:
    """문서 토큰이 사전 토큰과 같은가 — **조사가 붙은 형태도 같은 것으로 본다.**

    방향이 한쪽이다: 조사는 **문서 쪽에만** 붙는다. 사전 표제어에서 떼면 안 된다.
    """
    return text_token == term_token or strip_ko_particle(text_token) == term_token

# target_lang -> { 정규화된 첫 단어: [(정규화된 전체 단어 튜플, GlossaryTerm), ...] }
# 각 리스트는 단어 수 내림차순 — 같은 첫 단어를 공유하는 후보 중 더 긴 용어
# ("invoice number")가 짧은 용어("invoice")보다 먼저 매칭된다.
_INDEX: dict = {}
_DISABLED_LANGS: set = set()


def _normalize_en(word: str) -> str:
    """영어 단어를 규칙 기반으로 단수/기본형에 가깝게 정규화한다.

    영어가 아닌 토큰은 소문자화만 한다. **한국어 조사는 여기서 떼지 않는다** —
    조회 시점에 `strip_ko_particle` 로 뗀다(그 함수 머리말 참고). 색인 키에 절단을
    걸면 사전 표제어가 함께 깎여 `신용도` 같은 항목이 사라진다.
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
    # 조사가 붙은 형태도 "썼다" 로 본다 (2026-08-28) — `신용회복위원회를` 로 옮긴
    # 번역이 준수율 0.0 을 받고 있었다. 방향은 한쪽이다: 조사는 문서 쪽에만 붙는다.
    return any(
        all(
            _token_eq(text_tokens[start + offset], phrase_tokens[offset])
            for offset in range(span)
        )
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
        # `contains_phrase` 와 **같은 규칙**이어야 한다 — 여기만 다르면 "썼다" 인데
        # 위치는 못 찾는(또는 그 반대인) 상태가 생긴다.
        if all(
            _token_eq(normalized[start_index + offset], phrase_tokens[offset])
            for offset in range(span)
        ):
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
    # 조사가 붙은 형태로도 한 번 더 찾아본다 (2026-08-28). 정확 일치가 먼저다 —
    # 사전에 `신용도` 와 `신용` 이 함께 있으면 앞엣것이 이겨야 한다.
    stripped_tokens = [strip_ko_particle(token) for token in normalized_tokens]

    occurrences: list = []
    position = 0
    token_count = len(tokens)
    while position < token_count:
        bucket = index.get(normalized_tokens[position])
        if not bucket and stripped_tokens[position] != normalized_tokens[position]:
            bucket = index.get(stripped_tokens[position])
        if not bucket:
            position += 1
            continue

        matched_len = 0
        for normalized_words, term in bucket:  # 긴 후보부터 (최장 일치 우선)
            span_len = len(normalized_words)
            if position + span_len > token_count:
                continue
            # 여러 낱말 용어는 **낱말마다** 조사 폴백을 본다. 조사는 보통 마지막
            # 낱말에만 붙지만("가맹점 정산을") 중간에 붙는 형태도 있다.
            if not all(
                _token_eq(normalized_tokens[position + offset], normalized_words[offset])
                or _token_eq(stripped_tokens[position + offset], normalized_words[offset])
                for offset in range(span_len)
            ):
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
