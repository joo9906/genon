"""markdown_guard — 구조 지문 비교 동작 확인.

실행: cd SFR-018 && python -m unittest discover -s text_polish/tests -t .
"""

import unittest

from text_polish.markdown_guard import find_structure_issues

ORIGINAL = """# 보고서

내용 요약임.

| 항목 | 값 |
| --- | --- |
| 예산 | 1,200 |
| 기간 | 6개월 |
"""


class GuardTest(unittest.TestCase):
    def test_content_only_change_passes(self):
        polished = ORIGINAL.replace("내용 요약임.", "내용을 요약합니다.").replace(
            "6개월", "여섯 달"
        )
        self.assertEqual(find_structure_issues(ORIGINAL, polished), [])

    def test_dropped_table_row_detected(self):
        polished = ORIGINAL.replace("| 기간 | 6개월 |\n", "")
        issues = find_structure_issues(ORIGINAL, polished)
        self.assertTrue(any("표 구조" in i for i in issues))

    def test_changed_column_count_detected(self):
        polished = ORIGINAL.replace("| 예산 | 1,200 |", "| 예산 1,200 |")
        issues = find_structure_issues(ORIGINAL, polished)
        self.assertTrue(any("표 구조" in i for i in issues))

    def test_heading_level_change_detected(self):
        polished = ORIGINAL.replace("# 보고서", "## 보고서")
        issues = find_structure_issues(ORIGINAL, polished)
        self.assertTrue(any("제목" in i for i in issues))

    def test_paragraph_rewrite_not_flagged(self):
        # 문단 문장 수/줄 수 변화는 다듬기의 정상 동작 — 구조 훼손이 아니다
        polished = ORIGINAL.replace(
            "내용 요약임.", "내용을 요약합니다.\n\n추가 설명 문장입니다."
        )
        self.assertEqual(find_structure_issues(ORIGINAL, polished), [])

    def test_code_fence_loss_detected(self):
        original = ORIGINAL + "\n```\ncode\n```\n"
        issues = find_structure_issues(original, ORIGINAL)
        self.assertTrue(any("코드블록" in i for i in issues))


HTML_ORIGINAL = (
    "요약임.\n"
    '<table><tbody><tr><th colspan="2">구분</th></tr>'
    "<tr><td>예산</td><td>1,200</td></tr></tbody></table>\n"
)


class HtmlGuardTest(unittest.TestCase):
    """지능형 전처리기의 HTML 표 형식 점검."""

    def test_content_only_change_passes(self):
        polished = HTML_ORIGINAL.replace("요약임.", "요약합니다.").replace("예산", "총예산")
        self.assertEqual(find_structure_issues(HTML_ORIGINAL, polished), [])

    def test_dropped_html_row_detected(self):
        polished = HTML_ORIGINAL.replace("<tr><td>예산</td><td>1,200</td></tr>", "")
        issues = find_structure_issues(HTML_ORIGINAL, polished)
        self.assertTrue(any("HTML 표" in i for i in issues))

    def test_dropped_cell_detected(self):
        polished = HTML_ORIGINAL.replace("<td>1,200</td>", "")
        issues = find_structure_issues(HTML_ORIGINAL, polished)
        self.assertTrue(any("HTML 표" in i for i in issues))

    def test_whole_table_flattened_detected(self):
        polished = "요약임.\n구분 예산 1,200\n"
        issues = find_structure_issues(HTML_ORIGINAL, polished)
        self.assertTrue(any("HTML 표" in i for i in issues))


if __name__ == "__main__":
    unittest.main()
