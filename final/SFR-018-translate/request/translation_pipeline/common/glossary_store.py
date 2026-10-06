"""용어사전 적재 — **GenOS 용어사전**(`데이터 > 용어사전`, v1.9.3)에서 읽는다.

스펙 원문은 `archive/genos-project/용어사전.md` 다.

## 무엇을 읽는가

플랫폼 용어사전은 **사전마다 속성 구조를 정의**한다. 모든 사전에 고정으로 있는 속성은
대표어(키 `text`) 하나뿐이고, 나머지(정의·동의어·영문명 …)는 관리자가 만든 속성이다.
번역에 쓰는 것은 셋이다.

| 쓰임 | 속성 | 설정 |
|---|---|---|
| 한국어 원문 용어 | 대표어 `text` (고정) | — |
| 영어 대응 용어 | 관리자가 만든 영문명 속성 (`text` 또는 `text[]`) | `TRANSLATE_GLOSSARY_TARGET_KEY` |
| 한국어 이형(동의어·줄임말) | 관리자가 만든 동의어 속성 (`text[]`, 선택) | `TRANSLATE_GLOSSARY_SYNONYM_KEY` |

**속성 키는 사전마다 관리자가 정하므로 코드에 박지 않는다.** 영문명 키가 틀리면 받은
용어가 전부 번역어 없음으로 걸러지는데, 그 상태를 "사전이 비어 있다" 와 구분해
`target_key_missing` 으로 낸다 — 관리자가 고칠 것은 사전이 아니라 설정이다.

## 어떻게 받는가

스펙은 "인증 키(읽기 전용)로 코드에서 직접 조회한다" 까지만 정하고 REST 경로를 적지
않는다. 그래서 **경로를 코드가 만들지 않고 설정으로 통째로 받는다**:

```
GET {TRANSLATE_GLOSSARY_API_URL}                     # `{glossary_id}` 가 있으면 사전 ID 로 치환
    ?pg=<page>&pgSize=200                             # 페이지 파라미터 이름은 _PAGE_PARAMS 한 곳
    Authorization: Bearer {TRANSLATE_GLOSSARY_TOKEN}  # 사전의 읽기 전용 인증 키
    x-genos-workspace-id: {TRANSLATE_GLOSSARY_WORKSPACE_ID}   # 설정했을 때만
```

응답은 용어 객체의 목록이다. 목록 자리(`items`/`data`/`list`/`terms`/최상위 배열)와
속성 자리(용어 객체 최상위 또는 `properties`/`attributes`/`values` 아래)가 배포마다
다를 수 있어 모두 받는다 — 한 가지만 보고 빈손으로 끝나면 사전이 없는 것과 구분되지
않는다.

## 양방향으로 색인한다

번역 방향은 둘인데 사전 행은 하나다. 그래서 **같은 행을 뒤집어 두 언어에** 싣는다:

- `index["en"]` (ko→en): 대표어·한국어 이형 → 영문명 첫 값
- `index["ko"]` (en→ko): 영문명의 모든 값 → 대표어

한쪽만 실으면 `en→ko` 가 "적용 대상 방향인데 색인이 비어" 준수율 1.0 으로 나간다 —
지키지 못한 것이 아니라 **지킬 것이 없다고 보고되는** 상태다.
용어사전 적용 언어가 한국어·영어뿐이라(`languages.glossary_supported`) 이 두 색인이
전부다.

## 스펙에서 가져온 검증

API 응답이 늘 플랫폼 입력 규칙을 지킨다는 보장이 우리에게 없다. 걸러낸 건수는 사유별로
세어 로그에 남긴다(값은 남기지 않는다, 3.8절).

| 대상 | 규칙 |
|---|---|
| 대표어 | 필수 · 1,024자 이하 (`text` 타입 상한) |
| 영문명 | **번역어로 쓰므로 여기서는 필수** · 값마다 1,024자 이하 |
| 중복 | 같은 대표어·같은 표기가 다시 오면 **처음 것만** 쓴다 (대소문자 무시) |
| 건수 | 스펙에 사전 건수 한도가 없어 우리 상한 `_MAX_TERMS` 로 끊는다 |

## 실패 처리

**받지 못해도 번역은 계속하고 그 사실을 남긴다.** 용어사전은 품질 장치이고, 없다고
번역을 못 하는 것은 아니다. 대신 상태(`status()`)를 `GET /glossary` 와 번역 응답에
실어 "적용된 줄 알았는데 아니었다" 가 생기지 않게 한다.
"""

import json
import urllib.parse
from dataclasses import dataclass

import httpx

from translation_pipeline.common.glossary_exact import (
    GlossaryTerm,
    clear_terms,
    is_disabled,
    load_terms,
    term_count,
)
from translation_pipeline.common.logging_utils import log_info, log_warning

# 스펙(`용어사전.md`)에서 옮겨 적은 값
_REPRESENTATIVE_KEY = "text"      # 대표어 속성 키 — 모든 사전에 고정
_MAX_VALUE_CHARS = 1024           # `text`/`text[]` 값 하나의 상한

# 우리가 정한 값
_MAX_TERMS = 20_000               # 스펙에 사전 건수 한도가 없다. 기동 시간·메모리 상한이다
_PAGE_SIZE = 200
_MAX_PAGES = _MAX_TERMS // _PAGE_SIZE + 1   # 응답이 이상해도 무한 루프로 가지 않는다
_TIMEOUT = 20.0
_PAGE_PARAMS = ("pg", "pgSize")   # 스펙 미기재 — 실제 API 가 다르면 여기만 고친다
_ID_PLACEHOLDER = "{glossary_id}"
_LIST_KEYS = ("items", "data", "list", "terms")
_NESTED_KEYS = ("properties", "attributes", "values")

_KOREAN = "ko"
_ENGLISH = "en"

# 마지막 적재 시도 결과 — `GET /glossary` 와 번역 응답이 함께 본다
_LAST_LOAD: dict = {"loaded": False, "reason": "not_loaded", "languages": {}, "source": ""}


@dataclass(frozen=True)
class GlossarySettings:
    """적재에 필요한 설정 한 묶음. 값은 `Config.glossary_settings()` 가 환경변수에서 읽는다."""

    api_url: str = ""             # 용어 목록 URL. `{glossary_id}` 가 있으면 치환한다
    glossary_id: str = ""
    token: str = ""               # 사전의 읽기 전용 인증 키
    target_key: str = ""          # 영문명 속성 키
    synonym_key: str = ""         # 한국어 이형 속성 키 (선택)
    workspace_id: str = ""        # `x-genos-workspace-id` (선택)

    def missing(self) -> list:
        """비어 있어서 적재할 수 없게 만드는 설정 이름들 (값이 아니라 이름이라 로그에 싣는다)."""
        missing = []
        if not self.api_url:
            missing.append("api_url")
        if _ID_PLACEHOLDER in self.api_url and not self.glossary_id:
            missing.append("glossary_id")
        if not self.token:
            missing.append("token")
        if not self.target_key:
            missing.append("target_key")
        return missing


@dataclass(frozen=True)
class _Entry:
    korean: tuple                 # 대표어가 맨 앞, 이어서 이형
    english: tuple                # 영문명 값들. 맨 앞이 ko→en 번역어


def _endpoint(settings: GlossarySettings) -> str:
    url = settings.api_url.strip()
    if _ID_PLACEHOLDER in url:
        url = url.replace(_ID_PLACEHOLDER, urllib.parse.quote(settings.glossary_id, safe=""))
    return url


def _flatten(item: dict) -> dict:
    """속성이 최상위에 있든 `properties` 등의 아래에 있든 한 dict 로 편다. 최상위가 이긴다."""
    flat = {key: value for key, value in item.items() if key not in _NESTED_KEYS}
    for key in _NESTED_KEYS:
        nested = item.get(key)
        if isinstance(nested, dict):
            for name, value in nested.items():
                flat.setdefault(name, value)
    return flat


def _text_values(value) -> list:
    """`text` 또는 `text[]` 값 → 공백을 걷은 문자열 목록 (빈 값·중복 제외).

    문자열은 쪼개지 않는다. `;` 구분은 CSV 업로드 양식의 규칙이고 API 는 배열을 배열로 준다.
    """
    raw = value if isinstance(value, (list, tuple)) else [value]
    values: list = []
    for element in raw:
        if element is None or isinstance(element, (dict, list, tuple, bool)):
            continue
        text = str(element).strip()
        if text and text not in values:
            values.append(text)
    return values


def _count(skipped: dict, reason: str, n: int = 1) -> None:
    skipped[reason] = skipped.get(reason, 0) + n


def _entries_from_items(items: list, settings: GlossarySettings) -> tuple:
    """API 항목 목록 → `[_Entry]`, 사유별 걸러진 건수, 영문명 속성을 본 적이 있는지.

    마지막 값은 "영문명 키가 틀렸다" 를 "사전이 비어 있다" 와 가르는 데 쓴다.
    """
    entries: list = []
    seen_terms: set = set()
    skipped: dict = {}
    target_seen = False
    for position, item in enumerate(items):
        if not isinstance(item, dict):
            _count(skipped, "not_an_object")
            continue
        flat = _flatten(item)
        terms = _text_values(flat.get(_REPRESENTATIVE_KEY))
        if not terms:
            _count(skipped, "term_empty")
            continue
        term = terms[0]
        if len(term) > _MAX_VALUE_CHARS:
            _count(skipped, "term_too_long")
            continue
        if settings.target_key in flat:
            target_seen = True
        english = [v for v in _text_values(flat.get(settings.target_key)) if len(v) <= _MAX_VALUE_CHARS]
        if not english:
            # 영문명이 곧 번역어다. 비어 있으면 "이 용어는 이렇게 옮긴다" 가 성립하지 않는다.
            _count(skipped, "target_empty")
            continue
        if term.casefold() in seen_terms:
            _count(skipped, "duplicate_term")
            continue
        seen_terms.add(term.casefold())
        synonyms = []
        if settings.synonym_key:
            synonyms = [
                v for v in _text_values(flat.get(settings.synonym_key))
                if len(v) <= _MAX_VALUE_CHARS and v.casefold() != term.casefold()
            ]
        entries.append(_Entry(korean=tuple([term] + synonyms), english=tuple(english)))
        if len(entries) >= _MAX_TERMS:
            _count(skipped, "over_max_terms", len(items) - position - 1)
            break
    return entries, skipped, target_seen


def _unique_terms(pairs, skipped: dict) -> list:
    """`(원문 표기, 번역어)` 를 `GlossaryTerm` 으로. 같은 원문 표기는 처음 것만 쓴다.

    이형이 다른 행의 대표어와 겹치면 행 순서상 먼저 온 쪽이 이긴다 — 한 표기가 두
    번역어를 갖게 두면 어느 쪽을 강제할지가 색인 순서에 따라 달라진다.
    """
    terms: list = []
    seen: set = set()
    for source, target in pairs:
        key = source.casefold()
        if key in seen:
            _count(skipped, "duplicate_alias")
            continue
        seen.add(key)
        terms.append(GlossaryTerm(term_source=source, term_target=target))
    return terms


def _index_entries(entries: list, skipped: dict) -> dict:
    """행을 **양방향**으로 색인한다 (머리말 참고)."""
    to_english = _unique_terms(
        ((korean, entry.english[0]) for entry in entries for korean in entry.korean), skipped
    )
    to_korean = _unique_terms(
        ((english, entry.korean[0]) for entry in entries for english in entry.english), skipped
    )
    load_terms(_ENGLISH, to_english)
    load_terms(_KOREAN, to_korean)
    return {_ENGLISH: term_count(_ENGLISH), _KOREAN: term_count(_KOREAN)}


def _page_items(payload) -> list:
    """응답 한 페이지에서 용어 객체 목록을 찾는다 (머리말 "어떻게 받는가")."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in _LIST_KEYS:
        found = payload.get(key)
        if isinstance(found, dict):                 # {"data": {"items": [...]}}
            found = next((found[k] for k in _LIST_KEYS if isinstance(found.get(k), list)), None)
        if isinstance(found, list):
            return found
    return []


async def _fetch_items(settings: GlossarySettings) -> list:
    """페이지를 끝까지 따라가며 용어 객체를 모은다."""
    headers = {"Authorization": f"Bearer {settings.token}"}
    if settings.workspace_id:
        headers["x-genos-workspace-id"] = settings.workspace_id
    page_key, size_key = _PAGE_PARAMS
    url = _endpoint(settings)
    items: list = []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for page in range(1, _MAX_PAGES + 1):
            response = await client.get(
                url, headers=headers, params={page_key: page, size_key: _PAGE_SIZE}
            )
            response.raise_for_status()
            page_items = _page_items(response.json())
            if not page_items:
                break
            items.extend(page_items)
            if len(page_items) < _PAGE_SIZE or len(items) >= _MAX_TERMS:
                break
    return items


def _set_last(loaded: bool, reason: str, languages: dict = None) -> dict:
    global _LAST_LOAD
    _LAST_LOAD = {"loaded": loaded, "reason": reason, "languages": languages or {}, "source": "api"}
    return status()


async def load_from_admin_api(settings: GlossarySettings) -> dict:
    """용어사전 API 에서 용어를 받아 양방향으로 색인한다.

    Returns:
        상태 dict (`status()` 와 같은 형식). **예외를 던지지 않는다** — 기동 경로에서
        불리므로 용어사전 문제로 컨테이너가 죽으면 안 된다.
    """
    clear_terms()

    missing = settings.missing()
    if missing:
        log_info(
            "용어사전 설정 미완료 — 용어사전 없이 번역한다",
            event="glossary_not_configured",
            resource_id="glossary",
            status=f"disabled,missing={','.join(missing)}",
        )
        return _set_last(False, "not_configured")

    try:
        items = await _fetch_items(settings)
    except httpx.HTTPStatusError as exc:
        # 상태코드는 남기고 본문은 남기지 않는다 (3.8절). 401/403(인증 키) 과 5xx 는
        # 관리자가 할 일이 다르므로 사유에 상태코드를 함께 싣는다.
        log_warning(
            "용어사전 조회 실패 — 용어사전 없이 번역한다",
            event="glossary_fetch_failed",
            resource_id="glossary",
            upstream_status=exc.response.status_code,
            error_type=type(exc).__name__,
            status="disabled",
        )
        return _set_last(False, f"fetch_failed_{exc.response.status_code}")
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        log_warning(
            "용어사전 조회 실패 — 용어사전 없이 번역한다",
            event="glossary_fetch_failed",
            resource_id="glossary",
            error_type=type(exc).__name__,
            status="disabled",
        )
        return _set_last(False, "fetch_failed")

    entries, skipped, target_seen = _entries_from_items(items, settings)
    languages = _index_entries(entries, skipped) if entries else {}
    if entries:
        reason = "ok"
    elif items and not target_seen:
        reason = "target_key_missing"
    else:
        reason = "empty"

    log_info(
        "용어사전 적재 완료" if entries else "용어사전에 쓸 용어가 없다 — 용어사전 없이 번역한다",
        event="glossary_loaded",
        resource_id="glossary",
        item_count=len(entries),
        # 걸러진 것이 있으면 사유별로 남긴다 — 값은 싣지 않는다
        status=f"reason={reason},received={len(items)},skipped={json.dumps(skipped, ensure_ascii=False)}",
    )
    return _set_last(bool(entries), reason, languages)


def status() -> dict:
    """지금 적재 상태. 번역 응답과 `GET /glossary` 가 같은 값을 본다."""
    return {
        "loaded": _LAST_LOAD["loaded"],
        "reason": _LAST_LOAD["reason"],
        "languages": dict(_LAST_LOAD["languages"]),
        # 어디서 받은 것인가 — 화면·운영이 출처를 물을 때 쓴다.
        "source": _LAST_LOAD.get("source", ""),
    }


def language_status(target_lang: str) -> dict:
    """특정 언어의 적용 가능 여부 — 번역 응답에 싣는다.

    `disabled_over_limit` 는 사전이 너무 커서 색인을 포기한 상태다. 2단계(벡터 검색)
    폴백이 없으므로 그 언어는 용어사전 없이 번역된다 — 반드시 노출한다.

    **적재 실패 이유와 언어별 이유를 섞지 않는다.** 정상 적재됐는데 그 언어 항목만
    없는 경우를 `{"available": false, "reason": "ok"}` 로 내면 화면이 "적용 안
    됨(사유: ok)" 을 받는 셈이라 관리자가 무엇을 고쳐야 하는지 알 수 없다. 그래서
    `language_missing` 으로 갈라, **용어를 채울 일**과 **아예 못 받은 일**
    (`fetch_failed*`·`not_configured`·`target_key_missing`)을 구분한다.
    """
    if is_disabled(target_lang):
        return {"available": False, "reason": "disabled_over_limit", "term_count": 0}
    count = term_count(target_lang)
    if not count:
        reason = "language_missing" if _LAST_LOAD["loaded"] else _LAST_LOAD["reason"]
        return {"available": False, "reason": reason, "term_count": 0}
    return {"available": True, "reason": "ok", "term_count": count}
