"""field_judge — LLM 응답 검증/기각 동작 확인.

**`final/` 운영 코드를 직접 태운다** (`final/SFR-006/request`).

- `parse_updates` 는 튜플이 아니라 **`ParsedIntent`** 를 돌려준다.
  수정(`updates`)·삭제(`clears`)·본문 추가(`blocks`)가 한 응답에 섞여 오므로 튜플로는
  담을 수 없다.
- mock 추출 테스트는 없다 — 배포 단위 안에 mock 경로를 두지 않으므로 운영 코드에
  그 함수가 없다.

이 파일이 지키는 계약은 하나다: **LLM 이 뭘 보내든 화이트리스트 밖은 들어오지 않고,
버린 것은 반드시 드러난다.** 조용히 버리면 값이 왜 안 채워졌는지 알 수 없다.
"""

import unittest

from . import final_path  # noqa: F401 - import 부작용으로 sys.path 를 세운다

from template_fill.field_judge import parse_updates  # noqa: E402

ALLOWED = {"title", "date", "manager"}


class ParseUpdatesTest(unittest.TestCase):
    def test_valid_updates_accepted(self):
        raw = '{"updates": {"title": "사업 추진", "date": "2026. 8. 3."}}'
        intent = parse_updates(raw, ALLOWED)
        self.assertEqual(intent.updates, {"title": "사업 추진", "date": "2026. 8. 3."})
        self.assertEqual(intent.rejected, [])

    def test_unknown_field_rejected(self):
        raw = '{"updates": {"title": "ok", "invented_field": "x"}}'
        intent = parse_updates(raw, ALLOWED)
        self.assertEqual(intent.updates, {"title": "ok"})
        self.assertEqual(intent.rejected, ["invented_field"])

    def test_non_string_and_empty_rejected(self):
        raw = '{"updates": {"title": ["리스트"], "date": "", "manager": "홍길동"}}'
        intent = parse_updates(raw, ALLOWED)
        self.assertEqual(intent.updates, {"manager": "홍길동"})
        self.assertEqual(sorted(intent.rejected), ["date", "title"])

    def test_json_embedded_in_prose(self):
        raw = '다음과 같습니다: {"updates": {"title": "제목"}} 이상입니다.'
        intent = parse_updates(raw, ALLOWED)
        self.assertEqual(intent.updates, {"title": "제목"})

    def test_garbage_returns_rejected_marker(self):
        intent = parse_updates("json 아님", ALLOWED)
        self.assertEqual(intent.updates, {})
        # 기각 사유가 비어 있으면 "빈 응답" 과 구분되지 않는다
        self.assertTrue(intent.rejected)

    def test_missing_updates_key(self):
        intent = parse_updates('{"other": 1}', ALLOWED)
        self.assertEqual(intent.updates, {})
        self.assertTrue(intent.rejected)


class ClearsTest(unittest.TestCase):
    """삭제 의도 — 슬롯 방식에서 "값을 비운다" 는 수정과 별개 경로다."""

    def test_clears_accepted(self):
        intent = parse_updates('{"updates": {"title": "A"}, "clears": ["date"]}', ALLOWED)
        self.assertEqual(intent.updates, {"title": "A"})
        self.assertEqual(intent.clears, ["date"])

    def test_update_wins_over_clear_and_conflict_is_reported(self):
        """같은 항목에 수정과 삭제가 함께 오면 **수정을 채택**하고 사실을 남긴다.

        계약상 `updates` 와 `clears` 는 겹치지 않는다. 모순을 그대로 넘기면 호출부마다
        같은 해소 규칙을 다시 적게 되고, 한 곳이 빠뜨리면 **방금 채운 값을 지운다.**
        """
        intent = parse_updates('{"updates": {"title": "A"}, "clears": ["title"]}', ALLOWED)
        self.assertEqual(intent.updates, {"title": "A"})
        self.assertEqual(intent.clears, [])
        self.assertEqual(intent.conflicts, ["title"])

    def test_unknown_field_in_clears_rejected(self):
        intent = parse_updates('{"clears": ["invented_field"]}', ALLOWED)
        self.assertEqual(intent.clears, [])
        self.assertIn("invented_field", intent.rejected)


class UseDocumentTest(unittest.TestCase):
    """"문서 내용으로 바꿔줘" — 값이 아니라 지시라 플래그로 따로 받는다."""

    def test_flag_alone_is_a_valid_response(self):
        intent = parse_updates('{"use_document": true}', ALLOWED)
        self.assertTrue(intent.use_document)
        self.assertEqual(intent.rejected, [])

    def test_absent_means_no_overwrite(self):
        intent = parse_updates('{"updates": {"title": "a"}}', ALLOWED)
        self.assertFalse(intent.use_document)

    def test_only_boolean_true_counts(self):
        """문자열 `"true"` 를 참으로 읽으면 사용자가 시키지 않은 덮어쓰기가 일어난다."""
        intent = parse_updates('{"updates": {"title": "a"}, "use_document": "true"}', ALLOWED)
        self.assertFalse(intent.use_document)
        self.assertIn("<use_document: 불리언 아님>", intent.rejected)


if __name__ == "__main__":
    unittest.main()
