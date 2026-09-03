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
        batch: [(translation_unit_id, 원문, 문맥)] 목록. 문맥은 그 유닛이 속한 절의
            제목 원문이고, 없으면 빈 문자열이다.
        terms: 이 배치에 등장한 GlossaryTerm 목록 (없으면 빈 목록).

    ## 문맥(`c`)을 싣는 이유 (2026-08-29)

    LLM 에는 **셀·문장 텍스트만** 들어간다 — 구조는 코드가 스켈레톤으로 쥐고 있기
    때문이다. 그래서 표 셀 하나짜리 유닛(`대상`·`금액`·`해당 없음`)은 그것이 무엇에
    관한 값인지 알 방법이 없고, 주어가 생략된 한국어 문장은 더 그렇다. 절 제목 한 줄이
    그 대부분을 메운다.

    **번역 대상이 아니다.** 출력 스키마는 `{id, t}` 그대로이고, 시스템 프롬프트가
    "`c` 는 배경이며 번역하지도 출력하지도 말라" 를 못박는다.
    """
    items = [
        # 문맥이 없는 유닛에는 **키를 넣지 않는다** — 빈 문자열을 실으면 모델이 그것도
        # 번역해야 할 무엇으로 읽을 여지가 생기고 토큰만 는다.
        {"id": unit_id, "s": text, **({"c": scope} if scope else {})}
        for unit_id, text, scope in batch
    ]
    # JSON 은 코드가 만들어 그대로 싣는다 — jinja 로 조립하면 따옴표·역슬래시가
    # 있는 원문에서 깨진다 (user_batch.j2 주석 참고).
    user = render("user_batch.j2", items_json=json.dumps(items, ensure_ascii=False))
    return _render_system("system_batch.j2", context, terms), user


def build_single_prompts(
    context: PromptContext, text: str, terms: list, scope: str = ""
) -> tuple:
    """(system, user) 단건 프롬프트 — 배치 실패 시 폴백 경로.

    **문맥을 배치와 같이 싣는다.** 폴백에만 빠뜨리면 배치가 실패한 유닛들만 문맥 없이
    번역되고, 그 차이는 배치가 실패했을 때만 드러나 알아채기 어렵다.
    """
    user = render("user_single.j2", text=text, scope=scope)
    return _render_system("system_single.j2", context, terms), user
