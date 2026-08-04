"""내보내기 세션 저장소 (GenOS Redis).

다운로드 버튼은 대화 턴의 연장이 아니라 **별개 HTTP 요청**이고, GenOS 는 워크플로우
Python 단계에 이전 대화를 자동으로 넣어주지 않는다(CLAUDE.md §4.2 — session_id 만 제공).
그래서 대화에서 다듬은 문단 결과를 여기 보관해 두고 내보내기 요청이 꺼내 쓴다.

**LLM 을 다시 부르지 않는 것이 이 모듈의 존재 이유다.** 내보내기 시점에 재호출하면
같은 입력이라도 결과가 달라져 "화면에서 본 문장과 파일 속 문장이 다른" 상태가 된다.

보관하는 것:
- `paragraphs`: 원본에서 뽑은 문단 평문 (index 순서)
- `results`: 다듬은/번역한 문단 `{index: text}`
- `fingerprint`: 원본 hwpx 지문. 내보낼 때 올린 파일이 같은 문서인지 대조한다.
- `source_kind`: hwpx / docx / pdf — hwpx 출력 가능 여부를 여기서 판정한다.

보관하지 **않는** 것: **원본 파일 바이트.** 상한이 20MB 이고 JSON 에 실으면 더 커진다.
원본은 내보내기 요청에 multipart 로 다시 받는다.

SFR-006 `template_fill/session_store.py` 와 같은 계약의 사본이다
(배포 단위 간 import 금지). redis SDK 는 비동기 클라이언트만 쓴다 — 동기 클라이언트는
이벤트 루프를 막는다(가이드 blocking I/O 금지).

3.8절: 저장 값에 문서 원문이 담기므로 로그에는 개수·상태만 남긴다.
"""

import json
import re
import time

import redis.asyncio as redis
from redis.exceptions import RedisError

from config import Config
from export_pipeline.logging_utils import log_info, log_warning

_SESSION_ID_RE = re.compile(r"[^A-Za-z0-9_\-]")
_STATE_VERSION = 1

_CLIENT: "redis.Redis | None" = None

# 예외 메시지용 고정 문구 — 인프라 예외 원문을 담지 않는다 (3.8절)
_SAVE_FAILED_MSG = "작업 상태를 저장하지 못했습니다."


class SessionStoreError(RuntimeError):
    """세션 저장/조회 인프라 오류.

    계약: 메시지는 이 파일에서 만든 고정 문구만 담는다 (DB 오류 원문 금지).
    호출부가 사용자 노출 오류로 변환한다.
    """


def _safe_session_key(session_id: str) -> str:
    """세션 id 를 Redis 키로 안전하게 정규화 (키 인젝션/과대 키 방지)."""
    cleaned = _SESSION_ID_RE.sub("_", (session_id or "").strip())[:128]
    if not cleaned:
        raise ValueError("session_id 가 비어 있습니다.")
    return f"{Config.REDIS_KEY_PREFIX}:{cleaned}"


def _resolve_client() -> "redis.Redis":
    """GenOS Redis 클라이언트 (지연 초기화, 프로세스당 재사용)."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    if not Config.REDIS_URL:
        raise SessionStoreError("REDIS_URL 이 설정되지 않았습니다.")
    _CLIENT = redis.from_url(Config.REDIS_URL, decode_responses=True)
    return _CLIENT


def empty_state() -> dict:
    return {
        "version": _STATE_VERSION,
        "source_kind": "",
        "fingerprint": "",
        "paragraphs": [],
        "results": {},
        "updated_at": 0.0,
    }


async def load_session(session_id: str) -> dict:
    """세션 상태 로드. 없거나 만료/손상이면 빈 상태를 반환한다.

    인프라 오류도 빈 상태로 degrade 하되 로그로 노출한다 — 내보내기는 빈 상태면
    "세션을 찾을 수 없다"로 안내되므로 조용한 오작동이 되지 않는다.
    """
    empty = empty_state()
    key = _safe_session_key(session_id)
    try:
        raw = await _resolve_client().get(key)
    except (RedisError, SessionStoreError) as exc:
        log_warning(
            "세션 로드 실패로 빈 상태 사용",
            event="session_load_failed",
            resource_id="redis",
            error_type=type(exc).__name__,
        )
        return empty
    if raw is None:
        return empty
    try:
        state = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        log_warning(
            "세션 상태 값 손상으로 초기화",
            event="session_state_corrupt",
            resource_id="redis",
            error_type=type(exc).__name__,
        )
        return empty

    if (
        not isinstance(state, dict)
        or not isinstance(state.get("paragraphs"), list)
        or not isinstance(state.get("results"), dict)
    ):
        log_warning(
            "세션 상태 스키마 불일치로 초기화",
            event="session_state_schema_mismatch",
            resource_id="redis",
        )
        return empty
    return state


async def save_session(
    session_id: str,
    *,
    source_kind: str,
    fingerprint: str,
    paragraphs: list,
    results: dict | None = None,
) -> None:
    """세션 상태 저장. TTL 은 Redis 네이티브 만료(EX)로 설정한다.

    Args:
        source_kind: hwpx / docx / pdf. hwpx 출력 가능 여부 판정에 쓴다.
        fingerprint: 원본 hwpx 지문 (hwpx 가 아니면 빈 문자열).
        paragraphs: 원본 문단 평문 목록 (index 순서).
        results: 다듬은/번역한 문단 {index: text}. 대화가 진행되며 갱신된다.

    Raises:
        SessionStoreError: 저장 실패. 조용히 넘기면 다운로드 때 결과가 유실된다.
    """
    key = _safe_session_key(session_id)
    state = {
        "version": _STATE_VERSION,
        "source_kind": source_kind,
        "fingerprint": fingerprint,
        "paragraphs": paragraphs,
        # 키는 JSON 에서 문자열이 된다 — 읽을 때 int 로 되돌린다(results_as_mapping)
        "results": {str(k): v for k, v in (results or {}).items()},
        "updated_at": time.time(),
    }
    ttl_seconds = max(1, int(Config.SESSION_TTL_HOURS * 3600))
    try:
        await _resolve_client().set(key, json.dumps(state, ensure_ascii=False), ex=ttl_seconds)
    except (RedisError, SessionStoreError) as exc:
        # 저장 실패 = 다운로드 시 결과가 유실된다 — 침묵 처리하지 않고 호출부로 전달.
        # 3.8절: DB 오류 원문을 메시지에 담지 않는다. 분류는 error_type 으로만.
        log_warning(
            "세션 저장 실패",
            event="session_save_failed",
            resource_id="redis",
            error_type=type(exc).__name__,
        )
        raise SessionStoreError(_SAVE_FAILED_MSG) from exc
    log_info(
        "세션 저장 완료",
        event="session_saved",
        resource_id="redis",
        item_count=len(paragraphs),  # 문단 내용은 남기지 않고 개수만 (3.8절)
    )


def results_as_mapping(state: dict) -> dict:
    """세션의 results 를 {int: str} 로 되돌린다 (JSON 키는 문자열이다)."""
    mapping: dict = {}
    for key, value in (state.get("results") or {}).items():
        try:
            mapping[int(key)] = str(value)
        except (TypeError, ValueError):
            # 손상 키는 버리되 조용히 넘기지 않는다
            log_warning("세션 결과에 정수가 아닌 문단 번호가 있어 제외", event="session_bad_index")
    return mapping


async def end_session(session_id: str) -> None:
    """세션 종료 — 상태를 즉시 삭제한다.

    best-effort: 삭제 실패해도 TTL 이 회수하므로 예외를 던지지 않는다.
    """
    try:
        key = _safe_session_key(session_id)
    except ValueError:
        return
    try:
        await _resolve_client().delete(key)
    except (RedisError, SessionStoreError) as exc:
        log_warning(
            "세션 삭제 실패 — TTL 로 회수됨(무시)",
            event="session_delete_failed",
            resource_id="redis",
            error_type=type(exc).__name__,
        )
        return
    log_info("세션 종료로 상태 삭제 완료", event="session_ended", resource_id="redis")
