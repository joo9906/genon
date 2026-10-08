"""006 `/chat` 직접 호출의 입력 해석 — **no_pythonstep 판에만 있다.**

`GENON_SFR006_SOURCE=no_pythonstep` 일 때만 돈다(`run_all.py` 가 그때만 이 묶음을 고른다).
final 판에는 `chat_input` 이 없어 건너뛴다.
"""

import unittest

from tests import final_path

if final_path.SOURCE != "no_pythonstep":
    raise unittest.SkipTest("006 /chat 직접 호출은 no_pythonstep 판에만 있다")

from template_fill.chat_input import parse_chat_payload, split_document  # noqa: E402


class SessionTest(unittest.TestCase):
    def test_top_level_keys_in_order(self):
        chat = parse_chat_payload({"question": "q", "sessionId": "b", "socketIOClientId": "a"})
        self.assertEqual((chat.session_id, chat.session_source), ("a", "payload"))
        for key in ("chatId", "chat_id", "conversationId", "conversation_id"):
            self.assertEqual(parse_chat_payload({"question": "q", key: "c"}).session_id, "c", key)

    def test_genos_state(self):
        chat = parse_chat_payload({"question": "q", "genos_state": {"session_id": "g"}})
        self.assertEqual(chat.session_id, "g")

    def test_header_session_is_fallback(self):
        chat = parse_chat_payload({"question": "session_id: h\n\n제목은 A"})
        self.assertEqual((chat.session_id, chat.session_source, chat.question), ("h", "question", "제목은 A"))
        chat = parse_chat_payload({"question": "session_id: h\n\n제목은 A", "socketIOClientId": "p"})
        self.assertEqual(chat.session_id, "p")

    def test_missing(self):
        chat = parse_chat_payload({"question": "안녕"})
        self.assertEqual((chat.session_id, chat.session_source), ("", "none"))


class TemplateTest(unittest.TestCase):
    def test_top_level_wins_over_header(self):
        chat = parse_chat_payload({"question": "template_id: h\n\n안녕", "template_id": "t"})
        self.assertEqual(chat.template_id, "t")

    def test_header_aliases(self):
        for key in ("template_id", "template", "템플릿"):
            chat = parse_chat_payload({"question": f"{key}: 주간보고\n\n안녕"})
            self.assertEqual(chat.template_id, "주간보고", key)

    def test_empty_when_absent(self):
        """기본값은 `chat_direct` 가 세션·환경변수 순으로 채운다 — 여기서는 비워 둔다."""
        self.assertEqual(parse_chat_payload({"question": "안녕"}).template_id, "")


class DocumentTest(unittest.TestCase):
    def test_utterance_is_kept_with_document(self):
        """006 은 표식 앞 발화를 버리지 않는다 — "이 문서로 채우고 제목은 A" 가 한 턴에 온다."""
        chat = parse_chat_payload({"question": "제목은 A 로 해줘\n[입력된 문서]\n<doc>문서 본문</doc>"})
        self.assertEqual((chat.question, chat.document), ("제목은 A 로 해줘", "문서 본문"))

    def test_doc_tags_joined(self):
        _head, doc = split_document("[입력된 문서]\n<doc a>하나</doc>\n<DOC b>둘</DOC>")
        self.assertEqual(doc, "하나\n\n둘")

    def test_no_mark(self):
        self.assertEqual(split_document("그냥 발화"), ("그냥 발화", ""))

    def test_stream_flag(self):
        self.assertTrue(parse_chat_payload({"question": "q", "stream": "true"}).stream)
        self.assertFalse(parse_chat_payload({"question": "q"}).stream)


if __name__ == "__main__":
    unittest.main()
