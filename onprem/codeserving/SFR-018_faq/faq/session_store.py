"""생성된 FAQ 의 Redis 세션 저장소 — 대화(02)와 다운로드(03)를 잇는다.

GenOS 는 워크플로우 Python 단계에 이전 대화를 자동으로 넣어주지 않는다. 대화에서
만든 FAQ 를 다운로드 버튼(코드 서빙)이 다시 만들지 않고 그대로 내려주려면 두 pod 가
공유하는 저장소가 필요하다. SFR-006 과 같은 규약으로 GenOS Redis 를 쓴다.

**다시 생성하지 않고 저장해 둔 것을 내려주는 이유**: LLM 을 다시 부르면 화면에서 본
FAQ 와 내려받은 파일의 내용이 달라진다. 사용자는 같은 것을 기대한다.

생명주기
- 생성이 끝날 때마다 세션 키를 갱신 저장한다.
- 다운로드는 세션을 **지우지 않는다** — 사용자가 hwpx 로 받고 다시 xlsx 로 받을 수
  있어야 한다 (006 은 다운로드가 대화의 끝이라 거기서 종료하지만, FAQ 는 형식만
  바꿔 여러 번 받는 흐름이 정상이다).
- 버려진 세션은 Redis 네이티브 만료(SET ... EX)로 자동 회수한다.
- 그래서 **삭제 함수를 두지 않는다.** 006 의 `session_store` 에는 `end_session` 이
  있지만 여기에 같은 것을 두면 안 된다 — 호출하는 순간 위의 "형식만 바꿔 여러 번
  받기" 가 깨진다. 회수는 TTL 하나로만 한다.

3.8절: 저장 값에 문서 내용이 담기므로 로그에는 세션 id 대신 항목 개수 등 메타만 남긴다.
"""

import json
import re
import time

from redis.exceptions import RedisError

from .config import Config
from .logging_utils import log_info, log_warning
from .redis_client import RedisUnavailableError, resolve_client

_SESSION_ID_RE = re.compile(r"[^A-Za-z0-9_\-]")
_STATE_VERSION = 1

# 인프라 예외 묶음 — Redis 오류와 접속 정보 부재를 같은 자리에서 처리한다
_INFRA_ERRORS = (RedisError, RedisUnavailableError)

_SAVE_FAILED_MSG = "FAQ 를 저장하지 못했습니다."


class SessionStoreError(RuntimeError):
    """세션 저장/조회 인프라 오류.

    계약: 메시지는 이 파일에서 만든 고정 문구만 담는다 (DB 오류 원문 금지).
    """


def _safe_session_key(session_id: str) -> str:
    """세션 id 를 Redis 키로 안전하게 정규화 (키 인젝션/과대 키 방지)."""
    cleaned = _SESSION_ID_RE.sub("_", (session_id or "").strip())[:128]
    if not cleaned:
        raise ValueError("session_id 가 비어 있습니다.")
    return f"{Config.REDIS_KEY_PREFIX}:{cleaned}"


async def save_faqs(session_id: str, items: list, *, title: str = "") -> None:
    """생성된 FAQ 를 저장한다.

    Args:
        items: `formatting.to_export_rows` 형태 `[{question, answer, sources}]`.
        title: 문서 제목(있으면 파일명·시트명에 쓴다).

    Raises:
        SessionStoreError: 저장 실패. **침묵 처리하지 않는다** — 저장이 안 되면
            다운로드 버튼이 나중에 404 를 내는데, 그때는 원인을 짚기 어렵다.
    """
    key = _safe_session_key(session_id)
    state = {
        "version": _STATE_VERSION,
        "title": title,
        "items": items,
        "updated_at": time.time(),
    }
    ttl_seconds = max(1, int(Config.SESSION_TTL_HOURS * 3600))
    try:
        await resolve_client().set(key, json.dumps(state, ensure_ascii=False), ex=ttl_seconds)
    except _INFRA_ERRORS as exc:
        log_warning(
            "FAQ 세션 저장 실패",
            event="session_save_failed",
            resource_id="redis",
            error_type=type(exc).__name__,
        )
        raise SessionStoreError(_SAVE_FAILED_MSG) from exc
    log_info(
        "FAQ 세션 저장 완료",
        event="session_saved",
        resource_id="redis",
        item_count=len(items),  # 내용은 남기지 않고 개수만 (3.8절)
    )


async def load_faqs(session_id: str) -> dict:
    """저장된 FAQ 를 읽는다. 없거나 만료/손상이면 빈 상태를 반환한다."""
    empty = {"version": _STATE_VERSION, "title": "", "items": [], "updated_at": 0.0}
    key = _safe_session_key(session_id)
    try:
        raw = await resolve_client().get(key)
    except _INFRA_ERRORS as exc:
        log_warning(
            "FAQ 세션 로드 실패로 빈 상태 사용",
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
            "FAQ 세션 값 손상으로 초기화",
            event="session_state_corrupt",
            resource_id="redis",
            error_type=type(exc).__name__,
        )
        return empty
    if not isinstance(state, dict) or not isinstance(state.get("items"), list):
        log_warning(
            "FAQ 세션 스키마 불일치로 초기화",
            event="session_state_schema_mismatch",
            resource_id="redis",
        )
        return empty
    return state
