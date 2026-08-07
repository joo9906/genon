"""프롬프트 로더 — 파일(jinja) 또는 GenOS Prompt 리소스에서 문구를 가져온다.

## 두 소스, 하나의 계약

`POLISH_PROMPT_SOURCE` 로 고른다:
- `file`(기본) — `onprem/prompt/SFR-018_text_polish/<이름>.j2`
- `genos` — GenOS Prompt 리소스 (가이드 §10.5)

**어느 쪽이든 받아온 문자열을 jinja 로 렌더한다.** admin-api 는 본문 문자열만
돌려주고 템플릿 엔진이 딸려 오지 않으므로(`payload["data"]`), 프롬프트 라이브러리에
**jinja 원문을 그대로 등록**해 두면 제어문이 전부 살아 있다.
(Flowise `MNC Prompt` 노드의 단일 중괄호 치환은 **그 노드의 동작**이지 API 계약이
아니다. 그 노드로는 우리 프롬프트를 못 쓴다 — 본문의 JSON 예시를 변수로 읽는다.)

## GenOS 경로 (§10.5)

    GET {GENOS_ADMIN_API_URL}/prompt/template/{prompt_id}

- **Gateway 가 아니라 admin-api 다.** `/api/gateway/prompt/...` 는 없다.
  내부 `http://llmops-admin-api-service:8080`, 외부 `https://<host>/api/admin`.
- **인증 헤더가 없다** (확인된 사실 — 프롬프트 라이브러리는 무인증).
- 응답 `{code, data, errMsg}`. **`code != 0` 이면 HTTP 200 이어도 실패**다.
- `prompt_id` 는 GenOS 가 발급하는 정수다. 코드에 박지 않고
  `POLISH_PROMPT_ID_<이름 대문자>` 환경변수로 받는다 (§10.5 금지 조항).

## 실패를 폴백으로 감추지 않는다

`genos` 로 설정했는데 조회에 실패하면 **파일로 몰래 떨어지지 않고 세운다.** 떨어지면
"라이브러리 연동이 되고 있다"고 믿는 채로 옛 파일 문구가 나가고, 관리자가 라이브러리에서
고친 문구가 왜 반영이 안 되는지 알 방법이 없다. 템플릿이 없을 때 빈 프롬프트로 넘어가지
않는 것과 같은 판단이다.

## 캐시

프롬프트는 요청마다 바뀌지 않는데 조회는 HTTP 다. 번역은 배치마다 시스템 프롬프트를
만들므로 캐시가 없으면 한 번역 작업이 admin-api 호출 수십 회가 된다.
`POLISH_PROMPT_TTL_SECONDS`(기본 300) 동안 본문을 들고 있는다 — 리비전을 운영에
반영하면 그 시간 안에 따라온다. `0` 이면 매번 조회한다.

## 기동 점검

`genos` 소스일 때 코드 서빙은 기동 시 `probe()` 를 불러 도달 여부를 로그로 남긴다.
admin-api 는 Gateway 경유가 아니라 내부 서비스 직통이라 네트워크가 닿는지는 찔러 봐야만
안다. 첫 요청에서야 드러나면 사용자 요청 하나를 잃고 알게 된다.
워크플로우(02)는 기동 훅이 없어 첫 렌더가 그 역할을 한다.
"""

import os
import time
from functools import lru_cache

from .logging_utils import log_info, log_warning

_DEFAULT_PROMPT_DIRNAME = os.path.join("prompt", "SFR-018_text_polish")
# 저장 형식(확장자)은 이 모듈만 안다 — 호출부는 논리 이름만 넘긴다.
_TEMPLATE_SUFFIX = ".j2"

SOURCE_FILE = "file"
SOURCE_GENOS = "genos"

# {이름: (본문, 받은 시각)} — genos 소스 전용
_CACHE: dict = {}


class PromptRenderError(RuntimeError):
    """프롬프트를 가져오지 못했거나 렌더에 실패.

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다
    (템플릿 경로·jinja 예외 원문·admin-api 응답을 사용자에게 노출하지 않는다 — 3.8절).
    """


def source() -> str:
    """`file`(기본) 또는 `genos`. 알 수 없는 값은 파일로 본다."""
    value = os.environ.get("POLISH_PROMPT_SOURCE", SOURCE_FILE).strip().lower()
    return SOURCE_GENOS if value == SOURCE_GENOS else SOURCE_FILE


def prompt_dir() -> str:
    override = os.environ.get("POLISH_PROMPT_DIR", "").strip()
    if override:
        return override
    unit_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(os.path.dirname(unit_root), _DEFAULT_PROMPT_DIRNAME)


def _ttl_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get("POLISH_PROMPT_TTL_SECONDS", "300")))
    except ValueError:
        return 300.0


def _prompt_id(name: str) -> str:
    """논리 이름 → `POLISH_PROMPT_ID_<이름 대문자>` 환경변수 값."""
    return os.environ.get(f"POLISH_PROMPT_ID_{name.upper()}", "").strip()


def _admin_api_url() -> str:
    return os.environ.get("GENOS_ADMIN_API_URL", "").strip().rstrip("/")


def _jinja(loader):
    try:
        from jinja2 import Environment, StrictUndefined
    except ImportError as exc:
        raise PromptRenderError("프롬프트 템플릿 엔진이 설치되어 있지 않습니다.") from exc
    return Environment(
        loader=loader,
        undefined=StrictUndefined,  # 변수 오타를 빈칸으로 렌더하면 지시가 조용히 사라진다
        autoescape=False,  # 프롬프트는 HTML 이 아니다 — escape 하면 원문이 변형된다
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


@lru_cache(maxsize=1)
def _file_env():
    try:
        from jinja2 import FileSystemLoader
    except ImportError as exc:
        raise PromptRenderError("프롬프트 템플릿 엔진이 설치되어 있지 않습니다.") from exc
    directory = prompt_dir()
    if not os.path.isdir(directory):
        raise PromptRenderError("프롬프트 템플릿을 찾을 수 없습니다.")
    log_info(
        "프롬프트 디렉토리 로드",
        event="prompt_dir_loaded",
        resource_id="text_polish_prompts",
    )
    return _jinja(FileSystemLoader(directory, encoding="utf-8"))


@lru_cache(maxsize=1)
def _string_env():
    return _jinja(None)


async def _fetch(name: str) -> str:
    """GenOS Prompt 리소스에서 본문을 받아온다 (§10.5).

    Raises:
        PromptRenderError: 설정 누락·통신 실패·`code != 0`·빈 본문.
            어느 경우든 고정 안내문만 담는다.
    """
    ttl = _ttl_seconds()
    cached = _CACHE.get(name)
    if cached and ttl > 0 and (time.monotonic() - cached[1]) < ttl:
        return cached[0]

    base = _admin_api_url()
    prompt_id = _prompt_id(name)
    if not base or not prompt_id:
        # 설정 누락은 통신 실패와 다른 사건이다 — 고칠 곳이 환경변수다
        log_warning(
            "프롬프트 조회 설정 누락",
            event="prompt_config_missing",
            resource_id="text_polish_prompts",
            status="admin_api_url" if not base else "prompt_id",
        )
        raise PromptRenderError("프롬프트 설정이 완료되지 않았습니다.")

    import httpx

    url = f"{base}/prompt/template/{prompt_id}"
    try:
        # 인증 헤더 없음 — 프롬프트 라이브러리는 무인증이다 (확인된 사실).
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001 - 통신·파싱 실패를 한 사건으로 묶는다
        log_warning(
            "프롬프트 조회 실패",
            event="prompt_fetch_failed",
            resource_id="text_polish_prompts",
            error_type=type(exc).__name__,
            upstream_status=getattr(getattr(exc, "response", None), "status_code", None),
        )
        raise PromptRenderError("프롬프트를 가져오지 못했습니다.") from exc

    # HTTP 200 이어도 code != 0 이면 실패다 (§10.5). errMsg 는 로그에도 싣지 않는다 —
    # 외부 응답 본문이 그대로 흘러들 경로를 만들지 않는다 (3.8절).
    if payload.get("code") != 0:
        log_warning(
            "프롬프트 조회 응답이 실패를 나타냄",
            event="prompt_fetch_rejected",
            resource_id="text_polish_prompts",
            status=str(payload.get("code")),
        )
        raise PromptRenderError("프롬프트를 가져오지 못했습니다.")

    text = payload.get("data")
    if not isinstance(text, str) or not text.strip():
        # 빈 본문을 그대로 쓰면 지시 없는 프롬프트로 LLM 이 돌고 결과가 정상 응답처럼 내려간다
        log_warning(
            "프롬프트 본문이 비어 있음",
            event="prompt_body_empty",
            resource_id="text_polish_prompts",
        )
        raise PromptRenderError("프롬프트 내용이 비어 있습니다.")

    _CACHE[name] = (text, time.monotonic())
    return text


async def render(name: str, **variables) -> str:
    """논리 이름으로 프롬프트를 렌더한다 (`"system"` → 파일 `system.j2` 또는 Prompt 리소스).

    **호출부에 확장자도 prompt_id 도 남기지 않는다.** 저장 방식이 호출부마다 박히면
    소스를 바꿀 때 갈아 끼울 자리가 이 함수 하나가 아니라 전 호출부가 된다.

    Args:
        name: 확장자 없는 프롬프트 이름 (`"system"`, `"user_batch"`).

    Raises:
        PromptRenderError: 조회 실패·템플릿 부재·문법 오류·변수 누락.
            **`genos` 소스가 실패해도 파일로 떨어지지 않는다** (모듈 머리말 참고).
    """
    try:
        if source() == SOURCE_GENOS:
            template = _string_env().from_string(await _fetch(name))
        else:
            template = _file_env().get_template(f"{name}{_TEMPLATE_SUFFIX}")
        return template.render(**variables).strip()
    except PromptRenderError:
        raise
    except Exception as exc:  # noqa: BLE001 - jinja 예외 종류를 여기서 나열하지 않는다
        raise PromptRenderError("프롬프트를 생성하지 못했습니다.") from exc


async def probe(names) -> dict:
    """기동 시 소스 도달 여부를 확인해 로그로 남긴다 (코드 서빙 startup 에서 호출).

    파일 소스면 템플릿 존재만 본다. genos 소스면 **실제로 한 번 조회**한다 —
    admin-api 는 내부 서비스 직통이라 네트워크가 닿는지는 찔러 봐야만 안다.

    실패해도 **기동을 막지 않는다**: 프롬프트를 못 받는 것은 요청 시점 오류로 드러나야
    하고, 기동을 세우면 헬스체크만 죽어 원인이 안 보인다.

    Returns:
        {"source": ..., "ok": bool, "checked": [...]} — 로그·상태 확인용.
    """
    mode = source()
    checked = []
    ok = True
    for name in names:
        try:
            if mode == SOURCE_GENOS:
                await _fetch(name)
            else:
                _file_env().get_template(f"{name}{_TEMPLATE_SUFFIX}")
            checked.append(name)
        except Exception:  # noqa: BLE001 - 사유는 _fetch/_file_env 가 이미 로그로 남겼다
            ok = False
    (log_info if ok else log_warning)(
        "프롬프트 소스 점검 완료" if ok else "프롬프트 소스 점검 실패 — 요청 시점에 오류가 난다",
        event="prompt_source_probed",
        resource_id="text_polish_prompts",
        status=mode,
        item_count=len(checked),
    )
    return {"source": mode, "ok": ok, "checked": checked}
