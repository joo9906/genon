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
