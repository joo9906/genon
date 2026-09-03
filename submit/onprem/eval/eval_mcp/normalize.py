"""텍스트 정규화 — 결정적 채점의 전제.

README 평가 원칙: `Text` 도구는 "정규화 후" exact/contains/정규식으로 잰다.
정규화 규칙이 지표마다 다르면 점수를 비교할 수 없으므로 여기 한 곳에서만 정의한다.

기본 정규화(`normalize`)는 표기 차이만 없앤다 — 유니코드 NFKC(전각/호환문자 통일),
공백 축약, 앞뒤 공백 제거. 의미를 바꿀 수 있는 처리(구두점 제거, 소문자화)는
호출부가 명시적으로 켠다.
"""

import re
import unicodedata

_WS_RE = re.compile(r"\s+")
# **우리가 붙인 표시용 태그** — 원문 구조가 아니다 (2026-09-02).
# 글다듬이·번역의 최종 텍스트(`polished_text`·`translated_text`·`original_text`)는
# 바뀐 낱말·사전 용어에 `<mark>` 가 입혀진 **사본**이고, 정본은 payload 에서 빠졌다
# (2026-08-28 — 내려받기가 링크가 되며 파일로만 남는다). 그래서 평가에 들어오는 것은
# 사실상 사본이다.
#
# 벗기지 않으면 종결어미가 `…하였습니다</mark>` 로 끝나 `ending_consistency` ·
# `tone_rule_check` 의 어미 판정이 전부 `other` 로 떨어진다 — **불합격이 아니라
# `measurable: False`(미측정)로 조용히 빠지는** 쪽이라 더 나쁘다.
#
# **`<mark>` 만** 벗긴다. `<table>` 같은 태그는 원문에서 온 구조라 지우면 구조 지문이
# 무너진다 (FAQ txt 가 "그 기호를 누가 넣었나" 로 가르는 것과 같은 기준).
_DISPLAY_TAG_RE = re.compile(r"</?mark\s*>", re.IGNORECASE)
# 한국어 문서에 실제로 섞여 오는 구두점 + 마크다운 강조 기호
_PUNCT_RE = re.compile(r"[~!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?·…“”‘’「」『』〈〉]")
# 문장 종결 후보: 종결어미/마침표 뒤 공백 또는 줄바꿈
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|(?<=다\.)\s*|(?<=요\.)\s*|\n+")


def strip_display_tags(text: str) -> str:
    """표시용 `<mark>` 만 벗긴다 (근거는 `_DISPLAY_TAG_RE` 주석).

    `normalize` 안에 넣지 않는 이유: 구조 지문(`structure_metrics.fingerprint`)은
    정규화를 거치지 않고 원문 그대로를 읽는데, 태그 제거는 **입력 계약** 층에서
    한 번만 일어나야 한다. 두 층에서 벗기면 어느 쪽이 정본인지 알 수 없어진다.
    """
    return _DISPLAY_TAG_RE.sub("", text or "")


def normalize(text: str, *, drop_punct: bool = False, lower: bool = False) -> str:
    """비교용 표준형으로 바꾼다."""
    result = unicodedata.normalize("NFKC", text or "")
    if drop_punct:
        result = _PUNCT_RE.sub(" ", result)
    if lower:
        result = result.lower()
    return _WS_RE.sub(" ", result).strip()


def split_sentences(text: str) -> list[str]:
    """한국어 문서를 문장 단위로 나눈다.

    형태소 분석기 없이 종결부호/종결어미 뒤에서만 자르는 보수적 규칙이다 —
    문장 단위 지표(근거성 스크리닝, 어미 일관성)는 경계가 한두 개 어긋나도
    집계값이 크게 흔들리지 않으므로 외부 모델 의존을 만들지 않는다.
    """
    pieces = _SENT_SPLIT_RE.split(unicodedata.normalize("NFKC", text or ""))
    return [p.strip() for p in pieces if p and p.strip()]


def char_ngrams(text: str, size: int) -> list[str]:
    """문자 n-gram (chrF·중복률용). 공백은 제거하고 센다."""
    body = _WS_RE.sub("", normalize(text))
    if len(body) < size:
        return [body] if body else []
    return [body[i : i + size] for i in range(len(body) - size + 1)]


def word_ngrams(text: str, size: int) -> list[str]:
    """어절 n-gram (근거성 어휘 중복률용)."""
    words = normalize(text, drop_punct=True, lower=True).split()
    if len(words) < size:
        return [" ".join(words)] if words else []
    return [" ".join(words[i : i + size]) for i in range(len(words) - size + 1)]
