"""jinja 프롬프트 로더 — 프롬프트 문자열을 코드 밖(`onprem/prompt/`)에서 관리한다.

왜 파일로 빼는가
- 문구 수정이 코드 리뷰·재빌드 없이 끝난다. 나중에 GenOS Prompt 리소스(10.5절)로
  옮길 때도 템플릿 파일을 그대로 등록하면 된다.
- 프롬프트가 코드에 박혀 있으면 "어느 문구로 돌린 결과인지"를 배포 이미지 태그로만
  구분하게 된다. 파일로 두면 프롬프트 디렉토리 자체가 버전 대상이 된다.

배포 전제 (중요)
- 프롬프트 디렉토리는 **배포 단위 바깥**(`onprem/prompt/SFR-018_translation` —
  디렉토리 이름은 배포 단위 이름과 같게 맞춰 둔다)에 있다. 이미지를 만들 때 이
  디렉토리를 함께 넣어야 하고, 위치가 다르면 `TRANSLATION_PROMPT_DIR` 로 통째 지정한다.
- 디렉토리·템플릿이 없으면 **기동 시점이 아니라 첫 렌더 시점에** 고정 안내문과 함께
  실패한다. 없는 프롬프트를 빈 문자열로 대체하면 LLM 이 아무 지시 없이 돌아가고,
  그 결과가 정상 응답처럼 내려간다 (실패 침묵 처리 금지).

`StrictUndefined` 를 쓰는 이유도 같다 — 템플릿 변수 오타를 빈칸으로 렌더하면
지시문 한 줄이 조용히 사라진 프롬프트가 나간다.
"""

import os
from functools import lru_cache

from translation_pipeline.common import prompt_library
from translation_pipeline.common.logging_utils import log_info, log_warning

_DEFAULT_PROMPT_DIRNAME = os.path.join("prompt", "SFR-018_translation")


class PromptRenderError(RuntimeError):
    """프롬프트 디렉토리·템플릿을 찾지 못했거나 렌더에 실패.

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다
    (템플릿 경로·jinja 예외 원문을 사용자에게 노출하지 않는다 — 3.8절).
    """


def prompt_dir() -> str:
    """프롬프트 디렉토리 경로.

    `TRANSLATION_PROMPT_DIR` 이 있으면 그대로 쓰고, 없으면 배포 단위 기준
    `../prompt/SFR-018_translation` 을 본다 (저장소 배치와 같은 상대 위치).
    """
    override = os.environ.get("TRANSLATION_PROMPT_DIR", "").strip()
    if override:
        return override
    return _search_upward(os.path.dirname(os.path.abspath(__file__)))


# 상위 탐색으로 바꾼 근거는 006 `prompt_loader.py` 와 같다 (2026-08-11 재배치).
# 이 단위는 로더가 `translation_pipeline/common/` 안에 있어 깊이가 한 겹 더 달랐다 —
# 고정 깊이를 단위마다 따로 세는 방식 자체가 이런 이동에 약하다.
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
    return os.path.join(os.path.dirname(start), _DEFAULT_PROMPT_DIRNAME)


@lru_cache(maxsize=1)
def _environment():
    """jinja Environment (프로세스당 1회). 템플릿 파싱 결과는 jinja 가 캐시한다."""
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
    except ImportError as exc:
        raise PromptRenderError(
            "프롬프트 템플릿 엔진이 설치되어 있지 않습니다."
        ) from exc

    directory = prompt_dir()
    if not os.path.isdir(directory):
        raise PromptRenderError("프롬프트 템플릿을 찾을 수 없습니다.")

    log_info(
        "번역 프롬프트 디렉토리 로드",
        event="prompt_dir_loaded",
        resource_id="translation_prompts",
    )
    return Environment(
        loader=FileSystemLoader(directory, encoding="utf-8"),
        undefined=StrictUndefined,
        autoescape=False,  # 프롬프트는 HTML 이 아니다 — escape 하면 원문이 변형된다
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


    **프롬프트 라이브러리가 파일을 덮어쓴다** (2026-09-03). 환경변수에 이 템플릿 이름
    (`system.j2` → `system`)이 적혀 있으면 그 본문을 쓰고, 없거나 못 읽으면 이미지에 든
    `.j2` 파일을 쓴다. 근거는 `prompt_library` 머리말.

    **라이브러리 본문이 깨져도 파일로 떨어진다.** 관리자가 변수 이름을 잘못 적는 것은
    흔한 일이고(`StrictUndefined` 라 그 자리에서 렌더가 죽는다), 그때 요청을 세우면
    문구 오타 하나가 기능을 통째로 막는다. 대신 **조용히 넘기지 않는다** —
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
