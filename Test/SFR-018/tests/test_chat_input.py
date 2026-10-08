"""`/chat` 직접 호출의 입력 해석(`chat_input.py`) — 번역·글다듬이·FAQ.

세 단위 모두 `question` 한 문자열에 옵션(머리말 줄 또는 JSON)과 첨부(`[입력된 문서]` 뒤)를 싣는다.
번역·글다듬이는 최상위 모듈 이름이 `chat_input` 으로 같아 파일 경로로 따로 싣는다.
"""

import importlib.util
import os
import unittest

from . import final_path

final_path.install(final_path.TEXT_POLISH_UNIT)


def _load(name: str, *rel: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(*rel))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


translate = _load("_chat_input_translate", final_path.TRANSLATION_UNIT, "chat_input.py")
polish = _load("_chat_input_polish", final_path.TEXT_POLISH_UNIT, "chat_input.py")
faq = _load("_chat_input_faq", final_path.FAQ_UNIT, "faq", "chat_input.py")


class TranslateChatInputTest(unittest.TestCase):
    def test_header_options_and_body(self):
        chat = translate.parse_chat_payload({
            "question": "target_lang: en\nregister: 문어체\ntitle: 보도자료\n\n본문 첫 줄\n둘째 줄",
            "stream": True,
        })
        self.assertEqual(chat.target_lang, "en")
        self.assertEqual(chat.title, "보도자료")
        self.assertEqual(chat.source_text, "본문 첫 줄\n둘째 줄")
        self.assertTrue(chat.stream)
        self.assertEqual(chat.source_kind, "question")

    def test_unknown_key_line_starts_body(self):
        """본문 첫 줄이 `날짜: …` 여도 옵션으로 먹히지 않는다."""
        chat = translate.parse_chat_payload({"question": "target_lang: en\n날짜: 2026-10-08\n회의록"})
        self.assertEqual(chat.source_text, "날짜: 2026-10-08\n회의록")

    def test_json_question(self):
        chat = translate.parse_chat_payload({"question": '{"target_lang": "zh", "text": "본문"}'})
        self.assertEqual((chat.target_lang, chat.source_text), ("zh", "본문"))

    def test_top_level_key_wins(self):
        chat = translate.parse_chat_payload({"question": "target_lang: en\n\n본문", "target_lang": "vi"})
        self.assertEqual(chat.target_lang, "vi")

    def test_env_default_is_last(self):
        os.environ["TRANSLATE_DEFAULT_TARGET_LANG"] = "ru"
        try:
            self.assertEqual(translate.parse_chat_payload({"question": "본문"}).target_lang, "ru")
            chat = translate.parse_chat_payload({"question": "target_lang: en\n\n본문"})
            self.assertEqual(chat.target_lang, "en")
        finally:
            os.environ.pop("TRANSLATE_DEFAULT_TARGET_LANG", None)

    def test_document_mark(self):
        """표식 뒤가 원문이고, `<doc>` 이 있으면 태그 안만 원문이다. 앞쪽은 옵션만 읽는다."""
        chat = translate.parse_chat_payload({
            "question": "target_lang: en\n번역해줘\n[입력된 문서]\n<doc name='a'>첨부 본문</doc>",
        })
        self.assertEqual((chat.target_lang, chat.source_text, chat.source_kind),
                         ("en", "첨부 본문", "uploaded"))
        chat = translate.parse_chat_payload({"question": "target_lang: en\n[입력된 문서]\n태그 없는 본문"})
        self.assertEqual(chat.source_text, "태그 없는 본문")

    def test_stream_flag_values(self):
        for value, expected in ((True, True), ("true", True), ("1", True), (1, True),
                                (False, False), ("false", False), (None, False)):
            self.assertIs(translate.parse_stream_flag(value), expected, value)


class PolishChatInputTest(unittest.TestCase):
    def test_header_options(self):
        chat = polish.parse_chat_payload({"question": "doc_type: 메일\ntone: 격식·정중\n\n다듬을 글"})
        self.assertEqual(chat.source_text, "다듬을 글")
        self.assertTrue(chat.doc_type)
        self.assertTrue(chat.tone)

    def test_title_korean_key_is_body(self):
        """`제목:` 은 옵션이 아니다 — 다듬을 글의 첫 줄을 먹지 않는다."""
        chat = polish.parse_chat_payload({"question": "제목: 안내문\n본문"})
        self.assertEqual(chat.source_text, "제목: 안내문\n본문")

    def test_document_mark(self):
        chat = polish.parse_chat_payload({"question": "이걸 다듬어줘\n[입력된 문서]\n<doc>첨부 글</doc>"})
        self.assertEqual((chat.source_text, chat.source_kind), ("첨부 글", "uploaded"))


class FaqChatInputTest(unittest.TestCase):
    def test_header_options(self):
        chat = faq.parse_chat_payload({"question": "faq_count: 5\ntitle: 휴가\n\n[입력된 문서]\n<doc>문서</doc>"})
        self.assertEqual((chat.count, chat.title, chat.source_text), ("5", "휴가", "문서"))

    def test_uploaded_top_level_wins(self):
        chat = faq.parse_chat_payload({"question": "[입력된 문서]\n질문 속 문서", "genosUploaded": "최상위 문서"})
        self.assertEqual(chat.source_text, "최상위 문서")

    def test_session_keys(self):
        self.assertEqual(faq.parse_chat_payload({"question": "q", "socketIOClientId": "s1"}).session_id, "s1")
        self.assertEqual(faq.parse_chat_payload({"question": "q", "sessionId": "s2"}).session_id, "s2")
        self.assertEqual(faq.parse_chat_payload({"question": "q"}).session_id, "")


if __name__ == "__main__":
    unittest.main()
