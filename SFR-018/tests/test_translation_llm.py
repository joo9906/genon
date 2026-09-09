"""번역 LLM 호출을 **`httpx` 로 직접** 한다 (2026-09-07 — `openai` SDK 제거).

실환경에서 SDK 때문에 호출이 실패해 걷어냈다. 게이트웨이는 OpenAI 호환 경로를 내주므로
SDK 가 하던 일은 `POST {base}/chat/completions` 한 번과 응답 dict 에서 본문을 꺼내는
것뿐이다 — FAQ·006 은 처음부터, 글다듬이는 같은 날 이 모양이 됐다.

## 여기서 무엇을 보나

글다듬이(`test_polish_chunking.PolishLlmTransportTest`)와 **같은 셋**에 이 단위 고유
계약 셋이 더 붙는다:

| 공통 | 번역 고유 |
|---|---|
| 경로·인증 헤더 | **세마포어**를 함수 안에서 잡는다 |
| 4xx 미재시도 / 5xx 상한 | **`max_tokens`** 를 싣는다 |
| 타임아웃 → 통신 실패 분류 | **코드펜스**를 걷어낸다 |
| 어긋난 응답을 받아들이지 않는다 | |

고유 셋을 따로 보는 이유는 **SDK 를 걷어낼 때 이 셋이 조용히 빠지기 쉬운 자리**라서다:

- 세마포어를 밖으로 옮기면 단건 폴백이 동시성 제한을 우회하고, 그건 429 가 날 때까지
  드러나지 않는다.
- `max_tokens` 가 빠지면 배치 응답이 잘려 **유닛 일부가 조용히 원문으로 남는다**
  (번역 결과가 정상 응답으로 내려간다).
- 펜스를 안 걷어내면 배치 JSON 파싱이 죽고 그 배치가 전부 단건 폴백으로 떨어진다.

대역은 `httpx.MockTransport` 로 **배포 단위 밖에서** 꽂는다 — 운영 코드에 테스트용
분기를 만들지 않는다.
"""

import asyncio
import json
import os
import unittest

from . import onprem_path

onprem_path.install(onprem_path.TRANSLATION_UNIT)

import httpx  # noqa: E402

from config import Config  # noqa: E402
from translation_pipeline.common import llm as translation_llm  # noqa: E402

# 배치 응답에 붙는 코드펜스. **소스에 리터럴로 적지 않는다** — 이 파일의 독스트링·주석이
# 마크다운으로 읽히는 자리라 세 겹 backtick 이 섞이면 렌더가 깨진다.
_FENCE = "`" * 3


class TranslationLlmTransportTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_env = {
            k: os.environ.get(k)
            for k in ("GENOS_URL", "LLM_SERVING_ID", "GENOS_TOKEN", "LLM_RETRY_COUNT")
        }
        os.environ.update({
            "GENOS_URL": "http://gw.test", "LLM_SERVING_ID": "srv-7",
            "GENOS_TOKEN": "tok-xyz", "LLM_RETRY_COUNT": "3",
        })
        self._real_client = translation_llm.httpx.AsyncClient
        self.calls: list = []
        self.handler = None
        harness = self

        class _Mocked(self._real_client):
            def __init__(self, **kwargs):
                kwargs.pop("timeout", None)
                super().__init__(
                    transport=httpx.MockTransport(harness._route), **kwargs
                )

        translation_llm.httpx.AsyncClient = _Mocked

    def tearDown(self) -> None:
        translation_llm.httpx.AsyncClient = self._real_client
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _route(self, request):
        self.calls.append(request)
        return self.handler(request)

    def _call(self, handler, concurrency: int = 4):
        self.handler = handler
        sem = asyncio.Semaphore(concurrency)

        async def _run():
            return await translation_llm.llm_call_async(sem, "시스템", "원문")

        return asyncio.run(_run())

    @staticmethod
    def _ok(content=" 번역 결과 "):
        return lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    # ── SDK 제거가 실제로 됐는가 ────────────────────────────────

    def test_no_openai_dependency(self):
        """`openai` 를 import 하지 않는다.

        **문자열 검색으로 보지 않는다** — 운영 파일의 주석은 걷어낸 근거를 적으려고 SDK
        이름을 쓴다. 그 기록을 금지하면 다음 사람이 SDK 를 다시 넣는다. import 문만 본다.
        """
        import ast

        tree = ast.parse(open(translation_llm.__file__, encoding="utf-8").read())
        imported: list = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module.split(".")[0])
        self.assertNotIn("openai", imported, f"import 목록={sorted(set(imported))}")
        self.assertIn("httpx", imported)

    def test_openai_is_not_in_requirements(self):
        """고정 목록에 남으면 폐쇄망 빌드가 그 패키지를 찾는다."""
        path = os.path.join(onprem_path.TRANSLATION_UNIT, "requirements.txt")
        pinned = [
            line.split("#")[0].strip()
            for line in open(path, encoding="utf-8").read().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertFalse(
            [p for p in pinned if p.startswith("openai")], f"고정 목록={pinned}"
        )

    def test_no_global_client(self):
        """전역 커넥션을 두지 않는다 (§D.2).

        SDK 판은 `AsyncOpenAI` 를 모듈 전역에 캐시했고, 그래서 **캐시 키를 설정값으로
        잡는 방어 코드**가 따로 필요했다(토큰이 회전돼도 옛 값을 쓰는 것을 막으려고).
        전역이 없어지면 그 방어 자체가 필요 없다 — 다시 넣으면 문제도 함께 돌아온다.
        """
        leaked = [n for n in dir(translation_llm) if n.startswith("_CLIENT")]
        self.assertEqual(leaked, [], f"전역 심볼={leaked}")

    # ── 요청 모양 ──────────────────────────────────────────────

    def test_request_shape(self):
        result = self._call(self._ok())
        self.assertTrue(result.ok)
        self.assertEqual(result.content, "번역 결과")
        request = self.calls[0]
        self.assertEqual(
            str(request.url),
            "http://gw.test/api/gateway/rep/serving/srv-7/v1/chat/completions",
        )
        self.assertEqual(request.headers["authorization"], "Bearer tok-xyz")
        body = json.loads(request.content)
        # **`model` 을 싣지 않는다** (2026-09-07) — 서빙 경로가 이미 모델을 결정한다.
        self.assertNotIn("model", body, f"본문 키={sorted(body)}")
        self.assertIs(body["stream"], False)
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])

    def test_gateway_prefix_is_not_doubled(self):
        os.environ["GENOS_URL"] = "http://gw.test/api/gateway"
        self._call(self._ok())
        self.assertEqual(
            str(self.calls[0].url),
            "http://gw.test/api/gateway/rep/serving/srv-7/v1/chat/completions",
        )

    def test_max_tokens_is_sent(self):
        """빠지면 배치 응답이 잘려 **유닛 일부가 조용히 원문으로 남는다.**"""
        self._call(self._ok())
        body = json.loads(self.calls[0].content)
        if Config.MAX_TOKENS > 0:
            self.assertEqual(body.get("max_tokens"), Config.MAX_TOKENS)
        else:
            self.assertNotIn("max_tokens", body)

    def test_code_fence_is_stripped(self):
        """배치 출력이 JSON 이라 모델이 펜스를 붙이면 파싱이 죽는다."""
        payload = '[{"id": 1, "t": "hello"}]'
        fenced = f"{_FENCE}json\n{payload}\n{_FENCE}"
        result = self._call(self._ok(fenced))
        self.assertEqual(result.content, payload)
        json.loads(result.content)  # 파싱이 되는 것이 이 판정의 요점이다

    # ── 동시성 ────────────────────────────────────────────────

    def test_semaphore_is_held_inside(self):
        """세마포어를 **이 함수 안에서** 잡는다.

        밖에 두면 단건 폴백 경로가 동시성 제한을 우회하고, 그건 429 가 날 때까지
        드러나지 않는다. 동시에 여러 번 불러 **동시 진행 수가 상한을 넘지 않는지** 본다.
        """
        limit = 2
        inflight = {"now": 0, "peak": 0}

        def counting(request):
            inflight["now"] += 1
            inflight["peak"] = max(inflight["peak"], inflight["now"])
            inflight["now"] -= 1
            return self._ok()(request)

        self.handler = counting
        sem = asyncio.Semaphore(limit)

        async def _run():
            return await asyncio.gather(*[
                translation_llm.llm_call_async(sem, "시스템", f"원문 {i}")
                for i in range(6)
            ])

        results = asyncio.run(_run())
        self.assertTrue(all(r.ok for r in results))
        self.assertEqual(len(self.calls), 6)
        self.assertLessEqual(inflight["peak"], limit)

    # ── 실패 분류 ──────────────────────────────────────────────

    def test_4xx_is_not_retried(self):
        """요청이 잘못된 것이라 반복해도 같은 결과다.

        번역은 배치를 `LLM_CONCURRENCY`(15)로 동시에 돌리므로 그 낭비가 **배치 수만큼
        곱해진다** — SDK 판에는 이 구분이 없었다.
        """
        for status in (400, 401, 404, 422):
            self.calls.clear()
            result = self._call(lambda request, s=status: httpx.Response(s, json={}))
            self.assertFalse(result.ok)
            self.assertFalse(result.is_transport_error)
            self.assertEqual(len(self.calls), 1, f"{status} 를 재시도했다")

    def test_5xx_is_retried_to_the_cap(self):
        """기대 횟수를 손으로 적지 않는다 — `LLM_RETRY_COUNT` 는 **import 시점**에 굳는다."""
        cap = max(1, Config.LLM_RETRY_COUNT)
        result = self._call(lambda request: httpx.Response(503, json={}))
        self.assertFalse(result.ok)
        self.assertEqual(len(self.calls), cap)

    def test_timeout_is_transport_error(self):
        """`is_transport_error` 가 False 로 나가면 504 대신 502 가 되고 재시도가 안 걸린다."""
        def timing_out(request):
            raise httpx.ConnectTimeout("timed out")

        self.assertTrue(self._call(timing_out).is_transport_error)

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

    def test_config_missing_is_a_constant(self):
        """설정 부재 사유를 **상수로** 낸다 (2026-09-07).

        예전에는 이 파일 안 리터럴 두 개였다. 호출부가 이 값으로 분기하게 되는 순간
        한쪽만 고쳐도 예외 없이 조용히 분기가 죽는다 — FAQ·글다듬이·006 이 이미 상수다.
        """
        os.environ["GENOS_URL"] = ""
        result = self._call(self._ok())
        self.assertEqual(result.error_type, translation_llm.CONFIG_MISSING)
        self.assertEqual(translation_llm.CONFIG_MISSING, "CONFIG_MISSING")
        self.assertEqual(len(self.calls), 0, "설정이 없는데 호출을 시도했다")


if __name__ == "__main__":
    unittest.main()
