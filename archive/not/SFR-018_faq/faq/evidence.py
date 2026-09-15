"""근거 대조 — LLM 이 준 `evidence` 가 실제로 문서에 있는지 코드가 확인한다.

## 왜 필요한가

요구사항 §2 는 "생성된 FAQ 는 반드시 문서의 어떤 내용에서 추출된 것인지 명시"를
요구한다. 프롬프트로 "원문을 그대로 옮겨라"라고 지시할 수는 있지만 **지시는 보장이
아니다.** 검증 없이 표시만 하면 근거란이 장식이 되고, 지어낸 답변에 그럴듯한
출처가 붙어 오히려 더 위험해진다.

루트 `README.md` 018 지표 4절이 이 검사를 "1차 스크리닝(n-gram 중복·자카드)"으로
정의하고 있다. 여기 구현이 그 운영 쪽 짝이다 — 평가와 운영이 같은 판정을 쓴다.

## 판정 방식 (결정적)

1. 정규화: 공백 접기, 마크다운 강조/표 파이프/HTML 태그 제거, 대소문자 접기.
   전처리기 산출물과 hwpx 파서 산출물이 같은 문장을 다르게 꾸미기 때문이다
   (`**중요**` vs `중요`).
2. 완전 포함이면 통과 (대부분의 정상 케이스).
3. 아니면 **문자 3-gram 자카드**로 부분 일치를 본다. 임계값 이상이면 통과.
   LLM 이 앞뒤를 한두 글자 더 붙이거나 조사를 흘리는 정도는 근거로 인정한다.
   자카드를 쓰는 이유는 길이 차이에 견고해서다 — 짧은 근거 문장이 긴 문서에
   포함될 때 단순 중복률은 항상 낮게 나온다. 그래서 **근거 쪽을 분모로** 본다
   (근거의 3-gram 중 몇 %가 문서에 있는가).

## 통과 못하면

기본값은 **기각**이다(`FAQ_EVIDENCE_REJECT=1`). 근거를 확인할 수 없는 항목은
"문서에서 뽑았다"는 계약을 못 지킨다. 기각 건수는 응답·로그에 노출한다 —
조용히 버리면 왜 3개만 나왔는지 알 수 없다.
"""

import re
from dataclasses import dataclass

# 마크다운/HTML 꾸밈 제거 — 원문과 근거가 같은 문장인데 표기만 다른 경우를 흡수한다
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MD_DECOR_RE = re.compile(r"[*_`~#>|\\]+")
_WHITESPACE_RE = re.compile(r"\s+")

_NGRAM = 3


@dataclass(frozen=True)
class EvidenceVerdict:
    grounded: bool
    ratio: float   # 근거 3-gram 중 문서에 있는 비율 (완전 포함이면 1.0)


def normalize(text: str) -> str:
    """대조용 정규화. 문서 쪽과 근거 쪽에 **같은 함수**를 쓴다."""
    cleaned = _HTML_TAG_RE.sub(" ", text or "")
    cleaned = _MD_DECOR_RE.sub(" ", cleaned)
    return _WHITESPACE_RE.sub(" ", cleaned).strip().casefold()


def _ngrams(text: str) -> set:
    if len(text) < _NGRAM:
        return {text} if text else set()
    return {text[i: i + _NGRAM] for i in range(len(text) - _NGRAM + 1)}


class EvidenceChecker:
    """문서 하나에 대해 여러 근거를 대조한다.

    문서 정규화·n-gram 집합을 한 번만 만들어 재사용한다. 항목마다 다시 만들면
    FAQ 10개 × 수만 자 문서에서 같은 계산을 열 번 한다.
    """

    def __init__(self, document: str):
        self._document = normalize(document)
        self._document_ngrams = _ngrams(self._document)

    def check(self, evidence: str, min_ratio: float) -> EvidenceVerdict:
        normalized = normalize(evidence)
        if not normalized:
            return EvidenceVerdict(grounded=False, ratio=0.0)
        if normalized in self._document:
            return EvidenceVerdict(grounded=True, ratio=1.0)

        evidence_ngrams = _ngrams(normalized)
        if not evidence_ngrams:
            return EvidenceVerdict(grounded=False, ratio=0.0)
        overlap = len(evidence_ngrams & self._document_ngrams) / len(evidence_ngrams)
        return EvidenceVerdict(grounded=overlap >= min_ratio, ratio=round(overlap, 4))
