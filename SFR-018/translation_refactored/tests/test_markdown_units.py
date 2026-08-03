"""마크다운 구조 보존 번역 검증.

핵심 계약 두 가지:
1. 무손실: noop 모드에서 rebuild 결과가 입력과 바이트 단위로 동일하다.
2. 구조 불변: mock 번역 후에도 표 파이프 개수·구분 행·제목 마커·코드펜스가
   원본과 동일하다 (내용만 바뀐다).

실행: cd translation_refactored && python -m unittest discover -s tests -t .
"""

import asyncio
import re
import unittest

from translation_pipeline.office.markdown_units import (
    rebuild_markdown,
    split_markdown,
)
from translation_pipeline.office.pipeline import run_markdown_translation_job

SAMPLE_MD = """# 사업 개요

생성형 AI 플랫폼 구축 사업의 추진 현황을 보고함.

| 항목 | 담당 부서 | 예산(백만원) |
| --- | :---: | ---: |
| 플랫폼 구축 | 정보전략팀 | 1,200 |
| 교육 및 확산 | 인재개발팀 | 300 |

- 1단계: 인프라 구축
- 2단계: 파일럿 운영
1. 착수 보고
2. 중간 점검

> 참고: 예산은 **잠정치**임.

```python
print("코드는 번역하지 않는다")
```

<table>
최종 검토 의견을 첨부함.
</table>
"""

# 지능형 전처리기 형식: 같은 줄 제목 접두 + 한 줄 HTML 표 (셀 escape, colspan)
INTELLIGENT_HTML_MD = (
    "사업 현황, 예산 개요, "
    '<table><tbody><tr><th colspan="2">구분</th><th>내용</th></tr>'
    "<tr><td>플랫폼 구축 &amp; 운영</td><td>정보전략팀</td><td>1,200</td></tr>"
    "<tr><td>교육</td><td>인재개발팀</td><td>300</td></tr></tbody></table>"
    "\n---\n[표 설명]\n예산 배분 현황을 정리한 표임.\n"
    "\n<!-- PB -->\n다음 페이지 내용임.\n"
)


def _structure_lines(md: str) -> list:
    """구조 비교용: 각 줄을 (파이프 수, 마커) 로 요약."""
    out = []
    for line in md.split("\n"):
        pipe_count = len(re.findall(r"(?<!\\)\|", line))
        marker = re.match(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|```|<)?", line).group(0)
        out.append((pipe_count, marker))
    return out


class SplitRebuildTest(unittest.TestCase):
    def test_noop_roundtrip_is_lossless(self):
        segments, units = split_markdown(SAMPLE_MD)
        identity = {u.translation_unit_id: u.text for u in units}
        self.assertEqual(rebuild_markdown(segments, units, identity), SAMPLE_MD)

    def test_code_block_and_numbers_not_translated(self):
        _, units = split_markdown(SAMPLE_MD)
        texts = [u.text for u in units]
        self.assertNotIn('print("코드는 번역하지 않는다")', texts)  # 코드펜스 내부
        self.assertNotIn("1,200", texts)  # 숫자만 있는 셀
        self.assertNotIn("<table>", texts)  # 태그 줄
        self.assertIn("플랫폼 구축", texts)  # 셀 내용은 유닛
        self.assertIn("사업 개요", texts)  # 제목 텍스트는 유닛

    def test_unit_element_types(self):
        _, units = split_markdown(SAMPLE_MD)
        types = {u.text: u.element_type for u in units}
        self.assertEqual(types["플랫폼 구축"], "table_cell")
        self.assertEqual(types["사업 개요"], "heading")
        self.assertEqual(types["1단계: 인프라 구축"], "list_item")
        self.assertEqual(types["참고: 예산은 **잠정치**임."], "blockquote")

    def test_translated_newline_normalized(self):
        segments, units = split_markdown("| a한 |\n| --- |")
        broken = {units[0].translation_unit_id: "줄바꿈\n섞인 번역"}
        rebuilt = rebuild_markdown(segments, units, broken)
        self.assertEqual(rebuilt.split("\n")[0].count("|"), 2)  # 표 행 유지


class HtmlTableTest(unittest.TestCase):
    """지능형 전처리기의 HTML 표 형식 커버 검증."""

    def test_noop_roundtrip_is_lossless(self):
        segments, units = split_markdown(INTELLIGENT_HTML_MD)
        identity = {u.translation_unit_id: u.text for u in units}
        self.assertEqual(
            rebuild_markdown(segments, units, identity), INTELLIGENT_HTML_MD
        )

    def test_tags_are_literal_and_cells_are_units(self):
        _, units = split_markdown(INTELLIGENT_HTML_MD)
        texts = [u.text for u in units]
        self.assertIn("구분", texts)                      # th 텍스트
        self.assertIn("플랫폼 구축 & 운영", texts)         # 엔티티 unescape 상태로 유닛화
        self.assertIn("사업 현황, 예산 개요,", texts)      # 같은 줄 접두 텍스트
        self.assertIn("예산 배분 현황을 정리한 표임.", texts)  # [표 설명] 본문
        self.assertNotIn("1,200", texts)                  # 숫자 셀은 유닛 아님
        for text in texts:
            self.assertNotIn("<", text)                   # 태그가 유닛에 새지 않음
            self.assertNotIn("&amp;", text)               # 엔티티가 유닛에 새지 않음

    def test_mock_translation_preserves_html_structure(self):
        artifacts = asyncio.run(
            run_markdown_translation_job(
                markdown=INTELLIGENT_HTML_MD, target_lang="en", translator_mode="mock"
            )
        )
        tags = re.findall(r"<[^>]+>", artifacts.markdown)
        self.assertEqual(tags, re.findall(r"<[^>]+>", INTELLIGENT_HTML_MD))  # 태그열 동일
        self.assertIn('<th colspan="2">[en] 구분</th>', artifacts.markdown)  # 병합셀 보존
        self.assertIn("[en] 플랫폼 구축 &amp; 운영", artifacts.markdown)      # 재escape
        self.assertIn("<td>1,200</td>", artifacts.markdown)                  # 숫자 그대로
        self.assertIn("<!-- PB -->", artifacts.markdown)                     # 페이지 마커 보존

    def test_multiline_pretty_html_table(self):
        pretty = "<table>\n  <tr>\n    <td>내용 항목</td>\n  </tr>\n</table>"
        segments, units = split_markdown(pretty)
        identity = {u.translation_unit_id: u.text for u in units}
        self.assertEqual(rebuild_markdown(segments, units, identity), pretty)
        self.assertEqual([u.text for u in units], ["내용 항목"])

    def test_mixed_markdown_and_html_tables(self):
        mixed = SAMPLE_MD + "\n" + INTELLIGENT_HTML_MD
        segments, units = split_markdown(mixed)
        identity = {u.translation_unit_id: u.text for u in units}
        self.assertEqual(rebuild_markdown(segments, units, identity), mixed)


class MarkdownJobTest(unittest.TestCase):
    def test_mock_translation_preserves_structure(self):
        artifacts = asyncio.run(
            run_markdown_translation_job(
                markdown=SAMPLE_MD, target_lang="en", translator_mode="mock"
            )
        )
        self.assertEqual(artifacts.translation_error, "")
        # 구조(파이프 수·마커)는 줄 단위로 원본과 완전히 동일해야 한다
        self.assertEqual(
            _structure_lines(artifacts.markdown), _structure_lines(SAMPLE_MD)
        )
        # 내용은 번역됨 (mock: "[en] " 접두)
        self.assertIn("[en] 플랫폼 구축", artifacts.markdown)
        self.assertIn("# [en] 사업 개요", artifacts.markdown)
        # 코드블록/숫자 셀은 그대로
        self.assertIn('print("코드는 번역하지 않는다")', artifacts.markdown)
        self.assertIn("| 1,200 |", artifacts.markdown)

    def test_noop_returns_input_verbatim(self):
        artifacts = asyncio.run(
            run_markdown_translation_job(
                markdown=SAMPLE_MD, target_lang="en", translator_mode="noop"
            )
        )
        self.assertEqual(artifacts.markdown, SAMPLE_MD)

    def test_numbers_only_document(self):
        artifacts = asyncio.run(
            run_markdown_translation_job(
                markdown="| 1 | 2 |\n| --- | --- |\n| 3 | 4 |",
                target_lang="en",
                translator_mode="mock",
            )
        )
        self.assertEqual(artifacts.pairs, [])  # 유닛 없음 → LLM 호출 없음
        self.assertEqual(artifacts.markdown, "| 1 | 2 |\n| --- | --- |\n| 3 | 4 |")


if __name__ == "__main__":
    unittest.main()
