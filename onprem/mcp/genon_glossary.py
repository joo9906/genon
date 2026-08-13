# =====================================================================================
# genon_glossary — 사내 용어사전 조회 MCP 도구 (area 01)
#
# **이 파일 하나가 등록 단위다.** GenOS MCP 는 소스 파일 한 개를 받아 실행하며,
# `mcp` 객체를 런타임이 전역으로 주입한다. 그래서 패키지로 쪼갤 수 없다.
#
# **모든 최상위 심볼에 `GL` 접두어를 붙였다.** 한 서버에 다른 도구 파일이 함께 로드될 수
# 있어서다.
#
# ## 지금 무엇이 있고 무엇이 없나
#
# **1단계(완전 일치 + 활용형 정규화)만 있다.** 2단계(Weaviate + 임베딩 게이트웨이)는
# 폐쇄망 벡터DB 가용성이 확인되지 않아 보류다.
#
# **2단계 폴백이 없다는 것이 중요하다.** 사전이 없거나 캐시 상한을 넘으면 그 언어는
# **용어사전 없이** 번역된다. 그래서 `glossary_status` 가 적재 상태를 그대로 노출하고,
# `glossary_lookup` 도 `enabled=false` + `reason` 을 낸다 — 호출부가 "용어사전이 적용된
# 결과" 와 "적용되지 않은 결과" 를 구분할 수 있어야 한다.
#
# ## 준수율(compliance)은 여기 없다 — 의도한 것이다
#
# 준수율 계산은 번역 파이프라인의 `TranslationUnit` 객체를 받는다. JSON 으로 넘길 수 없고,
# MCP 용으로 다시 구현하면 **같은 준수율 규칙이 두 벌**이 된다. 번역 코드서빙 응답
# (`glossary.compliance`)에 그대로 둔다.
#
# ## 적재는 기동 시 볼륨 파일에서 한다
#
# `TRANSLATE_GLOSSARY_PATH`(JSON/CSV). Weaviate 에 묶지 않았으므로 벡터DB 가 열리면
# 적재 경로만 갈아 끼우면 되고 매칭 코드는 그대로다.
#
# 비표준 패키지를 쓰지 않는다 (stdlib 만).
# =====================================================================================

import csv
import json
import logging
import os
import re
from dataclasses import dataclass

# ── logging_utils.py ─────────────────────────────
# 3.8절 기록 허용 필드. 이 목록을 늘리려면 가이드 근거가 있어야 한다.
GLALLOWED_FIELDS = frozenset(
    {
        "event",
        "trace_id",
        "request_id",
        "resource_id",
        "status",
        "duration_ms",
        "item_count",
        "upstream_status",
        "error_code",
        "error_type",
    }
)

_GLlog = logging.getLogger("translation_pipeline")


def glconfigure_logging(level: str = "INFO") -> None:
    """코드 서빙 진입점에서 한 번 호출한다 (워크플로우 영역은 GenOS 가 이미 설정한다).

    핸들러가 이미 있으면 basicConfig 는 아무것도 하지 않으므로 중복 호출이 안전하다.
    stdout 으로 직접 쓰는 print 는 금지(3.10절)이고, 여기서도 쓰지 않는다.
    """
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))


def _GLprepare(message: str, event: str, fields: dict) -> tuple[str, dict]:
    extra: dict = {"event": event}
    dropped = []
    for key, value in fields.items():
        if key == "event" or key not in GLALLOWED_FIELDS:
            dropped.append(key)
            continue
        if value is not None:
            extra[key] = value
    if dropped:
        # 값은 남기지 않고 필드명만 — 호출부 실수를 드러내되 내용은 새지 않게
        message = f"{message} [dropped_fields={','.join(sorted(dropped))}]"
    return message, extra


def gllog_info(message: str, *, event: str, **fields) -> None:
    text, extra = _GLprepare(message, event, fields)
    _GLlog.info(text, extra=extra)


def gllog_warning(message: str, *, event: str, **fields) -> None:
    text, extra = _GLprepare(message, event, fields)
    _GLlog.warning(text, extra=extra)


def gllog_error(message: str, *, event: str, **fields) -> None:
    text, extra = _GLprepare(message, event, fields)
    _GLlog.error(text, extra=extra)


# ── glossary_exact.py ─────────────────────────────
# 캐시 상한. 초과하면 그 언어의 용어사전 적용을 비활성화한다.
_GLDEFAULT_MAX_CACHED_TERMS = 300_000

# 용어 하나가 가질 수 있는 최대 단어 수. 이보다 긴 항목은 "용어"가 아니라 문장/조항으로
# 보고 제외한다 — 정확 매칭될 확률이 낮고 오탐만 늘린다.
_GLMAX_TERM_WORDS = 6


@dataclass(frozen=True, slots=True)
class GLGlossaryTerm:
    term_source: str
    term_target: str
    domain: str = ""


# 영어 단어를 단수/기본형에 가깝게 되돌리는 규칙. 완전한 표제어 추출은 아니지만
# 용어사전 매칭 목적에는 실용적이다. 순서가 중요하다(구체적인 패턴 먼저).
_GLEN_SUFFIX_RULES: list = [
    ("ies", "y"),    # categories -> category
    ("ves", "f"),    # knives -> knife
    ("xes", "x"),    # boxes -> box
    ("ches", "ch"),  # matches -> match
    ("shes", "sh"),  # dishes -> dish
    ("s", ""),       # invoices -> invoice (가장 일반적 — 마지막에 검사)
]

# 지원 6개 언어의 글자를 토큰으로 잡는다. 원본 실험은 영어·한국어만 다뤘지만
# 이 배포 단위는 중국어·태국어·베트남어·러시아어 사전도 받는다.
#   - 한글 / 라틴(베트남어 성조 포함) / 키릴 / 한자 / 태국 문자
#   - 태국어·중국어는 띄어쓰기가 없어 토큰이 길게 잡힌다 → 그 언어 사전은
#     사실상 완전 일치만 걸린다 (한계로 문서화).
_GLTOKEN_RE = re.compile(
    r"[A-Za-zÀ-ɏ]+"      # 라틴 + 확장(베트남어)
    r"|[가-힣]+"            # 한글
    r"|[Ѐ-ԯ]+"            # 키릴(러시아어)
    r"|[一-鿿]+"            # 한자(중국어)
    r"|[฀-๿]+",           # 태국 문자
    re.UNICODE,
)
_GLASCII_WORD_RE = re.compile(r"[A-Za-z]+")

# target_lang -> { 정규화된 첫 단어: [(정규화된 전체 단어 튜플, GlossaryTerm), ...] }
# 각 리스트는 단어 수 내림차순 — 같은 첫 단어를 공유하는 후보 중 더 긴 용어
# ("invoice number")가 짧은 용어("invoice")보다 먼저 매칭된다.
_GLINDEX: dict = {}
_GLDISABLED_LANGS: set = set()


def _GLnormalize_en(word: str) -> str:
    """영어 단어를 규칙 기반으로 단수/기본형에 가깝게 정규화한다.

    영어가 아닌 토큰은 소문자화만 하고 통과시킨다 (한국어 조사 분리는 형태소 분석기가
    필요한 영역이며 이 모듈의 책임 범위 밖이다).
    """
    if not _GLASCII_WORD_RE.fullmatch(word):
        return word.lower()
    lowered = word.lower()
    for suffix, replacement in _GLEN_SUFFIX_RULES:
        # 과교정 방지: 규칙 적용 후 2자 미만이 되면 적용하지 않는다.
        if lowered.endswith(suffix) and len(lowered) - len(suffix) + len(replacement) >= 2:
            return lowered[: -len(suffix)] + replacement
    return lowered


def glload_terms(
    target_lang: str,
    terms: list,
    *,
    max_cached_terms: int = _GLDEFAULT_MAX_CACHED_TERMS,
) -> bool:
    """용어사전을 첫 토큰 역색인으로 메모리에 캐시한다.

    매 번역 요청마다 부르는 함수가 아니다 — 기동 시 1회, 그리고 관리자가
    `POST /glossary/reload` 를 호출할 때만 부른다.

    Returns:
        캐시 성공 여부. False 면 그 언어는 용어사전 없이 번역된다.
    """
    if len(terms) > max_cached_terms:
        _GLINDEX.pop(target_lang, None)
        _GLDISABLED_LANGS.add(target_lang)
        # 3.8절: 용어·언어 값은 메시지에 끼워 넣지 않고 허용 필드로만 남긴다
        gllog_warning(
            "용어 수가 캐시 상한을 초과해 용어사전 적용을 비활성화",
            event="glossary_disabled_over_limit",
            resource_id=f"glossary:{target_lang}",
            item_count=len(terms),
            status="disabled",
        )
        return False

    index: dict = {}
    skipped_long = 0
    for term in terms:
        if not term.term_source or not term.term_source.strip():
            continue
        words = term.term_source.split()
        if len(words) > _GLMAX_TERM_WORDS:
            skipped_long += 1
            continue
        normalized = tuple(_GLnormalize_en(word) for word in words)
        index.setdefault(normalized[0], []).append((normalized, term))

    # 같은 첫 단어 안에서 긴 용어를 먼저 검사 (최장 일치 우선)
    for bucket in index.values():
        bucket.sort(key=lambda item: len(item[0]), reverse=True)

    _GLINDEX[target_lang] = index
    _GLDISABLED_LANGS.discard(target_lang)
    gllog_info(
        "용어사전 색인 구성 완료",
        event="glossary_index_built",
        resource_id=f"glossary:{target_lang}",
        item_count=len(terms),
        # 길어서 제외된 항목이 있으면 조용히 넘기지 않는다
        status=f"skipped_long={skipped_long}",
    )
    return True


def glis_disabled(target_lang: str) -> bool:
    """상한 초과로 비활성화된 언어인지 (응답·로그에 노출하기 위한 조회)."""
    return target_lang in _GLDISABLED_LANGS


def glterm_count(target_lang: str) -> int:
    """색인에 올라간 용어 수 (`GET /glossary` 상태 표시용)."""
    return sum(len(bucket) for bucket in _GLINDEX.get(target_lang, {}).values())


def glclear_terms(target_lang: str = None) -> None:
    """캐시 해제. target_lang 이 None 이면 전체를 비운다 (재적재용)."""
    if target_lang is None:
        _GLINDEX.clear()
        _GLDISABLED_LANGS.clear()
    else:
        _GLINDEX.pop(target_lang, None)
        _GLDISABLED_LANGS.discard(target_lang)


def glcontains_phrase(text: str, phrase: str) -> bool:
    """`phrase` 가 `text` 안에 **토큰 단위로** 들어 있는가.

    준수 여부 판정(`glossary_report.py`)이 쓴다. 단순 substring 대신 토큰 비교를 쓰는
    이유는 매칭과 같다 — "cat"이 "category" 안에서 걸리는 오탐을 막는다.
    정규화(`_normalize_en`)를 거치므로 지정 용어가 문장에 맞게 활용돼도
    (`invoice` → `invoices`) 준수로 본다. 사전이 요구하는 것은 "그 용어를 썼는가"이지
    "글자가 똑같은가"가 아니다.
    """
    phrase_tokens = tuple(
        _GLnormalize_en(match.group(0)) for match in _GLTOKEN_RE.finditer(phrase or "")
    )
    if not phrase_tokens:
        return False
    text_tokens = [_GLnormalize_en(match.group(0)) for match in _GLTOKEN_RE.finditer(text or "")]
    span = len(phrase_tokens)
    return any(
        tuple(text_tokens[start: start + span]) == phrase_tokens
        for start in range(len(text_tokens) - span + 1)
    )


def glexact_match(text: str, target_lang: str) -> tuple:
    """활용형(복수형 등)까지 정규화해 사전과 매칭한다.

    첫 토큰 역색인을 쓰므로 사전에 등록된 용어의 최대 단어 수가 커져도 스캔 비용이
    늘지 않는다.

    Returns:
        (매칭된 GlossaryTerm 목록, 매칭 구간이 공백으로 치환된 나머지 텍스트).
        나머지 텍스트는 지금 쓰이지 않는다 — 2단계(임베딩 후보 추출)의 입력이었고,
        2단계를 병합할 때 그대로 쓰려고 계약을 유지한다.
    """
    index = _GLINDEX.get(target_lang)
    if not index or not text:
        return [], text

    tokens = [(m.group(0), m.start(), m.end()) for m in _GLTOKEN_RE.finditer(text)]
    if not tokens:
        return [], text

    normalized_tokens = [_GLnormalize_en(token[0]) for token in tokens]

    found: list = []
    seen: set = set()
    consumed_spans: list = []

    position = 0
    token_count = len(tokens)
    while position < token_count:
        bucket = index.get(normalized_tokens[position])
        if not bucket:
            position += 1
            continue

        matched_len = 0
        for normalized_words, term in bucket:  # 긴 후보부터 (최장 일치 우선)
            span_len = len(normalized_words)
            if position + span_len > token_count:
                continue
            if tuple(normalized_tokens[position: position + span_len]) != normalized_words:
                continue
            if term.term_source not in seen:
                seen.add(term.term_source)
                found.append(term)
            consumed_spans.append((tokens[position][1], tokens[position + span_len - 1][2]))
            matched_len = span_len
            break

        # 매칭된 구간은 건너뛴다 → 같은 토큰이 중복 소비되지 않고 전체가 O(토큰 수)로 유지된다
        position += matched_len if matched_len else 1

    remainder = text
    for start, end in sorted(consumed_spans, reverse=True):
        remainder = remainder[:start] + " " + remainder[end:]

    return found, remainder


# ── glossary_store.py ─────────────────────────────
# 마지막 적재 시도 결과 — `GET /glossary` 와 번역 응답이 함께 본다
_GLLAST_LOAD: dict = {"loaded": False, "path": "", "reason": "not_loaded", "languages": {}}


def _GLrows_from_json(raw: str) -> list:
    """[(lang, source, target, domain)] 로 평탄화."""
    payload = json.loads(raw)
    rows = []
    if isinstance(payload, dict):
        for lang, entries in payload.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict):
                    rows.append(
                        (
                            str(lang),
                            str(entry.get("source", "")),
                            str(entry.get("target", "")),
                            str(entry.get("domain", "")),
                        )
                    )
    elif isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, dict):
                rows.append(
                    (
                        str(entry.get("target_lang", "")),
                        str(entry.get("source", "")),
                        str(entry.get("target", "")),
                        str(entry.get("domain", "")),
                    )
                )
    return rows


def _GLrows_from_csv(path: str) -> list:
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for record in csv.DictReader(handle):
            rows.append(
                (
                    str(record.get("target_lang", "") or ""),
                    str(record.get("source", "") or ""),
                    str(record.get("target", "") or ""),
                    str(record.get("domain", "") or ""),
                )
            )
    return rows


def glload_from_file(path: str) -> dict:
    """용어사전 파일을 읽어 언어별로 색인한다.

    Returns:
        상태 dict (`status()` 와 같은 형식). 예외를 던지지 않는다 — 기동 경로에서
        불리므로 파일 문제로 컨테이너가 죽으면 안 된다.
    """
    global _GLLAST_LOAD
    glclear_terms()

    if not path:
        _GLLAST_LOAD = {"loaded": False, "path": "", "reason": "not_configured", "languages": {}}
        gllog_info(
            "용어사전 경로 미설정 — 용어사전 없이 번역한다",
            event="glossary_not_configured",
            resource_id="glossary",
            glstatus="disabled",
        )
        return glstatus()

    if not os.path.isfile(path):
        _GLLAST_LOAD = {"loaded": False, "path": path, "reason": "file_not_found", "languages": {}}
        gllog_warning(
            "용어사전 파일을 찾지 못했다 — 용어사전 없이 번역한다",
            event="glossary_file_missing",
            resource_id="glossary",
            glstatus="disabled",
        )
        return glstatus()

    try:
        if path.lower().endswith(".csv"):
            rows = _GLrows_from_csv(path)
        else:
            with open(path, encoding="utf-8") as handle:
                rows = _GLrows_from_json(handle.read())
    except (OSError, ValueError, csv.Error) as exc:
        # 3.8절: 파일 내용·파싱 예외 원문은 남기지 않고 분류만 남긴다
        _GLLAST_LOAD = {"loaded": False, "path": path, "reason": "parse_failed", "languages": {}}
        gllog_warning(
            "용어사전 파일을 해석하지 못했다 — 용어사전 없이 번역한다",
            event="glossary_parse_failed",
            resource_id="glossary",
            error_type=type(exc).__name__,
            glstatus="disabled",
        )
        return glstatus()

    by_lang: dict = {}
    skipped = 0
    for lang, source, target, domain in rows:
        lang = lang.strip().lower()
        source = source.strip()
        target = target.strip()
        if not lang or not source or not target:
            skipped += 1  # 한쪽이 비면 "이 용어는 이렇게 옮긴다"가 성립하지 않는다
            continue
        by_lang.setdefault(lang, []).append(
            GLGlossaryTerm(term_source=source, term_target=target, domain=domain.strip())
        )

    languages = {}
    for lang, terms in by_lang.items():
        glload_terms(lang, terms)
        languages[lang] = glterm_count(lang)

    _GLLAST_LOAD = {
        "loaded": bool(languages),
        "path": path,
        "reason": "ok" if languages else "empty",
        "languages": languages,
    }
    gllog_info(
        "용어사전 적재 완료",
        event="glossary_loaded",
        resource_id="glossary",
        item_count=sum(languages.values()),
        glstatus=f"langs={len(languages)},skipped={skipped}",
    )
    return glstatus()


def glstatus() -> dict:
    """지금 적재 상태. 번역 응답과 `GET /glossary` 가 같은 값을 본다."""
    return {
        "loaded": _GLLAST_LOAD["loaded"],
        "reason": _GLLAST_LOAD["reason"],
        "languages": dict(_GLLAST_LOAD["languages"]),
    }


def gllanguage_status(target_lang: str) -> dict:
    """특정 언어의 적용 가능 여부 — 번역 응답에 싣는다.

    `disabled_over_limit` 는 사전이 너무 커서 색인을 포기한 상태다. 2단계(벡터 검색)
    폴백이 없으므로 그 언어는 용어사전 없이 번역된다 — 반드시 노출한다.

    **파일 적재 이유와 언어별 이유를 섞지 않는다** (번역 단위 `glossary_store` 와 같은
    규약). 파일이 정상인데 그 언어 항목만 없으면 `language_missing` 이다 — 예전에는
    `reason: "ok"` 가 `available: false` 와 함께 나가 "적용 안 됨(사유: ok)" 이 됐다.
    """
    if glis_disabled(target_lang):
        return {"available": False, "reason": "disabled_over_limit", "term_count": 0}
    count = glterm_count(target_lang)
    if not count:
        reason = "language_missing" if _GLLAST_LOAD["loaded"] else _GLLAST_LOAD["reason"]
        return {"available": False, "reason": reason, "term_count": 0}
    return {"available": True, "reason": "ok", "term_count": count}


# ── tools.py ─────────────────────────────
class GLToolError(ValueError):
    def __init__(self, error_type: str):
        super().__init__(error_type)
        self.error_type = error_type


_GLMAX_TEXTS = 200
_GLMAX_TEXT_CHARS = 20_000


def glload_on_startup(path: str) -> dict:
    """기동 시 1회 적재. `main.py` 가 `to_thread` 로 부른다."""
    return glload_from_file(path)


def _GLtext_arg(arguments: dict, name: str) -> str:
    value = arguments.get(name)
    if value is None:
        raise GLToolError(f"MISSING_ARG_{name.upper()}")
    if not isinstance(value, str):
        raise GLToolError(f"INVALID_TYPE_{name.upper()}")
    return value


def _GLglossary_lookup(arguments: dict) -> dict:
    """문장들에 걸린 사내 용어를 모아 낸다.

    **같은 용어가 여러 문장에 나와도 한 번만** 낸다 — 프롬프트에 실을 목록이라
    중복은 토큰 낭비이고, 호출부가 다시 거르게 하면 그 규칙이 호출부마다 갈린다.
    """
    target_lang = _GLtext_arg(arguments, "target_lang")
    texts = arguments.get("texts")
    if not isinstance(texts, list):
        raise GLToolError("INVALID_TYPE_TEXTS")
    if len(texts) > _GLMAX_TEXTS:
        raise GLToolError("TOO_MANY_TEXTS")

    # 이 도구가 쓸 수 있는 상태인지 먼저 본다. 조용히 빈 목록을 주면
    # **"이 문장에 사내 용어가 없다" 와 "사전이 아예 없다" 가 구분되지 않는다.**
    # 2단계(벡터 검색) 폴백이 없어서 후자가 실제로 일어나고, 그때 호출부는 용어사전이
    # 적용된 결과로 착각한다.
    #
    # 예전에는 `is_disabled` 만 봤다 (2026-08-11 수정). 그건 **상한 초과 한 가지뿐**이라
    # 사전 미적재(경로 미설정·적재 실패·그 언어 사전 없음)는 전부 `enabled=True` 로
    # 빠져나갔다 — 이 도구가 선언한 설명("적재되지 않았거나 상한 초과로 꺼진 언어는
    # enabled=false")과 어긋나 있었다. `language_status` 가 이미 네 경우를 다 가른다.
    state = gllanguage_status(target_lang)
    if not state.get("available"):
        return {
            # 성공 경로가 `{원문: 번역}` dict 를 주므로 여기서도 dict 다.
            # 예전에는 이 자리만 `[]` 여서, 결과를 매핑으로 읽는 호출부가 축퇴 경로에서만
            # 터졌다 (가장 늦게 발견되는 형태다).
            "ok": True, "terms": {}, "term_count": 0,
            "enabled": False, "reason": state.get("reason") or "not_loaded",
        }

    seen: dict = {}
    for text in texts:
        if not isinstance(text, str):
            raise GLToolError("INVALID_TYPE_TEXTS")
        if len(text) > _GLMAX_TEXT_CHARS:
            raise GLToolError("TOO_LONG_TEXTS")
        matched = glexact_match(text, target_lang)
        # `exact_match` 는 튜플을 돌려준다. 첫 원소가 매칭 용어 목록이다.
        terms = matched[0] if isinstance(matched, tuple) else matched
        for term in terms or []:
            source = getattr(term, "term_source", None)
            target = getattr(term, "term_target", None)
            if source and source not in seen:
                seen[source] = target or ""

    return {
        "ok": True,
        # `{"원문": "번역"}` — 번역 응답의 `term_map` 과 같은 모양이라 UI 하이라이트에
        # 그대로 쓸 수 있다
        "terms": seen,
        "term_count": len(seen),
        "enabled": True,
        "reason": "",
    }


def _GLglossary_status(arguments: dict) -> dict:
    """적재 상태. **호출부가 이 값을 응답에 실어야 한다.**

    2단계 폴백이 없으므로 "사전 없이 번역됨" 이 실제로 일어난다. 그 사실이 드러나지
    않으면 준수율이 낮은 이유를 영영 알 수 없다.
    """
    target_lang = str(arguments.get("target_lang") or "").strip()
    payload = {"ok": True, "store": dict(glstatus() or {})}
    if target_lang:
        payload["language"] = dict(gllanguage_status(target_lang) or {})
        payload["term_count"] = glterm_count(target_lang)
        payload["disabled"] = glis_disabled(target_lang)
    return payload


def _GLglossary_reload(arguments: dict) -> dict:
    """관리자가 볼륨 파일을 갈아 끼운 뒤 부른다.

    경로는 인자로 받지 않는다 — 임의 경로를 열게 하면 MCP 도구를 통한 파일 읽기가 된다.
    환경변수로 고정된 경로만 다시 읽는다.
    """
    import os

    path = (os.environ.get("TRANSLATE_GLOSSARY_PATH") or "").strip()
    if not path:
        return {"ok": False, "reason": "path_not_configured"}
    result = glload_from_file(path)
    return {"ok": True, "result": dict(result or {})}


GLTOOL_SPECS = [
    {
        "name": "glossary_lookup",
        "description": (
            "문장들에 들어 있는 사내 용어와 그 지정 번역을 낸다. 완전 일치 + 영어 활용형 "
            "정규화로 매칭한다. 결과는 `{원문: 번역}` 이며 중복은 제거된다. "
            "용어사전이 적재되지 않았거나 상한 초과로 꺼진 언어는 `enabled=false` 다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "texts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "검사할 문장들 (최대 200개)",
                },
                "target_lang": {"type": "string", "description": "번역 대상 언어 코드"},
            },
            "required": ["texts", "target_lang"],
        },
    },
    {
        "name": "glossary_status",
        "description": (
            "용어사전 적재 상태를 낸다. 2단계(벡터 검색) 폴백이 없으므로 사전이 없으면 "
            "그 언어는 용어사전 없이 번역된다 — 호출부는 이 상태를 응답에 실어야 한다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_lang": {"type": "string", "description": "언어별 상태를 볼 때만 지정"},
            },
        },
    },
    {
        "name": "glossary_reload",
        "description": (
            "볼륨의 용어사전 파일을 다시 읽는다. 경로는 환경변수로 고정돼 있어 "
            "인자로 지정할 수 없다."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_GLHANDLERS = {
    "glossary_lookup": _GLglossary_lookup,
    "glossary_status": _GLglossary_status,
    "glossary_reload": _GLglossary_reload,
}


def glcall_tool(name: str, arguments: dict) -> dict:
    handler = _GLHANDLERS.get(name)
    if handler is None:
        raise GLToolError("UNKNOWN_TOOL")
    return handler(arguments)


# =====================================================================================
# 적재 — **기동 훅이 없으므로 첫 호출에서 한 번 적재한다**
#
# FastAPI 서빙이었을 때는 `lifespan` 이 적재했다. MCP 는 소스 파일 하나를 실행할 뿐
# 기동 훅을 주지 않으므로, 그 자리를 여기가 대신한다.
#
# **import 시점에 적재하지 않는다.** 파일이 크면(수십만 건) 로드가 길어지는데, import 가
# 느리면 서빙이 왜 안 뜨는지 드러나지 않는다. 첫 도구 호출로 미루면 그 지연이 그 호출의
# 지연으로 보인다.
#
# 실패해도 예외를 올리지 않는다 — **용어사전 없이 도는 것이 정상 축퇴 경로**이고,
# 그 사실은 `glossary_status` 로 드러난다.
# =====================================================================================

_GL_LOAD_ATTEMPTED = False


def _gl_ensure_loaded() -> None:
    global _GL_LOAD_ATTEMPTED
    if _GL_LOAD_ATTEMPTED:
        return
    _GL_LOAD_ATTEMPTED = True

    path = (os.environ.get("TRANSLATE_GLOSSARY_PATH") or "").strip()
    if not path:
        print("[GLOSSARY] 경로 미설정(TRANSLATE_GLOSSARY_PATH) — 용어사전 없이 동작한다")
        return
    try:
        result = glload_from_file(path)
    except Exception as exc:  # noqa: BLE001 - 적재 실패가 도구 호출을 막지 않게
        print(f"[GLOSSARY] 적재 실패({type(exc).__name__}) — 용어사전 없이 동작한다")
        return
    # 적재 결과는 언어별 건수(`languages`)로 온다 — `term_count` 라는 키는 없다.
    languages = (result or {}).get("languages") or {}
    total = sum(int(v or 0) for v in languages.values())
    print(f"[GLOSSARY] 적재 완료: {len(languages)}개 언어 / {total}건")


# =====================================================================================
# 로컬 단독 실행 대비: 런타임이 주입하는 전역 `mcp` 가 없으면 최소 shim 을 쓴다.
# =====================================================================================
try:
    mcp  # noqa: F821
except NameError:
    class _GLLocalMCP:
        def tool(self, *args, **kwargs):
            def _decorator(fn):
                return fn
            return _decorator

    mcp = _GLLocalMCP()
    print("[BOOT] 로컬 테스트용 shim 사용")


def _gl_run(name: str, arguments: dict) -> str:
    """도구 본문을 부르고 JSON 문자열로 돌려준다 (적재를 먼저 보장한다)."""
    _gl_ensure_loaded()
    try:
        result = glcall_tool(name, arguments)
    except GLToolError as exc:
        result = {"ok": False, "error_type": exc.error_type}
    except Exception as exc:  # noqa: BLE001 - 최종 방어선. 원문은 응답에 싣지 않는다 (3.8절)
        print(f"[ERROR] {name} 실패: {type(exc).__name__}")
        result = {"ok": False, "error_type": "TOOL_EXECUTION_FAILED"}
    return json.dumps(result, ensure_ascii=False)


# =====================================================================================
# MCP Tools
# =====================================================================================

@mcp.tool()
async def glossary_lookup(texts: list | str = "", target_lang: str = "") -> str:
    """[언제 쓰나] 번역·다듬기 프롬프트에 **사내 지정 용어**를 실어야 할 때.

    문장들에 들어 있는 사내 용어와 그 지정 번역을 낸다. 완전 일치 + 영어 활용형
    정규화로 매칭하며, 같은 용어가 여러 문장에 나와도 **한 번만** 낸다.

    Args:
        texts: 검사할 문장들 (최대 200개). JSON 배열 문자열도 받는다.
        target_lang: 번역 대상 언어 코드.

    Returns:
        JSON 문자열 `{"ok", "terms": {원문: 번역}, "term_count", "enabled", "reason"}`.

        **`enabled=false` 를 반드시 보라.** 사전이 적재되지 않았거나 상한 초과로 꺼진
        언어다. 2단계(벡터 검색) 폴백이 없으므로 그 언어는 **용어사전 없이** 번역되고,
        이 값이 없으면 호출부가 "이 문장에 사내 용어가 없다" 와 구분하지 못한다.

    알려진 한계: 태국어·중국어는 띄어쓰기가 없어 토큰이 길게 잡히므로 사실상 완전 일치만
    걸린다.
    """
    if isinstance(texts, str):
        try:
            texts = json.loads(texts) if texts.strip() else []
        except json.JSONDecodeError:
            return json.dumps(
                {"ok": False, "error_type": "INVALID_TYPE_TEXTS"}, ensure_ascii=False
            )
    return _gl_run("glossary_lookup", {"texts": texts, "target_lang": target_lang})


@mcp.tool()
async def glossary_status(target_lang: str = "") -> str:
    """[언제 쓰나] 번역 응답에 **용어사전이 적용됐는지**를 실어야 할 때.

    Args:
        target_lang: 언어별 상태를 볼 때만 지정. 비우면 전체 적재 상태만 낸다.

    Returns:
        JSON 문자열 `{"ok", "store": {"loaded", "reason", "languages"}, ...}`.
        `target_lang` 을 주면 `language`·`term_count`·`disabled` 가 함께 온다.

        **적재 상태를 숨기지 않는다.** 2단계 폴백이 없어 "사전 없이 번역됨" 이 실제로
        일어나고, 그 사실이 드러나지 않으면 준수율이 낮은 이유를 영영 알 수 없다.
    """
    return _gl_run("glossary_status", {"target_lang": target_lang})


@mcp.tool()
async def glossary_reload() -> str:
    """[언제 쓰나] 관리자가 볼륨의 용어사전 파일을 갈아 끼운 뒤.

    **경로는 인자로 받지 않는다** — 임의 경로를 열게 하면 MCP 도구를 통한 파일 읽기가
    된다. 환경변수(`TRANSLATE_GLOSSARY_PATH`)로 고정된 경로만 다시 읽는다.

    Returns:
        JSON 문자열. 경로 미설정이면 `{"ok": false, "reason": "path_not_configured"}`.
    """
    return _gl_run("glossary_reload", {})
