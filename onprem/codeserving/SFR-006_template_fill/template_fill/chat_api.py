"""SFR-006 대화 3단계를 코드 서빙(03) 엔드포인트로 노출한다.

**`run_chat.py` 를 대체하는 것이 아니라, 그 안의 계산을 HTTP 로 꺼내는 파일이다.**
워크플로우 스텝(`onprem/workflow/sfr006_0*.py`)이 이 세 경로를 부른다.

```
POST /chat/context   세션·템플릿 확정 → 항목 목록·현재 값        (스텝 1)
POST /chat/extract   발화 → LLM 추출 → 코드 판정                (스텝 2)
POST /chat/commit    병합 → 세션 저장 → 미리보기 → 답변 문구      (스텝 3)
```

## 왜 워크플로우에서 옮겨 왔나

`run_chat.py` 는 `chat_state` → `template_index` → `redis_client`(redis) 와
`hwpx_fields`(lxml) 를 로컬 import 했다. 워크플로우 단계는 **pod 기본 이미지에 있는
패키지만** 쓸 수 있고 그 셋은 없다 (가이드 11.5.6 / GENOS_RULES §D.3). 계산이 이쪽에
있으면 워크플로우 스텝은 `httpx` 하나로 끝난다.

## 세 경로가 각자 세션·템플릿을 다시 읽는다

스텝 사이로 상태를 나르지 않는다는 뜻이다. 워크플로우 `data` 는 JSON 직렬화 가능한 값만
실을 수 있고(§I), `TurnContext` 는 템플릿 **바이트**를 들고 있어 애초에 못 넘긴다.
다시 읽는 비용은 `template_index` 캐시가 흡수한다 — 등록 시점 1회 파싱이다.

## 판정 책임은 그대로다 (루트 CLAUDE.md §5)

- **LLM**: 발화 → `{항목명: 값}` + 삭제 + 본문 블록 추출까지만.
- **코드**: 화이트리스트 검증, 채워짐·부족 판정, `ready` 결정, 서식 이름 검증.

## 배선

`main.py` 에서 한 줄로 붙인다 — `api_errors.install` 과 같은 규약이다.

```python
from .chat_api import install as install_chat_api
install_chat_api(app)
```

오류는 `ApiError` 로 올린다. `api_errors.install` 이 HTTP 상태와 `error_code` 로 바꾼다.
**단, 여기서 올리는 코드는 워크플로우(02) 계열이다** — `chat_state.load_context` 가
템플릿 오류를 02 코드로 바꿔 던지는 기존 규약을 유지한다. 호출자가 워크플로우 스텝이라
02 로 보이는 편이 운영에서 단계 추적에 맞다.
"""

from pydantic import BaseModel, Field

from .chat_reply import compose_status_reply
from .chat_state import (
    load_context,
    merge_blocks,
    merge_values,
    render_preview,
    restore_state,
)
from .config import Config
from .error_codes import (
    ApiError,
    ERR_CHAT_CONFIG_MISSING,
    ERR_CHAT_INTERNAL,
    ERR_CHAT_UPSTREAM_EXECUTION,
    ERR_CHAT_UPSTREAM_TIMEOUT,
)
from .field_judge import normalize_blocks, parse_updates
from .hwpx_fields import missing_field_names
from .llm import CONFIG_MISSING, llm_call_async
from .logging_utils import log_info, log_warning
from .prompt_loader import PromptRenderError
from .prompts import build_extract_prompts
from .session_store import SessionStoreError, load_session, save_session


# ─────────────────────────────────────────────────────────────
# 요청 모델
# ─────────────────────────────────────────────────────────────
class ContextRequest(BaseModel):
    session_id: str = ""
    template_id: str = ""


class ExtractRequest(BaseModel):
    session_id: str = ""
    template_id: str = ""
    question: str = ""


class CommitRequest(BaseModel):
    session_id: str = ""
    template_id: str = ""
    fields_updated: dict = Field(default_factory=dict)
    fields_cleared: list = Field(default_factory=list)
    fields_rejected: list = Field(default_factory=list)
    blocks_added: list = Field(default_factory=list)
    block_clears: list = Field(default_factory=list)


def _log_context(session_id: str) -> dict:
    """워크플로우가 넘겨준 trace_id 가 없으므로 비워 둔다.

    **의도적으로 session_id 를 로그에 넣지 않는다** — 3.8절 허용 필드가 아니다.
    단계 간 추적이 필요하면 워크플로우가 `trace_id` 를 요청 헤더로 실어 주고 여기서
    읽는 쪽이 맞다 (아직 배선하지 않았다).
    """
    return {}


async def _load_turn(session_id: str, template_id: str) -> tuple:
    """세 경로가 공통으로 하는 것: 세션 읽기 → 템플릿 확정 → 상태 복원.

    이번 턴 지정(`template_id`)이 세션에 저장된 것보다 우선한다 — 사용자가 템플릿을
    바꾼 턴에 옛 템플릿으로 판정하면 항목이 통째로 어긋난다.
    """
    try:
        session = await load_session(session_id) if session_id else {}
    except (ValueError, SessionStoreError):
        # Redis 장애는 대화를 막지 않는다 — 빈 세션으로 시작한다. 다만 값이 유지되지
        # 않는다는 사실은 저장 시점에 오류로 드러난다.
        session = {}

    resolved_id = (template_id or str(session.get("template_id") or "")).strip()
    context = await load_context(resolved_id)
    state = restore_state(session, context, _log_context(session_id))
    return context, state


def install(app) -> None:
    """FastAPI 앱에 대화 3단계를 등록한다."""

    @app.post("/chat/context")
    async def chat_context(request: ContextRequest):
        """스텝 1 — 어느 템플릿인지 확정하고 항목 목록·현재 값을 낸다."""
        context, state = await _load_turn(request.session_id, request.template_id)
        missing = missing_field_names(context.specs, state.values)

        # 템플릿 파일명·개수까지만 (3.8절). 항목 값은 남기지 않는다.
        log_info(
            "템플릿 컨텍스트 조회",
            event="chat_context_loaded",
            resource_id=f"{context.template_id}.hwpx",
            item_count=len(context.specs),
            status=(
                f"collected={len(state.values)}"
                f" missing={len(missing)}"
                f" blocks={len(state.blocks)}"
                f" cached={int(context.index.from_cache)}"
            ),
        )

        return {
            "template_id": context.template_id,
            "field_names": [spec.name for spec in context.specs],
            "block_styles": list(context.block_styles),
            "field_values": dict(state.values),
            "blocks": [
                {"text": b.text, "style_ref": b.style_ref, "raw_text": b.raw_text}
                for b in state.blocks
            ],
            "fields_missing": missing,
            "ready_for_download": not missing,
            "template_markdown": context.index.markdown,
            "template_markdown_truncated": context.index.truncated,
            "from_cache": bool(context.index.from_cache),
        }

    @app.post("/chat/extract")
    async def chat_extract(request: ExtractRequest):
        """스텝 2 — 발화에서 값·삭제·본문 블록을 뽑고 코드로 검증한다.

        **저장하지 않는다.** 병합·저장은 `/chat/commit` 이 한다 — 추출이 성공했는데
        저장에서 실패한 중간 상태를 캔버스에 만들지 않기 위해서다.
        """
        question = (request.question or "").strip()[: Config.MAX_MESSAGE_CHARS]
        if not question:
            # 빈 발화로 LLM 을 부르면 항목을 지어낸다. 호출부도 막지만 여기서도 막는다.
            return _empty_extraction()

        context, state = await _load_turn(request.session_id, request.template_id)

        # 프롬프트 렌더 실패는 LLM 실패와 따로 잡는다 — 전자는 이미지에 프롬프트
        # 디렉토리를 안 넣은 배포 실수라 운영에서 구분돼야 손을 쓸 수 있다.
        try:
            system_prompt, user_prompt = build_extract_prompts(
                context.specs, state.values, question, context.block_styles, state.blocks
            )
        except PromptRenderError as exc:
            log_warning(
                "프롬프트 생성 실패",
                event="prompt_render_failed",
                error_type=type(exc).__name__,
            )
            raise ApiError(ERR_CHAT_INTERNAL) from exc

        try:
            result = await llm_call_async(system_prompt, user_prompt)
        except Exception as exc:  # noqa: BLE001 - 클라이언트 초기화 실패 등
            log_warning(
                "LLM 호출 준비 실패",
                event="llm_setup_failed",
                error_type=type(exc).__name__,
            )
            raise ApiError(ERR_CHAT_INTERNAL) from exc

        if not result.ok:
            # 설정 부재를 먼저 가른다 — **재시도로 풀리지 않는 배포 문제**라 실행 실패와
            # 같은 retryable 로 내보내면 캔버스가 무의미한 재시도를 건다
            # (`ERR_CHAT_CONFIG_MISSING` 머리말 참고).
            if result.error_type == CONFIG_MISSING:
                raise ApiError(ERR_CHAT_CONFIG_MISSING)
            raise ApiError(
                ERR_CHAT_UPSTREAM_TIMEOUT
                if result.is_transport_error
                else ERR_CHAT_UPSTREAM_EXECUTION
            )

        intent = parse_updates(
            result.content,
            context.allowed_names,
            allowed_styles=context.block_styles,
            block_count=len(state.blocks),
        )

        if intent.conflicts:
            # 모순 해소는 field_judge 가 한다(수정 채택). 조용히 넘기지 않고 건수를 남긴다.
            log_warning(
                "같은 항목에 수정·삭제 의도가 함께 와서 수정을 채택",
                event="edit_intent_conflict",
                item_count=len(intent.conflicts),
            )
        if intent.rejected:
            # 기각 건수는 006 환각률 지표의 원천이다 — 침묵 처리하지 않는다
            log_warning(
                "LLM 응답에서 템플릿에 없는 필드명을 기각",
                event="extraction_keys_rejected",
                item_count=len(intent.rejected),
            )

        accepted = dict(intent.updates)
        added_blocks = list(intent.blocks)

        return {
            "fields_updated": accepted,
            "fields_cleared": list(intent.clears),
            "fields_rejected": list(intent.rejected),
            # 블록은 HTTP 경계를 넘어야 하므로 dict 로 편다. `/chat/commit` 이
            # `normalize_blocks` 로 되읽으며 **같은 검증**을 다시 태운다.
            "blocks_added": [
                {"text": b.text, "style_ref": b.style_ref, "raw_text": b.raw_text}
                for b in added_blocks
            ],
            "block_clears": list(intent.block_clears),
        }

    @app.post("/chat/commit")
    async def chat_commit(request: CommitRequest):
        """스텝 3 — 병합·저장·미리보기·답변 문구를 한 요청으로 처리한다.

        셋을 나누면 "저장은 됐는데 미리보기에서 실패한" 중간 상태가 캔버스에 생긴다.
        """
        context, state = await _load_turn(request.session_id, request.template_id)

        # 이전 값을 남겨 둔다 — 답변에 `이전 → 새 값` 을 보여주려면 필요하고, 대화로
        # 값을 고치는 경로에서 의도치 않은 덮어쓰기를 사용자가 알아채는 유일한 수단이다.
        previous = dict(state.values)

        accepted = dict(request.fields_updated or {})
        state.raw_values.update(accepted)
        cleared = merge_values(state, accepted, list(request.fields_cleared or []))

        # 넘어온 블록도 되읽을 때 같은 검증을 태운다 — 없는 서식 이름은 기본 서식으로
        # 떨어뜨린다. HTTP 경계를 건너온 값을 그대로 믿지 않는다.
        added_blocks, stale = normalize_blocks(
            list(request.blocks_added or []), context.block_styles
        )
        if stale:
            log_warning(
                "본문 블록 일부가 현재 템플릿 서식과 맞지 않는다",
                event="blocks_commit_stale",
                item_count=len(stale),
            )

        dropped_blocks, overflow = merge_blocks(
            state, added_blocks, list(request.block_clears or []), {}
        )
        rejected = list(request.fields_rejected or [])
        if overflow:
            rejected = rejected + [f"<blocks: 개수 상한({Config.MAX_BLOCKS}건) 초과>"]

        # 세션 저장 — 실패는 침묵 처리하지 않는다. 다음 턴에 값이 유실된다는 뜻이다.
        # **저장은 덮어쓰기라** 값만 저장하면 블록이 지워진다 → 항상 함께 넘긴다.
        if request.session_id:
            try:
                await save_session(
                    request.session_id,
                    context.template_id,
                    state.values,
                    state.raw_values,
                    state.blocks,
                )
            except SessionStoreError as exc:
                log_warning(
                    "세션 저장 실패 — 이번 턴 값이 다음 턴에 유지되지 않는다",
                    event="session_save_failed",
                    error_type=type(exc).__name__,
                )
                raise ApiError(ERR_CHAT_INTERNAL) from exc

        missing = missing_field_names(context.specs, state.values)
        document_markdown, document_truncated = await render_preview(context, state, {})

        display_text = compose_status_reply(
            context.specs,
            state.values,
            accepted,
            rejected,
            previous=previous,
            cleared=cleared,
            blocks=state.blocks,
            added_blocks=added_blocks,
            dropped_blocks=dropped_blocks,
        )

        log_info(
            "대화 턴 커밋",
            event="chat_commit_done",
            resource_id=f"{context.template_id}.hwpx",
            item_count=len(state.values),
            status=f"missing={len(missing)} blocks={len(state.blocks)} ready={int(not missing)}",
        )

        return {
            "text": display_text,
            "field_values": dict(state.values),
            "field_values_raw": dict(state.raw_values),
            "fields_filled": [s.name for s in context.specs if s.name not in missing],
            "fields_missing": missing,
            "ready_for_download": not missing,
            "blocks": [
                {"text": b.text, "style_ref": b.style_ref, "raw_text": b.raw_text}
                for b in state.blocks
            ],
            "blocks_removed": len(dropped_blocks),
            "document_markdown": document_markdown,
            "document_markdown_truncated": document_truncated,
        }


def _empty_extraction() -> dict:
    return {
        "fields_updated": {},
        "fields_cleared": [],
        "fields_rejected": [],
        "blocks_added": [],
        "block_clears": [],
    }
