"""용어사전 준수 확인 + UI 하이라이트 데이터 생성.

## 두 가지를 한 번에 낸다

1. **준수율** (`compliance`) — 원문에 사전 용어가 나왔을 때 번역문이 지정 용어를
   실제로 썼는가. 루트 `README.md` 018 지표 3절의 `glossary_compliance` 가 바로 이 값이고,
   지금까지는 운영 기능이 없어 측정 자체가 불가능했다(CLAUDE.md 가 지적한 공백).
   **프롬프트로 지시했으니 지켜졌겠지로 넘기지 않는다** — 코드가 다시 센다.

2. **하이라이트 데이터** (`term_map`, `hits`) — 요구사항 §2 "어떤 단어가 용어사전의
   어떤 단어를 참고했는지 UI 에서 알려줄 수 있어야 함".
   프론트 협의 전이므로 요구사항 §5 가 정한 대로 `{"원문 용어": "번역 용어"}` 평면
   JSON(`term_map`)을 기본으로 내고, 위치까지 필요할 때를 대비해 유닛 단위 상세(`hits`)를
   함께 싣는다. 프론트는 둘 중 편한 쪽을 쓴다.

## 미준수를 실패로 만들지 않는 이유

지정 용어를 안 썼다고 번역문을 버리면 문서 전체가 원문으로 되돌아간다. 그래서
번역은 그대로 내보내고 `hits[].applied=false` 와 준수율로 드러낸다 — 미측정·미준수를
통과로 보이지 않게 하는 저장소 원칙과 같다.
"""

from dataclasses import dataclass, field

from translation_pipeline.common.glossary_exact import contains_phrase, exact_match

from .languages import glossary_applies


@dataclass
class GlossaryReport:
    """용어사전 적용 결과."""

    # {원문 용어: 번역 용어} — 프론트 하이라이트 기본 형식 (요구사항 §5)
    term_map: dict = field(default_factory=dict)
    # [{term_source, term_target, unit_id, node_id, applied}] — 위치까지 필요할 때
    hits: list = field(default_factory=list)
    matched_count: int = 0   # 원문에서 사전 용어가 발견된 (용어×유닛) 건수
    applied_count: int = 0   # 그중 번역문이 지정 용어를 쓴 건수

    @property
    def compliance(self) -> float:
        """준수율. 사전 용어가 한 번도 안 나왔으면 1.0 (감점 대상 없음)."""
        if not self.matched_count:
            return 1.0
        return round(self.applied_count / self.matched_count, 4)

    def as_payload(self) -> dict:
        return {
            "term_map": self.term_map,
            "hits": self.hits,
            "matched_count": self.matched_count,
            "applied_count": self.applied_count,
            "compliance": self.compliance,
        }


def terms_for_batch(texts: list, target_lang: str, source_lang: str = "") -> list:
    """이 배치에 등장한 용어만 모은다 (프롬프트에 실을 목록).

    사전 전체를 프롬프트에 넣지 않는 이유는 `prompt_builder.py` 머리말에 있다.

    **적용 대상이 아닌 방향이면 조회 자체를 하지 않는다** (`languages.glossary_applies`).
    사전 파일에 실수로 다른 언어 항목이 들어와도 프롬프트에 실리지 않는다 —
    "그 언어는 LLM 만으로 번역" 이 배포 파일 내용에 좌우되면 정책이 아니다.
    """
    if not glossary_applies(source_lang, target_lang):
        return []
    found: list = []
    seen: set = set()
    for text in texts:
        matches, _ = exact_match(text, target_lang)
        for term in matches:
            if term.term_source not in seen:
                seen.add(term.term_source)
                found.append(term)
    return found


def build_report(
    units: list, translated_by_unit_id: dict, target_lang: str, source_lang: str = ""
) -> GlossaryReport:
    """번역이 끝난 뒤 유닛별로 준수 여부를 판정한다.

    Args:
        units: TranslationUnit 목록 (원문).
        translated_by_unit_id: 번역 결과.
        target_lang: 대상 언어 코드 — 사전 색인 키.
        source_lang: 원문 언어 코드. 적용 대상 방향인지 판정하는 데만 쓴다.

    적용 대상이 아니면 **빈 보고서**다. `matched_count=0` 이므로 `compliance` 는 1.0 이고,
    그 1.0 은 "지킬 게 없었다" 는 뜻이다 — 응답의 `glossary.source.reason` 이
    `not_applicable` 로 그 사실을 따로 말한다(준수율만 보면 구분되지 않는다).
    """
    if not glossary_applies(source_lang, target_lang):
        return GlossaryReport()
    report = GlossaryReport()
    for unit in units:
        matches, _ = exact_match(unit.text, target_lang)
        if not matches:
            continue
        translated = translated_by_unit_id.get(unit.translation_unit_id, "")
        for term in matches:
            applied = contains_phrase(translated, term.term_target)
            report.matched_count += 1
            report.applied_count += 1 if applied else 0
            report.term_map.setdefault(term.term_source, term.term_target)
            report.hits.append(
                {
                    "term_source": term.term_source,
                    "term_target": term.term_target,
                    "unit_id": unit.translation_unit_id,
                    "node_id": unit.node_id,
                    "applied": applied,
                }
            )
    return report
