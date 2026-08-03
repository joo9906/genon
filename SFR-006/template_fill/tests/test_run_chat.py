"""run_chat 멀티턴 흐름 통합 테스트 — mock 추출기로 LLM 없이 검증.

시나리오: 템플릿 스캔 → 1턴에서 일부 값 제공 → 2턴에서 나머지 제공 →
ready_for_download 전환 → fill_template 로 실제 초안 생성까지.
"""

import asyncio
import os
import tempfile
import unittest

from template_fill.config import Config
from template_fill.hwpx_fields import fill_template, scan_fields
from template_fill.session_store import load_session, save_session

from .fixtures import build_sample_hwpx


async def _collect(agen):
    return [event async for event in agen]


class RunChatMockTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        template_dir = os.path.join(self._tmp.name, "templates")
        os.makedirs(template_dir)
        with open(os.path.join(template_dir, "report.hwpx"), "wb") as f:
            f.write(build_sample_hwpx())

        self._orig = (Config.TEMPLATE_DIR, Config.SESSION_DIR, Config.LLM_MODE)
        Config.TEMPLATE_DIR = template_dir
        Config.SESSION_DIR = os.path.join(self._tmp.name, "sessions")
        Config.LLM_MODE = "mock"

    def tearDown(self):
        Config.TEMPLATE_DIR, Config.SESSION_DIR, Config.LLM_MODE = self._orig
        self._tmp.cleanup()

    def _turn(self, question: str, session_id: str = "sess-1"):
        from template_fill.run_chat import run

        data = {
            "question": question,
            "genos_state": {"session_id": session_id},
            "overrideConfig": {"vars": {"template_fill_template_id": "report"}},
        }
        events = asyncio.run(_collect(run(data)))
        self.assertEqual(events[-1]["event"], "result")  # result 필수 (5.2절)
        return events[-1]["data"]

    def test_multiturn_until_ready(self):
        # 1턴: 제목만 제공 → 아직 부족
        result = self._turn("title: 생성형 AI 구축 사업 추진")
        self.assertIsNone(result["error"])
        self.assertIn("title", result["fields_filled"])
        self.assertIn("memo", result["fields_missing"])
        self.assertFalse(result["ready_for_download"])

        # 2턴: 나머지 제공 → 세션 누적으로 ready (manager 는 템플릿에 기입력)
        result = self._turn("시행일자 입력: 2026. 8. 3.\nmemo: 특이사항 없음")
        self.assertTrue(result["ready_for_download"])
        self.assertEqual(result["fields_missing"], [])

        # 다운로드 단계와 동일한 경로: 세션 값으로 실제 초안 생성
        session = load_session("sess-1")
        with open(os.path.join(Config.TEMPLATE_DIR, "report.hwpx"), "rb") as f:
            fill = fill_template(f.read(), session["values"])
        specs = {s.name: s for s in scan_fields(fill.hwpx_bytes)}
        self.assertEqual(specs["title"].current_value, "생성형 AI 구축 사업 추진")
        self.assertTrue(all(s.filled for s in specs.values()))

    def test_template_not_found_error(self):
        from template_fill.run_chat import run

        data = {
            "question": "안녕하세요",
            "genos_state": {"session_id": "sess-2"},
            "overrideConfig": {"vars": {"template_fill_template_id": "없는템플릿"}},
        }
        events = asyncio.run(_collect(run(data)))
        result = events[-1]["data"]
        self.assertIsNotNone(result["error"])
        self.assertEqual(result["error"]["error_code"], "02-00020003")

    def test_value_correction_overwrites(self):
        self._turn("title: 첫 제목", session_id="sess-3")
        result = self._turn("title: 고친 제목", session_id="sess-3")
        self.assertEqual(result["field_values"]["title"], "고친 제목")


class SessionStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = Config.SESSION_DIR
        Config.SESSION_DIR = self._tmp.name

    def tearDown(self):
        Config.SESSION_DIR = self._orig
        self._tmp.cleanup()

    def test_roundtrip(self):
        save_session("abc", "report", {"title": "값"})
        state = load_session("abc")
        self.assertEqual(state["values"], {"title": "값"})
        self.assertEqual(state["template_id"], "report")

    def test_missing_session_returns_empty(self):
        state = load_session("never-seen")
        self.assertEqual(state["values"], {})

    def test_path_traversal_sanitized(self):
        save_session("../../evil", "t", {})
        for name in os.listdir(Config.SESSION_DIR):
            self.assertNotIn("..", name)


if __name__ == "__main__":
    unittest.main()
