"""hwpx_repeat — `{'본문 1'}`·`{'내용 1-1'}` 묶음을 입력 분량만큼 늘리는 경로.

**`final/` 운영 코드를 직접 태운다.** 이 파일이 지키는 계약:

1. **묶음 인식은 결정적이다.** `1` 로 끝나는 슬롯이 묶음, `1-1` 로 끝나면 세부 항목이다.
   번호 2 이상이 이미 적힌 템플릿은 반복으로 보지 않는다(관리자가 고정해 둔 문서다).
2. **묶음마다 세부 항목 수가 다를 수 있다** — 본문 1 은 내용 셋, 본문 2 는 하나.
3. **복제는 이름만 바꾼다.** 서식 인자·중괄호 밖 글자·문단 모양(들여쓰기)은 그대로고,
   구역 정의(secPr)는 원본 한 벌에만 남으며, 표 id 는 겹치지 않는다.
4. **빈 묶음은 당겨진다** — "2번 빼줘" 는 그 묶음을 비우는 것으로 들어온다.
5. **자동 채움은 다음 번호를 안다** — 조각마다 1번부터 다시 세면 뒤 주제가 버려진다.
"""

import asyncio
import io
import json
import types
import unittest
import zipfile

from . import final_path  # noqa: F401 - import 부작용으로 sys.path 를 세운다

from template_fill import doc_prefill, document  # noqa: E402
from template_fill.config import Config  # noqa: E402
from template_fill.hwpx_fields import (  # noqa: E402
    HP_NS,
    iter_section_xml,
    para_text,
    parse_xml,
    scan_fields,
)
from template_fill.hwpx_repeat import expand_repeats, scan_repeat  # noqa: E402
from template_fill.prompts import build_document_prompts  # noqa: E402
from template_fill.template_index import allowed_names, field_specs  # noqa: E402

from .fixtures import HP, HS, _pack  # noqa: E402

_P = f"{{{HP_NS}}}p"


def _para(text: str, para_pr: str = "0") -> str:
    return (
        f'<hp:p paraPrIDRef="{para_pr}"><hp:run charPrIDRef="0">'
        f"<hp:t>{text}</hp:t></hp:run></hp:p>"
    )


def _slot(name: str, extra: str = "") -> str:
    return "{&apos;" + name + "&apos;" + extra + "}"


def _section(*paras: str) -> bytes:
    return _pack(
        f'<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">'
        + "".join(paras)
        + "</hs:sec>"
    )


def press_release() -> bytes:
    """보도자료 모양 — 머리(secPr 를 든 첫 문단) · 묶음(본문/세부 내용/표 안 요약) · 꼬리.

    일부러 까다로운 것을 넣는다: 첫 문단의 secPr·단 정의, 들여쓴 세부 문단(paraPr 7),
    표 셀 안 슬롯, 묶음 밖 항목.
    """
    head = (
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"><hp:secPr id=""/>'
        '<hp:ctrl><hp:colPr id=""/></hp:ctrl></hp:run>'
        f'<hp:run charPrIDRef="0"><hp:t>제 목 : {_slot("제목", ", 16pt")}</hp:t></hp:run></hp:p>'
    )
    table = (
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"><hp:tbl id="555"><hp:tc><hp:subList>'
        + _para("요약: " + _slot("요약 1"))
        + "</hp:subList></hp:tc></hp:tbl></hp:run></hp:p>"
    )
    return _section(
        head,
        _para("□ " + _slot("본문 1", ", 14pt")),
        _para("  - " + _slot("내용 1-1"), para_pr="7"),
        table,
        _para("담당 : " + _slot("담당자")),
    )


def _paragraphs(hwpx_bytes: bytes) -> list:
    out = []
    for _, xml in iter_section_xml(hwpx_bytes):
        root = parse_xml(xml)
        out.extend(child for child in root if child.tag == _P)
    return out


class ScanTest(unittest.TestCase):
    def test_members_and_spans(self):
        scan = scan_repeat(press_release())
        self.assertIsNotNone(scan.group)
        self.assertEqual([m.name for m in scan.group.members], ["본문 1", "내용 1-1", "요약 1"])
        self.assertTrue(scan.group.inner_repeatable)
        self.assertEqual(scan.span, (1, 3))
        self.assertEqual(scan.inner_span, (2, 2))
        self.assertEqual(scan.warnings, [])

    def test_no_numbered_slot_means_no_group(self):
        scan = scan_repeat(_section(_para(_slot("제목")), _para(_slot("분기"))))
        self.assertIsNone(scan.group)

    def test_fixed_numbers_disable_repeat(self):
        """`본문 2` 가 이미 적혀 있으면 늘린 이름과 부딪힌다 — 반복을 끄고 경고한다."""
        scan = scan_repeat(_section(_para(_slot("본문 1")), _para(_slot("본문 2"))))
        self.assertIsNone(scan.group)
        self.assertTrue(any("번호 2 이상" in w for w in scan.warnings))

    def test_loose_slot_inside_span_is_warned(self):
        scan = scan_repeat(
            _section(_para(_slot("본문 1")), _para(_slot("비고")), _para(_slot("내용 1-1")))
        )
        self.assertIsNotNone(scan.group)
        self.assertTrue(any("비고" in w for w in scan.warnings))

    def test_outer_inside_inner_span_disables_items_only(self):
        scan = scan_repeat(
            _section(_para(_slot("내용 1-1")), _para(_slot("본문 1")), _para(_slot("내용 1-1") + "x"))
        )
        self.assertIsNotNone(scan.group)
        self.assertFalse(scan.group.inner_repeatable)
        self.assertTrue(any("세부 항목" in w for w in scan.warnings))

    def test_spacing_of_number_is_kept(self):
        """`본문1`(붙여 씀)은 `본문2` 로 늘어난다 — 관리자가 쓴 표기를 바꾸지 않는다."""
        scan = scan_repeat(_section(_para(_slot("본문1"))))
        self.assertEqual(scan.group.members[0].name_for(2), "본문2")


class GroupModelTest(unittest.TestCase):
    def setUp(self):
        self.template = press_release()
        self.group = scan_repeat(self.template).group
        self.specs = scan_fields(self.template)

    def test_counts_follow_values_per_group(self):
        """본문 1 은 내용 셋, 본문 2 는 내용 하나 — 묶음마다 세부 수가 다르다."""
        values = {"본문 1": "A", "내용 1-3": "c", "본문 2": "B"}
        self.assertEqual(self.group.counts(values, 10, 10), [3, 1])
        self.assertEqual(self.group.counts({}, 10, 10), [1])
        self.assertEqual(self.group.counts({"본문 2": ""}, 10, 10), [1])  # 빈 값은 세지 않는다

    def test_counts_ignore_numbers_over_the_cap(self):
        self.assertEqual(self.group.counts({"본문 11": "x"}, 10, 10), [1])

    def test_expand_specs_in_document_order(self):
        values = {"본문 1": "A", "내용 1-2": "b", "본문 2": "B"}
        names = [s.name for s in self.group.expand_specs(self.specs, values, 10, 10)]
        self.assertEqual(
            names,
            ["제목", "본문 1", "내용 1-1", "내용 1-2", "요약 1", "본문 2", "내용 2-1", "요약 2", "담당자"],
        )

    def test_extra_copy_only_after_first_group_is_used(self):
        empty = [s.name for s in self.group.expand_specs(self.specs, {}, 10, 10, extra_copy=True)]
        self.assertNotIn("본문 2", empty)
        used = self.group.expand_specs(self.specs, {"본문 1": "A"}, 10, 10, extra_copy=True)
        self.assertIn("본문 2", [s.name for s in used])

    def test_compact_pulls_up_empty_groups_and_items(self):
        values = {"제목": "T", "본문 1": "", "본문 2": "B", "내용 2-3": "z", "내용 2-1": "x"}
        self.assertEqual(
            self.group.compact(values),
            {"제목": "T", "본문 1": "B", "내용 1-1": "x", "내용 1-2": "z"},
        )

    def test_allowed_names_cover_caps(self):
        names = allowed_names(self.specs, self.group)
        self.assertIn("본문 %d" % Config.MAX_REPEAT, names)
        self.assertIn("내용 2-%d" % Config.MAX_REPEAT_ITEMS, names)
        self.assertNotIn("본문 %d" % (Config.MAX_REPEAT + 1), names)
        self.assertIn("제목", names)

    def test_payload_round_trip(self):
        from template_fill.hwpx_repeat import RepeatGroup

        self.assertEqual(RepeatGroup.from_payload(self.group.to_payload()), self.group)


class ExpandTest(unittest.TestCase):
    def setUp(self):
        self.template = press_release()

    def test_single_group_returns_input_unchanged(self):
        out = expand_repeats(self.template, {"본문 1": "A"}, max_outer=10, max_inner=10)
        self.assertIs(out, self.template)

    def test_expanded_template_has_renamed_slots(self):
        values = {"본문 1": "A", "내용 1-3": "c", "본문 2": "B"}
        out = expand_repeats(self.template, values, max_outer=10, max_inner=10)
        self.assertEqual(
            [s.name for s in scan_fields(out)],
            ["제목", "본문 1", "내용 1-1", "내용 1-2", "내용 1-3", "요약 1",
             "본문 2", "내용 2-1", "요약 2", "담당자"],
        )
        texts = [para_text(p) for p in _paragraphs(out)]
        # 서식 인자는 이름 뒤에 그대로 남는다 — 서식 단계가 그것을 읽는다
        self.assertIn("□ {'본문 2', 14pt}", texts)

    def test_copies_keep_layout_and_drop_section_definition(self):
        values = {"본문 2": "B", "내용 1-2": "b"}
        paras = _paragraphs(expand_repeats(self.template, values, max_outer=10, max_inner=10))
        # 들여쓴 세부 문단은 문단 모양째 복제된다
        indented = [p for p in paras if p.get("paraPrIDRef") == "7"]
        self.assertEqual(len(indented), 3)  # 1-1, 1-2, 2-1
        all_xml = b"".join(
            xml for _, xml in iter_section_xml(
                expand_repeats(self.template, values, max_outer=10, max_inner=10)
            )
        ).decode()
        self.assertEqual(all_xml.count("<hp:secPr"), 1)
        self.assertEqual(all_xml.count("<hp:colPr"), 1)
        table_ids = [p.get("id") for p in parse_xml(all_xml.encode()).iter(f"{{{HP_NS}}}tbl")]
        self.assertEqual(len(table_ids), 2)
        self.assertEqual(len(set(table_ids)), 2)

    def test_section_definition_in_span_stays_once(self):
        """섹션 첫 문단(secPr·단 정의)이 묶음 구간 안이면 복제본에서 떼야 한다.

        위 픽스처는 첫 문단이 구간 **밖**이라 이 방어를 지나지 않는다 — 따로 본다.
        """
        head = (
            '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"><hp:secPr id=""/>'
            '<hp:ctrl><hp:colPr id=""/></hp:ctrl></hp:run>'
            f'<hp:run charPrIDRef="0"><hp:t>{_slot("본문 1")}</hp:t></hp:run></hp:p>'
        )
        out = expand_repeats(
            _section(head, _para(_slot("내용 1-1"))), {"본문 3": "C"}, max_outer=10, max_inner=10
        )
        xml = b"".join(x for _, x in iter_section_xml(out)).decode()
        self.assertEqual(xml.count("<hp:secPr"), 1)
        self.assertEqual(xml.count("<hp:colPr"), 1)
        self.assertEqual(
            [s.name for s in scan_fields(out)],
            ["본문 1", "내용 1-1", "본문 2", "내용 2-1", "본문 3", "내용 3-1"],
        )

    def test_zip_conventions_preserved(self):
        out = expand_repeats(self.template, {"본문 2": "B"}, max_outer=10, max_inner=10)
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            first = zf.infolist()[0]
            self.assertEqual(first.filename, "mimetype")
            self.assertEqual(first.compress_type, zipfile.ZIP_STORED)

    def test_build_fills_every_group(self):
        """조립 파이프라인 한 벌을 그대로 탄다 — 복제 → 서식 → 채우기."""
        values = {
            "제목": "T", "본문 1": "A", "내용 1-1": "a1", "내용 1-2": "a2",
            "요약 1": "sa", "본문 2": "B", "내용 2-1": "b1", "요약 2": "sb", "담당자": "me",
        }
        built = document.build(self.template, values, apply_style=False)
        self.assertEqual(built.missing_fields, [])
        self.assertEqual(built.unknown_keys, [])
        texts = [para_text(p) for p in _paragraphs(built.hwpx_bytes)]
        self.assertEqual(
            [t for t in texts if t.strip()],
            ["제 목 : T", "□ A", "  - a1", "  - a2", "□ B", "  - b1", "담당 : me"],
        )


class PrefillNextIndexTest(unittest.TestCase):
    """문서가 주제 둘을 담으면 조각 2 는 2번 묶음에 써야 한다."""

    def setUp(self):
        self.template = press_release()
        self.group = scan_repeat(self.template).group
        self.specs = scan_fields(self.template)
        self._saved = (doc_prefill.llm_call_async, Config.DOC_CHUNK_CHARS)

    def tearDown(self):
        doc_prefill.llm_call_async, Config.DOC_CHUNK_CHARS = self._saved

    def test_second_chunk_targets_next_group(self):
        prompts: list = []
        replies = [
            {"updates": {"본문 1": "A", "내용 1-1": "a"}},
            {"updates": {"본문 2": "B", "내용 2-1": "b", "본문 1": "덮으면 안 된다"}},
        ]

        async def _fake(system_prompt, user_prompt, **_kwargs):
            prompts.append(user_prompt)
            content = json.dumps(replies.pop(0) if replies else {}, ensure_ascii=False)
            return types.SimpleNamespace(ok=True, content=content, error_type="",
                                         is_transport_error=False)

        doc_prefill.llm_call_async = _fake
        Config.DOC_CHUNK_CHARS = 40
        document_text = "# 첫 주제\n" + "가" * 30 + "\n# 둘째 주제\n" + "나" * 30
        outcome = asyncio.run(
            doc_prefill.prefill_from_document(
                self.specs, allowed_names(self.specs, self.group), document_text, {},
                repeat=self.group,
            )
        )
        self.assertEqual(outcome.values["본문 1"], "A")
        self.assertEqual(outcome.values["본문 2"], "B")
        self.assertEqual(outcome.values["내용 2-1"], "b")
        self.assertEqual(outcome.conflicts, 1)
        self.assertGreaterEqual(len(prompts), 2)
        self.assertIn("2번 묶음", prompts[1])
        self.assertIn("- 본문 2", prompts[1])

    def test_prompt_has_no_repeat_section_without_group(self):
        _, user = build_document_prompts(self.specs, "문서")
        self.assertNotIn("[반복 묶음]", user)


class FieldSpecsWithoutRepeatTest(unittest.TestCase):
    def test_plain_template_is_untouched(self):
        specs = scan_fields(_section(_para(_slot("제목"))))
        self.assertEqual(field_specs(specs, None, {"제목": "x"}), specs)


if __name__ == "__main__":
    unittest.main()
