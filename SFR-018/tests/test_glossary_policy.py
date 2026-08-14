"""용어사전 적용 범위 — **onprem 번역 코드서빙을 직접 태운다.**

실행: `cd SFR-018 && python -m unittest discover -s tests -t .`

## 무엇을 지키나 (2026-08-14 요구 확정)

용어사전은 **한국어·영어에만** 있다. 중국어·태국어·베트남어·러시아어는 사내 용어사전이
없으므로 LLM 만으로 번역한다. 그 사실이 세 자리에서 같은 말을 해야 한다:

1. `GET /languages` 가 화면에 알려주는 값 (`glossary_supported` / `glossary_languages`)
2. 프롬프트에 실리는 용어 목록 (`terms_for_batch`)
3. 번역 후 준수율 판정 (`build_report`)

**갈리면 예외가 나지 않는다.** 화면은 "용어사전 적용" 배지를 띄우는데 실행은 사전을 안
쓰고, 준수율은 `matched_count=0` 이라 **1.0** 으로 나온다 — 어느 계기판을 봐도 정상이다.
그래서 세 자리를 한 테스트 파일에서 함께 잰다.

## 왜 쌍으로 판정하나

대상 언어만 보면 `ru→ko` 가 통과한다. 그때 색인(`ko`)이 들고 있는 것은 **영어** 원문
용어라 러시아어 본문에 맞을 리가 없다 — 걸리지도 않을 조회를 돌리고 "준수율 1.0" 을 낸다.

원문을 감지하지 못한 경우는 막지 않는다. 조회가 빈손으로 끝날 뿐이고, 감지 실패를 이유로
기능을 끄면 숫자·기호뿐인 문서에서 사전이 통째로 사라진다(그 문서도 표 라벨은 있다).
"""

import unittest

from . import onprem_path  # noqa: F401

onprem_path.install(onprem_path.TRANSLATION_UNIT)

from translation_pipeline.common import glossary_store  # noqa: E402
from translation_pipeline.common.glossary_exact import (  # noqa: E402
    GlossaryTerm,
    clear_terms,
    exact_match,
    load_terms,
    phrase_positions,
)
from translation_pipeline.office.glossary_report import (  # noqa: E402
    build_report,
    highlight_translations,
    terms_for_batch,
)
from translation_pipeline.office.languages import (  # noqa: E402
    LanguageNotSupported,
    glossary_applies,
    glossary_languages,
    resolve_direction,
    supported_payload,
)

_TERM = GlossaryTerm(term_source="신용회복위원회", term_target="Credit Counseling Service")
_SENTENCE = "신용회복위원회 안내입니다."


class _Unit:
    """`TranslationUnit` 대신 쓰는 최소 대역 — 보고서가 읽는 세 필드만 있으면 된다."""

    def __init__(self, unit_id: int, text: str):
        self.translation_unit_id = unit_id
        self.node_id = f"n{unit_id}"
        self.text = text


class LanguageOptionTest(unittest.TestCase):
    """화면이 그리는 선택지. 프론트가 목록을 따로 들고 있지 않게 하는 것이 이 응답의 목적이다."""

    def test_six_languages_are_offered(self):
        codes = {entry["code"] for entry in supported_payload()}
        self.assertEqual(codes, {"ko", "en", "zh", "th", "vi", "ru"})

    def test_only_korean_and_english_are_flagged(self):
        flagged = sorted(e["code"] for e in supported_payload() if e["glossary_supported"])
        self.assertEqual(flagged, ["en", "ko"])

    def test_flag_and_list_say_the_same_thing(self):
        """둘이 갈리면 화면 배지와 실제 적용이 어긋난다 — 그 상태는 오류를 내지 않는다."""
        flagged = sorted(e["code"] for e in supported_payload() if e["glossary_supported"])
        self.assertEqual(flagged, sorted(glossary_languages()))


class GlossaryDirectionTest(unittest.TestCase):
    def test_korean_english_pair_applies(self):
        self.assertTrue(glossary_applies("ko", "en"))
        self.assertTrue(glossary_applies("en", "ko"))

    def test_other_languages_do_not(self):
        for source, target in (("ko", "ru"), ("ko", "zh"), ("ko", "th"), ("ko", "vi")):
            self.assertFalse(glossary_applies(source, target), f"{source}->{target}")

    def test_target_alone_is_not_enough(self):
        """`ru→ko` 는 대상만 보면 통과한다. 색인은 영어 용어를 들고 있어 맞을 리가 없다."""
        self.assertFalse(glossary_applies("ru", "ko"))
        self.assertFalse(glossary_applies("zh", "ko"))

    def test_undetected_source_is_not_blocked(self):
        """감지 실패로 기능을 끄면 표만 있는 문서에서 사전이 통째로 사라진다."""
        self.assertTrue(glossary_applies("", "en"))
        self.assertFalse(glossary_applies("", "ru"))


class GlossaryGateTest(unittest.TestCase):
    """색인에 용어가 있어도 **적용 대상 방향이 아니면 쓰지 않는다.**

    사전 파일에 실수로 다른 언어 항목이 들어와도 프롬프트에 실리지 않아야 한다 —
    "그 언어는 LLM 만으로 번역" 이 배포 파일 내용에 좌우되면 그건 정책이 아니다.
    """

    def setUp(self):
        clear_terms()
        # 두 언어 색인에 같은 용어를 넣는다. 게이트가 없으면 둘 다 걸린다.
        load_terms("en", [_TERM])
        load_terms("ru", [_TERM])

    def tearDown(self):
        clear_terms()

    def test_prompt_terms_only_for_supported_pair(self):
        self.assertEqual([t.term_source for t in terms_for_batch([_SENTENCE], "en", "ko")],
                         ["신용회복위원회"])
        self.assertEqual(terms_for_batch([_SENTENCE], "ru", "ko"), [])

    def test_report_is_empty_for_unsupported_pair(self):
        units = [_Unit(0, _SENTENCE)]
        translated = {0: "안내입니다"}   # 지정 용어를 안 썼다 — 대상이면 미준수다

        supported = build_report(units, translated, "en", "ko")
        self.assertEqual(supported.matched_count, 1)
        self.assertEqual(supported.applied_count, 0)

        unsupported = build_report(units, translated, "ru", "ko")
        self.assertEqual(unsupported.matched_count, 0)
        self.assertEqual(unsupported.hits, [])
        # 잴 것이 없으면 1.0 이다. **그 1.0 은 "잘 지켰다" 가 아니다** — 응답의
        # `glossary.source.reason` 이 `not_applicable` 로 그 사실을 따로 말한다.
        self.assertEqual(unsupported.compliance, 1.0)


class GlossaryHighlightTest(unittest.TestCase):
    """프론트 하이라이트 계약 (2026-08-14 추가 — 요구사항 §2).

    요구는 "용어사전을 **참고한** 단어에 대해서만 표시" 다. 그전에는 `term_map` 이
    원문에 사전 용어가 나오기만 하면 담아서, 번역문이 그 용어를 **안 썼는데도**
    프론트가 하이라이트하게 돼 있었다 — 오류를 내지 않고 화면에만 틀리게 나온다.
    """

    _MERCHANT = GlossaryTerm(term_source="가맹점", term_target="merchant")
    _SETTLE = GlossaryTerm(term_source="정산", term_target="settlement")

    def setUp(self):
        clear_terms()
        load_terms("en", [self._MERCHANT, self._SETTLE])

    def tearDown(self):
        clear_terms()

    def _report(self):
        units = [
            _Unit(0, "가맹점 정산 내역과 가맹점 등급을 확인한다."),   # 가맹점이 두 번
            _Unit(1, "정산 주기는 매월 말일이다."),
        ]
        translated = {
            0: "Check the merchant settlement details and merchant grade.",
            1: "The payout cycle is the last day of each month.",   # settlement 미사용
        }
        return units, build_report(units, translated, "en", "ko")

    def test_term_map_holds_only_applied_terms(self):
        """미적용 용어가 하이라이트 기본형에 섞이면 화면이 거짓말을 한다."""
        units = [_Unit(0, "정산 주기는 매월 말일이다.")]
        report = build_report(units, {0: "The payout cycle is monthly."}, "en", "ko")
        self.assertEqual(report.term_map, {})
        self.assertEqual(report.term_map_unapplied, {"정산": "settlement"})
        self.assertEqual(report.compliance, 0.0)

    def test_unapplied_terms_are_kept_not_dropped(self):
        """준수율 숫자만으로는 **어느 용어가** 안 지켜졌는지 알 수 없다."""
        _units, report = self._report()
        self.assertEqual(report.term_map["가맹점"], "merchant")
        self.assertIn("정산", report.term_map_unapplied)

    def test_spans_point_at_the_real_occurrences(self):
        """문자열 검색으로 자리를 찾으면 같은 단어의 걸린 자리와 아닌 자리가 안 갈린다."""
        units, report = self._report()
        source = units[0].text
        spans = {hit["term_source"]: hit["spans"]
                 for hit in report.hits if hit["unit_id"] == 0}
        self.assertEqual([source[s:e] for s, e in spans["가맹점"]], ["가맹점", "가맹점"])
        self.assertEqual([source[s:e] for s, e in spans["정산"]], ["정산"])

    def test_repeat_in_one_unit_does_not_move_compliance(self):
        """`hits` 는 (용어×유닛) 하나로 유지된다 — 등장마다 쪼개면 분모가 조용히 바뀐다."""
        _units, report = self._report()
        self.assertEqual(report.matched_count, 3)   # (가맹점,u0) (정산,u0) (정산,u1)
        self.assertEqual(report.applied_count, 2)
        self.assertEqual(len(report.hits), report.matched_count)

    def test_applied_flag_and_term_map_agree(self):
        """둘이 갈리면 프론트가 어느 쪽을 믿느냐에 따라 화면이 달라진다."""
        _units, report = self._report()
        for hit in report.hits:
            target = report.term_map.get(hit["term_source"])
            if hit["applied"]:
                self.assertEqual(target, hit["term_target"], hit)
            else:
                self.assertEqual(
                    report.term_map_unapplied.get(hit["term_source"]),
                    hit["term_target"],
                    hit,
                )

    def test_payload_carries_both_maps(self):
        """응답 형태가 계약이다 — 키가 빠지면 프론트가 조용히 예전 동작으로 돌아간다."""
        _units, report = self._report()
        payload = report.as_payload()
        for key in ("term_map", "term_map_unapplied", "hits", "compliance"):
            self.assertIn(key, payload)
        self.assertTrue(all("spans" in hit for hit in payload["hits"]))


class GlossaryAdminApiLoadTest(unittest.TestCase):
    """용어사전을 **GenOS AI 드라이브 용어사전 API** 에서 받는다 (2026-08-14 전환).

    플랫폼 용어사전은 `{용어명, 설명}` 이고 번역어 칸이 따로 없다(`용어사전.md`).
    사내 운용이 **설명 칸에 영문 용어**를 적기로 확정돼서 그 매핑을 적재부가 쥔다.
    """

    def setUp(self):
        clear_terms()

    def tearDown(self):
        clear_terms()

    def _load(self, items, **kwargs):
        """`httpx.AsyncClient` 를 대역으로 바꿔 적재를 태운다 (네트워크 없음)."""
        import asyncio

        import httpx

        def handler(request):
            self.assertEqual(request.headers.get("x-genos-workspace-id"), "ws-1")
            self.assertEqual(request.headers.get("authorization"), "Bearer tok")
            self.assertIn("/data/ai-drive/drive-9/glossary/terms", str(request.url))
            page = int(dict(request.url.params).get("pg", 1))
            return httpx.Response(200, json={"items": items if page == 1 else []})

        transport = kwargs.get("transport") or httpx.MockTransport(handler)
        original = httpx.AsyncClient
        httpx.AsyncClient = lambda **kw: original(transport=transport, **kw)
        try:
            return asyncio.run(glossary_store.load_from_admin_api(
                "https://admin.example", "drive-9", "ws-1", "tok"
            ))
        finally:
            httpx.AsyncClient = original

    def test_term_and_description_become_a_translation_pair(self):
        status = self._load([{"term": "매출채권", "description": "accounts receivable"}])
        self.assertTrue(status["loaded"])
        self.assertEqual(status["source"], "api")
        terms, _ = exact_match("매출채권 잔액", "en")
        self.assertEqual([(t.term_source, t.term_target) for t in terms],
                         [("매출채권", "accounts receivable")])

    def test_pairs_are_indexed_in_both_directions(self):
        """`ko→en` 만 싣던 시절에는 `en→ko` 가 **준수율 1.0** 으로 나갔다 —
        지키지 못한 게 아니라 지킬 것이 없다고 보고되는 상태였다."""
        self._load([{"term": "정산", "description": "settlement"}])
        to_english, _ = exact_match("정산 내역", "en")
        to_korean, _ = exact_match("the settlement details", "ko")
        self.assertEqual([t.term_target for t in to_english], ["settlement"])
        self.assertEqual([t.term_target for t in to_korean], ["정산"])

    def test_spec_rules_filter_bad_rows(self):
        """플랫폼이 업로드 시 거르는 규칙과 같은 것을 적재에서도 본다."""
        status = self._load([
            {"term": "정상", "description": "valid"},
            {"term": "  ", "description": "빈 용어명"},
            {"term": "가" * 31, "description": "30자 초과"},
            {"term": "금지/문자", "description": "금지문자"},
            {"term": "번역어없음", "description": "   "},
            {"term": "정상", "description": "중복"},
            "문자열은 항목이 아니다",
        ])
        # 살아남는 것은 첫 행 하나뿐이다 (중복은 처음 것만)
        self.assertEqual(status["languages"], {"en": 1, "ko": 1})

    def test_missing_settings_do_not_crash(self):
        """설정이 없으면 **용어사전 없이 번역한다.** 기동을 막지 않는다."""
        import asyncio

        status = asyncio.run(glossary_store.load_from_admin_api("", "", "", ""))
        self.assertFalse(status["loaded"])
        self.assertEqual(status["reason"], "not_configured")

    def test_http_error_is_reported_not_raised(self):
        """조회 실패가 예외로 올라가면 기동이 죽는다. 사유에 상태코드를 남긴다."""
        import httpx

        transport = httpx.MockTransport(lambda request: httpx.Response(403, json={}))
        status = self._load([], transport=transport)
        self.assertFalse(status["loaded"])
        self.assertEqual(status["reason"], "fetch_failed_403")

    def test_language_status_separates_missing_from_unfetched(self):
        """"용어를 채울 일" 과 "아예 못 받은 일" 은 관리자가 할 일이 다르다."""
        self._load([{"term": "정산", "description": "settlement"}])
        self.assertEqual(glossary_store.language_status("en")["reason"], "ok")
        self.assertEqual(glossary_store.language_status("th")["reason"], "language_missing")


class KoreanAxisTest(unittest.TestCase):
    """번역 방향은 **한국어를 한쪽에 둔 쌍만** 지원한다 (요구사항 §6).

    화면이 선택지를 잘못 그려도 서버가 막아야 한다 — 비한국어 쌍은 품질 검증 대상 밖이라
    열어두면 검증 안 된 경로가 운영에서 조용히 쓰인다.
    """

    def test_korean_axis_pairs_pass(self):
        for target, source in (("en", "ko"), ("ko", "en"), ("ru", "ko"), ("ko", "th")):
            with self.subTest(direction=f"{source}->{target}"):
                src, tgt = resolve_direction(target, source, "표본")
                self.assertEqual((src.code, tgt.code), (source, target))

    def test_non_korean_pair_is_rejected(self):
        with self.assertRaises(LanguageNotSupported):
            resolve_direction("ru", "en", "Hello everyone.")

    def test_non_korean_pair_is_rejected_by_detection(self):
        """원문을 안 줘도 감지해서 막는다 — 화면이 원문 선택을 빠뜨려도 뒷문이 아니다."""
        with self.assertRaises(LanguageNotSupported):
            resolve_direction("ru", "", "Hello everyone, this is a test document.")

    def test_undetectable_source_to_non_korean_is_rejected(self):
        """감지 불가 + 비한국어 대상 = **한국어 축을 증명할 수 없다** (2026-08-14).

        그대로 통과시키면 숫자만 든 문서로 `en→ru` 를 통과시키는 뒷문이 된다.
        """
        with self.assertRaises(LanguageNotSupported):
            resolve_direction("ru", "", "12345 67890 3.14")

    def test_undetectable_source_to_korean_passes(self):
        """대상이 한국어면 축이 이미 성립한다 — 표만 있는 문서를 막지 않는다."""
        source, target = resolve_direction("ko", "", "12345 67890 3.14")
        self.assertIsNone(source)
        self.assertEqual(target.code, "ko")

    def test_same_language_is_rejected(self):
        with self.assertRaises(LanguageNotSupported):
            resolve_direction("ko", "ko", "안녕하세요.")

    def test_unknown_language_is_rejected(self):
        with self.assertRaises(LanguageNotSupported):
            resolve_direction("클링온", "ko", "안녕하세요.")


class GlossaryStrongTagTest(unittest.TestCase):
    """번역문 사본에 `<strong>` 을 입히는 경로 (2026-08-14 추가).

    **정본(`markdown`)은 건드리지 않는다** — 그 값이 `POST /download` 로 파일이 된다.
    파일에서 태그를 지우는 방식은 원문에 원래 있던 `<strong>` 까지 지운다.
    """

    _MERCHANT = GlossaryTerm(term_source="가맹점", term_target="merchant")
    _INVOICE = GlossaryTerm(term_source="청구서", term_target="invoice")

    def setUp(self):
        clear_terms()
        load_terms("en", [self._MERCHANT, self._INVOICE])

    def tearDown(self):
        clear_terms()

    def test_positions_follow_the_same_matching_rule_as_compliance(self):
        """활용형이 준수로 판정되면 위치도 나와야 한다 — 아니면 "썼다는데 어딘지 모른다"."""
        self.assertEqual(phrase_positions("We sent two invoices.", "invoice"), [(12, 20)])
        # 돌려주는 구간은 **번역문에 실제로 적힌 글자**다 (사전 표기가 아니다)
        self.assertEqual("We sent two invoices."[12:20], "invoices")

    def test_partial_word_is_not_a_position(self):
        """`cat` 이 `category` 안에서 걸리면 엉뚱한 자리에 태그가 붙는다."""
        self.assertEqual(phrase_positions("category of invoices", "cat"), [])

    def test_highlight_wraps_applied_terms_only(self):
        # 원문에 조사를 붙이지 않는다 — `청구서를` 은 한 토큰이라 사전의 `청구서` 와
        # 매칭되지 않는다(한국어 조사 분리는 이 모듈 밖이라고 `glossary_exact` 가
        # 명시한 한계다). 하이라이트가 아니라 **매칭**의 성질이라 여기서 다루지 않는다.
        units = [_Unit(0, "가맹점 청구서 확인")]
        translated = {0: "Check the merchant invoice."}
        report = build_report(units, translated, "en", "ko")
        marked = highlight_translations(translated, report.as_payload()["hits"])
        self.assertEqual(
            marked[0],
            "Check the <strong>merchant</strong> <strong>invoice</strong>.",
        )

    def test_source_map_is_not_mutated(self):
        """정본을 그대로 두는 것이 이 설계의 요점이다."""
        units = [_Unit(0, "가맹점 안내")]
        translated = {0: "merchant guide"}
        report = build_report(units, translated, "en", "ko")
        highlight_translations(translated, report.as_payload()["hits"])
        self.assertEqual(translated[0], "merchant guide")

    def test_unapplied_terms_get_no_tag(self):
        """번역문이 안 쓴 용어는 감쌀 자리가 없다."""
        units = [_Unit(0, "청구서 안내")]
        translated = {0: "billing guide"}   # invoice 미사용
        report = build_report(units, translated, "en", "ko")
        marked = highlight_translations(translated, report.as_payload()["hits"])
        self.assertEqual(marked[0], "billing guide")

    def test_overlapping_spans_merge_into_one_tag(self):
        """겹친 구간을 각각 감싸면 `<strong>A<strong>B</strong>C</strong>` 가 된다."""
        hits = [
            {"unit_id": 0, "applied": True, "target_spans": [[4, 12]]},
            {"unit_id": 0, "applied": True, "target_spans": [[4, 20]]},
        ]
        marked = highlight_translations({0: "The merchant invoice ok"}, hits)
        self.assertEqual(marked[0], "The <strong>merchant invoice</strong> ok")
        self.assertEqual(marked[0].count("<strong>"), 1)


if __name__ == "__main__":
    unittest.main()
