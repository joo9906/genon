"""Office 번역 파이프라인 공용 타입.

이 파일 하나에 모든 dataclass를 모아두면, 각 처리 단계(units/modes/pipeline)가
공통 타입을 어디서 import해야 하는지 헷갈리지 않는다.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List


@dataclass
class TranslationUnit:
    """LLM에 실제로 보낼 최소 번역 단위 (문장/셀/텍스트박스 등)."""

    translation_unit_id: int
    node_id: str
    text: str
    element_type: str = ""
    context_scope: str = ""       # 예: "pptx:slide:3"
    context_text: str = ""


@dataclass
class OfficeTranslationArtifacts:
    """번역 파이프라인의 최종 산출물."""

    pairs: List[dict]
    text: str
    trans_map: Dict[str, str]
    translated_by_unit_id: Dict[int, str]
    translation_error: str


@dataclass
class MarkdownTranslationArtifacts:
    """마크다운 구조 보존 번역(markdown_units.py 경로)의 최종 산출물."""

    markdown: str          # 구조가 원본과 동일한 번역 마크다운
    pairs: List[dict]      # 유닛별 원문/번역 쌍 (검수용)
    translation_error: str  # 전량 성공 시 "", 일부 실패 시 사유 분류


@dataclass
class OfficePipelineDeps:
    """번역 파이프라인이 의존하는 외부 동작을 주입 지점으로 분리.

    실제 구현(plain batch 번역, contextual 번역)을 여기 함수 포인터로 넣어두면,
    파이프라인 로직과 번역 실행 로직이 서로 몰라도 되어 테스트/교체가 쉬워진다.
    """

    batch_translate_async: Callable[..., Any]
