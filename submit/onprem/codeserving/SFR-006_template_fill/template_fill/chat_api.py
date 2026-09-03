"""SFR-006 대화 3단계를 코드 서빙(03) 엔드포인트로 노출한다.

**`run_chat.py` 를 대체하는 것이 아니라, 그 안의 계산을 HTTP 로 꺼내는 파일이다.**
워크플로우 스텝(`onprem/workflow/sfr006_0*.py`)이 이 세 경로를 부른다.

```
POST /chat/context   세션·템플릿 확정 → 항목 목록·현재 값        (스텝 1)
POST /chat/prefill   업로드 문서 → 빈 항목 자동 채움 (첫 턴만)    (스텝 1, 조건부)
POST /chat/extract   발화 → LLM 추출 → 코드 판정                (스텝 2)
POST /chat/commit    병합 → 세션 저장 → 미리보기 → 답변 문구      (스텝 3)
```

`/chat/prefill` 은 **스텝을 늘리지 않는다** — 스텝 1 이 `/chat/context` 뒤에 이어서
부른다. 캔버스 스텝을 넷으로 만들면 등록을 다시 해야 하고, 문서가 없는 대화(기존 흐름)
에서는 아무 일도 하지 않는 스텝이 하나 늘어난다.

**저장하지 않는다.** 뽑은 값을 그대로 돌려주고 병합·저장은 `/chat/commit` 이 한다 —
`/chat/extract` 와 같은 규약이다. 자동 채움만 저장하면 "문서는 반영됐는데 그 턴 발화는
날아간" 중간 상태가 생기고, 두 곳에서 저장하면 순서에 따라 서로를 덮는다.

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
from .doc_prefill import prefill_from_document
from .field_judge import normalize_blocks, parse_updates
from .hwpx_fields import missing_field_names
import hashlib

from .llm import CONFIG_MISSING, llm_call_async
from .logging_utils import log_info, log_warning
from .prompt_loader import PromptRenderError
from .prompts import build_extract_prompts
from .session_store import (
    SessionStoreError,
    load_session,
    normalize_doc_hashes,
    save_session,
)


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


class PrefillRequest(BaseModel):
    session_id: str = ""
    template_id: str = ""
    document: str = ""


class CommitRequest(BaseModel):
    session_id: str = ""
    template_id: str = ""
    fields_updated: dict = Field(default_factory=dict)
    # 문서 자동 채움분 (2026-08-31). `fields_updated` 와 **따로** 받는다 — 병합 순서가
    # 다르고(문서 먼저, 발화 나중) 답변 문구도 따로 나가야 한다. 한 dict 로 뭉치면
    # 사용자 발화가 문서 값에 밀리는지 아닌지를 커밋 시점에 알 방법이 없다.
    fields_prefilled: dict = Field(default_factory=dict)
    # 이번 턴에 태운(또는 태우려다 건너뛴) 문서의 해시 **하나**다. 세션에는 목록으로
    # 쌓이지만(`source_doc_hashes`) 경계를 건너오는 것은 이번 턴 것뿐이다 — 스텝이
    # 목록을 들고 다니면 그것이 곧 세션 사본이 되고, 두 벌이 갈린다.
    source_doc_hash: str = ""
    prefill_failed: bool = False
    # 자동 채움을 **왜 건너뛰었나**. 답변 문구가 갈린다 (`no_pending_fields` 만 한 줄을
    # 낸다 — 나머지는 사용자가 할 일이 없거나 이미 말한 사건이다).
    prefill_skipped_reason: str = ""
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


def _doc_hash(document: str) -> str:
    """업로드 문서의 표식. **내용 자체는 세션에도 로그에도 남기지 않는다**(3.8절).

    16자로 자른다 — 같은 대화 안에서 문서 두세 개를 구분하는 용도라 충돌 위험이 없고,
    세션 값이 짧을수록 Redis 페이로드가 작다.
    """
    return hashlib.sha256((document or "").encode("utf-8")).hexdigest()[:16]


async def _load_turn(session_id: str, template_id: str) -> tuple:
    """네 경로가 공통으로 하는 것: 세션 읽기 → 템플릿 확정 → 상태 복원.

    이번 턴 지정(`template_id`)이 세션에 저장된 것보다 우선한다 — 사용자가 템플릿을
    바꾼 턴에 옛 템플릿으로 판정하면 항목이 통째로 어긋난다.

    **세션 dict 도 함께 돌려준다** (2026-08-31). `TurnState` 는 값·블록만 담는데
    `source_doc_hashes` 는 그 둘이 아니고, 저장이 덮어쓰기라 커밋이 기존 목록을 다시
    실어야 한다 — 목록이 지워지면 다음 턴에 같은 문서를 또 태운다.
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
    return context, state, session


def install(app) -> None:
    """FastAPI 앱에 대화 3단계를 등록한다."""

    @app.post("/chat/context")
    async def chat_context(request: ContextRequest):
        """스텝 1 — 어느 템플릿인지 확정하고 항목 목록·현재 값을 낸다."""
        context, state, session = await _load_turn(request.session_id, request.template_id)
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
                {"text": b.text, "style_ref": b.style_ref}
                for b in state.blocks
            ],
            "fields_missing": missing,
            "ready_for_download": not missing,
            "template_markdown": context.index.markdown,
            "template_markdown_truncated": context.index.truncated,
            "from_cache": bool(context.index.from_cache),
        }

    @app.post("/chat/prefill")
    async def chat_prefill(request: PrefillRequest):
        """스텝 1(조건부) — 업로드 문서에서 **빈 항목만** 자동으로 채운다.

        저장하지 않는다. 뽑은 값을 돌려주고 병합·저장은 `/chat/commit` 이 한다.

        ## 대화 **중간에도** 돈다 (요구 변경 2026-09-02)

        처음에는 첫 턴 전용이었다(`state.values or state.blocks` 면 스킵). 요구가 바뀌어
        **대화 도중 언제든 파일을 올릴 수 있고, 파일이 여러 번 올 수 있다.** 그래서 그
        게이트를 걷어냈다 — 남는 판정은 둘이다.

        - **이미 태운 문서면 안 돈다** (`source_doc_hashes` 멤버십). 없으면 캔버스가 매 턴
          같은 `genosUploaded` 를 실어 올 때 문서를 다시 태워, **사용자가 지운 값을 우리가
          되살린다** — 그 상태는 오류를 내지 않아 제보로만 드러난다. 표식이 **목록**인
          이유가 여기 있다: 하나만 들면 두 번째 문서를 태운 순간 첫 문서를 잊고, 캔버스가
          둘을 계속 실어 올 때 **번갈아 가며 다시 태운다.**
        - **빈 항목이 없으면 안 돈다** (`no_pending_fields`). 채울 자리가 없는데 LLM 을
          부르는 것이라 비용만 든다. 이 판정은 첫 턴 전용이던 시절에는 사실상 닿지
          않았지만, 이제는 **다 채운 뒤 파일을 올리는 것이 정상 흐름**이라 흔하다.

        **"이미 값이 있으면 안 돈다" 가 아니다.** 요구는 "남아 있는 중괄호를 그 파일로
        채운다" 이고, 기존 값을 안 덮는 것은 게이트가 아니라 `doc_prefill._pending_specs`
        (프롬프트에서 뺀다) + `conflicts`(그래도 오면 버린다) 두 층이 이미 보장한다.

        ## 실패는 오류로 올리지 않는다

        문서 자동 채움은 부가 기능이다. 실패했다고 요청을 세우면 사용자는 **템플릿 채우기
        자체가 안 되는 것으로** 보고, 원래 하려던 대화 채우기까지 막힌다. 대신
        `prefill_failed` 로 사실을 돌려주고 커밋이 답변에 한 줄 싣는다 — 조용히 넘기면
        "문서를 올렸는데 아무 일도 일어나지 않았다" 가 된다.
        """
        document = (request.document or "").strip()
        context, state, session = await _load_turn(request.session_id, request.template_id)

        if not Config.DOC_PREFILL:
            return _prefill_skipped("disabled", context.template_id)
        if not document:
            return _prefill_skipped("no_document", context.template_id)

        digest = _doc_hash(document)
        # 판정 순서가 계약이다. `already_applied` 가 **먼저**라야 같은 문서가 매 턴 실려
        # 와도 안내문이 한 번만 나간다 — 뒤로 밀면 항목을 다 채운 뒤부터 매 턴
        # `no_pending_fields` 가 새 사건처럼 보고된다.
        if digest in (session.get("source_doc_hashes") or ()):
            return _prefill_skipped("already_applied", context.template_id, digest)
        if not missing_field_names(context.specs, state.values):
            # 채울 자리가 없다. 문서를 태워도 값이 전부 `conflicts` 로 버려지므로 LLM
            # 비용만 든다. **해시는 돌려준다** — 커밋이 기록해 다음 턴부터
            # `already_applied` 로 조용히 빠지게 한다(안내문 반복 방지).
            return _prefill_skipped("no_pending_fields", context.template_id, digest)

        outcome = await prefill_from_document(
            context.specs, context.allowed_names, document, state.values
        )

        log_info(
            "문서 자동 채움",
            event="chat_prefill_done",
            resource_id=f"{context.template_id}.hwpx",
            item_count=len(outcome.values),
            status=(
                f"chunks={outcome.chunks_called}/{outcome.chunk_count}"
                f" failed={outcome.chunks_failed}"
                f" rejected={outcome.rejected}"
                f" conflicts={outcome.conflicts}"
            ),
        )

        return {
            "applied": bool(outcome.values),
            "skipped_reason": "",
            "template_id": context.template_id,
            "fields_prefilled": dict(outcome.values),
            # 실패해도 해시를 낸다 — 커밋이 저장해 **같은 문서로 매 턴 재시도하지 않게**
            # 한다. 재시도를 원하면 사용자가 문서를 다시 올리는 것이 맞다(내용이 같으면
            # 해시도 같으므로, 그때는 대화로 채우는 쪽이 빠르다).
            "source_doc_hash": digest,
            "prefill_failed": not outcome.ok,
            "chunk_count": outcome.chunk_count,
            "chunks_called": outcome.chunks_called,
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

        context, state, session = await _load_turn(request.session_id, request.template_id)

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
                {"text": b.text, "style_ref": b.style_ref}
                for b in added_blocks
            ],
            "block_clears": list(intent.block_clears),
        }

    @app.post("/chat/commit")
    async def chat_commit(request: CommitRequest):
        """스텝 3 — 병합·저장·미리보기·답변 문구를 한 요청으로 처리한다.

        셋을 나누면 "저장은 됐는데 미리보기에서 실패한" 중간 상태가 캔버스에 생긴다.
        """
        context, state, session = await _load_turn(request.session_id, request.template_id)

        # 이전 값을 남겨 둔다 — 답변에 `이전 → 새 값` 을 보여주려면 필요하고, 대화로
        # 값을 고치는 경로에서 의도치 않은 덮어쓰기를 사용자가 알아채는 유일한 수단이다.
        previous = dict(state.values)

        # ── 문서 자동 채움분을 **먼저** 병합한다 (2026-08-31) ──────────────────
        #
        # 순서가 계약이다. 뒤에 넣으면 **같은 턴에 사용자가 말한 값을 문서 값이 덮는다** —
        # "이 문서로 채우고 제목은 A 로 해줘" 가 문서의 제목으로 되돌아간다.
        # 그리고 **이미 값이 있는 항목은 건너뛴다**: 서빙 쪽 `doc_prefill` 도 같은 판정을
        # 하지만 여기서 다시 본다. 값이 HTTP 경계를 건너왔으므로 그대로 믿지 않는다
        # (블록을 `normalize_blocks` 로 되읽는 것과 같은 규율).
        prefilled = {
            name: value
            for name, value in (request.fields_prefilled or {}).items()
            if name in context.allowed_names and name not in state.values
        }
        if prefilled:
            merge_values(state, prefilled, [])

        accepted = dict(request.fields_updated or {})
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
                    state.blocks,
                    # 표식을 **매 턴 다시 실어야** 한다 (저장은 덮어쓰기다). 그리고
                    # 이번 턴 해시는 **덮는 것이 아니라 목록에 더한다** — 대화 중간에도
                    # 파일을 올릴 수 있어 한 세션이 문서를 여러 벌 태우기 때문이다
                    # (2026-09-02). 덮으면 앞서 태운 문서를 잊고, 캔버스가 그 문서를
                    # 계속 실어 올 때 번갈아 가며 다시 태운다.
                    source_doc_hashes=_merged_doc_hashes(
                        session.get("source_doc_hashes"), request.source_doc_hash
                    ),
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
            prefilled=prefilled,
            prefill_failed=bool(request.prefill_failed),
            prefill_skipped_reason=str(request.prefill_skipped_reason or ""),
        )

        log_info(
            "대화 턴 커밋",
            event="chat_commit_done",
            resource_id=f"{context.template_id}.hwpx",
            item_count=len(state.values),
            status=(
                f"missing={len(missing)} blocks={len(state.blocks)}"
                f" prefilled={len(prefilled)} ready={int(not missing)}"
            ),
        )

        return {
            "text": display_text,
            "field_values": dict(state.values),
            "fields_filled": [s.name for s in context.specs if s.name not in missing],
            "fields_missing": missing,
            "ready_for_download": not missing,
            "blocks": [
                {"text": b.text, "style_ref": b.style_ref}
                for b in state.blocks
            ],
            "blocks_removed": len(dropped_blocks),
            "document_markdown": document_markdown,
            "document_markdown_truncated": document_truncated,
        }


def _merged_doc_hashes(existing, digest: str) -> list:
    """세션의 표식 목록에 이번 턴 해시를 **더한다** (덮지 않는다).

    정규화·상한은 `session_store.normalize_doc_hashes` 한 곳이 쥔다 — 여기서 또 자르면
    두 곳이 서로 다른 상한을 갖게 된다. 여기가 하는 일은 **순서**뿐이다: 이번 턴 것을
    맨 뒤에 놓아 상한에 걸릴 때 **가장 오래된 문서부터** 잊히게 한다.
    """
    merged = [str(item or "").strip() for item in (existing or ())]
    fresh = str(digest or "").strip()
    if fresh:
        # 이미 있으면 뒤로 옮긴다 — 방금 다시 쓰인 문서가 상한에 밀려 나가면 안 된다.
        merged = [item for item in merged if item != fresh] + [fresh]
    return normalize_doc_hashes(merged)


def _prefill_skipped(reason: str, template_id: str, digest: str = "") -> dict:
    """자동 채움을 하지 않은 응답. **`applied=False` + 사유**를 함께 낸다.

    사유를 안 내면 호출부가 "문서가 없었다" 와 "이미 반영했다" 와 "기능이 꺼져 있다" 를
    구분할 수 없고, 그 넷은 사용자에게 할 말이 서로 다르다.

    사유는 넷이다: `disabled` · `no_document` · `already_applied` ·
    **`no_pending_fields`**(2026-09-02 — 채울 자리가 없다). 마지막 것만 답변에 한 줄이
    나간다 — 사용자는 방금 파일을 올렸으므로, 조용히 넘기면 "올렸는데 아무 일도 일어나지
    않았다" 가 된다. 앞의 셋은 사용자가 할 일이 없거나(꺼짐·문서 없음) 이미 앞선 턴에
    말한 사건이다(이미 반영).
    """
    return {
        "applied": False,
        "skipped_reason": reason,
        "template_id": template_id,
        "fields_prefilled": {},
        # 이미 반영한 문서면 그 해시를 그대로 돌려준다 — 커밋이 세션에 다시 실어야
        # 표식이 유지된다(저장은 덮어쓰기다).
        "source_doc_hash": digest,
        "prefill_failed": False,
        "chunk_count": 0,
        "chunks_called": 0,
    }


def _empty_extraction() -> dict:
    return {
        "fields_updated": {},
        "fields_cleared": [],
        "fields_rejected": [],
        "blocks_added": [],
        "block_clears": [],
    }
