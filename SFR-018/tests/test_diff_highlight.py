"""글다듬이 변경 하이라이트 — 낱말 단위 판정과 좌표 (2026-08-27 추가).

실행: `cd SFR-018 && python -m unittest discover -s tests -t .`

**MCP 도구 파일(`onprem/mcp/genon_text_guard.py`)을 태운다.**

## 이 파일이 지키는 계약

변경 표시는 **답변 아래 목록이 아니라 본문 위 하이라이트**다. 그러려면 두 가지가
성립해야 하고, 둘 다 여기서 지킨다:

1. **낱말 단위** — 문장 쌍은 "이 문장이 바뀌었다" 까지만 말한다. 어느 낱말을
   손질했는지가 요구였다.
2. **되쓴 글 기준 좌표(`span`)** — 좌표가 없으면 프론트는 `after` 문자열을 본문에서
   다시 찾아야 하고, 같은 낱말이 두 번 나오면 어느 쪽을 칠할지 결정할 수 없다.
   **좌표 없이는 인라인 하이라이트가 성립하지 않는다.**

그리고 하이라이트는 **정본을 손대지 않는다** — `POST /download` 가 정본을 그대로
파일로 만들기 때문에, 태그가 정본에 섞이면 사용자가 메모장에서 지워야 한다.
"""

import unittest

from . import onprem_path  # noqa: F401

_guard = onprem_path.load_mcp(onprem_path.TEXT_GUARD_MCP)
build_change_list = _guard.tgbuild_change_list
build_highlighted = _guard.tgbuild_highlighted
call_tool = _guard.tgcall_tool


class SpanTest(unittest.TestCase):
    """`span` 이 되쓴 글에서 **실제로 그 낱말을 가리키는가**."""

    def test_span_points_at_the_changed_word(self):
        source = "본 사업은 2026년에 개발함."
        revised = "본 사업은 2026년에 개발하였습니다."
        changes = build_change_list(source, revised)
        self.assertEqual(len(changes), 1)
        start, end = changes[0]["span"]
        # 좌표가 가리키는 글자가 곧 `after` 다. 이 등식이 하이라이트의 전부다.
        self.assertEqual(revised[start:end], changes[0]["after"])
        self.assertEqual(changes[0]["after"], "개발하였습니다.")
        self.assertEqual(changes[0]["before"], "개발함.")

    def test_only_the_changed_word_is_marked_not_the_whole_sentence(self):
        """문장 단위로 냈다면 span 이 문장 전체를 덮는다 — 그러면 표시가 묻힌다."""
        source = "담당자가 자료를 검토함."
        revised = "담당자가 자료를 검토하였습니다."
        changes = build_change_list(source, revised)
        start, end = changes[0]["span"]
        self.assertNotIn("담당자가", revised[start:end])
        self.assertNotIn("자료를", revised[start:end])

    def test_repeated_word_gets_its_own_span(self):
        """같은 낱말이 두 번 나오는 경우 — 문자열 검색으로는 가릴 수 없는 자리다."""
        source = "검토함. 다시 검토함."
        revised = "검토함. 다시 검토하였습니다."
        changes = build_change_list(source, revised)
        self.assertEqual(len(changes), 1)
        start, end = changes[0]["span"]
        # 앞쪽 `검토함.` 이 아니라 **뒤쪽**이 바뀐 것이다
        self.assertGreater(start, revised.index("검토함."))
        self.assertEqual(revised[start:end], "검토하였습니다.")

    def test_deletion_has_no_span(self):
        """되쓴 글에 칠할 글자가 없다. 0 을 넣으면 문서 맨 앞이 칠해진다."""
        source = "불필요한 문장이다. 남는 문장이다."
        revised = "남는 문장이다."
        changes = build_change_list(source, revised)
        deletions = [c for c in changes if not c["after"]]
        self.assertTrue(deletions)
        for item in deletions:
            self.assertIsNone(item["span"])

    def test_insertion_gets_a_span(self):
        source = "남는 문장이다."
        revised = "새 문장이다. 남는 문장이다."
        changes = build_change_list(source, revised)
        start, end = changes[0]["span"]
        self.assertEqual(revised[start:end], "새 문장이다.")

    def test_max_items_caps_the_list(self):
        source = "\n".join(f"{i}번 항목임." for i in range(30))
        revised = "\n".join(f"{i}번 항목입니다." for i in range(30))
        changes = build_change_list(source, revised, max_items=5)
        self.assertEqual(len(changes), 5)

    def test_identical_text_has_no_changes(self):
        text = "그대로인 문장입니다."
        self.assertEqual(build_change_list(text, text), [])
        self.assertEqual(build_highlighted(text, []), text)


class HighlightTest(unittest.TestCase):
    """표시용 사본 — 정본은 손대지 않고, 태그를 손상 없이 끼우는가."""

    def test_marks_wrap_the_changed_words(self):
        source = "본 사업은 개발함. 담당자가 검토함."
        revised = "본 사업은 개발하였습니다. 담당자가 검토하였습니다."
        marked = build_highlighted(revised, build_change_list(source, revised))
        self.assertEqual(
            marked,
            "본 사업은 <mark>개발하였습니다.</mark> 담당자가 <mark>검토하였습니다.</mark>",
        )

    def test_stripping_the_tags_restores_the_original(self):
        """정본이 그대로 남아 있다는 것을 문자 단위로 본다 — 파일이 이 값이다."""
        source = "계획을 수립함. 예산은 1,200만원임."
        revised = "계획을 수립하였습니다. 예산은 1,200만원입니다."
        marked = build_highlighted(revised, build_change_list(source, revised))
        self.assertEqual(marked.replace("<mark>", "").replace("</mark>", ""), revised)

    def test_markdown_table_cell_is_marked(self):
        source = "| 구분 | 값 |\n| --- | --- |\n| 매출 | 100 |"
        revised = "| 구분 | 값 |\n| --- | --- |\n| 매출액 | 100 |"
        marked = build_highlighted(revised, build_change_list(source, revised))
        self.assertIn("<mark>매출액</mark>", marked)
        # 표 구조는 건드리지 않는다
        self.assertIn("| --- | --- |", marked)

    def test_html_table_cell_is_marked_without_breaking_tags(self):
        """전처리기가 표를 한 줄 HTML 로 낸다. 태그 가운데를 가르면 표가 통째로 깨진다.

        공백으로만 낱말을 끊으면 이 줄이 통째로 낱말 하나가 되고, 그 span 은 태그에
        걸치므로 칠할 수 없게 된다 — **HTML 표 안 변경은 영영 표시되지 않는다.**
        """
        source = "<table><tbody><tr><td>매출</td><td>100</td></tr></tbody></table>"
        revised = "<table><tbody><tr><td>매출액</td><td>100</td></tr></tbody></table>"
        marked = build_highlighted(revised, build_change_list(source, revised))
        self.assertIn("<td><mark>매출액</mark></td>", marked)
        # 태그는 하나도 갈라지지 않았다
        self.assertIn("<table><tbody><tr>", marked)
        self.assertIn("</tr></tbody></table>", marked)

    def test_code_fence_is_left_alone(self):
        """코드펜스 안에 끼우면 `<mark>` 가 화면에 글자 그대로 나온다."""
        source = "설명은 아래와 같다.\n```\nfoo = 1\n```"
        revised = "설명은 아래와 같습니다.\n```\nfoo = 2\n```"
        marked = build_highlighted(revised, build_change_list(source, revised))
        self.assertIn("<mark>같습니다.</mark>", marked)
        self.assertIn("\nfoo = 2\n", marked)
        self.assertNotIn("<mark>foo", marked)
        self.assertNotIn("mark>2", marked)

    def test_overlapping_spans_merge_into_one_tag(self):
        """겹친 채로 각각 감싸면 `<mark>A<mark>B</mark>C</mark>` 가 된다."""
        text = "The merchant invoice ok"
        changes = [{"before": "x", "after": "y", "span": [4, 12]},
                   {"before": "x", "after": "y", "span": [4, 20]}]
        marked = build_highlighted(text, changes)
        self.assertEqual(marked, "The <mark>merchant invoice</mark> ok")
        self.assertEqual(marked.count("<mark>"), 1)

    def test_out_of_range_and_malformed_spans_are_ignored(self):
        """프론트가 준 값이 아니라 우리 계산이지만, 좌표가 어긋나면 본문이 깨진다."""
        text = "짧은 글"
        for span in ([0, 999], [5, 2], ["a", "b"], [1], None, [-1, 2]):
            marked = build_highlighted(text, [{"before": "x", "after": "y", "span": span}])
            self.assertEqual(marked, text, f"span={span!r}")


class ToolContractTest(unittest.TestCase):
    """`diff_changes` 응답이 스텝이 읽는 모양인가 — 키가 어긋나면 조용히 빈 값이 된다."""

    def test_payload_carries_changes_highlight_and_truncation(self):
        result = call_tool("diff_changes", {"source": "개발함.", "revised": "개발하였습니다."})
        self.assertTrue(result["ok"])
        self.assertEqual(result["change_count"], len(result["changes"]))
        self.assertEqual(result["highlighted"], "<mark>개발하였습니다.</mark>")
        self.assertFalse(result["truncated"])
        # 스텝이 payload 에 그대로 실어 보내는 값이라 JSON 직렬화가 가능해야 한다
        self.assertEqual(set(result["changes"][0]), {"before", "after", "span"})

    def test_truncated_is_reported(self):
        """상한에 걸린 사실이 안 나가면 "뒷부분은 안 바뀌었다" 로 읽힌다."""
        source = "\n".join(f"{i}번 항목임." for i in range(10))
        revised = "\n".join(f"{i}번 항목입니다." for i in range(10))
        result = call_tool("diff_changes", {"source": source, "revised": revised, "max_items": 3})
        self.assertTrue(result["truncated"])
        self.assertEqual(result["change_count"], 3)

    def test_empty_string_max_items_falls_back_to_default(self):
        """GenOS 는 값이 없을 때 `None` 이 아니라 빈 문자열을 주입한다."""
        result = call_tool("diff_changes", {"source": "가", "revised": "나"})
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
