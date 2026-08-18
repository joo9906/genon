"""FAQ 근거 대조 — **정본(`faq/evidence.py`)을 직접 태운다** (2026-08-18).

이 파일이 생긴 경위가 이 테스트의 요점이다.

근거 대조 판정은 **두 벌**이었다 — FAQ 코드서빙 `faq/evidence.py`(운영이 실제로 쓰는
것)와 MCP `genon_text_guard.evidence_check`(호출부 0건). 그런데 **점검은 MCP 사본만
태우고 있었다.** 즉 운영이 쓰는 판정은 한 번도 검증된 적이 없고, 아무도 안 부르는
사본만 검증되고 있었다.

2026-08-18 에 그 사본을 걷어내면서 점검을 이쪽으로 옮겼다. 사본을 지우고 테스트도 같이
지웠다면 **근거 대조 규칙을 보는 점검이 0건이 됐을 것**이다 — 지우는 김에 커버리지가
조용히 사라지는, 정리 작업에서 제일 흔한 실패다.

`faq/evidence.py` 는 LLM 이 "근거" 라며 내놓은 문장이 원본에 실제로 있는지 대조한다.
**검증 없이 표시하면 지어낸 답변에 그럴듯한 출처가 붙어 더 위험하다.**
"""

import unittest

from . import onprem_path

onprem_path.install(onprem_path.FAQ_UNIT)

from faq.evidence import EvidenceChecker, normalize  # noqa: E402


_DOC = "본 사업은 2026년에 완료하였다. 예산은 1,200만원이 배정되었다."


class EvidenceCheckerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = EvidenceChecker(_DOC)

    def test_verbatim_evidence_is_grounded(self):
        """원문에 그대로 있는 문장은 1.0 이다 (완전 포함 지름길)."""
        verdict = self.checker.check("예산은 1,200만원이 배정되었다.", 0.8)
        self.assertTrue(verdict.grounded)
        self.assertEqual(verdict.ratio, 1.0)

    def test_fabricated_evidence_is_rejected(self):
        """문서에 없는 수치를 지어내면 기각된다 — 이 판정이 이 모듈의 존재 이유다."""
        verdict = self.checker.check("예산은 50억원으로 증액되었다.", 0.8)
        self.assertFalse(verdict.grounded)

    def test_markdown_decoration_is_absorbed(self):
        """표기만 다른 같은 문장을 기각하지 않는다 (꾸밈 제거 후 대조)."""
        verdict = self.checker.check("**예산은 1,200만원이 배정되었다.**", 0.8)
        self.assertTrue(verdict.grounded)

    def test_empty_evidence_is_not_grounded(self):
        """빈 근거를 통과시키면 '근거 없음' 이 '근거 있음' 으로 집계된다."""
        self.assertFalse(self.checker.check("", 0.8).grounded)

    def test_min_ratio_is_honored(self):
        """문턱이 판정을 실제로 가르는가 — 같은 입력에 기준만 바꿔 본다.

        부분 일치 문장 하나로 양쪽을 다 본다. 문턱을 무시하고 있으면 두 판정이 같아진다.
        """
        partial = "본 사업은 2026년에 완료하였고 예산은 전액 반납되었다."
        loose = self.checker.check(partial, 0.1)
        strict = self.checker.check(partial, 0.99)
        self.assertTrue(loose.grounded)
        self.assertFalse(strict.grounded)
        self.assertEqual(loose.ratio, strict.ratio)   # 비율은 같고 기준만 다르다

    def test_shuffled_words_are_not_evidence(self):
        """문서에 있는 **단어만 그러모은** 문장은 근거가 아니다.

        이 판정이 n-gram 크기가 하는 일의 전부다 — 근거는 "그 문장이 문서에 있었나"
        이지 "그 글자들이 문서에 있었나" 가 아니다. 1-gram 이면 이 입력의 겹침이
        **1.0** 이라 그대로 통과한다(2-gram 도 0.73 이다).

        앞의 판정들만으로는 이걸 못 잡는다 — `_NGRAM` 을 1 로 바꿔도 완전 포함은
        1.0 이고 지어낸 문장은 여전히 기각돼서 전부 통과한다. 실제로 확인하고 넣었다.
        """
        verdict = self.checker.check("완료 예산 사업 배정 2026", 0.8)
        self.assertFalse(verdict.grounded)
        self.assertLess(verdict.ratio, 0.5)

    def test_normalize_strips_html_and_whitespace(self):
        self.assertEqual(normalize("<b>본  사업</b>\n완료"), "본 사업 완료")


if __name__ == "__main__":
    unittest.main()
