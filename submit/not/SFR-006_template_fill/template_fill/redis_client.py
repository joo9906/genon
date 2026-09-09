"""GenOS Redis 클라이언트 공유 지점.

세션 저장소(session_store)와 템플릿 색인 캐시(template_index)가 같은 Redis 를
쓴다. 모듈마다 `redis.from_url` 을 부르면 **연결 풀이 그만큼 늘어난다** — 같은
서버를 향한 풀을 여러 개 두면 pod 당 커넥션 수가 배로 뛰고, 운영에서 상한에
먼저 부딪히는 쪽이 세션 저장(값 유실)이다. 그래서 클라이언트는 여기 하나만 둔다.

- 비동기 클라이언트(redis.asyncio)만 쓴다. 동기 클라이언트는 이벤트 루프를 막는다
  (가이드 blocking I/O 금지).
- 접속 정보 부재/오류 원문은 호출부로 흘리지 않는다 (3.8절) — 고정 문구만 담는다.
"""

import redis.asyncio as redis

from .config import Config

_CLIENT: "redis.Redis | None" = None


class RedisUnavailableError(RuntimeError):
    """Redis 접속 정보가 없거나 클라이언트를 만들 수 없다.

    계약: 메시지는 이 파일에서 만든 고정 문구만 담는다.
    """


def resolve_client() -> "redis.Redis":
    """지연 초기화된 공용 클라이언트 (프로세스당 하나)."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    if not Config.REDIS_URL:
        raise RedisUnavailableError("REDIS_URL 이 설정되지 않았습니다.")
    _CLIENT = redis.from_url(Config.REDIS_URL, decode_responses=True)
    return _CLIENT
