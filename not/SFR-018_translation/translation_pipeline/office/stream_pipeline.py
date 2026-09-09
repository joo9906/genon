"""스트리밍 번역 — **번역문이 만들어지는 대로 흘린다** (`not/` 판본).

> 이 파일은 `not/` 에만 있다. 정본(`onprem/`)의 번역은 스켈레톤 분해 + 배치
> JSON 이라 **흘릴 것이 없다**(원시 `{"id":1,"t":"…"` 이 화면에 보이고, 배치 15개가
> 도는 순서도 문서 순서가 아니다). 요구가 "번역도 주루룩 보이게" 로 바뀌어 만든 경로다.

## 흐름 — 흘리고, 끝나면 한 번 더 부른다

```
POST /translate/stream      (SSE)   ← 번역문 델타가 문서 순서대로 흐른다
      … delta … delta … done{options, chunks}
POST /translate/finalize    (JSON)  ← {original_text, translated_text, glossary, …}
                                       프론트가 이걸 받아 **바뀐 낱말만** 칠한다
```

**두 번 부르는 이유**는 하이라이트가 번역이 끝나야 정해지기 때문이다. 용어사전 준수
판정(`applied`)은 번역문 전체를 봐야 하고, 좌표(`spans`·`target_spans`)는 최종 문자열
기준이라 흐르는 도중에는 존재하지 않는다. 흘리는 것은 **정본 텍스트**이고 태그가 섞이지
않는다 — 사본(`<mark>`)을 흘리면 ① 하이라이트가 스트리밍 중에 먼저 나타나 요구가 말한
순서와 어긋나고 ② 태그가 조각 경계에서 갈려 `<ma` 같은 부스러기가 남는다.

**finalize 는 상태를 두지 않는다.** 프론트가 방금 받은 두 텍스트를 되돌려 보내면 서빙이
용어사전 대조를 다시 한다 — 용어 매칭은 **결정적**이라 같은 입력에서 같은 답이 나오고,
Redis 세션을 붙이면 이 무상태 단위에 상태가 생긴다(글다듬이를 무상태로 둔 것과 같은
판단). 대신 **길이 상한은 여기서도 건다** — 되돌아오는 본문이 곧 요청 크기다.

## 구조 보존은 감지로 바뀐다 (`stream_chunking` 머리말 참고)

스켈레톤을 쓰지 않으므로 표·코드펜스를 지키는 주체가 코드에서 프롬프트로 넘어간다.
못 막는 대신 **숨기지 않는다** — `structure_diff` 가 원문·번역문의 구조 지문을 세어
어긋나면 finalize 응답의 `structure.issues` 로 낸다(글다듬이 `markdown_guard` 와 같은
취지다). 표가 많은 문서는 정본 경로(`POST /translate/markdown`)가 맞다.
"""

import asyncio
import re
from dataclasses import dataclass, field

from config import Config
from translation_pipeline.common.glossary_exact import (
    contains_phrase,
    match_occurrences,
    phrase_positions,
)
from translation_pipeline.common.llm import (
    CONFIG_MISSING,
    STREAM_UNSUPPORTED,
    llm_call_async,
    translate_stream_async,
)
from translation_pipeline.common.logging_utils import log_info, log_warning
from translation_pipeline.common.prompt_builder import PromptContext, build_stream_prompts
from translation_pipeline.common.prompt_loader import PromptRenderError

from . import stream_chunking
from .glossary_report import terms_for_batch
from .languages import glossary_applies
# **판정을 다시 짜지 않는다.** 원문 언어 교차검증(§6 축 거부)·문체 폴백은
# `pipeline._resolve_options` 한 곳에 있다 — 여기서 다시 구현하면 스트리밍 경로만
# 그 집행을 건너뛰는 뒷문이 생기고, 그 상태는 "en→ru 가 통과한다" 로만 드러난다.
from .pipeline import _glossary_source_status, _options_payload, _resolve_options


@dataclass
class StreamOutcome:
    """스트리밍 번역 결과. 예외 대신 값으로 실패를 담는다."""

    text: str = ""
    chunk_count: int = 0          # LLM 을 부른 조각 수 (빈 조각은 세지 않는다)
    failed_chunk_count: int = 0
    streamed_chars: int = 0       # 실제로 흘린 글자 수
    stream_unsupported: bool = False   # 게이트웨이가 스트리밍을 안 받는다
    stream_diverged: bool = False      # 흘린 것과 정본이 어긋났다 (되돌릴 수 없다)
    error_type: str = ""
    is_transport_error: bool = False

    @property
    def ok(self) -> bool:
        """조각 하나라도 번역됐으면 성공이다 (부분 실패 규약).

        전량 실패만 오류다 — 실패한 조각 자리에는 원문이 들어가므로 결과는 여전히
        읽을 수 있는 문서이고, 몇 조각이 실패했는지는 `failed_chunk_count` 가 남긴다.
        """
        return self.chunk_count == 0 or self.failed_chunk_count < self.chunk_count

    @property
    def config_missing(self) -> bool:
        return self.error_type == CONFIG_MISSING


def resolve_options(target_lang: str, source_lang: str, register: str, sample_text: str):
    """언어·문체 확정. `pipeline` 과 **같은 함수**를 지난다 (위 import 주석)."""
    return _resolve_options(
        target_lang=target_lang,
        source_lang=source_lang,
        register=register,
        sample_text=sample_text,
    )


def options_payload(options) -> dict:
    return _options_payload(options)


def _prompt_context(options) -> PromptContext:
    return PromptContext(
        source_label=options.source_label,
        target_label=options.target_label,
        register_label=options.register_label,
        register_instruction=options.register_instruction,
    )


def _chunk_prompts(chunk_text: str, options) -> tuple:
    """조각 하나의 (system, user).

    **용어사전은 이 조각에 실제로 나온 것만** 싣는다 (`terms_for_batch` 규약 그대로).
    사전 전체를 실으면 토큰이 폭발하고, 등장하지 않는 용어까지 지시하면 모델이 억지로
    끼워 넣는다.
    """
    terms = terms_for_batch([chunk_text], options.target_code, options.source_code)
    return build_stream_prompts(_prompt_context(options), chunk_text, terms)


# ═══════════════════════════════════════════════════════════════════════════
# 흘리는 순서 — 조각은 겹쳐 돌지만 화면은 문서 순서다
# ═══════════════════════════════════════════════════════════════════════════
# 조각들은 세마포어 상한 안에서 함께 돈다. 끝난 순서대로 흘리면 **문단이 뒤섞이는데,
# 최종 `text` 는 `rebuild` 가 자리를 맞추므로 멀쩡하다** — 스트리밍 중에만 틀리고
# 로그에는 아무것도 안 남는다. 그래서 병렬은 유지하고 흘리는 순서만 묶는다:
# **머리 조각**은 델타가 오는 대로 라이브로, **뒤 조각**은 자기 버퍼에 모아 두고
# 차례가 오면 한 번에 붙인다.
#
# ## 실패 조각의 원문은 최종 판정 뒤에만 흘린다
#
# 실패 자리에 원문을 되꽂는 것은 기존 규약이지만(`stream_chunking.rebuild`), 그것을
# **실패하는 즉시** 흘리면 전량 실패에서 원문이 통째로 화면에 나간 뒤 오류로 갈아엎게
# 된다 — 사용자에게는 답이 나왔다가 사라지는 것으로 보인다. 스트리밍을 안 받는 배포는
# 그 특수한 경우다(모든 조각이 `STREAM_UNSUPPORTED` 로 실패한다).
#
# 그래서 규칙은 하나다 — **한 글자도 안 흘린 실패 조각을 만나면 그 자리에서 멈춘다.**
# `gather` 가 끝나 `ok` 면 멈춰 둔 자리를 풀어 흘린다(전량 실패면 풀지 않는다).


async def _emit(state: dict, outcome: StreamOutcome, index: int, text: str) -> None:
    """흘린다. **`state["lock"]` 을 쥔 채로 부른다.**"""
    if not text:
        return
    state["flushed"][index] += len(text)
    outcome.streamed_chars += len(text)
    await state["on_text"](text)


async def _advance(state: dict, outcome: StreamOutcome) -> None:
    """머리부터 흘릴 수 있는 데까지 흘린다. **`state["lock"]` 을 쥔 채로 부른다.**"""
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
            # 흘린 뒤 끊긴 조각이다. 되돌릴 수 없으므로 사실만 올린다.
            outcome.stream_diverged = True

        # ⑤ 꼬리 공백은 **코드가** 되꽂는다 — LLM 이 응답 끝 공백을 지우므로, 이게 없으면
        #    문단 경계가 사라져 제목과 본문이 한 줄이 된다 (`stream_chunking` 머리말).
        await _emit(state, outcome, index, chunk.suffix)
        state["head"] = index + 1


async def _stream_chunk(
    semaphore: asyncio.Semaphore,
    index: int,
    chunk,
    options,
    state: dict,
    outcome: StreamOutcome,
    aborted: asyncio.Event,
) -> None:
    """조각 하나를 스트리밍으로 번역하고 순서 버퍼에 넣는다."""
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

    try:
        system_prompt, user_prompt = _chunk_prompts(chunk.text, options)
    except PromptRenderError as exc:
        # 이미지에 프롬프트 디렉토리를 안 넣은 **배포 실수**다. 조각 수만큼 두드릴
        # 이유가 없으므로 남은 조각도 세운다.
        outcome.failed_chunk_count += 1
        outcome.error_type = type(exc).__name__
        aborted.set()
        state["bodies"][index] = chunk.text
        state["failed"].add(index)
        state["finished"].add(index)
        async with state["lock"]:
            await _advance(state, outcome)
        return

    async with semaphore:
        result = await translate_stream_async(system_prompt, user_prompt, _on_delta)

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
        # 실패한 조각 자리에는 원문이 들어간다. **다만 지금 흘리지는 않는다** —
        # `_advance` 가 최종 판정까지 멈춰 둔다(위 머리말).
        state["bodies"][index] = chunk.text
        state["failed"].add(index)

    state["finished"].add(index)
    async with state["lock"]:
        await _advance(state, outcome)


def _new_state(chunks: list, on_text) -> dict:
    state = {
        "chunks": chunks,
        "on_text": on_text,
        "head": 0,
        # 아직 안 흘린 델타. 빈 `text` 조각도 자리를 만들어 둔다 — 인덱스가 곧 문서 순서다.
        "pending": {index: [] for index in range(len(chunks))},
        "flushed": {index: 0 for index in range(len(chunks))},
        "bodies": {},
        "finished": set(),
        "failed": set(),
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
    return state


async def translate_document_stream(markdown: str, options, on_text) -> StreamOutcome:
    """문서를 번역하면서 **문서 순서대로** 흘린다. 예외를 던지지 않는다.

    Args:
        markdown: 원문 (상한 검사는 라우트가 이미 했다).
        options: `resolve_options` 결과.
        on_text: `async def (str) -> None`. **호출은 직렬화된다** — 소비자가 SSE 에
            쓰므로 겹치면 글자가 섞인다.

    Returns:
        `StreamOutcome`. `text` 는 흘린 것과 **같아야 하고 그 등식이 이 함수의 계약**이다
        (`stream_chunking.rebuild` 로 조립한다). `stream_unsupported` 가 참이고
        `streamed_chars` 가 0 이면 호출부가 `translate_document_plain` 으로 되돌아간다.
    """
    chunks = stream_chunking.split_for_translation(markdown, Config.STREAM_CHUNK_CHARS)
    targets = [(index, chunk) for index, chunk in enumerate(chunks) if chunk.text]
    outcome = StreamOutcome(chunk_count=len(targets))
    if not targets:
        # 글자가 없는 문서다. LLM 을 부르지 않고 원문을 그대로 낸다 — 분모에 넣으면
        # 공백만 든 문서가 "전량 실패" 로 보인다.
        outcome.text = markdown
        if markdown:
            outcome.streamed_chars += len(markdown)
            await on_text(markdown)
        return outcome

    state = _new_state(chunks, on_text)
    semaphore = asyncio.Semaphore(max(1, Config.LLM_CONCURRENCY))
    aborted = asyncio.Event()
    log_info(
        "번역 스트리밍 조각 분할 완료",
        event="translate_stream_chunks_prepared",
        item_count=len(targets),
        status=f"budget={Config.STREAM_CHUNK_CHARS},concurrency={Config.LLM_CONCURRENCY}",
    )

    # 앞이 빈 조각이면 머리가 미리 나아갈 수 있으므로 한 번 밀어 둔다.
    async with state["lock"]:
        await _advance(state, outcome)

    await asyncio.gather(
        *[
            _stream_chunk(semaphore, index, chunk, options, state, outcome, aborted)
            for index, chunk in targets
        ]
    )
    outcome.text = stream_chunking.rebuild(chunks, state["bodies"])
    # **여기서 판정이 끝난다.** 조각 하나라도 번역됐으면 보류해 둔 실패 조각의 원문을
    # 풀어 흘린다(부분 실패 규약). 전량 실패면 풀지 않는다 — 흘린 것이 0 인 채로
    # 라우트가 오류 프레임을 낸다.
    if outcome.ok:
        state["finalize"] = True
        async with state["lock"]:
            await _advance(state, outcome)
    if outcome.failed_chunk_count:
        log_warning(
            "번역 조각 일부 실패 — 그 구간은 원문을 유지한다",
            event="translate_stream_chunk_failed",
            error_type=outcome.error_type,
            item_count=outcome.failed_chunk_count,
            status=(
                f"total={outcome.chunk_count}"
                f",diverged={int(outcome.stream_diverged)}"
                f",unsupported={int(outcome.stream_unsupported)}"
            ),
        )
    return outcome


async def translate_document_plain(markdown: str, options) -> StreamOutcome:
    """스트리밍을 안 받는 배포용 폴백 — **같은 조각 분할**로 비스트리밍 호출한다.

    같은 분할·같은 프롬프트를 쓰는 것이 요점이다. 폴백만 다른 방식으로 만들면 게이트웨이
    설정에 따라 **결과물이 달라지는데** 그 차이는 오류로 드러나지 않는다.
    """
    chunks = stream_chunking.split_for_translation(markdown, Config.STREAM_CHUNK_CHARS)
    targets = [(index, chunk) for index, chunk in enumerate(chunks) if chunk.text]
    outcome = StreamOutcome(chunk_count=len(targets))
    if not targets:
        outcome.text = markdown
        return outcome

    semaphore = asyncio.Semaphore(max(1, Config.LLM_CONCURRENCY))
    bodies: dict = {}
    aborted = asyncio.Event()

    async def _one(index: int, chunk) -> None:
        if aborted.is_set():
            outcome.failed_chunk_count += 1
            bodies[index] = chunk.text
            return
        try:
            system_prompt, user_prompt = _chunk_prompts(chunk.text, options)
        except PromptRenderError as exc:
            outcome.failed_chunk_count += 1
            outcome.error_type = type(exc).__name__
            aborted.set()
            bodies[index] = chunk.text
            return
        result = await llm_call_async(semaphore, system_prompt, user_prompt)
        if result.ok:
            bodies[index] = result.content
            return
        outcome.failed_chunk_count += 1
        outcome.error_type = result.error_type
        outcome.is_transport_error = outcome.is_transport_error or result.is_transport_error
        if result.error_type == CONFIG_MISSING:
            aborted.set()
        bodies[index] = chunk.text

    await asyncio.gather(*[_one(index, chunk) for index, chunk in targets])
    outcome.text = stream_chunking.rebuild(chunks, bodies)
    return outcome


# ═══════════════════════════════════════════════════════════════════════════
# finalize — 프론트가 하이라이트할 재료
# ═══════════════════════════════════════════════════════════════════════════


def build_document_glossary(original: str, translated: str, options) -> dict:
    """문서 **전체**를 한 단위로 보고 용어사전 준수를 판정한다.

    정본의 `glossary_report.build_report` 는 유닛(셀·문장) 단위로 돈다. 스트리밍 경로에는
    유닛이 없으므로 같은 판정을 문서 좌표로 한다 — 쓰는 함수는 **같은 셋**이다
    (`match_occurrences` · `contains_phrase` · `phrase_positions`). 규칙이 갈리면 같은
    문서가 경로에 따라 다른 준수율을 낸다.

    Returns:
        `{term_map, term_map_unapplied, hits, matched_count, applied_count, compliance,
          applies, source}`. `hits[].spans` 는 **원문** 좌표, `hits[].target_spans` 는
        **번역문** 좌표다 — 프론트가 좌우를 각각 칠한다.

    **적용된 용어만 양쪽을 칠한다** (요구사항 §2). "어떤 단어가 용어사전의 어떤 단어를
    참고하였는지" 가 요구이므로 참고하지 않은 자리는 칠할 관계가 없다 — 미준수는
    `term_map_unapplied` 와 준수율이 맡는 검수용 값이다.
    """
    applies = glossary_applies(options.source_code, options.target_code)
    payload = {
        "term_map": {},
        "term_map_unapplied": {},
        "hits": [],
        "matched_count": 0,
        "applied_count": 0,
        "compliance": 1.0,
        "applies": applies,
        "source": _glossary_source_status(options),
    }
    if not applies:
        return payload

    occurrences = match_occurrences(original, options.target_code)
    if not occurrences:
        return payload

    # 같은 용어가 여러 번 나오면 **위치만 모은다.** 판정과 건수는 용어 단위다 —
    # 등장마다 쪼개면 준수율 분모가 조용히 바뀐다(`build_report` 와 같은 규약).
    spans_by_term: dict = {}
    target_by_term: dict = {}
    for term, start, end in occurrences:
        spans_by_term.setdefault(term.term_source, []).append([start, end])
        target_by_term.setdefault(term.term_source, term.term_target)

    for term_source, spans in spans_by_term.items():
        term_target = target_by_term[term_source]
        applied = contains_phrase(translated, term_target)
        payload["matched_count"] += 1
        payload["applied_count"] += 1 if applied else 0
        if applied:
            payload["term_map"].setdefault(term_source, term_target)
        else:
            payload["term_map_unapplied"].setdefault(term_source, term_target)
        payload["hits"].append(
            {
                "term_source": term_source,
                "term_target": term_target,
                "applied": applied,
                "spans": spans,
                "target_spans": (
                    [list(pair) for pair in phrase_positions(translated, term_target)]
                    if applied
                    else []
                ),
            }
        )

    if payload["matched_count"]:
        payload["compliance"] = round(
            payload["applied_count"] / payload["matched_count"], 4
        )
    return payload


# 구조 지문 — **개수만** 센다. 내용은 담지 않는다 (3.8절: 문서 원문이 응답·로그에
# 실리면 안 된다). 어느 종류가 몇 개 어긋났는지까지가 여기서 말할 수 있는 전부다.
_FINGERPRINTS = (
    ("md_table_row", re.compile(r"(?m)^\s*\|")),
    ("code_fence", re.compile(r"(?m)^\s*(?:```|~~~)")),
    ("html_table", re.compile(r"<table\b", re.IGNORECASE)),
    ("html_row", re.compile(r"<tr\b", re.IGNORECASE)),
    ("html_cell", re.compile(r"<t[dh]\b", re.IGNORECASE)),
    ("heading", re.compile(r"(?m)^#{1,6}\s")),
    ("list_item", re.compile(r"(?m)^\s*(?:[-*+]\s|\d+\.\s)")),
)


def structure_diff(original: str, translated: str) -> dict:
    """원문·번역문의 구조 지문을 세어 어긋난 항목을 낸다.

    **막는 장치가 아니라 알리는 장치다.** 스켈레톤을 쓰지 않는 경로라 표·코드펜스를
    지키는 주체가 프롬프트이고, 프롬프트 지시는 보장이 아니다 — 그래서 끝나고 대조해서
    사실을 낸다(글다듬이 `markdown_structure_issues` 와 같은 취지).

    Returns:
        `{"ok": bool, "issues": [{"kind", "source", "translated"}]}`.
        숫자만 담는다 — 어느 줄이 깨졌는지는 문서 내용이라 싣지 않는다.
    """
    issues: list = []
    for kind, pattern in _FINGERPRINTS:
        before = len(pattern.findall(original))
        after = len(pattern.findall(translated))
        if before != after:
            issues.append({"kind": kind, "source": before, "translated": after})
    return {"ok": not issues, "issues": issues}
