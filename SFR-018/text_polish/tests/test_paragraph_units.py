"""문단 정렬 테스트 — 원본 hwpx 되쓰기 좌표의 정확성을 지킨다.

되쓰기는 "몇 번째 문단이 무엇으로 바뀌었는지"가 정확해야 성립한다. LLM 이 줄을 합치거나
번호를 빼먹으면 **엉뚱한 문단에 값이 들어가는데 그건 조용히 망가지는 실패**다.
그래서 번호 표시로 정렬하고, 어긋난 항목은 채택하지 않고 사유를 보고한다.
이 테스트가 그 계약을 고정한다.
"""

import unittest

from text_polish.paragraph_units import (
    build_numbered_source,
    merge_display_text,
    parse_numbered_result,
)

_PARAGRAPHS = [
    {"index": 0, "text": "보고서 제목"},
    {"index": 1, "text": "안녕하세요 중요한 사항입니다"},
    {"index": 2, "text": "셀 하나"},
]
_EXPECTED = {item["index"] for item in _PARAGRAPHS}


class BuildNumberedSourceTest(unittest.TestCase):
    def test_문단마다_번호_표시를_붙인다(self):
        source = build_numbered_source(_PARAGRAPHS)
        self.assertEqual(
            source.splitlines(),
            ["⟦0⟧ 보고서 제목", "⟦1⟧ 안녕하세요 중요한 사항입니다", "⟦2⟧ 셀 하나"],
        )

    def test_빈_문단은_넣지_않는다(self):
        source = build_numbered_source([{"index": 0, "text": "  "}, {"index": 1, "text": "본문"}])
        self.assertEqual(source, "⟦1⟧ 본문")

    def test_문단_안_줄바꿈은_공백으로_눌러_한_줄로_만든다(self):
        # 줄바꿈이 남으면 문단 경계와 줄 경계가 섞인다
        source = build_numbered_source([{"index": 0, "text": "첫 줄\n둘째 줄"}])
        self.assertEqual(source, "⟦0⟧ 첫 줄 둘째 줄")


class ParseNumberedResultTest(unittest.TestCase):
    def test_정상_응답은_전부_채택한다(self):
        response = "⟦0⟧ 새 제목\n⟦1⟧ 안녕하십니까.\n⟦2⟧ 첫째 셀"
        parsed, notes = parse_numbered_result(response, _EXPECTED)
        self.assertEqual(parsed, {0: "새 제목", 1: "안녕하십니까.", 2: "첫째 셀"})
        self.assertEqual(notes, [])

    def test_빠진_번호는_원문을_유지하고_사유를_보고한다(self):
        parsed, notes = parse_numbered_result("⟦0⟧ 새 제목\n⟦2⟧ 첫째 셀", _EXPECTED)
        self.assertNotIn(1, parsed)
        self.assertTrue(any("빠진 문단" in note for note in notes))
        # 화면 본문에는 원문이 그대로 남아야 한다
        self.assertEqual(
            merge_display_text(_PARAGRAPHS, parsed).splitlines()[1],
            "안녕하세요 중요한 사항입니다",
        )

    def test_번호가_중복되면_채택하지_않는다(self):
        # 어느 쪽이 맞는지 알 수 없으므로 첫 번째만 쓰고 사실을 알린다
        response = "⟦0⟧ 첫째\n⟦0⟧ 둘째\n⟦1⟧ 본문\n⟦2⟧ 셀"
        parsed, notes = parse_numbered_result(response, _EXPECTED)
        self.assertEqual(parsed[0], "첫째")
        self.assertTrue(any("중복" in note for note in notes))

    def test_원문에_없는_번호는_무시한다(self):
        response = "⟦0⟧ 가\n⟦1⟧ 나\n⟦2⟧ 다\n⟦99⟧ 지어낸 문단"
        parsed, notes = parse_numbered_result(response, _EXPECTED)
        self.assertNotIn(99, parsed)
        self.assertTrue(any("없는 번호" in note for note in notes))

    def test_본문에_줄바꿈이_섞여도_문단_경계를_잃지_않는다(self):
        response = "⟦0⟧ 제목\n계속되는 줄\n⟦1⟧ 본문\n⟦2⟧ 셀"
        parsed, _ = parse_numbered_result(response, _EXPECTED)
        self.assertIn("계속되는 줄", parsed[0])

    def test_표시가_아예_없으면_아무것도_채택하지_않는다(self):
        # 번호를 다 잃은 응답으로 되쓰면 전부 어긋난다 — 채택 0 이 정답이다
        parsed, notes = parse_numbered_result("그냥 다듬은 본문입니다.", _EXPECTED)
        self.assertEqual(parsed, {})
        self.assertTrue(notes)

    def test_빈_본문은_채택하지_않는다(self):
        parsed, notes = parse_numbered_result("⟦0⟧ \n⟦1⟧ 본문\n⟦2⟧ 셀", _EXPECTED)
        self.assertNotIn(0, parsed)
        self.assertTrue(notes)


class MergeDisplayTextTest(unittest.TestCase):
    def test_채택된_문단만_바꾸고_나머지는_원문(self):
        merged = merge_display_text(_PARAGRAPHS, {1: "다듬은 본문"})
        self.assertEqual(merged.splitlines(), ["보고서 제목", "다듬은 본문", "셀 하나"])

    def test_채택이_없으면_원문_그대로(self):
        merged = merge_display_text(_PARAGRAPHS, {})
        self.assertEqual(merged.splitlines(), [item["text"] for item in _PARAGRAPHS])


if __name__ == "__main__":
    unittest.main()
