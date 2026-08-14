"""용어사전 준수 확인 + UI 하이라이트 데이터 생성.

## 두 가지를 한 번에 낸다

1. **준수율** (`compliance`) — 원문에 사전 용어가 나왔을 때 번역문이 지정 용어를
   실제로 썼는가. 루트 `README.md` 018 지표 3절의 `glossary_compliance` 가 바로 이 값이고,
   지금까지는 운영 기능이 없어 측정 자체가 불가능했다(CLAUDE.md 가 지적한 공백).
   **프롬프트로 지시했으니 지켜졌겠지로 넘기지 않는다** — 코드가 다시 센다.

2. **하이라이트 데이터** (`term_map`, `hits`) — 요구사항 §2 "어떤 단어가 용어사전의
   어떤 단어를 참고했는지 UI 에서 알려줄 수 있어야 함".
   요구사항 §5 가 정한 `{"원문 용어": "번역 용어"}` 평면 JSON(`term_map`)을 기본으로 내고,
   위치까지 필요할 때를 위해 유닛 단위 상세(`hits`)를 함께 싣는다.

### `term_map` 은 **실제로 참고된 용어만** 담는다 (2026-08-14 변경)

그전에는 원문에 사전 용어가 나오기만 하면 들어갔다 — 번역문이 그 용어를 **안 썼어도**
(`applied=false`) 그대로였다. 요구사항은 "참고한 단어에 대해서만 표시" 인데, 그 형태로는
프론트가 `term_map` 을 그대로 하이라이트하면 **참고하지 않은 단어까지 표시된다.**
실측 예: `정산→settlement` 이 어느 유닛에서 `payout` 으로 번역됐는데도 term_map 에 남았다.

버리지는 않는다 — 매칭됐지만 미적용인 것은 `term_map_unapplied` 로 갈라 낸다.
"사전에 있는데 안 지켜졌다" 는 그 자체로 검수 대상이고, 준수율(0.67 같은 숫자)만으로는
**어느 용어가** 안 지켜졌는지 알 수 없다.

**두 map 은 겹칠 수 있다.** 판정은 유닛마다 하므로 같은 용어가 A 유닛에서는 적용되고 B
유닛에서는 안 될 수 있다 — 그때 양쪽에 다 들어간다(각각 "적어도 한 번 참고됨" /
"적어도 한 번 미적용" 이다). 평면 map 은 원래 이만큼만 말할 수 있다. **자리까지 정확히
가르려면 `hits` 를 쓴다** — 아래 `spans` 절이 그것을 위해 있다.

### `hits[].spans` — 원문 안 문자 위치 (2026-08-14 추가)

`unit_id`/`node_id` 만으로는 "이 유닛 어딘가" 까지다. 프론트가 문자열 검색으로 자리를
찾으면 같은 단어가 여러 번 나올 때 **사전이 걸린 자리와 아닌 자리를 구분하지 못한다.**
스캔(`glossary_exact.match_occurrences`)이 이미 알고 있던 값이라 새로 계산하지 않는다.

`spans` 는 **그 유닛 원문(`unit.text`) 기준 `[start, end)` 목록**이다. 한 유닛에 같은
용어가 두 번 나오면 원소가 둘이다. **`hits` 는 여전히 (용어×유닛) 하나**이고 등장마다
쪼개지 않는다 — `matched_count` 가 그 단위이고, 쪼개면 준수율 분모가 조용히 바뀐다.

## 미준수를 실패로 만들지 않는 이유

지정 용어를 안 썼다고 번역문을 버리면 문서 전체가 원문으로 되돌아간다. 그래서
번역은 그대로 내보내고 `hits[].applied=false` 와 준수율로 드러낸다 — 미측정·미준수를
통과로 보이지 않게 하는 저장소 원칙과 같다.

## 여기서 만든 것은 **본문에 섞이지 않는다**

하이라이트는 이 별도 메타데이터로만 나간다. 번역문(`markdown`)에 표시 기호를 심으면
`markdown_units` 가 지켜낸 구조 보존 계약을 우리가 깨뜨리고, 그 기호가 `POST /download`
의 txt 에 그대로 실려 **사용자가 메모장에서 손으로 지워야 한다.**
"""

from dataclasses import dataclass, field

from translation_pipeline.common.glossary_exact import contains_phrase, match_occurrences

from .languages import glossary_applies


@dataclass
class GlossaryReport:
    """용어사전 적용 결과."""

    # {원문 용어: 번역 용어} — **실제로 참고된 것만** (머리말 참고). 프론트 하이라이트 기본형
    term_map: dict = field(default_factory=dict)
    # {원문 용어: 번역 용어} — 사전에 있었지만 번역문이 안 쓴 것 (검수용, 하이라이트 대상 아님)
    term_map_unapplied: dict = field(default_factory=dict)
    # [{term_source, term_target, unit_id, node_id, applied, spans}] — 위치까지 필요할 때
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
            "term_map_unapplied": self.term_map_unapplied,
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
        for term, _start, _end in match_occurrences(text, target_lang):
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
        occurrences = match_occurrences(unit.text, target_lang)
        if not occurrences:
            continue
        translated = translated_by_unit_id.get(unit.translation_unit_id, "")

        # 같은 용어가 한 유닛에 여러 번 나오면 **위치만 모은다.** 판정과 건수는 용어 단위다
        # (머리말 "hits[].spans" 절 — 등장마다 쪼개면 준수율 분모가 조용히 바뀐다).
        spans_by_term: dict = {}
        target_by_term: dict = {}
        for term, start, end in occurrences:
            spans_by_term.setdefault(term.term_source, []).append([start, end])
            target_by_term.setdefault(term.term_source, term.term_target)

        for term_source, spans in spans_by_term.items():
            term_target = target_by_term[term_source]
            applied = contains_phrase(translated, term_target)
            report.matched_count += 1
            report.applied_count += 1 if applied else 0
            # **참고된 것만 term_map 에 넣는다** (머리말). 미적용은 버리지 않고 갈라 둔다 —
            # 준수율 숫자만으로는 어느 용어가 안 지켜졌는지 알 수 없다.
            if applied:
                report.term_map.setdefault(term_source, term_target)
            else:
                report.term_map_unapplied.setdefault(term_source, term_target)
            report.hits.append(
                {
                    "term_source": term_source,
                    "term_target": term_target,
                    "unit_id": unit.translation_unit_id,
                    "node_id": unit.node_id,
                    "applied": applied,
                    # 이 유닛 원문(`unit.text`) 기준 [start, end) — 등장 순서
                    "spans": spans,
                }
            )
    return report
