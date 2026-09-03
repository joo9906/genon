"""프롬프트 본문을 **GenOS 프롬프트 라이브러리**에서 받는다 (2026-09-03).

## 왜 만들었나

FAQ 의 프롬프트는 이미지에 함께 넣는 `.j2` 파일이었다. 그러면 문구 한 줄을 고치는 데
**코드 PR → 재빌드 → 재배포**가 필요하고, 가이드 §10.5 가 그걸 금지사항으로 못박아 뒀다
(p.58 표: "코드 PR 로 프롬프트 변경 … 비개발자가 수정하기 어렵다"). 글다듬이 톤·문서유형
정책이 2026-08-18 에 먼저 이 경로를 깔았고(`text_polish/policy_store.py`), FAQ 의 생성 지시문(개수·난이도·근거 표기)도 같은 성격이다 — 요구가 바뀔 때마다 손보게
되는 문장이다.

## 무엇을 라이브러리로 빼고 무엇을 파일로 두나 (요구 확정)

| | 자리 | 왜 |
|---|---|---|
| **자주 바뀌는 것** — 항목 매핑 지시, 톤·문서유형 | **프롬프트 라이브러리** | 비개발자가 고친다 |
| 고정 골격 — 시스템 프롬프트(출력 형식·금지 조항) | 파일(`.j2`) | 바뀌면 코드도 바뀐다 |

**둘 중 하나를 고르는 것이 아니다.** 라이브러리는 파일 위에 **덮어쓰는** 것이고, 파일은
기본값이자 폴백으로 남는다 — 시스템 프롬프트도 ID 를 주면 라이브러리가 이긴다.

## 이름 → ID 매핑

`FAQ_PROMPT_IDS` 하나에 담는다. 두 표기를 다 받는다:

    FAQ_PROMPT_IDS=system=41,user=42
    FAQ_PROMPT_IDS={"system": "41", "user": "42"}

이름은 **템플릿 파일 이름에서 확장자를 뗀 것**(`system.j2` → `system`)이다.
따로 이름표를 만들지 않는 이유는 그 순간 "파일 이름 ↔ 라이브러리 이름" 대조표가 하나 더
생기고, 어긋나면 **덮어쓰기가 조용히 일어나지 않기** 때문이다.

**ID 를 코드에 적지 않는다** (§10.5). 안 적힌 이름은 그냥 파일을 쓴다 — 미설정은 오류가
아니라 정상 경로다.

## 실패해도 대화를 막지 않는다 — 다만 조용하지 않다

조회 실패·본문 없음·렌더 실패는 **파일로 떨어진다.** 여기서 요청을 세우면 admin-api 장애가
이 기능 전체를 멈춘다.

대신 **조용히 옛 문구로 돌지 않게** 두 곳에 남긴다 — `event=prompt_library_failed` 로그와
`GET /prompts` 의 `source`/`reason`. 이게 없으면 관리자는 자기가 고친 문구가 왜 반영되지
않는지 알 방법이 없다(글다듬이 `policy.source` 와 같은 규약).

**파일도 없으면 그때는 요청을 세운다** — 지시문 없는 프롬프트로 LLM 을 돌리면 그 결과가
정상 응답처럼 내려간다. 그 판정은 `prompt_loader` 가 그대로 갖고 있다.
"""

import json
import time

import httpx

from .config import Config
from .logging_utils import log_info, log_warning

# 조회 결과를 이 초만큼 재사용한다. 매 요청 HTTP 를 때리면 요청 하나가 admin-api 지연에
# 묶이고, 무한 캐시면 관리자가 리비전을 운영 반영해도 재기동 전까지 안 바뀐다.
# `POST /prompts/reload` 로 즉시 비운다 (글다듬이 `/policies/reload` 와 같은 규약).
_TTL_SECONDS = 60.0

# 프롬프트 본문 상한. 관리자가 문서를 통째로 붙여 넣으면 그것이 매 요청 LLM 입력에
# 실린다 — 토큰 비용이 조용히 몇 배가 된다.
_MAX_BODY_CHARS = 20000

_cache: dict = {}          # {name: {"body": str|None, "reason": str}}
_cache_at: float = 0.0


def prompt_ids() -> dict:
    """`{템플릿 이름: 프롬프트 ID}`. 형식이 깨졌으면 **빈 dict** 다.

    파싱 실패를 예외로 올리지 않는다 — 환경변수 오타로 서빙이 안 뜨면 그 사실이
    "기능이 통째로 죽었다" 로 보인다. 빈 dict 면 파일로 돌고, 그 상태는
    `GET /prompts` 의 `configured: false` 로 드러난다.
    """
    raw = Config.prompt_ids_raw()
    if not raw:
        return {}

    if raw.lstrip().startswith("{"):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        if not isinstance(parsed, dict):
            return {}
        items = parsed.items()
    else:
        items = (
            (part.split("=", 1) + [""])[:2]
            for part in raw.split(",")
            if "=" in part
        )

    mapping = {}
    for name, value in items:
        key = str(name).strip()
        prompt_id = str(value).strip()
        if key and prompt_id:
            mapping[key] = prompt_id
    return mapping


def _endpoint(prompt_id: str) -> str:
    # 가이드 §10.5: `GET {admin-api}/prompt/template/{id}` → `{"code": 0, "data": "<본문>"}`.
    return f"{Config.genos_admin_api_url()}/prompt/template/{prompt_id}"


def _fetch_one(prompt_id: str) -> tuple:
    """`(본문|None, 사유)`. 본문이 있으면 사유는 `"prompt_library"` 다."""
    if not Config.genos_admin_api_url():
        return None, "not_configured"
    try:
        response = httpx.get(_endpoint(prompt_id), timeout=Config.PROMPT_FETCH_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        # 상태코드만 남기고 본문은 남기지 않는다 (3.8절). 404 는 ID 오기입이고 5xx 는
        # admin-api 장애다 — 관리자가 할 일이 다르다.
        return None, f"fetch_failed_{exc.response.status_code}"
    except Exception:  # noqa: BLE001 - 연결 실패·타임아웃·JSON 파싱까지
        return None, "fetch_failed"

    if not isinstance(payload, dict) or payload.get("code") != 0:
        return None, "api_error"
    body = payload.get("data")
    if not isinstance(body, str) or not body.strip():
        # 빈 본문을 받아들이면 **지시문 없는 프롬프트**가 되고, 그 결과는 형식상 정상
        # 응답으로 내려간다.
        return None, "empty_body"
    return body.strip()[:_MAX_BODY_CHARS], "prompt_library"


def load(*, force: bool = False) -> dict:
    """`{name: {"body", "reason"}}` — 설정된 이름만. **기동 훅에서 부르지 않는다.**

    첫 요청에서 받는다. import·기동에서 받으면 admin-api 가 느릴 때 "왜 안 뜨는지" 가
    드러나지 않는다(글다듬이 `policy_store`·용어사전 MCP 와 같은 이유).
    """
    global _cache, _cache_at
    now = time.monotonic()
    if not force and _cache and (now - _cache_at) < _TTL_SECONDS:
        return _cache

    result = {}
    for name, prompt_id in prompt_ids().items():
        body, reason = _fetch_one(prompt_id)
        result[name] = {"body": body, "reason": reason}
        if body is not None:
            log_info(
                "프롬프트 라이브러리 적재",
                event="prompt_library_loaded",
                resource_id=f"prompt:{prompt_id}",
                status=f"name={name} chars={len(body)}",
            )
        else:
            log_warning(
                "프롬프트 라이브러리를 읽지 못해 내장 파일로 동작한다",
                event="prompt_library_failed",
                resource_id=f"prompt:{prompt_id}",
                status=f"name={name} reason={reason}",
            )
    _cache, _cache_at = result, now
    return result


def body_for(name: str) -> str | None:
    """그 이름에 등록된 프롬프트 본문. 미설정·조회 실패면 `None`(→ 파일)."""
    return (load().get(name) or {}).get("body")


def status() -> list:
    """`GET /prompts` — 이름마다 어디서 왔는지.

    **관리자가 고친 문구가 왜 반영되지 않는지**를 화면에서 답할 수 있어야 한다. 이 값이
    없으면 "ID 를 안 넣었다" 와 "넣었는데 못 읽었다" 가 똑같이 옛 문구로 보인다.
    """
    ids = prompt_ids()
    loaded = load()
    rows = []
    for name in sorted(set(ids) | set(loaded)):
        entry = loaded.get(name) or {}
        configured = name in ids
        rows.append({
            "name": name,
            "configured": configured,
            # ID 자체는 싣는다 — 관리자가 화면에서 대조할 값이고 비밀이 아니다.
            "prompt_id": ids.get(name, ""),
            "source": "prompt_library" if entry.get("body") else "file",
            "reason": entry.get("reason", "not_configured" if not configured else ""),
        })
    return rows


def reload() -> list:
    """관리자가 리비전을 운영 반영한 뒤 부른다 (`POST /prompts/reload`)."""
    load(force=True)
    return status()


def clear_cache() -> None:
    """점검용 — 캐시를 비운다."""
    global _cache, _cache_at
    _cache, _cache_at = {}, 0.0
