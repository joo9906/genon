"""jinja 프롬프트 로더 — 문구는 `onprem/prompt/SFR-006_template_fill/*.j2` 에 있다.

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

from .logging_utils import log_info

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
    unit_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(os.path.dirname(unit_root), _DEFAULT_PROMPT_DIRNAME)


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
