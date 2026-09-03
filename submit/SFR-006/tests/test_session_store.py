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

    def test_tone_residue_is_gone(self):
        """세션에 톤 잔재(`raw_values`)를 더는 저장하지 않는다 (2026-09-02).

        006 의 톤은 2026-08-12 에 없어졌고(`archive/sfr006-tone`), 그 뒤로
        `merge_values` 가 정규화를 하지 않아 `raw_values` 는 **`values` 와 언제나 같은
        dict** 였다 — 매 턴 Redis 에 두 벌로 저장되고 HTTP 응답에도 실려 나갔다.
        (이 자리에 있던 `test_raw_values_default_to_values` 를 대체한다.)
        """
        asyncio.run(self.store.save_session("s2", "report", {"title": "값"}))
        state = asyncio.run(self.store.load_session("s2"))
        self.assertNotIn("raw_values", state)
        self.assertEqual(state["values"], {"title": "값"})

    def test_doc_hashes_accumulate(self):
        """업로드 문서 표식은 **목록**이고 여러 벌이 남는다 (2026-09-02).

        대화 중간에도 파일을 올릴 수 있게 되면서 한 세션이 문서를 여러 벌 태운다.
        문자열 하나로 두면 두 번째 문서를 태운 순간 첫 문서를 잊고, 캔버스가 둘을 계속
        실어 올 때 **번갈아 가며 다시 태운다** — 사용자가 지운 값이 되살아난다.
        """
        asyncio.run(
            self.store.save_session("h1", "report", {}, source_doc_hashes=["aaa", "bbb"])
        )
        state = asyncio.run(self.store.load_session("h1"))
        self.assertEqual(state["source_doc_hashes"], ["aaa", "bbb"])

    def test_legacy_single_hash_is_absorbed(self):
        """옛 세션(`source_doc_hash` 문자열 하나)을 **버리지 않는다.**

        목록으로 바뀌었다는 이유로 그 값을 버리면, 배포 시점에 진행 중이던 대화가 다음
        턴에 같은 문서를 다시 태우고 사용자가 지운 값을 되살린다 — 오류는 나지 않는다.
        `blocks` 를 기본값으로 흡수하는 것과 같은 규율이다.
        """
        import json

        asyncio.run(self.store.save_session("h2", "report", {"title": "값"}))
        key = [k for k in self.fake.store if k.endswith("h2")][0]
        legacy = json.loads(self.fake.store[key])
        legacy.pop("source_doc_hashes", None)
        legacy["source_doc_hash"] = "old-digest"   # 2026-09-02 이전 모양
        self.fake.store[key] = json.dumps(legacy, ensure_ascii=False)

        state = asyncio.run(self.store.load_session("h2"))
        self.assertEqual(state["source_doc_hashes"], ["old-digest"])
        # 옛 키는 남기지 않는다 — 남으면 읽는 쪽이 어느 것이 정본인지 모른다.
        self.assertNotIn("source_doc_hash", state)

    def test_doc_hashes_are_capped_oldest_first(self):
        """목록에 상한이 있고 **오래된 것부터** 버린다.

        상한이 없으면 긴 대화에서 세션 페이로드가 단조 증가한다. 버려진 표식의 문서가
        다시 오면 자동 채움이 한 번 더 돌 뿐이고(빈 항목만 채우므로 값은 안 밀린다),
        목록이 커져 저장이 실패하는 쪽이 훨씬 나쁘다.
        """
        limit = self.store._MAX_DOC_HASHES
        hashes = [f"d{i}" for i in range(limit + 5)]
        asyncio.run(self.store.save_session("h3", "report", {}, source_doc_hashes=hashes))
        state = asyncio.run(self.store.load_session("h3"))
        self.assertEqual(len(state["source_doc_hashes"]), limit)
        self.assertEqual(state["source_doc_hashes"][-1], hashes[-1])
        self.assertNotIn(hashes[0], state["source_doc_hashes"])

    def test_doc_hashes_dedupe_and_survive_garbage(self):
        """중복은 한 번만, 이상한 항목이 섞여도 **목록 전체를 버리지 않는다.**

        표식 하나가 이상하다고 나머지를 잃으면 그만큼 문서를 다시 태운다.
        """
        normalized = self.store.normalize_doc_hashes(["aaa", "", None, "aaa", 5, "bbb"])
        self.assertEqual(normalized, ["aaa", "5", "bbb"])

    def test_end_session_clears(self):
        asyncio.run(self.store.save_session("s3", "report", {"title": "값"}))
        asyncio.run(self.store.end_session("s3"))
        state = asyncio.run(self.store.load_session("s3"))
        self.assertEqual(state["values"], {})


if __name__ == "__main__":
    unittest.main()
