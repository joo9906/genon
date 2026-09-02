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
- 클라이언트는 `redis_client.resolve_client()` 하나를 공유한다 (연결 풀 중복 방지).
  비동기 클라이언트만 쓴다 — 동기 클라이언트는 이벤트 루프를 막는다.

3.8절: 저장 값에 사용자 입력이 담기므로 로그에는 세션 id 와 필드 개수 등
메타정보만 남긴다.
"""

import json
import re
import time

from redis.exceptions import RedisError

from .config import Config
from .logging_utils import log_info, log_warning
from .redis_client import RedisUnavailableError, resolve_client

_SESSION_ID_RE = re.compile(r"[^A-Za-z0-9_\-]")
# 2: 본문 블록(blocks) 추가. 옛 세션에는 키가 없으므로 읽는 쪽이 기본값으로 흡수한다
#    (버전 불일치로 세션을 버리면 진행 중인 대화의 값이 사라진다).
# 3: `source_doc_hash`(문자열 하나) → `source_doc_hashes`(목록). 대화 중간에도 파일을
#    올릴 수 있게 되면서 **한 세션이 문서를 여러 벌 태운다** (2026-09-02).
_STATE_VERSION = 3

# 한 세션이 기억하는 업로드 문서 표식의 최대 개수. 목록이 무한히 늘면 긴 대화에서
# 세션 페이로드가 단조 증가한다 — **오래된 것부터 버린다.** 버려진 표식의 문서가 다시
# 올라오면 자동 채움을 한 번 더 돌 뿐이고(빈 항목만 채우므로 값은 안 밀린다) 그때
# 드는 것은 LLM 호출 몇 번이다. 목록이 커져 세션 저장이 실패하는 쪽이 훨씬 나쁘다.
_MAX_DOC_HASHES = 20

# 인프라 예외 묶음 — Redis 오류와 접속 정보 부재를 같은 자리에서 처리한다
_INFRA_ERRORS = (RedisError, RedisUnavailableError)


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


def _block_payload(blocks) -> list:
    """본문 블록을 JSON 으로 저장 가능한 형태로 만든다.

    `BodyBlock`(dataclass)과 dict 를 모두 받는다 — 대화는 검증을 거친 dataclass 를 주고,
    화면 편집 경로는 요청 본문의 dict 를 그대로 준다. 여기서 hwpx_blocks 를 import 하지
    않는 이유는 세션 저장소가 문서 조작 모듈에 의존할 이유가 없어서다 (덕 타이핑으로 충분).
    """
    payload: list = []
    for block in blocks or ():
        text = getattr(block, "text", None)
        style_ref = getattr(block, "style_ref", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
            style_ref = block.get("style_ref")
        text = str(text or "").strip()
        if not text:
            continue
        payload.append({"text": text, "style_ref": str(style_ref or "")})
    return payload


def normalize_doc_hashes(raw, legacy: str = "") -> list:
    """업로드 문서 표식 목록을 정규화한다. **옛 세션도 버리지 않고 흡수한다.**

    2026-09-02 이전 세션에는 `source_doc_hash` 문자열 하나만 있다. 목록으로 바뀌었다는
    이유로 그 값을 버리면, 배포 시점에 진행 중이던 대화가 **다음 턴에 같은 문서를 다시
    태우고 사용자가 지운 값을 되살린다** — 오류는 나지 않는다. `blocks` 를 기본값으로
    흡수하는 것과 같은 규율이다.

    Args:
        raw: 세션의 `source_doc_hashes` (목록이 아닐 수 있다 — 손상 값 방어).
        legacy: 세션의 옛 `source_doc_hash` 문자열. 목록이 비었을 때만 쓴다.

    Returns:
        중복 없는 문자열 목록. **뒤쪽이 최신**이고 길이는 `_MAX_DOC_HASHES` 이하.
    """
    items = raw if isinstance(raw, (list, tuple)) else ()
    hashes: list = []
    for item in items:
        # 숫자·None 이 섞여 들어와도 목록 전체를 버리지 않는다 — 표식 하나가 이상하다고
        # 나머지를 잃으면 그만큼 문서를 다시 태운다.
        value = str(item or "").strip()
        if value and value not in hashes:
            hashes.append(value)

    fallback = str(legacy or "").strip()
    if not hashes and fallback:
        hashes = [fallback]

    # 상한을 넘으면 **오래된 앞쪽**을 버린다.
    return hashes[-_MAX_DOC_HASHES:]


async def load_session(session_id: str) -> dict:
    """세션 상태 로드. 없거나 만료/손상이면 빈 상태를 반환한다.

    Redis 만료(TTL)는 서버가 처리하므로 만료 키는 조회 시 없는 것과 동일하게
    빈 상태가 된다. 인프라 오류(연결 실패 등)도 빈 상태로 degrade 하되 로그로 노출한다.

    Returns:
        {"version": 3, "template_id": str, "values": {필드명: 값},
         "blocks": [...], "source_doc_hashes": [str], "updated_at": float}
    """
    empty = {
        "version": _STATE_VERSION,
        "template_id": "",
        "values": {},
        # blocks: 템플릿 항목 밖에 이어 쓴 본문 [{"text":..., "style_ref":...}].
        # 항목(values)과 달리 **순서가 의미를 갖는** 목록이라 dict 가 아니라 배열이다.
        "blocks": [],
        # source_doc_hashes: 자동 채움에 **이미 쓴** 업로드 문서의 해시 목록
        # (2026-08-31 문자열 하나로 도입 → 2026-09-02 목록). 이 표식이 없으면 매 턴
        # 문서가 다시 실려 올 때 같은 값을 또 추출하고, 사용자가 지운 값을 **우리가
        # 되살린다** — 오류는 나지 않는다.
        #
        # **목록인 이유**: 대화 중간에도 파일을 올릴 수 있어 한 세션이 문서를 여러 벌
        # 태운다. 하나만 들면 두 번째 문서를 태운 순간 첫 문서의 표식이 사라져, 캔버스가
        # 그 문서를 계속 실어 올 때 **번갈아 가며 다시 태운다.**
        # **본문은 담지 않는다** (3.8절) — 자동 채움은 그 턴에 끝나므로 뒤에서 볼 일이 없다.
        "source_doc_hashes": [],
        "updated_at": 0.0,
    }
    key = _safe_session_key(session_id)
    try:
        raw = await resolve_client().get(key)
    except _INFRA_ERRORS as exc:
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
    # 옛 버전 세션(blocks 없음)도 그대로 이어 쓴다 — 버전이 올랐다고 값을 버리면
    # 배포 시점에 진행 중이던 대화가 전부 초기화된다.
    if not isinstance(state.get("blocks"), list):
        state["blocks"] = []
    # 표식도 같은 규율로 흡수한다. 옛 세션(문자열 하나)은 목록 한 칸이 된다.
    state["source_doc_hashes"] = normalize_doc_hashes(
        state.get("source_doc_hashes"), state.get("source_doc_hash")
    )
    # 옛 키는 지운다 — 남겨 두면 읽는 쪽이 둘 중 어느 것이 정본인지 모른다.
    state.pop("source_doc_hash", None)
    return state


async def save_session(
    session_id: str,
    template_id: str,
    values: dict,
    blocks: list | None = None,
    source_doc_hashes: list | None = None,
) -> None:
    """세션 상태 저장. TTL 은 Redis 네이티브 만료(EX)로 설정한다.

    **`raw_values` 는 2026-09-02 에 걷어냈다** (`raw_text` 와 같은 톤 제거 잔재).
    톤이 값을 다시 쓰던 시절의 "변환 전 원본" 인데, 006 의 톤이 없어진 뒤로
    `merge_values` 가 정규화를 하지 않아 **`values` 와 언제나 같은 dict** 였다 —
    매 턴 Redis 에 두 벌로 저장되고 HTTP 응답에도 실려 나갔다.

    Args:
        values: 문서에 기록할 값.
        blocks: 템플릿 항목 밖에 이어 쓴 본문 목록. `BodyBlock` 또는 dict 를 받는다.
        source_doc_hashes: 자동 채움에 이미 쓴 업로드 문서의 해시 **목록**.
            **저장은 덮어쓰기라** 호출부가 매 턴 기존 목록을 다시 실어야 한다 —
            빠뜨리면 표식이 지워져 다음 턴에 같은 문서를 또 태우고, 사용자가 지운 값이
            되살아난다. **이번 턴 것만 실으면 앞서 태운 문서들이 통째로 잊힌다.**
    """
    key = _safe_session_key(session_id)
    state = {
        "version": _STATE_VERSION,
        "template_id": template_id,
        "values": values,
        "blocks": _block_payload(blocks),
        # 상한·중복 제거를 저장 시점에도 건다 — 호출부가 병합을 어떻게 하든 세션에
        # 들어가는 모양은 한 곳에서 정해진다.
        "source_doc_hashes": normalize_doc_hashes(source_doc_hashes),
        "updated_at": time.time(),
    }
    ttl_seconds = max(1, int(Config.SESSION_TTL_HOURS * 3600))
    try:
        await resolve_client().set(
            key, json.dumps(state, ensure_ascii=False), ex=ttl_seconds
        )
    except _INFRA_ERRORS as exc:
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
        status=f"blocks={len(state['blocks'])}",
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
        await resolve_client().delete(key)
    except _INFRA_ERRORS as exc:
        log_warning(
            "세션 삭제 실패 — TTL 로 회수됨(무시)",
            event="session_delete_failed",
            resource_id="redis",
            error_type=type(exc).__name__,
        )
        return
    log_info("세션 종료로 상태 삭제 완료", event="session_ended", resource_id="redis")
