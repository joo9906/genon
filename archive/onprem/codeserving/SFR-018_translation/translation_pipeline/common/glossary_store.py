"""용어사전 적재 — **GenOS AI 드라이브 용어사전 API** 에서 읽는다 (2026-08-14 전환).

## 무엇을 읽는가

플랫폼의 용어사전은 드라이브 단위로 `{용어명, 설명}` 을 관리하는 기능이다
(`용어사전.md` — 관리자 콘솔 → 데이터 → AI 드라이브 → 용어사전).

```
GET {ADMIN_API_URL}/data/ai-drive/{drive_id}/glossary/terms?pg=1&pgSize=200
    Authorization: Bearer {token}
    x-genos-workspace-id: {workspace_id}
```

**`용어명` 을 한국어 원문 용어, `설명` 을 영어 대응 용어로 읽는다.** 플랫폼 스펙에는
번역어를 담는 칸이 따로 없고(그 기능의 원래 목적은 임베딩·검색에서 한 토큰으로 다루는
것이다), 사내 운용이 설명 칸에 영문 용어를 적기로 확정됐다(2026-08-14). 그래서 그
매핑이 **이 파일 하나에만** 있다 — 나중에 플랫폼에 번역어 칸이 생기면 여기만 고친다.

## 양방향으로 색인한다

받은 것은 `(한국어, 영어)` 쌍 하나뿐이지만 번역 방향은 둘이다. `ko→en` 은 한국어를
찾아 영어를 강제하고, `en→ko` 는 그 반대다. 그래서 **같은 쌍을 뒤집어 두 언어에** 싣는다:

- `index["en"]`  source=용어명(한국어) → target=설명(영어)
- `index["ko"]`  source=설명(영어)   → target=용어명(한국어)

한쪽만 싣던 시절에는 `en→ko` 가 "적용 대상 방향인데 색인이 비어" 준수율 1.0 으로
나갔다 — 지키지 못한 것이 아니라 **지킬 것이 없다고 보고되는** 상태였다.
용어사전 적용 언어가 한국어·영어뿐이라(`languages.glossary_supported`) 이 두 색인이
전부다.

## 스펙에서 그대로 가져온 검증

플랫폼이 업로드 시점에 거르는 규칙과 같은 것을 여기서도 본다 — API 응답이 항상 그
규칙을 지킨다는 보장을 우리가 갖고 있지 않고(옛 버전에서 적재된 데이터가 남아 있을 수
있다), 걸러진 건수를 세어 두면 "왜 이 용어가 안 걸리나" 를 답할 수 있다.

| 대상 | 규칙 |
|---|---|
| 용어명 | 필수 · 30자 이하 · 금지문자(`\\ / : * ? " < > |`) 없음 · 공백만 불가 |
| 설명 | **번역어로 쓰므로 여기서는 필수** · 500자 이하 |
| 중복 | 같은 용어명이 두 번 오면 **처음 것만** 쓴다 |
| 건수 | 드라이브당 2,000건 (플랫폼 한도) |

## 실패 처리

**받지 못해도 번역은 계속하고 그 사실을 남긴다.** 용어사전은 품질 장치이고, 없다고
번역을 못 하는 것은 아니다. 대신 상태(`status()`)를 `GET /glossary` 와 번역 응답에
실어 "적용된 줄 알았는데 아니었다" 가 생기지 않게 한다.
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

# 플랫폼 스펙(`용어사전.md`)의 값. 우리가 정한 값이 아니라 **옮겨 적은 값**이다.
_MAX_TERM_CHARS = 30
_MAX_DESCRIPTION_CHARS = 500
_MAX_TERMS = 2000
_FORBIDDEN_CHARS = set('\\/:*?"<>|')

_PAGE_SIZE = 200
_MAX_PAGES = 50          # 2,000건 / 200 = 10 페이지. 응답이 이상해도 무한 루프로 가지 않는다
_TIMEOUT = 20.0

_KOREAN = "ko"
_ENGLISH = "en"

# 마지막 적재 시도 결과 — `GET /glossary` 와 번역 응답이 함께 본다
_LAST_LOAD: dict = {"loaded": False, "reason": "not_loaded", "languages": {}, "source": ""}


def _endpoint(base_url: str, drive_id: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    return f"{base}/data/ai-drive/{urllib.parse.quote(drive_id)}/glossary/terms"


def _valid_pair(term: str, description: str) -> str:
    """걸러야 하면 사유 코드를, 쓸 수 있으면 빈 문자열을 돌려준다.

    사유를 문자열로 돌려주는 이유: 건수만 세면 "몇 건 빠졌다" 는 알아도 **무엇을
    고쳐야 하는지** 는 알 수 없다. 용어명·설명 값 자체는 로그에 남기지 않는다(3.8절).
    """
    if not term:
        return "term_empty"
    if len(term) > _MAX_TERM_CHARS:
        return "term_too_long"
    if any(char in _FORBIDDEN_CHARS for char in term):
        return "term_forbidden_char"
    if not description:
        # 설명이 곧 번역어다. 비어 있으면 "이 용어는 이렇게 옮긴다" 가 성립하지 않는다.
        return "description_empty"
    if len(description) > _MAX_DESCRIPTION_CHARS:
        return "description_too_long"
    return ""


def _pairs_from_items(items: list) -> tuple:
    """API 항목 목록 → `[(용어명, 설명)]` + 걸러진 사유별 건수."""
    pairs: list = []
    seen: set = set()
    skipped: dict = {}
    for item in items:
        if not isinstance(item, dict):
            skipped["not_an_object"] = skipped.get("not_an_object", 0) + 1
            continue
        term = str(item.get("term") or "").strip()
        description = str(item.get("description") or "").strip()
        reason = _valid_pair(term, description)
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        key = term.casefold()
        if key in seen:
            skipped["duplicate_term"] = skipped.get("duplicate_term", 0) + 1
            continue
        seen.add(key)
        pairs.append((term, description))
        if len(pairs) >= _MAX_TERMS:
            break
    return pairs, skipped


def _index_pairs(pairs: list) -> dict:
    """`(한국어, 영어)` 쌍을 **양방향**으로 색인한다 (머리말 참고)."""
    to_english = [GlossaryTerm(term_source=ko, term_target=en) for ko, en in pairs]
    to_korean = [GlossaryTerm(term_source=en, term_target=ko) for ko, en in pairs]
    load_terms(_ENGLISH, to_english)
    load_terms(_KOREAN, to_korean)
    return {_ENGLISH: term_count(_ENGLISH), _KOREAN: term_count(_KOREAN)}


async def _fetch_items(url: str, headers: dict) -> list:
    """페이지를 끝까지 따라가며 항목을 모은다.

    응답 모양이 배포마다 조금씩 다를 수 있어 `items`/`data`/`list`/최상위 배열을 모두
    받는다 — 한 가지만 보고 빈손으로 끝나면 "용어사전이 비어 있다" 로 보이는데, 그건
    사전이 없는 것과 구분되지 않는다.
    """
    items: list = []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for page in range(1, _MAX_PAGES + 1):
            response = await client.get(
                url, headers=headers, params={"pg": page, "pgSize": _PAGE_SIZE}
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                page_items = payload
            elif isinstance(payload, dict):
                page_items = (
                    payload.get("items")
                    or payload.get("data")
                    or payload.get("list")
                    or []
                )
                if isinstance(page_items, dict):        # {"data": {"items": [...]}}
                    page_items = page_items.get("items") or []
            else:
                page_items = []
            if not isinstance(page_items, list) or not page_items:
                break
            items.extend(page_items)
            if len(page_items) < _PAGE_SIZE or len(items) >= _MAX_TERMS:
                break
    return items


async def load_from_admin_api(base_url: str, drive_id: str, workspace_id: str, token: str) -> dict:
    """용어사전 API 에서 용어를 받아 양방향으로 색인한다.

    Returns:
        상태 dict (`status()` 와 같은 형식). **예외를 던지지 않는다** — 기동 경로에서
        불리므로 용어사전 문제로 컨테이너가 죽으면 안 된다.
    """
    global _LAST_LOAD
    clear_terms()

    if not (base_url and drive_id and workspace_id):
        _LAST_LOAD = {"loaded": False, "reason": "not_configured", "languages": {}, "source": "api"}
        log_info(
            "용어사전 설정 미완료 — 용어사전 없이 번역한다",
            event="glossary_not_configured",
            resource_id="glossary",
            status="disabled",
        )
        return status()

    url = _endpoint(base_url, drive_id)
    headers = {"x-genos-workspace-id": workspace_id}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        items = await _fetch_items(url, headers)
    except httpx.HTTPStatusError as exc:
        # 상태코드는 남기고 본문은 남기지 않는다 (3.8절). 401/403 과 5xx 는 관리자가
        # 할 일이 다르므로 사유에 상태코드를 함께 싣는다.
        _LAST_LOAD = {
            "loaded": False,
            "reason": f"fetch_failed_{exc.response.status_code}",
            "languages": {},
            "source": "api",
        }
        log_warning(
            "용어사전 조회 실패 — 용어사전 없이 번역한다",
            event="glossary_fetch_failed",
            resource_id="glossary",
            upstream_status=exc.response.status_code,
            error_type=type(exc).__name__,
            status="disabled",
        )
        return status()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        _LAST_LOAD = {"loaded": False, "reason": "fetch_failed", "languages": {}, "source": "api"}
        log_warning(
            "용어사전 조회 실패 — 용어사전 없이 번역한다",
            event="glossary_fetch_failed",
            resource_id="glossary",
            error_type=type(exc).__name__,
            status="disabled",
        )
        return status()

    pairs, skipped = _pairs_from_items(items)
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
        # 어디서 받은 것인가 — 파일 시절과 구분된다. 화면·운영이 출처를 물을 때 쓴다.
        "source": _LAST_LOAD.get("source", ""),
    }


def language_status(target_lang: str) -> dict:
    """특정 언어의 적용 가능 여부 — 번역 응답에 싣는다.

    `disabled_over_limit` 는 사전이 너무 커서 색인을 포기한 상태다. 2단계(벡터 검색)
    폴백이 없으므로 그 언어는 용어사전 없이 번역된다 — 반드시 노출한다.

    **적재 실패 이유와 언어별 이유를 섞지 않는다.** 예전에는 정상 적재됐는데 그 언어
    항목만 없을 때 `{"available": false, "reason": "ok"}` 가 나갔다 — 화면이
    "적용 안 됨(사유: ok)" 을 받는 셈이라 관리자가 무엇을 고쳐야 하는지 알 수 없다.
    지금은 `language_missing` 으로 갈라, **용어를 채울 일**과 **아예 못 받은 일**
    (`fetch_failed*`·`not_configured`)을 구분한다.
    """
    if is_disabled(target_lang):
        return {"available": False, "reason": "disabled_over_limit", "term_count": 0}
    count = term_count(target_lang)
    if not count:
        reason = "language_missing" if _LAST_LOAD["loaded"] else _LAST_LOAD["reason"]
        return {"available": False, "reason": reason, "term_count": 0}
    return {"available": True, "reason": "ok", "term_count": count}
