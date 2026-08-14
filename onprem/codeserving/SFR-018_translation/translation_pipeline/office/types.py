"""번역 파이프라인 공용 타입.

모든 dataclass 를 한 파일에 모아 각 단계(units/modes/pipeline)가 공통 타입을
어디서 import 할지 헷갈리지 않게 한다.
"""

from dataclasses import dataclass, field


@dataclass
class TranslationUnit:
    """LLM 에 실제로 보낼 최소 번역 단위 (문장/셀/텍스트박스 등)."""

    translation_unit_id: int
    node_id: str
    text: str
    element_type: str = ""
    context_scope: str = ""       # 예: "pptx:slide:3"
    context_text: str = ""


@dataclass(frozen=True)
class TranslationOptions:
    """한 요청 전체에 걸리는 번역 설정.

    언어·문체 해석은 진입점에서 한 번만 하고 이 값 객체로 파이프라인에 내린다.
    단계마다 문자열을 다시 해석하면 같은 요청 안에서 판정이 갈릴 수 있다.
    """

    target_code: str
    target_label: str          # 프롬프트용 영문 이름
    target_korean_label: str
    source_code: str = ""      # 감지 실패 시 빈 문자열
    source_label: str = "the source language"
    source_detected: bool = False   # True 면 호출부가 명시하지 않아 감지한 값이다
    register_key: str = "written"
    register_label: str = ""
    register_instruction: str = ""
    register_fell_back: bool = False  # 알 수 없는 문체 값이 와서 기본값을 쓴 경우


@dataclass
class TranslationStats:
    """번역 실행 통계 — 응답과 평가지표가 함께 쓴다.

    `fallback_rate` 를 응답에 싣는 이유: 루트 `README.md` 018 공통 지표가
    "재조립 실패·세그먼트 수 불일치로 인한 fallback 발생률(0 에 수렴해야 함)"을
    운영 지표로 잡는데, 예전 응답에는 `translation_error` 문자열만 있어 **분모·분자가
    없었다** — 지표를 계산할 수 없었다.
    """

    unit_count: int = 0        # 전체 번역 유닛 수 (분모)
    failed_unit_count: int = 0  # 원문으로 폴백된 유닛 수 (분자)
    llm_unit_count: int = 0    # 실제로 LLM 에 보낸 유닛 수 (중복 제거 후)
    deduped_unit_count: int = 0  # 같은 원문이라 재사용한 유닛 수
    numeric_warning_count: int = 0   # 숫자 보존 검사에 걸린 유닛 수
    numeric_reverted_count: int = 0  # 그중 정책상 원문으로 되돌린 유닛 수

    @property
    def fallback_rate(self) -> float:
        if not self.unit_count:
            return 0.0
        return round(self.failed_unit_count / self.unit_count, 4)

    def as_payload(self) -> dict:
        return {
            "unit_count": self.unit_count,
            "failed_unit_count": self.failed_unit_count,
            "llm_unit_count": self.llm_unit_count,
            "deduped_unit_count": self.deduped_unit_count,
            "numeric_warning_count": self.numeric_warning_count,
            "numeric_reverted_count": self.numeric_reverted_count,
            "fallback_rate": self.fallback_rate,
        }


@dataclass
class OfficeTranslationArtifacts:
    """노드 배열 번역(`POST /translate`)의 산출물."""

    pairs: list          # 노드별 원문/번역 쌍 (`node_id`·`unit_id` 포함)
    text: str            # 번역문을 이어붙인 전체 텍스트
    translation_error: str
    # `trans_map`(원문→번역 dict)과 `translated_by_unit_id` 는 2026-08-14 에 뺐다 —
    # 만들기만 하고 **응답에도 없고 읽는 코드도 없었다.** 위치 정확도가 필요한 소비자는
    # 원래부터 `pairs` 를 써야 했다(같은 원문이 문서에 여러 번 나오면 dict 키가 충돌한다).
    stats: TranslationStats = field(default_factory=TranslationStats)
    glossary: dict = field(default_factory=dict)
    numeric_warnings: list = field(default_factory=list)
    options: dict = field(default_factory=dict)


@dataclass
class MarkdownTranslationArtifacts:
    """마크다운 구조 보존 번역(`markdown_units.py` 경로)의 산출물."""

    markdown: str            # 구조가 원본과 동일한 번역 마크다운 — **정본. 파일이 되는 값**
    source_markdown: str     # 원본 (UI 가 원문·번역본을 나란히 보여준다 — 요구사항 §2)
    pairs: list              # 유닛별 원문/번역 쌍 (하이라이트·검수용)
    translation_error: str
    # 사전 용어에 `<strong>` 을 입힌 **표시용 사본** (2026-08-14). 화면 전용이고 파일이
    # 되지 않는다 — 정본을 덮어쓰면 태그가 txt 에 실리고, 지우는 방식은 원문에 원래 있던
    # `<strong>` 까지 지운다. 사전이 안 걸린 문서에서는 `markdown` 과 같다.
    # 기본값이 있어야 하므로 **여기(기본값 있는 필드 구역)에 둔다** — 위쪽에 끼우면
    # `non-default argument follows default argument` 로 import 단계에서 죽는다.
    markdown_highlighted: str = ""
    stats: TranslationStats = field(default_factory=TranslationStats)
    glossary: dict = field(default_factory=dict)
    numeric_warnings: list = field(default_factory=list)
    options: dict = field(default_factory=dict)
