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
import unittest

from . import onprem_path

onprem_path.install(onprem_path.TEXT_POLISH_UNIT)

from text_polish import chunking, polisher  # noqa: E402
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
