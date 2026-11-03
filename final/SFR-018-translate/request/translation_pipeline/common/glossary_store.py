"""용어사전 적재 — **GenOS 독립 용어사전(`데이터 > 용어사전`) API** 에서 읽는다.

## 무엇을 읽는가

```
GET {API_URL}/data/glossaries/{glossary_id}/attributes          # 속성 이름 → 키
GET {API_URL}/data/glossaries/{glossary_id}/terms?pg=N&pgSize=200
    Authorization: Bearer {token}
```

응답은 공통 래퍼 `{code, message, data}` 이고 `code` 가 0 이 아니면 실패다. 속성은
`data.items`, 용어는 `data.list`(+ `data.total_count`)에 온다. 용어의 값은
`values = {속성 키: 값}` 이다.

**이름이 `ko` / `en` 인 속성을 한국어 · 영어로 읽는다**(이름이 없으면 키가 같은 속성).
`ko` 속성이 없으면 **대표어**(`is_representative`)를 한국어로 쓴다 — 운영은 대표어에
한국어, `en` 속성에 영어를 넣는다. 속성 이름은 `TRANSLATE_GLOSSARY_KO_ATTR` ·
`TRANSLATE_GLOSSARY_EN_ATTR` 로 바꿀 수 있다. 값이 `text[]` 이면 첫 비어 있지 않은 값을 쓴다.

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

한국어나 영어가 비었으면, 그리고 같은 한국어(대소문자 무시)가 두 번 오면 처음 것만
쓴다. 걸러진 건수를 사유별로 세어 로그에 남긴다 — "왜 이 용어가 안 걸리나" 를 답하려면
몇 건이 무슨 이유로 빠졌는지가 있어야 한다. 값 자체는 남기지 않는다(3.8절).

## 실패 처리

**받지 못해도 번역은 계속하고 그 사실을 남긴다.** 용어사전은 품질 장치이고, 없다고
번역을 못 하는 것은 아니다. 대신 상태(`status()`)를 `GET /glossary` 와 번역 응답에
실어 "적용된 줄 알았는데 아니었다" 가 생기지 않게 한다. 사유:

| reason | 뜻 |
|---|---|
| `not_configured` | 용어사전 id 가 없다 |
| `fetch_failed_{HTTP}` / `fetch_failed` | 응답 상태코드 오류 / 연결 실패 |
| `invalid_response` | JSON 이 아니거나 래퍼 `code` 가 0 이 아니다 |
| `attribute_not_found` | 한국어·영어 속성을 찾지 못했다 |
| `empty` | 받았지만 쓸 수 있는 쌍이 없다 |
"""

import json
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


class _LoadError(Exception):
    """적재를 멈추는 사유. `reason` 이 그대로 `status()["reason"]` 이 된다."""

    def __init__(self, reason: str, upstream_status: int = 0):
        super().__init__(reason)
        self.reason = reason
        self.upstream_status = upstream_status


def _base(api_url: str, glossary_id: str) -> str:
    return f"{(api_url or '').strip().rstrip('/')}/data/glossaries/{urllib.parse.quote(glossary_id)}"


async def _get_data(client: httpx.AsyncClient, url: str, headers: dict, params: dict = None):
    """GET 한 번 → 래퍼를 벗긴 `data`. 래퍼 `code` 가 0 이 아니면 실패다."""
    response = await client.get(url, headers=headers, params=params)
    if response.status_code >= 400:
        raise _LoadError(f"fetch_failed_{response.status_code}", response.status_code)
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise _LoadError("invalid_response") from exc
    if not isinstance(payload, dict) or payload.get("code") not in (0, None):
        raise _LoadError("invalid_response")
    data = payload.get("data")
    return data if data is not None else {}


async def _fetch(api_url: str, glossary_id: str, token: str) -> tuple:
    """속성 정의와 모든 쪽의 원본 용어를 받는다 → `(attributes, items)`."""
    base = _base(api_url, glossary_id)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    items: list = []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        data = await _get_data(client, f"{base}/attributes", headers)
        attributes = data.get("items") if isinstance(data, dict) else None
        attributes = attributes if isinstance(attributes, list) else []
        for page in range(1, _MAX_PAGES + 1):
            data = await _get_data(client, f"{base}/terms", headers,
                                   {"pg": page, "pgSize": _PAGE_SIZE})
            rows = data.get("list") if isinstance(data, dict) else None
            rows = rows if isinstance(rows, list) else []
            if not rows:
                break
            items.extend(rows)
            total = data.get("total_count")
            if len(rows) < _PAGE_SIZE or (isinstance(total, int) and len(items) >= total):
                break
    return attributes, items


def _attr_key(attributes: list, name: str) -> str:
    """속성 이름 → 키. 이름이 없으면 키가 같은 속성을 쓴다."""
    for attr in attributes:
        if isinstance(attr, dict) and attr.get("name") == name:
            return str(attr.get("key") or "")
    for attr in attributes:
        if isinstance(attr, dict) and attr.get("key") == name:
            return str(attr.get("key") or "")
    return ""


def _resolve_keys(attributes: list, ko_attr: str, en_attr: str) -> tuple:
    """`(ko 키, en 키)`. ko 속성이 따로 없으면 대표어를 한국어로 쓴다."""
    ko_key = _attr_key(attributes, ko_attr) or next(
        (str(a.get("key") or "") for a in attributes
         if isinstance(a, dict) and a.get("is_representative")),
        "",
    )
    return ko_key, _attr_key(attributes, en_attr)


def _text(value) -> str:
    """text 는 문자열, text[] 는 첫 비어 있지 않은 값을 쓴다."""
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


def _fail(reason: str, **fields) -> dict:
    global _LAST_LOAD
    _LAST_LOAD = {"loaded": False, "reason": reason, "languages": {}, "source": "api"}
    log_warning(
        "용어사전 조회 실패 — 용어사전 없이 번역한다",
        event="glossary_fetch_failed",
        resource_id="glossary",
        status=f"disabled,reason={reason}",
        **fields,
    )
    return status()


async def load_from_admin_api(
    api_url: str, glossary_id: str, token: str, ko_attr: str = _KOREAN, en_attr: str = _ENGLISH
) -> dict:
    """용어사전 API 에서 용어를 받아 양방향으로 색인한다.

    Returns:
        상태 dict (`status()` 와 같은 형식). **예외를 던지지 않는다** — 기동 경로에서
        불리므로 용어사전 문제로 컨테이너가 죽으면 안 된다.
    """
    global _LAST_LOAD
    clear_terms()

    if not (api_url and glossary_id):
        _LAST_LOAD = {"loaded": False, "reason": "not_configured", "languages": {}, "source": "api"}
        log_info(
            "용어사전 설정 미완료 — 용어사전 없이 번역한다",
            event="glossary_not_configured",
            resource_id="glossary",
            status="disabled",
        )
        return status()

    try:
        attributes, items = await _fetch(api_url, glossary_id, token)
    except _LoadError as exc:
        # 상태코드는 남기고 본문은 남기지 않는다 (3.8절). 401/403 과 5xx 는 관리자가
        # 할 일이 다르므로 사유에 상태코드를 함께 싣는다.
        extra = {"upstream_status": exc.upstream_status} if exc.upstream_status else {}
        return _fail(exc.reason, **extra)
    except (httpx.HTTPError, OSError) as exc:
        return _fail("fetch_failed", error_type=type(exc).__name__)

    ko_key, en_key = _resolve_keys(attributes, ko_attr or _KOREAN, en_attr or _ENGLISH)
    if not (ko_key and en_key):
        return _fail("attribute_not_found", item_count=len(attributes))

    pairs, skipped = _pairs_from_items(items, ko_key, en_key)
    languages = _index_pairs(pairs) if pairs else {}

    _LAST_LOAD = {
        "loaded": bool(pairs),
        "reason": "ok" if pairs else "empty",
        "languages": languages,
        "source": "api",
    }
    log_info(
        "용어사전 적재 완료",
        event="glossary_loaded",
        resource_id="glossary",
        item_count=len(pairs),
        # 걸러진 것이 있으면 사유별로 남긴다 — 값은 싣지 않는다
        status=f"received={len(items)},skipped={json.dumps(skipped, ensure_ascii=False)}",
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
