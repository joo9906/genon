"""관리자가 등록한 톤·문서유형이 실제로 적용되는가 (2026-08-18).

고객사 관리자가 GenOS `도구 > 프롬프트 라이브러리` 에 톤을 추가하면 **재배포 없이**
화면 선택지와 프롬프트에 반영돼야 한다. 가이드 §10.5 가 정한 경로이고,
§10.10.2 는 이 리소스를 "비개발자도 변경할 수 있어" 라고 소개한다.

## 여기서 무엇을 보나

이 기능은 **조용히 실패하는 방식이 여러 개**다. 전부 예외가 아니라 "관리자가 넣은 톤이
안 보이거나, 골라도 기본 톤으로 되돌아가는" 모양으로 드러난다:

1. 목록에는 뜨는데 **고르면 기본 톤으로 돌아간다** — `allowed_tones` 가 내장 3종으로
   닫혀 있으면 그렇게 된다(구현 중 실제로 밟았다).
2. 관리자가 톤 하나를 넣었더니 **내장 셋이 사라진다** — 병합이 아니라 대체로 짜면 그렇다.
3. JSON 오타 하나로 **글다듬이 전체가 죽는다** — 파싱 실패를 예외로 올리면 그렇다.
4. 조회가 실패했는데 화면에는 내장 목록이 그대로 떠서 **"아직 등록 안 함" 과 구분되지
   않는다** — `source`/`reason` 을 안 실으면 그렇다.

`SFR-018/tests/test_glossary_policy.py` 와 달리 **가짜 admin-api 를 배포 단위 바깥에서**
꽂는다. 운영 코드에 테스트용 분기를 만들지 않는다.
"""

import json
import unittest

from . import onprem_path

onprem_path.install(onprem_path.TEXT_POLISH_UNIT)

import httpx  # noqa: E402

from text_polish import policy_store  # noqa: E402
from text_polish.tone_presets import (  # noqa: E402
    DEFAULT_TONE,
    doc_type_choices,
    policy_source,
    resolve_policy,
    tone_choices,
)

_ADMIN_POLICY = {
    "tones": [
        {"code": "legal", "label": "법무체", "instruction": "법률 문서 어투로 다듬는다."},
        {"code": "friendly", "disabled": True},
    ],
    "doc_types": [
        {"code": "contract", "label": "계약서", "forced_tone": "legal",
         "extra_instruction": "조항 번호를 바꾸지 않는다."},
    ],
}


class _FakeAdminApi:
    """`GET /prompt/template/{id}` 대역. 가이드 §10.5 응답 계약을 그대로 흉내 낸다."""

    def __init__(self, *, body=None, status=200, code=0):
        self.body = body
        self.status = status
        self.code = code
        self.calls = 0

    def __call__(self, url, timeout=None):
        self.calls += 1
        request = httpx.Request("GET", url)
        if self.status != 200:
            return httpx.Response(self.status, json={}, request=request)
        return httpx.Response(200, json={"code": self.code, "data": self.body}, request=request)


class AdminPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._real_get = policy_store.httpx.get
        policy_store.Config.genos_admin_api_url = staticmethod(lambda: "http://admin.test")
        policy_store.Config.policy_prompt_id = staticmethod(lambda: "42")
        policy_store.clear_cache()

    def tearDown(self) -> None:
        policy_store.httpx.get = self._real_get
        policy_store.clear_cache()

    def _serve(self, **kwargs) -> _FakeAdminApi:
        api = _FakeAdminApi(**kwargs)
        policy_store.httpx.get = api
        return api

    # ── 추가가 실제로 되는가 ────────────────────────────────────

    def test_added_tone_appears_in_choices(self):
        self._serve(body=json.dumps(_ADMIN_POLICY, ensure_ascii=False))
        codes = [t["code"] for t in tone_choices()]
        self.assertIn("legal", codes)

    def test_added_tone_is_selectable_for_builtin_doc_type(self):
        """**목록에 뜨는 것만으로는 부족하다** — 골랐을 때 실제로 적용돼야 한다.

        `allowed_tones` 가 내장 3종으로 닫혀 있으면 여기서 `polite` 로 되돌아온다.
        오류가 아니라 "고른 톤이 조용히 무시되는" 모양이라 구현 중 실제로 놓쳤다.
        """
        self._serve(body=json.dumps(_ADMIN_POLICY, ensure_ascii=False))
        doc_type, tone_key, overridden, _policy, tone = resolve_policy("email", "legal")
        self.assertEqual((doc_type, tone_key, overridden), ("email", "legal", False))
        self.assertEqual(tone.instruction, "법률 문서 어투로 다듬는다.")

    def test_added_doc_type_forces_its_tone(self):
        self._serve(body=json.dumps(_ADMIN_POLICY, ensure_ascii=False))
        doc_type, tone_key, overridden, policy, _tone = resolve_policy("contract", "polite")
        self.assertEqual((doc_type, tone_key, overridden), ("contract", "legal", True))
        self.assertEqual(policy.extra_instruction, "조항 번호를 바꾸지 않는다.")

    def test_builtin_tones_survive(self):
        """**병합이지 대체가 아니다.** 톤 하나를 등록했다고 내장 셋이 사라지면 안 된다."""
        self._serve(body=json.dumps(_ADMIN_POLICY, ensure_ascii=False))
        codes = [t["code"] for t in tone_choices()]
        self.assertIn("polite", codes)
        self.assertIn("report", codes)

    def test_disabled_builtin_tone_is_hidden(self):
        self._serve(body=json.dumps(_ADMIN_POLICY, ensure_ascii=False))
        self.assertNotIn("friendly", [t["code"] for t in tone_choices()])
        # 감춘 톤을 요청하면 기본 톤으로 떨어지되 **정책 강제가 아니다**.
        self.assertEqual(resolve_policy("email", "friendly")[1], DEFAULT_TONE)

    def test_builtin_forced_tone_is_not_weakened(self):
        """관리자 톤을 추가해도 내장 강제군(`고객발송문구`)은 그대로 강제한다."""
        self._serve(body=json.dumps(_ADMIN_POLICY, ensure_ascii=False))
        self.assertEqual(resolve_policy("customer_notice", "legal")[1:3], ("polite", True))

    # ── 실패해도 죽지 않는가 ────────────────────────────────────

    def test_broken_json_falls_back_without_raising(self):
        """관리자가 JSON 을 잘못 쓰는 것은 흔하다. 그때 글다듬이가 멈추면 안 된다."""
        self._serve(body="{ 이건 JSON 이 아니다")
        self.assertEqual([t["code"] for t in tone_choices()],
                         ["polite", "friendly", "report"])
        self.assertEqual(policy_source()["reason"], "invalid_json")

    def test_http_failure_reports_status(self):
        """404(ID 오기입)와 5xx(장애)는 관리자가 할 일이 다르다."""
        self._serve(status=404)
        self.assertEqual(policy_source()["reason"], "fetch_failed_404")

    def test_api_error_code_is_not_treated_as_success(self):
        """가이드 §10.5 는 `code != 0` 을 실패로 규정한다 — 200 이어도 실패다."""
        self._serve(code=7, body=json.dumps(_ADMIN_POLICY, ensure_ascii=False))
        self.assertEqual(policy_source()["reason"], "api_error")

    def test_item_without_instruction_is_rejected_and_counted(self):
        """지시문 없는 톤을 받아들이면 **톤 지시가 통째로 빠진 프롬프트**가 돌고,
        그 결과는 형식상 정상 응답으로 내려간다. 기각하고 건수를 노출한다."""
        self._serve(body=json.dumps({"tones": [{"code": "empty", "label": "빈 톤"}]}))
        self.assertNotIn("empty", [t["code"] for t in tone_choices()])
        self.assertEqual(policy_source()["rejected"], {"tone_instruction_missing": 1})

    def test_unconfigured_is_not_an_error(self):
        """미설정은 정상 축퇴 경로다 — 내장 목록으로 돌고 사유만 남긴다."""
        policy_store.Config.policy_prompt_id = staticmethod(lambda: "")
        policy_store.clear_cache()
        self.assertEqual(policy_source()["reason"], "not_configured")
        self.assertEqual(len(tone_choices()), 3)

    # ── 캐시 ────────────────────────────────────────────────

    def test_result_is_cached_and_reload_refetches(self):
        """매 요청 HTTP 를 때리면 화면 진입이 admin-api 지연에 묶인다. 그렇다고 무한
        캐시면 관리자가 리비전을 운영 반영해도 재기동 전까지 안 바뀐다."""
        api = self._serve(body=json.dumps(_ADMIN_POLICY, ensure_ascii=False))
        tone_choices()
        tone_choices()
        self.assertEqual(api.calls, 1)
        policy_store.reload()
        self.assertEqual(api.calls, 2)

    def test_doc_type_choices_include_admin_entry(self):
        self._serve(body=json.dumps(_ADMIN_POLICY, ensure_ascii=False))
        self.assertIn("contract", [d["code"] for d in doc_type_choices()])


if __name__ == "__main__":
    unittest.main()
