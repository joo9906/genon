"""session_store — Redis 세션 저장소 왕복·키 안전·블록 보존.

## 이 파일이 `test_run_chat.py` 를 대체한다 (2026-08-11)

옛 파일은 세 가지를 검증했는데 **셋 다 지금은 존재하지 않는다**:

| 옛 테스트 | 지금 |
|---|---|
| `run_chat.run` 멀티턴 generator | 워크플로우 스텝 3개(`sfr006_0*.py`) + `chat_api` 로 갈렸다. `onprem/test/check_chat_turn.py`(25건)가 **둘을 함께 태워** 검증한다 |
| `Config.LLM_MODE = "mock"` 추출 | onprem 배포 단위에는 mock 경로가 없다 |
| `Config.SESSION_DIR` 파일 세션 | **Redis** 로 옮겼다 (레플리카 2개면 파일/전역 dict 세션은 깨진다) |

그래서 옛 파일을 되살리는 대신, 지금 실제로 있는 것 — **Redis 세션 저장소** — 을
검증한다. 채팅 흐름 자체는 `check_chat_turn.py` 가 맡으므로 여기서 겹쳐 하지 않는다.

## 가짜 Redis 는 import 보다 먼저 꽂는다

`session_store` 가 `from .redis_client import resolve_client` 로 **이름을 복사**한다.
모듈이 로드된 뒤에 `redis_client` 쪽만 갈아 끼우면 이미 복사된 원본이 계속 쓰여
**점검이 통째로 무의미해진다.** 그래서 양쪽을 다 바꾼다.
"""

import asyncio
import unittest

from . import onprem_path  # noqa: F401 - import 부작용으로 sys.path 를 세운다


class FakeRedis:
    """세션 저장소가 쓰는 명령만 가진 최소 대역.

    TTL(`ex`/`setex`)은 **받되 적용하지 않는다** — 만료를 흉내 내면 테스트가 시간에
    좌우된다. 여기서 볼 것은 "TTL 을 주며 저장하는가" 가 아니라 저장된 값의 왕복이다.
    """

    def __init__(self) -> None:
        self.store: dict = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def setex(self, key, ttl, value):
        self.store[key] = value

    async def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)

    async def ping(self):
        return True


def _install_fake_redis():
    from template_fill import redis_client

    fake = FakeRedis()
    redis_client.resolve_client = lambda: fake

    from template_fill import session_store

    session_store.resolve_client = redis_client.resolve_client
    return fake, session_store


class SessionStoreTest(unittest.TestCase):
    def setUp(self):
        self.fake, self.store = _install_fake_redis()

    def test_roundtrip(self):
        asyncio.run(self.store.save_session("abc", "report", {"title": "값"}))
        state = asyncio.run(self.store.load_session("abc"))
        self.assertEqual(state["values"], {"title": "값"})
        self.assertEqual(state["template_id"], "report")

    def test_missing_session_returns_empty(self):
        """없는 세션은 **예외가 아니라 빈 상태**다.

        첫 턴은 언제나 없는 세션이다. 여기서 예외를 올리면 모든 대화의 첫 턴이 실패한다.
        """
        state = asyncio.run(self.store.load_session("never-seen"))
        self.assertEqual(state["values"], {})

    def test_key_is_namespaced_and_sanitized(self):
        """세션 id 가 Redis 키를 벗어나지 못한다.

        옛 파일 세션에서는 `../../evil` 이 **디렉토리 밖 파일 쓰기**였다. Redis 로
        옮긴 지금은 키 인젝션이 같은 자리에 있다 — 구분자·와일드카드가 키 이름에
        그대로 들어가면 다른 세션을 덮거나 긁을 수 있다.
        """
        asyncio.run(self.store.save_session("../../evil", "t", {}))
        keys = list(self.fake.store)
        self.assertEqual(len(keys), 1)
        key = keys[0]
        self.assertNotIn("..", key)
        self.assertNotIn("/", key.split(":", 1)[1])  # prefix 뒤쪽에 경로 구분자 금지

    def test_empty_session_id_rejected(self):
        with self.assertRaises(ValueError):
            asyncio.run(self.store.save_session("   ", "t", {}))

    def test_blocks_survive_save(self):
        """**세션 저장은 덮어쓰기다.** 값만 저장하면 본문 블록이 지워진다.

        그래서 값 수정 경로가 항상 블록을 함께 넘긴다 — 그 계약이 저장소 쪽에서도
        성립하는지 본다.
        """
        blocks = [{"text": "본문 한 줄", "style_ref": "제목"}]
        asyncio.run(self.store.save_session("s1", "report", {"title": "값"}, blocks=blocks))
        state = asyncio.run(self.store.load_session("s1"))
        self.assertEqual(len(state["blocks"]), 1)
        self.assertEqual(state["blocks"][0]["text"], "본문 한 줄")

    def test_raw_values_default_to_values(self):
        """톤 변환 전 원본을 안 주면 값 자체가 원본이 된다.

        원본이 비어 버리면 톤을 다시 걸 때 **이미 다듬어진 문장을 또 다듬는다.**
        """
        asyncio.run(self.store.save_session("s2", "report", {"title": "다듬은 값"}))
        state = asyncio.run(self.store.load_session("s2"))
        self.assertEqual(state["raw_values"], {"title": "다듬은 값"})

    def test_end_session_clears(self):
        asyncio.run(self.store.save_session("s3", "report", {"title": "값"}))
        asyncio.run(self.store.end_session("s3"))
        state = asyncio.run(self.store.load_session("s3"))
        self.assertEqual(state["values"], {})


if __name__ == "__main__":
    unittest.main()
