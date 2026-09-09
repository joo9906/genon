"""관리자가 고친 프롬프트가 실제로 적용되는가 (2026-09-07 개정).

고객사 관리자가 GenOS `도구 > 프롬프트 라이브러리` 에서 문구를 고치면 **재배포 없이**
반영돼야 한다. 가이드 §10.5 가 정한 경로이고, §10.10.2 는 이 리소스를 "비개발자도
변경할 수 있어" 라고 소개한다.

## 2026-09-07 에 방식이 바뀌었다 — JSON 문서 한 건 → 이름=ID 매칭

그전에는 프롬프트 **한 건**의 본문에 `{"tones": [...], "doc_types": [...]}` 를 담고
코드서빙이 `json.loads` 로 읽었다(`text_polish/policy_store.py`). 요구가 "프롬프트는
전부 라이브러리에서 당겨 쓰고 **코드서빙 안에서 JSON 을 해석하지 않는다**" 로 바뀌어
그 파일을 걷어냈다. 지금 배선은 이름=ID 하나다:

    POLISH_PROMPT_IDS=system=43,system_polite=51,doc_type_debt_reason=62

| 이름 | 본문 | 덮는 것 |
|---|---|---|
| `system` | 시스템 프롬프트 골격 | `system.j2` |
| `system_<tone>` | 그 톤 전용 시스템 프롬프트 | 있으면 골격 대신 이것을 쓴다 |
| `doc_type_<code>` | 문서유형 추가 지시문 | `DOC_TYPE_POLICIES[code].extra_instruction` |

**목록·라벨·강제 톤은 라이브러리로 오지 않는다** — 프롬프트 본문은 문장 하나라 그런
값을 담을 수 없다. 그 셋은 `tone_presets.py` 표가 계속 들고 있다.

## 여기서 무엇을 보나

이 기능은 **조용히 실패하는 방식이 여러 개**다. 전부 예외가 아니라 "고친 문구가 반영되지
않거나, 반영됐는데 다른 것이 함께 바뀌는" 모양으로 드러난다:

1. 고친 문구가 **안 쓰인다** — 이름 규약이 어긋나면 그렇게 되고, 오류는 안 난다.
2. 전용 프롬프트를 아직 안 만든 톤에서 **요청이 선다** — 폴백이 없으면 그렇다.
   톤 하나를 안 만들었다는 이유로 기능이 통째로 죽는다.
3. 문서유형 지시문을 고쳤더니 **강제 톤이 사라진다** — 라벨·강제 톤을 표에서 물려받지
   않으면 그렇다. 오류가 아니라 결과물의 문체로만 드러난다.
4. 조회가 실패했는데 화면에는 옛 문구가 그대로 떠서 **"아직 등록 안 함" 과 구분되지
   않는다** — `GET /prompts` 의 `source`/`reason` 이 없으면 그렇다.

`SFR-018/tests/test_glossary_policy.py` 와 달리 **가짜 admin-api 를 배포 단위 바깥에서**
꽂는다. 운영 코드에 테스트용 분기를 만들지 않는다.
"""

import unittest

from . import onprem_path

onprem_path.install(onprem_path.TEXT_POLISH_UNIT)

import httpx  # noqa: E402

import main as polish_main  # noqa: E402
from text_polish import prompt_library  # noqa: E402
from text_polish.tone_presets import (  # noqa: E402
    DOC_TYPE_POLICIES,
    TONE_PRESETS,
    doc_type_choices,
    resolve_policy,
    tone_choices,
)

# 관리자가 등록했다고 가정할 본문들. **JSON 이 아니라 문장 그대로**다.
_BODIES = {
    "system_polite": "당신은 격식 있는 문서를 다듬는 전문가입니다. (관리자 판)",
    "doc_type_debt_reason": "사실관계만 시간 순으로 적고 추측을 쓰지 않는다. (관리자 판)",
}


class _FakeAdminApi:
    """`GET /prompt/template/{id}` 대역. 가이드 §10.5 응답 계약을 그대로 흉내 낸다."""

    def __init__(self, *, bodies=None, status=200, code=0):
        self.bodies = bodies or {}
        self.status = status
        self.code = code
        self.calls = 0

    def __call__(self, url, timeout=None):
        self.calls += 1
        request = httpx.Request("GET", url)
        if self.status != 200:
            return httpx.Response(self.status, json={}, request=request)
        # URL 끝의 ID 로 본문을 고른다 — 이름 → ID 매핑을 뒤집어 찾는다.
        prompt_id = url.rstrip("/").rsplit("/", 1)[-1]
        body = self.bodies.get(prompt_id, "")
        return httpx.Response(200, json={"code": self.code, "data": body}, request=request)


class AdminPromptTest(unittest.TestCase):
    # 이름 → ID. 값은 아무 숫자나 된다 — 코드가 ID 를 해석하지 않는다는 것이 요점이다.
    IDS = {"system_polite": "51", "doc_type_debt_reason": "62"}

    def setUp(self) -> None:
        self._real_get = prompt_library.httpx.get
        prompt_library.Config.genos_admin_api_url = staticmethod(lambda: "http://admin.test")
        prompt_library.Config.prompt_ids_raw = staticmethod(
            lambda: ",".join(f"{name}={pid}" for name, pid in self.IDS.items())
        )
        prompt_library.clear_cache()

    def tearDown(self) -> None:
        prompt_library.httpx.get = self._real_get
        prompt_library.clear_cache()

    def _serve(self, **kwargs) -> _FakeAdminApi:
        api = _FakeAdminApi(**kwargs)
        prompt_library.httpx.get = api
        return api

    def _serve_registered(self) -> _FakeAdminApi:
        """등록된 두 프롬프트를 그대로 내주는 대역."""
        return self._serve(bodies={self.IDS[name]: body for name, body in _BODIES.items()})

    # ── 덮어쓰기가 실제로 되는가 ────────────────────────────────

    def test_tone_prompt_is_used_when_registered(self):
        self._serve_registered()
        self.assertEqual(polish_main._tone_prompt_name("polite"), "system_polite")

    def test_unregistered_tone_falls_back_to_system(self):
        """**폴백이 살아 있는 것이 요점이다.**

        전용 프롬프트를 아직 안 만든 톤에서 이름만 보고 고르면 `system_objective.j2`
        파일이 없어 `PromptRenderError` 가 나고, **톤 하나를 안 만들었다는 이유로
        글다듬이가 통째로 죽는다.** 미설정은 정상 경로여야 한다.
        """
        self._serve_registered()
        self.assertEqual(polish_main._tone_prompt_name("objective"), "system")
        self.assertEqual(polish_main._tone_prompt_name(""), "system")

    def test_doc_type_instruction_is_overridden(self):
        self._serve_registered()
        self.assertEqual(
            polish_main._doc_type_instruction("debt_reason", DOC_TYPE_POLICIES["debt_reason"]),
            _BODIES["doc_type_debt_reason"],
        )

    def test_unregistered_doc_type_keeps_builtin_instruction(self):
        self._serve_registered()
        self.assertEqual(
            polish_main._doc_type_instruction("email", DOC_TYPE_POLICIES["email"]),
            DOC_TYPE_POLICIES["email"].extra_instruction,
        )

    # ── 덮어써도 함께 바뀌면 안 되는 것 ──────────────────────────

    def test_forced_tone_survives_instruction_override(self):
        """지시문을 고쳤다고 **강제 톤이 풀리면 안 된다.**

        프롬프트 본문에는 강제 톤을 담을 수 없으므로 표에서 물려받는다. 안 물려받으면
        `debt_reason` 이 사실·객관 고정을 잃고, 그 실패는 오류가 아니라 **결과물의
        문체로만** 드러난다.
        """
        self._serve_registered()
        _doc, tone, overridden, _policy, _preset = resolve_policy("debt_reason", "polite")
        self.assertEqual(tone, "objective")
        self.assertTrue(overridden)

    def test_choices_come_from_the_table_only(self):
        """목록은 라이브러리를 타지 않는다 — 등록해도 선택지가 늘거나 줄지 않는다."""
        self._serve_registered()
        self.assertEqual([t["code"] for t in tone_choices()], list(TONE_PRESETS))
        self.assertEqual([d["code"] for d in doc_type_choices()], list(DOC_TYPE_POLICIES))

    # ── 실패해도 죽지 않는다 ────────────────────────────────────

    def test_http_failure_falls_back_and_reports_status(self):
        self._serve(status=404)
        self.assertEqual(polish_main._tone_prompt_name("polite"), "system")
        rows = {row["name"]: row for row in prompt_library.status()}
        self.assertEqual(rows["system_polite"]["source"], "file")
        self.assertEqual(rows["system_polite"]["reason"], "fetch_failed_404")

    def test_api_error_code_is_not_treated_as_success(self):
        self._serve(bodies={self.IDS["system_polite"]: "본문"}, code=1)
        rows = {row["name"]: row for row in prompt_library.status()}
        self.assertEqual(rows["system_polite"]["reason"], "api_error")

    def test_empty_body_is_rejected(self):
        """빈 본문을 받아들이면 **지시문 없는 프롬프트**가 되고, 그 결과는 형식상 정상
        응답으로 내려간다."""
        self._serve(bodies={})
        rows = {row["name"]: row for row in prompt_library.status()}
        self.assertEqual(rows["system_polite"]["reason"], "empty_body")
        self.assertEqual(polish_main._tone_prompt_name("polite"), "system")

    def test_unconfigured_is_not_an_error(self):
        """**미설정은 정상 경로다.** 오류로 보이면 관리자가 고칠 것이 없는데 고치려 든다."""
        prompt_library.Config.prompt_ids_raw = staticmethod(lambda: "")
        prompt_library.clear_cache()
        self._serve(bodies={})
        self.assertEqual(prompt_library.status(), [])
        self.assertEqual(polish_main._tone_prompt_name("polite"), "system")

    def test_body_is_not_exposed(self):
        """`GET /prompts` 에 본문을 실으면 그 경로가 **지시문 유출 경로**가 된다 (3.8절)."""
        self._serve_registered()
        for row in prompt_library.status():
            self.assertNotIn("body", row)

    # ── 캐시 ────────────────────────────────────────────────

    def test_result_is_cached_and_reload_refetches(self):
        api = self._serve_registered()
        polish_main._tone_prompt_name("polite")
        first = api.calls
        polish_main._tone_prompt_name("polite")
        self.assertEqual(api.calls, first, "TTL 안에서는 다시 받지 않는다")
        prompt_library.reload()
        self.assertGreater(api.calls, first, "리로드는 다시 받는다")


if __name__ == "__main__":
    unittest.main()
