"""번역 유닛에 **절 제목을 문맥으로** 달아 프롬프트에 싣는다 (2026-08-29).

## 왜 필요한가

구조 보존을 스켈레톤 분해로 하는 대가다 — 표 파이프·제목 마커·목록 기호는 코드가 쥐고
**LLM 에는 셀·문장 텍스트만** 들어간다. 그래서 표 셀 하나짜리 유닛(`대상`·`금액`·
`해당 없음`)은 그것이 무엇에 관한 값인지 알 방법이 없고, 주어가 생략된 한국어 문장은
더 그렇다. 절 제목 한 줄이 그 대부분을 메운다.

`TranslationUnit.context_scope` 필드는 **원래부터 있었다** — 노드 경로에서만 채워지고
(`units.py` 가 `node["scope"]` 를 읽는다) 프롬프트는 그 값을 한 번도 쓰지 않았다.
계산해 놓고 안 쓰던 값이다.

## 여기서 보는 것

1. 마크다운 분해가 제목을 따라가며 문맥을 다는가 (제목 **자신**에게는 달지 않는다).
2. 그 문맥이 배치 프롬프트 JSON 에 실리는가 — **없으면 키 자체가 없어야 한다.**
3. 단건 폴백에도 실리는가. 폴백에만 빠뜨리면 배치가 실패한 유닛들만 문맥 없이
   번역되고, 그 차이는 배치가 실패했을 때만 드러난다.
"""

import json
import unittest

from . import onprem_path

onprem_path.install(onprem_path.TRANSLATION_UNIT)

from translation_pipeline.common.prompt_builder import (  # noqa: E402
    PromptContext,
    build_batch_prompts,
    build_single_prompts,
)
from translation_pipeline.office.markdown_units import split_markdown  # noqa: E402

_DOC = """# 연차 휴가

신청은 결재 상신으로 한다.

## 정산 기준

| 구분 | 금액 |
|---|---|
| 국내 | 5만원 |
"""

_CONTEXT = PromptContext(
    source_label="Korean",
    target_label="English",
    register_label="written",
    register_instruction="Use formal written style.",
)


def _unit_by_text(units: list, text: str):
    for unit in units:
        if unit.text == text:
            return unit
    raise AssertionError(f"유닛을 찾지 못했다: {text!r}")


class SectionScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        _, self.units = split_markdown(_DOC)

    def test_paragraph_carries_its_section(self):
        """문단은 자기 위 제목을 문맥으로 갖는다."""
        unit = _unit_by_text(self.units, "신청은 결재 상신으로 한다.")
        self.assertEqual(unit.context_scope, "연차 휴가")

    def test_table_cell_carries_its_section(self):
        """**표 셀이 이 기능의 이유다** — 셀 하나만 보면 무엇의 값인지 알 수 없다."""
        unit = _unit_by_text(self.units, "국내")
        self.assertEqual(unit.context_scope, "정산 기준")

    def test_heading_itself_has_no_scope(self):
        """제목 자신에게는 문맥을 달지 않는다 — 자기가 그 문맥이다."""
        unit = _unit_by_text(self.units, "정산 기준")
        self.assertEqual(unit.context_scope, "")

    def test_scope_switches_at_the_next_heading(self):
        """제목을 지나면 문맥이 바뀐다 (첫 절 문맥이 문서 끝까지 따라가지 않는다)."""
        first = _unit_by_text(self.units, "신청은 결재 상신으로 한다.")
        later = _unit_by_text(self.units, "금액")
        self.assertNotEqual(first.context_scope, later.context_scope)

    def test_document_without_heading_has_no_scope(self):
        """제목이 없으면 빈 문자열이다 — 지어내지 않는다."""
        _, units = split_markdown("제목 없는 문서입니다.\n")
        self.assertEqual(units[0].context_scope, "")


class BatchPromptContextTest(unittest.TestCase):
    def _items(self, batch: list) -> list:
        _system, user = build_batch_prompts(_CONTEXT, batch, [])
        return json.loads(user.strip())

    def test_scope_is_sent_as_c(self):
        """문맥이 배치 항목에 실린다 — 안 실리면 이 기능 전체가 없는 것과 같다."""
        items = self._items([(0, "국내", "정산 기준")])
        self.assertEqual(items[0]["c"], "정산 기준")
        self.assertEqual(items[0]["s"], "국내")

    def test_missing_scope_omits_the_key(self):
        """문맥이 없으면 **키 자체가 없다.**

        빈 문자열을 실으면 모델이 그것도 번역해야 할 무엇으로 읽을 여지가 생기고
        토큰만 는다.
        """
        items = self._items([(0, "제목 없는 문장", "")])
        self.assertNotIn("c", items[0])

    def test_output_schema_is_unchanged(self):
        """시스템 프롬프트가 `c` 를 **번역·출력 대상에서 뺀다**고 못박는가.

        이 지시가 없으면 모델이 문맥을 번역문에 섞어 넣고, 그 결과는 형식상 정상
        응답으로 내려간다 — 구조는 코드가 지키므로 오류로도 안 드러난다.
        """
        system, _user = build_batch_prompts(_CONTEXT, [(0, "국내", "정산 기준")], [])
        self.assertIn('[{"id": <int>, "t": "<translated text>"}, ...]', system)
        self.assertIn("Never translate `c`", system)


class SinglePromptContextTest(unittest.TestCase):
    def test_scope_is_sent(self):
        """단건 폴백도 문맥을 싣는다 (배치와 같은 값)."""
        _system, user = build_single_prompts(_CONTEXT, "국내", [], "정산 기준")
        self.assertIn("CONTEXT (do not translate): 정산 기준", user)
        self.assertIn("SOURCE_TEXT: 국내", user)

    def test_no_scope_renders_no_context_line(self):
        _system, user = build_single_prompts(_CONTEXT, "국내", [])
        self.assertNotIn("CONTEXT", user)
        self.assertTrue(user.strip().startswith("SOURCE_TEXT:"))

    def test_system_prompt_warns_about_the_context_line(self):
        system, _user = build_single_prompts(_CONTEXT, "국내", [], "정산 기준")
        self.assertIn("CONTEXT line", system)


if __name__ == "__main__":
    unittest.main()
