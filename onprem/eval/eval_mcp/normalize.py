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
# 한국어 문서에 실제로 섞여 오는 구두점 + 마크다운 강조 기호
_PUNCT_RE = re.compile(r"[~!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?·…“”‘’「」『』〈〉]")
# 문장 종결 후보: 종결어미/마침표 뒤 공백 또는 줄바꿈
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|(?<=다\.)\s*|(?<=요\.)\s*|\n+")


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
