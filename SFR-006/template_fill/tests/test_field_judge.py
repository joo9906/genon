"""field_judge — LLM 응답 검증/기각 동작 확인."""

import unittest

from template_fill.field_judge import mock_extract, parse_updates

ALLOWED = {"title", "date", "manager"}


class ParseUpdatesTest(unittest.TestCase):
    def test_valid_updates_accepted(self):
        raw = '{"updates": {"title": "사업 추진", "date": "2026. 8. 3."}}'
        accepted, rejected = parse_updates(raw, ALLOWED)
        self.assertEqual(accepted, {"title": "사업 추진", "date": "2026. 8. 3."})
        self.assertEqual(rejected, [])

    def test_unknown_field_rejected(self):
        raw = '{"updates": {"title": "ok", "invented_field": "x"}}'
        accepted, rejected = parse_updates(raw, ALLOWED)
        self.assertEqual(accepted, {"title": "ok"})
        self.assertEqual(rejected, ["invented_field"])

    def test_non_string_and_empty_rejected(self):
        raw = '{"updates": {"title": ["리스트"], "date": "", "manager": "홍길동"}}'
        accepted, rejected = parse_updates(raw, ALLOWED)
        self.assertEqual(accepted, {"manager": "홍길동"})
        self.assertEqual(sorted(rejected), ["date", "title"])

    def test_json_embedded_in_prose(self):
        raw = '다음과 같습니다: {"updates": {"title": "제목"}} 이상입니다.'
        accepted, rejected = parse_updates(raw, ALLOWED)
        self.assertEqual(accepted, {"title": "제목"})

    def test_garbage_returns_rejected_marker(self):
        accepted, rejected = parse_updates("json 아님", ALLOWED)
        self.assertEqual(accepted, {})
        self.assertTrue(rejected)

    def test_missing_updates_key(self):
        accepted, rejected = parse_updates('{"other": 1}', ALLOWED)
        self.assertEqual(accepted, {})
        self.assertTrue(rejected)


class MockExtractTest(unittest.TestCase):
    def test_line_format(self):
        message = "title: 생성형 AI 사업\ndate: 2026. 8. 3.\n없는필드: 무시됨"
        accepted, rejected = mock_extract(message, ALLOWED)
        self.assertEqual(accepted, {"title": "생성형 AI 사업", "date": "2026. 8. 3."})
        self.assertEqual(rejected, ["없는필드"])


if __name__ == "__main__":
    unittest.main()
