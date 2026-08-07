"""jinja 프롬프트 로더 — 문구는 `onprem/prompt/SFR-018_faq/*.j2` 에 있다.

번역 단위의 `prompt_loader.py` 와 같은 계약의 사본이다 (배포 단위 간 import 금지).
설계 근거는 그쪽 머리말과 같다:
- 문구 수정이 코드 리뷰·재빌드 없이 끝나고, GenOS Prompt 리소스(10.5절)로 옮기기 쉽다.
- 템플릿이 없으면 **빈 프롬프트로 넘어가지 않고 실패한다.** 지시문 없는 프롬프트로
  LLM 을 돌리면 그 결과가 정상 응답처럼 내려간다.
- `StrictUndefined` — 변수 오타를 빈칸으로 렌더하면 지시 한 줄이 조용히 사라진다.

배포 전제: 프롬프트 디렉토리는 배포 단위 **바깥**이므로 이미지에 함께 넣어야 한다.
위치가 다르면 `FAQ_PROMPT_DIR` 로 통째 지정한다.
"""

import os
from functools import lru_cache

from .logging_utils import log_info

_DEFAULT_PROMPT_DIRNAME = os.path.join("prompt", "SFR-018_faq")


class PromptRenderError(RuntimeError):
    """프롬프트 디렉토리·템플릿을 찾지 못했거나 렌더에 실패.

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다
    (템플릿 경로·jinja 예외 원문을 사용자에게 노출하지 않는다 — 3.8절).
    """


def prompt_dir() -> str:
    override = os.environ.get("FAQ_PROMPT_DIR", "").strip()
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
        "FAQ 프롬프트 디렉토리 로드",
        event="prompt_dir_loaded",
        resource_id="faq_prompts",
    )
    return Environment(
        loader=FileSystemLoader(directory, encoding="utf-8"),
        undefined=StrictUndefined,
        autoescape=False,  # 프롬프트는 HTML 이 아니다 — escape 하면 문서 원문이 변형된다
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


# 저장 형식(확장자)은 이 모듈만 안다 — 호출부는 논리 이름만 넘긴다.
_TEMPLATE_SUFFIX = ".j2"


def render(name: str, **variables) -> str:
    """논리 이름으로 프롬프트를 렌더한다 (`"system"` → `system.j2`).

    **호출부에 확장자를 남기지 않는다.** 파일명을 그대로 받으면 "프롬프트가 파일로
    존재한다"는 사실이 호출부마다 박힌다. 가이드 §10.5 는 프롬프트를 GenOS Prompt
    리소스에 등록하고 **ID 로 참조**하라고 하는데(`GET /prompt/template/{id}`),
    그때 갈아 끼울 자리가 이 함수 하나가 아니라 모든 호출부가 된다.
    논리 이름만 받으면 소스 교체가 여기서 끝난다.

    Args:
        name: 확장자 없는 프롬프트 이름 (`"system"`, `"user_batch"`).

    Raises:
        PromptRenderError: 템플릿 부재·문법 오류·변수 누락. 어느 경우든 고정 안내문만 담는다.
    """
    try:
        template = _environment().get_template(f"{name}{_TEMPLATE_SUFFIX}")
        return template.render(**variables).strip()
    except PromptRenderError:
        raise
    except Exception as exc:  # noqa: BLE001 - jinja 예외 종류를 여기서 나열하지 않는다
        raise PromptRenderError("프롬프트를 생성하지 못했습니다.") from exc
