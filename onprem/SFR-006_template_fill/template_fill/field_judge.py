"""LLM 필드 추출·수정 의도 응답 검증.

LLM 응답을 믿지 않는다 (번역 파이프라인 validation.py 와 같은 취지):
- JSON 스키마가 어긋나면 해당 항목만 버리고 정상 항목만 채택한다
- 필드명은 템플릿 스키마 화이트리스트에 있는 것만 받는다
- 값 길이 상한을 넘으면 자른다 (result payload / 문서 폭주 방지)

버려진 키는 rejected 로 상위에 노출한다 — 실패를 침묵 처리하지 않는다.

**대화로 값을 지우는 경로**도 여기서 검증한다. "담당자는 지워줘" 를 표현할 방법이
`updates` 밖에 없으면 LLM 은 빈 문자열을 넣게 되고, 빈 값은 형식 위반으로 기각되므로
사용자 지시가 조용히 사라진다. 그래서 지움은 `clears` 배열로 분리해 받는다.
"""

import json
from dataclasses import dataclass, field as dc_field

from .config import Config


@dataclass(frozen=True)
class ParsedIntent:
    """검증을 통과한 이번 턴의 편집 의도.

    계약: `updates` 와 `clears` 는 **서로 겹치지 않는다.** 모순된 응답을 그대로 넘기면
    호출부마다 같은 해소 규칙을 다시 적어야 하고, 한 곳이 빠뜨리면 방금 채운 값을 지운다.
    """

    updates: dict = dc_field(default_factory=dict)   # {필드명: 새 값}
    clears: list = dc_field(default_factory=list)    # 비울 필드명
    rejected: list = dc_field(default_factory=list)  # 화이트리스트 밖 / 형식 위반
    conflicts: list = dc_field(default_factory=list)  # 수정·삭제가 함께 온 항목 (수정 채택)


def parse_updates(raw: str, allowed_names: set) -> ParsedIntent:
    """LLM 응답에서 수정·삭제 의도를 안전하게 추출한다.

    Args:
        raw: LLM 응답 원문.
        allowed_names: 템플릿에 실제 존재하는 필드명 집합 (화이트리스트).

    Returns:
        ParsedIntent — 검증 통과 항목만 담고, 버린 키는 rejected 로 노출한다.
    """
    parsed = _parse_json_object(raw)
    if parsed is None:
        return ParsedIntent(rejected=["<응답 전체: JSON 파싱 실패>"])
    updates = parsed.get("updates")
    clears_raw = parsed.get("clears")
    if updates is None and clears_raw is None:
        return ParsedIntent(rejected=["<응답 전체: updates/clears 없음>"])

    # 기각 사유는 실제 원인을 적는다 — "updates 가 없다"로 뭉개면 로그만 보고는
    # 어느 키가 어떻게 어긋났는지 알 수 없다 (기각 건수는 006 환각률 지표의 원천이다).
    rejected: list = []
    if updates is not None and not isinstance(updates, dict):
        rejected.append("<updates: 객체 아님>")
        updates = None
    # clears 만 온 응답도 유효하다 ("담당자 지워줘" 처럼 새 값이 없는 턴)
    updates = updates or {}
    if clears_raw is not None and not isinstance(clears_raw, list):
        rejected.append("<clears: 배열 아님>")
        clears_raw = None

    accepted: dict = {}
    for key, value in updates.items():
        name = str(key).strip()
        if name not in allowed_names:
            rejected.append(name)
            continue
        if isinstance(value, (list, dict)) or value is None:
            rejected.append(name)
            continue
        text = str(value).strip()
        if not text:
            # 빈 값은 '지움' 의도일 수 있지만 여기서 단정하지 않는다 — 지움은 clears 로만
            # 받는다. 추측으로 값을 지우면 사용자가 시키지 않은 삭제가 일어난다.
            rejected.append(name)
            continue
        accepted[name] = text[: Config.MAX_VALUE_CHARS]

    clears: list = []
    conflicts: list = []
    for key in clears_raw or ():
        name = str(key).strip()
        if not name or name not in allowed_names:
            rejected.append(name or "<빈 항목명>")
            continue
        if name in accepted:
            # 같은 항목을 고치라고도 하고 지우라고도 한 응답은 모순이다 — 더 구체적인
            # 지시인 '새 값'을 채택하고 지움은 버린다. 건수는 호출부가 로그로 남긴다.
            if name not in conflicts:
                conflicts.append(name)
            continue
        if name not in clears:
            clears.append(name)

    return ParsedIntent(
        updates=accepted, clears=clears, rejected=rejected, conflicts=conflicts
    )


def _parse_json_object(raw: str):
    """응답에서 JSON 객체를 관대하게 추출. 실패 시 None."""
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            try:
                result = json.loads(raw[start : end + 1])
                return result if isinstance(result, dict) else None
            except json.JSONDecodeError:
                return None
    return None
