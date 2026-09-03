"""hwpx 표 → LLM 입력 형식. 병합·중첩이 있으면 HTML, 없으면 마크다운.

실행: `cd SFR-018 && python -m unittest discover -s tests -t .`

## 왜 형식이 갈리나

**마크다운 표에는 병합 문법이 없다.** `rowspan`/`colspan` 을 마크다운으로 내면 그 자리가
빈 칸이 되고, LLM 은 "머리글이 없는 열" 로 읽는다. 중첩 표는 아예 한 덩어리 텍스트로
뭉개진다 — 실제 출력이 이랬다:

```
| 구분 | 2025년 실적 |   | 비고 |   ← colspan 사라짐 → 3열이 빈칸
|   | 상반기 | 하반기 | - |        ← rowspan 사라짐 → 1열이 빈칸
| 세부 | 소분류<br>값 |   |   |     ← 중첩표가 텍스트로 뭉개짐
```

**수치는 남는데 그 수치가 무엇의 값인지가 사라진다.** 요구사항 §5 가 걱정한 "표 깨짐" 이
이것이고, 마크다운을 아무리 잘 만들어도 못 고친다 — 형식의 한계다.

## 이 파일이 지키는 계약

1. **손실이 없으면 형식을 바꾸지 않는다.** 단순한 표는 마크다운 그대로. 토큰이 적고
   사람이 읽기도 낫다.
2. **병합·중첩은 HTML 로 보존한다.**
3. **번역 스켈레톤을 무손실로 통과한다.** 이게 제일 중요하다 — 새 형식을 만든 것이
   아니라 **지능형 전처리기가 이미 내는 형식**(한 줄 HTML 표)에 맞춘 것이라,
   `markdown_units` 의 기존 HTML 경로가 그대로 받는다.
4. **숫자 셀은 번역 단위가 되지 않는다.** LLM 에 보내지 않으므로 값이 바뀔 수 없다.
"""

import io
import re
import unittest
import zipfile

from . import onprem_path  # noqa: F401

onprem_path.install(onprem_path.TRANSLATION_UNIT)

from translation_pipeline.office.hwpx_text import to_markdown  # noqa: E402
from translation_pipeline.office.markdown_units import (  # noqa: E402
    rebuild_markdown,
    split_markdown,
)

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"


def _para(text: str) -> str:
    return f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"


def _cell(row: int, col: int, body: str, *, row_span: int = 1, col_span: int = 1) -> str:
    return (
        f'<hp:tc><hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
        f'<hp:cellSpan colSpan="{col_span}" rowSpan="{row_span}"/>'
        f"<hp:subList>{body}</hp:subList></hp:tc>"
    )


def _pack(body: str) -> bytes:
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<hs:sec xmlns:hp="{HP}" xmlns:hs="{HS}">{body}</hs:sec>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("Contents/section0.xml", section.encode("utf-8"))
    return buf.getvalue()


def simple_table_hwpx() -> bytes:
    """병합도 중첩도 없는 표 — 마크다운으로 손실 없이 표현된다."""
    rows = (
        f'<hp:tr>{_cell(0, 0, _para("항목"))}{_cell(0, 1, _para("값"))}</hp:tr>'
        f'<hp:tr>{_cell(1, 0, _para("예산"))}{_cell(1, 1, _para("1,200"))}</hp:tr>'
    )
    return _pack(f"<hp:p><hp:run><hp:tbl>{rows}</hp:tbl></hp:run></hp:p>")


def merged_table_hwpx() -> bytes:
    """현장 표에서 흔한 것을 한 표에 담는다 — 세로 병합·가로 병합·중첩·다문단 셀."""
    inner = (
        "<hp:p><hp:run><hp:tbl>"
        f'<hp:tr>{_cell(0, 0, _para("소분류"))}{_cell(0, 1, _para("값 &amp; 비율"))}</hp:tr>'
        "</hp:tbl></hp:run></hp:p>"
    )
    rows = (
        "<hp:tr>"
        + _cell(0, 0, _para("구분"), row_span=2)
        + _cell(0, 1, _para("2025년 실적"), col_span=2)
        + _cell(0, 3, _para("비고"))
        + "</hp:tr>"
        "<hp:tr>"
        + _cell(1, 1, _para("상반기"))
        + _cell(1, 2, _para("하반기"))
        + _cell(1, 3, _para("-"))
        + "</hp:tr>"
        "<hp:tr>"
        + _cell(2, 0, _para("예산"))
        + _cell(2, 1, _para("1,200"))
        + _cell(2, 2, _para("3,400"))
        + _cell(2, 3, _para("단위: 백만원") + _para("증액 반영"))
        + "</hp:tr>"
        "<hp:tr>"
        + _cell(3, 0, _para("세부"))
        + _cell(3, 1, inner, col_span=3)
        + "</hp:tr>"
    )
    return _pack(
        '<hp:p><hp:run><hp:t>예산 현황</hp:t></hp:run></hp:p>'
        f"<hp:p><hp:run><hp:tbl>{rows}</hp:tbl></hp:run></hp:p>"
    )


class FormatChoiceTest(unittest.TestCase):
    def test_simple_table_stays_markdown(self):
        """손실이 없으면 형식을 바꾸지 않는다 — 토큰도 적고 사람이 읽기도 낫다."""
        markdown = to_markdown(simple_table_hwpx()).markdown
        self.assertNotIn("<table", markdown)
        self.assertIn("| 항목 | 값 |", markdown)
        self.assertIn("1,200", markdown)

    def test_merged_table_becomes_html(self):
        markdown = to_markdown(merged_table_hwpx()).markdown
        self.assertIn("<table><tbody>", markdown)

    def test_spans_are_preserved(self):
        """마크다운에서는 빈 칸이 되던 것들."""
        markdown = to_markdown(merged_table_hwpx()).markdown
        self.assertIn('rowspan="2"', markdown)   # 구분 — 두 행에 걸친다
        self.assertIn('colspan="2"', markdown)   # 2025년 실적 — 상반기·하반기를 덮는다

    def test_nested_table_stays_a_table(self):
        """마크다운에서는 `소분류<br>값` 한 덩어리가 됐다."""
        markdown = to_markdown(merged_table_hwpx()).markdown
        self.assertGreaterEqual(markdown.count("<table><tbody>"), 2)
        self.assertIn("<td>소분류</td>", markdown)

    def test_covered_positions_get_no_cell(self):
        """병합으로 덮인 자리에 `<td>` 를 내면 그 행만 열이 하나 늘어난다."""
        markdown = to_markdown(merged_table_hwpx()).markdown
        rows = [line for line in markdown.splitlines() if line.startswith("<tr>")]

        def top_level(row: str) -> int:
            stripped = row
            while True:
                reduced = re.sub(r"<table\b[^>]*>.*?</table\s*>", "", stripped, flags=re.DOTALL)
                if reduced == stripped:
                    return stripped.count("<td")
                stripped = reduced

        # 4열 표: 1행 3개(colspan=2 포함), 2행 3개(rowspan 에 덮임), 3행 4개, 4행 2개
        self.assertEqual([top_level(row) for row in rows], [3, 3, 4, 2])

    def test_multi_paragraph_cell_joined(self):
        markdown = to_markdown(merged_table_hwpx()).markdown
        self.assertIn("단위: 백만원<br>증액 반영", markdown)


class TranslationRoundTripTest(unittest.TestCase):
    """번역 스켈레톤을 무손실로 통과하는가 — 이 변경의 가장 큰 위험 지점."""

    def test_lossless_roundtrip(self):
        markdown = to_markdown(merged_table_hwpx()).markdown
        segments, units = split_markdown(markdown)
        identity = {u.translation_unit_id: u.text for u in units}
        self.assertEqual(rebuild_markdown(segments, units, identity), markdown)

    def test_structure_survives_translation(self):
        markdown = to_markdown(merged_table_hwpx()).markdown
        segments, units = split_markdown(markdown)
        translated = {u.translation_unit_id: "[en] " + u.text for u in units}
        out = rebuild_markdown(segments, units, translated)
        # 태그열이 그대로여야 구조가 보존된 것이다
        self.assertEqual(re.findall(r"<[^>]+>", out), re.findall(r"<[^>]+>", markdown))
        self.assertIn('<td rowspan="2">[en] 구분</td>', out)

    def test_numeric_cells_are_not_translation_units(self):
        """숫자 셀은 LLM 에 보내지 않는다 — 보내지 않으면 바뀔 수 없다."""
        markdown = to_markdown(merged_table_hwpx()).markdown
        _segments, units = split_markdown(markdown)
        texts = [u.text for u in units]
        self.assertNotIn("1,200", texts)
        self.assertNotIn("3,400", texts)
        self.assertIn("구분", texts)

    def test_entities_reach_llm_unescaped_and_return_escaped(self):
        """셀 안 `&` 는 LLM 에 `&` 로 가고 문서에는 `&amp;` 로 돌아온다."""
        markdown = to_markdown(merged_table_hwpx()).markdown
        segments, units = split_markdown(markdown)
        self.assertIn("값 & 비율", [u.text for u in units])
        identity = {u.translation_unit_id: u.text for u in units}
        self.assertIn("&amp;", rebuild_markdown(segments, units, identity))


if __name__ == "__main__":
    unittest.main()
