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
from .llm import (
    CONFIG_MISSING,
    STREAM_UNSUPPORTED,
    polish_stream_async,
    polish_text_async,
)
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

    # ── 스트리밍 경로에서만 채워진다 (`polish_document_stream`) ──
    #
    # `streamed_chars` 가 0 인데 `stream_unsupported` 가 참이면 **한 글자도 안 흘렸다** =
    # 라우트가 비스트리밍으로 되돌아가도 화면이 겹치지 않는다. 이 둘을 함께 봐야 하는
    # 이유는 그 절의 머리말에 있다.
    streamed_chars: int = 0
    stream_unsupported: bool = False
    # 머리 조각이 흘린 **뒤에** 끊겼다 = 화면에 나간 글과 정본이 어긋난다. 되돌릴 수
    # 없으므로 사실만 올려 스텝이 안내문을 낸다.
    stream_diverged: bool = False

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


# ═══════════════════════════════════════════════════════════════════════════
# 스트리밍 — **문서 순서를 지키는 버퍼** (2026-09-09)
# ═══════════════════════════════════════════════════════════════════════════
# `polish_document` 는 다 끝난 뒤 문서를 돌려준다. 그래서 화면은 LLM 이 도는 동안 비어
# 있고, 스텝이 조각내 흘리는 것은 완성 뒤의 연출이다. 여기는 **다듬어지는 대로** 흘린다.
#
# ## 왜 버퍼가 필요한가
#
# 조각은 세마포어 상한 안에서 **함께** 돈다(위 "동시 실행"). 그래서 조각 3이 조각 1보다
# 먼저 끝날 수 있는데, 끝난 순서대로 흘리면 **문서 순서가 뒤섞인다.** 순차로 바꾸면
# 순서는 지켜지지만 조각 수만큼 시간이 곱해져 나눈 이유(타임아웃)가 되살아난다.
#
# 그래서 병렬은 유지하고 **흘리는 순서만** 묶는다:
#
#   - **머리 조각**(앞의 조각이 전부 흘러간 것)은 델타가 오는 대로 그대로 흘린다.
#     이것이 사용자가 보는 "주루룩" 이다.
#   - **뒤 조각**이 먼저 끝났으면 자기 버퍼에 모아 둔다. 머리가 끝나 차례가 오면
#     **모인 만큼을 한 번에** 붙이고, 아직 도는 중이면 그때부터 라이브로 넘어간다.
#     (요구 확정: 뒤 조각이 먼저 끝난 경우 한방에 붙여도 된다.)
#
# ## 흘린 것과 정본이 같아야 한다
#
# 스텝은 흘린 것을 화면에 이어 쓰고 `result` 가 하이라이트 사본으로 갈아 끼운다. 둘이
# 어긋나면 화면이 순간 다른 글을 보여주고, 그 어긋남은 **오류로 드러나지 않는다.**
# 그래서 `content` 를 `strip()` 하지 않고(`llm.polish_stream_async` 머리말), 조각 사이
# 꼬리 공백도 `chunking.rebuild` 와 **같은 순서**로 흘린다 — 본문 → `suffix`.
#
# **딱 한 자리에서 어긋날 수 있다**: 머리 조각이 **흘린 뒤에** 끊긴 경우다. 화면에 이미
# 나간 부분 출력은 되돌릴 수 없는데 정본은 그 자리에 원문을 쓴다(실패 조각 규약). 그
# 사실을 `stream_diverged` 로 올려 스텝이 안내문을 낼 수 있게 한다 — 조용히 넘기면
# 사용자는 화면에서 사라진 문장을 찾게 된다.
#
# ## 실패한 조각의 원문은 **최종 판정 뒤에만** 흘린다
#
# 실패 조각 자리에는 원문이 들어간다(`chunking.rebuild` 규약). 그런데 그것을 실패하는
# 즉시 흘리면 **전량 실패에서 원문이 통째로 화면에 흘러 나간 뒤** 라우트가 오류로
# 갈아엎는다 — 사용자에게는 답이 나왔다가 사라지는 것으로 보인다(스모크가 이걸 잡았다).
# 스트리밍을 안 받는 배포는 같은 사건의 특수한 경우다: 모든 조각이 `STREAM_UNSUPPORTED`
# 로 실패하므로, 즉시 흘리면 원문이 나간 뒤 폴백이 다듬은 글을 **다시** 보낸다.
#
# 그래서 규칙은 하나다 — **한 글자도 안 흘린 실패 조각을 만나면 그 자리에서 멈춘다.**
# 조각 하나라도 성공했는지는 `gather` 가 끝나야 알 수 있고, 그때 `ok` 면 멈춰 둔 자리를
# 풀어 흘린다(전량 실패면 풀지 않는다 — 흘린 것이 0 이라 오류 프레임만 나간다).
#
# **전량 실패면 흘린 것이 언제나 0 이다**: 전량이란 첫 조각도 실패했다는 뜻이고, 머리가
# 거기서 멈추므로 뒤 조각은 버퍼에만 쌓인다.


async def _stream_chunk(
    semaphore: asyncio.Semaphore,
    index: int,
    chunk,
    system_prompt: str,
    state: dict,
    outcome: PolishOutcome,
    aborted: asyncio.Event,
) -> None:
    """조각 하나를 스트리밍으로 다듬고 순서 버퍼에 넣는다.

    `state` 는 `polish_document_stream` 이 만든 **공유** 상태다. 조각마다 값 객체를 두면
    머리 판정을 할 수 없다 — 그건 조각 하나의 상태가 아니라 조각들 사이의 상태다.
    """
    if aborted.is_set():
        # 설정 부재가 이미 확인됐다. 남은 조각을 부르면 같은 실패만 쌓인다.
        outcome.failed_chunk_count += 1
        state["bodies"][index] = chunk.text
        state["failed"].add(index)
        state["finished"].add(index)
        async with state["lock"]:
            await _advance(state, outcome)
        return

    async def _on_delta(piece: str) -> None:
        async with state["lock"]:
            if state["head"] == index:
                # 내 차례다 — 모아 둔 것을 먼저 비우고 이어서 흘린다.
                buffered = state["pending"][index]
                if buffered:
                    text = "".join(buffered)
                    buffered.clear()
                    await _emit(state, outcome, index, text)
                await _emit(state, outcome, index, piece)
            else:
                # 앞 조각이 아직 안 끝났다. 모아 둔다 — 지금 흘리면 순서가 뒤섞인다.
                state["pending"][index].append(piece)

    async with semaphore:
        result = await polish_stream_async(system_prompt, chunk.text, _on_delta)

    if result.ok:
        state["bodies"][index] = result.content
    else:
        outcome.failed_chunk_count += 1
        outcome.error_type = result.error_type
        outcome.is_transport_error = outcome.is_transport_error or result.is_transport_error
        if result.error_type == CONFIG_MISSING:
            aborted.set()
        if result.error_type == STREAM_UNSUPPORTED:
            outcome.stream_unsupported = True
        # 실패한 조각 자리에는 원문이 들어간다 (`chunking.rebuild` 와 같은 규약).
        # **다만 지금 흘리지는 않는다** — `_advance` 가 최종 판정까지 멈춰 둔다(위 머리말).
        state["bodies"][index] = chunk.text
        state["failed"].add(index)

    state["finished"].add(index)
    async with state["lock"]:
        await _advance(state, outcome)


async def _emit(state: dict, outcome: PolishOutcome, index: int, text: str) -> None:
    """흘린다. **`state["lock"]` 을 쥔 채로 부른다.**

    흘린 양을 조각별로 세는 자리이기도 하다 — `_advance` 가 그 값으로 "이 조각은 이미
    흘렸는가" 를 판정한다.
    """
    if not text:
        return
    state["flushed"][index] += len(text)
    outcome.streamed_chars += len(text)
    await state["on_text"](text)


async def _advance(state: dict, outcome: PolishOutcome) -> None:
    """머리부터 흘릴 수 있는 데까지 흘린다. **`state["lock"]` 을 쥔 채로 부른다.**

    끝난 조각이 여러 개 이어져 있으면 그 전부를 이 한 번에 내보낸다 — 앞 조각을 기다리던
    뒤 조각들이 "한방에 붙는" 자리가 여기다.
    """
    chunks = state["chunks"]
    while state["head"] < len(chunks):
        index = state["head"]
        chunk = chunks[index]

        # ① 모아 둔 것을 먼저 비운다 (아직 도는 중일 수도 있다).
        buffered = state["pending"][index]
        if buffered:
            text = "".join(buffered)
            buffered.clear()
            await _emit(state, outcome, index, text)

        # ② 아직 안 끝났으면 여기서 멈춘다. 이 조각이 머리이므로 남은 델타는
        #    `_on_delta` 가 라이브로 흘린다.
        if index not in state["finished"]:
            return

        body = state["bodies"].get(index, chunk.text)
        already = state["flushed"][index]

        # ③ 한 글자도 안 흘린 **실패** 조각이다. 전량 실패인지 아직 모르므로 원문을
        #    흘리지 않고 멈춘다 (위 머리말). 최종 판정 뒤 `finalize` 로 풀린다.
        if already == 0 and index in state["failed"] and not state["finalize"]:
            return

        # ④ 확정 본문과 흘린 양을 맞춘다.
        if already == 0:
            await _emit(state, outcome, index, body)
        elif already != len(body):
            # 흘린 뒤 끊긴 조각이다 (위 머리말). 되돌릴 수 없으므로 사실만 올린다.
            outcome.stream_diverged = True

        # ⑤ 꼬리 공백은 **코드가** 되꽂는다 — LLM 이 응답 끝 공백을 지우므로, 이게 없으면
        #    문단 경계가 사라져 제목과 본문이 한 줄이 된다 (`chunking` 머리말).
        await _emit(state, outcome, index, chunk.suffix)
        state["head"] = index + 1


async def polish_document_stream(
    system_prompt: str, source_text: str, on_text
) -> PolishOutcome:
    """문서를 다듬으면서 **문서 순서대로** 흘린다. 예외를 던지지 않는다.

    Args:
        system_prompt: 문서유형·톤이 반영된 시스템 프롬프트.
        source_text: 다듬을 본문 (상한 검사는 라우트가 이미 했다).
        on_text: `async def (str) -> None`. 흘릴 글이 생길 때마다 불린다. **호출은
            직렬화된다** — 소비자가 소켓·SSE 에 쓰므로 겹치면 글자가 섞인다.

    Returns:
        `PolishOutcome`. `text` 는 `polish_document` 와 **같은 방식**으로 조립한다
        (`chunking.rebuild`) — 흘린 것과 같아야 하고 그 등식이 이 함수의 계약이다.
        `stream_unsupported` 가 참이고 `streamed_chars` 가 0 이면 게이트웨이가 스트리밍을
        받지 않는 배포이므로 호출부가 `polish_document` 로 되돌아가야 한다.
    """
    chunks = chunking.split_for_polish(source_text, Config.MAX_CHUNK_CHARS)
    targets = [(index, chunk) for index, chunk in enumerate(chunks) if chunk.text]
    outcome = PolishOutcome(chunk_count=len(targets))
    if not targets:
        # 글자가 없는 문서다. LLM 을 부르지 않고 원문을 그대로 낸다 — 분모에 넣으면
        # 공백만 든 문서가 "전량 실패" 로 보인다 (`polish_document` 와 같은 규약).
        outcome.text = source_text
        if source_text:
            outcome.streamed_chars += len(source_text)
            await on_text(source_text)
        return outcome

    state: dict = {
        "chunks": chunks,
        "on_text": on_text,
        "head": 0,
        # 아직 안 흘린 델타. 빈 `text` 조각도 자리를 만들어 둔다 — 인덱스가 곧 문서 순서다.
        "pending": {index: [] for index in range(len(chunks))},
        "flushed": {index: 0 for index in range(len(chunks))},
        "bodies": {},
        "finished": set(),
        # 실패한 조각 번호. ③ 의 보류 판정이 본다.
        "failed": set(),
        # 최종 판정이 끝났는가 — 참이 되면 보류해 둔 원문을 흘린다.
        "finalize": False,
        # `on_text` 직렬화 + 머리 이동. 조각들이 함께 도므로 이게 없으면 두 조각의
        # 글자가 섞여 나간다.
        "lock": asyncio.Lock(),
    }
    # 본문이 빈 조각(앞뒤가 통째로 공백인 문서에서 나온다)은 LLM 을 부르지 않으므로
    # **처음부터 끝난 것으로 둔다.** 안 그러면 머리가 그 자리에서 영영 멈춘다.
    for index, chunk in enumerate(chunks):
        if not chunk.text:
            state["bodies"][index] = ""
            state["finished"].add(index)

    semaphore = asyncio.Semaphore(max(1, Config.LLM_CONCURRENCY))
    aborted = asyncio.Event()
    log_info(
        "글다듬이 스트리밍 조각 분할 완료",
        event="polish_stream_chunks_prepared",
        item_count=len(targets),
        status=f"budget={Config.MAX_CHUNK_CHARS},concurrency={Config.LLM_CONCURRENCY}",
    )

    # 앞이 빈 조각이면 머리가 미리 나아갈 수 있으므로 한 번 밀어 둔다.
    async with state["lock"]:
        await _advance(state, outcome)

    await asyncio.gather(
        *[
            _stream_chunk(
                semaphore, index, chunk, system_prompt, state, outcome, aborted
            )
            for index, chunk in targets
        ]
    )
    outcome.text = chunking.rebuild(chunks, state["bodies"])
    # **여기서 판정이 끝난다.** 조각 하나라도 다듬어졌으면 보류해 둔 실패 조각의 원문을
    # 풀어 흘린다(부분 실패 규약). 전량 실패면 풀지 않는다 — 흘린 것이 0 인 채로 라우트가
    # 오류 프레임을 낸다.
    if outcome.ok:
        state["finalize"] = True
        async with state["lock"]:
            await _advance(state, outcome)
    if outcome.failed_chunk_count:
        log_warning(
            "글다듬이 조각 일부 실패 — 그 구간은 원문을 유지한다",
            event="polish_stream_chunk_failed",
            error_type=outcome.error_type,
            item_count=outcome.failed_chunk_count,
            status=(
                f"total={outcome.chunk_count}"
                f",diverged={int(outcome.stream_diverged)}"
                f",unsupported={int(outcome.stream_unsupported)}"
            ),
        )
    return outcome
