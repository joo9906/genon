"""문서를 조각으로 나눠 다듬고 원문 자리에 되꽂는다 — 실패는 조각 단위로 센다.

`main.py` 의 라우트에서 갈라져 나왔다. 라우트는 입력 검증·정책 확정·응답 조립을 하고,
**몇 번 부를지와 실패를 어떻게 셀지는 여기가 정한다.**

## 실패를 조각 단위로 가른다 (번역 단위의 규약을 그대로 따른다)

- **전량 실패는 오류다.** 원문을 그대로 돌려주면 사용자는 "다듬어졌는데 바뀐 게 없다"
  로 읽는다. 번역이 전량 폴백을 성공으로 흘려보내던 결함과 같은 자리다.
- **부분 실패는 결과를 낸다.** 조각 하나 때문에 다듬어진 문서 전체를 못 보게 할 이유가
  없다. 대신 **몇 조각이 실패했는지를 응답에 싣는다** — 그 값이 없으면 사용자는 어느
  구간이 손대지 않은 원문인지 알 수 없고, 그 상태는 로그에도 정상으로 보인다.
- **설정 부재(`CONFIG_MISSING`)는 첫 조각에서 끝낸다.** 재시도로 풀리지 않는 배포
  문제라 조각 수만큼 두드릴 이유가 없다.

## 동시 실행

조각은 서로 독립이므로 세마포어 상한 안에서 함께 돈다. 순차로 돌리면 조각 수만큼
시간이 곱해져 나누는 의미가 없다 — 나눈 이유가 타임아웃이었다.
"""

import asyncio
from dataclasses import dataclass

from . import chunking
from .config import Config
from .llm import CONFIG_MISSING, polish_text_async
from .logging_utils import log_info, log_warning


@dataclass
class PolishOutcome:
    """다듬기 결과 + 무엇이 얼마나 실패했는지."""

    text: str = ""
    chunk_count: int = 0
    failed_chunk_count: int = 0
    # 실패 분류 — 라우트가 오류 코드로 매핑한다. 전량 실패일 때만 의미가 있다.
    error_type: str = ""
    is_transport_error: bool = False

    @property
    def ok(self) -> bool:
        """조각 하나라도 다듬어졌는가. 전량 실패면 거짓이다."""
        return bool(self.text) and self.failed_chunk_count < self.chunk_count

    @property
    def config_missing(self) -> bool:
        return self.error_type == CONFIG_MISSING


async def _polish_chunk(
    semaphore: asyncio.Semaphore,
    index: int,
    chunk,
    system_prompt: str,
    polished: dict,
    outcome: PolishOutcome,
    aborted: asyncio.Event,
) -> None:
    if aborted.is_set():
        # 설정 부재가 이미 확인됐다. 남은 조각을 부르면 같은 실패만 쌓인다.
        outcome.failed_chunk_count += 1
        return
    async with semaphore:
        result = await polish_text_async(system_prompt, chunk.text)
    if result.ok:
        polished[index] = result.content
        return
    outcome.failed_chunk_count += 1
    outcome.error_type = result.error_type
    outcome.is_transport_error = outcome.is_transport_error or result.is_transport_error
    if result.error_type == CONFIG_MISSING:
        aborted.set()


async def polish_document(system_prompt: str, source_text: str) -> PolishOutcome:
    """문서를 다듬는다. 예외를 던지지 않고 `PolishOutcome` 으로 돌려준다.

    Args:
        system_prompt: 문서유형·톤이 반영된 시스템 프롬프트 (라우트가 렌더한다).
        source_text: 다듬을 본문 (상한 검사는 라우트가 이미 했다).

    Returns:
        PolishOutcome. 실패한 조각 자리에는 **원문이 그대로** 들어 있다.
    """
    chunks = chunking.split_for_polish(source_text, Config.MAX_CHUNK_CHARS)
    # 글자가 없는 조각(공백뿐)은 LLM 을 부르지 않는다. 세지도 않는다 — 분모에 넣으면
    # 공백만 든 문서가 "전량 실패" 로 보인다.
    targets = [(index, chunk) for index, chunk in enumerate(chunks) if chunk.text]
    outcome = PolishOutcome(chunk_count=len(targets))
    if not targets:
        outcome.text = source_text
        return outcome

    semaphore = asyncio.Semaphore(max(1, Config.LLM_CONCURRENCY))
    polished: dict = {}
    aborted = asyncio.Event()
    log_info(
        "글다듬이 조각 분할 완료",
        event="polish_chunks_prepared",
        item_count=len(targets),
        status=f"budget={Config.MAX_CHUNK_CHARS},concurrency={Config.LLM_CONCURRENCY}",
    )

    await asyncio.gather(
        *[
            _polish_chunk(
                semaphore, index, chunk, system_prompt, polished, outcome, aborted
            )
            for index, chunk in targets
        ]
    )

    # 실패한 조각은 `rebuild` 가 원문으로 채운다 — 빈 문자열로 두면 그 구간이 통째로
    # 사라진 결과가 정상 응답처럼 나간다.
    outcome.text = chunking.rebuild(chunks, polished)
    if outcome.failed_chunk_count:
        log_warning(
            "글다듬이 조각 일부 실패 — 그 구간은 원문을 유지한다",
            event="polish_chunk_failed",
            error_type=outcome.error_type,
            item_count=outcome.failed_chunk_count,
            status=f"total={outcome.chunk_count}",
        )
    return outcome
