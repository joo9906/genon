"""doc_prefill — 업로드 문서로 빈 항목을 자동 채우는 경로.

**`final/` 운영 코드를 직접 태운다** (`final/SFR-006/request`).

이 파일이 지키는 계약은 넷이다:

1. **조각 분할은 글자를 버리지 않는다.** 버리면 그 구간의 값이 후보에서 조용히 사라진다.
2. **빈 항목만 채운다.** 사용자가 이미 넣은 값을 문서가 덮으면, 사용자는 자기 값이
   사라진 것을 화면에서 우연히 발견한다 (요구 확정: 절대 안 덮는다).
3. **다 채우면 남은 조각을 부르지 않는다.** 조각 수가 곧 LLM 비용이 되지 않게 하는
   유일한 장치다.
4. **화이트리스트 밖 항목명은 들어오지 않는다.** 대화 경로와 같은 판정기를 태운다.

LLM 은 대본 대역으로 갈아 끼운다 — 배포 단위 **바깥**에서 꽂으므로 운영 코드에 테스트용
분기가 생기지 않는다(배포 단위 규칙). `doc_prefill` 이 `from .llm import llm_call_async`
로 **이름을 복사**해 갔으므로 그 모듈 속성을 바꿔야 한다. 원본만 갈아 끼우면 복사본이
계속 쓰이고, 이 경로는 실패해도 예외를 올리지 않으므로 **점검이 조용히 통과한다.**
"""

import asyncio
import json
import types
import unittest

from . import final_path  # noqa: F401 - import 부작용으로 sys.path 를 세운다

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


class _Streamed:
    """`llm_stream_async` 자리 — 대본(`_Script`)의 응답을 `step` 글자씩 흘린다.

    `done_after` 글자를 흘린 뒤 끊으면 "흘린 뒤 끊긴 스트림" 이다. `unsupported` 면
    게이트웨이가 스트리밍을 거절한 배포다(한 글자도 안 흘린다).
    """

    def __init__(self, script, step: int = 3, break_after: int = -1, unsupported: bool = False):
        self.script = script
        self.step = step
        self.break_after = break_after
        self.unsupported = unsupported
        self.calls = 0

    async def __call__(self, system_prompt, user_prompt, on_delta):
        self.calls += 1
        if self.unsupported:
            return types.SimpleNamespace(
                ok=False, content="", error_type=doc_prefill.STREAM_UNSUPPORTED,
                is_transport_error=False,
            )
        result = await self.script(system_prompt, user_prompt)
        if not result.ok:
            return result
        text = result.content
        if 0 <= self.break_after:
            text = text[: self.break_after]
        for start in range(0, len(text), self.step):
            await on_delta(text[start:start + self.step])
        if 0 <= self.break_after:
            return types.SimpleNamespace(
                ok=False, content="", error_type="ReadError", is_transport_error=True
            )
        return result


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


class PrefillProgressTest(unittest.TestCase):
    """`on_progress` 콜백 — `/chat/prefill/stream` 이 SSE 진행 문구를 짓는 재료다
    (2026-09-22 신규). 콜백은 도메인 계층을 텍스트에서 떼어 두려고 **구조화된 dict**
    만 준다(`{status, index, total, filled}`) — 문구는 `chat_api._prefill_progress_text`
    가 짓는다.
    """

    def setUp(self) -> None:
        self._chars = Config.DOC_CHUNK_CHARS
        self._chunks = Config.DOC_MAX_CHUNKS

    def tearDown(self) -> None:
        Config.DOC_CHUNK_CHARS = self._chars
        Config.DOC_MAX_CHUNKS = self._chunks

    def _run_with_progress(self, script, document: str, existing=None, specs=None, stream=None):
        events: list = []

        async def on_progress(event: dict) -> None:
            events.append(dict(event))

        saved = doc_prefill.llm_call_async, doc_prefill.llm_stream_async
        doc_prefill.llm_call_async = script
        doc_prefill.llm_stream_async = stream or _Streamed(script)
        try:
            outcome = asyncio.run(
                doc_prefill.prefill_from_document(
                    specs if specs is not None else SPECS,
                    ALLOWED, document, existing or {}, on_progress=on_progress,
                )
            )
        finally:
            doc_prefill.llm_call_async, doc_prefill.llm_stream_async = saved
        return outcome, events

    def test_on_progress_is_optional(self):
        """콜백이 없으면(비스트리밍 `/chat/prefill`) 아무 일도 하지 않는다."""
        outcome = _run(_Script({"updates": {"제목": "ok"}}), "제 목 : ok")
        self.assertEqual(outcome.values, {"제목": "ok"})

    def test_start_and_done_bracket_each_chunk(self):
        Config.DOC_CHUNK_CHARS = 30
        # 항목을 둘로 좁힌다(기간을 뺀다) — 두 조각이 둘 다 채워지면 세 번째 조각이
        # 실제로 있어도 안 부르므로 `chunks_called == 2` 가 조각 실측값과 무관해진다.
        specs = [_Spec("제목"), _Spec("작성자")]
        script = _Script(
            {"updates": {"제목": "앞 조각의 제목"}},
            {"updates": {"작성자": "왕주영"}},
        )
        document = "제 목 : 앞 조각의 제목\n" + ("본문 문장입니다.\n" * 4) + "작성자 : 왕주영"
        outcome, events = self._run_with_progress(script, document, specs=specs)
        self.assertEqual(outcome.chunks_called, 2)
        # 항목 줄(`field`)은 start 와 done 사이에 끼므로 괄호 모양은 그것을 빼고 본다.
        statuses = [(e["index"], e["status"]) for e in events if e["status"] != "field"]
        # 조각마다 start 가 done 보다 먼저다 — 진행 문구가 결과보다 앞서 나가야
        # "지금 확인 중" 이라는 뜻이 선다.
        self.assertEqual(statuses[0], (1, "start"))
        self.assertEqual(statuses[1], (1, "done"))
        self.assertEqual(statuses[2], (2, "start"))
        self.assertEqual(statuses[3], (2, "done"))
        dones = [e for e in events if e["status"] == "done"]
        self.assertEqual(dones[0]["filled"], ["제목"])
        self.assertEqual(dones[1]["filled"], ["작성자"])
        # 모든 이벤트가 같은 `total` 을 본다(조각 수가 도중에 바뀌지 않는다) — 문서를
        # 실제로 나눈 조각 수(`chunk_count`)가 정답이지, 여기서 두 번만 불렀다고
        # `total` 도 2 라고 가정하지 않는다(항목을 다 채워 세 번째 조각은 안 불렀을 뿐).
        self.assertTrue(all(e["total"] == outcome.chunk_count for e in events))

    def test_conflict_is_not_reported_as_filled(self):
        """프롬프트에서 뺐는데도 온 값(conflict)은 `filled` 에 넣지 않는다.

        넣으면 진행 문구가 "반영: 제목" 을 흘리는데 실제로는 버려진 값이라 사용자가
        틀린 사실을 안내받는다.
        """
        script = _Script({"updates": {"제목": "덮으려는 값"}})
        outcome, events = self._run_with_progress(
            script, "제 목 : 덮으려는 값", existing={"제목": "이미 있는 값"}
        )
        self.assertEqual(outcome.conflicts, 1)
        done = next(e for e in events if e["status"] == "done")
        self.assertEqual(done["filled"], [])
        # 흘리는 도중에도 막혀야 한다 — 안 막으면 버릴 값이 화면에 먼저 나간다.
        self.assertFalse([e for e in events if e["status"] == "field"])

    def test_failed_chunk_reports_status(self):
        script = _Script(fail_after=0)
        outcome, events = self._run_with_progress(script, "제 목 : 무엇")
        self.assertFalse(outcome.ok)
        statuses = [e["status"] for e in events]
        self.assertEqual(statuses, ["start", "failed"])

    def test_no_progress_after_everything_is_filled(self):
        """다 채우면 남은 조각을 안 부르므로 그 조각의 진행 이벤트도 없다."""
        Config.DOC_CHUNK_CHARS = 30
        script = _Script({"updates": {"제목": "ㄱ", "작성자": "ㄴ", "기간": "ㄷ"}})
        document = "\n".join(f"{i}번째 줄입니다." for i in range(20))
        outcome, events = self._run_with_progress(script, document)
        self.assertGreater(outcome.chunk_count, 1, "조각이 하나면 이 판정이 의미가 없다")
        self.assertEqual(outcome.chunks_called, 1)
        # start/done 한 쌍뿐이다 — 두 번째 조각은 아예 시작 이벤트도 없어야 한다.
        self.assertEqual([e["status"] for e in events if e["status"] != "field"], ["start", "done"])


class PrefillStreamTest(unittest.TestCase):
    """항목이 닫히는 대로 값을 흘린다 (2026-09-29). 조각이 하나뿐인 보통 문서에서 LLM
    호출이 끝날 때까지 화면이 멈추던 자리다. 흘린 줄과 최종 채택이 어긋나면 안 된다."""

    _run = PrefillProgressTest._run_with_progress

    def test_fields_stream_before_done_with_values(self):
        script = _Script({"updates": {"제목": "2026 사업계획", "작성자": "왕주영"}})
        outcome, events = self._run(script, "제 목 : 2026 사업계획\n작성자 : 왕주영")
        statuses = [e["status"] for e in events]
        self.assertEqual(statuses, ["start", "field", "field", "done"])
        fields = [(e["name"], e["value"]) for e in events if e["status"] == "field"]
        self.assertEqual(fields, [("제목", "2026 사업계획"), ("작성자", "왕주영")])
        self.assertEqual(outcome.values, {"제목": "2026 사업계획", "작성자": "왕주영"})
        # done 은 이미 흘린 항목을 알려 호출부가 두 번 말하지 않게 한다.
        self.assertEqual(sorted(events[-1]["announced"]), ["작성자", "제목"])

    def test_whitelist_applies_while_streaming(self):
        script = _Script({"updates": {"없는항목": "x", "제목": "ok"}})
        _outcome, events = self._run(script, "제 목 : ok")
        self.assertEqual([e["name"] for e in events if e["status"] == "field"], ["제목"])

    def test_one_char_deltas_yield_the_same_pairs(self):
        """델타가 한 글자씩 와도(키 · 값 · 이스케이프 한가운데서 끊겨도) 같은 쌍이다."""
        script = _Script({"updates": {"제목": "따옴표 \"안\" 과 \\ 역슬래시", "작성자": "왕주영"}})
        outcome, events = self._run(script, "문서", stream=_Streamed(script, step=1))
        fields = {e["name"]: e["value"] for e in events if e["status"] == "field"}
        self.assertEqual(fields, outcome.values)

    def test_unsupported_stream_falls_back_once(self):
        """스트리밍을 안 받는 배포 — 비스트리밍으로 채우고, 남은 조각은 다시 묻지 않는다."""
        Config_chars = Config.DOC_CHUNK_CHARS
        Config.DOC_CHUNK_CHARS = 30
        try:
            specs = [_Spec("제목"), _Spec("작성자")]
            script = _Script({"updates": {"제목": "ㄱ"}}, {"updates": {"작성자": "ㄴ"}})
            stream = _Streamed(script, unsupported=True)
            document = "제 목 : ㄱ\n" + ("본문 문장입니다.\n" * 4) + "작성자 : ㄴ"
            outcome, events = self._run(script, document, specs=specs, stream=stream)
        finally:
            Config.DOC_CHUNK_CHARS = Config_chars
        self.assertEqual(outcome.values, {"제목": "ㄱ", "작성자": "ㄴ"})
        self.assertEqual(stream.calls, 1)
        self.assertFalse([e for e in events if e["status"] == "field"])
        self.assertEqual([e["announced"] for e in events if e["status"] == "done"], [[], []])

    def test_broken_stream_discards_announced(self):
        """흘린 뒤 끊기면 그 값은 채우지 않고, 흘린 항목을 `discarded` 로 알린다."""
        script = _Script({"updates": {"제목": "먼저 닫힌 값", "작성자": "아직 안 온 값"}})
        content = json.dumps({"updates": {"제목": "먼저 닫힌 값", "작성자": "아직 안 온 값"}},
                             ensure_ascii=False)
        cut = content.index("아직")
        outcome, events = self._run(script, "문서", stream=_Streamed(script, break_after=cut))
        self.assertEqual(outcome.values, {})
        self.assertEqual([e["name"] for e in events if e["status"] == "field"], ["제목"])
        failed = next(e for e in events if e["status"] == "failed")
        self.assertEqual(failed["discarded"], ["제목"])


class UpdatesScannerTest(unittest.TestCase):
    def _pairs(self, text: str, step: int = 1) -> list:
        scanner = doc_prefill._UpdatesScanner()
        pairs: list = []
        for start in range(0, len(text), step):
            pairs.extend(scanner.feed(text[start:start + step]))
        return pairs

    def test_number_waits_for_its_end(self):
        """`12` 가 다음 델타에서 `123` 이 될 수 있다 — 뒤가 닫혀야 꺼낸다."""
        scanner = doc_prefill._UpdatesScanner()
        self.assertEqual(scanner.feed('{"updates": {"건수": 12'), [])
        self.assertEqual(scanner.feed('3}}'), [("건수", 123)])

    def test_code_fence_and_prefix(self):
        text = '```json\n{"updates": {"제목": "a", "작성자": "b"}}\n```'
        self.assertEqual(self._pairs(text), [("제목", "a"), ("작성자", "b")])

    def test_empty_updates(self):
        self.assertEqual(self._pairs('{"updates": {}}'), [])

    def test_malformed_stops_quietly(self):
        self.assertEqual(self._pairs('{"updates": {"제목" "a", "작성자": "b"}}'), [])


class ProgressTextTest(unittest.TestCase):
    """진행 줄 문구 (`chat_api._prefill_progress_text`) — 값까지 한 줄에."""

    def setUp(self) -> None:
        from template_fill import chat_api

        self.text = chat_api._prefill_progress_text

    def test_field_line_shows_value(self):
        line = self.text({"status": "field", "index": 1, "total": 1,
                          "name": "제목", "value": "2026 사업계획"})
        self.assertEqual(line, "✔ 제목: 2026 사업계획\n")

    def test_long_value_is_cut_to_one_line(self):
        line = self.text({"status": "field", "index": 1, "total": 1,
                          "name": "개요", "value": "줄\n바꿈 " + "가" * 200})
        self.assertNotIn("\n", line.rstrip("\n"))
        self.assertTrue(line.rstrip("\n").endswith("…"))

    def test_done_only_says_what_was_not_streamed(self):
        line = self.text({"status": "done", "index": 1, "total": 1,
                          "filled": ["제목", "작성자"],
                          "values": {"제목": "a", "작성자": "b"}, "announced": ["제목"]})
        self.assertEqual(line, "✔ 작성자: b\n")

    def test_failed_after_streaming_says_values_were_dropped(self):
        line = self.text({"status": "failed", "index": 1, "total": 1, "discarded": ["제목"]})
        self.assertIn("반영하지 않았습니다", line)


class OverwriteTest(unittest.TestCase):
    """"문서 내용으로 바꿔줘" 턴 (`overwrite=True`) — 찬 항목도 묻고, 온 값을 버리지 않는다.
    기본(덮지 않음)은 위 테스트들이 지킨다."""

    def _run(self, script, existing, *, overwrite, stream=False):
        events: list = []

        async def on_progress(event: dict) -> None:
            events.append(dict(event))

        saved = doc_prefill.llm_call_async, doc_prefill.llm_stream_async
        doc_prefill.llm_call_async = script
        doc_prefill.llm_stream_async = _Streamed(script)
        try:
            outcome = asyncio.run(
                doc_prefill.prefill_from_document(
                    SPECS, ALLOWED, "제 목 : 문서 제목", existing,
                    on_progress=on_progress if stream else None,
                    overwrite=overwrite,
                )
            )
        finally:
            doc_prefill.llm_call_async, doc_prefill.llm_stream_async = saved
        return outcome, events

    def test_filled_field_is_asked_and_replaced(self):
        script = _Script({"updates": {"제목": "문서 제목", "작성자": "홍길동"}})
        outcome, _ = self._run(script, {"제목": "사용자 제목"}, overwrite=True)
        self.assertEqual(outcome.values, {"제목": "문서 제목", "작성자": "홍길동"})
        self.assertEqual(outcome.conflicts, 0)

    def test_everything_filled_still_calls_llm(self):
        """다 찬 뒤의 "문서로 바꿔줘" 가 정상 흐름이다 — 빈 항목이 없다고 멈추면 안 된다."""
        script = _Script({"updates": {"기간": "2026. 1. 1. ~ 2026. 12. 31."}})
        existing = {"제목": "a", "작성자": "b", "기간": "c"}
        outcome, _ = self._run(script, existing, overwrite=True)
        self.assertEqual(len(script.prompts), 1)
        self.assertEqual(outcome.values, {"기간": "2026. 1. 1. ~ 2026. 12. 31."})

    def test_filled_field_is_streamed_too(self):
        """흘리는 판정도 같은 보호 목록을 본다 — 갈리면 채운 값이 화면에 안 나온다."""
        script = _Script({"updates": {"제목": "문서 제목"}})
        _outcome, events = self._run(script, {"제목": "사용자 제목"}, overwrite=True, stream=True)
        self.assertEqual([e["name"] for e in events if e["status"] == "field"], ["제목"])


class OverwriteReplyTest(unittest.TestCase):
    """덮어쓰기 턴의 답변 — 무엇이 밀렸는지(`이전 → 새`)를 말한다."""

    def _reply(self, prefilled, previous, **kwargs):
        from template_fill.chat_reply import _prefill_notices

        return "\n".join(_prefill_notices(prefilled, False, previous=previous, **kwargs))

    def test_changed_value_shows_before_and_after(self):
        text = self._reply({"제목": "문서 제목"}, {"제목": "사용자 제목"}, overwrite=True)
        self.assertIn("1개 항목을 바꿨습니다", text)
        self.assertIn("사용자 제목 → 문서 제목", text)

    def test_new_and_changed_are_listed_apart(self):
        text = self._reply(
            {"제목": "문서 제목", "작성자": "홍길동"}, {"제목": "사용자 제목"}, overwrite=True
        )
        self.assertIn("1개 항목을 채웠습니다", text)
        self.assertIn("1개 항목을 바꿨습니다", text)

    def test_nothing_found_is_said(self):
        text = self._reply({}, {"제목": "a"}, overwrite=True)
        self.assertIn("찾지 못해 바뀐 항목이 없습니다", text)

    def test_overwrite_without_document_asks_for_one(self):
        text = self._reply({}, {}, overwrite=True, skipped_reason="no_document")
        self.assertIn("먼저 문서를 올려 주세요", text)


if __name__ == "__main__":
    unittest.main()
