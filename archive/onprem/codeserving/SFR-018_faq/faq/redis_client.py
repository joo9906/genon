"""GenOS Redis 클라이언트 공유 지점.

모듈마다 `redis.from_url` 을 부르면 **연결 풀이 그만큼 늘어난다** — 같은 서버를 향한
풀을 여러 개 두면 pod 당 커넥션 수가 배로 뛴다. 그래서 클라이언트는 여기 하나만 둔다
(SFR-006 `redis_client.py` 와 같은 계약의 사본 — 배포 단위 간 import 금지).

- 비동기 클라이언트(`redis.asyncio`)만 쓴다. 동기 클라이언트는 이벤트 루프를 막는다.
- 접속 정보 부재/오류 원문은 호출부로 흘리지 않는다 (3.8절) — 고정 문구만 담는다.
"""

import redis.asyncio as redis

from .config import Config

_CLIENT = None


class RedisUnavailableError(RuntimeError):
    """Redis 접속 정보가 없거나 클라이언트를 만들 수 없다.

    계약: 메시지는 이 파일에서 만든 고정 문구만 담는다.
    """


def resolve_client():
    """지연 초기화된 공용 클라이언트 (프로세스당 하나)."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    if not Config.REDIS_URL:
        raise RedisUnavailableError("REDIS_URL 이 설정되지 않았습니다.")
    _CLIENT = redis.from_url(Config.REDIS_URL, decode_responses=True)
    return _CLIENT
