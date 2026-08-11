"""마크다운 구조 보존 번역 검증 — **onprem 번역 코드서빙을 직접 태운다.**

실행: `cd SFR-018 && python -m unittest discover -s tests -t .`

핵심 계약 두 가지:

1. **무손실**: 항등 번역에서 rebuild 결과가 입력과 **문자 단위로 동일**하다.
2. **구조 불변**: 번역 후에도 표 파이프 개수·구분 행·제목 마커·코드펜스가 원본과
   동일하다 (내용만 바뀐다).

두 계약이 중요한 이유는 요구사항 §5 다 — 표 구조가 깨지면 그 안의 수치가 어느 항목의
값인지 알 수 없게 된다. 그래서 **"표를 유지하라" 는 프롬프트 지시로 처리하지 않고**
코드가 스켈레톤을 들고 있다가 다시 끼운다.

## 사본에서 옮겨오며 바뀐 것 (2026-08-11)

옛 테스트는 `run_markdown_translation_job(..., translator_mode="mock"|"noop")` 을 썼다.
**onprem 에는 그 인자가 없다** — 배포 단위 안에 mock 경로를 두지 않는 규칙 때문이다.
그래서 모드 인자 대신 **번역 경계(`pipeline._run`)에 대역을 꽂는다.** 주입은 배포 단위
**바깥**인 이 파일에서만 하므로 운영 코드에는 테스트용 분기가 생기지 않는다
(`pdf_convert` 검증에서 쓰는 것과 같은 방식이다).

경계를 고른 것이지 함수를 고른 것이 아니다: `_run` 위쪽(`split_markdown` → 스켈레톤)과
아래쪽(`rebuild_markdown`)이 이 테스트가 지키려는 계약 전부이고, 그 사이가 LLM 이다.
"""

import asyncio
import re
import unittest

from . import onprem_path  # noqa: F401

onprem_path.install(onprem_path.TRANSLATION_UNIT)

from translation_pipeline.office import pipeline  # noqa: E402
from translation_pipeline.office.markdown_units import (  # noqa: E402
    rebuild_markdown,
    split_markdown,
)

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


class _FakeStats:
    """`MarkdownTranslationArtifacts` 가 응답으로 펴는 통계의 최소 대역."""

    def as_payload(self) -> dict:
        return {"unit_count": 0, "fallback_rate": 0.0}


def _install_translator(prefix: str):
    """번역 경계에 대역을 꽂는다. 원본을 돌려주므로 호출부가 되돌릴 수 있다.

    `prefix` 가 빈 문자열이면 **항등 번역**이다 — 무손실 계약을 재는 데 쓴다.
    """
    original = pipeline._run

    async def fake_run(units, options):
        translated = {u.translation_unit_id: prefix + u.text for u in units}
        return translated, "", _FakeStats(), [], {}

    pipeline._run = fake_run
    return original


class _TranslatorMixin(unittest.TestCase):
    def _translate(self, markdown: str, prefix: str = "[en] "):
        original = _install_translator(prefix)
        try:
            return asyncio.run(
                pipeline.run_markdown_translation_job(
                    markdown=markdown, target_lang="en", source_lang="ko"
                )
            )
        finally:
            pipeline._run = original


class SplitRebuildTest(unittest.TestCase):
    """LLM 경계를 지나지 않는 순수 구조 계약 — 대역조차 필요 없다."""

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
        """번역문에 줄바꿈이 섞여도 표 행이 갈라지지 않는다.

        LLM 출력은 통제할 수 없다. 줄바꿈 하나가 그대로 들어가면 그 행부터 표가 끝난다.
        """
        segments, units = split_markdown("| a한 |\n| --- |")
        broken = {units[0].translation_unit_id: "줄바꿈\n섞인 번역"}
        rebuilt = rebuild_markdown(segments, units, broken)
        self.assertEqual(rebuilt.split("\n")[0].count("|"), 2)  # 표 행 유지


class HtmlTableTest(unittest.TestCase):
    """지능형 전처리기의 한 줄 HTML 표 형식 커버 검증."""

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


class MarkdownJobTest(_TranslatorMixin):
    """잡 전체 — 번역 경계에 대역을 꽂고 스켈레톤 왕복을 확인한다."""

    def test_translation_preserves_structure(self):
        artifacts = self._translate(SAMPLE_MD)
        self.assertEqual(artifacts.translation_error, "")
        # 구조(파이프 수·마커)는 줄 단위로 원본과 완전히 동일해야 한다
        self.assertEqual(
            _structure_lines(artifacts.markdown), _structure_lines(SAMPLE_MD)
        )
        self.assertIn("[en] 플랫폼 구축", artifacts.markdown)
        self.assertIn("# [en] 사업 개요", artifacts.markdown)
        # 코드블록/숫자 셀은 그대로
        self.assertIn('print("코드는 번역하지 않는다")', artifacts.markdown)
        self.assertIn("| 1,200 |", artifacts.markdown)

    def test_identity_translation_returns_input_verbatim(self):
        """대역이 원문을 그대로 돌려주면 산출물도 원문과 **문자 단위로** 같아야 한다.

        여기서 어긋나면 스켈레톤 분해·재조립 자체가 손실을 내고 있다는 뜻이다.
        """
        artifacts = self._translate(SAMPLE_MD, prefix="")
        self.assertEqual(artifacts.markdown, SAMPLE_MD)

    def test_html_structure_preserved(self):
        artifacts = self._translate(INTELLIGENT_HTML_MD)
        tags = re.findall(r"<[^>]+>", artifacts.markdown)
        self.assertEqual(tags, re.findall(r"<[^>]+>", INTELLIGENT_HTML_MD))  # 태그열 동일
        self.assertIn('<th colspan="2">[en] 구분</th>', artifacts.markdown)  # 병합셀 보존
        self.assertIn("[en] 플랫폼 구축 &amp; 운영", artifacts.markdown)      # 재escape
        self.assertIn("<td>1,200</td>", artifacts.markdown)                  # 숫자 그대로
        self.assertIn("<!-- PB -->", artifacts.markdown)                     # 페이지 마커 보존

    def test_numbers_only_document_skips_llm(self):
        """번역할 텍스트가 없으면 **LLM 을 부르지 않는다.**

        숫자만 있는 표를 LLM 에 보내면 비용만 들고 값이 바뀔 위험만 생긴다.
        """
        source = "| 1 | 2 |\n| --- | --- |\n| 3 | 4 |"
        called = []

        original = pipeline._run

        async def tripwire(units, options):
            called.append(True)
            return {}, "", _FakeStats(), [], {}

        pipeline._run = tripwire
        try:
            artifacts = asyncio.run(
                pipeline.run_markdown_translation_job(
                    markdown=source, target_lang="en", source_lang="ko"
                )
            )
        finally:
            pipeline._run = original

        self.assertEqual(called, [])          # 경계에 아예 닿지 않았다
        self.assertEqual(artifacts.pairs, [])
        self.assertEqual(artifacts.markdown, source)


if __name__ == "__main__":
    unittest.main()
