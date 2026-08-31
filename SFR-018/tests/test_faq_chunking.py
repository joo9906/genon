"""FAQ 는 **문서 전체**에서 뽑는다 — 앞부분만 보던 것을 고친 자리 (2026-08-29).

## 이 테스트가 지키는 것

그전에는 상한(`FAQ_MAX_CONTEXT_CHARS`)을 넘는 문서를 `source[:상한]` 으로 **자르고**
한 번만 LLM 에 보냈다. 잘린 뒷부분은 **FAQ 후보에서 통째로 빠졌고 기각 건수에도 잡히지
않았다** — LLM 이 본 적이 없으니 `ungrounded` 도 `duplicate` 도 아니다. 사내 규정집은
대부분 그 상한을 넘으므로 **긴 문서에서는 언제나 앞부분만** FAQ 가 됐다.

그 결함은 예외를 던지지 않고, 나온 FAQ 도 멀쩡해 보인다. **뒷부분 내용을 물었을 때
아무것도 안 나오는 것**으로만 드러난다. 그래서 여기서 보는 것은 "몇 개 나왔나" 가
아니라 **LLM 이 문서의 어느 부분을 봤나** 다.

## 두 층을 따로 본다

1. `chunking` — 자르는 규칙 자체 (무손실·제목 경계·배분).
2. `generate_faqs` — 그 규칙이 실제 생성 경로에서 쓰이는가 (가짜 LLM 을 꽂아 태운다).

1번만 있으면 모듈이 맞아도 호출부가 예전처럼 `[:상한]` 을 쓰는 상태를 통과시킨다.
"""

import asyncio
import json
import unittest

from . import onprem_path

onprem_path.install(onprem_path.FAQ_UNIT)

from faq import chunking, generator  # noqa: E402
from faq.config import Config  # noqa: E402
from faq.formatting import build_notice  # noqa: E402
from faq.llm import LlmResult  # noqa: E402


class SplitForContextTest(unittest.TestCase):
    def test_nothing_is_dropped(self):
        """조각을 이으면 원문의 **모든 줄**이 그대로 있다 — 이 모듈의 존재 이유다."""
        lines = [f"{index}번째 줄입니다." for index in range(60)]
        text = "\n".join(lines)
        chunks = chunking.split_for_context(text, 80)
        joined = "\n".join(chunks)
        for line in lines:
            self.assertIn(line, joined)

    def test_budget_is_honored(self):
        """조각이 예산을 넘지 않는다 — 넘으면 LLM 이 뒤를 잘라 버린다(우리는 못 본다)."""
        text = "\n".join(f"{index}번 항목" for index in range(100))
        for chunk in chunking.split_for_context(text, 50):
            self.assertLessEqual(len(chunk), 50)

    def test_heading_starts_a_new_chunk(self):
        """예산의 60% 를 넘긴 뒤 제목을 만나면 거기서 끊는다.

        조각이 절 단위로 떨어져야 그 안에서 뽑은 FAQ 가 한 주제로 묶인다.
        """
        text = "가나다라마바사아자차카타파하" * 4 + "\n## 두 번째 절\n내용입니다."
        chunks = chunking.split_for_context(text, 70)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(chunks[1].startswith("## 두 번째 절"))

    def test_overlong_line_is_split_not_dropped(self):
        """한 줄이 예산보다 길어도 버리지 않는다 (한 줄 HTML 표가 대표적)."""
        line = "가" * 250
        chunks = chunking.split_for_context(line, 100)
        self.assertEqual("".join(chunks), line)

    def test_empty_document_yields_no_chunk(self):
        self.assertEqual(chunking.split_for_context("   \n\n  ", 100), [])


class PlanQuotaTest(unittest.TestCase):
    """조각당 개수는 고정이고 **총량 상한이 몇 조각을 태울지** 정한다 (2026-08-31)."""

    def test_sum_never_exceeds_cap(self):
        """합이 총량 상한을 넘으면 LLM 예산 상한이 무의미해진다."""
        for chunk_count in range(1, 12):
            for per_chunk in range(1, 7):
                for cap in range(0, 32, 3):
                    quota = chunking.plan_quota(chunk_count, per_chunk, cap)
                    self.assertEqual(len(quota), chunk_count)
                    self.assertLessEqual(
                        sum(quota), cap, f"chunks={chunk_count} per={per_chunk} cap={cap}"
                    )

    def test_uses_whole_budget_when_document_is_long_enough(self):
        """예산을 남기지 않는다 — 남기면 사용자가 받을 수 있는 개수를 우리가 버린다."""
        for per_chunk, cap in ((5, 30), (3, 10), (4, 30), (7, 30)):
            chunk_count = 40  # 예산을 다 쓸 만큼 긴 문서
            self.assertEqual(
                sum(chunking.plan_quota(chunk_count, per_chunk, cap)),
                cap,
                f"per={per_chunk} cap={cap}",
            )

    def test_every_chunk_gets_the_full_per_chunk_share(self):
        """요구 확정: 구간당 5개 · 총량 30개 → **여섯 구간에서 5개씩**.

        총 개수를 조각 수로 나누던 시절에는 40조각 문서에서 조각당 0~1개였다.
        """
        quota = chunking.plan_quota(40, 5, 30)
        picked = [value for value in quota if value]
        self.assertEqual(picked, [5] * 6, f"quota={quota}")

    def test_short_document_is_unchanged(self):
        """조각이 하나면 예전과 같다 — 5개를 고르면 5개다 (회귀 위험이 큰 자리)."""
        self.assertEqual(chunking.plan_quota(1, 5, 30), [5])

    def test_remainder_goes_to_one_more_chunk(self):
        """상한이 구간당 개수로 나누어지지 않으면 마지막 한 구간이 나머지만 맡는다."""
        quota = chunking.plan_quota(10, 7, 30)
        self.assertEqual(sum(quota), 30)
        self.assertEqual(sorted(value for value in quota if value), [2, 7, 7, 7, 7])

    def test_burned_chunks_are_spread_not_front_loaded(self):
        """태울 조각은 **고르게 표집한다.**

        앞에서부터 채우면 문서를 잘라 쓰던 시절과 결과가 같아진다(앞부분만 FAQ 가
        된다) — 이 테스트가 그 회귀를 막는 유일한 자리다.
        """
        quota = chunking.plan_quota(24, 5, 15)
        picked = [index for index, value in enumerate(quota) if value]
        self.assertEqual(len(picked), 3)
        self.assertGreater(picked[0], 0, "첫 조각부터 고르면 앞부분 편중이다")
        self.assertGreaterEqual(picked[-1], 16, f"뒷부분을 안 태웠다: {picked}")
        gaps = [b - a for a, b in zip(picked, picked[1:])]
        self.assertTrue(all(gap >= 6 for gap in gaps), f"자리가 붙어 있다: {picked}")

    def test_zero_inputs_yield_no_call(self):
        self.assertEqual(chunking.plan_quota(3, 0, 30), [0, 0, 0])
        self.assertEqual(chunking.plan_quota(3, 5, 0), [0, 0, 0])
        self.assertEqual(chunking.plan_quota(0, 5, 30), [])


def _faq_json(question: str, evidence: str) -> str:
    return json.dumps(
        {"faqs": [{"question": question, "answer": "답변입니다.", "evidence": evidence}]},
        ensure_ascii=False,
    )


class _FakeLlm:
    """조각의 **첫 줄을 근거로** FAQ 한 건을 돌려주는 대역.

    근거가 조각마다 다르므로 **어느 조각이 실제로 LLM 에 갔는지**가 결과에 남는다.
    """

    def __init__(self, fail_after: int = -1):
        self.documents: list = []
        self.fail_after = fail_after

    async def __call__(self, system_prompt: str, user_prompt: str) -> LlmResult:
        self.documents.append(user_prompt)
        if 0 <= self.fail_after <= len(self.documents) - 1:
            return LlmResult(content="", error_type="APITimeoutError", is_transport_error=True)
        body = [line for line in user_prompt.splitlines() if line.strip()]
        # 문서 본문의 첫 줄 (프롬프트 머리말 "문서 내용:" 다음)
        evidence = body[1] if len(body) > 1 else body[0]
        return LlmResult(content=_faq_json(f"{evidence} 관련 질문인가요?", evidence), error_type="")


class GenerateFaqsCoversWholeDocumentTest(unittest.TestCase):
    """생성 경로가 실제로 문서 전체를 태우는가."""

    def setUp(self) -> None:
        self._chars = Config.MAX_CONTEXT_CHARS
        self._chunks = Config.MAX_CONTEXT_CHUNKS
        self._llm = generator.llm_call_async
        # 조각 규칙만 보면 되므로 예산을 실물보다 작게 잡는다.
        Config.MAX_CONTEXT_CHARS = 40
        Config.MAX_CONTEXT_CHUNKS = 40

    def tearDown(self) -> None:
        Config.MAX_CONTEXT_CHARS = self._chars
        Config.MAX_CONTEXT_CHUNKS = self._chunks
        generator.llm_call_async = self._llm

    @staticmethod
    def _document() -> str:
        return "\n".join(
            [
                "첫 번째 절의 내용은 연차 휴가에 관한 것입니다.",
                "두 번째 절의 내용은 출장 정산에 관한 것입니다.",
                "세 번째 절의 내용은 재택 근무에 관한 것입니다.",
                "네 번째 절의 내용은 교육 지원에 관한 것입니다.",
            ]
        )

    def test_last_section_reaches_the_llm(self):
        """**문서 뒷부분이 LLM 에 실제로 간다.**

        예전 코드(`source[:상한]`)로 되돌리면 마지막 절은 프롬프트에 한 번도 실리지
        않으므로 이 판정이 깨진다.
        """
        fake = _FakeLlm()
        generator.llm_call_async = fake
        result = asyncio.run(generator.generate_faqs(self._document(), 1))

        self.assertTrue(result.ok, f"failure={result.failure}")
        seen = "\n".join(fake.documents)
        self.assertIn("네 번째 절", seen, "마지막 절이 LLM 에 한 번도 실리지 않았다")
        self.assertFalse(result.source_truncated, "조각 상한에 걸리지 않았는데 잘렸다고 한다")
        self.assertGreater(result.source_chunks, 1, "조각으로 나누지 않았다")

    def test_evidence_from_any_chunk_is_grounded(self):
        """근거 대조는 **문서 전체**로 한다 — 조각으로 대조하면 경계 문장이 오탐 기각된다."""
        fake = _FakeLlm()
        generator.llm_call_async = fake
        result = asyncio.run(generator.generate_faqs(self._document(), 1))
        self.assertEqual(result.rejected_ungrounded, 0)
        self.assertEqual(len(result.items), 4)

    def test_duplicate_question_across_chunks_is_rejected(self):
        """중복 판정은 조각을 가로질러 공유한다.

        같은 주제가 여러 절에 나오면 조각마다 같은 질문이 나오는데, 조각별로 따로 세면
        그게 전부 통과한다.
        """
        same = _faq_json("연차 휴가는 며칠인가요?", "첫 번째 절의 내용은 연차 휴가에 관한 것입니다.")

        async def always_same(_system, _user):
            return LlmResult(content=same, error_type="")

        generator.llm_call_async = always_same
        result = asyncio.run(generator.generate_faqs(self._document(), 1))
        self.assertEqual(len(result.items), 1)
        self.assertGreaterEqual(result.rejected_duplicate, 1)

    def test_partial_chunk_failure_keeps_what_was_made(self):
        """조각 일부가 실패해도 **건진 항목은 내보낸다** (번역의 부분 실패 규약).

        그리고 `chunks_used < chunks_planned` 로 그 사실이 남는다 — 스텝이 이 차이를
        보고 안내문을 낸다.
        """
        fake = _FakeLlm(fail_after=2)
        generator.llm_call_async = fake
        result = asyncio.run(generator.generate_faqs(self._document(), 1))

        self.assertTrue(result.ok, "조각 하나가 실패했다고 전체를 버렸다")
        self.assertGreaterEqual(len(result.items), 2)
        self.assertLess(result.chunks_used, result.chunks_planned)

    def test_first_chunk_failure_with_no_items_is_a_failure(self):
        """하나도 못 만들었으면 실패다 — 빈 목록을 성공으로 내보내지 않는다."""

        async def always_fail(_system, _user):
            return LlmResult(content="", error_type="CONFIG_MISSING")

        generator.llm_call_async = always_fail
        result = asyncio.run(generator.generate_faqs(self._document(), 1))
        self.assertFalse(result.ok)
        self.assertEqual(result.failure, generator.FAILURE_CONFIG)

    def test_chunk_cap_marks_truncated(self):
        """조각 상한에 걸린 문서만 `source_truncated` 다 (그때만 뒤가 잘린다)."""
        Config.MAX_CONTEXT_CHUNKS = 2
        fake = _FakeLlm()
        generator.llm_call_async = fake
        result = asyncio.run(generator.generate_faqs(self._document(), 1))
        self.assertTrue(result.source_truncated)
        self.assertEqual(result.source_chunks, 2)


class _FakeLlmMulti:
    """프롬프트가 요청한 개수만큼 돌려주는 대역. 근거는 그 조각의 첫 줄이다."""

    def __init__(self, per_call: int):
        self.per_call = per_call
        self.counts: list = []

    async def __call__(self, system_prompt: str, user_prompt: str) -> LlmResult:
        body = [line for line in user_prompt.splitlines() if line.strip()]
        evidence = body[1] if len(body) > 1 else body[0]
        self.counts.append(self.per_call)
        items = [
            {
                "question": f"{evidence} 관련 질문 {index + 1}?",
                "answer": "답변입니다.",
                "evidence": evidence,
            }
            for index in range(self.per_call)
        ]
        return LlmResult(
            content=json.dumps({"faqs": items}, ensure_ascii=False), error_type=""
        )


class PerChunkCountTest(unittest.TestCase):
    """개수는 조각 수로 **나누지 않는다** (2026-08-31 요구 변경).

    그전에는 총 개수를 조각들이 나눠 가져서, 40조각 문서에서 5개를 요청하면 조각당
    0~1개였다 — 그 조각을 대표하는 FAQ 가 나올 수 없다.
    """

    def setUp(self) -> None:
        self._chars = Config.MAX_CONTEXT_CHARS
        self._chunks = Config.MAX_CONTEXT_CHUNKS
        self._cap = Config.MAX_TOTAL_FAQ_COUNT
        self._llm = generator.llm_call_async
        Config.MAX_CONTEXT_CHARS = 40
        Config.MAX_CONTEXT_CHUNKS = 40

    def tearDown(self) -> None:
        Config.MAX_CONTEXT_CHARS = self._chars
        Config.MAX_CONTEXT_CHUNKS = self._chunks
        Config.MAX_TOTAL_FAQ_COUNT = self._cap
        generator.llm_call_async = self._llm

    @staticmethod
    def _document(sections: int = 4) -> str:
        return "\n".join(
            f"{index + 1} 번째 절의 내용은 사내 규정 제{index + 1}조에 관한 것입니다."
            for index in range(sections)
        )

    def test_requested_count_is_per_chunk_not_total(self):
        """구간당 3개 · 4구간 → 목표 12개. 전체 3개로 읽으면 이 판정이 깨진다."""
        fake = _FakeLlmMulti(3)
        generator.llm_call_async = fake
        result = asyncio.run(generator.generate_faqs(self._document(), 3))

        self.assertEqual(result.source_chunks, 4)
        self.assertEqual(result.per_chunk_count, 3)
        self.assertEqual(result.requested_count, 12, "구간당 개수를 구간 수로 나눴다")
        self.assertEqual(len(result.items), 12)
        self.assertEqual(fake.counts, [3, 3, 3, 3], "구간마다 자기 몫을 요청하지 않았다")
        self.assertFalse(result.coverage_capped)

    def test_total_cap_limits_chunks_and_says_so(self):
        """상한에 걸리면 **일부 구간만** 태우고 그 사실을 낸다.

        조용히 건너뛰면 사용자는 문서 전체에서 뽑은 결과로 읽는다 — 안 나온 내용이
        문서에 없는 것으로 보인다.
        """
        Config.MAX_TOTAL_FAQ_COUNT = 10
        fake = _FakeLlmMulti(5)
        generator.llm_call_async = fake
        result = asyncio.run(generator.generate_faqs(self._document(), 5))

        self.assertEqual(result.total_cap, 10)
        self.assertEqual(result.requested_count, 10, "상한을 넘겨 만들었다")
        self.assertEqual(result.chunks_planned, 2)
        self.assertEqual(result.source_chunks, 4)
        self.assertTrue(result.coverage_capped, "일부 구간만 태운 사실이 어디에도 없다")
        # 조각 수 상한과는 다른 사건이다 — 문서 뒤를 안 본 것이 아니다.
        self.assertFalse(result.source_truncated)

    def test_notice_tells_which_share_of_the_document_was_used(self):
        """안내문이 구간 수를 말한다 — 건수만 말하면 왜 이만큼인지 알 수 없다."""
        Config.MAX_TOTAL_FAQ_COUNT = 10
        generator.llm_call_async = _FakeLlmMulti(5)
        result = asyncio.run(generator.generate_faqs(self._document(), 5))
        notice = build_notice(result)
        self.assertIn("4개 구간 중 2개 구간", notice)

    def test_short_document_behaves_like_before(self):
        """구간이 하나면 예전과 같다 — 5개를 고르면 5개다."""
        Config.MAX_CONTEXT_CHARS = 4000
        generator.llm_call_async = _FakeLlmMulti(5)
        result = asyncio.run(generator.generate_faqs(self._document(), 5))
        self.assertEqual(result.source_chunks, 1)
        self.assertEqual(result.requested_count, 5)
        self.assertEqual(len(result.items), 5)
        self.assertFalse(result.coverage_capped)


if __name__ == "__main__":
    unittest.main()
