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
    strip_ko_particle,
    GlossaryTerm,
    clear_terms,
    exact_match,
    load_terms,
    phrase_positions,
)
from translation_pipeline.office.glossary_report import (  # noqa: E402
    build_report,
    highlight_sources,
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


class KoreanParticleTest(unittest.TestCase):
    """조사가 붙은 한국어에서도 사전을 찾는가 (2026-08-28).

    토큰이 `[가-힣]+` 라 `가맹점을` 이 한 덩어리다. 폴백이 없으면 **하이라이트보다
    앞단이 깨진다** — 방향마다 얼굴이 다르다:

    | 방향 | 어디서 | 증상 |
    |---|---|---|
    | ko→en | `match_occurrences` 0건 | 그 용어가 **프롬프트에 안 실린다**. 준수율은 1.0 |
    | en→ko | `contains_phrase` False | 제대로 옮겼는데 **준수율 0.0**, 양쪽 형광 없음 |

    두 증상이 반대 방향이라(0.0 / 1.0) 지표만 보면 서로를 가린다.
    """

    _MERCHANT = GlossaryTerm(term_source="가맹점", term_target="merchant")
    _CCRS = GlossaryTerm(term_source="ccrs", term_target="신용회복위원회")

    def tearDown(self):
        clear_terms()

    def test_ko_source_with_particle_is_matched(self):
        """ko→en — 원문에 조사가 붙어도 매칭된다(그래야 프롬프트에 실린다)."""
        clear_terms()
        load_terms("en", [self._MERCHANT])
        for text in ("가맹점을 확인한다.", "가맹점에서 정산한다.", "가맹점의 등급"):
            found = terms_for_batch([text], "en", "ko")
            self.assertEqual([t.term_source for t in found], ["가맹점"], text)

    def test_ko_target_with_particle_counts_as_used(self):
        """en→ko — `신용회복위원회를` 로 옮긴 번역이 준수율 0.0 을 받고 있었다."""
        clear_terms()
        load_terms("ko", [self._CCRS])
        units = [_Unit(0, "I love ccrs.")]
        translated = {0: "나는 신용회복위원회를 좋아한다."}
        report = build_report(units, translated, "ko", "en")
        self.assertEqual(report.compliance, 1.0)
        self.assertEqual(report.term_map, {"ccrs": "신용회복위원회"})

    def test_highlight_covers_the_word_with_its_particle(self):
        """칠하는 구간은 **문서에 실제로 적힌 글자**다 — `invoices` 규약과 같다."""
        clear_terms()
        load_terms("ko", [self._CCRS])
        units = [_Unit(0, "I love ccrs.")]
        translated = {0: "나는 신용회복위원회를 좋아한다."}
        hits = build_report(units, translated, "ko", "en").as_payload()["hits"]
        self.assertEqual(
            highlight_translations(translated, hits)[0],
            "나는 <mark>신용회복위원회를</mark> 좋아한다.",
        )

    def test_overstripping_is_blocked(self):
        """떼고 나서 2자 미만이 되면 적용하지 않는다 — `추가` 가 `추` 가 되면 안 된다."""
        for word in ("추가", "참가", "우리", "보증인", "에서"):
            self.assertEqual(strip_ko_particle(word), word, word)

    def test_exact_match_wins_over_stripping(self):
        """사전에 `신용도` 가 있으면 그쪽이 먼저다 — 절단형(`신용`)으로 새면 안 된다."""
        clear_terms()
        load_terms("en", [
            GlossaryTerm(term_source="신용", term_target="credit"),
            GlossaryTerm(term_source="신용도", term_target="credit rating"),
        ])
        found = terms_for_batch(["신용도 평가"], "en", "ko")
        self.assertEqual([t.term_source for t in found], ["신용도"])

    def test_multi_word_term_with_trailing_particle(self):
        """여러 낱말 용어는 마지막 낱말에 조사가 붙는다 — 낱말마다 폴백을 본다."""
        clear_terms()
        load_terms("en", [GlossaryTerm(term_source="가맹점 정산", term_target="merchant settlement")])
        found = terms_for_batch(["가맹점 정산을 확인한다."], "en", "ko")
        self.assertEqual([t.term_source for t in found], ["가맹점 정산"])


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
                verdict = resolve_direction(target, source, "표본")
                self.assertEqual((verdict.source.code, verdict.target.code), (source, target))

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
        verdict = resolve_direction("ko", "", "12345 67890 3.14")
        self.assertIsNone(verdict.source)
        self.assertEqual(verdict.target.code, "ko")

    def test_same_language_is_rejected(self):
        with self.assertRaises(LanguageNotSupported):
            resolve_direction("ko", "ko", "안녕하세요.")

    def test_unknown_language_is_rejected(self):
        with self.assertRaises(LanguageNotSupported):
            resolve_direction("클링온", "ko", "안녕하세요.")

    # ── 교차검증 (2026-08-18) ────────────────────────────────────────
    # 그전에는 `source_lang` 이 오면 감지를 **건너뛰었다.** 그래서 "한국어→러시아어" 를
    # 고르고 영어 문서를 올리면 실제 방향은 `en→ru` 인데 선언을 믿어 통과했다 —
    # §6 이 막으려던 바로 그 쌍이다.

    def test_declared_korean_but_english_document_is_rejected(self):
        """선언은 한국어인데 문서에 한글이 없다 → 실제로는 `en→ru` 다."""
        with self.assertRaises(LanguageNotSupported) as caught:
            resolve_direction("ru", "ko", "Hello everyone, this is an English document.")
        # 사용자가 무엇을 해야 하는지 안내문이 말해 준다 (원문 언어를 다시 고른다).
        self.assertIn("원문 언어를 확인해", str(caught.exception))

    def test_mismatch_passes_when_target_is_korean(self):
        """대상이 한국어면 축이 성립한다 — 충돌은 **보고만** 하고 막지 않는다.

        선언은 태국어인데 문서는 한국어다(태국 문자 0%). 그래도 `?→ko` 는 어느 쪽으로
        읽어도 §6 을 어기지 않으므로 막을 이유가 없다.
        """
        verdict = resolve_direction("ko", "th", "안녕하세요. 본 사업은 완료하였습니다.")
        self.assertEqual(verdict.source.code, "th")   # 선언이 정본이다
        self.assertEqual(verdict.detected, "ko")
        self.assertTrue(verdict.mismatch)             # 사실은 보고한다
        self.assertEqual(verdict.declared_share, 0.0)

    def test_same_language_declaration_is_rejected_before_mismatch(self):
        """선언과 대상이 같으면 문서가 무엇이든 그 전에 거부된다 (판정 순서)."""
        with self.assertRaises(LanguageNotSupported) as caught:
            resolve_direction("ko", "ko", "Hello, this is an English document.")
        self.assertIn("같은 언어", str(caught.exception))

    def test_korean_document_with_many_english_terms_passes(self):
        """**오차단 방지.** 라틴 문자가 최빈이어도 한글이 있으면 한국어 문서다.

        문턱을 최빈값(60%)으로 뒀을 때 이 문장이 거부됐다 — 라틴 문자가 62% 다.
        사용자에게는 우회할 방법이 없는 차단이라 판정 근거를 바꿨다.
        """
        verdict = resolve_direction("ru", "ko", "본 사업 KPI 는 ROI, TCO, SLA, API, SDK 로 관리한다.")
        self.assertEqual(verdict.source.code, "ko")
        # 최빈값은 영어지만(충돌은 사실이다) 한글이 10% 를 넘어 거부 근거가 되지 않는다.
        self.assertTrue(verdict.mismatch)
        self.assertGreater(verdict.declared_share, 0.10)

    def test_declaration_is_canonical_when_it_agrees(self):
        """감지가 선언을 **덮지 않는다** — 사용자가 고른 값이 정본이다."""
        verdict = resolve_direction("ru", "ko", "본 사업은 2026년에 완료하였습니다.")
        self.assertEqual(verdict.source.code, "ko")
        self.assertTrue(verdict.declared)
        self.assertFalse(verdict.mismatch)

    def test_detection_runs_even_when_source_declared(self):
        """선언이 있어도 감지를 돌린다 — 이게 없으면 교차검증 자체가 성립하지 않는다."""
        verdict = resolve_direction("ru", "ko", "본 사업은 완료하였습니다.")
        self.assertEqual(verdict.detected, "ko")


class GlossaryMarkTagTest(unittest.TestCase):
    """번역문 사본에 `<mark>` 을 입히는 경로 (2026-08-14 추가, 2026-08-27 태그 변경).

    **정본(`markdown`)은 건드리지 않는다** — 그 값이 `POST /download` 로 파일이 된다.
    파일에서 태그를 지우는 방식은 원문에 원래 있던 강조 태그까지 지운다.

    태그가 `<strong>` 이 아니라 `<mark>` 인 것도 여기서 지킨다 — 굵게는 원문 강조와
    화면에서 구분되지 않아 "사전 용어를 썼다" 는 표시가 되지 못한다.
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
            "Check the <mark>merchant</mark> <mark>invoice</mark>.",
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

    # ── 원문 쪽 사본 (2026-08-28) ─────────────────────────────────────────
    #
    # 화면이 원문과 번역문을 좌우로 놓고 비교하게 되면서 **양쪽에** 칠한다.
    # `hits[]` 는 좌표를 처음부터 양쪽 다 들고 있었다(`spans` / `target_spans`) —
    # 예전에는 뒤엣것만 썼다. **판정 기준은 양쪽이 같다** — 실제로 참고한 것만.

    def test_source_side_is_highlighted(self):
        units = [_Unit(0, "가맹점 청구서 확인")]
        translated = {0: "Check the merchant invoice."}
        report = build_report(units, translated, "en", "ko")
        marked = highlight_sources(units, report.as_payload()["hits"])
        self.assertEqual(marked[0], "<mark>가맹점</mark> <mark>청구서</mark> 확인")

    def test_source_side_skips_unapplied_terms(self):
        """**양쪽 다 "실제로 참고한 것" 만 칠한다.**

        요구사항 §2 가 하이라이트에 요구하는 것은 **"어떤 단어가 용어사전의 어떤 단어를
        참고하였는지"** 다. 참고하지 않은 자리는 그 관계가 없으므로 칠할 것이 없다.
        원문에 사전 용어가 나오기만 하면 칠하는 방식도 가능하지만(왼쪽에만 형광이 남아
        미준수가 화면에 드러난다) 그러면 형광이 두 가지를 뜻하게 된다.

        미준수는 `term_map_unapplied` 와 준수율이 맡는다 — **화면용이 아니라 검수용**
        이고, `term_map` 이 미적용을 담지 않는 것과 같은 기준이다.
        """
        units = [_Unit(0, "청구서 안내")]
        translated = {0: "billing guide"}   # invoice 미사용
        report = build_report(units, translated, "en", "ko")
        hits = report.as_payload()["hits"]
        self.assertEqual(highlight_sources(units, hits)[0], "청구서 안내")
        self.assertEqual(highlight_translations(translated, hits)[0], "billing guide")
        # 화면에 안 보인다고 사실이 사라지지는 않는다 — 검수 경로가 받는다
        self.assertEqual(report.term_map_unapplied, {"청구서": "invoice"})

    def test_only_the_term_is_marked_not_the_surrounding_words(self):
        """사전에 걸린 **낱말만** 칠한다 — 문장·유닛 단위가 아니다.

        `I love ccrs` 에서 `ccrs` 만 사전에 있으면 `I love` 는 그대로 남는다. 좌표가
        낱말의 문자 위치(`hits[].spans`)라 성립하는 성질이고, 같은 용어가 두 번 나오면
        **두 자리 모두** 칠해진다.
        """
        clear_terms()
        load_terms("ko", [GlossaryTerm(term_source="ccrs", term_target="신용회복위원회")])
        try:
            units = [_Unit(0, "I love ccrs and the ccrs team.")]
            translated = {0: "나는 신용회복위원회 팀을 좋아한다."}
            report = build_report(units, translated, "ko", "en")
            marked = highlight_sources(units, report.as_payload()["hits"])[0]
            self.assertEqual(
                marked, "I love <mark>ccrs</mark> and the <mark>ccrs</mark> team."
            )
        finally:
            clear_terms()
            load_terms("en", [self._MERCHANT, self._INVOICE])

    def test_source_side_does_not_mutate_units(self):
        units = [_Unit(0, "가맹점 안내")]
        report = build_report(units, {0: "merchant guide"}, "en", "ko")
        highlight_sources(units, report.as_payload()["hits"])
        self.assertEqual(units[0].text, "가맹점 안내")

    def test_overlapping_spans_merge_into_one_tag(self):
        """겹친 구간을 각각 감싸면 `<mark>A<mark>B</mark>C</mark>` 가 된다."""
        hits = [
            {"unit_id": 0, "applied": True, "target_spans": [[4, 12]]},
            {"unit_id": 0, "applied": True, "target_spans": [[4, 20]]},
        ]
        marked = highlight_translations({0: "The merchant invoice ok"}, hits)
        self.assertEqual(marked[0], "The <mark>merchant invoice</mark> ok")
        self.assertEqual(marked[0].count("<mark>"), 1)


if __name__ == "__main__":
    unittest.main()
