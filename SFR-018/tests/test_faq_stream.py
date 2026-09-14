"""FAQ 항목 단위 스트리밍 — 증분 파서 · 검증 순서 · SSE 전송 규약 (2026-09-11).

```
cd SFR-018 && python -m unittest tests.test_faq_stream -v
```

## 왜 이 파일이 있나

FAQ 스트리밍을 붙이면서 **세 층이 새로 생겼는데 그 층을 보는 점검이 0건이었다.**
이 저장소가 반복해서 밟은 자리다 — 글다듬이 스트리밍도, MCP 406 도, 전처리기 자동
번호도 "코드는 있는데 아무도 안 태우는" 상태로 살아남았다.

1. **증분 파서**(`markdown_items`) — 라벨이 흔들리면 항목이 통째로 기각되는데, 그
   상태는 "FAQ 가 하나도 안 나온다" 로만 드러난다.
2. **검증 순서**(`generate_faqs_stream`) — 근거·중복에서 기각될 항목이 화면에 **한
   글자도** 나가지 않아야 한다. 순서가 뒤집히면 "답이 나왔다가 사라진다" 가 된다.
3. **SSE 전송**(`faq_stream_async`) — `openai` SDK 없이 `data: {json}` 줄을 직접
   읽는다. 대역을 **배포 단위 밖에서** 꽂는다 (운영 코드에 테스트용 분기 금지).

## 형식이 프롬프트와 사본 관계다

여기 쓰는 `<<<FAQ` · `근거:` · `질문:` · `답변:` · `>>>` 는
`onprem/prompt/SFR-018_faq/md_system.txt` 와 **글자 그대로** 같아야 한다. 한쪽만
고치면 파서가 0건을 낸다.
"""

import asyncio
import json
import os
import unittest

import httpx

from . import onprem_path

onprem_path.install(onprem_path.FAQ_UNIT)

from faq import generator, markdown_items  # noqa: E402
from faq import llm as faq_llm  # noqa: E402
from faq.config import Config  # noqa: E402
from faq.llm import LlmResult  # noqa: E402


def _item(evidence: str, question: str, answer: str) -> str:
    return f"<<<FAQ\n근거: {evidence}\n질문: {question}\n답변: {answer}\n>>>"


# ══════════════════════════════════════════════════════════════════════════
# 1. 증분 파서
# ══════════════════════════════════════════════════════════════════════════

class MarkdownItemsTest(unittest.TestCase):
    """`ItemStream` — 델타를 먹여 사건을 받는다."""

    def _feed(self, text: str, size: int = 7) -> list:
        stream = markdown_items.ItemStream()
        events: list = []
        for start in range(0, len(text), size):
            events.extend(stream.feed(text[start:start + size]))
        events.extend(stream.finish())
        return events

    def test_field_order_is_evidence_question_answer(self):
        """검증을 **접두어 연산**으로 만드는 순서다 — 근거가 답변보다 먼저 닫힌다."""
        events = self._feed(_item("원문 문장이다.", "무엇인가요?", "답변입니다."))
        kinds = [event.kind for event in events]
        self.assertLess(
            kinds.index(markdown_items.EVIDENCE),
            kinds.index(markdown_items.ANSWER_DELTA),
            "근거가 답변보다 늦게 닫히면 기각될 항목이 이미 화면에 나간다",
        )
        self.assertLess(
            kinds.index(markdown_items.QUESTION),
            kinds.index(markdown_items.ANSWER_DELTA),
        )
        self.assertEqual(kinds[-1], markdown_items.ITEM_END)

    def test_answer_arrives_in_pieces_without_repeating(self):
        """답변은 줄이 끝나기 전에도 흘린다. **같은 글자를 두 번 내보내지 않는다.**"""
        events = self._feed(_item("근거 문장.", "질문?", "앞부분 그리고 뒷부분."), size=3)
        deltas = [e.text for e in events if e.kind == markdown_items.ANSWER_DELTA]
        self.assertGreater(len(deltas), 1, "한 덩어리로만 나왔다 — 증분이 아니다")
        self.assertEqual("".join(deltas), "앞부분 그리고 뒷부분.")

    def test_evidence_and_question_are_never_streamed(self):
        """근거·질문은 **검증 재료**다 — 증분으로 흘리면 기각될 항목이 보였다 사라진다."""
        events = self._feed(_item("근거 문장.", "질문?", "답변."), size=2)
        for event in events:
            if event.kind == markdown_items.ANSWER_DELTA:
                self.assertNotIn("근거 문장", event.text)
                self.assertNotIn("질문?", event.text)

    def test_missing_close_mark_still_yields_the_item(self):
        """모델이 `>>>` 를 빠뜨려도 버리지 않는다 — 최종 판정은 호출부가 한다."""
        text = "<<<FAQ\n근거: 원문.\n질문: 왜?\n답변: 그래서."
        ends = [e for e in self._feed(text) if e.kind == markdown_items.ITEM_END]
        self.assertEqual(len(ends), 1)
        self.assertTrue(markdown_items.is_complete(ends[0].item))

    def test_next_open_mark_cuts_the_previous_item(self):
        """닫기를 빠뜨리고 다음 묶음이 시작되면 **두 항목이 섞이지 않게** 끊는다."""
        text = "<<<FAQ\n근거: 첫.\n질문: 하나?\n답변: 하나다.\n" + _item("둘.", "둘?", "둘이다.")
        ends = [e for e in self._feed(text) if e.kind == markdown_items.ITEM_END]
        self.assertEqual(len(ends), 2)
        self.assertEqual(ends[0].item["question"], "하나?")
        self.assertEqual(ends[1].item["question"], "둘?")

    def test_chatter_outside_the_block_is_dropped(self):
        """묶음 밖 인사말·설명은 버린다 (형식 위반이지만 흔하다)."""
        text = "알겠습니다. 아래와 같이 만들었습니다.\n" + _item("원문.", "질문?", "답변.")
        items = markdown_items.parse_all(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["question"], "질문?")

    def test_label_drift_leaves_the_field_empty(self):
        """라벨이 흔들리면 필드가 빈다 — 호출부가 `rejected_schema` 로 센다."""
        text = "<<<FAQ\n증거: 원문.\n질문: 왜?\n답변: 그래서.\n>>>"
        items = markdown_items.parse_all(text)
        self.assertEqual(len(items), 1)
        self.assertFalse(markdown_items.is_complete(items[0]))

    def test_parse_all_matches_the_streaming_parser(self):
        """비스트리밍도 **같은 파서**를 지난다 — 갈리면 한쪽만 검증된다."""
        text = _item("원문 하나.", "질문 하나?", "답변 하나.") + "\n" + _item(
            "원문 둘.", "질문 둘?", "답변 둘."
        )
        streamed = [e.item for e in self._feed(text) if e.kind == markdown_items.ITEM_END]
        self.assertEqual(markdown_items.parse_all(text), streamed)


# ══════════════════════════════════════════════════════════════════════════
# 2. 검증 순서 — 기각될 항목은 화면에 안 나간다
# ══════════════════════════════════════════════════════════════════════════

_DOC = "가맹점 등록은 영업일 기준 3일이 걸립니다.\n수수료는 매월 25일에 정산합니다."


class _FakeStream:
    """조각 하나마다 미리 정한 마크다운을 **델타로 쪼개** 흘리는 대역."""

    def __init__(self, body: str, piece: int = 5):
        self.body = body
        self.piece = piece
        self.calls = 0

    async def __call__(self, system_prompt, user_prompt, on_delta):
        self.calls += 1
        for start in range(0, len(self.body), self.piece):
            await on_delta(self.body[start:start + self.piece])
        return LlmResult(content=self.body, error_type="")


class StreamAdoptionTest(unittest.TestCase):
    """`generate_faqs_stream` — 무엇이 프레임으로 나가고 무엇이 조용히 기각되나."""

    def _run(self, body: str, count: int = 5):
        frames: list = []

        async def on_frame(frame):
            frames.append(frame)

        original = generator.faq_stream_async
        generator.faq_stream_async = _FakeStream(body)
        try:
            result = asyncio.run(
                generator.generate_faqs_stream(_DOC, count, on_frame=on_frame)
            )
        finally:
            generator.faq_stream_async = original
        return result, frames

    def test_grounded_item_opens_and_closes(self):
        body = _item("수수료는 매월 25일에 정산합니다.", "정산일은 언제인가요?", "매월 25일입니다.")
        result, frames = self._run(body)
        kinds = [f["type"] for f in frames]
        self.assertIn(generator.FRAME_ITEM_OPEN, kinds)
        self.assertIn(generator.FRAME_ITEM_CLOSE, kinds)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].question, "정산일은 언제인가요?")

    def test_ungrounded_item_never_reaches_the_screen(self):
        """지어낸 근거는 **한 프레임도** 나가지 않는다 (나타났다 사라지지 않는다)."""
        body = _item("문서에 없는 완전히 새로운 문장입니다.", "그게 뭔가요?", "지어낸 답변입니다.")
        result, frames = self._run(body)
        self.assertEqual(frames, [], "기각될 항목이 화면에 나갔다")
        self.assertEqual(result.rejected_ungrounded, 1)
        self.assertEqual(result.items, [])

    def test_duplicate_question_never_reaches_the_screen(self):
        evidence = "가맹점 등록은 영업일 기준 3일이 걸립니다."
        body = (
            _item(evidence, "등록은 얼마나 걸리나요?", "3일입니다.")
            + "\n"
            + _item(evidence, "등록은 얼마나 걸리나요?", "영업일 3일입니다.")
        )
        result, frames = self._run(body)
        opens = [f for f in frames if f["type"] == generator.FRAME_ITEM_OPEN]
        self.assertEqual(len(opens), 1, "중복 항목이 화면에 나갔다")
        self.assertEqual(result.rejected_duplicate, 1)

    def test_item_opens_on_first_answer_delta_not_on_question(self):
        """질문이 닫힐 때 열면 **답 없는 질문**이 화면에 남을 수 있다 (형식 위반 시)."""
        body = "<<<FAQ\n근거: 수수료는 매월 25일에 정산합니다.\n질문: 정산일은?\n>>>"
        result, frames = self._run(body)
        self.assertEqual(frames, [], "답변이 없는데 항목을 열었다")
        self.assertEqual(result.items, [])
        self.assertEqual(result.rejected_schema, 1)

    def test_streamed_order_matches_the_final_list(self):
        """흘린 순서와 `faq_items` 순서가 같다 — 다르면 마지막에 화면이 재정렬된다."""
        body = (
            _item("가맹점 등록은 영업일 기준 3일이 걸립니다.", "등록 기간은?", "3일입니다.")
            + "\n"
            + _item("수수료는 매월 25일에 정산합니다.", "정산일은?", "25일입니다.")
        )
        result, frames = self._run(body)
        opened = [f["question"] for f in frames if f["type"] == generator.FRAME_ITEM_OPEN]
        self.assertEqual(opened, [item.question for item in result.items])

    def test_stream_unsupported_is_its_own_verdict(self):
        """게이트웨이가 스트리밍을 안 받으면 **실패가 아니라 경로 문제**로 갈라 낸다."""
        async def refuse(system_prompt, user_prompt, on_delta):
            return LlmResult(content="", error_type=faq_llm.STREAM_UNSUPPORTED)

        original = generator.faq_stream_async
        generator.faq_stream_async = refuse
        try:
            result = asyncio.run(generator.generate_faqs_stream(_DOC, 3))
        finally:
            generator.faq_stream_async = original
        self.assertEqual(result.failure, generator.FAILURE_STREAM_UNSUPPORTED)

    def test_both_paths_adopt_the_same_items(self):
        """같은 문서·같은 응답이면 두 경로가 **같은 항목**을 채택한다.

        판정부(`_adopt_one`)가 한 곳이라는 것의 증거다. 갈리면 같은 문서가 경로에
        따라 다른 FAQ 를 내고, 그 차이는 오류로 드러나지 않는다.

        **기각 건수까지 같다고 보지는 않는다** — 아래 `test_streaming_has_no_shortfall_refill`
        참고. 비스트리밍만 부족분을 한 번 더 부르므로 그 호출의 기각이 더해진다.
        """
        body = (
            _item("가맹점 등록은 영업일 기준 3일이 걸립니다.", "등록 기간은?", "3일입니다.")
            + "\n"
            + _item("문서에 없는 문장이다.", "지어낸 질문?", "지어낸 답변.")
        )
        streamed, _ = self._run(body)

        async def fake_call(system_prompt, user_prompt):
            return LlmResult(content=body, error_type="")

        original = generator.llm_call_async
        generator.llm_call_async = fake_call
        try:
            plain = asyncio.run(generator.generate_faqs(_DOC, 5))
        finally:
            generator.llm_call_async = original

        self.assertEqual(
            [item.question for item in streamed.items],
            [item.question for item in plain.items],
        )
        self.assertGreaterEqual(streamed.rejected_ungrounded, 1)
        self.assertGreaterEqual(plain.rejected_ungrounded, 1)

    def test_streaming_has_no_shortfall_refill(self):
        """**스트리밍은 부족분을 다시 부르지 않는다** — 두 경로의 유일한 동작 차이다.

        `_fill_shortfall` 은 이미 채택된 질문 목록을 프롬프트에 실어 다시 부르는
        호출이라 앞 호출의 결과가 뒤 호출의 입력이다. 항목을 흘리는 중에는 그 목록이
        아직 확정되지 않았고, 흘린 뒤에 더 붙이면 화면이 한 번 멈췄다 다시 움직인다.

        대가는 **모델이 덜 내놓으면 스트리밍 쪽이 적게 나온다**는 것이다. 이 판정은
        그 차이를 규약으로 못박아 둔다 — 나중에 붙일 때 여기가 먼저 FAIL 한다.
        """
        body = _item("수수료는 매월 25일에 정산합니다.", "정산일은?", "25일입니다.")
        calls: list = []

        async def fake_call(system_prompt, user_prompt):
            calls.append(user_prompt)
            return LlmResult(content=body, error_type="")

        original = generator.llm_call_async
        generator.llm_call_async = fake_call
        try:
            asyncio.run(generator.generate_faqs(_DOC, 5))
        finally:
            generator.llm_call_async = original
        self.assertGreater(len(calls), 1, "비스트리밍이 부족분을 다시 부르지 않았다")

        stream_fake = _FakeStream(body)
        original_stream = generator.faq_stream_async
        generator.faq_stream_async = stream_fake
        try:
            asyncio.run(generator.generate_faqs_stream(_DOC, 5))
        finally:
            generator.faq_stream_async = original_stream
        self.assertEqual(stream_fake.calls, 1, "스트리밍이 부족분을 다시 불렀다")


# ══════════════════════════════════════════════════════════════════════════
# 3. SSE 전송 — `openai` SDK 없이 `httpx` 로 읽는다
# ══════════════════════════════════════════════════════════════════════════

class FaqStreamTransportTest(unittest.TestCase):
    """`faq_stream_async` — 글다듬이 `polish_stream_async` 와 같은 전송 규약이다."""

    def setUp(self) -> None:
        self._env = {
            key: os.environ.get(key)
            for key in ("GENOS_URL", "LLM_SERVING_ID", "GENOS_TOKEN")
        }
        os.environ["GENOS_URL"] = "https://genos.example"
        os.environ["LLM_SERVING_ID"] = "9"
        os.environ["GENOS_TOKEN"] = "token"
        self.requests: list = []

    def tearDown(self) -> None:
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _call(self, handler) -> tuple:
        """대역 트랜스포트를 **배포 단위 밖에서** 꽂는다."""
        real = httpx.AsyncClient
        transport = httpx.MockTransport(handler)

        class Patched(real):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        deltas: list = []

        async def on_delta(piece):
            deltas.append(piece)

        httpx.AsyncClient = Patched
        try:
            result = asyncio.run(faq_llm.faq_stream_async("sys", "문서", on_delta))
        finally:
            httpx.AsyncClient = real
        return result, deltas

    def _sse(self, *frames) -> str:
        return "\n\n".join(frames) + "\n\n"

    def test_no_openai_dependency(self):
        """**이 단위는 `openai` 를 import 하지 않는다** — mirror 의존을 늘리지 않는다."""
        import inspect
        source = inspect.getsource(faq_llm)
        self.assertNotIn("import openai", source)
        self.assertNotIn("AsyncOpenAI", source)

    def test_sse_frames_become_deltas(self):
        def handler(request):
            self.requests.append(request)
            body = json.loads(request.content)
            self.assertTrue(body["stream"], "스트리밍을 요청하지 않았다")
            self.assertNotIn("model", body, "서빙 경로가 모델을 정한다 (2026-09-07)")
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=self._sse(
                    'data: {"choices":[{"delta":{"content":"<<<FAQ\\n"}}]}',
                    ": keepalive",
                    'data: {"choices":[{"delta":{"content":"근거: 원문.\\n"}}]}',
                    'data: {"choices":[{"delta":{}}]}',
                    "data: [DONE]",
                ),
            )

        result, deltas = self._call(handler)
        self.assertEqual(deltas, ["<<<FAQ\n", "근거: 원문.\n"])
        self.assertEqual(result.content, "".join(deltas))
        self.assertEqual(
            self.requests[0].headers.get("accept"),
            "text/event-stream",
            "Accept 를 밝히지 않으면 SSE 를 안 내주는 서버가 있다 (MCP 406 과 같은 자리)",
        )

    def test_url_goes_through_the_gateway_prefix(self):
        def handler(request):
            self.requests.append(request)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=self._sse('data: {"choices":[{"delta":{"content":"x"}}]}', "data: [DONE]"),
            )

        self._call(handler)
        url = str(self.requests[0].url)
        self.assertIn("/api/gateway/rep/serving/9/v1/chat/completions", url)

    def test_request_rejection_is_its_own_reason(self):
        """400·415·422·501 = 이 배포는 스트리밍을 안 받는다 → 되돌아갈 근거를 준다."""
        for status in (400, 415, 422, 501):
            def handler(_request, code=status):
                return httpx.Response(code, json={"detail": "no stream"})

            result, deltas = self._call(handler)
            self.assertEqual(result.error_type, faq_llm.STREAM_UNSUPPORTED, status)
            self.assertEqual(deltas, [], status)

    def test_non_sse_response_is_not_thrown_away(self):
        """200 인데 SSE 가 아니면 **한 덩어리로** 흘린다 — 결과를 버리지 않는다."""
        def handler(_request):
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "통째로 온 응답"}}]},
                headers={"content-type": "application/json"},
            )

        result, deltas = self._call(handler)
        self.assertEqual(deltas, ["통째로 온 응답"])
        self.assertTrue(result.ok)

    def test_broken_frame_does_not_kill_the_stream(self):
        def handler(_request):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=self._sse(
                    'data: {"choices":[{"delta":{"content":"앞"}}]}',
                    "data: {깨진 json",
                    'data: {"choices":[{"delta":{"content":"뒤"}}]}',
                    "data: [DONE]",
                ),
            )

        result, deltas = self._call(handler)
        self.assertEqual(deltas, ["앞", "뒤"])
        self.assertTrue(result.ok)

    def test_no_retry_after_first_delta(self):
        """흘린 뒤에는 다시 부르지 않는다 — 같은 항목이 화면에 두 번 나온다."""
        attempts: list = []

        def handler(_request):
            attempts.append(1)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=self._sse('data: {"choices":[{"delta":{"content":"앞부분"}}]}'),
            )

        result, deltas = self._call(handler)
        self.assertEqual(len(attempts), 1, "델타가 나온 뒤 다시 불렀다")
        self.assertEqual(result.content, "앞부분")

    def test_4xx_is_not_retried(self):
        """404 는 요청이 잘못된 것이다 — 두드려도 같은 결과다."""
        attempts: list = []

        def handler(_request):
            attempts.append(1)
            return httpx.Response(404, json={"detail": "no such serving"})

        result, _ = self._call(handler)
        self.assertEqual(len(attempts), 1)
        self.assertFalse(result.ok)
        self.assertNotEqual(result.error_type, faq_llm.STREAM_UNSUPPORTED)

    def test_5xx_is_retried_up_to_the_cap(self):
        attempts: list = []

        def handler(_request):
            attempts.append(1)
            return httpx.Response(503, json={"detail": "busy"})

        result, _ = self._call(handler)
        self.assertEqual(len(attempts), max(1, Config.LLM_RETRY_COUNT))
        self.assertFalse(result.ok)

    def test_config_missing_makes_no_call(self):
        """설정 부재는 예외가 아니라 `CONFIG_MISSING` 이고, 호출을 시도하지 않는다."""
        os.environ["GENOS_URL"] = ""
        called: list = []

        def handler(_request):
            called.append(1)
            return httpx.Response(200, text="")

        result, _ = self._call(handler)
        self.assertEqual(called, [])
        self.assertEqual(result.error_type, faq_llm.CONFIG_MISSING)


if __name__ == "__main__":
    unittest.main()
