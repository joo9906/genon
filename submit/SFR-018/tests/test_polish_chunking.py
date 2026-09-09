"""글다듬이는 문서를 **조각으로 나눠** 다듬는다 (2026-08-29).

## 왜 나눴나

이 단위는 셋 중 유일하게 문서 전체를 한 번에 LLM 에 보냈다. 그런데 입력 상한은 20만
자인데 `RES_TIMEOUT` 은 90초라 **상한에 닿기 한참 전에 타임아웃이 먼저 났다.** 그 실패는
재시도 가능(00020001)으로 분류돼 같은 자리에서 또 걸리므로, 사용자에게 긴 문서는 그냥
안 되는 기능이었다.

나눠도 되는 근거는 이 기능이 하는 일이다 — 내용을 다시 쓰는 것이 아니라 **문체에 맞게
낱말·어미를 손질**한다. 판단 단위가 문장이라 조각 경계 너머의 문맥이 필요하지 않다.

## 나누면 새로 생기는 위험 둘 — 여기서 그 둘을 지킨다

1. **경계에서 글자가 새는 것.** 실패한 조각 자리에 원문을 되꽂아야 하는데, 개행 하나만
   잃어도 그 자리에서 문단·표가 붙어 버린다. 그래서 무손실 왕복이 계약이다.
2. **구조 한가운데를 가르는 것.** 코드펜스·여러 줄 HTML 표는 **안에 빈 줄이 올 수 있어**
   경계 규칙만으로는 갈린다. 절반만 LLM 에 주면 그 조각의 출력이 표·코드로 보이지 않고,
   `markdown_structure_issues` 가 잡는 훼손을 **우리가 만들어 내는** 셈이다.
   (마크다운 표는 안에 빈 줄이 없어 이미 안전하다 — 따로 떼는 것은 앞뒤 문단이 붙어
   덩어리가 커지는 것을 막기 위해서다.)
"""

import asyncio
import json
import os
import unittest

from . import onprem_path

onprem_path.install(onprem_path.TEXT_POLISH_UNIT)

import httpx  # noqa: E402

from text_polish import chunking, polisher  # noqa: E402
from text_polish import llm as polish_llm  # noqa: E402
from text_polish.config import Config  # noqa: E402
from text_polish.llm import CONFIG_MISSING, LlmResult  # noqa: E402


def _joined(chunks: list) -> str:
    return "".join(chunk.text + chunk.suffix for chunk in chunks)


class SplitForPolishTest(unittest.TestCase):
    def test_round_trip_is_lossless(self):
        """이어붙이면 원문과 **문자 단위로** 같다 — 이 모듈의 첫 계약이다."""
        text = "# 제목\n\n첫 문단입니다.\n\n둘째 문단입니다.\n\n\n셋째 문단입니다.\n"
        self.assertEqual(_joined(chunking.split_for_polish(text, 20)), text)

    def test_round_trip_survives_trailing_whitespace(self):
        """앞뒤 공백이 있는 문서에서도 무손실이다 (꼬리를 따로 드는 이유)."""
        text = "\n\n  본문입니다.  \n\n"
        self.assertEqual(_joined(chunking.split_for_polish(text, 10)), text)

    def test_markdown_table_stays_whole(self):
        """표는 예산을 넘겨도 한 조각에 있다.

        반으로 자르면 그 조각의 출력이 표로 보이지 않는다 — 구조 훼손은 되돌릴 수 없고,
        큰 조각은 느릴 뿐이다.
        """
        table = "| 구분 | 값 |\n|---|---|\n| 가 | 1 |\n| 나 | 2 |\n"
        text = f"앞 문단입니다.\n\n{table}\n뒤 문단입니다.\n"
        chunks = chunking.split_for_polish(text, 15)
        holding = [chunk for chunk in chunks if "| 구분 |" in chunk.text]
        self.assertEqual(len(holding), 1, "표가 두 조각으로 갈렸다")
        self.assertIn("| 나 | 2 |", holding[0].text, "표 끝이 다른 조각으로 넘어갔다")

    def test_table_glued_to_text_is_isolated(self):
        """빈 줄 없이 표에 붙어 있는 문단은 표와 **다른 덩어리**가 된다.

        전처리기 산출물에 흔한 모양이다. 떼어 내지 않으면 표와 앞뒤 문단이 한 덩어리가
        되어 조각이 예산을 크게 넘고, 그러면 나눈 의미가 없어진다. (표 자체가 갈리는
        일은 빈 줄 경계만으로도 없다 — 표 안에는 빈 줄이 없다.)
        """
        text = "앞 문단입니다.\n| 구분 | 값 |\n|---|---|\n| 가 | 1 |\n뒤 문단입니다.\n"
        chunks = chunking.split_for_polish(text, 20)
        self.assertEqual(_joined(chunks), text)
        self.assertGreater(len(chunks), 1, "표에 붙은 문단까지 한 조각이 됐다")

    def test_code_fence_is_never_split(self):
        """코드펜스 안은 빈 줄이 있어도 끊지 않는다."""
        text = "설명입니다.\n\n```\n첫 줄\n\n둘째 줄\n```\n\n끝 문단입니다.\n"
        chunks = chunking.split_for_polish(text, 12)
        holding = [chunk for chunk in chunks if "```" in chunk.text]
        self.assertEqual(len(holding), 1)
        self.assertEqual(holding[0].text.count("```"), 2, "펜스가 두 조각으로 갈렸다")

    def test_html_table_is_never_split(self):
        """여러 줄 HTML 표도 한 덩어리다 (전처리기 산출물에 나온다)."""
        text = "앞 문단.\n\n<table>\n<tr><td>가</td></tr>\n\n<tr><td>나</td></tr>\n</table>\n\n뒤.\n"
        chunks = chunking.split_for_polish(text, 15)
        holding = [chunk for chunk in chunks if "<table>" in chunk.text]
        self.assertEqual(len(holding), 1)
        self.assertIn("</table>", holding[0].text)

    def test_long_document_is_actually_split(self):
        """예산이 있으면 실제로 나눈다 — 안 나누면 타임아웃 문제가 그대로다."""
        text = "\n\n".join(f"{index}번째 문단입니다." for index in range(40))
        self.assertGreater(len(chunking.split_for_polish(text, 100)), 5)

    def test_empty_input(self):
        self.assertEqual(chunking.split_for_polish("", 100), [])


class RebuildTest(unittest.TestCase):
    def test_missing_chunk_falls_back_to_source(self):
        """실패한 조각 자리에는 **원문이 들어간다.**

        빈 문자열로 두면 그 구간이 통째로 사라진 결과가 정상 응답처럼 나간다.
        """
        text = "첫 문단.\n\n둘째 문단.\n\n셋째 문단.\n"
        chunks = chunking.split_for_polish(text, 10)
        self.assertGreaterEqual(len(chunks), 3)
        rebuilt = chunking.rebuild(chunks, {0: "첫 문단입니다."})
        self.assertIn("첫 문단입니다.", rebuilt)
        self.assertIn("둘째 문단.", rebuilt)
        self.assertIn("셋째 문단.", rebuilt)

    def test_all_missing_returns_source(self):
        text = "첫 문단.\n\n둘째 문단.\n"
        chunks = chunking.split_for_polish(text, 10)
        self.assertEqual(chunking.rebuild(chunks, {}), text)


class _FakeLlm:
    """조각마다 접두어를 붙여 돌려주는 대역. `fail_at` 번째 호출만 실패한다."""

    def __init__(self, fail_at: int = -1, error_type: str = "APITimeoutError",
                 transport: bool = True, fail_all: bool = False):
        self.calls: list = []
        self.fail_at = fail_at
        self.error_type = error_type
        self.transport = transport
        self.fail_all = fail_all

    async def __call__(self, _system: str, user_text: str) -> LlmResult:
        index = len(self.calls)
        self.calls.append(user_text)
        if self.fail_all or index == self.fail_at:
            return LlmResult(
                content="", error_type=self.error_type, is_transport_error=self.transport
            )
        return LlmResult(content=f"[다듬음]{user_text}", error_type="")


_DOC = "첫 문단입니다.\n\n둘째 문단입니다.\n\n셋째 문단입니다.\n"


class PolishDocumentTest(unittest.TestCase):
    def setUp(self) -> None:
        self._budget = Config.MAX_CHUNK_CHARS
        self._call = polisher.polish_text_async
        Config.MAX_CHUNK_CHARS = 12

    def tearDown(self) -> None:
        Config.MAX_CHUNK_CHARS = self._budget
        polisher.polish_text_async = self._call

    def test_every_chunk_is_sent(self):
        """문서 전체가 LLM 을 지난다 — 조각 하나만 보내고 끝내지 않는다."""
        fake = _FakeLlm()
        polisher.polish_text_async = fake
        outcome = asyncio.run(polisher.polish_document("system", _DOC))

        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.chunk_count, 3)
        self.assertEqual(outcome.failed_chunk_count, 0)
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(outcome.text.count("[다듬음]"), 3)

    def test_paragraph_breaks_survive(self):
        """조각 사이의 빈 줄이 살아남는다.

        LLM 은 응답 끝 공백을 지운다 — 꼬리를 코드가 되꽂지 않으면 **문단 경계가
        사라져** 제목과 본문이 한 줄이 된다.
        """
        polisher.polish_text_async = _FakeLlm()
        outcome = asyncio.run(polisher.polish_document("system", _DOC))
        self.assertEqual(outcome.text.count("\n\n"), 2)
        self.assertTrue(outcome.text.endswith("\n"))

    def test_failed_chunk_keeps_source_text(self):
        """실패한 조각 자리에는 원문이 남고, 그 사실이 건수로 남는다 (부분 실패)."""
        polisher.polish_text_async = _FakeLlm(fail_at=1)
        outcome = asyncio.run(polisher.polish_document("system", _DOC))

        self.assertTrue(outcome.ok, "조각 하나가 실패했다고 문서 전체를 버렸다")
        self.assertEqual(outcome.failed_chunk_count, 1)
        self.assertIn("둘째 문단입니다.", outcome.text)
        self.assertNotIn("[다듬음]둘째", outcome.text)

    def test_all_chunks_failed_is_not_ok(self):
        """전량 실패는 오류다 — 원문을 그대로 돌려주면 '바뀐 게 없다' 로 읽힌다."""
        polisher.polish_text_async = _FakeLlm(fail_all=True)
        outcome = asyncio.run(polisher.polish_document("system", _DOC))

        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.failed_chunk_count, outcome.chunk_count)
        self.assertTrue(outcome.is_transport_error)

    def test_config_missing_stops_after_first_chunk(self):
        """설정 부재는 첫 조각에서 끝낸다 — 조각 수만큼 두드릴 이유가 없다."""
        fake = _FakeLlm(fail_all=True, error_type=CONFIG_MISSING, transport=False)
        polisher.polish_text_async = fake
        outcome = asyncio.run(polisher.polish_document("system", _DOC))

        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.config_missing)
        self.assertEqual(len(fake.calls), 1, f"{len(fake.calls)}번 불렀다")

    def test_whitespace_only_document_is_not_a_failure(self):
        """공백뿐인 문서는 분모가 0 이다 — 전량 실패로 보이면 안 된다."""
        polisher.polish_text_async = _FakeLlm(fail_all=True)
        outcome = asyncio.run(polisher.polish_document("system", "\n\n  \n"))
        self.assertEqual(outcome.chunk_count, 0)
        self.assertEqual(outcome.text, "\n\n  \n")


if __name__ == "__main__":
    unittest.main()


class PolishLlmTransportTest(unittest.TestCase):
    """글다듬이 LLM 호출을 **`httpx` 로 직접** 한다 (2026-09-07 — `openai` SDK 제거).

    실환경에서 SDK 때문에 호출이 실패해 걷어냈다. 게이트웨이는 OpenAI 호환 경로를
    내주므로 SDK 가 하던 일은 `POST {base}/chat/completions` 한 번과 응답 dict 에서
    본문을 꺼내는 것뿐이다 — FAQ·006 두 단위는 처음부터 이 모양이었다.

    ## 여기서 무엇을 보나

    SDK 를 걷어낼 때 **조용히 깨지는 자리가 셋**이고 전부 오류로 드러나지 않는다:

    1. **경로** — SDK 는 `/v1` 뒤를 자기가 붙였다. 우리가 끝까지 만들어야 하는데
       빠뜨리면 게이트웨이가 아니라 없는 경로를 때려 404 다.
    2. **오류 분류** — `_TRANSPORT_ERRORS` 에 `openai.APITimeoutError` 가 있었다.
       `httpx` 예외로 갈아 끼우지 않으면 타임아웃이 **실행 실패(502)로 나가고**
       캔버스가 재시도를 걸지 않는다.
    3. **응답 검증** — SDK 가 스키마를 봐 줬다. 직접 부르면 모양이 어긋난 응답에서
       빈 본문이 정상처럼 흘러간다.

    대역은 `httpx.MockTransport` 로 **배포 단위 밖에서** 꽂는다 — 운영 코드에
    테스트용 분기를 만들지 않는다.
    """

    def setUp(self) -> None:
        self._saved_env = {
            k: os.environ.get(k)
            for k in ("GENOS_URL", "LLM_SERVING_ID",
                      "GENOS_TOKEN", "LLM_RETRY_COUNT")
        }
        os.environ.update({
            "GENOS_URL": "http://gw.test", "LLM_SERVING_ID": "srv-9",
            "GENOS_TOKEN": "tok-abc",
            "LLM_RETRY_COUNT": "3",
        })
        self._real_client = polish_llm.httpx.AsyncClient
        self.calls: list = []
        self.handler = None
        harness = self

        class _Mocked(self._real_client):
            def __init__(self, **kwargs):
                kwargs.pop("timeout", None)
                super().__init__(
                    transport=httpx.MockTransport(harness._route), **kwargs
                )

        polish_llm.httpx.AsyncClient = _Mocked

    def tearDown(self) -> None:
        polish_llm.httpx.AsyncClient = self._real_client
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _route(self, request):
        self.calls.append(request)
        return self.handler(request)

    def _call(self, handler):
        self.handler = handler
        return asyncio.run(polish_llm.polish_text_async("시스템", "원문"))

    @staticmethod
    def _ok(content=" 다듬은 결과 "):
        return lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    def test_no_openai_dependency(self):
        """`openai` 를 import 하지 않는다 — 그게 이 변경의 목적이다.

        **문자열 검색으로 보지 않는다.** 이 파일 주석은 SDK 를 걷어낸 근거를 적으려고
        `AsyncOpenAI` 라는 낱말을 쓴다 — 주석까지 금지하면 "왜 걷어냈나" 를 파일에 적을
        수 없게 되고, 그 기록이 없으면 다음 사람이 SDK 를 다시 넣는다. **import 문만**
        본다(AST).
        """
        import ast

        tree = ast.parse(open(polish_llm.__file__, encoding="utf-8").read())
        imported: list = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module.split(".")[0])
        self.assertNotIn("openai", imported, f"import 목록={sorted(set(imported))}")
        self.assertIn("httpx", imported, "httpx 로 직접 부르는 것이 계약이다")

    def test_openai_is_not_in_requirements(self):
        """`requirements.txt` 에서도 빠져야 한다 — 남으면 폐쇄망 빌드가 그 패키지를 찾는다."""
        # 경로를 손으로 세지 않는다 — `onprem_path` 가 배포 단위 위치를 아는 유일한 자리다.
        path = os.path.join(onprem_path.TEXT_POLISH_UNIT, "requirements.txt")
        pinned = [
            line.split("#")[0].strip()
            for line in open(path, encoding="utf-8").read().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertFalse(
            [p for p in pinned if p.startswith("openai")], f"고정 목록={pinned}"
        )

    def test_request_shape(self):
        """경로·모델·인증 헤더가 게이트웨이 표준이다."""
        result = self._call(self._ok())
        self.assertTrue(result.ok)
        self.assertEqual(result.content, "다듬은 결과")
        request = self.calls[0]
        self.assertEqual(
            str(request.url),
            "http://gw.test/api/gateway/rep/serving/srv-9/v1/chat/completions",
        )
        body = json.loads(request.content)
        # **`model` 을 싣지 않는다** (2026-09-07) — 서빙 경로
        # (`/rep/serving/{LLM_SERVING_ID}/…`)가 이미 모델을 결정하므로 `LLM_SERVING_ID`
        # 가 모델 지정 역할을 함께 한다. 되살아나면 여기서 걸린다.
        self.assertNotIn("model", body, f"본문 키={sorted(body)}")
        self.assertIs(body["stream"], False)
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertEqual(request.headers["authorization"], "Bearer tok-abc")

    def test_gateway_prefix_is_not_doubled(self):
        """`GENOS_URL` 이 이미 prefix 로 끝나면 중복시키지 않는다."""
        os.environ["GENOS_URL"] = "http://gw.test/api/gateway"
        self._call(self._ok())
        self.assertEqual(
            str(self.calls[0].url),
            "http://gw.test/api/gateway/rep/serving/srv-9/v1/chat/completions",
        )

    def test_4xx_is_not_retried(self):
        """요청이 잘못된 것이라 반복해도 같은 결과다 — SDK 판은 이 구분이 없었다."""
        for status in (400, 401, 404, 422):
            self.calls.clear()
            result = self._call(lambda request, s=status: httpx.Response(s, json={}))
            self.assertFalse(result.ok)
            self.assertFalse(result.is_transport_error)
            self.assertEqual(len(self.calls), 1, f"{status} 를 재시도했다")

    def test_5xx_is_retried_to_the_cap(self):
        """상한까지만 재시도한다 (§10.2 — 무한 재시도 금지).

        **기대 횟수를 손으로 적지 않는다.** `Config.LLM_RETRY_COUNT` 는 **import 시점**에
        굳으므로(게이트웨이 4종만 호출 시점 읽기다) 테스트가 환경변수를 바꿔도 안 따라온다 —
        3 을 적어 뒀다가 실제 2 에서 FAIL 했다. 운영 값에서 파생시킨다.
        """
        cap = max(1, Config.LLM_RETRY_COUNT)
        result = self._call(lambda request: httpx.Response(503, json={}))
        self.assertFalse(result.ok)
        self.assertEqual(len(self.calls), cap)

    def test_timeout_is_transport_error(self):
        """`is_transport_error` 가 False 로 나가면 504 대신 502 가 되고 재시도가 안 걸린다."""
        def timing_out(request):
            raise httpx.ConnectTimeout("timed out")

        result = self._call(timing_out)
        self.assertTrue(result.is_transport_error, "타임아웃이 실행 실패로 분류됐다")

    def test_connect_error_is_transport_error(self):
        def refused(request):
            raise httpx.ConnectError("refused")

        self.assertTrue(self._call(refused).is_transport_error)

    def test_malformed_response_is_not_accepted(self):
        """모양이 어긋난 응답에서 **빈 본문이 정상처럼 흘러가지 않는다.**"""
        for label, payload in (
            ("choices 없음", {}),
            ("choices 빈 배열", {"choices": []}),
            ("message 없음", {"choices": [{}]}),
            ("content 빈 문자열", {"choices": [{"message": {"content": "   "}}]}),
        ):
            result = self._call(lambda request, p=payload: httpx.Response(200, json=p))
            self.assertFalse(result.ok, label)
            self.assertFalse(result.is_transport_error, label)

    def test_config_missing_is_its_own_reason(self):
        """설정 부재는 예외가 아니라 `CONFIG_MISSING` 이다 — 조각을 더 두드리지 않는다."""
        os.environ["GENOS_URL"] = ""
        result = self._call(self._ok())
        self.assertEqual(result.error_type, polish_llm.CONFIG_MISSING)
        self.assertEqual(len(self.calls), 0, "설정이 없는데 호출을 시도했다")


# ═══════════════════════════════════════════════════════════════════════════
# 스트리밍 (2026-09-09)
# ═══════════════════════════════════════════════════════════════════════════
# 조각내 나눈 것을 **다듬어지는 대로** 흘린다. 그전에는 다 끝난 뒤 스텝이 조각내 흘려서,
# 사용자가 기다리는 수십 초 동안 화면이 비어 있었다.
#
# 여기서 지키는 것 넷 — 전부 **오류를 내지 않고 조용히 틀리는** 종류다:
#
# 1. **문서 순서.** 조각은 함께 도므로 조각 3이 조각 1보다 먼저 끝날 수 있다. 끝난
#    순서대로 흘리면 문단이 뒤섞인 글이 화면에 나가고, `result` 가 갈아 끼우므로
#    **최종 결과는 멀쩡하다** — 스트리밍 중에만 틀리고 로그에는 아무것도 안 남는다.
# 2. **무손실.** 흘린 것을 이어 붙인 것이 정본과 같아야 한다. 어긋나면 화면이 순간
#    다른 글을 보여준다.
# 3. **전량 실패에 원문을 흘리지 않는 것.** 실패 조각 자리에는 원문이 들어가는데
#    (`rebuild` 규약) 그것을 즉시 흘리면 전량 실패에서 **원문이 통째로 화면에 나간 뒤**
#    오류로 갈아엎는다 — 답이 나왔다가 사라진다. 구현 중 실제로 그렇게 만들었다.
# 4. **스트리밍을 안 받는 배포에서 한 글자도 흘리지 않는 것.** 흘려 놓고 비스트리밍으로
#    되돌아가면 같은 문서가 두 번, 그것도 처음엔 안 다듬어진 채로 나간다.


class _FakeStreamLlm:
    """조각을 다듬어 **증분으로** 돌려주는 대역.

    `finish_reverse=True` 면 뒤 조각이 먼저 끝난다 — 순서 버퍼를 태우려면 그 상황을
    실제로 만들어야 한다(순차로 끝나면 버퍼가 없어도 통과한다).
    """

    def __init__(self, chunk_texts: list, *, fail_indexes=(), fail_all: bool = False,
                 error_type: str = "APITimeoutError", transport: bool = True,
                 finish_reverse: bool = False, emit_then_fail=()):
        self.chunk_texts = chunk_texts
        self.fail_indexes = set(fail_indexes)
        self.fail_all = fail_all
        self.error_type = error_type
        self.transport = transport
        self.finish_reverse = finish_reverse
        self.emit_then_fail = set(emit_then_fail)
        self.calls: list = []

    def _index_of(self, user_text: str) -> int:
        return self.chunk_texts.index(user_text)

    async def __call__(self, _system: str, user_text: str, on_delta) -> LlmResult:
        index = self._index_of(user_text)
        self.calls.append(user_text)
        if self.finish_reverse:
            # 인덱스가 클수록 빨리 끝난다.
            await asyncio.sleep(0.01 * (len(self.chunk_texts) - index))
        if index in self.emit_then_fail:
            # 머리 조각이 **흘린 뒤** 끊기는 경우 (되돌릴 수 없다).
            await on_delta("절반만")
            return LlmResult(content="", error_type="ReadError", is_transport_error=True)
        if self.fail_all or index in self.fail_indexes:
            return LlmResult(
                content="", error_type=self.error_type, is_transport_error=self.transport
            )
        polished = f"[다듬음]{user_text}"
        for start in range(0, len(polished), 5):
            await on_delta(polished[start:start + 5])
            await asyncio.sleep(0)
        return LlmResult(content=polished, error_type="")


class PolishStreamOrderTest(unittest.TestCase):
    """`polish_document_stream` — 순서 버퍼와 무손실."""

    def setUp(self) -> None:
        self._budget = Config.MAX_CHUNK_CHARS
        self._call = polisher.polish_stream_async
        self._plain = polisher.polish_text_async
        Config.MAX_CHUNK_CHARS = 12

    def tearDown(self) -> None:
        Config.MAX_CHUNK_CHARS = self._budget
        polisher.polish_stream_async = self._call
        polisher.polish_text_async = self._plain

    def _run(self, fake) -> tuple:
        polisher.polish_stream_async = fake
        streamed: list = []

        async def on_text(text):
            streamed.append(text)

        outcome = asyncio.run(polisher.polish_document_stream("sys", _DOC, on_text))
        return outcome, "".join(streamed)

    def _chunk_texts(self) -> list:
        return [c.text for c in chunking.split_for_polish(_DOC, Config.MAX_CHUNK_CHARS)]

    def test_streamed_equals_canonical(self):
        """흘린 것을 이어 붙이면 정본과 **문자 단위로 같다.**"""
        outcome, streamed = self._run(_FakeStreamLlm(self._chunk_texts()))
        self.assertTrue(outcome.ok)
        self.assertEqual(streamed, outcome.text)
        self.assertEqual(outcome.streamed_chars, len(streamed))

    def test_document_order_survives_reverse_completion(self):
        """**뒤 조각이 먼저 끝나도** 문서 순서로 흘린다.

        이 판정이 없으면 순서 버퍼를 통째로 걷어내도 통과한다 — 대역이 순차로 끝나면
        어차피 순서가 맞기 때문이다.
        """
        texts = self._chunk_texts()
        fake = _FakeStreamLlm(texts, finish_reverse=True)
        outcome, streamed = self._run(fake)
        self.assertEqual(streamed, outcome.text)
        # 원문 문단이 나온 순서가 문서 순서와 같은가
        positions = [streamed.index(text) for text in texts]
        self.assertEqual(positions, sorted(positions), f"문단이 뒤섞였다: {streamed!r}")

    def test_failed_chunk_keeps_source_and_stays_lossless(self):
        """부분 실패 — 그 자리에 원문이 들어가고 흘린 것은 여전히 정본과 같다."""
        texts = self._chunk_texts()
        outcome, streamed = self._run(_FakeStreamLlm(texts, fail_indexes=(1,)))
        self.assertTrue(outcome.ok, "부분 실패는 성공이어야 한다")
        self.assertEqual(outcome.failed_chunk_count, 1)
        self.assertEqual(streamed, outcome.text)
        self.assertIn(texts[1], streamed, "실패한 조각 자리에 원문이 없다")
        self.assertFalse(outcome.stream_diverged)

    def test_total_failure_streams_nothing(self):
        """**전량 실패에서는 한 글자도 흘리지 않는다.**

        실패 조각의 원문을 즉시 흘리면 원문이 통째로 화면에 나간 뒤 라우트가 오류로
        갈아엎는다 — 사용자에게는 답이 나왔다가 사라지는 것으로 보인다.
        """
        outcome, streamed = self._run(_FakeStreamLlm(self._chunk_texts(), fail_all=True))
        self.assertFalse(outcome.ok)
        self.assertEqual(streamed, "", "전량 실패인데 원문을 흘렸다")
        self.assertEqual(outcome.streamed_chars, 0)

    def test_stream_unsupported_streams_nothing(self):
        """스트리밍 미지원 — 흘린 것이 0 이라 라우트가 비스트리밍으로 되돌아갈 수 있다."""
        outcome, streamed = self._run(
            _FakeStreamLlm(self._chunk_texts(), fail_all=True,
                           error_type=polish_llm.STREAM_UNSUPPORTED, transport=False)
        )
        self.assertTrue(outcome.stream_unsupported)
        self.assertEqual(outcome.streamed_chars, 0)
        self.assertEqual(streamed, "")

    def test_config_missing_stops_after_first_chunk(self):
        """설정 부재는 첫 조각에서 끝낸다 — 비스트리밍 경로와 같은 규약이다."""
        texts = self._chunk_texts()
        fake = _FakeStreamLlm(texts, fail_all=True, error_type=CONFIG_MISSING,
                              transport=False)
        outcome, streamed = self._run(fake)
        self.assertTrue(outcome.config_missing)
        self.assertEqual(streamed, "")
        self.assertLess(len(fake.calls), len(texts),
                        "설정이 없는데 조각 수만큼 두드렸다")

    def test_diverged_is_reported_not_swallowed(self):
        """머리 조각이 **흘린 뒤** 끊기면 화면과 정본이 어긋난다 — 사실을 올린다."""
        texts = self._chunk_texts()
        outcome, streamed = self._run(_FakeStreamLlm(texts, emit_then_fail=(0,)))
        self.assertTrue(outcome.stream_diverged,
                        "흘린 뒤 끊겼는데 어긋남을 알리지 않는다")
        self.assertTrue(outcome.ok, "나머지 조각은 살렸어야 한다")
        self.assertIn("절반만", streamed)

    def test_blank_document_is_not_total_failure(self):
        """공백만 든 문서 — LLM 을 부르지 않고 원문을 그대로 흘린다."""
        polisher.polish_stream_async = _FakeStreamLlm([])
        streamed: list = []

        async def on_text(text):
            streamed.append(text)

        outcome = asyncio.run(polisher.polish_document_stream("sys", "   \n\n  ", on_text))
        self.assertEqual(outcome.chunk_count, 0)
        self.assertEqual("".join(streamed), outcome.text)


class PolishStreamTransportTest(unittest.TestCase):
    """`polish_stream_async` — SSE 를 델타로 읽는가, 거절을 가르는가."""

    def setUp(self) -> None:
        self._env = {k: os.environ.get(k) for k in ("GENOS_URL", "LLM_SERVING_ID", "GENOS_TOKEN")}
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
        """대역 트랜스포트를 **배포 단위 밖에서** 꽂는다 (운영 코드에 분기를 두지 않는다)."""
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
            result = asyncio.run(polish_llm.polish_stream_async("sys", "안녕", on_delta))
        finally:
            httpx.AsyncClient = real
        return result, deltas

    def _sse(self, *frames) -> str:
        return "\n\n".join(frames) + "\n\n"

    def test_sse_frames_become_deltas(self):
        """`data: {...delta.content}` 를 증분으로 읽고, 이어 붙인 것이 `content` 다."""
        def handler(request):
            self.requests.append(request)
            body = json.loads(request.content)
            self.assertTrue(body["stream"], "스트리밍을 요청하지 않았다")
            self.assertNotIn("model", body, "서빙 경로가 모델을 정한다 (2026-09-07)")
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=self._sse(
                'data: {"choices":[{"delta":{"content":"안녕"}}]}',
                ': keepalive',
                'data: {"choices":[{"delta":{"content":"하세요"}}]}',
                'data: {"choices":[{"delta":{}}]}',
                'data: [DONE]',
            ))

        result, deltas = self._call(handler)
        self.assertEqual(deltas, ["안녕", "하세요"])
        self.assertEqual(result.content, "안녕하세요")
        self.assertEqual(
            self.requests[0].headers.get("accept"), "text/event-stream",
            "Accept 를 밝히지 않으면 SSE 를 안 내주는 서버가 있다 (MCP 406 과 같은 자리)",
        )

    def test_content_is_not_stripped(self):
        """`content` 에 `strip()` 을 걸지 않는다 — 흘린 것과 한 글자도 달라지면 안 된다."""
        def handler(_request):
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=self._sse(
                'data: {"choices":[{"delta":{"content":"  앞뒤 공백  "}}]}',
                'data: [DONE]',
            ))

        result, deltas = self._call(handler)
        self.assertEqual(result.content, "".join(deltas))

    def test_request_rejection_is_its_own_reason(self):
        """400·415·422·501 = 이 배포는 스트리밍을 안 받는다 → 되돌아갈 근거를 준다."""
        for status in (400, 415, 422, 501):
            def handler(_request, code=status):
                return httpx.Response(code, json={"detail": "no stream"})

            result, deltas = self._call(handler)
            self.assertEqual(result.error_type, polish_llm.STREAM_UNSUPPORTED, status)
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
        """프레임 하나가 깨진 것으로 응답 전체를 버리지 않는다."""
        def handler(_request):
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=self._sse(
                'data: {"choices":[{"delta":{"content":"앞"}}]}',
                'data: {깨진 json',
                'data: {"choices":[{"delta":{"content":"뒤"}}]}',
                'data: [DONE]',
            ))

        result, deltas = self._call(handler)
        self.assertEqual(deltas, ["앞", "뒤"])
        self.assertTrue(result.ok)

    def test_no_retry_after_first_delta(self):
        """흘린 뒤 끊기면 **재시도하지 않는다** — 같은 글이 화면에 두 번 나온다."""
        attempts: list = []

        def handler(_request):
            attempts.append(1)
            # 델타 하나를 보낸 뒤 `[DONE]` 없이 끝난다 → content 는 남지만
            # 여기서는 델타 뒤 실패를 만들기 위해 빈 본문으로 끝낸다.
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=self._sse(
                'data: {"choices":[{"delta":{"content":"앞부분"}}]}',
            ))

        result, deltas = self._call(handler)
        # 프레임이 정상이므로 성공으로 끝난다 — 중요한 것은 **한 번만 불렀다**는 것이다.
        self.assertEqual(len(attempts), 1, "델타가 나온 뒤 다시 불렀다")
        self.assertEqual(deltas, ["앞부분"])
        self.assertEqual(result.content, "앞부분")

    def test_config_missing_makes_no_call(self):
        """설정 부재는 예외가 아니라 `CONFIG_MISSING` 이고, 호출을 시도하지 않는다."""
        os.environ["GENOS_URL"] = ""
        called: list = []

        def handler(_request):
            called.append(1)
            return httpx.Response(200)

        result, _deltas = self._call(handler)
        self.assertEqual(result.error_type, CONFIG_MISSING)
        self.assertEqual(called, [])
