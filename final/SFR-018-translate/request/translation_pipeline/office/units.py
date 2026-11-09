"""번역 단위(TranslationUnit)와 번역 결과를 화면용 원문/번역 쌍으로 묶는다."""

from typing import Dict, List

from .types import TranslationUnit


def build_pairs(
    units: List[TranslationUnit],
    translated_by_unit_id: Dict[int, str],
) -> List[dict]:
    pairs = []
    for unit in units:
        translated = translated_by_unit_id.get(unit.translation_unit_id, unit.text)
        pairs.append(
            {
                "id": unit.node_id,
                # unit_id 를 함께 싣는다 — 용어사전 하이라이트(glossary.hits)와 숫자 경고가
                # 이 값으로 유닛을 가리키므로, 없으면 화면이 어느 쌍인지 되짚지 못한다.
                "unit_id": unit.translation_unit_id,
                "original": unit.text,
                "translated": translated,
                "type": unit.element_type,
            }
        )
    return pairs
