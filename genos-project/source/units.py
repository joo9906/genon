"""문서 노드를 번역 단위(TranslationUnit)로 변환/역변환.

PoC 범위: 노드 하나 = 번역 단위 하나로 단순화한다.
실제 서비스에서는 문장 분리, 문맥 스코프(슬라이드/표) 묶기 등이 이 파일 안에서
확장되어야 하며, 다른 모듈(translation_modes 등)은 이 파일의 출력 형식만 알면 된다.
"""

from typing import Dict, List

from .types import TranslationUnit


def build_translation_units(nodes: List[dict]) -> List[TranslationUnit]:
    units: List[TranslationUnit] = []
    for idx, node in enumerate(nodes):
        units.append(
            TranslationUnit(
                translation_unit_id=idx,
                node_id=str(node.get("id", idx)),
                text=str(node.get("text", "")),
                element_type=str(node.get("type", "")),
                context_scope=str(node.get("scope", "")),
                context_text=str(node.get("context", "")),
            )
        )
    return units


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
                "original": unit.text,
                "translated": translated,
                "type": unit.element_type,
            }
        )
    return pairs
