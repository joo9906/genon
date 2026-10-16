"""업로드 문서(스캔 OCR 결과 포함)의 세션별 Redis 캐시.

**왜 있나**: 스캔 pdf 는 스텝 1 이 표식(`[[GENON_SCAN …]]`)을 OCR 로 읽어 본문으로 바꾼다.
그 결과를 어디에도 남기지 않으면 ① 다음 턴에 플랫폼이 `genosUploaded` 를 싣지 않을 때
문서가 사라지고("문서 내용으로 바꿔줘" 가 `no_document`), ② 싣더라도 매 턴 OCR 을 다시
돌린다(presigned URL 이 만료되면 `SCAN_SOURCE_MISSING`).

- 키는 **세션 키와 따로**다(`<세션 키>:doc`). 세션 저장이 덮어쓰기라 같은 키에 담으면
  값을 저장할 때마다 문서가 지워진다.
- 한 세션에 최근 `_MAX_ENTRIES` 벌만 둔다. **뒤쪽이 최신**이다.
- 조회 키가 비어 있으면(이번 턴에 첨부가 없다) **가장 최근 것**을 준다.
- **캐시는 부가 장치다.** Redis 가 죽어도 요청은 계속된다 — 못 읽으면 없는 것으로, 못
  쓰면 저장 안 한 것으로 돌려주고 로그만 남긴다.
- 문서 본문은 로그에 남기지 않는다(3.8절) — 건수·글자 수만이다.
"""

import json
import re
import time

from redis.exceptions import RedisError

from .config import Config
from .logging_utils import log_info, log_warning
from .redis_client import RedisUnavailableError, resolve_client
from .session_store import _safe_session_key

_INFRA_ERRORS = (RedisError, RedisUnavailableError)
_MAX_ENTRIES = 5
_KEY_RE = re.compile(r"[^A-Za-z0-9_\-]")


def _redis_key(session_id: str) -> str:
    return f"{_safe_session_key(session_id)}:doc"


def _entry_key(key: str) -> str:
    return _KEY_RE.sub("", (key or "").strip())[:64]


async def load_document(session_id: str, key: str) -> dict:
    """`{"found": bool, "text": str, "scan": bool}`. 못 찾거나 Redis 오류면 `found=False`."""
    miss = {"found": False, "text": "", "scan": False}
    try:
        redis_key = _redis_key(session_id)
    except ValueError:
        return miss
    try:
        raw = await resolve_client().get(redis_key)
    except _INFRA_ERRORS as exc:
        log_warning(
            "문서 캐시 조회 실패 — 캐시 없이 진행",
            event="doc_cache_load_failed",
            resource_id="redis",
            error_type=type(exc).__name__,
        )
        return miss
    if raw is None:
        return miss
    try:
        entries = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        log_warning("문서 캐시 값 손상 — 무시", event="doc_cache_corrupt", resource_id="redis")
        return miss
    if not isinstance(entries, list):
        return miss

    wanted = _entry_key(key)
    chosen = None
    for entry in reversed(entries):
        if not isinstance(entry, dict) or not str(entry.get("text") or ""):
            continue
        if not wanted or entry.get("key") == wanted:
            chosen = entry
            break
    if chosen is None:
        return miss
    return {"found": True, "text": str(chosen["text"]), "scan": chosen.get("scan") is True}


async def save_document(session_id: str, key: str, text: str, scan: bool) -> bool:
    """문서를 최신으로 올린다. 같은 키는 갱신하고, 상한을 넘으면 오래된 것부터 버린다."""
    text = text or ""
    entry_key = _entry_key(key)
    if not text.strip() or not entry_key:
        return False
    if len(text) > Config.DOC_CACHE_MAX_CHARS:
        # 잘라 담으면 다음 턴에 **일부만 있는 문서**로 채운다 — 못 담는 편이 낫다.
        log_warning(
            "문서가 캐시 상한을 넘어 저장하지 않는다",
            event="doc_cache_too_large",
            resource_id="redis",
            item_count=len(text),
        )
        return False
    try:
        redis_key = _redis_key(session_id)
    except ValueError:
        return False

    client = resolve_client()
    try:
        raw = await client.get(redis_key)
        try:
            entries = json.loads(raw) if raw is not None else []
        except (json.JSONDecodeError, TypeError):
            entries = []
        entries = [
            e for e in (entries if isinstance(entries, list) else [])
            if isinstance(e, dict) and e.get("key") != entry_key
        ]
        entries.append(
            {"key": entry_key, "text": text, "scan": bool(scan), "saved_at": time.time()}
        )
        ttl_seconds = max(1, int(Config.SESSION_TTL_HOURS * 3600))
        await client.set(
            redis_key,
            json.dumps(entries[-_MAX_ENTRIES:], ensure_ascii=False),
            ex=ttl_seconds,
        )
    except _INFRA_ERRORS as exc:
        log_warning(
            "문서 캐시 저장 실패 — 다음 턴에 다시 읽는다",
            event="doc_cache_save_failed",
            resource_id="redis",
            error_type=type(exc).__name__,
        )
        return False
    log_info(
        "문서 캐시 저장",
        event="doc_cache_saved",
        resource_id="redis",
        item_count=len(text),
        status=f"scan={int(bool(scan))}",
    )
    return True
