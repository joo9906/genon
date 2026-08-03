"""멀티턴 필드 수집 상태의 파일 기반 세션 저장소.

GenOS 는 워크플로우 Python 단계에 이전 대화를 자동으로 넣어주지 않는다
(CLAUDE.md §4.2 — genos_state.session_id 만 제공). 따라서 턴 사이에
수집된 필드 값을 자체적으로 보존해야 하며, 여기서는 세션당 JSON 파일
하나로 저장한다.

배포 전제:
- 워크플로우 pod(대화)와 코드 서빙 pod(다운로드)가 같은 볼륨을
  TEMPLATE_FILL_SESSION_DIR 로 마운트한다.
- 단일 writer(한 세션은 한 사용자의 순차 턴) 전제. 동시 쓰기 충돌은
  임시파일 + os.replace 원자 교체로 마지막 쓰기 승리(last-write-wins).

3.8절: 저장 파일에 사용자 입력값이 담기므로 로그에는 세션 id 와
필드 개수 등 메타정보만 남긴다.
"""

import json
import os
import re
import time

from .config import Config
from .logging_utils import log_info, log_warning

_SESSION_ID_RE = re.compile(r"[^A-Za-z0-9_\-]")
_STATE_VERSION = 1


def _safe_session_filename(session_id: str) -> str:
    """세션 id 를 파일명으로 안전하게 정규화 (경로 조작 문자 제거)."""
    cleaned = _SESSION_ID_RE.sub("_", (session_id or "").strip())[:128]
    if not cleaned:
        raise ValueError("session_id 가 비어 있습니다.")
    return f"{cleaned}.json"


def _session_path(session_id: str) -> str:
    return os.path.join(Config.SESSION_DIR, _safe_session_filename(session_id))


def load_session(session_id: str) -> dict:
    """세션 상태 로드. 없거나 만료/손상이면 빈 상태를 반환한다.

    Returns:
        {"version": 1, "template_id": str, "values": {필드명: 값}, "updated_at": float}
    """
    empty = {"version": _STATE_VERSION, "template_id": "", "values": {}, "updated_at": 0.0}
    path = _session_path(session_id)
    if not os.path.exists(path):
        return empty
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        # 손상 파일은 침묵 처리하지 않고 로그로 노출 후 초기화 (5장 컨벤션)
        log_warning(f"[세션] 상태 파일 손상으로 초기화 error_type={type(exc).__name__}")
        return empty

    if not isinstance(state, dict) or not isinstance(state.get("values"), dict):
        log_warning("[세션] 상태 스키마 불일치로 초기화")
        return empty

    age_hours = (time.time() - float(state.get("updated_at") or 0)) / 3600.0
    if age_hours > Config.SESSION_TTL_HOURS:
        log_info(f"[세션] TTL 초과({age_hours:.1f}h)로 초기화")
        return empty
    return state


def save_session(session_id: str, template_id: str, values: dict) -> None:
    """세션 상태 저장 (임시파일 → 원자 교체)."""
    os.makedirs(Config.SESSION_DIR, exist_ok=True)
    path = _session_path(session_id)
    state = {
        "version": _STATE_VERSION,
        "template_id": template_id,
        "values": values,
        "updated_at": time.time(),
    }
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp_path, path)
    log_info(f"[세션] 저장 완료 fields={len(values)}")


def cleanup_expired_sessions() -> int:
    """TTL 지난 세션 파일 삭제. 호출 시점에 기회적으로 수행 (별도 데몬 불필요).

    Returns:
        삭제한 파일 수.
    """
    if not os.path.isdir(Config.SESSION_DIR):
        return 0
    now = time.time()
    ttl_seconds = Config.SESSION_TTL_HOURS * 3600
    removed = 0
    for name in os.listdir(Config.SESSION_DIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(Config.SESSION_DIR, name)
        try:
            if now - os.path.getmtime(path) > ttl_seconds:
                os.remove(path)
                removed += 1
        except OSError:
            continue  # 다른 프로세스가 먼저 지웠거나 잠금 — 다음 기회에
    if removed:
        log_info(f"[세션] 만료 세션 {removed}건 정리")
    return removed
