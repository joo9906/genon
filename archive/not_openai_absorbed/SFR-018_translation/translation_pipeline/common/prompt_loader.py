"""프롬프트 로더 — 프롬프트 문자열을 코드 밖(`onprem/prompt/`)에서 관리한다.

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
import re

from translation_pipeline.common import prompt_library
# `lru_cache`·`log_info` 를 2026-09-08 에 뺐다 — jinja 를 걷어내며(2026-09-07)
# 쓰는 자리가 사라졌는데 선언만 남아 있었다. 이관이 손 타이핑이라 안 쓰는 줄은 비용이다.
from translation_pipeline.common.logging_utils import log_warning

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


# ===========================================================================
# 렌더러 — `{{ 이름 }}` 치환만 한다 (2026-09-07, jinja2 제거)
# ===========================================================================
# 그전에는 jinja2 였다. 걷어낸 이유는 `openai` SDK 와 같다 — **사내 PyPI mirror 에 없으면
# 첫 호출에서 기능이 죽는다**(지연 import 라 기동·헬스체크는 통과한다). 프롬프트 문법이
# 실제로 쓰던 것은 `{{ 변수 }}`·`{% if %}`·`{% for %}` 셋이고, 뒤의 둘은 **파이썬이 미리
# 조립해 변수 하나로 넘기면** 사라진다(조립하는 자리는 각 단위의 프롬프트 조립 함수다).
# 그래서 남은 것은 치환뿐이고, 그건 표준 라이브러리로 끝난다.
#
# ## 지원하는 것과 하지 않는 것
#
# - `{{ 이름 }}` — 이름은 파이썬 식별자만. 값은 `str()` 로 바꿔 **그대로** 넣는다.
# - `{# 주석 #}` — 지운다. 템플릿 머리말(변수 설명·근거)이 이 문법으로 적혀 있다.
# - **`{% ... %}` 는 오류다.** 조용히 남겨 두면 그 문장이 프롬프트에 글자로 실려 LLM 이
#   지시로 읽는다. 관리자가 라이브러리 본문에 jinja 를 적었을 때 드러나야 한다.
# - **점 접근(`{{ entry.source }}`)도 오류다.** 되살리려면 표현식 평가가 필요해지고,
#   그건 이 파일을 다시 템플릿 엔진으로 만드는 일이다.
#
# ## 변수가 없으면 세운다 (jinja `StrictUndefined` 자리)
#
# 오타를 빈칸으로 렌더하면 **지시 한 줄이 조용히 사라진다.** 그 프롬프트로 LLM 을 돌린
# 결과는 정상 응답처럼 내려온다 — 이 저장소가 프롬프트 부재를 요청 실패로 세우는 것과
# 같은 이유다.
#
# ## 값 안의 중괄호는 검사하지 않는다
#
# 검사는 **치환 전 템플릿 원문**에서만 한다. 문서 본문·사용자 발화에 `{{` 가 들어 있을 수
# 있고(006 템플릿 문법이 `{'제목', 16pt}` 다), 치환 뒤를 훑으면 그 문서를 못 쓰게 된다.
_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _render_source(source: str, **variables) -> str:
    """템플릿 문자열 하나를 렌더한다 (파일·라이브러리 본문 공용).

    **파일과 라이브러리가 같은 함수를 지난다** — 규칙이 갈리면 같은 문구가 자리에 따라
    다르게 렌더된다.

    Raises:
        PromptRenderError: 지원하지 않는 문법, 정의되지 않은 변수. 메시지는 이 파일 안의
            고정 한국어 안내문만 담는다 (템플릿 내용을 노출하지 않는다 — 3.8절).
    """
    text = _COMMENT_RE.sub("", source)
    if "{%" in text:
        raise PromptRenderError("프롬프트에 지원하지 않는 문법이 있습니다.")

    missing: list = []

    def _replace(match) -> str:
        name = match.group(1).strip()
        if not _NAME_RE.match(name):
            missing.append(name)
            return ""
        if name not in variables:
            missing.append(name)
            return ""
        value = variables[name]
        return value if isinstance(value, str) else str(value)

    rendered = _PLACEHOLDER_RE.sub(_replace, text)
    if missing:
        # 어느 이름이 비었는지는 **로그로** 남긴다. 이름은 프롬프트 변수명이지 문서
        # 내용이 아니므로 진단에 필요하고, 사용자 안내문에는 담지 않는다.
        log_warning(
            "프롬프트 변수를 채우지 못했다",
            event="prompt_variable_missing",
            resource_id=",".join(sorted(set(missing))[:5]),
            item_count=len(missing),
        )
        raise PromptRenderError("프롬프트를 생성하지 못했습니다.")
    return rendered.strip()


# 프롬프트 파일 확장자. **`.j2` 가 아니다** (2026-09-07) — jinja 를 걷어냈으므로 그
# 확장자는 거짓말이고, 편집기가 jinja 문법을 제안해 `{% if %}` 를 적게 만든다.
_TEMPLATE_SUFFIX = ".txt"


def _template_stem(template_name: str) -> str:
    """`"system"`·`"system.txt"`·`"system.j2"` 를 다 같은 이름으로 본다.

    라이브러리 이름(=환경변수 `이름=ID` 의 키)은 **확장자를 뗀 것**이라, 호출부가 어느
    형태로 넘겨도 같은 프롬프트를 가리켜야 한다. `.j2` 를 계속 받는 이유는 옛 호출부·
    옛 환경변수가 남아 있을 때 **조용히 다른 프롬프트로 떨어지지 않게** 하기 위해서다.
    """
    for suffix in (_TEMPLATE_SUFFIX, ".j2"):
        if template_name.endswith(suffix):
            return template_name[: -len(suffix)]
    return template_name


def _read_template(template_name: str) -> str:
    """프롬프트 파일 하나를 읽는다.

    **디렉토리가 없거나 파일이 없으면 요청을 세운다.** 빈 프롬프트로 넘어가면 지시문 없이
    LLM 을 돌리게 되고 그 결과가 정상 응답처럼 내려간다. 경로·예외 원문은 안내문에 담지
    않는다 (3.8절) — 로그에 파일 이름만 남긴다(문서 내용이 아니다).

    이름에 경로 구분자가 오면 거절한다. 라이브러리 이름이 곧 파일 이름이라
    (`prompt_ids()` 의 키), 관리자가 `../` 를 적을 수 있는 자리를 열어 둘 이유가 없다.
    """
    if "/" in template_name or "\\" in template_name or template_name.startswith("."):
        raise PromptRenderError("프롬프트 이름이 올바르지 않습니다.")

    directory = prompt_dir()
    if not os.path.isdir(directory):
        raise PromptRenderError("프롬프트 템플릿을 찾을 수 없습니다.")

    path = os.path.join(directory, template_name)
    if not os.path.isfile(path):
        log_warning(
            "프롬프트 파일이 없다",
            event="prompt_file_missing",
            resource_id=template_name,
        )
        raise PromptRenderError("프롬프트 템플릿을 찾을 수 없습니다.")

    with open(path, encoding="utf-8") as handle:
        return handle.read()


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
    name = _template_stem(template_name)
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
        source = _read_template(f"{name}{_TEMPLATE_SUFFIX}")
    except PromptRenderError:
        raise
    except OSError as exc:
        raise PromptRenderError("프롬프트를 생성하지 못했습니다.") from exc
    return _render_source(source, **variables)
