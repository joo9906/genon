"""SFR-006 템플릿 채우기 — 코드 서빙 (area 03).

사용자가 채팅 UI 에서 **다운로드 버튼**을 누르면 호출되는 파일 생성 API. 대화
(`run_chat.py`)가 세션에 누적해 둔 값·본문을 읽어 hwpx 초안을 만들어 바이너리로 반환한다.

## 이 파일의 역할은 **배선뿐**이다

문서 조립은 `document.py`, 세션·화면 조립은 `session_view.py`, 템플릿 볼륨은
`template_store.py` 가 한다. 여기서는 요청을 받아 그 셋을 부르고 결과를 HTTP 로 바꾼다.
오류는 `ApiError` 예외 하나로 올라와 `api_errors.install()` 이 건 핸들러가 응답으로 바꾼다.

**요청→값**과 **값→파일**도 갈라 뒀다 (2026-08-11). 그전에는 이 파일이 셋을 다 들고
736줄이었고, "배선뿐" 이라는 위 문장이 사실이 아니었다:

| 파일 | 맡는 것 |
|---|---|
| `api_requests.py` | 요청 스키마 + 입력 검증·정규화 (요청 → 믿을 수 있는 값) |
| `api_download.py` | 블록 검증 → `document.build` → 다운로드 응답 (값 → 파일) |
| `main.py`(이 파일) | 라우트 정의와 그 둘의 호출 순서 |

호출 이름은 그대로 두고 별칭으로 들여온다(`resolve_format as _resolve_format`). 라우트
본문을 한 줄도 바꾸지 않아야 **특성화 점검**(`check_api_contract`·`check_chat_turn`)이
"동작이 안 바뀌었다" 를 실제로 보증한다 — 분해와 동작 변경을 한 커밋에 섞으면 그 점검이
무엇을 통과시킨 것인지 알 수 없어진다.

## 엔드포인트

| 경로 | 하는 일 |
|---|---|
| `GET /health` | 헬스체크 (가이드 필수) |
| `GET /templates` | 등록된 템플릿 목록 (+ 색인 상태) |
| `POST /templates` | **관리자** 템플릿 등록 (업로드 + 즉시 색인) |
| `DELETE /templates/{id}` | **관리자** 템플릿 삭제 (+ 색인 폐기) |
| `GET /fields` | 항목 스키마 + 본문 블록 서식 목록 |
| `GET /status` | 세션 채움 현황 (다운로드 버튼 활성화 판단용) |
| `GET /preview` | 채운 결과를 마크다운으로 (표시 전용) |
| `PATCH /values` | 화면에서 고친 항목 값을 세션에 반영 |
| `DELETE /values` | 화면에서 항목 값 비우기 |
| `PUT /blocks` | 본문 추가 내용 목록을 통째로 교체 |
| `POST /generate` | 등록 템플릿으로 초안 생성 + 다운로드 (**hwpx 만**) |
| `POST /generate/upload` | **업로드한 hwpx** 로 초안 생성 (multipart) |

## 가이드 반영 (v1.02)

- 0.0.0.0:$PORT bind, `/health` 제공
- 오류 응답은 `{error_code, msg}` (3.9.5절), 예외 원문 미노출 (3.8절)
- blocking I/O(zip·XML·파일)는 전부 `asyncio.to_thread` (6.9절)
- **부분 초안 허용**: 값이 없는 항목은 그대로(라벨은 `제목:`, 누름틀은 안내문) 남겨
  사용자가 한/글에서 이어서 작성하게 한다. 무엇이 비었는지는 응답 헤더로 알린다.
"""

import asyncio
import os
import time

from fastapi import FastAPI, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse, Response

from . import session_view, template_store
from .api_download import (
    build as _build,
    download_response as _download_response,
    resolve_blocks as _resolve_blocks,
)
from .api_errors import ApiError, install as install_error_handler
from .api_requests import (
    BlockPutRequest,
    GenerateRequest,
    ValueDeleteRequest,
    ValuePatchRequest,
    check_value_count as _check_value_count,
    normalize_values as _normalize_values,
    parse_json_form as _parse_json_form,
    read_upload as _read_upload,
    require_admin as _require_admin,
    resolve_format as _resolve_format,
)
from .chat_api import install as install_chat_api
from .config import Config
from .error_codes import (
    ERR_API_INPUT,
    ERR_API_SESSION_NOT_FOUND,
    ERR_API_TEMPLATE_EXISTS,
)
from .field_judge import normalize_blocks
from .hwpx_fields import TemplateError
from .logging_utils import configure_logging, log_info, log_warning
from .session_store import end_session, load_session
from .template_index import build_index_async, invalidate, peek_index, store_index

configure_logging(os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="hwpx-template-fill-service")
install_error_handler(app)

# 대화 3단계(`POST /chat/context|extract|commit`). 워크플로우 스텝
# `onprem/workflow/sfr006_0*.py` 가 이 세 경로를 부른다 — 배선이 빠지면 스텝 셋이
# 전부 404 를 받는데, 그 실패는 캔버스에서만 드러나 원인을 찾기 어렵다.
# `install_error_handler` 뒤에 와야 `ApiError` 가 HTTP 상태로 변환된다.
install_chat_api(app)

if not Config.ADMIN_TOKEN:
    # 인증 부재를 조용히 넘기지 않는다 — 배포자가 보호되고 있다고 착각하면
    # 누구나 템플릿을 덮어쓸 수 있는 상태로 운영된다.
    log_warning(
        "TEMPLATE_FILL_ADMIN_TOKEN 미설정 — 템플릿 등록/삭제가 인증 없이 열려 있다",
        event="admin_token_missing",
        status="open",
    )



# ─────────────────────────────────────────────────────────────
# 헬스체크 · 템플릿 관리
# ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/")
@app.get("")
async def root() -> dict:
    """게이트웨이가 서빙 베이스를 경로 없이 때리는 배포가 있다 (운영 app.py 대조 결과).

    거기서 404 가 나면 배선이 잘못된 것처럼 보이므로 최소 정보를 돌려준다.
    018 두 단위와 같은 규약이다.

    **`""` 와 `"/"` 를 둘 다 등록해야 한다** (2026-08-11 수정). `@app.get("")` 만 두면
    **아무 경로에도 매칭되지 않는다** — ASGI 요청의 path 는 최소 `/` 라서 빈 문자열
    라우트는 영영 닿지 않고, `/` 라우트는 등록된 적이 없으니 둘 다 404 다. 2026-08-07 에
    이 라우트를 넣고 "루트 경로를 맞췄다" 고 적었지만 실제로는 동작하지 않았다.
    """
    return {"service": "template-fill-service", "status": "ok"}


@app.get("/templates")
async def templates() -> dict:
    """등록된 템플릿 목록.

    색인 정보는 **캐시에 있는 것만** 붙인다. 목록을 만들 때마다 모든 템플릿을 열어
    파싱하면 목록 조회 한 번이 전체 파싱이 된다. 색인이 없으면 `indexed: false` 로
    정직하게 표시하고, 그 템플릿의 `/fields` 첫 호출이 색인을 만든다.
    """
    names = await template_store.list_ids()
    # 템플릿마다 순차로 await 하면 목록 지연이 (템플릿 수 × Redis 왕복)이 된다
    indexes = await asyncio.gather(*(peek_index(name) for name in names))
    return {
        "templates": names,
        "items": [
            {
                "template_id": name,
                "indexed": index is not None,
                "field_count": len(index.fields) if index else None,
                "table_count": index.table_count if index else None,
                "indexed_at": index.indexed_at if index else None,
            }
            for name, index in zip(names, indexes)
        ],
        "formats": session_view.available_formats(),
    }


@app.post("/templates")
async def register_template(
    template: UploadFile = File(..., description="등록할 hwpx 템플릿 파일"),
    template_id: str | None = Form(None, description="생략하면 업로드 파일명을 쓴다"),
    overwrite: bool = Form(False, description="같은 이름이 있을 때 덮어쓸지"),
    x_admin_token: str | None = Header(None),
) -> Response:
    """관리자 템플릿 등록 — 파일을 볼륨에 두고 **그 자리에서 색인까지** 만든다.

    등록 시점에 파싱하는 이유가 두 가지다:
    - 깨진 템플릿을 등록 단계에서 막는다 (대화 중에 터지면 사용자가 손쓸 수 없다).
    - 첫 대화 턴이 파싱 비용을 물지 않는다.

    **파싱이 먼저, 파일 쓰기가 나중이다.** 순서를 바꾸면 해석 불가 파일이 볼륨에 남는다.
    """
    _require_admin(x_admin_token)
    template_bytes = await _read_upload(template)
    resolved_id = template_store.safe_id(template_id or os.path.basename(template.filename or ""))

    exists = await template_store.exists(resolved_id)
    if exists and not overwrite:
        raise ApiError(ERR_API_TEMPLATE_EXISTS)

    try:
        index = await build_index_async(resolved_id, template_bytes)
    except TemplateError as exc:
        raise ApiError(ERR_API_INPUT, str(exc)) from exc

    await template_store.write(resolved_id, template_bytes)
    await store_index(index)

    log_info(
        "템플릿 등록 완료",
        event="template_registered",
        resource_id=resolved_id,
        item_count=len(index.fields),
        status=(
            f"overwritten={int(exists)} tables={index.table_count} "
            f"bare_braces={len(index.bare_braces)}"
        ),
    )
    if index.bare_braces:
        # 따옴표를 빠뜨린 오타일 수도, 값 안내를 일부러 적은 것일 수도 있다. 코드가
        # 판단하지 않고 등록자에게 보여 준다 — 조용히 넘기면 채워질 줄 알았던 자리가
        # 빈 채로 배포된다 (침묵 처리 금지 규약).
        log_warning(
            "따옴표 없는 중괄호가 있어 채울 자리로 잡히지 않았다",
            event="template_bare_braces",
            resource_id=resolved_id,
            item_count=len(index.bare_braces),
        )
    return JSONResponse(
        status_code=200 if exists else 201,
        content={
            "template_id": resolved_id,
            "overwritten": exists,
            "content_hash": index.content_hash,
            "fields": [session_view.field_payload(s) for s in index.fields],
            "block_styles": list(index.block_styles) if Config.BODY_BLOCKS else [],
            "markdown": index.markdown,
            "markdown_truncated": index.truncated,
            # 채울 자리로 보지 않은 `{…}` — 관리자가 따옴표 누락인지 판단할 근거다.
            "bare_braces": list(index.bare_braces),
        },
    )


@app.delete("/templates/{template_id}")
async def delete_template(template_id: str, x_admin_token: str | None = Header(None)) -> Response:
    """관리자 템플릿 삭제 — 파일과 색인을 함께 없앤다."""
    _require_admin(x_admin_token)
    resolved_id = template_store.safe_id(template_id)
    await template_store.remove(resolved_id)
    # 파일이 사라진 뒤에 색인이 남아 있으면 목록이 유령 템플릿을 보여준다
    await invalidate(resolved_id)
    log_info("템플릿 삭제 완료", event="template_deleted", resource_id=resolved_id)
    return JSONResponse(content={"template_id": resolved_id, "deleted": True})


@app.get("/fields")
async def fields(template_id: str) -> dict:
    _, index = await session_view.load_index(template_id)
    return {
        "template_id": template_id,
        "fields": [session_view.field_payload(s) for s in index.fields],
        # 본문 블록의 서식으로 지정할 수 있는 항목명 — 화면의 선택지가 된다
        "block_styles": list(index.block_styles) if Config.BODY_BLOCKS else [],
        "from_cache": index.from_cache,
    }


# ─────────────────────────────────────────────────────────────
# 세션 상태 조회
# ─────────────────────────────────────────────────────────────
@app.get("/status")
async def status(session_id: str, template_id: str | None = None) -> dict:
    """세션 채움 현황 — UI 가 다운로드 버튼 활성화를 판단할 때 사용.

    마크다운을 만들지 않는 가벼운 경로다(그래서 `/preview` 와 따로 있다). 부족 항목
    판정은 `session_view` 가 쥔 하나를 공유한다 — 각자 적어 두면 다운로드 버튼과 대화가
    서로 다른 `ready` 를 보고한다.
    """
    context = await session_view.load_context(session_id, template_id)
    missing = context.missing
    return {
        "template_id": context.template_id,
        "session_id": session_id,
        "values": context.values,
        "fields_missing": missing,
        # 본문 블록은 `ready_for_download` 에 관여하지 않는다 — 항목이 아니라 **덤**이라
        # 0개여도 문서는 완성이다. 개수만 알려 화면이 표시할 수 있게 한다.
        "block_count": len(context.blocks),
        "ready_for_download": not missing,
        "formats": session_view.available_formats(),
    }


@app.get("/preview")
async def preview(session_id: str | None = None, template_id: str | None = None) -> dict:
    """지금 값으로 **채운 결과**를 마크다운으로 돌려준다 (표시 전용, 파일 생성 아님).

    브라우저는 hwpx 를 렌더링하지 못한다. 그래서 다운로드 전에 확인할 수단이 필요하고,
    미리보기는 다운로드와 **같은 조립 파이프라인**(`document.build`)을 탄다 — 서식만
    건너뛴다(마크다운에 반영할 자리가 없다). 세션은 건드리지 않는다.
    """
    context = await session_view.load_context(session_id, template_id, require_session=False)
    return await session_view.compose_view_async(context)


# ─────────────────────────────────────────────────────────────
# 화면에서 직접 편집 (대화를 거치지 않는 경로)
# ─────────────────────────────────────────────────────────────
@app.patch("/values")
async def patch_values(body: ValuePatchRequest) -> dict:
    """화면에서 고친 항목 값을 세션에 반영한다.

    판정 책임은 대화 경로와 같다 — **코드가 화이트리스트로 검증한다.** 템플릿에 없는
    항목명은 기각하고 건수를 응답·로그에 노출한다(침묵 처리 금지). 값이 빈 문자열이면
    "지움"으로 처리하고 `cleared_fields` 로 알린다 — 화면의 빈 입력칸은 지우겠다는 뜻이고,
    그걸 조용히 무시하면 사용자는 지웠다고 믿은 값을 그대로 다운로드한다.

    """
    _check_value_count(body.values)
    context = await session_view.load_context(body.session_id, body.template_id)
    allowed = context.field_names

    accepted: dict = {}
    cleared: list = []
    rejected: list = []
    for raw_name, raw_value in body.values.items():
        name = str(raw_name).strip()
        if name not in allowed:
            rejected.append(name)
            continue
        text = str(raw_value or "").strip()[: Config.MAX_VALUE_CHARS]
        if not text:
            context.values.pop(name, None)
            cleared.append(name)
            continue
        accepted[name] = text

    context.values.update(accepted)
    await session_view.save_state(context)

    if rejected:
        # 템플릿에 없는 항목명을 화면이 보냈다는 뜻 — 스키마 불일치 신호다
        log_warning(
            "템플릿에 없는 항목명을 기각",
            event="values_patch_rejected",
            resource_id=context.template_id,
            item_count=len(rejected),
        )
    log_info(
        "항목 값 직접 수정",
        event="values_patched",
        resource_id=context.template_id,
        item_count=len(accepted),
        status=f"cleared={len(cleared)} rejected={len(rejected)}",
    )

    payload = await session_view.compose_view_async(context, body.preview)
    return {
        **payload,
        "updated_fields": sorted(accepted),
        "cleared_fields": sorted(cleared),
        "rejected_fields": sorted(rejected),
    }


@app.delete("/values")
async def delete_values(body: ValueDeleteRequest) -> dict:
    """화면에서 항목 값을 비운다 (여러 개를 한 번에).

    지우는 대상은 **세션에 모인 값**이다. 템플릿 자체에 이미 적혀 있던 값(`filled=True`)은
    문서에 남으므로, 지운 뒤에도 그 항목은 채워진 상태로 보일 수 있다 — 화면이 그 차이를
    표시할 수 있도록 `still_filled_in_template` 로 함께 알린다.
    """
    context = await session_view.load_context(body.session_id, body.template_id)
    specs = {spec.name: spec for spec in context.index.fields}

    removed: list = []
    unknown: list = []
    still_filled: list = []
    for raw_name in body.fields:
        name = str(raw_name).strip()
        if name not in specs:
            unknown.append(name)
            continue
        if context.values.pop(name, None) is not None:
            removed.append(name)
        if specs[name].filled:
            still_filled.append(name)

    await session_view.save_state(context)
    log_info(
        "항목 값 삭제",
        event="values_deleted",
        resource_id=context.template_id,
        item_count=len(removed),
        status=f"unknown={len(unknown)} template_filled={len(still_filled)}",
    )

    payload = await session_view.compose_view_async(context, body.preview)
    return {
        **payload,
        "deleted_fields": sorted(removed),
        "rejected_fields": sorted(unknown),
        "still_filled_in_template": sorted(still_filled),
    }


@app.put("/blocks")
async def put_blocks(body: BlockPutRequest) -> dict:
    """본문 블록 목록을 세션에 통째로 반영한다 (대화를 거치지 않는 직접 편집).

    항목 값(`PATCH /values`)과 달리 **배열 통째 교체**인 이유: 블록은 순서가 의미를 갖는
    목록이라 부분 갱신을 하려면 화면과 서버가 같은 인덱스를 공유해야 하고, 한 번만
    어긋나도 다른 문단이 지워진다. 화면이 가진 목록을 그대로 보내면 그 문제가 없다.
    빈 배열이면 전부 삭제.

    서식 이름(`style_ref`)은 템플릿 화이트리스트로 검증하고, 목록에 없으면 기본 서식으로
    떨어뜨린 뒤 `rejected_blocks` 로 알린다 — 이름이 틀렸다고 본문을 버리지 않는다.

    여기서 쓴 본문은 **다듬지 않는다**(톤 미적용). 사용자가 타이핑한 것이 곧 최종이다
    (`PATCH /values` 가 raw=value 로 두는 것과 같은 규칙).
    """
    if not Config.BODY_BLOCKS:
        raise ApiError(ERR_API_INPUT, "본문 추가 기능이 꺼져 있습니다.")

    context = await session_view.load_context(body.session_id, body.template_id)
    blocks, rejected = normalize_blocks(body.blocks, context.index.block_styles)
    context.blocks = blocks
    await session_view.save_state(context)

    if rejected:
        log_warning(
            "본문 블록 일부를 기각했다",
            event="blocks_put_rejected",
            resource_id=context.template_id,
            item_count=len(rejected),
        )
    log_info(
        "본문 블록 직접 수정",
        event="blocks_put",
        resource_id=context.template_id,
        item_count=len(blocks),
        status=f"rejected={len(rejected)}",
    )

    payload = await session_view.compose_view_async(context, body.preview)
    return {**payload, "rejected_blocks": rejected}


# ─────────────────────────────────────────────────────────────
# 문서 생성 (다운로드 버튼)
# ─────────────────────────────────────────────────────────────
@app.post("/generate")
async def generate(body: GenerateRequest) -> Response:
    """등록된 템플릿(TEMPLATE_DIR)으로 초안을 생성해 다운로드 응답으로 반환한다."""
    started = time.monotonic()
    # 값이 오면 hwpx 인지 확인만 한다 — 다른 값은 400 (조용히 hwpx 를 내려주지 않는다)
    _resolve_format(body.format)

    values: dict = {}
    session_template = ""
    session_blocks: list = []
    if body.session_id:
        try:
            session = await load_session(body.session_id)
        except ValueError as exc:
            raise ApiError(ERR_API_INPUT, "session_id 가 올바르지 않습니다.") from exc
        values.update(session.get("values") or {})
        session_template = str(session.get("template_id") or "")
        session_blocks = session.get("blocks") or []

    if body.values:
        _check_value_count(body.values)
        values.update(_normalize_values(body.values))

    if body.session_id and not values and not body.values:
        raise ApiError(ERR_API_SESSION_NOT_FOUND)

    template_id = (body.template_id or session_template).strip()
    template_bytes = await template_store.read(template_id)
    raw_blocks = body.blocks if body.blocks is not None else session_blocks
    blocks = await _resolve_blocks(template_id, template_bytes, raw_blocks)

    built = await _build(template_bytes, values, blocks, template_id)
    response = _download_response(built, body.filename or f"{template_id}_초안")

    # 부분 초안 여부는 운영에서 봐야 하는 수치다 — 항목명·값은 남기지 않는다
    log_info(
        "초안 생성 완료",
        event="generate_succeeded",
        resource_id=template_id,
        item_count=len(built.written_fields),
        status=(
            f"missing={len(built.missing_fields)}"
            f" styled={len(built.styled_fields)} blocks={built.appended_blocks}"
        ),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    # 생성 성공 = 세션 종료. 조립이 실패했다면 `_build` 가 예외를 올려 여기 오지 않는다.
    if body.session_id:
        await end_session(body.session_id)
    return response


@app.post("/generate/upload")
async def generate_upload(
    template: UploadFile = File(..., description="채울 hwpx 템플릿 파일"),
    session_id: str | None = Form(None),
    values: str | None = Form(None, description="추가 값 JSON 문자열"),
    blocks: str | None = Form(None, description="본문 추가 내용 JSON 배열 문자열"),
    filename: str | None = Form(None),
    format: str | None = Form(None, description="hwpx 만. 다른 값은 400"),
) -> Response:
    """업로드한 hwpx 를 그대로 채워 내려준다 (템플릿 사전 등록 없이).

    처리 규칙은 `/generate` 와 **완전히 같다** — 값의 출처와 서식 목록을 얻는 경로만 다르다
    (등록 템플릿은 색인 캐시, 업로드 파일은 그 자리에서 파싱).
    """
    started = time.monotonic()
    _resolve_format(format)
    template_bytes = await _read_upload(template)

    collected: dict = {}
    session_blocks: list = []
    if session_id:
        try:
            session = await load_session(session_id)
        except ValueError as exc:
            raise ApiError(ERR_API_INPUT, "session_id 가 올바르지 않습니다.") from exc
        collected.update(session.get("values") or {})
        session_blocks = session.get("blocks") or []

    if values:
        parsed = _parse_json_form(values, "values", dict)
        _check_value_count(parsed)
        collected.update(_normalize_values(parsed))

    raw_blocks = _parse_json_form(blocks, "blocks", list) if blocks else session_blocks
    label = os.path.splitext(os.path.basename((template.filename or "").strip()))[0]
    # 업로드 파일은 색인이 없으므로 서식 목록을 그 자리에서 뽑는다 (template_id 는 빈 값)
    body_blocks = await _resolve_blocks("", template_bytes, raw_blocks)

    built = await _build(template_bytes, collected, body_blocks, label)
    response = _download_response(built, filename or f"{label}_초안")

    log_info(
        "업로드 템플릿으로 초안 생성 완료",
        event="generate_upload_succeeded",
        item_count=len(built.written_fields),
        status=(
            f"missing={len(built.missing_fields)}"
            f" styled={len(built.styled_fields)} blocks={built.appended_blocks}"
        ),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    if session_id:
        await end_session(session_id)
    return response

