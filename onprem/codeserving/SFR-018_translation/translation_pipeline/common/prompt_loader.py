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

from translation_pipeline.common.logging_utils import log_info

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


def render(template_name: str, **variables) -> str:
    """템플릿을 렌더해 프롬프트 문자열을 만든다.

    Raises:
        PromptRenderError: 템플릿 부재·문법 오류·변수 누락. 어느 경우든 고정 안내문만 담는다.
    """
    try:
        template = _environment().get_template(template_name)
        return template.render(**variables).strip()
    except PromptRenderError:
        raise
    except Exception as exc:  # noqa: BLE001 - jinja 예외 종류를 여기서 나열하지 않는다
        raise PromptRenderError("프롬프트를 생성하지 못했습니다.") from exc
