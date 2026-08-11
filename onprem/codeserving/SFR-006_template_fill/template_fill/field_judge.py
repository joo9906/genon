"""LLM 필드 추출·수정 의도 응답 검증.

LLM 응답을 믿지 않는다 (번역 파이프라인 validation.py 와 같은 취지):
- JSON 스키마가 어긋나면 해당 항목만 버리고 정상 항목만 채택한다
- 필드명은 템플릿 스키마 화이트리스트에 있는 것만 받는다
- 값 길이 상한을 넘으면 자른다 (result payload / 문서 폭주 방지)

버려진 키는 rejected 로 상위에 노출한다 — 실패를 침묵 처리하지 않는다.

**대화로 값을 지우는 경로**도 여기서 검증한다. "담당자는 지워줘" 를 표현할 방법이
`updates` 밖에 없으면 LLM 은 빈 문자열을 넣게 되고, 빈 값은 형식 위반으로 기각되므로
사용자 지시가 조용히 사라진다. 그래서 지움은 `clears` 배열로 분리해 받는다.

**본문 블록**(템플릿 항목 밖에 이어 쓰는 내용)의 검증 규율은 값과 다르다:222
- 내용(`text`)은 화이트리스트가 없다 — 애초에 템플릿에 없는 내용을 쓰라는 기능이다.
  대신 개수·길이 상한으로만 막는다.
- **서식(`style_ref`)은 화이트리스트를 건다.** 그 이름이 템플릿 문단을 가리켜야
  hwpx_blocks 가 복제할 원본을 찾는다. 다만 이름이 틀렸다고 내용을 버리지는 않는다 —
  기본 서식으로 넣고 기각 사유를 남긴다. 서식 오타 때문에 사용자가 쓴 글을 지우는 편이
  더 나쁘다.
"""

import json
from dataclasses import dataclass, field as dc_field

from .config import Config
from .hwpx_blocks import BodyBlock


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
    blocks: list = dc_field(default_factory=list)    # 이번 턴에 **추가**할 BodyBlock
    block_clears: list = dc_field(default_factory=list)  # 지울 블록 번호 (0-based, 오름차순)


def normalize_blocks(raw, allowed_styles=(), *, limit: int | None = None) -> tuple:
    """블록 입력을 BodyBlock 목록으로 정규화한다 (LLM·화면 공용).

    대화 경로와 `PUT /blocks` 가 같은 함수를 쓴다 — 각자 검증하면 한쪽에만 상한이
    걸리거나 서식 화이트리스트가 갈린다.

    Args:
        raw: 블록 배열. 각 항목은 `{"text": ..., "style_ref": ...}` 또는 문자열.
        allowed_styles: 서식으로 지정할 수 있는 항목명. 비어 있으면 검사하지 않는다
            (템플릿 색인이 아직 없는 호출부 대비).
        limit: 받아들일 최대 개수. 생략하면 `Config.MAX_BLOCKS`.

    Returns:
        (BodyBlock 목록, 기각 사유 목록)
    """
    cap = Config.MAX_BLOCKS if limit is None else limit
    allowed = set(allowed_styles or ())
    blocks: list = []
    rejected: list = []
    if raw is None:
        return blocks, rejected
    if not isinstance(raw, list):
        return blocks, ["<blocks: 배열 아님>"]

    for item in raw:
        if len(blocks) >= cap:
            rejected.append(f"<blocks: 개수 상한({cap}건) 초과>")
            break
        raw_text = ""
        if isinstance(item, str):
            text, style_ref = item, ""
        elif isinstance(item, dict):
            text = item.get("text")
            style_ref = item.get("style_ref") or item.get("style") or ""
            # 톤 적용 전 원문. 세션에서 되읽을 때만 들어 있고, LLM 응답에는 없다
            # (있어도 무시해야 할 값이 아니라 그냥 비어 있는 것이 정상이다).
            raw_text = str(item.get("raw_text") or "")[: Config.MAX_BLOCK_CHARS]
        else:
            rejected.append("<blocks: 항목이 객체/문자열 아님>")
            continue
        if isinstance(text, (list, dict)) or text is None:
            rejected.append("<blocks: text 없음>")
            continue
        cleaned = str(text).strip()[: Config.MAX_BLOCK_CHARS]
        if not cleaned:
            rejected.append("<blocks: text 비어 있음>")
            continue
        name = str(style_ref or "").strip()
        if name and allowed and name not in allowed:
            # 내용은 살리고 서식만 기본값으로 떨어뜨린다 (모듈 docstring 참고)
            rejected.append(f"<blocks.style_ref: {name}>")
            name = ""
        blocks.append(BodyBlock(text=cleaned, style_ref=name, raw_text=raw_text))
    return blocks, rejected


def _parse_block_clears(raw, block_count: int) -> tuple:
    """지울 블록 번호를 0-based 인덱스로 바꾼다.

    사용자와 LLM 이 보는 번호는 대화 답변에 표시된 **1-based** 번호다. 범위를 벗어나면
    조용히 무시하지 않고 기각으로 남긴다 — 지우라고 했는데 안 지워진 것을 알아야 한다.
    """
    indexes: list = []
    rejected: list = []
    if raw is None:
        return indexes, rejected
    if not isinstance(raw, list):
        return indexes, ["<block_clears: 배열 아님>"]
    for item in raw:
        try:
            number = int(str(item).strip())
        except (TypeError, ValueError):
            rejected.append(f"<block_clears: {item}>")
            continue
        if not 1 <= number <= block_count:
            rejected.append(f"<block_clears: {number}>")
            continue
        if number - 1 not in indexes:
            indexes.append(number - 1)
    return sorted(indexes), rejected


def parse_updates(
    raw: str,
    allowed_names: set,
    *,
    allowed_styles=(),
    block_count: int = 0,
) -> ParsedIntent:
    """LLM 응답에서 수정·삭제·본문 추가 의도를 안전하게 추출한다.

    Args:
        raw: LLM 응답 원문.
        allowed_names: 템플릿에 실제 존재하는 필드명 집합 (화이트리스트).
        allowed_styles: 본문 블록의 `style_ref` 로 쓸 수 있는 항목명.
        block_count: 지금 세션에 쌓여 있는 블록 수 (`block_clears` 범위 검사용).

    Returns:
        ParsedIntent — 검증 통과 항목만 담고, 버린 키는 rejected 로 노출한다.
    """
    parsed = _parse_json_object(raw)
    if parsed is None:
        return ParsedIntent(rejected=["<응답 전체: JSON 파싱 실패>"])
    updates = parsed.get("updates")
    clears_raw = parsed.get("clears")
    blocks_raw = parsed.get("blocks")
    block_clears_raw = parsed.get("block_clears")
    if all(v is None for v in (updates, clears_raw, blocks_raw, block_clears_raw)):
        return ParsedIntent(rejected=["<응답 전체: updates/clears/blocks 없음>"])

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

    blocks, block_rejected = normalize_blocks(blocks_raw, allowed_styles)
    rejected.extend(block_rejected)
    block_clears, clear_rejected = _parse_block_clears(block_clears_raw, block_count)
    rejected.extend(clear_rejected)

    return ParsedIntent(
        updates=accepted,
        clears=clears,
        rejected=rejected,
        conflicts=conflicts,
        blocks=blocks,
        block_clears=block_clears,
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
