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
# ## 적재는 **GenOS AI 드라이브 용어사전 API** 에서 한다 (2026-08-14 전환)
#
# `GET {TRANSLATE_GLOSSARY_API_URL}/data/ai-drive/{DRIVE_ID}/glossary/terms`
# (`용어사전.md`). 그전에는 볼륨 파일(`TRANSLATE_GLOSSARY_PATH`)이었다.
# **용어명 → 한국어 원문 용어, 설명 → 영어 대응 용어**로 읽고 양방향으로 색인한다.
# 첫 도구 호출에서 적재한다(기동 훅이 없다 — 아래 `_GLensure_loaded`).
#
# **설치가 필요한 패키지를 쓰지 않는다.** stdlib 만으로 돈다 (조회는 `urllib`).
# `pydantic` 하나를 **선택적으로**(try/except) 가져다 쓰는데, MCP 런타임(FastMCP)이 도구
# 스키마를 만들 때 이미 쓰는 패키지라 따로 설치할 것이 아니고, 없으면 선택지 없이 그냥
# 돈다 (아래 "선택지를 도구 스키마에 싣는다" 절).
# =====================================================================================

import csv
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from typing import Annotated

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

# 로거 이름은 **파일 이름**이다. 번역 코드서빙에서 옮겨 오며 `translation_pipeline`
# 그대로였는데, 그러면 이 MCP 가 남긴 줄이 그 서빙의 로그처럼 보인다.
_GLlog = logging.getLogger("genon_glossary")


def _GLsetup_logging() -> None:
    """이 파일 전용 **stderr** 핸들러를 붙인다 (2026-08-14).

    두 가지를 동시에 지키려는 것이다:

    - **`print()` 를 쓰지 않는다** (GENOS_RULES §C). MCP 는 stdout 이 전송 채널이 될 수
      있고(stdio 방식), 그러면 로그 한 줄이 프로토콜을 깨뜨린다 — `eval/` 이 stderr 전용
      로깅을 쓰는 이유와 같다.
    - **그렇다고 조용해지지도 않는다.** 로깅 설정이 없는 프로세스에서 `logger.info` 는
      **아무 데도 안 나온다**(기본 최후 핸들러가 WARNING 부터다). 그냥 logger 로 바꾸기만
      하면 부팅·적재 메시지가 소리 없이 사라진다 — 그건 print 보다 나쁘다.

    핸들러가 이미 있으면 아무것도 하지 않는다(런타임이 설정했다면 그쪽을 존중한다).
    """
    if _GLlog.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    _GLlog.addHandler(handler)
    _GLlog.setLevel(logging.INFO)
    # 루트로 올리지 않는다 — 루트에 stdout 핸들러가 붙어 있으면 그리로 새어 나간다.
    _GLlog.propagate = False


_GLsetup_logging()


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
_GLLAST_LOAD: dict = {"loaded": False, "reason": "not_loaded", "languages": {}, "source": ""}


# ── 적재: GenOS AI 드라이브 용어사전 API ──────────────────────
#
# 플랫폼 용어사전은 `{용어명, 설명}` 을 드라이브 단위로 관리한다(`용어사전.md`).
# **용어명을 한국어 원문 용어, 설명을 영어 대응 용어로 읽는다** — 스펙에 번역어 칸이
# 따로 없고, 사내 운용이 설명 칸에 영문 용어를 적기로 확정됐다(2026-08-14).
#
# 받은 것은 `(한국어, 영어)` 쌍 하나지만 **양방향으로 색인한다** — `ko→en` 과 `en→ko`
# 둘 다 지켜야 하고, 한쪽만 실으면 반대 방향이 "적용 대상인데 색인이 비어" 준수율
# 1.0 으로 나간다(지킬 것이 없다고 보고되는 상태).
#
# **`urllib` 을 쓴다.** MCP 파일은 `requirements.txt` 가 없어 httpx 를 가정할 수 없다.

_GLMAX_TERM_CHARS = 30
_GLMAX_DESCRIPTION_CHARS = 500
_GLMAX_TERMS = 2000
_GLFORBIDDEN_CHARS = set('\\/:*?"<>|')
_GLPAGE_SIZE = 200
_GLMAX_PAGES = 50
_GLFETCH_TIMEOUT = 20.0
_GLKOREAN = "ko"
_GLENGLISH = "en"

# ── 언어 코드 정규화 (2026-08-18) ──────────────────────────────────
#
# `target_lang` 은 **색인의 키로 그대로 쓰인다**(`_GLINDEX[target_lang]`). 그래서
# `"KO"`·`"Korean"`·`"한국어"`·`"ko-KR"` 이 오면 색인에 그런 키가 없어
# `language_missing` 으로 떨어졌다 — 예외도 오류도 없이 **용어사전만 조용히 빠진
# 번역**이 나가고, 준수율은 대조할 용어가 없으니 늘 1.0 이라 정상처럼 보인다.
# 화면·워크플로우 변수 표기가 제각각이므로 한 곳에서 흡수한다.
#
# **`genon_lang_policy` 의 표와 같은 내용이어야 한다.** 등록 단위 간 import 이 금지라
# 강제된 사본이고, 갈리면 그쪽이 허용한 값을 이쪽이 못 알아본다 —
# `check_mcp_tools.py` 가 두 파일을 한 네임스페이스에 올려 대조한다.
_GLLANGUAGE_CODES = ("ko", "en", "zh", "th", "vi", "ru")

_GLLANGUAGE_ALIASES = {
    "korean": "ko", "kor": "ko", "ko-kr": "ko", "한국어": "ko", "국문": "ko",
    "english": "en", "eng": "en", "en-us": "en", "영어": "en", "영문": "en",
    "chinese": "zh", "zh-cn": "zh", "zh-hans": "zh", "cn": "zh", "중국어": "zh",
    "thai": "th", "th-th": "th", "태국어": "th",
    "vietnamese": "vi", "vi-vn": "vi", "베트남어": "vi",
    "russian": "ru", "ru-ru": "ru", "러시아어": "ru", "노어": "ru",
}


def glnormalize_lang(value: str) -> str:
    """언어 코드/별칭을 소문자 코드로. **모르는 값은 그대로 돌려준다.**

    거부하지 않는 이유: 이 파일의 계약은 "그 언어에 사전이 있는가" 를 답하는 것이고,
    지원 언어 판정은 `genon_lang_policy.validate_direction` 의 몫이다. 여기서 예외를
    올리면 같은 거부가 두 곳에서 서로 다른 모양으로 나간다.
    """
    normalized = (value or "").strip().lower().replace("_", "-")
    return _GLLANGUAGE_ALIASES.get(normalized, normalized)


def _GLvalid_pair(term: str, description: str) -> str:
    """걸러야 하면 사유 코드를, 쓸 수 있으면 빈 문자열을. 값 자체는 로그에 남기지 않는다."""
    if not term:
        return "term_empty"
    if len(term) > _GLMAX_TERM_CHARS:
        return "term_too_long"
    if any(char in _GLFORBIDDEN_CHARS for char in term):
        return "term_forbidden_char"
    if not description:
        return "description_empty"     # 설명이 곧 번역어다
    if len(description) > _GLMAX_DESCRIPTION_CHARS:
        return "description_too_long"
    return ""


def _GLpairs_from_items(items: list) -> tuple:
    pairs: list = []
    seen: set = set()
    skipped: dict = {}
    for item in items:
        if not isinstance(item, dict):
            skipped["not_an_object"] = skipped.get("not_an_object", 0) + 1
            continue
        term = str(item.get("term") or "").strip()
        description = str(item.get("description") or "").strip()
        reason = _GLvalid_pair(term, description)
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        key = term.casefold()
        if key in seen:
            skipped["duplicate_term"] = skipped.get("duplicate_term", 0) + 1
            continue
        seen.add(key)
        pairs.append((term, description))
        if len(pairs) >= _GLMAX_TERMS:
            break
    return pairs, skipped


def _GLitems_from_payload(payload) -> list:
    """응답 모양이 배포마다 달라도 항목을 찾아낸다 (`items`/`data`/`list`/최상위 배열)."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    found = payload.get("items") or payload.get("data") or payload.get("list") or []
    if isinstance(found, dict):
        found = found.get("items") or []
    return found if isinstance(found, list) else []


def _GLfetch_items(base_url: str, drive_id: str, workspace_id: str, token: str) -> list:
    import urllib.parse
    import urllib.request

    endpoint = f"{base_url.rstrip('/')}/data/ai-drive/{urllib.parse.quote(drive_id)}/glossary/terms"
    items: list = []
    for page in range(1, _GLMAX_PAGES + 1):
        query = urllib.parse.urlencode({"pg": page, "pgSize": _GLPAGE_SIZE})
        request = urllib.request.Request(f"{endpoint}?{query}", method="GET")
        request.add_header("x-genos-workspace-id", workspace_id)
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(request, timeout=_GLFETCH_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
        page_items = _GLitems_from_payload(payload)
        if not page_items:
            break
        items.extend(page_items)
        if len(page_items) < _GLPAGE_SIZE or len(items) >= _GLMAX_TERMS:
            break
    return items


def _GLapi_settings():
    """`(base_url, drive_id, workspace_id, token)` — 하나라도 비면 `None`.

    경로를 인자로 받지 않는 것과 같은 이유로 **환경변수로 고정한다** — 도구 인자로
    받으면 MCP 를 통해 임의 호스트를 호출하게 된다.
    """
    import os

    base_url = (os.environ.get("TRANSLATE_GLOSSARY_API_URL") or "").strip().rstrip("/")
    drive_id = (os.environ.get("TRANSLATE_GLOSSARY_DRIVE_ID") or "").strip()
    workspace_id = (os.environ.get("TRANSLATE_GLOSSARY_WORKSPACE_ID") or "").strip()
    token = ((os.environ.get("TRANSLATE_GLOSSARY_TOKEN") or "").strip()
             or (os.environ.get("GENOS_TOKEN") or "").strip())
    if not (base_url and drive_id and workspace_id):
        return None
    return base_url, drive_id, workspace_id, token


def glload_from_admin_api(base_url: str, drive_id: str, workspace_id: str, token: str) -> dict:
    """용어사전 API 에서 받아 양방향으로 색인한다. **예외를 던지지 않는다.**"""
    global _GLLAST_LOAD
    glclear_terms()

    if not (base_url and drive_id and workspace_id):
        _GLLAST_LOAD = {"loaded": False, "reason": "not_configured", "languages": {}, "source": "api"}
        return glstatus()

    try:
        items = _GLfetch_items(base_url, drive_id, workspace_id, token)
    except Exception as exc:  # noqa: BLE001 - 통신·파싱 실패 전부. 원문은 남기지 않는다(3.8절)
        _GLLAST_LOAD = {"loaded": False, "reason": "fetch_failed", "languages": {}, "source": "api"}
        _GLlog.warning(
            "용어사전 조회 실패 — 사전 없이 동작한다",
            extra={"event": "glossary_fetch_failed", "error_type": type(exc).__name__},
        )
        return glstatus()

    pairs, skipped = _GLpairs_from_items(items)
    languages = {}
    if pairs:
        glload_terms(_GLENGLISH, [GLGlossaryTerm(term_source=ko, term_target=en) for ko, en in pairs])
        glload_terms(_GLKOREAN, [GLGlossaryTerm(term_source=en, term_target=ko) for ko, en in pairs])
        languages = {_GLENGLISH: glterm_count(_GLENGLISH), _GLKOREAN: glterm_count(_GLKOREAN)}

    _GLLAST_LOAD = {
        "loaded": bool(pairs),
        "reason": "ok" if pairs else "empty",
        "languages": languages,
        "source": "api",
    }
    _GLlog.info(
        "용어사전 적재 완료",
        extra={"event": "glossary_loaded", "item_count": len(pairs),
               "status": f"received={len(items)},skipped={json.dumps(skipped, ensure_ascii=False)}"},
    )
    return glstatus()



def glstatus() -> dict:
    """지금 적재 상태. 번역 응답과 `GET /glossary` 가 같은 값을 본다."""
    return {
        "loaded": _GLLAST_LOAD["loaded"],
        "reason": _GLLAST_LOAD["reason"],
        "languages": dict(_GLLAST_LOAD["languages"]),
        "source": _GLLAST_LOAD.get("source", ""),
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
    # 색인 키로 쓰이므로 **여기서 정규화한다** — "KO"·"한국어" 가 오면 사전이 조용히 빠진다.
    target_lang = glnormalize_lang(_GLtext_arg(arguments, "target_lang"))
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
        # `{"원문": "번역"}` — **조회 결과**다. 모양은 번역 응답의 `term_map` 과 같지만
        # **의미가 다르므로 UI 하이라이트에 그대로 쓰면 안 된다** (2026-08-14 정정):
        # 이건 번역 **전에** "이 문장에 사전 용어가 있다" 를 말하는 값이고,
        # 번역문이 그 용어를 실제로 썼는지는 아직 아무도 모른다. 요구사항의
        # "참고한 단어에 대해서만 표시" 는 번역 **후** 판정이라, 번역 응답의
        # `glossary.term_map`(적용된 것만) 또는 `glossary.hits[].applied` 를 써야 한다.
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
    target_lang = glnormalize_lang(str(arguments.get("target_lang") or ""))
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

    settings = _GLapi_settings()
    if not settings:
        return {"ok": False, "reason": "api_not_configured"}
    result = glload_from_admin_api(*settings)
    return {"ok": True, "result": dict(result or {})}

# ── 도구 카탈로그는 손으로 적지 않는다 (2026-08-14) ──────────────────
# 예전에는 `GLTOOL_SPECS` 에 JSON-Schema 를 손으로 적어 뒀다 — `/mcp/list` 를 우리가
# 구현하던 시절의 잔재다. 지금은 `@mcp.tool()` 이 시그니처·타입힌트·독스트링에서
# 카탈로그를 만들므로 그 목록은 **아무 데서도 읽히지 않았고**, 고쳐도 노출되는
# 스키마가 바뀌지 않는다 — 고친 사람은 바뀐 줄 안다. 그래서 지웠다.
# 도구 설명을 고칠 곳은 각 `@mcp.tool()` 함수의 독스트링이다.

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

    settings = _GLapi_settings()
    if not settings:
        _GLlog.info("용어사전 API 설정 미완료 — 사전 없이 동작한다",
                    extra={"event": "glossary_api_not_configured"})
        return
    try:
        result = glload_from_admin_api(*settings)
    except Exception as exc:  # noqa: BLE001 - 적재 실패가 도구 호출을 막지 않게
        _GLlog.warning("용어사전 적재 실패 — 사전 없이 동작한다",
                       extra={"event": "glossary_load_failed", "error_type": type(exc).__name__})
        return
    # 적재 결과는 언어별 건수(`languages`)로 온다 — `term_count` 라는 키는 없다.
    languages = (result or {}).get("languages") or {}
    total = sum(int(v or 0) for v in languages.values())
    _GLlog.info("용어사전 적재 완료",
                extra={"event": "glossary_loaded", "item_count": total, "status": f"languages={len(languages)}"})


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
    _GLlog.info("로컬 테스트용 shim 사용", extra={"event": "mcp_shim_used"})


def _gl_run(name: str, arguments: dict) -> str:
    """도구 본문을 부르고 JSON 문자열로 돌려준다 (적재를 먼저 보장한다)."""
    _gl_ensure_loaded()
    try:
        result = glcall_tool(name, arguments)
    except GLToolError as exc:
        result = {"ok": False, "error_type": exc.error_type}
    except Exception as exc:  # noqa: BLE001 - 최종 방어선. 원문은 응답에 싣지 않는다 (3.8절)
        _GLlog.warning("도구 실행 실패", extra={"event": "mcp_tool_failed", "error_type": type(exc).__name__})
        result = {"ok": False, "error_type": "TOOL_EXECUTION_FAILED"}
    return json.dumps(result, ensure_ascii=False)


# =====================================================================================
# 선택지를 **도구 스키마에 싣는다** (2026-08-18 — `genon_lang_policy` 와 같은 규약)
#
# `target_lang` 이 맨 `str` 이면 **선택지가 계약 어디에도 없다.** 노출되는 스키마에는
# "문자열" 이라고만 적히고, 호출부(캔버스 화면·워크플로우 변수·도구를 고르는 LLM)가
# 자기 목록을 들고 있게 된다. 이 도구에서는 그 결과가 특히 조용하다 —
# 알 수 없는 코드는 오류가 아니라 `enabled=false`(사전 없음)로 떨어지므로,
# **용어사전만 빠진 정상 응답**이 나간다.
#
# 판정은 그대로 본문이 한다(`glnormalize_lang` 이 별칭을 흡수한다). `Literal[...]` 로
# 하지 않는 이유도 같다 — 별칭이 타입 검증에서 죽고, 그러면 "이 언어에는 사전이 없다"
# 는 안내가 전송 실패와 구분되지 않는 형태로 바뀐다.
#
# 빈 문자열(`""`)은 항상 선택지에 넣는다 — GenOS 는 값이 없을 때 `""` 를 주입한다.
# =====================================================================================
try:  # pydantic 은 MCP 런타임(FastMCP)이 스키마를 만들 때 이미 쓰는 패키지다.
    from pydantic import Field as _GLPydanticField
except Exception:  # noqa: BLE001 - 없으면 선택지 없이(맨 str) 동작한다. 판정은 그대로다.
    _GLPydanticField = None


def _GLlang_arg(description: str) -> object:
    """언어 코드 인자에 **선택지가 실린 주석**을 만든다.

    용어사전이 있는 언어(`ko`·`en`)를 설명에 밝히되 **선택지에서 빼지는 않는다** —
    `ru` 로 물어 "이 언어에는 사전이 없다" 는 답을 받는 것이 호출부가 미적용 사유를
    응답에 실을 수 있는 유일한 경로다. 빼면 그 질문 자체를 못 하게 된다.
    """
    values = list(_GLLANGUAGE_CODES) + [""]
    text = (f"{description} 선택지: {', '.join(_GLLANGUAGE_CODES)}. "
            f"사내 용어사전이 있는 언어는 {_GLKOREAN}·{_GLENGLISH} 뿐이고, "
            "나머지는 enabled=false 로 사유가 온다. (미지정은 빈 문자열)")
    if _GLPydanticField is None:
        return str
    return Annotated[str, _GLPydanticField(description=text, json_schema_extra={"enum": values})]


_GLTargetLangArg = _GLlang_arg("번역 대상 언어 코드.")
_GLStatusLangArg = _GLlang_arg("언어별 상태를 볼 때만 지정.")


# =====================================================================================
# MCP Tools
# =====================================================================================

@mcp.tool()
async def glossary_lookup(texts: list | str = "", target_lang: _GLTargetLangArg = "") -> str:
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
async def glossary_status(target_lang: _GLStatusLangArg = "") -> str:
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
    """[언제 쓰나] 관리자가 용어사전에 용어를 등록·수정하고 **승인 결재가 끝난 뒤.**

    **호스트·드라이브를 인자로 받지 않는다** — 도구 인자로 받으면 MCP 를 통해 임의
    호스트를 호출하게 된다. 환경변수로 고정된 드라이브만 다시 받는다.

    Returns:
        JSON 문자열. 설정 미완료면 `{"ok": false, "reason": "api_not_configured"}`.
    """
    return _gl_run("glossary_reload", {})
