"""markdown_guard — 구조 지문 비교 동작 확인.

실행: `cd SFR-018 && python -m unittest discover -s tests -t .`

**MCP 도구 파일(`onprem/mcp/genon_text_guard.py`)을 태운다.** 2026-08-11 영역 재배치로
이 모듈이 글다듬이 코드서빙에서 MCP 로 옮겨갔다 — LLM 을 쓰지 않는 결정적 판정이라
area 01 이 제자리다. 사본을 검증하던 옛 테스트는 그 이동을 전혀 몰랐고, 옮겨간 뒤에도
옛 파일을 계속 통과시켰다.

이 파일이 지키는 계약: **표를 유지하라는 프롬프트 지시로 구조 보존을 처리하지 않는다.**
LLM 이 되쓴 결과와 원문의 지문(표 행·열 수, 제목 단계, 코드펜스)을 코드가 대조한다.
"""

import unittest

from . import onprem_path  # noqa: F401

# MCP 는 패키지가 아니라 **파일 하나**라 import 문으로 끌어올 수 없다. 파일을 실어
# 그 안의 함수를 꺼낸다. 심볼에 `tg` 접두어가 붙어 있는 이유는 한 서버에 다른 도구
# 파일이 함께 로드될 수 있어서다 (겹치면 나중 것이 앞엣것을 덮는다).
_guard = onprem_path.load_mcp(onprem_path.TEXT_GUARD_MCP)
find_structure_issues = _guard.tgfind_structure_issues

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
