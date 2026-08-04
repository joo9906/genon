"""멀티턴 필드 수집 상태의 Redis 기반 세션 저장소.

GenOS 는 워크플로우 Python 단계에 이전 대화를 자동으로 넣어주지 않는다
(CLAUDE.md §4.2 — genos_state.session_id 만 제공). 따라서 턴 사이에
수집된 필드 값을 자체적으로 보존해야 하며, 여기서는 GenOS 가 제공하는
Redis 에 세션당 키 하나(JSON)로 저장한다.

생명주기:
- 대화가 진행되는 동안(턴마다) 수집 값을 세션 키에 갱신 저장한다.
- 문서 생성이 끝나면 end_session() 으로 해당 세션 키를 즉시 삭제한다.
- 완료 없이 버려진 세션은 Redis 네이티브 만료(SET ... EX)로 자동 회수한다
  (별도 청소 데몬/스캔 불필요, TTL 은 안전망 역할).

배포 전제:
- 워크플로우 pod(대화)와 코드 서빙 pod(다운로드)가 같은 Redis(REDIS_URL)를
  바라본다. 공유 볼륨 마운트는 더 이상 필요 없다.
- redis SDK 는 비동기 클라이언트(redis.asyncio)를 쓴다. 동기 클라이언트는
  이벤트 루프를 막으므로(가이드 blocking I/O 금지) 사용하지 않는다.

3.8절: 저장 값에 사용자 입력이 담기므로 로그에는 세션 id 와 필드 개수 등
메타정보만 남긴다.
"""

import json
import re
import time

import redis.asyncio as redis
from redis.exceptions import RedisError

from .config import Config
from .logging_utils import log_info, log_warning

_SESSION_ID_RE = re.compile(r"[^A-Za-z0-9_\-]")
_STATE_VERSION = 1

_CLIENT: "redis.Redis | None" = None


# 예외 메시지용 고정 문구 — 인프라 예외 원문을 담지 않는다 (3.8절)
_SAVE_FAILED_MSG = "세션 상태를 저장하지 못했습니다."


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


async def load_session(session_id: str) -> dict:
    """세션 상태 로드. 없거나 만료/손상이면 빈 상태를 반환한다.

    Redis 만료(TTL)는 서버가 처리하므로 만료 키는 조회 시 없는 것과 동일하게
    빈 상태가 된다. 인프라 오류(연결 실패 등)도 빈 상태로 degrade 하되 로그로 노출한다.

    Returns:
        {"version": 1, "template_id": str, "values": {필드명: 값}, "updated_at": float}
    """
    empty = {
        "version": _STATE_VERSION,
        "template_id": "",
        "values": {},
        # raw_values: 톤 변환 전 원본. 매 턴 누적 값을 다시 변환해 문체가 중첩되는 것을
        # 막고, 톤 설정이 바뀌었을 때 원본에서 다시 적용할 수 있게 보존한다.
        "raw_values": {},
        "updated_at": 0.0,
    }
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
        # 손상 값은 침묵 처리하지 않고 로그로 노출 후 초기화 (5장 컨벤션)
        log_warning(
            "세션 상태 값 손상으로 초기화",
            event="session_state_corrupt",
            resource_id="redis",
            error_type=type(exc).__name__,
        )
        return empty

    if not isinstance(state, dict) or not isinstance(state.get("values"), dict):
        log_warning(
            "세션 상태 스키마 불일치로 초기화",
            event="session_state_schema_mismatch",
            resource_id="redis",
        )
        return empty
    return state


async def save_session(
    session_id: str, template_id: str, values: dict, raw_values: dict | None = None
) -> None:
    """세션 상태 저장. TTL 은 Redis 네이티브 만료(EX)로 설정한다.

    Args:
        values: 문서에 기록할 최종 값 (톤 적용 후).
        raw_values: 톤 변환 전 원본 값. 생략하면 values 를 그대로 원본으로 본다.
    """
    key = _safe_session_key(session_id)
    state = {
        "version": _STATE_VERSION,
        "template_id": template_id,
        "values": values,
        "raw_values": raw_values if raw_values is not None else values,
        "updated_at": time.time(),
    }
    ttl_seconds = max(1, int(Config.SESSION_TTL_HOURS * 3600))
    try:
        await _resolve_client().set(
            key, json.dumps(state, ensure_ascii=False), ex=ttl_seconds
        )
    except (RedisError, SessionStoreError) as exc:
        # 저장 실패 = 다음 턴에 값이 유실된다 — 침묵 처리하지 않고 호출부로 전달.
        # 3.8절: DB 오류 원문을 메시지에 담지 않는다. 분류는 error_type 으로만 남긴다.
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
        item_count=len(values),  # 필드 값은 남기지 않고 개수만 (3.8절)
    )


async def end_session(session_id: str) -> None:
    """세션 종료 — 수집 상태를 즉시 삭제한다.

    문서 생성이 끝나면 더는 유지할 필요가 없으므로 호출한다. best-effort:
    삭제 실패해도 TTL 이 나중에 회수하므로 예외를 던지지 않고 로그만 남긴다.
    """
    try:
        key = _safe_session_key(session_id)
    except ValueError:
        return  # 빈/잘못된 세션 id 는 지울 것도 없음
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
