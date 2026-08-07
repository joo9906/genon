"""번역 프롬프트 조립 — 문구는 `onprem/prompt/SFR-018_translation/*.j2` 에 있다.

이 파일은 **템플릿에 넘길 변수를 정리하는 역할만** 한다. 문구를 여기 두지 않는 이유는
`prompt_loader.py` 머리말에 적었다.

용어사전 블록을 프롬프트에 넣는 방식에 대해:
- 배치에 **실제로 등장한 용어만** 넣는다. 사전 전체를 실으면 토큰이 폭발하고,
  등장하지 않는 용어까지 지시하면 모델이 억지로 끼워 넣는다.
- 프롬프트 지시는 강제력이 없다. 그래서 준수 여부는 번역 후 코드가 다시 확인하고
  (`glossary_report.py`) 준수율을 응답에 싣는다 — 지시만으로 처리하지 않는다는
  이 저장소의 구조 보존 원칙과 같은 계열이다.
"""

import json
from dataclasses import dataclass

from translation_pipeline.common.prompt_loader import render


@dataclass(frozen=True)
class PromptContext:
    """한 번역 요청 전체에 공통인 프롬프트 변수."""

    source_label: str   # 감지 실패 시 "the source language"
    target_label: str
    register_label: str
    register_instruction: str


def glossary_entries(terms) -> list:
    """`GlossaryTerm` 목록을 템플릿이 쓰는 형태로 바꾼다."""
    return [{"source": term.term_source, "target": term.term_target} for term in terms]


def _render_system(template: str, context: PromptContext, terms: list) -> str:
    """배치·단건 시스템 프롬프트는 템플릿 이름만 다르고 변수는 같다.

    변수 목록을 두 벌로 두면 프롬프트 변수를 늘릴 때 한쪽만 고치게 되고, 그러면
    폴백 경로(단건)만 지시가 빠진 채 LLM 을 부른다 — 배치가 실패했을 때만 드러나는
    차이라 알아채기 어렵다.
    """
    return render(
        template,
        source_label=context.source_label,
        target_label=context.target_label,
        register_label=context.register_label,
        register_instruction=context.register_instruction,
        glossary=glossary_entries(terms),
    )


def build_batch_prompts(context: PromptContext, batch: list, terms: list) -> tuple:
    """(system, user) 배치 프롬프트.

    Args:
        batch: [(translation_unit_id, 원문)] 목록.
        terms: 이 배치에 등장한 GlossaryTerm 목록 (없으면 빈 목록).
    """
    items = [{"id": unit_id, "s": text} for unit_id, text in batch]
    # JSON 은 코드가 만들어 그대로 싣는다 — jinja 로 조립하면 따옴표·역슬래시가
    # 있는 원문에서 깨진다 (user_batch.j2 주석 참고).
    user = render("user_batch", items_json=json.dumps(items, ensure_ascii=False))
    return _render_system("system_batch", context, terms), user


def build_single_prompts(context: PromptContext, text: str, terms: list) -> tuple:
    """(system, user) 단건 프롬프트 — 배치 실패 시 폴백 경로."""
    user = render("user_single", text=text)
    return _render_system("system_single", context, terms), user
