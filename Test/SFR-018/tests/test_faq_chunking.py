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
import unittest

from . import final_path

final_path.install(final_path.FAQ_UNIT)

from faq import chunking, generator  # noqa: E402
from faq.config import Config  # noqa: E402
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


class ChunkBudgetTest(unittest.TestCase):
    """조각 크기 = `총 글자 ÷ 요청 개수` 를 하한·상한 사이로."""

    def test_middle_document_gets_one_chunk_per_item(self):
        self.assertEqual(chunking.chunk_budget(100_000, 5, 12_000, 40_000), 20_000)

    def test_short_document_is_not_cut_finer_than_floor(self):
        self.assertEqual(chunking.chunk_budget(5_000, 10, 12_000, 40_000), 12_000)

    def test_long_document_is_capped_at_ceiling(self):
        """100만 자에 10개 — 조각당 10만 자는 LLM 한 번에 실을 수 없다."""
        self.assertEqual(chunking.chunk_budget(1_000_000, 10, 12_000, 40_000), 40_000)

    def test_ceiling_below_floor_uses_floor(self):
        self.assertEqual(chunking.chunk_budget(1_000_000, 10, 12_000, 5_000), 12_000)


class SelectSpreadTest(unittest.TestCase):
    """후보에서 요청 개수만 — 근거 일치율 순, 같은 점수는 문서 전체에 고르게."""

    def test_fewer_candidates_than_count_keeps_all(self):
        self.assertEqual(chunking.select_spread([1.0, 0.9], 5), [0, 1])

    def test_higher_ratio_wins(self):
        self.assertEqual(chunking.select_spread([0.8, 1.0, 0.85, 1.0], 2), [1, 3])

    def test_ties_are_spread_not_front_loaded(self):
        """일치율이 모두 같으면(실제로 대부분 1.0) 앞에서 자르지 않고 고르게 고른다."""
        chosen = chunking.select_spread([1.0] * 84, 10)
        self.assertEqual(len(chosen), 10)
        self.assertEqual(len(set(chosen)), 10)
        self.assertLess(chosen[0], 9, f"{chosen}")
        self.assertGreater(chosen[-1], 75, f"뒷부분이 빠졌다: {chosen}")

    def test_result_is_in_document_order(self):
        chosen = chunking.select_spread([0.9, 1.0, 0.95, 1.0, 0.9], 3)
        self.assertEqual(chosen, sorted(chosen))


class PlanQuotaTest(unittest.TestCase):
    """**모든 조각이 최소 1개를 받고, 총 개수를 조각들이 나눠 갖는다.**"""

    def test_sum_is_total_or_chunk_count_whichever_is_larger(self):
        """합이 `max(총 개수, 조각 수)` 다 — 조각이 많으면 조각 수만큼 늘어난다."""
        for chunk_count in range(1, 12):
            for total in range(1, 31, 3):
                quota = chunking.plan_quota(chunk_count, total)
                self.assertEqual(len(quota), chunk_count)
                self.assertEqual(sum(quota), max(total, chunk_count), f"{chunk_count},{total}")

    def test_no_chunk_is_skipped(self):
        """**건너뛰는 조각이 없다** — 몫 0 인 조각은 LLM 이 한 번도 안 본 구간이다."""
        for chunk_count, total in ((40, 30), (40, 3), (90, 5), (7, 7), (1, 5)):
            quota = chunking.plan_quota(chunk_count, total)
            self.assertTrue(all(value >= 1 for value in quota), f"{chunk_count},{total}: {quota}")

    def test_more_chunks_than_total_gives_one_each(self):
        self.assertEqual(chunking.plan_quota(40, 3), [1] * 40)

    def test_remainder_is_spread_not_dumped_on_one_chunk(self):
        """나누어떨어지지 않는 나머지는 한 개씩 얹는다 — 몰아주면 그 구간만 과대표된다."""
        quota = chunking.plan_quota(4, 10)
        self.assertEqual(sorted(quota), [2, 2, 3, 3])

    def test_short_document_gets_it_all(self):
        """조각이 하나면 그 조각이 전부 만든다 — 5개를 고르면 5개다."""
        self.assertEqual(chunking.plan_quota(1, 5), [5])

    def test_zero_inputs_yield_no_call(self):
        self.assertEqual(chunking.plan_quota(3, 0), [0, 0, 0])
        self.assertEqual(chunking.plan_quota(0, 5), [])


def _faq_block(items) -> str:
    """LLM 출력 대역 — **마크다운 구분자 형식** (`prompt/SFR-018_faq/md_system.md`).

    라벨·표식은 `faq/markdown_items.py` 의 상수와 글자 그대로 같아야 한다. 한쪽만
    고치면 파서가 0건을 내고 모든 판정이 "아무것도 안 나왔다" 로 떨어진다.
    """
    parts = []
    for item in items:
        parts.append(
            "<<<FAQ\n"
            f"근거: {item['evidence']}\n"
            f"질문: {item['question']}\n"
            f"답변: {item['answer']}\n"
            ">>>"
        )
    return "\n".join(parts)


def _faq_json(question: str, evidence: str) -> str:
    return _faq_block(
        [{"question": question, "answer": "답변입니다.", "evidence": evidence}]
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


# 이 클래스의 문서는 네 조각이고, 요청 개수는 **총 개수**다. 조각마다 최소 1개라
# 네 개를 요청하면 조각마다 정확히 하나씩이다.
_ONE_PER_CHUNK = 4


class GenerateFaqsCoversWholeDocumentTest(unittest.TestCase):
    """생성 경로가 실제로 문서 전체를 태우는가."""

    def setUp(self) -> None:
        self._chars = Config.MAX_CONTEXT_CHARS
        self._ceiling = Config.MAX_CHUNK_CHARS
        self._llm = generator.llm_call_async
        # 조각 규칙만 보면 되므로 예산(하한·상한)을 실물보다 작게 잡는다.
        Config.MAX_CONTEXT_CHARS = 40
        Config.MAX_CHUNK_CHARS = 40

    def tearDown(self) -> None:
        Config.MAX_CONTEXT_CHARS = self._chars
        Config.MAX_CHUNK_CHARS = self._ceiling
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
        result = asyncio.run(generator.generate_faqs(self._document(), _ONE_PER_CHUNK))

        self.assertTrue(result.ok, f"failure={result.failure}")
        seen = "\n".join(fake.documents)
        self.assertIn("네 번째 절", seen, "마지막 절이 LLM 에 한 번도 실리지 않았다")
        self.assertGreater(result.source_chunks, 1, "조각으로 나누지 않았다")

    def test_evidence_from_any_chunk_is_grounded(self):
        """근거 대조는 **문서 전체**로 한다 — 조각으로 대조하면 경계 문장이 오탐 기각된다."""
        fake = _FakeLlm()
        generator.llm_call_async = fake
        result = asyncio.run(generator.generate_faqs(self._document(), _ONE_PER_CHUNK))
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
        result = asyncio.run(generator.generate_faqs(self._document(), _ONE_PER_CHUNK))
        self.assertEqual(len(result.items), 1)
        self.assertGreaterEqual(result.rejected_duplicate, 1)

    def test_partial_chunk_failure_keeps_what_was_made(self):
        """조각 일부가 실패해도 **건진 항목은 내보낸다** (번역의 부분 실패 규약).

        그리고 `chunks_used < chunks_planned` 로 그 사실이 남는다 — 스텝이 이 차이를
        보고 안내문을 낸다.
        """
        fake = _FakeLlm(fail_after=2)
        generator.llm_call_async = fake
        result = asyncio.run(generator.generate_faqs(self._document(), _ONE_PER_CHUNK))

        self.assertTrue(result.ok, "조각 하나가 실패했다고 전체를 버렸다")
        self.assertGreaterEqual(len(result.items), 2)
        self.assertLess(result.chunks_used, result.chunks_planned)

    def test_first_chunk_failure_with_no_items_is_a_failure(self):
        """하나도 못 만들었으면 실패다 — 빈 목록을 성공으로 내보내지 않는다."""

        async def always_fail(_system, _user):
            return LlmResult(content="", error_type="CONFIG_MISSING")

        generator.llm_call_async = always_fail
        result = asyncio.run(generator.generate_faqs(self._document(), _ONE_PER_CHUNK))
        self.assertFalse(result.ok)
        self.assertEqual(result.failure, generator.FAILURE_CONFIG)

    def test_every_chunk_is_called(self):
        """**모든 조각이 LLM 에 실린다** — 조각 수가 많아도 건너뛰지 않는다."""
        Config.MAX_CONTEXT_CHARS = 20
        Config.MAX_CHUNK_CHARS = 20
        fake = _FakeLlm()
        generator.llm_call_async = fake
        result = asyncio.run(generator.generate_faqs(self._document(), 1))
        self.assertGreater(result.source_chunks, 4)
        # 모자란 만큼의 재요청이 더해질 수 있어 "이상" 이다 — 조각이 빠지지 않는 것이 요점이다.
        self.assertGreaterEqual(len(fake.documents), result.source_chunks)
        self.assertEqual(result.chunks_planned, result.source_chunks)
        self.assertEqual(result.chunks_used, result.source_chunks)
        seen = chr(10).join(fake.documents)
        for section in ("첫 번째", "두 번째", "세 번째", "네 번째"):
            self.assertIn(section, seen)


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
        return LlmResult(content=_faq_block(items), error_type="")


class TotalCountTest(unittest.TestCase):
    """**사용자는 총 개수만 고르고 배분은 우리가 한다** (2026-09-03 요구 확정).

    고른 숫자가 곧 받는 개수다. 2026-08-31~09-02 에는 선택이 구간당 개수여서 구간이
    여섯이면 5를 골라도 30개가 나왔다.

    대역은 **몫보다 많이** 돌려준다(10건). 조각마다 채택된 건수가 곧 그 조각의 몫이라,
    배분이 틀리면 총합이 아니라 **분포**에서 먼저 드러난다.
    """

    def setUp(self) -> None:
        self._chars = Config.MAX_CONTEXT_CHARS
        self._ceiling = Config.MAX_CHUNK_CHARS
        self._llm = generator.llm_call_async
        Config.MAX_CONTEXT_CHARS = 40
        Config.MAX_CHUNK_CHARS = 40

    def tearDown(self) -> None:
        Config.MAX_CONTEXT_CHARS = self._chars
        Config.MAX_CHUNK_CHARS = self._ceiling
        generator.llm_call_async = self._llm

    @staticmethod
    def _document(sections: int = 4) -> str:
        return "\n".join(
            f"{index + 1} 번째 절의 내용은 사내 규정 제{index + 1}조에 관한 것입니다."
            for index in range(sections)
        )

    def test_user_choice_is_the_total_not_the_per_chunk_share(self):
        """8개를 고르면 4구간 문서에서도 **8개**다 (구간당으로 읽으면 32개가 된다)."""
        fake = _FakeLlmMulti(10)
        generator.llm_call_async = fake
        result = asyncio.run(generator.generate_faqs(self._document(), 8))

        self.assertEqual(result.source_chunks, 4)
        self.assertEqual(result.requested_count, 8, "사용자가 고른 총 개수가 아니다")
        self.assertEqual(len(result.items), 8, "고른 숫자와 받는 개수가 다르다")
        self.assertEqual(len(fake.counts), 4, "구간마다 한 번씩 부르지 않았다")
        self.assertEqual(result.chunks_planned, 4)

    def test_total_is_shared_evenly_across_chunks(self):
        """몫은 구간들에 **고르게** 나눈다 — 앞 구간이 다 먹으면 뒤 구간이 안 실린다."""
        generator.llm_call_async = _FakeLlmMulti(10)
        result = asyncio.run(generator.generate_faqs(self._document(), 8))
        # 대역은 근거로 그 조각의 첫 줄을 쓴다 → 근거별 건수가 곧 조각별 몫이다.
        per_chunk = {}
        for item in result.items:
            per_chunk[item.evidence] = per_chunk.get(item.evidence, 0) + 1
        self.assertEqual(sorted(per_chunk.values()), [2, 2, 2, 2], f"분포={per_chunk}")

    def test_more_chunks_than_requested_keeps_the_count_and_spreads(self):
        """구간이 요청보다 많으면 **구간마다 후보 1개** 를 만들고 요청 개수만 남긴다.

        남는 것은 앞 구간이 아니라 문서 전체에 퍼진 것이다 — 근거 일치율이 같으면 고르게 고른다.
        """
        fake = _FakeLlmMulti(10)
        generator.llm_call_async = fake
        result = asyncio.run(generator.generate_faqs(self._document(), 2))

        self.assertEqual(result.source_chunks, 4)
        self.assertEqual(len(fake.counts), 4, "일부 구간을 건너뛰었다")
        self.assertEqual(result.requested_count, 2)
        self.assertEqual(len(result.items), 2, "고른 숫자와 받는 개수가 다르다")
        self.assertEqual(result.candidate_count, 4)
        sections = [item.evidence.split(" ")[0] for item in result.items]
        self.assertEqual(sections, ["2", "4"], f"앞 구간에 몰렸다: {sections}")

    def test_short_document_behaves_like_before(self):
        """구간이 하나면 그 구간이 전부 만든다 — 5개를 고르면 5개다."""
        Config.MAX_CONTEXT_CHARS = 4000
        generator.llm_call_async = _FakeLlmMulti(10)
        result = asyncio.run(generator.generate_faqs(self._document(), 5))
        self.assertEqual(result.source_chunks, 1)
        self.assertEqual(result.requested_count, 5)
        self.assertEqual(len(result.items), 5)


class _ConcurrencyProbe:
    """동시에 몇 개가 떠 있었는지 재는 대역.

    **순차 코드로는 `peak > 1` 이 될 수 없다** — 타이밍에 기대지 않는 판정이다.
    `_FakeLlmMulti` 와 같은 응답을 내되(근거 = 그 조각의 첫 줄) 응답 전에 잠깐 양보해
    다른 호출이 들어올 틈을 준다.
    """

    def __init__(self, per_call: int = 1, delay: float = 0.02):
        self.per_call = per_call
        self.delay = delay
        self.inflight = 0
        self.peak = 0
        self.finished: list = []

    async def __call__(self, system_prompt: str, user_prompt: str) -> LlmResult:
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        body = [line for line in user_prompt.splitlines() if line.strip()]
        evidence = body[1] if len(body) > 1 else body[0]
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.inflight -= 1
        self.finished.append(evidence)
        items = [
            {
                "question": f"{evidence} 관련 질문 {index + 1}?",
                "answer": "답변입니다.",
                "evidence": evidence,
            }
            for index in range(self.per_call)
        ]
        return LlmResult(content=_faq_block(items), error_type="")


class _ReverseOrderLlm(_ConcurrencyProbe):
    """**뒤 조각이 먼저 끝나게** 만든다 — 도착 순서가 결과를 흔드는지 보는 대역."""

    async def __call__(self, system_prompt: str, user_prompt: str) -> LlmResult:
        body = [line for line in user_prompt.splitlines() if line.strip()]
        evidence = body[1] if len(body) > 1 else body[0]
        # 조각 번호가 앞일수록 오래 걸린다 (문서 첫 줄이 "1 번째 절…" 이다)
        try:
            order = int(evidence.split(" ", 1)[0])
        except ValueError:
            order = 0
        self.delay = 0.005 * (5 - order)
        return await super().__call__(system_prompt, user_prompt)


class ParallelChunkCallTest(unittest.TestCase):
    """조각 호출은 **겹쳐 돈다** (2026-09-09).

    조각 사이에 순서 의존이 없는데도 순차로 돌아서 **대기시간이 조각 수에 비례**했다.
    여기서 보는 것은 "빠른가" 가 아니라 **동시에 떠 있었는가** 다 — 순차 코드에서는
    어떤 타이밍에도 `peak` 가 1 을 넘을 수 없다.
    """

    def setUp(self) -> None:
        self._chars = Config.MAX_CONTEXT_CHARS
        self._concurrency = Config.LLM_CONCURRENCY
        self._llm = generator.llm_call_async
        Config.MAX_CONTEXT_CHARS = 40

    def tearDown(self) -> None:
        Config.MAX_CONTEXT_CHARS = self._chars
        Config.LLM_CONCURRENCY = self._concurrency
        generator.llm_call_async = self._llm

    @staticmethod
    def _document(sections: int = 4) -> str:
        return chr(10).join(
            f"{index + 1} 번째 절의 내용은 사내 규정 제{index + 1}조에 관한 것입니다."
            for index in range(sections)
        )

    def test_chunks_are_called_concurrently(self):
        """조각들이 **동시에** LLM 에 떠 있다 — 순차로 되돌리면 peak 가 1 이다."""
        probe = _ConcurrencyProbe(per_call=2)
        generator.llm_call_async = probe
        result = asyncio.run(generator.generate_faqs(self._document(), 8))

        self.assertTrue(result.ok, f"failure={result.failure}")
        self.assertEqual(result.chunks_used, 4)
        self.assertGreater(probe.peak, 1, "조각을 하나씩 순차로 불렀다")

    def test_concurrency_is_capped(self):
        """동시 수는 `FAQ_LLM_CONCURRENCY` 가 잡는다 — 없으면 조각 수만큼 한꺼번에 뜬다."""
        Config.LLM_CONCURRENCY = 2
        probe = _ConcurrencyProbe(per_call=2)
        generator.llm_call_async = probe
        asyncio.run(generator.generate_faqs(self._document(), 8))
        self.assertEqual(probe.peak, 2, f"동시 수 상한을 지키지 않았다: peak={probe.peak}")

    def test_adoption_follows_chunk_order_not_arrival_order(self):
        """**도착 순서가 결과를 흔들지 않는다.**

        중복 판정·기각 건수·조각별 채택 상한이 누적 상태라, 도착한 순서대로 채택하면
        같은 문서가 실행마다 다른 분포를 낸다 — 오류로는 드러나지 않는다.
        """
        llm = _ReverseOrderLlm(per_call=10)
        generator.llm_call_async = llm
        result = asyncio.run(generator.generate_faqs(self._document(), 8))

        # 뒤 조각이 먼저 끝났는데도
        self.assertEqual(
            llm.finished[0].split(" ", 1)[0], "4", f"도착 순서가 뒤집히지 않았다: {llm.finished}"
        )
        # 채택은 조각 순서대로다 (몫도 고르게 유지된다)
        adopted = [item.evidence.split(" ", 1)[0] for item in result.items]
        self.assertEqual(adopted, ["1", "1", "2", "2", "3", "3", "4", "4"], f"{adopted}")

    def test_one_chunk_failure_does_not_cancel_the_others(self):
        """조각 하나가 실패해도 나머지는 이미 떠 있다 — 건진 항목을 버리지 않는다."""

        class _OneFails(_ConcurrencyProbe):
            async def __call__(self, system_prompt, user_prompt):
                if "2 번째 절" in user_prompt:
                    return LlmResult(
                        content="", error_type="APITimeoutError", is_transport_error=True
                    )
                return await super().__call__(system_prompt, user_prompt)

        generator.llm_call_async = _OneFails(per_call=2)
        result = asyncio.run(generator.generate_faqs(self._document(), 8))
        self.assertTrue(result.ok, "조각 하나가 실패했다고 전체를 버렸다")
        self.assertEqual(result.chunks_used, 3)
        self.assertEqual(result.chunks_planned, 4)


if __name__ == "__main__":
    unittest.main()
