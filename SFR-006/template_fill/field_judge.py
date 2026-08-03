"""LLM 필드 추출 응답 검증 + mock 추출기.

LLM 응답을 믿지 않는다 (CLAUDE.md §5, 번역 파이프라인 validation.py 와 같은 취지):
- JSON 스키마가 어긋나면 해당 항목만 버리고 정상 항목만 채택한다
- 필드명은 템플릿 스키마 화이트리스트에 있는 것만 받는다
- 값 길이 상한을 넘으면 자른다 (result payload / 문서 폭주 방지)

버려진 키는 rejected 로 상위에 노출한다 — 실패를 침묵 처리하지 않는다.
"""

import json
import re

from .config import Config

_MOCK_LINE_RE = re.compile(r"^\s*(?P<name>[^:：]{1,80}?)\s*[:：]\s*(?P<value>.+?)\s*$")


def parse_updates(raw: str, allowed_names: set) -> tuple[dict, list]:
    """LLM 응답에서 updates 를 안전하게 추출한다.

    Args:
        raw: LLM 응답 원문.
        allowed_names: 템플릿에 실제 존재하는 필드명 집합 (화이트리스트).

    Returns:
        (accepted, rejected)
        accepted: {필드명: 값} — 검증 통과 항목만.
        rejected: 화이트리스트 밖이거나 형식이 어긋나 버린 키 목록.
    """
    parsed = _parse_json_object(raw)
    if parsed is None:
        return {}, ["<응답 전체: JSON 파싱 실패>"]

    updates = parsed.get("updates")
    if not isinstance(updates, dict):
        return {}, ["<응답 전체: updates 객체 없음>"]

    accepted: dict = {}
    rejected: list = []
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
            rejected.append(name)
            continue
        accepted[name] = text[: Config.MAX_VALUE_CHARS]
    return accepted, rejected


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


def mock_extract(user_message: str, allowed_names: set) -> tuple[dict, list]:
    """LLM 없이 '필드명: 값' 줄 형식을 파싱하는 mock 추출기.

    폐쇄망에서 LLM 서빙 없이 워크플로우 구조(세션 누적 → 판정 → 다운로드)를
    끝까지 검증하기 위한 테스트 모드 (저장소 컨벤션 — mock/noop 상시 유지).
    """
    accepted: dict = {}
    rejected: list = []
    for line in user_message.splitlines():
        match = _MOCK_LINE_RE.match(line)
        if not match:
            continue
        name = match.group("name").strip()
        if name in allowed_names:
            accepted[name] = match.group("value")[: Config.MAX_VALUE_CHARS]
        else:
            rejected.append(name)
    return accepted, rejected
