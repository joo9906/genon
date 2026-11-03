"""용어사전 적재 — **GenOS 용어사전 API**(관리자 콘솔 → 데이터 → 용어사전)에서 읽는다.

## 무엇을 읽는가

```
GET {API_URL}/data/glossaries/{glossary_id}/attributes          # 속성 이름 → 키
GET {API_URL}/data/glossaries/{glossary_id}/terms?pg=N&pgSize=200
    Authorization: Bearer {token}
```

응답은 공통 래퍼 `{code, message, data}` 이고 `code` 가 0 이 아니면 실패다.
속성은 `data.items[] = {key, name, is_representative, …}`, 용어는
`data.list[] = {values: {속성 키: 값}}` + `data.total_count` 로 온다.

**이름이 `ko` / `en` 인 속성을 한국어 · 영어로 읽는다**(이름이 없으면 키가 같은 속성).
`ko` 속성이 없으면 **대표어**(`is_representative`)를 한국어로 쓴다 — 사내 운용은 대표어에
한국어, `en` 속성에 영어를 넣는다. 속성 이름은 `TRANSLATE_GLOSSARY_KO_ATTR` ·
`TRANSLATE_GLOSSARY_EN_ATTR` 로 바꿀 수 있다. 값이 목록(`text[]`)이면 첫 비어 있지 않은
값을 쓴다. 이 매핑이 **이 파일 하나에만** 있다(MCP 사본 `genon_glossary.py` 제외).

## 양방향으로 색인한다

받은 것은 `(한국어, 영어)` 쌍 하나뿐이지만 번역 방향은 둘이다. `ko→en` 은 한국어를
찾아 영어를 강제하고, `en→ko` 는 그 반대다. 그래서 **같은 쌍을 뒤집어 두 언어에** 싣는다:

- `index["en"]`  source=한국어 → target=영어
- `index["ko"]`  source=영어   → target=한국어

한쪽만 실으면 `en→ko` 가 "적용 대상 방향인데 색인이 비어" 준수율 1.0 으로 나간다 —
지키지 못한 것이 아니라 **지킬 것이 없다고 보고되는** 상태다.
용어사전 적용 언어가 한국어·영어뿐이라(`languages.glossary_supported`) 이 두 색인이
전부다.

## 거르는 것

한국어나 영어가 비었으면, 같은 한국어가 두 번 오면(처음 것만 쓴다) 뺀다. 걸러진 건수를
사유별로 세어 두면 "왜 이 용어가 안 걸리나" 를 답할 수 있다. 값은 로그에 남기지 않는다.

## 실패 처리

**받지 못해도 번역은 계속하고 그 사실을 남긴다.** 용어사전은 품질 장치이고, 없다고
번역을 못 하는 것은 아니다. 대신 상태(`status()`)를 `GET /glossary` 와 번역 응답에
실어 "적용된 줄 알았는데 아니었다" 가 생기지 않게 한다. 사유는 `not_configured` ·
`fetch_failed[_상태코드]` · `invalid_response` · `attribute_not_found` · `empty` 로 갈린다.
"""

import urllib.parse

import httpx

from translation_pipeline.common.glossary_exact import (
    GlossaryTerm,
    clear_terms,
    is_disabled,
    load_terms,
    term_count,
)
from translation_pipeline.common.logging_utils import log_info, log_warning

_PAGE_SIZE = 200
_MAX_PAGES = 500         # 응답이 이상해도 무한 루프로 가지 않는다
_TIMEOUT = 20.0

_KOREAN = "ko"
_ENGLISH = "en"

# 마지막 적재 시도 결과 — `GET /glossary` 와 번역 응답이 함께 본다
_LAST_LOAD: dict = {"loaded": False, "reason": "not_loaded", "languages": {}, "source": ""}


class _LoadFailed(Exception):
    """적재 실패. `reason` 이 `glossary.source.reason` 으로 나간다."""

    def __init__(self, reason: str, upstream_status: int = 0):
        super().__init__(reason)
        self.reason = reason
        self.upstream_status = upstream_status


def _base(base_url: str, glossary_id: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    return f"{base}/data/glossaries/{urllib.parse.quote(glossary_id)}"


async def _get_data(client: httpx.AsyncClient, url: str, headers: dict, params: dict = None):
    """공통 래퍼를 벗겨 `data` 를 돌려준다."""
    try:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        # 상태코드는 남기고 본문은 남기지 않는다 (3.8절). 401/403 과 5xx 는 관리자가
        # 할 일이 다르므로 사유에 상태코드를 함께 싣는다.
        status_code = exc.response.status_code
        raise _LoadFailed(f"fetch_failed_{status_code}", status_code) from exc
    except httpx.HTTPError as exc:
        raise _LoadFailed("fetch_failed") from exc
    except ValueError as exc:            # JSON 이 아니다
        raise _LoadFailed("invalid_response") from exc
    if not isinstance(payload, dict) or payload.get("code") not in (0, None):
        raise _LoadFailed("invalid_response")
    data = payload.get("data")
    return data if data is not None else {}


async def _fetch_attributes(client, base: str, headers: dict) -> list:
    data = await _get_data(client, f"{base}/attributes", headers)
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


async def _fetch_terms(client, base: str, headers: dict) -> list:
    """쪽을 끝까지 따라가며 원본 용어를 모은다 (`total_count` 도달 또는 빈 쪽에서 멈춤)."""
    items: list = []
    for page in range(1, _MAX_PAGES + 1):
        data = await _get_data(
            client, f"{base}/terms", headers, params={"pg": page, "pgSize": _PAGE_SIZE}
        )
        rows = data.get("list") if isinstance(data, dict) else None
        rows = rows if isinstance(rows, list) else []
        if not rows:
            break
        items.extend(rows)
        total = data.get("total_count")
        if len(rows) < _PAGE_SIZE or (isinstance(total, int) and len(items) >= total):
            break
    return items


def _attr_key(attributes: list, name: str) -> str:
    """속성 이름 → 키. 이름이 같은 속성이 없으면 키가 같은 속성을 쓴다."""
    for attr in attributes:
        if isinstance(attr, dict) and attr.get("name") == name:
            return str(attr.get("key") or "")
    for attr in attributes:
        if isinstance(attr, dict) and attr.get("key") == name:
            return str(attr.get("key") or "")
    return ""


def _representative_key(attributes: list) -> str:
    for attr in attributes:
        if isinstance(attr, dict) and attr.get("is_representative"):
            return str(attr.get("key") or "")
    return ""


def _text(value) -> str:
    """`text` 는 문자열, `text[]` 는 첫 비어 있지 않은 값."""
    if isinstance(value, list):
        value = next((v for v in value if str(v or "").strip()), "")
    return str(value or "").strip()


def _pairs_from_items(items: list, ko_key: str, en_key: str) -> tuple:
    """원본 용어 → `[(한국어, 영어)]` + 걸러진 사유별 건수. 같은 한국어는 처음 것만."""
    pairs: list = []
    seen: set = set()
    skipped: dict = {}
    for item in items:
        values = item.get("values") if isinstance(item, dict) else None
        if not isinstance(values, dict):
            skipped["not_an_object"] = skipped.get("not_an_object", 0) + 1
            continue
        ko, en = _text(values.get(ko_key)), _text(values.get(en_key))
        reason = "ko_empty" if not ko else "en_empty" if not en else ""
        if not reason and ko.casefold() in seen:
            reason = "duplicate_ko"
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        seen.add(ko.casefold())
        pairs.append((ko, en))
    return pairs, skipped


def _index_pairs(pairs: list) -> dict:
    """`(한국어, 영어)` 쌍을 **양방향**으로 색인한다 (머리말 참고)."""
    to_english = [GlossaryTerm(term_source=ko, term_target=en) for ko, en in pairs]
    to_korean = [GlossaryTerm(term_source=en, term_target=ko) for ko, en in pairs]
    load_terms(_ENGLISH, to_english)
    load_terms(_KOREAN, to_korean)
    return {_ENGLISH: term_count(_ENGLISH), _KOREAN: term_count(_KOREAN)}


def _fail(reason: str, **log_fields) -> dict:
    global _LAST_LOAD
    _LAST_LOAD = {"loaded": False, "reason": reason, "languages": {}, "source": "api"}
    log_warning(
        "용어사전 조회 실패 — 용어사전 없이 번역한다",
        event="glossary_fetch_failed",
        resource_id="glossary",
        error_type=reason,
        status="disabled",
        **log_fields,
    )
    return status()


async def load_from_admin_api(
    base_url: str, glossary_id: str, token: str, ko_attr: str = "ko", en_attr: str = "en"
) -> dict:
    """용어사전 API 에서 용어를 받아 양방향으로 색인한다.

    Returns:
        상태 dict (`status()` 와 같은 형식). **예외를 던지지 않는다** — 기동 경로에서
        불리므로 용어사전 문제로 컨테이너가 죽으면 안 된다.
    """
    global _LAST_LOAD
    clear_terms()

    if not (base_url and glossary_id):
        _LAST_LOAD = {"loaded": False, "reason": "not_configured", "languages": {}, "source": "api"}
        log_info(
            "용어사전 설정 미완료 — 용어사전 없이 번역한다",
            event="glossary_not_configured",
            resource_id="glossary",
            status="disabled",
        )
        return status()

    base = _base(base_url, glossary_id)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            attributes = await _fetch_attributes(client, base, headers)
            ko_key = _attr_key(attributes, ko_attr or "ko") or _representative_key(attributes)
            en_key = _attr_key(attributes, en_attr or "en")
            if not (ko_key and en_key):
                return _fail("attribute_not_found", item_count=len(attributes))
            items = await _fetch_terms(client, base, headers)
    except _LoadFailed as exc:
        extra = {"upstream_status": exc.upstream_status} if exc.upstream_status else {}
        return _fail(exc.reason, **extra)

    pairs, skipped = _pairs_from_items(items, ko_key, en_key)
    languages = _index_pairs(pairs) if pairs else {}

    _LAST_LOAD = {
        "loaded": bool(pairs),
        "reason": "ok" if pairs else "empty",
        "languages": languages,
        "source": "api",
    }
    skipped_text = ",".join(f"{reason}:{count}" for reason, count in sorted(skipped.items()))
    log_info(
        "용어사전 적재 완료",
        event="glossary_loaded",
        resource_id="glossary",
        item_count=len(pairs),
        # 걸러진 것이 있으면 사유별로 남긴다 — 값은 싣지 않는다
        status=f"received={len(items)},skipped={skipped_text or 'none'}",
    )
    return status()


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
    (`fetch_failed*`·`not_configured`)을 구분한다.
    """
    if is_disabled(target_lang):
        return {"available": False, "reason": "disabled_over_limit", "term_count": 0}
    count = term_count(target_lang)
    if not count:
        reason = "language_missing" if _LAST_LOAD["loaded"] else _LAST_LOAD["reason"]
        return {"available": False, "reason": reason, "term_count": 0}
    return {"available": True, "reason": "ok", "term_count": count}
