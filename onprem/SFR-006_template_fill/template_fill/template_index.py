"""템플릿 파싱 결과 색인 — 한 번 파싱해 Redis 에 두고 재사용한다.

왜 필요한가: 지금까지 `/fields`, `/status`, 대화의 **매 턴**, `/generate` 가 각각
`scan_fields()` 를 불러 zip 을 풀고 XML 을 처음부터 다시 파싱했다. 템플릿은 관리자가
올려두면 바뀌지 않는 입력이므로, 같은 파싱을 대화 턴 수만큼 반복할 이유가 없다.

캐시 무효화는 **키에 조건을 담지 않고 값에 담아 대조**한다:
- `content_hash` — 파일이 교체되면 자동으로 miss (관리자가 볼륨에 덮어써도 감지된다)
- `schema_version` — 파서 규칙을 바꾸면 옛 색인을 쓰지 않는다. **슬롯 인식 규칙이나
  FieldSpec 구조를 고치면 이 숫자를 올려야 한다.** 안 올리면 새 코드가 옛 판정을 읽는다.
- `slots` — `TEMPLATE_FILL_SLOTS` 를 끄고 켜면 항목 목록 자체가 달라진다

키를 template_id 하나로 두는 이유: 해시를 키에 넣으면 삭제할 때 옛 해시를 알아야 해서
`DELETE /templates/{id}` 가 지울 수 없는 잔여 키를 남긴다.

캐시는 **성능 장치일 뿐이다.** Redis 가 없거나 죽어도 기능은 그대로 동작해야 하므로,
읽기·쓰기 실패는 로그만 남기고 직접 파싱으로 degrade 한다 (세션 저장과 다르다 —
세션 저장 실패는 값 유실이라 오류로 올린다).
"""

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass

from redis.exceptions import RedisError

from .config import Config
from .hwpx_fields import FieldSpec, scan_fields
from .hwpx_markdown import render_markdown
from .logging_utils import log_info, log_warning
from .redis_client import RedisUnavailableError, resolve_client

# 파서 규칙/FieldSpec 구조를 바꿀 때 올린다 (옛 색인 자동 폐기)
SCHEMA_VERSION = 3

_INFRA_ERRORS = (RedisError, RedisUnavailableError)
_HASH_CHARS = 16


@dataclass(frozen=True)
class TemplateIndex:
    """템플릿 1개의 파싱 결과."""

    template_id: str
    content_hash: str
    fields: list          # FieldSpec 목록 (문서 등장 순서)
    markdown: str         # 템플릿 원본 모양 (표시 전용, 값은 채워지지 않은 상태)
    table_count: int      # GET /templates 가 목록에 표시한다
    truncated: bool       # 마크다운이 상한에 걸려 잘렸는지
    indexed_at: float
    from_cache: bool = False


def content_hash(template_bytes: bytes) -> str:
    return hashlib.sha256(template_bytes).hexdigest()[:_HASH_CHARS]


# 키에 그대로 쓸 수 있는 문자. 한글은 `isalnum()` 이 참이라 따로 범위를 적지 않는다 —
# 문자 클래스에 `가-힣` 을 문자열로 늘어놓으면 그 두 글자만 통과해 서로 다른 한글
# 이름이 같은 키(`___`)로 뭉개진다. 우리 템플릿 이름은 전부 한글이므로 치명적이다.
_KEY_SAFE_EXTRA = "._- ()[]"
_KEY_UNSAFE_RUN_RE = re.compile(r"_{2,}")


def _index_key(template_id: str) -> str:
    # 템플릿 id 는 main.py/run_chat.py 가 이미 경로 조작을 걸러낸 파일명이지만,
    # 키 인젝션은 여기서 한 번 더 막는다 (세션 키와 같은 규약).
    cleaned = "".join(
        ch if (ch.isalnum() or ch in _KEY_SAFE_EXTRA) else "_"
        for ch in (template_id or "").strip()
    )
    safe = _KEY_UNSAFE_RUN_RE.sub("_", cleaned)[:128].strip()
    if not safe:
        raise ValueError("template_id 가 비어 있습니다.")
    return f"{Config.REDIS_INDEX_PREFIX}:{safe}"


def build_index(template_id: str, template_bytes: bytes) -> TemplateIndex:
    """파싱만 한다 (캐시 접근 없음).

    Raises:
        TemplateError: ZIP/XML 손상.
    """
    specs = scan_fields(template_bytes, include_slots=Config.SLOTS)
    rendered = render_markdown(template_bytes, max_chars=Config.MAX_PREVIEW_CHARS)
    return TemplateIndex(
        template_id=template_id,
        content_hash=content_hash(template_bytes),
        fields=specs,
        markdown=rendered.markdown,
        table_count=rendered.table_count,
        truncated=rendered.truncated,
        indexed_at=time.time(),
    )


async def build_index_async(template_id: str, template_bytes: bytes) -> TemplateIndex:
    """`build_index` 를 스레드에서 돌린다 (가이드 6.9절 — 이벤트 루프 차단 금지).

    파싱은 zip 해제 + 전 섹션 XML 파싱이라 20MB 상한까지 갈 수 있는 blocking 작업이다.
    async 핸들러에서 그대로 부르면 그 동안 같은 pod 의 다른 요청이 전부 멈춘다.
    Redis 가 죽어 있으면 **모든** 요청이 이 경로로 오므로(캐시 miss) 특히 중요하다.

    Raises:
        TemplateError: ZIP/XML 손상.
    """
    return await asyncio.to_thread(build_index, template_id, template_bytes)


def _to_payload(index: TemplateIndex) -> str:
    return json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "slots": bool(Config.SLOTS),
            "content_hash": index.content_hash,
            "markdown": index.markdown,
            "table_count": index.table_count,
            "truncated": index.truncated,
            "indexed_at": index.indexed_at,
            "fields": [
                {
                    "name": s.name,
                    "guide": s.guide,
                    "field_type": s.field_type,
                    "occurrences": s.occurrences,
                    "filled": s.filled,
                    "current_value": s.current_value,
                    "source": s.source,
                }
                for s in index.fields
            ],
        },
        ensure_ascii=False,
    )


def _from_payload(
    template_id: str, raw: str, expected_hash: str | None
) -> TemplateIndex | None:
    """캐시 값 → TemplateIndex. 조건이 안 맞거나 손상이면 None (= miss).

    조용히 None 을 돌려주는 대신 사유를 로그로 남긴다 — 캐시가 계속 miss 하는데
    이유를 모르는 상태(매 턴 재파싱)가 성능 문제의 실제 원인이 되기 때문이다.

    Args:
        expected_hash: 지금 파일 내용의 해시. `None` 은 **대조할 파일이 없다**는 뜻이고
            (목록 표시처럼 파일을 읽지 않는 호출부), 그때는 내용 검증을 건너뛴다.
            저장된 해시를 기대값으로 되먹여 자기 자신과 비교하지 않는다 — 통과가
            보장된 검사는 있으나 없으나 같고, 읽는 사람만 속인다.
    """
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        log_warning("템플릿 색인 값 손상 — 재파싱", event="index_corrupt", resource_id=template_id)
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("fields"), list):
        log_warning(
            "템플릿 색인 스키마 불일치 — 재파싱",
            event="index_schema_mismatch",
            resource_id=template_id,
        )
        return None
    if payload.get("schema_version") != SCHEMA_VERSION:
        log_info(
            "파서 스키마 버전이 달라 색인을 다시 만든다",
            event="index_version_changed",
            resource_id=template_id,
        )
        return None
    if bool(payload.get("slots")) != bool(Config.SLOTS):
        log_info(
            "슬롯 인식 설정이 달라 색인을 다시 만든다",
            event="index_config_changed",
            resource_id=template_id,
        )
        return None
    if expected_hash is not None and payload.get("content_hash") != expected_hash:
        log_info(
            "템플릿 내용이 바뀌어 색인을 다시 만든다",
            event="index_content_changed",
            resource_id=template_id,
        )
        return None

    fields = []
    for item in payload["fields"]:
        if not isinstance(item, dict) or not item.get("name"):
            log_warning(
                "템플릿 색인 항목 손상 — 재파싱",
                event="index_field_corrupt",
                resource_id=template_id,
            )
            return None
        fields.append(
            FieldSpec(
                name=str(item.get("name")),
                guide=str(item.get("guide") or ""),
                field_type=str(item.get("field_type") or ""),
                occurrences=int(item.get("occurrences") or 1),
                filled=bool(item.get("filled")),
                current_value=str(item.get("current_value") or ""),
                source=str(item.get("source") or "field"),
            )
        )
    return TemplateIndex(
        template_id=template_id,
        content_hash=str(payload.get("content_hash") or ""),
        fields=fields,
        markdown=str(payload.get("markdown") or ""),
        table_count=int(payload.get("table_count") or 0),
        truncated=bool(payload.get("truncated")),
        indexed_at=float(payload.get("indexed_at") or 0.0),
        from_cache=True,
    )


async def get_index(template_id: str, template_bytes: bytes) -> TemplateIndex:
    """색인을 돌려준다. 캐시가 유효하면 파싱하지 않는다.

    Args:
        template_id: 캐시 키가 되는 템플릿 식별자 (호출부에서 경로 검증을 끝낸 값).
        template_bytes: 현재 파일 내용. 해시 대조로 교체를 감지하는 데 쓴다.

    Raises:
        TemplateError: 파싱이 필요한데 파일이 손상된 경우.
    """
    expected = content_hash(template_bytes)
    try:
        key = _index_key(template_id)
    except ValueError:
        return await build_index_async(template_id, template_bytes)

    try:
        raw = await resolve_client().get(key)
    except _INFRA_ERRORS as exc:
        # 캐시는 성능 장치다 — 없으면 그냥 파싱한다 (기능 차단 금지)
        log_warning(
            "템플릿 색인 조회 실패 — 직접 파싱",
            event="index_load_failed",
            resource_id=template_id,
            error_type=type(exc).__name__,
        )
        return await build_index_async(template_id, template_bytes)

    if raw is not None:
        cached = _from_payload(template_id, raw, expected)
        if cached is not None:
            return cached

    index = await build_index_async(template_id, template_bytes)
    await store_index(index)
    return index


async def store_index(index: TemplateIndex) -> None:
    """색인 저장 (best-effort). 실패해도 호출부를 막지 않는다.

    등록 API 는 파일을 쓰기 전에 `build_index` 로 파싱 가능 여부를 먼저 확인하므로,
    이미 만든 색인을 다시 파싱하지 않고 저장만 하는 경로가 필요하다.
    """
    ttl_seconds = max(1, int(Config.INDEX_TTL_HOURS * 3600))
    try:
        await resolve_client().set(_index_key(index.template_id), _to_payload(index), ex=ttl_seconds)
    except (ValueError, *_INFRA_ERRORS) as exc:
        log_warning(
            "템플릿 색인 저장 실패 — 다음 요청에서 다시 파싱된다",
            event="index_save_failed",
            resource_id=index.template_id,
            error_type=type(exc).__name__,
        )


async def peek_index(template_id: str) -> TemplateIndex | None:
    """파일을 읽지 않고 캐시만 본다 (목록 표시용).

    `GET /templates` 가 등록된 템플릿마다 파일을 읽어 파싱하면 목록 한 번에
    전체 템플릿을 파싱하게 된다. 그래서 목록은 캐시에 있는 것만 상세를 붙이고,
    없으면 "아직 색인되지 않음" 으로 정직하게 표시한다.
    """
    try:
        key = _index_key(template_id)
    except ValueError:
        return None
    try:
        raw = await resolve_client().get(key)
    except _INFRA_ERRORS:
        return None
    if raw is None:
        return None
    # 파일을 읽지 않으니 내용 대조는 못 한다(expected_hash=None) — 스키마·설정 검증만
    # 한다. 그래서 목록에 보이는 항목 수는 "색인 당시" 값이며, 파일이 그 뒤에 교체됐다면
    # 다음 /fields 호출이 재파싱해 갱신한다.
    return _from_payload(template_id, raw, None)


async def invalidate(template_id: str) -> None:
    """색인 삭제 (템플릿 삭제/교체 시). best-effort."""
    try:
        key = _index_key(template_id)
    except ValueError:
        return
    try:
        await resolve_client().delete(key)
    except _INFRA_ERRORS as exc:
        log_warning(
            "템플릿 색인 삭제 실패 — TTL 로 회수됨",
            event="index_delete_failed",
            resource_id=template_id,
            error_type=type(exc).__name__,
        )
        return
    log_info("템플릿 색인 삭제", event="index_invalidated", resource_id=template_id)
