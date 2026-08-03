"""hwpx_fields 스캔/채우기 라운드트립 검증 (LLM/GenOS 불필요)."""

import io
import unittest
import zipfile

from template_fill.hwpx_fields import (
    TemplateError,
    fill_template,
    scan_fields,
    scan_tokens,
)

from .fixtures import build_sample_hwpx


class ScanTest(unittest.TestCase):
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

    def test_scan_tokens(self):
        self.assertEqual(scan_tokens(self.hwpx), {"dept"})

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


if __name__ == "__main__":
    unittest.main()
