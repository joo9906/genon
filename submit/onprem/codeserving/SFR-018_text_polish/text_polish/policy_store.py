"""관리자가 등록한 톤·문서유형을 **GenOS 프롬프트 라이브러리**에서 받는다 (2026-08-18).

## 왜 만들었나

톤 지시문이 코드 상수(`tone_presets.py`)였다. 그러면 고객사 관리자가 어투를 바꾸거나
새 톤을 추가하려면 **코드 PR → 재빌드 → 재배포**를 거쳐야 한다. 가이드가 그걸
금지사항으로 못박아 뒀다 (§10.5 p.58 표, p.64):

> 코드 안 긴 문자열 인라인 / **코드 PR 로 프롬프트 변경** … 변경 시 코드 반영 절차가
> 필요하며 **비개발자가 수정하기 어렵다.**

§10.10.2 는 Prompt 리소스를 "**비개발자도 변경할 수 있어** 적용 절차가 비교적 단순하다"
고 소개한다. 이 모듈이 그 경로다.

## 무엇을 받나 — 프롬프트 본문에 **JSON** 을 담는다

`도구 > 프롬프트 라이브러리` 에 정책 프롬프트를 하나 만들고 그 ID 를
`POLISH_POLICY_PROMPT_ID` 로 주입한다. 본문 형식:

```json
{
  "tones": [
    {"code": "legal", "label": "법무체",
     "instruction": "법률 문서 어투로 다듬는다. 단정적 표현을 피하고 …"}
  ],
  "doc_types": [
    {"code": "contract", "label": "계약서", "forced_tone": "legal",
     "extra_instruction": "조항 번호와 정의 용어를 바꾸지 않는다."}
  ]
}
```

**본문이 프롬프트 문장이 아니라 JSON 인 이유**: 톤은 "문장 하나" 가 아니라 `code`·
`label`·`instruction` 이 묶인 **선택지**다. 화면 드롭다운(`label`)·판정(`code`)·
프롬프트(`instruction`)가 한 항목에서 나와야 셋이 갈리지 않는다. 톤마다 프롬프트를
따로 만들면 목록을 알 방법이 없다 — admin-api 에 **프롬프트 목록 조회 경로가 없다**
(가이드에 있는 것은 `GET /prompt/template/{id}` 하나뿐이다).

## 병합이지 대체가 아니다

관리자 항목은 내장 기본값(`tone_presets.py`) **위에 얹는다.** 같은 `code` 면 관리자
것이 이기고, 없는 `code` 는 추가된다. 대체로 만들면 관리자가 톤 하나만 등록했을 때
기존 셋이 통째로 사라진다 — 요구는 "추가" 다. 내장 톤을 감추려면 `"disabled": true`.

## 실패해도 죽지 않는다

설정이 없거나·조회가 실패하거나·JSON 이 깨졌으면 **내장 기본값으로 돈다.** 다만
조용히 그러지 않는다 — `source`/`reason` 을 `GET /policies` 응답에 실어 "관리자가 넣은
톤이 왜 안 보이나" 를 화면에서 답할 수 있게 한다. 불량 항목은 **사유별 건수**로 센다
(값 자체는 로그에 남기지 않는다 — 3.8절).
"""

import json
import time

import httpx

from text_polish.config import Config
from text_polish.logging_utils import log_info, log_warning

# 조회 결과를 이 초만큼 재사용한다. 매 요청 HTTP 를 때리면 화면 진입이 admin-api 지연에
# 묶이고, 무한 캐시면 관리자가 리비전을 운영 반영해도 재기동 전까지 안 바뀐다.
# `POST /policies/reload` 로 즉시 비울 수 있다 (용어사전 `/glossary/reload` 와 같은 규약).
_TTL_SECONDS = 60.0

_MAX_CODE_CHARS = 40
_MAX_LABEL_CHARS = 40
_MAX_INSTRUCTION_CHARS = 2000
_MAX_ITEMS = 50

_cache: dict = {}
_cache_at: float = 0.0


def _empty(reason: str) -> dict:
    return {"tones": {}, "doc_types": {}, "source": "builtin", "reason": reason, "rejected": {}}


def _reject(rejected: dict, why: str) -> None:
    rejected[why] = rejected.get(why, 0) + 1


def _clean(value, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def parse_policy_document(raw: str) -> dict:
    """프롬프트 본문(JSON)을 검증된 정책 dict 로 바꾼다.

    **예외를 던지지 않는다.** 관리자가 JSON 을 잘못 쓰는 것은 흔한 일이고, 그때 글다듬이
    전체가 멈추면 안 된다 — 내장 기본값으로 돌면서 사유를 노출한다.

    Returns:
        `{"tones": {code: {...}}, "doc_types": {...}, "source", "reason", "rejected"}`.
        `rejected` 는 **사유별 건수**다. 값 자체는 담지 않는다 (3.8절).
    """
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return _empty("invalid_json")
    if not isinstance(document, dict):
        return _empty("invalid_shape")

    rejected: dict = {}
    tones: dict = {}
    for item in (document.get("tones") or [])[:_MAX_ITEMS]:
        if not isinstance(item, dict):
            _reject(rejected, "tone_not_object")
            continue
        code = _clean(item.get("code"), _MAX_CODE_CHARS)
        if not code:
            _reject(rejected, "tone_code_missing")
            continue
        if item.get("disabled") is True:
            tones[code] = {"disabled": True}
            continue
        instruction = _clean(item.get("instruction"), _MAX_INSTRUCTION_CHARS)
        if not instruction:
            # 지시문 없는 톤을 받아들이면 **프롬프트에 톤 지시가 통째로 빠진 채** LLM 이
            # 돌고, 그 결과는 형식상 정상 응답으로 내려간다.
            _reject(rejected, "tone_instruction_missing")
            continue
        tones[code] = {
            "label": _clean(item.get("label"), _MAX_LABEL_CHARS) or code,
            "instruction": instruction,
            "disabled": False,
        }

    doc_types: dict = {}
    for item in (document.get("doc_types") or [])[:_MAX_ITEMS]:
        if not isinstance(item, dict):
            _reject(rejected, "doc_type_not_object")
            continue
        code = _clean(item.get("code"), _MAX_CODE_CHARS)
        if not code:
            _reject(rejected, "doc_type_code_missing")
            continue
        if item.get("disabled") is True:
            doc_types[code] = {"disabled": True}
            continue
        allowed = item.get("allowed_tones")
        doc_types[code] = {
            "label": _clean(item.get("label"), _MAX_LABEL_CHARS) or code,
            "extra_instruction": _clean(item.get("extra_instruction"), _MAX_INSTRUCTION_CHARS),
            "forced_tone": _clean(item.get("forced_tone"), _MAX_CODE_CHARS),
            "allowed_tones": tuple(
                _clean(t, _MAX_CODE_CHARS) for t in allowed if _clean(t, _MAX_CODE_CHARS)
            ) if isinstance(allowed, list) else (),
            "disabled": False,
        }

    return {
        "tones": tones,
        "doc_types": doc_types,
        "source": "prompt_library",
        "reason": "ok",
        "rejected": rejected,
    }


def _endpoint() -> str:
    return f"{Config.genos_admin_api_url()}/prompt/template/{Config.policy_prompt_id()}"


def _fetch() -> dict:
    """admin-api 에서 정책 프롬프트를 받아 파싱한다. 예외를 밖으로 내지 않는다."""
    if not (Config.genos_admin_api_url() and Config.policy_prompt_id()):
        return _empty("not_configured")

    try:
        response = httpx.get(_endpoint(), timeout=Config.POLICY_FETCH_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        # 상태코드는 남기고 본문은 남기지 않는다 (3.8절). 404 와 5xx 는 관리자가 할 일이
        # 다르다 — 전자는 ID 를 잘못 넣은 것이고 후자는 admin-api 장애다.
        return _empty(f"fetch_failed_{exc.response.status_code}")
    except Exception:  # noqa: BLE001 - 연결 실패·타임아웃·JSON 파싱까지
        return _empty("fetch_failed")

    # 가이드 §10.5 응답 계약: `{"code": 0, "data": "<본문>"}`.
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return _empty("api_error")
    body = payload.get("data")
    if not isinstance(body, str) or not body.strip():
        return _empty("empty_body")
    return parse_policy_document(body)


def load(*, force: bool = False) -> dict:
    """정책을 가져온다 (TTL 캐시). **기동 훅에서 부르지 않는다.**

    첫 요청에서 받는다 — import 나 기동에서 받으면 admin-api 가 느릴 때 "왜 안 뜨는지"
    가 드러나지 않는다(용어사전 MCP 와 같은 이유).
    """
    global _cache, _cache_at
    now = time.monotonic()
    if not force and _cache and (now - _cache_at) < _TTL_SECONDS:
        return _cache

    result = _fetch()
    _cache, _cache_at = result, now

    if result["source"] == "prompt_library":
        log_info(
            "관리자 정책 적재",
            event="policy_loaded",
            resource_id=f"prompt:{Config.policy_prompt_id()}",
            item_count=len(result["tones"]) + len(result["doc_types"]),
            status=f"rejected={sum(result['rejected'].values())}",
        )
    elif result["reason"] != "not_configured":
        # 설정을 넣었는데 못 읽은 경우만 경고다. 미설정은 정상 축퇴 경로다.
        log_warning(
            "관리자 정책을 읽지 못해 내장 기본값으로 동작한다",
            event="policy_load_failed",
            resource_id=f"prompt:{Config.policy_prompt_id()}",
            status=result["reason"],
        )
    return result


def reload() -> dict:
    """관리자가 리비전을 운영 반영한 뒤 부른다 (`POST /policies/reload`)."""
    return load(force=True)


def clear_cache() -> None:
    """점검용 — 캐시를 비운다."""
    global _cache, _cache_at
    _cache, _cache_at = {}, 0.0
