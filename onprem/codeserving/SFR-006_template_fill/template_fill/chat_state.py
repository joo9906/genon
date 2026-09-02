"""대화(02) 한 턴의 **상태 전이** — 무엇을 읽어 오고, 어떻게 합치는가.

`run_chat.run()` 은 GenOS 계약(async generator, `token`…`result`) 때문에 통짜 제너레이터일
수밖에 없다. 그 안에 상태 계산까지 들어가면 "스트리밍 흐름" 과 "값 판정" 이 한 함수에서
뒤섞여, 둘 중 하나만 고치려 해도 전체를 읽어야 한다. 계산만 여기로 뺀다.

여기 있는 것은 전부 **결정적**이다 — LLM 을 부르지 않고, 주어진 추출 결과를 어떻게
받아들일지만 정한다. (판정 책임은 코드에 있다 — 루트 CLAUDE.md §5.)
"""

import asyncio
from dataclasses import dataclass, field as dc_field

from .config import Config
from .error_codes import (
    ApiError,
    ERR_CHAT_NO_FIELDS,
    ERR_CHAT_TEMPLATE_INVALID,
    ERR_CHAT_TEMPLATE_NOT_FOUND,
)
from .field_judge import normalize_blocks
from .hwpx_fields import TemplateError
from .logging_utils import log_warning
from .template_index import get_index
from .template_store import read as read_template


@dataclass
class TurnContext:
    """이번 턴이 기준으로 삼는 템플릿 정보 (읽기 전용)."""

    template_id: str
    template_bytes: bytes
    index: object
    specs: list                       # 채울 항목 스키마 (상한 적용)
    allowed_names: set                # 값 화이트리스트
    block_styles: list                # 본문 블록 서식 화이트리스트


@dataclass
class TurnState:
    """세션에서 읽어 이번 턴에 갱신할 상태."""

    values: dict = dc_field(default_factory=dict)
    blocks: list = dc_field(default_factory=list)


async def load_context(template_id: str) -> TurnContext:
    """템플릿을 읽고 채울 항목 스키마를 확보한다.

    색인 캐시를 경유한다 — 예전에는 **매 턴** zip+XML 을 다시 파싱했다. 캐시가 비어 있거나
    Redis 가 죽어 있으면 `template_index` 가 직접 파싱으로 degrade 하므로 기능은 그대로다.

    경로 검증·파일 읽기는 코드 서빙과 **같은 `template_store`** 를 쓴다. 예전에는 여기에
    자체 경로 정리(`..`·구분자를 지우는 방식)가 따로 있었는데, 등록 API 가 거부하는 이름을
    대화 경로는 받아들이는 비대칭이 있었다.

    Raises:
        ApiError: 템플릿 없음/해석 불가/채울 항목 없음. 워크플로우(02) 오류 코드로 올린다 —
            호출부가 `data["error"]` 로 바꾼다.
    """
    try:
        template_bytes = await read_template(template_id)
    except ApiError as exc:
        # 코드 서빙(03) 코드로 올라온 것을 워크플로우(02) 코드로 바꿔 던진다.
        # 영역코드가 섞이면 운영에서 어느 단계가 실패했는지 구분이 안 된다 (가이드 3.9.2).
        raise ApiError(ERR_CHAT_TEMPLATE_NOT_FOUND) from exc

    try:
        index = await get_index(template_id, template_bytes)
    except TemplateError as exc:
        raise ApiError(ERR_CHAT_TEMPLATE_INVALID) from exc

    specs = index.fields[: Config.MAX_FIELDS]
    if not specs:
        raise ApiError(ERR_CHAT_NO_FIELDS)

    return TurnContext(
        template_id=template_id,
        template_bytes=template_bytes,
        index=index,
        specs=specs,
        allowed_names={spec.name for spec in specs},
        # 서식 목록이 비어 있으면(기능 꺼짐/복제 가능한 문단 없음) 프롬프트에도 넣지 않는다 —
        # 쓸 수 없는 기능을 설명하면 LLM 이 그쪽으로 답을 만든다.
        block_styles=list(index.block_styles) if Config.BODY_BLOCKS else [],
    )


def restore_state(session: dict, context: TurnContext, log_context: dict) -> TurnState:
    """세션 상태를 지금 템플릿에 맞게 걸러 읽는다.

    템플릿이 교체되면 사라진 항목·서식이 남아 있을 수 있다. 값은 화이트리스트로 버리고,
    블록은 **되읽을 때도 같은 검증**(`normalize_blocks`)을 거쳐 없는 서식 이름을 기본
    서식으로 떨어뜨린다.
    """
    allowed = context.allowed_names
    blocks, stale = normalize_blocks(session.get("blocks"), context.block_styles)
    if stale:
        log_warning(
            "세션의 본문 블록 일부가 현재 템플릿과 맞지 않는다",
            event="blocks_session_stale",
            item_count=len(stale),
            **log_context,
        )
    return TurnState(
        values={k: v for k, v in (session.get("values") or {}).items() if k in allowed},
        blocks=blocks,
    )


def merge_values(state: TurnState, accepted: dict, clears: list) -> list:
    """값 수정·삭제를 반영하고 **실제로 비워진** 항목명을 돌려준다.

    세션에 값이 없던 항목을 "비웠다" 고 말하지 않는다 — 템플릿에 원래 적혀 있던 값은
    문서에 남으므로, 그 항목은 여전히 채워진 것으로 보일 수 있다.
    """
    state.values.update(accepted)
    cleared: list = []
    for name in clears:
        if state.values.pop(name, None) is not None:
            cleared.append(name)
    return cleared


def merge_blocks(state: TurnState, added: list, clear_indexes: list, log_context: dict) -> tuple:
    """본문 블록 추가·삭제를 반영한다.

    **삭제를 먼저, 추가를 나중에** 한다. `clear_indexes` 는 LLM 이 이번 턴에 본 목록
    (= 추가 이전 상태) 기준이므로, 순서를 바꾸면 방금 추가한 문단이 지워진다.

    Returns:
        (지워진 블록 목록, 상한에 걸려 못 넣은 블록 수). 상한 초과는 조용히 자르지 않고
        호출부가 사용자에게 알릴 수 있도록 건수를 돌려준다.
    """
    dropped = [state.blocks[i] for i in clear_indexes]
    if clear_indexes:
        removing = set(clear_indexes)
        state.blocks = [b for i, b in enumerate(state.blocks) if i not in removing]

    room = max(0, Config.MAX_BLOCKS - len(state.blocks))
    overflow = max(0, len(added) - room)
    if overflow:
        log_warning(
            "본문 블록 개수 상한에 걸려 일부를 반영하지 못했다",
            event="blocks_limit_exceeded",
            item_count=overflow,
            **log_context,
        )
        added = added[:room]
    state.blocks = state.blocks + added
    return dropped, overflow


async def render_preview(context: TurnContext, state: TurnState, log_context: dict) -> tuple:
    """지금 값·블록으로 채운 문서 미리보기 (표시 전용).

    **코드 서빙 `GET /preview` 와 같은 함수**(`render_filled`)를 쓴다 — 두 경로가 각자
    조립하면 채팅 창과 미리보기가 같은 세션을 다르게 그린다.
    부가 기능이므로 실패해도 대화를 막지 않는다.

    Returns:
        (마크다운, 잘렸는지)
    """
    if not Config.CHAT_PREVIEW:
        return "", False
    from .hwpx_markdown import render_filled

    try:
        rendered = await asyncio.to_thread(
            render_filled,
            context.template_bytes,
            state.values,
            max_chars=Config.MAX_PREVIEW_CHARS,
            blocks=state.blocks,
        )
    except Exception as exc:  # noqa: BLE001 - 미리보기 실패가 대화를 막지 않게
        log_warning(
            "대화 미리보기 생성 실패 — 미리보기 없이 진행",
            event="chat_preview_failed",
            error_type=type(exc).__name__,
            **log_context,
        )
        return "", False
    return rendered.markdown, rendered.truncated
