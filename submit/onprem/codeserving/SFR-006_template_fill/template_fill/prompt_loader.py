"""jinja 프롬프트 로더 — 문구는 **프롬프트 라이브러리**, 없으면 `.j2` 파일이다.

**2026-09-03: 라이브러리가 파일을 덮어쓴다.** `TEMPLATE_FILL_PROMPT_IDS` 에 이름→ID 를
주면 `prompt_library` 가 받아 오고, 안 주거나 못 읽으면 아래 파일 경로로 돈다. 어느
쪽을 썼는지는 `GET /prompts` 가 말한다. 자주 바뀌는 문구(항목 매핑 지시)를 재배포 없이
고치게 하려는 것이고, 고정 골격(시스템 프롬프트)은 파일로 두어도 된다 — §10.5.

기본값 파일은 `onprem/prompt/SFR-006_template_fill/*.j2` 에 있다.

번역·FAQ 단위의 `prompt_loader.py` 와 같은 계약의 사본이다 (배포 단위 간 import 금지).
설계 근거는 그쪽 머리말과 같다:
- 문구 수정이 코드 리뷰·재빌드 없이 끝나고, GenOS Prompt 리소스(10.5절)로 옮기기 쉽다.
- 템플릿이 없으면 **빈 프롬프트로 넘어가지 않고 실패한다.** 지시문 없는 프롬프트로
  LLM 을 돌리면 그 결과가 정상 응답처럼 내려간다.
- `StrictUndefined` — 변수 오타를 빈칸으로 렌더하면 지시 한 줄이 조용히 사라진다.

배포 전제: 프롬프트 디렉토리는 배포 단위 **바깥**이므로 이미지에 함께 넣어야 한다.
위치가 다르면 `TEMPLATE_FILL_PROMPT_DIR` 로 통째 지정한다.
**이 단위는 워크플로우(02)와 코드서빙(03) 양쪽에서 프롬프트를 쓴다** — 두 이미지 모두
디렉토리와 `jinja2` 가 있어야 한다(02 는 값 추출, 03 은 톤 변환).
"""

import os
from functools import lru_cache

from . import prompt_library
from .logging_utils import log_info, log_warning

_DEFAULT_PROMPT_DIRNAME = os.path.join("prompt", "SFR-006_template_fill")


class PromptRenderError(RuntimeError):
    """프롬프트 디렉토리·템플릿을 찾지 못했거나 렌더에 실패.

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다
    (템플릿 경로·jinja 예외 원문을 사용자에게 노출하지 않는다 — 3.8절).
    """


def prompt_dir() -> str:
    override = os.environ.get("TEMPLATE_FILL_PROMPT_DIR", "").strip()
    if override:
        return override
    return _search_upward(os.path.dirname(os.path.abspath(__file__)))


# 고정 깊이(`dirname(unit_root)`)로 잡던 것을 상위 탐색으로 바꿨다 (2026-08-11).
# 배포 단위가 `onprem/<단위>` 에서 `onprem/codeserving/<단위>` 로 한 겹 깊어지자 네 단위의
# 프롬프트가 **동시에** 사라졌고, 증상은 "프롬프트 생성 실패" 라는 요청 실패 하나뿐이라
# 디렉토리 이동이 원인이라는 것이 드러나지 않았다. 위로 훑으면 단위가 어느 깊이에 있든,
# 이미지에서 프롬프트를 단위 옆에 두든 같은 코드로 걸린다.
_SEARCH_DEPTH = 6


def _search_upward(start: str) -> str:
    here = start
    for _ in range(_SEARCH_DEPTH):
        candidate = os.path.join(here, _DEFAULT_PROMPT_DIRNAME)
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    # 못 찾아도 경로 하나는 돌려준다 — `_environment()` 가 부재를 고정 안내문으로 올린다.
    return os.path.join(os.path.dirname(start), _DEFAULT_PROMPT_DIRNAME)


@lru_cache(maxsize=1)
def _environment():
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
    except ImportError as exc:
        raise PromptRenderError("프롬프트 템플릿 엔진이 설치되어 있지 않습니다.") from exc

    directory = prompt_dir()
    if not os.path.isdir(directory):
        raise PromptRenderError("프롬프트 템플릿을 찾을 수 없습니다.")

    log_info(
        "템플릿 채우기 프롬프트 디렉토리 로드",
        event="prompt_dir_loaded",
        resource_id="template_fill_prompts",
    )
    return Environment(
        loader=FileSystemLoader(directory, encoding="utf-8"),
        undefined=StrictUndefined,
        autoescape=False,  # 프롬프트는 HTML 이 아니다 — escape 하면 사용자 발화가 변형된다
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _render_source(source: str, **variables) -> str:
    """문자열 하나를 그 자리에서 템플릿으로 렌더한다 (라이브러리 본문 전용).

    파일과 **같은 Environment** 를 쓴다 — `StrictUndefined`·`trim_blocks` 가 달라지면
    같은 문구가 자리에 따라 다르게 렌더된다.
    """
    return _environment().from_string(source).render(**variables).strip()


def render(template_name: str, **variables) -> str:
    """템플릿을 렌더해 프롬프트 문자열을 만든다.

    **프롬프트 라이브러리가 파일을 덮어쓴다** (2026-09-03). `TEMPLATE_FILL_PROMPT_IDS` 에
    이 템플릿 이름(`extract_user.j2` → `extract_user`)이 적혀 있으면 그 본문을 쓰고,
    없거나 못 읽으면 이미지에 든 `.j2` 파일을 쓴다. 근거는 `prompt_library` 머리말.

    **라이브러리 본문이 깨져도 파일로 떨어진다.** 관리자가 변수 이름을 잘못 적는 것은
    흔한 일이고(`StrictUndefined` 라 그 자리에서 렌더가 죽는다), 그때 요청을 세우면
    문구 오타 하나가 대화를 통째로 막는다. 대신 **조용히 넘기지 않는다** —
    `event=prompt_library_render_failed` 로그가 남고 `GET /prompts` 가 그 이름을
    `source: "file"` 로 보여준다.

    Raises:
        PromptRenderError: **파일** 템플릿 부재·문법 오류·변수 누락. 어느 경우든 고정
            안내문만 담는다 (지시문 없는 프롬프트로 LLM 을 돌리지 않는다).
    """
    name = template_name[:-3] if template_name.endswith(".j2") else template_name
    body = prompt_library.body_for(name)
    if body is not None:
        try:
            return _render_source(body, **variables)
        except Exception as exc:  # noqa: BLE001 - jinja 예외 종류를 나열하지 않는다
            log_warning(
                "프롬프트 라이브러리 본문을 렌더하지 못해 내장 파일로 동작한다",
                event="prompt_library_render_failed",
                resource_id=f"prompt:{name}",
                status=type(exc).__name__,
            )

    try:
        template = _environment().get_template(template_name)
        return template.render(**variables).strip()
    except PromptRenderError:
        raise
    except Exception as exc:  # noqa: BLE001 - jinja 예외 종류를 여기서 나열하지 않는다
        raise PromptRenderError("프롬프트를 생성하지 못했습니다.") from exc
