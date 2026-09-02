"""doc_prefill — 업로드 문서로 빈 항목을 자동 채우는 경로 (2026-08-31 요구 변경).

**onprem 운영 코드를 직접 태운다** (`onprem/codeserving/SFR-006_template_fill`).

이 파일이 지키는 계약은 넷이다:

1. **조각 분할은 글자를 버리지 않는다.** 버리면 그 구간의 값이 후보에서 조용히 사라진다.
2. **빈 항목만 채운다.** 사용자가 이미 넣은 값을 문서가 덮으면, 사용자는 자기 값이
   사라진 것을 화면에서 우연히 발견한다 (요구 확정: 절대 안 덮는다).
3. **다 채우면 남은 조각을 부르지 않는다.** 조각 수가 곧 LLM 비용이 되지 않게 하는
   유일한 장치다.
4. **화이트리스트 밖 항목명은 들어오지 않는다.** 대화 경로와 같은 판정기를 태운다.

LLM 은 대본 대역으로 갈아 끼운다 — 배포 단위 **바깥**에서 꽂으므로 운영 코드에 테스트용
분기가 생기지 않는다(`onprem/` 규칙). `doc_prefill` 이 `from .llm import llm_call_async`
로 **이름을 복사**해 갔으므로 그 모듈 속성을 바꿔야 한다. 원본만 갈아 끼우면 복사본이
계속 쓰이고, 이 경로는 실패해도 예외를 올리지 않으므로 **점검이 조용히 통과한다.**
"""

import asyncio
import json
import types
import unittest

from . import onprem_path  # noqa: F401 - import 부작용으로 sys.path 를 세운다

from template_fill import doc_prefill  # noqa: E402
from template_fill.config import Config  # noqa: E402


class _Spec:
    """`hwpx_fields.FieldSpec` 에서 이 경로가 읽는 것만 가진 최소 대역.

    실물 `FieldSpec` 은 위치(occurrence)까지 들고 있어 hwpx 를 만들어야 하는데, 이
    모듈은 `name`·`guide`·`filled` 만 본다 — 그 셋이 계약이다.
    """

    def __init__(self, name: str, guide: str = "", filled: bool = False):
        self.name = name
        self.guide = guide
        self.filled = filled


class _Script:
    """`llm_call_async` 자리에 꽂히는 대역. 대본을 순서대로 돌려준다."""

    def __init__(self, *payloads, fail_after: int = -1):
        self.queue = [json.dumps(p, ensure_ascii=False) for p in payloads]
        self.prompts: list = []
        self.fail_after = fail_after

    async def __call__(self, system_prompt, user_prompt, **_kwargs):
        self.prompts.append(user_prompt)
        if 0 <= self.fail_after <= len(self.prompts) - 1:
            return types.SimpleNamespace(
                ok=False, content="", error_type="APITimeoutError", is_transport_error=True
            )
        content = self.queue.pop(0) if self.queue else "{}"
        return types.SimpleNamespace(
            ok=True, content=content, error_type="", is_transport_error=False
        )


SPECS = [_Spec("제목"), _Spec("작성자"), _Spec("기간", guide="YYYY. M. D. ~ YYYY. M. D.")]
ALLOWED = {"제목", "작성자", "기간"}


def _run(script, document: str, existing=None, specs=None):
    saved = doc_prefill.llm_call_async
    doc_prefill.llm_call_async = script
    try:
        return asyncio.run(
            doc_prefill.prefill_from_document(
                specs if specs is not None else SPECS,
                ALLOWED,
                document,
                existing or {},
            )
        )
    finally:
        doc_prefill.llm_call_async = saved


class SplitDocumentTest(unittest.TestCase):
    def test_nothing_is_dropped(self):
        text = "\n".join(f"{i}번째 줄입니다." for i in range(40))
        chunks = doc_prefill.split_document(text, 60)
        self.assertGreater(len(chunks), 1, "나누지 않았다면 이 판정이 의미가 없다")
        joined = "".join(chunks).replace("\n", "")
        self.assertEqual(joined, text.replace("\n", ""), "글자가 사라졌다")

    def test_budget_is_honored(self):
        text = "\n".join(f"{i}번째 줄입니다." for i in range(40))
        for chunk in doc_prefill.split_document(text, 60):
            self.assertLessEqual(len(chunk), 60)

    def test_heading_starts_a_new_chunk(self):
        text = "가나다라마바사아자차" * 5 + "\n## 두 번째 절\n내용입니다."
        chunks = doc_prefill.split_document(text, 70)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(chunks[1].startswith("## 두 번째 절"))

    def test_overlong_line_is_split_not_dropped(self):
        # 한 줄 HTML 표가 이 모양이다 — 자르지 않으면 조각 하나가 상한을 넘겨
        # LLM 이 뒤를 잘라 버리고, 그 절단은 우리에게 보이지 않는다.
        line = "<table><tbody>" + "가" * 300 + "</tbody></table>"
        chunks = doc_prefill.split_document(line, 100)
        self.assertEqual("".join(chunks), line)

    def test_empty_document_yields_no_chunk(self):
        self.assertEqual(doc_prefill.split_document("   \n\n ", 100), [])


class PrefillTest(unittest.TestCase):
    def setUp(self) -> None:
        self._chars = Config.DOC_CHUNK_CHARS
        self._chunks = Config.DOC_MAX_CHUNKS

    def tearDown(self) -> None:
        Config.DOC_CHUNK_CHARS = self._chars
        Config.DOC_MAX_CHUNKS = self._chunks

    def test_values_are_taken_from_the_document(self):
        script = _Script({"updates": {"제목": "통합 플랫폼 구축", "작성자": "왕주영"}})
        outcome = _run(script, "제 목 : 통합 플랫폼 구축\n작성자 : 왕주영")
        self.assertEqual(outcome.values, {"제목": "통합 플랫폼 구축", "작성자": "왕주영"})
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.chunks_called, 1)

    def test_existing_value_is_never_overwritten(self):
        """요구 확정 — 사용자가 이미 넣은 값은 절대 덮지 않는다."""
        script = _Script({"updates": {"제목": "문서의 제목", "작성자": "왕주영"}})
        outcome = _run(script, "제 목 : 문서의 제목", existing={"제목": "사용자의 제목"})
        self.assertEqual(outcome.values, {"작성자": "왕주영"}, "사용자 값을 덮었다")
        self.assertEqual(outcome.conflicts, 1, "덮으려 한 사실을 세지 않았다")

    def test_filled_field_is_not_asked(self):
        """템플릿에 원래 값이 적혀 있던 항목(`spec.filled`)도 대상이 아니다."""
        specs = [_Spec("제목", filled=True), _Spec("작성자")]
        script = _Script({"updates": {"작성자": "왕주영"}})
        outcome = _run(script, "작성자 : 왕주영", specs=specs)
        self.assertNotIn("제목", script.prompts[0], "이미 채워진 항목을 프롬프트에 실었다")
        self.assertEqual(outcome.values, {"작성자": "왕주영"})

    def test_conversation_values_are_not_in_the_prompt(self):
        """대화로 이미 채운 항목은 **프롬프트에서 빠진다** (2026-09-02).

        `spec.filled`(템플릿에 원래 적혀 있던 값)만 빼던 것이 아니다 — 대화 중간에도
        파일을 올릴 수 있게 되면서 `existing` 이 대개 차 있고, 그 항목을 실으면 모델이
        같은 값을 문서 표현으로 고쳐 다시 준다. 우리는 그것을 버리므로(덮어쓰기 금지)
        **토큰만 든다.** 덮지 않는다는 보장 자체는 아래 `conflicts` 층이 따로 진다.
        """
        script = _Script({"updates": {"작성자": "왕주영"}})
        _run(script, "작성자 : 왕주영", existing={"제목": "대화로 넣은 제목"})
        self.assertNotIn("제목", script.prompts[0], "이미 채운 항목을 프롬프트에 실었다")
        self.assertIn("작성자", script.prompts[0], "남은 항목이 프롬프트에서 빠졌다")

    def test_no_pending_field_means_no_call(self):
        """빈 항목이 없으면 **LLM 을 아예 부르지 않는다** (2026-09-02).

        항목을 다 채운 뒤 파일을 올리는 것이 이제는 정상 흐름이다. 부르면 값이 전부
        `conflicts` 로 버려지므로 비용만 든다. `/chat/prefill` 이 같은 판정을 게이트로
        한 번 더 하지만(`no_pending_fields`), **여기서도 성립해야** 그 게이트를 지나
        들어오는 경로에서 새지 않는다.
        """
        script = _Script({"updates": {"제목": "문서의 제목"}})
        outcome = _run(
            script,
            "제 목 : 문서의 제목",
            existing={"제목": "a", "작성자": "b", "기간": "c"},
        )
        self.assertEqual(outcome.chunks_called, 0, "채울 자리가 없는데 LLM 을 불렀다")
        self.assertEqual(outcome.values, {})

    def test_unknown_field_name_is_rejected(self):
        script = _Script({"updates": {"제목": "ok", "없는항목": "버려져야 함"}})
        outcome = _run(script, "본문")
        self.assertEqual(outcome.values, {"제목": "ok"})
        self.assertEqual(outcome.rejected, 1, "기각 건수가 없으면 환각률을 셀 수 없다")

    def test_earlier_chunk_wins(self):
        """앞 조각이 이긴다 — 문서 앞쪽(표지·개요)이 값을 정면으로 적어 둔다."""
        Config.DOC_CHUNK_CHARS = 30
        script = _Script(
            {"updates": {"제목": "앞 조각의 제목"}},
            {"updates": {"제목": "뒤 조각의 제목", "작성자": "왕주영"}},
        )
        document = "제 목 : 앞 조각의 제목\n" + ("본문 문장입니다.\n" * 4) + "작성자 : 왕주영"
        outcome = _run(script, document)
        self.assertEqual(outcome.values.get("제목"), "앞 조각의 제목")
        self.assertEqual(outcome.values.get("작성자"), "왕주영")
        self.assertGreaterEqual(outcome.conflicts, 1)
        self.assertNotIn("제목", script.prompts[1], "채운 항목을 뒤 조각에 또 물었다")

    def test_stops_calling_once_everything_is_filled(self):
        """다 채우면 남은 조각을 부르지 않는다 — 조각 수가 곧 비용이 되지 않게."""
        Config.DOC_CHUNK_CHARS = 30
        script = _Script({"updates": {"제목": "ㄱ", "작성자": "ㄴ", "기간": "ㄷ"}})
        document = "\n".join(f"{i}번째 줄입니다." for i in range(20))
        outcome = _run(script, document)
        self.assertGreater(outcome.chunk_count, 1, "조각이 하나면 이 판정이 의미가 없다")
        self.assertEqual(outcome.chunks_called, 1, "다 채웠는데 남은 조각을 또 불렀다")

    def test_chunk_cap_limits_calls(self):
        Config.DOC_CHUNK_CHARS = 30
        Config.DOC_MAX_CHUNKS = 2
        script = _Script({"updates": {}}, {"updates": {}}, {"updates": {}})
        document = "\n".join(f"{i}번째 줄입니다." for i in range(20))
        outcome = _run(script, document)
        self.assertEqual(outcome.chunk_count, 2)
        self.assertLessEqual(outcome.chunks_called, 2)

    def test_empty_updates_is_not_a_failure(self):
        """문서에 항목 값이 없으면 `{}` 가 정상 답이다.

        실패로 보면 사용자에게 "문서를 못 읽었다" 고 잘못 말하고, 그러면 사용자는 파일을
        바꿔 다시 올린다 — 고칠 것이 없는데 시키는 셈이다.
        """
        outcome = _run(_Script({"updates": {}}), "항목과 무관한 본문입니다.")
        self.assertEqual(outcome.values, {})
        self.assertTrue(outcome.ok)

    def test_llm_failure_is_reported_not_raised(self):
        """실패해도 예외를 올리지 않는다 — 대화로 채우는 원래 흐름을 막지 않는다."""
        outcome = _run(_Script(fail_after=0), "제 목 : 무엇")
        self.assertEqual(outcome.values, {})
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.is_transport_error)

    def test_config_missing_stops_at_first_chunk(self):
        """재시도로 풀리지 않는 배포 문제라 조각 수만큼 두드리지 않는다."""
        Config.DOC_CHUNK_CHARS = 30

        async def config_missing(_system, _user, **_kwargs):
            return types.SimpleNamespace(
                ok=False, content="", error_type=doc_prefill.CONFIG_MISSING,
                is_transport_error=False,
            )

        document = "\n".join(f"{i}번째 줄입니다." for i in range(20))
        saved = doc_prefill.llm_call_async
        doc_prefill.llm_call_async = config_missing
        try:
            outcome = asyncio.run(
                doc_prefill.prefill_from_document(SPECS, ALLOWED, document, {})
            )
        finally:
            doc_prefill.llm_call_async = saved
        self.assertEqual(outcome.chunks_called, 1, "설정 부재인데 조각마다 불렀다")
        self.assertTrue(outcome.config_missing)

    def test_no_document_no_call(self):
        script = _Script({"updates": {"제목": "안 불려야 한다"}})
        outcome = _run(script, "   ")
        self.assertEqual(script.prompts, [])
        self.assertEqual(outcome.values, {})


if __name__ == "__main__":
    unittest.main()
