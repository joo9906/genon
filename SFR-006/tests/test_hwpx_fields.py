"""hwpx_fields 스캔/채우기 라운드트립 검증 (LLM·GenOS·한/글 불필요).

**onprem 운영 코드를 직접 태운다.** 사본 검증에서 옮겨오며 두 가지가 바뀌었다
(2026-08-11):

1. `scan_tokens` 테스트를 **없앴다.** 슬롯 문법 전환으로 그 함수는 사라졌고,
   사본에만 남아 있었다. `{{token}}` 자체는 `fill_template` 의 `leftover_tokens`
   경로로 여전히 살아 있어 아래 `test_partial_fill_reports_missing` 이 지킨다.
2. **슬롯 모드 테스트를 새로 넣었다** (`SlotTest`). 슬롯은 2026-08-06 이후 **기본 방식**
   인데 사본에 파서가 없어 회귀 테스트가 없었다 — CLAUDE.md 가 "onprem 에만 있는 기능은
   정식 테스트가 없다" 고 적어 둔 공백이 바로 이것이다.

누름틀(CLICK_HERE) 경로는 폴백으로 살아 있으므로 함께 검증한다.
"""

import io
import unittest
import zipfile

from . import onprem_path  # noqa: F401 - import 부작용으로 sys.path 를 세운다

from template_fill.hwpx_fields import (  # noqa: E402
    TemplateError,
    fill_template,
    scan_fields,
)

from .fixtures import build_sample_hwpx, build_slot_hwpx  # noqa: E402


class ScanTest(unittest.TestCase):
    """누름틀 폴백 경로."""

    def setUp(self):
        self.hwpx = build_sample_hwpx()

    def test_scan_fields_schema(self):
        specs = scan_fields(self.hwpx)
        names = [s.name for s in specs]
        # 이름 없는 누름틀은 안내문으로 대체 이름 부여
        self.assertEqual(names, ["title", "시행일자 입력", "manager", "memo"])

        by_name = {s.name: s for s in specs}
        self.assertFalse(by_name["title"].filled)  # 본문 == 안내문 → 미입력
        self.assertEqual(by_name["title"].guide, "이곳을 눌러 제목 입력")
        self.assertTrue(by_name["manager"].filled)  # 본문 != 안내문 → 기입력
        self.assertEqual(by_name["manager"].current_value, "김철수 과장")
        self.assertFalse(by_name["memo"].filled)  # 본문 없음 → 미입력

    def test_bad_zip_raises_template_error(self):
        with self.assertRaises(TemplateError):
            scan_fields(b"not a zip at all")


class FillTest(unittest.TestCase):
    def setUp(self):
        self.hwpx = build_sample_hwpx()

    def test_fill_roundtrip(self):
        values = {
            "title": "생성형 AI 구축 사업 추진",
            "시행일자 입력": "2026. 8. 3.",
            "memo": "특이사항 없음",
            "dept": "지원부서",
        }
        result = fill_template(self.hwpx, values)

        self.assertEqual(
            result.written_fields, ["dept", "memo", "title", "시행일자 입력"]
        )
        self.assertEqual(result.missing_fields, [])
        self.assertEqual(result.unknown_keys, [])
        self.assertEqual(result.leftover_tokens, [])

        # 재스캔: 값이 실제로 들어갔는지 결정적으로 확인
        specs = {s.name: s for s in scan_fields(result.hwpx_bytes)}
        self.assertTrue(specs["title"].filled)
        self.assertEqual(specs["title"].current_value, "생성형 AI 구축 사업 추진")
        self.assertTrue(specs["memo"].filled)  # 빈 본문 → run/t 신규 삽입 경로
        self.assertEqual(specs["memo"].current_value, "특이사항 없음")
        self.assertEqual(specs["manager"].current_value, "김철수 과장")  # 미지정 필드 보존

    def test_partial_fill_reports_missing(self):
        result = fill_template(self.hwpx, {"title": "제목만 입력"})
        self.assertEqual(result.written_fields, ["title"])
        self.assertIn("memo", result.missing_fields)
        self.assertIn("시행일자 입력", result.missing_fields)
        self.assertNotIn("manager", result.missing_fields)  # 기입력 필드는 부족 아님
        self.assertEqual(result.leftover_tokens, ["dept"])  # 미치환 토큰 노출

    def test_unknown_keys_reported(self):
        result = fill_template(self.hwpx, {"없는필드": "값"})
        self.assertEqual(result.unknown_keys, ["없는필드"])

    def test_xml_escape_and_newline(self):
        result = fill_template(self.hwpx, {"title": "A<B&C\n다음줄"})
        specs = {s.name: s for s in scan_fields(result.hwpx_bytes)}
        self.assertEqual(specs["title"].current_value, "A<B&C 다음줄")

    def test_zip_conventions_preserved(self):
        result = fill_template(self.hwpx, {"title": "x"})
        with zipfile.ZipFile(io.BytesIO(result.hwpx_bytes)) as zf:
            mimetype_info = zf.getinfo("mimetype")
            self.assertEqual(mimetype_info.compress_type, zipfile.ZIP_STORED)
            section = zf.read("Contents/section0.xml")
            self.assertTrue(section.startswith(b"<?xml"))


class SlotTest(unittest.TestCase):
    """슬롯 방식 — 2026-08-06 이후의 **기본** 인식 경로.

    현장 템플릿은 누름틀이 아니라 본문에 그냥 텍스트로 적혀 있고, 채울 자리는
    중괄호 안뿐이다. 이 클래스가 지키는 것은 그 규칙의 경계 셋이다.
    """

    def setUp(self):
        self.hwpx = build_slot_hwpx()

    def test_slot_names_and_always_unfilled(self):
        specs = scan_fields(self.hwpx)
        self.assertEqual([s.name for s in specs], ["제목", "작성자", "소속", "성명"])
        # 슬롯은 **언제나 미입력**이다 — 채우고 나면 `{…}` 자체가 사라지므로,
        # 문서에 남아 있다는 것이 곧 아직 안 채웠다는 뜻이다.
        self.assertTrue(all(not s.filled for s in specs))
        self.assertTrue(all(s.field_type == "SLOT" for s in specs))

    def test_quoteless_brace_is_not_a_field(self):
        """따옴표 없는 `{…}` 는 채울 자리가 아니라 **값 안내**다.

        `배포일 : {YYYY.MM.DD. (요일)}` 를 항목으로 잡으면 LLM 이 거기에 값을 넣고,
        원문에 있던 서식 안내가 사라진다. 지우지도 않는다 — 원문 그대로 남긴다.
        """
        names = [s.name for s in scan_fields(self.hwpx)]
        self.assertNotIn("YYYY.MM.DD. (요일)", names)

        result = fill_template(self.hwpx, {"제목": "x"})
        with zipfile.ZipFile(io.BytesIO(result.hwpx_bytes)) as zf:
            section = zf.read("Contents/section0.xml").decode("utf-8")
        self.assertIn("YYYY.MM.DD. (요일)", section)

    def test_text_outside_braces_is_preserved_verbatim(self):
        """중괄호 **밖**은 무조건 원문 그대로 남는다.

        라벨 방식은 `항목명: 값` 으로 줄을 재조립하느라 `제 목  : ` 의 줄맞춤 공백을
        잃었다. 자리를 중괄호로 명시하면 그 문제가 아예 생기지 않는다 — 그 성질을
        여기서 못 박는다 (공백 두 칸이 한 칸으로 줄면 실패한다).
        """
        result = fill_template(self.hwpx, {"제목": "hwpx 만들기 문서"})
        with zipfile.ZipFile(io.BytesIO(result.hwpx_bytes)) as zf:
            section = zf.read("Contents/section0.xml").decode("utf-8")
        self.assertIn("제 목  : ", section)
        self.assertIn("hwpx 만들기 문서", section)
        self.assertNotIn("{'제목'", section)  # 슬롯은 채워지면 사라진다

    def test_two_slots_in_one_paragraph(self):
        """한 문단에 슬롯이 둘 이상 올 수 있다 (라벨 방식의 "문단당 1개" 제약이 없다)."""
        result = fill_template(self.hwpx, {"소속": "AI팀", "성명": "홍길동"})
        self.assertEqual(sorted(result.written_fields), ["성명", "소속"])
        with zipfile.ZipFile(io.BytesIO(result.hwpx_bytes)) as zf:
            section = zf.read("Contents/section0.xml").decode("utf-8")
        self.assertIn("AI팀", section)
        self.assertIn("홍길동", section)

    def test_curly_quotes_are_accepted(self):
        """한/글 자동 고침이 `'제목'` 을 `‘제목’` 으로 바꿔 저장한다.

        굽은 따옴표를 안 받으면 **관리자가 눈으로 구분할 수 없는 차이로 항목이 통째로
        사라진다.** 한쪽만 바뀐 문서도 열어 준다.
        """
        specs = scan_fields(build_slot_hwpx(quote_style="curly"))
        self.assertIn("제목", [s.name for s in specs])

        specs = scan_fields(build_slot_hwpx(quote_style="half"))
        self.assertIn("제목", [s.name for s in specs])


if __name__ == "__main__":
    unittest.main()
