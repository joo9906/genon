"""field_judge — LLM 응답 검증/기각 동작 확인.

**onprem 운영 코드를 직접 태운다** (`onprem/codeserving/SFR-006_template_fill`).
사본을 검증하던 옛 테스트에서 옮겨오며 현행 API 에 맞췄다 (2026-08-11):

- `parse_updates` 가 `(accepted, rejected)` 튜플이 아니라 **`ParsedIntent`** 를 돌려준다.
  수정(`updates`)·삭제(`clears`)·본문 추가(`blocks`)가 한 응답에 섞여 오므로 튜플로는
  담을 수 없었다.
- `mock_extract` 테스트는 **없앴다.** 그 함수는 사본에만 있었다 — 배포 단위 안에
  mock 경로를 두지 않는 것이 `onprem/` 규칙이라 운영 코드에는 존재한 적이 없고,
  따라서 그 테스트는 운영에 없는 코드를 지키고 있었다.

이 파일이 지키는 계약은 하나다: **LLM 이 뭘 보내든 화이트리스트 밖은 들어오지 않고,
버린 것은 반드시 드러난다.** 조용히 버리면 값이 왜 안 채워졌는지 알 수 없다.
"""

import unittest

from . import onprem_path  # noqa: F401 - import 부작용으로 sys.path 를 세운다

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


if __name__ == "__main__":
    unittest.main()
