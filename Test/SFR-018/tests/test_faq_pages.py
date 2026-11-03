"""FAQ 근거 쪽 — 첨부 원문의 쪽 표식(`[[GENON_PAGE n]]`)으로 근거의 쪽을 코드가 정한다."""

import asyncio
import unittest

from . import final_path

final_path.install(final_path.FAQ_UNIT)

from faq import generator  # noqa: E402
from faq.evidence import EvidenceChecker  # noqa: E402
from faq.formatting import evidence_line, rows_to_markdown, to_export_rows  # noqa: E402
from faq.llm import LlmResult  # noqa: E402
from faq.pages import split_pages  # noqa: E402

from .test_faq_stream import _FakeStream, _item  # noqa: E402

_MARKED = (
    "[[GENON_PAGE 1]]\n가맹점 등록은 영업일 기준 3일이 걸립니다.\n\n"
    "[[GENON_PAGE 2]]\n수수료는 매월 25일에 정산합니다.\n\n"
    "[[GENON_PAGE 2]]\n정산 내역은 메일로 보냅니다."
)


class SplitPagesTest(unittest.TestCase):
    def test_markers_are_removed_and_segments_keep_pages(self):
        clean, segments = split_pages(_MARKED)
        self.assertNotIn("GENON_PAGE", clean)
        self.assertEqual([page for page, _ in segments], [1, 2, 2])

    def test_text_before_first_marker_has_no_page(self):
        clean, segments = split_pages("머리글\n[[GENON_PAGE 3]]\n본문")
        self.assertEqual(clean, "머리글\n본문")
        self.assertEqual(segments, [(3, "본문")])

    def test_unmarked_text_has_no_segments(self):
        self.assertEqual(split_pages("표식 없는 원문"), ("표식 없는 원문", []))


class EvidencePageTest(unittest.TestCase):
    def setUp(self) -> None:
        clean, segments = split_pages(_MARKED)
        self.checker = EvidenceChecker(clean, segments)

    def test_verbatim_evidence_gets_its_page(self):
        self.assertEqual(self.checker.check("수수료는 매월 25일에 정산합니다.", 0.8).page, 2)
        self.assertEqual(self.checker.check("영업일 기준 3일", 0.8).page, 1)

    def test_evidence_across_pages_goes_to_the_larger_share(self):
        verdict = self.checker.check("3일이 걸립니다. 수수료는 매월 25일에 정산합니다.", 0.8)
        self.assertTrue(verdict.grounded)
        self.assertEqual(verdict.page, 2)

    def test_rejected_or_unmarked_evidence_has_no_page(self):
        self.assertIsNone(self.checker.check("문서에 없는 문장", 0.8).page)
        self.assertIsNone(EvidenceChecker("수수료는 25일").check("수수료는 25일", 0.8).page)


class EvidenceLineTest(unittest.TestCase):
    def test_page_is_shown_only_when_known(self):
        self.assertEqual(evidence_line("근거 문장", 3), "> 근거 (3쪽): 근거 문장")
        self.assertEqual(evidence_line("근거 문장", None), "> 근거: 근거 문장")

    def test_file_carries_page(self):
        item = generator.FaqItem("질문?", "답변.", "근거 문장", 1.0, page=4)
        self.assertIn("> 근거 (4쪽): 근거 문장", rows_to_markdown(to_export_rows([item])))
        # 쪽이 없던 시절에 저장된 행도 그대로 그린다.
        old = [{"question": "질문?", "answer": "답변.", "sources": "근거 문장"}]
        self.assertIn("> 근거: 근거 문장", rows_to_markdown(old))


class GeneratePageTest(unittest.TestCase):
    body = _item("수수료는 매월 25일에 정산합니다.", "정산일은?", "25일입니다.")

    def test_plain_path_sets_page_and_hides_markers_from_llm(self):
        prompts: list = []

        async def fake_call(system_prompt, user_prompt):
            prompts.append(user_prompt)
            return LlmResult(content=self.body, error_type="")

        original = generator.llm_call_async
        generator.llm_call_async = fake_call
        try:
            result = asyncio.run(generator.generate_faqs(_MARKED, 1))
        finally:
            generator.llm_call_async = original
        self.assertEqual([item.page for item in result.items], [2])
        self.assertEqual(result.as_payload()["items"][0]["page"], 2)
        self.assertTrue(prompts and all("GENON_PAGE" not in p for p in prompts))

    def test_stream_path_puts_page_on_close_frame(self):
        frames: list = []

        async def on_frame(frame):
            frames.append(frame)

        original = generator.faq_stream_async
        generator.faq_stream_async = _FakeStream(self.body)
        try:
            result = asyncio.run(generator.generate_faqs_stream(_MARKED, 1, on_frame=on_frame))
        finally:
            generator.faq_stream_async = original
        closes = [f for f in frames if f.get("type") == generator.FRAME_ITEM_CLOSE]
        self.assertEqual([f["page"] for f in closes], [2])
        self.assertEqual([item.page for item in result.items], [2])


if __name__ == "__main__":
    unittest.main()
