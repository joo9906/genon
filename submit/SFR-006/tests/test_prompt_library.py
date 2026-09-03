"""프롬프트를 **프롬프트 라이브러리에서 받는가** (2026-09-03 신규).

라이브러리는 파일을 **덮어쓴다.** 못 읽으면 파일로 떨어지되 조용하지 않다 —
`GET /prompts` 가 이름마다 출처와 사유를 낸다.

여기서 지키는 것 넷:

1. ID 를 준 이름은 **라이브러리 본문**이 렌더된다 (안 그러면 관리자가 고친 문구가
   아무 데도 반영되지 않는데, 결과는 정상 응답이라 드러나지 않는다).
2. ID 가 없거나 조회가 실패하면 **파일**로 돈다 (admin-api 장애가 대화를 막지 않는다).
3. 라이브러리 본문이 깨져도(변수 오타) 파일로 떨어진다 — 문구 오타 하나가 대화를
   통째로 막으면 안 된다.
4. 어느 쪽을 썼는지가 `status()` 에 남는다 — "ID 를 안 넣었다" 와 "넣었는데 못 읽었다"
   가 구분돼야 관리자가 손을 쓸 수 있다.
"""

import unittest

from . import onprem_path  # noqa: F401  (sys.path 를 세운다)

import httpx  # noqa: E402

from template_fill import prompt_library, prompt_loader  # noqa: E402


class _FakeAdminApi:
    """`GET /prompt/template/{id}` 대역. 가이드 §10.5 응답 계약을 그대로 흉내 낸다."""

    def __init__(self, *, bodies=None, status=200, code=0):
        # {프롬프트 ID: 본문}
        self.bodies = bodies or {}
        self.status = status
        self.code = code
        self.calls = 0

    def __call__(self, url, timeout=None):
        self.calls += 1
        request = httpx.Request("GET", url)
        if self.status != 200:
            return httpx.Response(self.status, json={}, request=request)
        prompt_id = url.rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            json={"code": self.code, "data": self.bodies.get(prompt_id)},
            request=request,
        )


class PromptLibraryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._real_get = prompt_library.httpx.get
        prompt_library.Config.genos_admin_api_url = staticmethod(lambda: "http://admin.test")
        self._set_ids("extract_user=41")
        prompt_library.clear_cache()

    def tearDown(self) -> None:
        prompt_library.httpx.get = self._real_get
        self._set_ids("")
        prompt_library.clear_cache()

    def _set_ids(self, raw: str) -> None:
        prompt_library.Config.prompt_ids_raw = staticmethod(lambda: raw)

    def _serve(self, **kwargs) -> _FakeAdminApi:
        api = _FakeAdminApi(**kwargs)
        prompt_library.httpx.get = api
        return api

    # ── 이름 → ID 매핑 ──────────────────────────────────────────

    def test_mapping_accepts_both_notations(self):
        """`name=id` 목록과 JSON 을 둘 다 받는다 — 관리자가 JSON 을 쓰게 강요하지 않는다."""
        self._set_ids("extract_user=41, document_user = 42")
        self.assertEqual(
            prompt_library.prompt_ids(), {"extract_user": "41", "document_user": "42"}
        )
        self._set_ids('{"extract_user": "41", "document_user": 42}')
        self.assertEqual(
            prompt_library.prompt_ids(), {"extract_user": "41", "document_user": "42"}
        )

    def test_broken_mapping_is_not_an_error(self):
        """환경변수 오타로 서빙이 안 뜨면 "기능이 통째로 죽었다" 로 보인다."""
        self._set_ids("{ 이건 JSON 이 아니다")
        self.assertEqual(prompt_library.prompt_ids(), {})

    # ── 덮어쓰기가 실제로 되는가 ────────────────────────────────

    def test_library_body_overrides_the_file(self):
        self._serve(bodies={"41": "라이브러리 지시문: {{ user_message }}"})
        rendered = prompt_loader.render(
            "extract_user.j2",
            field_lines=[],
            current_values_json="{}",
            block_styles=[],
            block_lines=[],
            user_message="제목은 가나다",
        )
        self.assertEqual(rendered, "라이브러리 지시문: 제목은 가나다")

    def test_unconfigured_name_uses_the_file(self):
        """ID 를 안 준 이름은 파일이다 — 미설정은 오류가 아니라 정상 경로다."""
        self._serve(bodies={"41": "덮어쓴 문구"})
        rendered = prompt_loader.render("extract_system.j2")
        self.assertNotEqual(rendered, "덮어쓴 문구")
        self.assertTrue(rendered.strip(), "파일 프롬프트가 비어 있다")

    def test_fetch_failure_falls_back_to_the_file(self):
        """admin-api 장애가 대화를 막지 않는다 (자동 채움 실패를 오류로 안 올리는 것과 같다)."""
        self._serve(status=404)
        rendered = prompt_loader.render(
            "extract_user.j2",
            field_lines=[],
            current_values_json="{}",
            block_styles=[],
            block_lines=[],
            user_message="제목은 가나다",
        )
        self.assertIn("제목은 가나다", rendered)
        row = next(r for r in prompt_library.status() if r["name"] == "extract_user")
        self.assertEqual((row["source"], row["reason"]), ("file", "fetch_failed_404"))

    def test_empty_body_is_rejected(self):
        """빈 본문을 받아들이면 **지시문 없는 프롬프트**가 돌고 결과는 정상으로 보인다."""
        self._serve(bodies={"41": "   "})
        row = next(r for r in prompt_library.status() if r["name"] == "extract_user")
        self.assertEqual((row["source"], row["reason"]), ("file", "empty_body"))

    def test_broken_library_body_falls_back_to_the_file(self):
        """관리자가 변수 이름을 틀리는 것은 흔하다 (`StrictUndefined` 라 렌더가 죽는다)."""
        self._serve(bodies={"41": "{{ 없는_변수 }}"})
        rendered = prompt_loader.render(
            "extract_user.j2",
            field_lines=[],
            current_values_json="{}",
            block_styles=[],
            block_lines=[],
            user_message="제목은 가나다",
        )
        self.assertIn("제목은 가나다", rendered, "라이브러리 렌더 실패가 요청을 세웠다")

    # ── 캐시·상태 ───────────────────────────────────────────────

    def test_result_is_cached_and_reload_refetches(self):
        """매 요청 HTTP 를 때리면 대화 한 턴이 admin-api 지연에 묶인다."""
        api = self._serve(bodies={"41": "본문"})
        prompt_library.load()
        prompt_library.load()
        self.assertEqual(api.calls, 1)
        prompt_library.reload()
        self.assertEqual(api.calls, 2)

    def test_status_separates_unset_from_unreadable(self):
        """둘이 구분되지 않으면 관리자는 무엇을 고쳐야 하는지 알 수 없다."""
        self._set_ids("extract_user=41,document_user=99")
        self._serve(bodies={"41": "본문"})
        rows = {r["name"]: r for r in prompt_library.status()}
        self.assertEqual(rows["extract_user"]["source"], "prompt_library")
        self.assertEqual(rows["document_user"]["source"], "file")
        self.assertEqual(rows["document_user"]["reason"], "empty_body")
        self.assertNotIn("body", rows["extract_user"], "본문을 응답에 실었다 (3.8절)")

    def test_status_does_not_expose_prompt_text(self):
        """`GET /prompts` 가 지시문 유출 경로가 되면 안 된다."""
        self._serve(bodies={"41": "비밀 지시문"})
        serialized = repr(prompt_library.status())
        self.assertNotIn("비밀 지시문", serialized)


if __name__ == "__main__":
    unittest.main()
