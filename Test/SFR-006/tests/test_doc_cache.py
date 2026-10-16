"""세션별 문서 캐시 — 키 조회·최신 폴백·상한·세션 종료 시 삭제."""

import asyncio
import unittest

from . import final_path  # noqa: F401 - import 부작용으로 sys.path 를 세운다
from .test_session_store import FakeRedis


def _setup():
    from template_fill import doc_cache, redis_client, session_store

    fake = FakeRedis()
    redis_client.resolve_client = lambda: fake
    doc_cache.resolve_client = redis_client.resolve_client
    session_store.resolve_client = redis_client.resolve_client
    return fake, doc_cache, session_store


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class DocCacheTest(unittest.TestCase):
    def setUp(self):
        self.fake, self.cache, self.sessions = _setup()

    def test_key_hit_and_latest_fallback(self):
        _run(self.cache.save_document("s1", "aaa", "문서 A", True))
        _run(self.cache.save_document("s1", "bbb", "문서 B", False))
        self.assertEqual(_run(self.cache.load_document("s1", "aaa")),
                         {"found": True, "text": "문서 A", "scan": True})
        # 첨부 없는 턴(키 없음)은 가장 최근 문서를 받는다
        self.assertEqual(_run(self.cache.load_document("s1", ""))["text"], "문서 B")
        self.assertFalse(_run(self.cache.load_document("s1", "zzz"))["found"])
        self.assertFalse(_run(self.cache.load_document("other", ""))["found"])

    def test_same_key_updates_and_limit(self):
        for i in range(8):
            _run(self.cache.save_document("s1", f"k{i}", f"본문{i}", False))
        self.assertFalse(_run(self.cache.load_document("s1", "k0"))["found"])
        self.assertTrue(_run(self.cache.load_document("s1", "k7"))["found"])
        _run(self.cache.save_document("s1", "k7", "새 본문", False))
        self.assertEqual(_run(self.cache.load_document("s1", ""))["text"], "새 본문")

    def test_oversize_and_empty_are_not_saved(self):
        from template_fill.config import Config

        big = "가" * (Config.DOC_CACHE_MAX_CHARS + 1)
        self.assertFalse(_run(self.cache.save_document("s1", "k", big, False)))
        self.assertFalse(_run(self.cache.save_document("s1", "k", "  ", False)))
        self.assertFalse(_run(self.cache.save_document("", "k", "본문", False)))

    def test_end_session_removes_cache(self):
        _run(self.cache.save_document("s1", "k", "본문", False))
        _run(self.sessions.end_session("s1"))
        self.assertFalse(_run(self.cache.load_document("s1", ""))["found"])


if __name__ == "__main__":
    unittest.main()
