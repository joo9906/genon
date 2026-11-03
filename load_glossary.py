# 테스트용 등록 예시 — 사전에 속성 `en`(text) 을 추가하고, 대표어에 한국어 · en 에 영어를 넣어 보세요.
#
#   ko (한국어)        en (영어)
#   제논               GenOn
#   젠오에스           GenOS
#   젠포탈             GenPortal
#   젠빌더             GenBuilder
#   용어사전           Glossary
#   워크플로우         Workflow
#   AI 드라이브        AI Drive
#   재인덱싱           Reindexing
#   변경 승인          Change Approval
#   경영지원실         Management Support Team
#
# 한국어는 대표어를 쓴다(이름이 `ko` 인 속성을 따로 만들면 그쪽이 우선).
# 용어 추가는 변경 승인을 거치므로, 승인 후에 조회됩니다.

"""GenOS 용어사전(독립 `데이터 > 용어사전`)에서 번역용 ko/en 쌍을 불러온다.

    GET {API_URL}/data/glossaries/{glossary_id}/attributes   # 속성 이름 -> 키 매핑
    GET {API_URL}/data/glossaries/{glossary_id}/terms?pg=N&pgSize=200
        Authorization: Bearer {token}

용어의 값은 `values = {속성 키: 값}` 로 내려온다. 사전에 정의한 속성 중
**이름이 `ko` / `en` 인 속성**을 한국어 · 영어로 읽는다(이름이 없으면 키가 같은 속성).
`ko` 속성이 없으면 대표어를 한국어로 쓴다 — 대표어에 한국어, `en` 속성에 영어를 넣으면 된다.

환경변수:

    GLOSSARY_API_URL       admin-api 베이스. 비우면 https://genos.genon.ai/api/admin
    GLOSSARY_ID            용어사전 id (필수)
    GLOSSARY_TOKEN         admin-api 토큰. 비우면 GENOS_TOKEN
    GLOSSARY_KO_ATTR       한국어 속성 이름 (기본 ko, 없으면 대표어)
    GLOSSARY_EN_ATTR       영어 속성 이름 (기본 en)

실행:

    python call_gl.py          # 진행 · 요약 · 채택한 쌍(`ko -> en`)을 찍는다
    python call_gl.py --raw    # 속성 정의와 원본 용어를 그대로 찍는다
    python call_gl.py --find "젠포탈에서 워크플로우를 실행한다"      # 문장 속 용어 찾기(ko→en)
    python call_gl.py --find "Open the workflows" --source en       # en→ko

코드에서:

    from call_gl import load_glossary
    pairs, report = load_glossary()   # pairs = [{"ko": ..., "en": ...}]
    hits = find_terms("젠포탈에서 워크플로우 실행", pairs)   # 하드매칭(Weaviate·벡터 없음)

stdlib 만 쓴다(urllib). 토큰 값은 찍지 않는다.
"""

import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

_DEFAULT_API_URL = "https://genos.genon.ai/api/admin"
_PAGE_SIZE = 200
_MAX_PAGES = 500          # 응답이 이상해도 무한 루프로 가지 않는다
_TIMEOUT = 20.0


class GlossaryLoadError(Exception):
    """설정 누락 · 통신 실패 · 응답 형식 오류. `reason` 이 원인을 가른다."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _settings() -> dict:
    env = os.environ.get
    return {
        "api_url": (env("GLOSSARY_API_URL", "").strip() or _DEFAULT_API_URL).rstrip("/"),
        "glossary_id": env("GLOSSARY_ID", "").strip(),
        "token": env("GLOSSARY_TOKEN", "").strip() or env("GENOS_TOKEN", "").strip(),
        "ko_attr": env("GLOSSARY_KO_ATTR", "").strip() or "ko",
        "en_attr": env("GLOSSARY_EN_ATTR", "").strip() or "en",
    }


def _get_json(url: str, headers: dict):
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise GlossaryLoadError(f"fetch_failed_{exc.code}", f"용어사전 조회 실패 (HTTP {exc.code})") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GlossaryLoadError("fetch_failed", f"용어사전 API 에 연결하지 못했습니다 ({type(exc).__name__})") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GlossaryLoadError("invalid_response", "용어사전 응답이 JSON 이 아닙니다") from exc
    # 공통 래퍼 {code, message, data}. code 가 0 이 아니면 실패.
    if not isinstance(payload, dict) or payload.get("code") not in (0, None):
        raise GlossaryLoadError("invalid_response", f"용어사전 응답 오류: {str(payload)[:120]}")
    data = payload.get("data")
    return data if data is not None else {}


def _headers(settings: dict) -> dict:
    headers = {"Accept": "application/json"}
    if settings["token"]:
        headers["Authorization"] = f"Bearer {settings['token']}"
    return headers


def _base(settings: dict) -> str:
    return f"{settings['api_url']}/data/glossaries/{urllib.parse.quote(settings['glossary_id'])}"


def fetch_attributes(settings: dict) -> list:
    data = _get_json(f"{_base(settings)}/attributes", _headers(settings))
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def fetch_terms(settings: dict) -> list:
    """모든 쪽을 따라가며 원본 용어를 모은다 (`total_count` 도달 또는 빈 쪽에서 멈춤)."""
    headers = _headers(settings)
    items: list = []
    for page in range(1, _MAX_PAGES + 1):
        query = urllib.parse.urlencode({"pg": page, "pgSize": _PAGE_SIZE})
        data = _get_json(f"{_base(settings)}/terms?{query}", headers)
        rows = data.get("list") if isinstance(data, dict) else None
        rows = rows if isinstance(rows, list) else []
        print(f"[page {page}] 항목 {len(rows)}건")
        if not rows:
            break
        items.extend(rows)
        total = data.get("total_count")
        if len(rows) < _PAGE_SIZE or (isinstance(total, int) and len(items) >= total):
            break
    return items


def _attr_key(attributes: list, name: str) -> str:
    """속성 이름 → 키. 이름이 없으면 키가 같은 속성을 쓴다."""
    for attr in attributes:
        if isinstance(attr, dict) and attr.get("name") == name:
            return str(attr.get("key") or "")
    for attr in attributes:
        if isinstance(attr, dict) and attr.get("key") == name:
            return str(attr.get("key") or "")
    return ""


def _text(value) -> str:
    """text 는 문자열, text[] 는 첫 비어있지 않은 값을 쓴다."""
    if isinstance(value, list):
        value = next((v for v in value if str(v or "").strip()), "")
    return str(value or "").strip()


def to_pairs(items: list, ko_key: str, en_key: str) -> tuple:
    """원본 용어 → (채택 쌍, 사유별 기각 건수). 같은 ko 는 처음 것만 쓴다."""
    pairs: list = []
    skipped: dict = {}
    seen: set = set()
    for item in items:
        values = item.get("values") if isinstance(item, dict) else None
        if not isinstance(values, dict):
            skipped["not_object"] = skipped.get("not_object", 0) + 1
            continue
        ko, en = _text(values.get(ko_key)), _text(values.get(en_key))
        reason = "ko_empty" if not ko else "en_empty" if not en else ""
        if not reason and ko.casefold() in seen:
            reason = "duplicate_ko"
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        seen.add(ko.casefold())
        pairs.append({"ko": ko, "en": en})
    return pairs, skipped


def _norm(text: str) -> str:
    """NFKC · 소문자 · 공백 압축 — 전각/대소문자/공백 차이를 흡수한다."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "")).casefold().strip()


_HANGUL = re.compile(r"[가-힣]")


def _term_regex(term: str):
    """한글이 든 용어는 부분일치(조사·어미가 붙어도 잡힘), 영문 용어는 단어 경계 + 복수형(s/es) 허용."""
    escaped = re.escape(term)
    if _HANGUL.search(term):
        return re.compile(escaped)
    return re.compile(rf"(?<![a-z0-9]){escaped}(?:e?s)?(?![a-z0-9])")


def find_terms(text: str, pairs: list, source: str = "ko") -> list:
    """문장에서 사전 용어를 찾는다 — 하드매칭(정규화 · 복수형 · 긴 용어 우선 · 겹침 제외).

    source="ko" 면 ko 용어를 찾아 en 을 돌려주고, "en" 이면 반대다.
    → [{"ko", "en", "matched", "start"}] 문장 등장 순서.
    """
    if source not in ("ko", "en"):
        raise ValueError("source 는 'ko' 또는 'en'")
    haystack = _norm(text)
    covered: list = []   # 이미 쓰인 구간 [(start, end)] — 긴 용어가 먼저 차지한다
    hits: list = []
    for pair in sorted(pairs, key=lambda p: len(p[source]), reverse=True):
        term = _norm(pair[source])
        if not term:
            continue
        for m in _term_regex(term).finditer(haystack):
            start, end = m.span()
            if any(start < c_end and end > c_start for c_start, c_end in covered):
                continue
            covered.append((start, end))
            hits.append({"ko": pair["ko"], "en": pair["en"], "matched": haystack[start:end], "start": start})
    return sorted(hits, key=lambda h: h["start"])


def _check(settings: dict) -> None:
    if not settings["glossary_id"]:
        raise GlossaryLoadError("not_configured", "환경변수 없음: GLOSSARY_ID")


def load_glossary() -> tuple:
    """환경변수로 용어사전을 불러온다. → (`[{"ko", "en"}]`, report)."""
    settings = _settings()
    _check(settings)
    print(f"GET {_base(settings)}")
    print(f"token: {'있음' if settings['token'] else '없음'}")

    attributes = fetch_attributes(settings)
    # ko 속성이 따로 없으면 대표어(이름 `대표어` · 키 `text` 고정)를 한국어로 쓴다.
    ko_key = _attr_key(attributes, settings["ko_attr"]) or next(
        (str(a.get("key") or "") for a in attributes if isinstance(a, dict) and a.get("is_representative")), "")
    en_key = _attr_key(attributes, settings["en_attr"])
    absent = [n for n, k in ((settings["ko_attr"], ko_key), (settings["en_attr"], en_key)) if not k]
    if absent:
        names = ", ".join(str(a.get("name")) for a in attributes if isinstance(a, dict))
        raise GlossaryLoadError("attribute_not_found", f"속성 없음: {', '.join(absent)} (사전 속성: {names})")
    print(f"속성 매핑: ko={ko_key} en={en_key}")

    items = fetch_terms(settings)
    pairs, skipped = to_pairs(items, ko_key, en_key)
    report = {"received": len(items), "adopted": len(pairs), "skipped": skipped,
              "reason": "ok" if pairs else "empty"}
    return pairs, report


def main(argv: list) -> int:
    try:
        if "--raw" in argv:
            settings = _settings()
            _check(settings)
            print(f"GET {_base(settings)}")
            attributes = fetch_attributes(settings)
            items = fetch_terms(settings)
            print(f"\n속성 {len(attributes)}건")
            print(json.dumps(attributes, ensure_ascii=False, indent=2))
            print(f"\n원본 용어 {len(items)}건")
            print(json.dumps(items, ensure_ascii=False, indent=2))
            return 0
        pairs, report = load_glossary()
        if "--find" in argv:
            index = argv.index("--find")
            sentence = argv[index + 1] if index + 1 < len(argv) else ""
            source = argv[argv.index("--source") + 1] if "--source" in argv else "ko"
            print(f"\n문장: {sentence}  (source={source})")
            for hit in find_terms(sentence, pairs, source):
                print(f"  {hit['matched']} -> {hit['en'] if source == 'ko' else hit['ko']}")
            return 0
    except GlossaryLoadError as exc:
        print(f"\n실패: {exc} (reason={exc.reason})")
        return 1

    print(f"\n받음 {report['received']}건 / 채택 {report['adopted']}건")
    for reason, count in report["skipped"].items():
        print(f"  기각 {reason}: {count}건")
    print()
    for pair in pairs:
        print(f"  {pair['ko']} -> {pair['en']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
