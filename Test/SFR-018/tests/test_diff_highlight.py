"""글다듬이 변경 하이라이트 — 낱말 단위 판정과 좌표 (2026-08-27 추가).

실행: `cd SFR-018 && python -m unittest discover -s tests -t .`

**MCP 도구 파일(`onprem/mcp/genon_text_guard.py`)을 태운다.**

## 이 파일이 지키는 계약

변경 표시는 **답변 아래 목록이 아니라 본문 위 하이라이트**다. 그러려면 두 가지가
성립해야 하고, 둘 다 여기서 지킨다:

1. **낱말 단위** — 문장 쌍은 "이 문장이 바뀌었다" 까지만 말한다. 어느 낱말을
   손질했는지가 요구였다.
2. **양쪽 기준 좌표(`source_span`·`target_span`)** — 좌표가 없으면 프론트는 `after` 문자열을 본문에서
   다시 찾아야 하고, 같은 낱말이 두 번 나오면 어느 쪽을 칠할지 결정할 수 없다.
   **좌표 없이는 인라인 하이라이트가 성립하지 않는다.**

그리고 하이라이트는 **정본을 손대지 않는다** — `POST /download` 가 정본을 그대로
파일로 만들기 때문에, 태그가 정본에 섞이면 사용자가 메모장에서 지워야 한다.
"""

import unittest

from . import final_path  # noqa: F401

_guard = final_path.load_mcp(final_path.TEXT_GUARD_MCP)
build_change_list = _guard.tgbuild_change_list
build_highlighted = _guard.tgbuild_highlighted
call_tool = _guard.tgcall_tool
_split_units = _guard._TGsplit_units_with_spans


def _aligned(source: str, revised: str) -> bool:
    """`i↔i` 로 봐도 되는가 — 판정을 도구에서 직접 가져온다(사본을 적지 않는다)."""
    return _guard._TGaligned(_split_units(source), _split_units(revised))


class SpanTest(unittest.TestCase):
    """좌표가 그 텍스트에서 **실제로 그 낱말을 가리키는가**."""

    def test_span_points_at_the_changed_word(self):
        source = "본 사업은 2026년에 개발함."
        revised = "본 사업은 2026년에 개발하였습니다."
        changes = build_change_list(source, revised)
        self.assertEqual(len(changes), 1)
        start, end = changes[0]["target_span"]
        # 좌표가 가리키는 글자가 곧 `after` 다. 이 등식이 하이라이트의 전부다.
        self.assertEqual(revised[start:end], changes[0]["after"])
        self.assertEqual(changes[0]["after"], "개발하였습니다.")
        self.assertEqual(changes[0]["before"], "개발함.")

    def test_only_the_changed_word_is_marked_not_the_whole_sentence(self):
        """문장 단위로 냈다면 좌표가 문장 전체를 덮는다 — 그러면 표시가 묻힌다."""
        source = "담당자가 자료를 검토함."
        revised = "담당자가 자료를 검토하였습니다."
        changes = build_change_list(source, revised)
        start, end = changes[0]["target_span"]
        self.assertNotIn("담당자가", revised[start:end])
        self.assertNotIn("자료를", revised[start:end])

    def test_repeated_word_gets_its_own_span(self):
        """같은 낱말이 두 번 나오는 경우 — 문자열 검색으로는 가릴 수 없는 자리다."""
        source = "검토함. 다시 검토함."
        revised = "검토함. 다시 검토하였습니다."
        changes = build_change_list(source, revised)
        self.assertEqual(len(changes), 1)
        start, end = changes[0]["target_span"]
        # 앞쪽 `검토함.` 이 아니라 **뒤쪽**이 바뀐 것이다
        self.assertGreater(start, revised.index("검토함."))
        self.assertEqual(revised[start:end], "검토하였습니다.")

    def test_deletion_has_source_span_only(self):
        """되쓴 글에 칠할 글자가 없다. 0 을 넣으면 문서 맨 앞이 칠해진다.

        **원문에는 자리가 있다** (2026-08-28) — 좌우 비교에서 지워진 낱말을 왼쪽에
        보여주는 것이 절반이다. 원문 좌표까지 `None` 이면 삭제는 영영 안 보인다.
        """
        source = "불필요한 문장이다. 남는 문장이다."
        revised = "남는 문장이다."
        changes = build_change_list(source, revised)
        deletions = [c for c in changes if not c["after"]]
        self.assertTrue(deletions)
        for item in deletions:
            self.assertIsNone(item["target_span"])
            start, end = item["source_span"]
            self.assertEqual(source[start:end], "불필요한 문장이다.")

    def test_insertion_gets_a_span(self):
        """새로 들어온 낱말은 **되쓴 글에만** 자리가 있다."""
        source = "남는 문장이다."
        revised = "새 문장이다. 남는 문장이다."
        changes = build_change_list(source, revised)
        self.assertIsNone(changes[0]["source_span"])
        start, end = changes[0]["target_span"]
        self.assertEqual(revised[start:end], "새 문장이다.")

    def test_replacement_has_both_spans(self):
        """치환은 양쪽에 자리가 있다 — 좌우 비교의 기본 경우다."""
        source = "지난 분기 실적을 검토함."
        revised = "지난 분기 실적을 검토하였습니다."
        changes = build_change_list(source, revised)
        item = changes[0]
        s_start, s_end = item["source_span"]
        t_start, t_end = item["target_span"]
        self.assertEqual(source[s_start:s_end], "검토함.")
        self.assertEqual(revised[t_start:t_end], "검토하였습니다.")

    def test_no_cap_on_change_count(self):
        """건수 상한을 두면 잘린 목록으로 사본을 만들어 뒤쪽이 안 칠해진다.

        옛 기본값이 50 이라 그보다 많은 변경으로 본다 — 30건짜리 픽스처는 상한이
        되살아나도 통과한다.
        """
        source = "\n".join(f"{i}번 항목임." for i in range(80))
        revised = "\n".join(f"{i}번 항목입니다." for i in range(80))
        changes = build_change_list(source, revised)
        self.assertEqual(len(changes), 80)
        # 마지막 변경의 좌표가 실제로 그 낱말을 가리켜야 끝까지 칠할 수 있다
        start, end = changes[-1]["target_span"]
        self.assertEqual(revised[start:end], "항목입니다.")
        self.assertTrue(revised[:start].endswith("79번 "), revised[start - 8:end])

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

        공백으로만 낱말을 끊으면 이 줄이 통째로 낱말 하나가 되고, 그 좌표는 태그에
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
        changes = [{"before": "x", "after": "y", "target_span": [4, 12]},
                   {"before": "x", "after": "y", "target_span": [4, 20]}]
        marked = build_highlighted(text, changes)
        self.assertEqual(marked, "The <mark>merchant invoice</mark> ok")
        self.assertEqual(marked.count("<mark>"), 1)

    def test_out_of_range_and_malformed_spans_are_ignored(self):
        """프론트가 준 값이 아니라 우리 계산이지만, 좌표가 어긋나면 본문이 깨진다."""
        text = "짧은 글"
        for span in ([0, 999], [5, 2], ["a", "b"], [1], None, [-1, 2]):
            marked = build_highlighted(text, [{"before": "x", "after": "y", "target_span": span}])
            self.assertEqual(marked, text, f"span={span!r}")


class ToolContractTest(unittest.TestCase):
    """`diff_changes` 응답이 스텝이 읽는 모양인가 — 키가 어긋나면 조용히 빈 값이 된다."""

    def test_payload_carries_changes_and_highlight(self):
        result = call_tool("diff_changes", {"source": "개발함.", "revised": "개발하였습니다."})
        self.assertTrue(result["ok"])
        self.assertEqual(result["change_count"], len(result["changes"]))
        self.assertEqual(result["highlighted"], "<mark>개발하였습니다.</mark>")
        # 스텝이 payload 에 그대로 실어 보내는 값이라 JSON 직렬화가 가능해야 한다
        self.assertEqual(set(result["changes"][0]),
                         {"before", "after", "source_span", "target_span"})

    def test_both_sides_are_highlighted(self):
        """화면이 원문과 되쓴 글을 좌우로 놓고 비교한다 — 양쪽 다 사본이 온다."""
        source = "불필요한 수식어를 넣어서 개발함."
        revised = "개발하였습니다."
        result = call_tool("diff_changes", {"source": source, "revised": revised})
        self.assertIn("<mark>", result["source_highlighted"])
        self.assertIn("<mark>", result["highlighted"])
        # 태그를 떼면 정본으로 돌아온다 — 사본이 본문을 건드리지 않았다는 뜻이다
        strip = lambda t: t.replace("<mark>", "").replace("</mark>", "")
        self.assertEqual(strip(result["source_highlighted"]), source)
        self.assertEqual(strip(result["highlighted"]), revised)

    def test_deleted_words_are_visible_on_the_source_side(self):
        """삭제는 되쓴 글에 자리가 없다. 원문 사본이 없으면 영영 안 보인다."""
        source = "불필요한 문장이다. 남는 문장이다."
        revised = "남는 문장이다."
        result = call_tool("diff_changes", {"source": source, "revised": revised})
        self.assertIn("<mark>불필요한 문장이다.</mark>", result["source_highlighted"])
        self.assertNotIn("<mark>", result["highlighted"])

    def test_no_truncated_field(self):
        """상한이 없어져 언제나 false 인 필드다 — 읽는 쪽이 확인했다고 믿게 된다."""
        result = call_tool("diff_changes", {"source": "개발함.", "revised": "개발하였습니다."})
        self.assertNotIn("truncated", result)

    def test_all_changes_are_highlighted(self):
        """옛 상한(50)을 넘는 변경도 끝까지 칠해야 한다."""
        source = "\n".join(f"{i}번 항목임." for i in range(80))
        revised = "\n".join(f"{i}번 항목입니다." for i in range(80))
        result = call_tool("diff_changes", {"source": source, "revised": revised})
        self.assertEqual(result["change_count"], 80)
        self.assertTrue(result["highlighted"].endswith("79번 <mark>항목입니다.</mark>"))

    def test_empty_string_injection(self):
        """GenOS 는 값이 없을 때 `None` 이 아니라 빈 문자열을 주입한다."""
        result = call_tool("diff_changes", {"source": "", "revised": ""})
        self.assertTrue(result["ok"])



class SentenceAlignmentTest(unittest.TestCase):
    """**문장 1:1 정렬** — 프롬프트가 요청하고 코드가 검증한다 (2026-09-15).

    글다듬이 시스템 프롬프트가 "문장을 합치거나 나누거나 새로 만들지 않는다" 를 요구한다.
    지켜지면 원문 i 번째와 되쓴 글 i 번째가 짝이고, 그때는 문장 레벨 `difflib` 을 아예
    돌리지 않는다 — **짝이 이미 정해져 있어 이동·밀림이 원천적으로 불가능**하다.

    **프롬프트를 보장으로 보지 않는다**(§5)는 것이 이 묶음의 요점이다. 지시를 어긴
    출력에서도 안전해야 하므로, 정렬이 안 서는 갈래(수가 다름·순서가 바뀜)가 **예전
    경로로 되돌아가는지**를 함께 지킨다.
    """

    def test_one_to_one_keeps_changes_inside_each_sentence(self):
        """1:1 이면 낱말 짝이 **문장 경계를 넘지 않는다.**

        이것이 이 경로를 만든 이유다. 문장 레벨 diff 가 여러 문장을 한 덩어리
        `replace` 로 묶으면 그 안의 낱말 LCS 가 경계를 넘어 `("임. 자료", "입니다.")`
        처럼 **두 문장에 걸친 항목**을 만들고, 그 구간을 칠하면 형광이 줄바꿈을 넘어간다.

        **폴백이 실제로 경계를 넘는 입력이라야 이 판정이 산다.** 손으로 지은 짧은
        예제로는 두 경로가 같은 답을 내서 1:1 을 통째로 꺼도 통과한다 — 실측으로
        확인하고 이 픽스처로 바꿨다(무작위 대조에서 9% 가 이런 입력이다).
        """
        source = (
            "검토 관련 회신 홍길동 담당자 함.\n담당자 홍길동 관련 임.\n"
            "자료 승인 임.\n2025년 사업 담당자 회신 바람."
        )
        revised = (
            "검토 관련 회신 관련 담당자 하였습니다.\n담당자 홍길동 관련 입니다.\n"
            "승인 승인 하였습니다.\n담당자 사업 담당자 회신 부탁드립니다."
        )
        self.assertTrue(_aligned(source, revised))
        for item in build_change_list(source, revised):
            for text, key in ((source, "source_span"), (revised, "target_span")):
                span = item[key]
                if span:
                    self.assertNotIn("\n", text[span[0]:span[1]])

    def test_spans_point_at_the_word(self):
        """좌표 등식 — 1:1 경로에서도 `revised[start:end] == after` 다."""
        source = "가격은 1000원임.\n수량은 20개임."
        revised = "가격은 1000원입니다.\n수량은 20개입니다."
        self.assertTrue(_aligned(source, revised))
        for item in build_change_list(source, revised):
            if item["target_span"]:
                start, end = item["target_span"]
                self.assertEqual(revised[start:end], item["after"])
            if item["source_span"]:
                start, end = item["source_span"]
                self.assertEqual(source[start:end], item["before"])

    def test_inserted_sentence_falls_back(self):
        """문장을 새로 만들면 **수가 달라져** 1:1 이 서지 않는다 → 예전 경로.

        되돌아간 뒤에도 삽입은 한 건으로 잡혀야 한다 — `difflib` 은 LCS 라 뒤가 밀리지
        않는다(뒤가 밀리는 것은 이 도구가 애초에 겪지 않는 문제다).
        """
        source = "본 사업은 2025년에 개발함.\n담당자는 홍길동임."
        revised = "귀사의 발전을 기원합니다.\n본 사업은 2025년에 개발함.\n담당자는 홍길동임."
        self.assertFalse(_aligned(source, revised))
        changes = build_change_list(source, revised)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["before"], "")
        self.assertIsNone(changes[0]["source_span"])

    def test_reordered_sentences_fall_back(self):
        """**수는 같은데 순서가 바뀐** 경우 — 유사도 가드가 없으면 못 잡는다.

        이 가드가 빠지면 `i↔i` 가 **엉뚱한 문장끼리** 짝을 짓고, 그 결과는 오류가
        아니라 **문서 전체가 형광인 화면**으로만 드러난다.
        """
        source = "본 사업은 2025년에 개발함.\n담당자는 홍길동임.\n검토 후 회신 바람."
        revised = "담당자는 홍길동임.\n검토 후 회신 바람.\n본 사업은 2025년에 개발함."
        self.assertFalse(_aligned(source, revised))

    def test_one_heavy_rewrite_still_aligns(self):
        """짝 하나가 크게 바뀌어도 정렬은 선다 — `max(1, …)` 이 그 한 칸을 봐준다.

        비율만 쓰면 다섯 문장 미만 문서에서 허용치가 1 밑으로 떨어져 **무관용**이 되고,
        한 문장만 크게 다시 써도 문서 전체가 폴백한다. 짧은 글이 흔한 기능이라 그러면
        1:1 경로가 거의 안 탄다.
        """
        source = "제목은 사업계획임.\n담당자는 홍길동임.\n일정은 2025년임."
        revised = (
            "제목은 전사 차원의 중장기 발전 로드맵 수립 계획입니다.\n"
            "담당자는 홍길동입니다.\n일정은 2025년입니다."
        )
        self.assertTrue(_aligned(source, revised))

    def test_untouched_sentences_produce_no_change(self):
        """1:1 이어도 **안 바뀐 문장은 항목을 만들지 않는다.**"""
        source = "제목은 그대로다.\n본문은 개발함."
        revised = "제목은 그대로다.\n본문은 개발하였습니다."
        changes = build_change_list(source, revised)
        self.assertEqual(len(changes), 1)
        self.assertNotIn("제목", changes[0]["before"])

    def test_structure_lines_are_one_unit(self):
        """표·제목 줄은 통째로 한 단위라 1:1 을 깨뜨리지 않는다."""
        source = "# 제목\n| 구분 | 값 |\n내용은 개발함."
        revised = "# 제목\n| 구분 | 값 |\n내용은 개발하였습니다."
        self.assertTrue(_aligned(source, revised))
        self.assertEqual(len(build_change_list(source, revised)), 1)


class HeavyRewriteCollapseTest(unittest.TestCase):
    """**크게 다시 쓰인 자리는 통째로 한 항목** (2026-09-15).

    낱말로 잘게 쪼개는 것은 "어느 낱말을 손질했나" 를 보여주려는 것인데, 문장이 크게
    다시 쓰이면 조사·흔한 낱말만 `equal` 로 남고 나머지가 흩어져 **형광이 누더기**가
    된다 — 문장 전체를 칠한 것보다 어느 낱말을 고쳤는지가 오히려 묻힌다.
    """

    def test_heavy_rewrite_is_one_item(self):
        """**공통 낱말이 흩어진** 재작성이라야 이 판정이 산다.

        공통 낱말이 앞에 몰려 있으면 낱말 diff 가 어차피 한 덩어리를 내서, 접기를
        통째로 꺼도 통과한다 — 실측으로 확인하고 이 픽스처로 바꿨다.
        """
        source = "본 사업 및 과제 등 계획 관련 내용임."
        revised = "본 계획 및 업무 등 방침 세부 사항입니다."
        self.assertEqual(len(build_change_list(source, revised)), 1)

    def test_light_rewrite_stays_word_level(self):
        """조금 고친 문장은 **접지 않는다** — 접으면 이 도구의 목적이 사라진다."""
        source = "본 사업은 2025년에 개발함.\n담당자는 홍길동임."
        revised = "본 사업은 2025년에 개발하였습니다.\n담당자는 홍길동입니다."
        changes = build_change_list(source, revised)
        self.assertEqual(len(changes), 2)
        for item in changes:
            self.assertNotIn("2025년", item["after"])

    def test_collapsed_span_still_points_at_the_text(self):
        """접어도 좌표 등식은 그대로다 — 하이라이트의 전부가 그 등식이다."""
        source = "본 사업 및 과제 등 계획 관련 내용임."
        revised = "본 계획 및 업무 등 방침 세부 사항입니다."
        for item in build_change_list(source, revised):
            start, end = item["target_span"]
            self.assertEqual(revised[start:end], item["after"])


if __name__ == "__main__":
    unittest.main()
