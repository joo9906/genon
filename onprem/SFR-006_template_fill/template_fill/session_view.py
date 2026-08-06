"""세션 상태 + 템플릿 색인 → **화면이 쓰는 형태**로 조립하는 계층.

`/status`·`/preview`·`PATCH /values`·`DELETE /values`·`PUT /blocks` 가 전부 같은 준비
과정을 거친다: 세션을 읽고 → 템플릿을 확정하고 → 색인을 얻고 → 값·블록을 지금 템플릿에
맞게 걸러낸다. 엔드포인트마다 그 순서를 다시 적으면 규칙이 갈린다. 실제로 갈리면
**같은 세션을 보고도 화면과 대화가 서로 다른 `ready` 를 보고한다.**

여기 모인 규칙:

- 템플릿 확정: **이번 요청 지정 > 세션에 저장된 것.**
- 값·블록은 **지금 템플릿에 있는 것만** 남긴다. 템플릿이 교체되면 옛 항목은 버린다.
- 저장은 **덮어쓰기**다. 값만 저장하면 본문 블록이 통째로 사라지므로, 저장 함수가
  값·원본·블록을 **한꺼번에** 받도록 강제한다 (`save_state` 의 인자가 그래서 셋이다).
- 부족 항목 판정은 `hwpx_fields.missing_field_names` **하나만** 쓴다.

이 모듈은 HTTP 를 모른다. 실패는 `ApiError` 로 올리고 응답 변환은 `main.py` 가 한다.
"""

import asyncio

from .config import Config
from .error_codes import ApiError, ERR_API_INPUT, ERR_API_INTERNAL
from .field_judge import normalize_blocks
from .hwpx_fields import TemplateError, missing_field_names
from .hwpx_markdown import render_filled
from .logging_utils import log_error, log_warning
from .pdf_convert import available as pdf_available
from .session_store import SessionStoreError, load_session, save_session
from .template_index import get_index
from .template_store import read as read_template


class EditingContext:
    """한 세션의 편집 상태 — 세션·템플릿·색인·걸러낸 값/블록을 함께 들고 다닌다."""

    __slots__ = ("session_id", "template_id", "template_bytes", "index", "values", "raw_values", "blocks")

    def __init__(self, session_id, template_id, template_bytes, index, values, raw_values, blocks):
        self.session_id = session_id
        self.template_id = template_id
        self.template_bytes = template_bytes
        self.index = index
        self.values = values
        self.raw_values = raw_values
        self.blocks = blocks

    @property
    def field_names(self) -> set:
        return {spec.name for spec in self.index.fields}

    @property
    def missing(self) -> list:
        return missing_field_names(self.index.fields, self.values)


async def load_index(template_id: str):
    """템플릿 파일 + 색인 (색인은 Redis 캐시 경유, 없으면 직접 파싱).

    Raises:
        ApiError: 템플릿이 없거나(404) 해석 불가(400).
    """
    template_bytes = await read_template(template_id)
    try:
        index = await get_index(template_id, template_bytes)
    except TemplateError as exc:
        # 계약: TemplateError 메시지는 hwpx_fields.py 의 고정 안내문만 담는다
        raise ApiError(ERR_API_INPUT, str(exc)) from exc
    return template_bytes, index


async def load_context(
    session_id: str | None, template_id: str | None, *, require_session: bool = True
) -> EditingContext:
    """세션 + 템플릿 + 색인을 함께 얻고, 값·블록을 지금 템플릿에 맞게 걸러낸다.

    Args:
        require_session: `/preview` 는 세션 없이 템플릿 원본만 볼 수 있어야 한다.
            그때만 False 로 부르고, 세션 id 가 비어 있으면 빈 상태로 진행한다.

    Raises:
        ApiError: session_id 형식 오류(400), 템플릿 없음(404), 해석 불가(400).
    """
    session: dict = {}
    if require_session or session_id:
        try:
            session = await load_session(session_id)
        except ValueError as exc:
            raise ApiError(ERR_API_INPUT, "session_id 가 올바르지 않습니다.") from exc

    resolved = (template_id or session.get("template_id") or "").strip()
    template_bytes, index = await load_index(resolved)

    allowed = {spec.name for spec in index.fields}
    return EditingContext(
        session_id=session_id or "",
        template_id=resolved,
        template_bytes=template_bytes,
        index=index,
        values={k: v for k, v in (session.get("values") or {}).items() if k in allowed},
        raw_values={k: v for k, v in (session.get("raw_values") or {}).items() if k in allowed},
        blocks=restore_blocks(session.get("blocks"), index),
    )


def restore_blocks(raw_blocks, index) -> list:
    """세션에 저장된 본문 블록을 `BodyBlock` 목록으로 되읽는다.

    되읽을 때도 대화 경로와 **같은 검증**(`normalize_blocks`)을 거친다 — 템플릿이 바뀌어
    사라진 서식 이름은 여기서 기본 서식으로 떨어진다(값을 `allowed` 로 거르는 것과 같은 규율).
    """
    if not Config.BODY_BLOCKS:
        return []
    blocks, _ = normalize_blocks(raw_blocks, index.block_styles)
    return blocks


async def save_state(context: EditingContext) -> None:
    """편집 결과를 세션에 저장한다.

    **값·원본·블록을 한꺼번에 받는 이유**: 세션은 키 하나에 통째로 저장되므로 일부만
    저장하면 나머지가 지워진다. 컨텍스트를 통으로 넘기게 해서 "블록을 빠뜨리는" 실수를
    구조적으로 막는다.

    Raises:
        ApiError: 저장 실패 (500). 화면에 반영된 값이 조용히 사라지면 안 된다.
    """
    try:
        await save_session(
            context.session_id,
            context.template_id,
            context.values,
            context.raw_values,
            context.blocks,
        )
    except SessionStoreError as exc:
        log_warning(
            "세션 저장 실패 — 화면 상태가 유지되지 않는다",
            event="values_save_failed",
            resource_id=context.template_id,
            error_code=ERR_API_INTERNAL.code,
            error_type=type(exc).__name__,
        )
        # 계약: SessionStoreError 메시지는 session_store.py 의 고정 안내문만 담는다
        raise ApiError(ERR_API_INTERNAL, str(exc)) from exc


def available_formats() -> list:
    """지금 환경에서 실제로 내려줄 수 있는 형식 (UI 버튼 노출 판단용)."""
    return ["hwpx", "pdf"] if pdf_available() else ["hwpx"]


def field_payload(spec, value: str | None = None) -> dict:
    payload = {
        "name": spec.name,
        "guide": spec.guide,
        "occurrences": spec.occurrences,
        "filled": spec.filled,
        "current_value": spec.current_value,
        # 라벨 항목인지 누름틀인지 — 템플릿 제작 방식 확인용
        "source": spec.source,
    }
    if value is not None:
        payload["value"] = value
    return payload


def block_payload(blocks) -> list:
    # raw_text 는 톤(글다듬이) 적용 전 원문 — 화면이 "다듬기 전/후" 를 보여줄 근거다.
    return [
        {"text": b.text, "style_ref": b.style_ref, "raw_text": b.raw_text} for b in (blocks or ())
    ]


def compose_view(context: EditingContext, with_markdown: bool = True) -> dict:
    """항목 상태 + (선택) 채운 결과 마크다운을 하나의 화면용 payload 로 만든다.

    `GET /preview` 와 편집 응답(`PATCH`/`DELETE /values`, `PUT /blocks`)이 **같은 payload** 를
    쓴다 — 편집 직후 화면과 미리보기가 다른 계산을 하면 사용자가 보는 상태가 갈린다.

    **동기 함수다** (zip+XML 을 다루는 blocking 작업). async 핸들러는 반드시
    `asyncio.to_thread` 로 감싸 부른다 — 가이드 6.9절.

    Raises:
        ApiError: 미리보기 생성 실패 (400/500).
    """
    markdown = ""
    truncated = False
    if with_markdown:
        try:
            rendered = render_filled(
                context.template_bytes,
                context.values,
                max_chars=Config.MAX_PREVIEW_CHARS,
                blocks=context.blocks,
            )
        except TemplateError as exc:
            raise ApiError(ERR_API_INPUT, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
            log_error(
                "미리보기 생성 중 내부 오류",
                event="preview_internal_error",
                resource_id=context.template_id,
                error_code=ERR_API_INTERNAL.code,
                error_type=type(exc).__name__,
            )
            raise ApiError(ERR_API_INTERNAL, "미리보기를 만들지 못했습니다.") from exc
        markdown = rendered.markdown
        truncated = rendered.truncated

    missing = context.missing
    return {
        "template_id": context.template_id,
        "session_id": context.session_id,
        "markdown": markdown,
        # 잘린 미리보기를 문서 전체로 오인하면 빠진 항목을 못 보고 다운로드한다
        "truncated": truncated,
        "fields": [
            field_payload(spec, context.values.get(spec.name, "")) for spec in context.index.fields
        ],
        "values": context.values,
        "fields_missing": missing,
        "ready_for_download": not missing,
        "formats": available_formats(),
        # 본문 블록 — 항목과 달리 순서가 의미를 갖는 목록이라 배열 그대로 내려준다
        "blocks": block_payload(context.blocks),
        "block_styles": list(context.index.block_styles) if Config.BODY_BLOCKS else [],
    }


async def compose_view_async(context: EditingContext, with_markdown: bool = True) -> dict:
    """`compose_view` 를 스레드에서 돌린다 (이벤트 루프 차단 금지 — 가이드 6.9)."""
    return await asyncio.to_thread(compose_view, context, with_markdown)
