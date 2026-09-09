"""스트리밍 번역용 조각 분할 — 문서를 LLM 호출 단위로 나누고 되꽂는다.

> **이 파일은 `not/openai/` 판본에만 있다.** 글다듬이 `text_polish/chunking.py` 와
> **같은 규칙**이고, 이름과 머리말만 이 단위에 맞췄다. 배포 단위 간 import 가 금지라
> 사본이 된다 — 규칙을 고치면 두 곳을 함께 고친다.

## 왜 스켈레톤이 아니라 조각인가 — 그 대가를 먼저 적는다

정본 경로(`POST /translate/markdown`)는 문서를 **스켈레톤과 유닛으로 분해**해서 표
파이프·HTML 태그·제목 마커를 **코드가** 쥐고 셀·문장 텍스트만 LLM 에 보낸다. 그래서
구조 보존이 LLM 출력과 무관하게 보장된다 — 요구사항 §5 의 "표 깨짐" 을 코드로 막는
장치이고, 이 저장소가 "프롬프트 지시를 보장으로 보지 않는다" 고 말하는 자리다.

**스트리밍은 그 보장과 맞바꾼다.** 유닛은 배치 JSON(`{id, t}`)으로 오가므로 화면에
흘릴 것이 없고(원시 JSON 이 보인다), 배치 15개가 동시에 도는 순서도 문서 순서가
아니다. 흘리려면 **LLM 이 마크다운 본문을 그대로 내야** 하고, 그러면 구조를 지키는
주체가 코드에서 프롬프트로 넘어간다 — 글다듬이가 이미 그 자리에 있고, 그쪽은
`markdown_guard` 지문 대조로 **훼손을 감지**해서 알린다.

그래서 이 경로도 같은 규율을 따른다:

1. 구조를 **가르지 않는다** (아래 계약 2). 우리가 깨뜨리지는 않는다.
2. 끝나고 **대조해서 알린다** (`stream_pipeline.structure_diff`). 못 막는 대신 숨기지
   않는다.
3. **정본 경로를 지운 것이 아니다.** `POST /translate/markdown` 은 그대로 있고, 표가
   많은 문서는 그쪽이 맞다.

## 이 모듈의 계약 두 개

1. **무손실 분해** — `"".join(chunk.text + chunk.suffix for chunk in chunks)` 가
   원문과 **문자 단위로 같다.** 조각이 실패하면 그 자리에 원문을 그대로 되꽂아야 하는데,
   경계에서 개행 하나라도 잃으면 그 자리에서 문단·표가 붙어 버린다.
2. **구조를 가르지 않는다** — 코드펜스 안과 여러 줄 HTML 표 가운데에서 끊지 않는다.
   절반만 LLM 에 주면 그 조각의 출력이 표·코드로 보이지 않는다. 둘 다 **안에 빈 줄이
   올 수 있어서** 따로 다뤄야 한다 — 마크다운 표는 빈 줄이 없으므로 경계 규칙만으로
   이미 안전하고, 따로 떼는 것은 앞뒤 문단이 표에 붙어 덩어리가 커지는 것을 막기
   위해서다.

## 조각의 꼬리(`suffix`)를 따로 든다

경계는 언제나 빈 줄이므로 조각 사이에는 `\\n\\n` 이 있다. 그런데 LLM 은 응답 끝의 공백을
지운다 — 번역한 조각을 그냥 이어붙이면 **문단 경계가 사라져** 제목과 본문이 한 줄이 된다.
그래서 조각을 (본문, 꼬리 공백)으로 갈라 **본문만 LLM 에 보내고 꼬리는 코드가 되꽂는다.**
"""

import re
from dataclasses import dataclass

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_TABLE_LINE_RE = re.compile(r"^\s*\|")
_HTML_TABLE_OPEN_RE = re.compile(r"<table\b", re.IGNORECASE)
_HTML_TABLE_CLOSE_RE = re.compile(r"</table\s*>", re.IGNORECASE)


@dataclass(frozen=True)
class StreamChunk:
    """LLM 에 보낼 본문 + 코드가 되꽂을 꼬리 공백.

    `text + suffix` 를 순서대로 이으면 원문이 된다.
    """

    text: str      # LLM 에 보낼 알맹이 (앞뒤 공백 없음)
    suffix: str    # 이 조각과 다음 조각 사이의 원문 공백 (보통 "\n\n")

    @property
    def size(self) -> int:
        return len(self.text)


def _split_blocks(text: str) -> list:
    """원문을 **가르면 안 되는 최소 덩어리**로 나눈다. 이어붙이면 원문이다.

    빈 줄이 경계이고, 코드펜스 안과 표 블록은 빈 줄이 있어도 끊지 않는다.
    """
    lines = text.splitlines(keepends=True)
    blocks: list = []
    current: list = []
    in_fence = False
    in_html_table = False

    def close() -> None:
        nonlocal current
        if current:
            blocks.append("".join(current))
            current = []

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if in_fence:
            current.append(line)
            if _FENCE_RE.match(line):
                in_fence = False
                close()
            index += 1
            continue

        if in_html_table:
            current.append(line)
            if _HTML_TABLE_CLOSE_RE.search(line):
                in_html_table = False
                close()
            index += 1
            continue

        if _FENCE_RE.match(line):
            close()
            current.append(line)
            in_fence = True
            index += 1
            continue

        if _HTML_TABLE_OPEN_RE.search(line) and not _HTML_TABLE_CLOSE_RE.search(line):
            # 여러 줄로 펼쳐진 HTML 표. 한 줄짜리(지능형 전처리기 기본형)는 여기 안 걸리고
            # 아래 일반 줄로 처리된다 — 한 줄이면 가를 위험이 없다.
            close()
            current.append(line)
            in_html_table = True
            index += 1
            continue

        if not stripped:
            # 빈 줄은 앞 덩어리에 붙인다 — 꼬리 공백은 `_to_chunk` 가 따로 떼어 낸다.
            current.append(line)
            close()
            index += 1
            continue

        if _TABLE_LINE_RE.match(line):
            # 마크다운 표: `|` 로 시작하는 줄이 이어지는 동안 한 덩어리로 **떼어 낸다.**
            #
            # **표가 갈리는 것을 막는 코드가 아니다** — 표 안에는 빈 줄이 없으므로 빈 줄
            # 경계만으로도 갈리지 않는다. 이 분기가 하는 일은 앞뒤 문단이 빈 줄 없이
            # 표에 붙어 있을 때(전처리기 산출물에 흔하다) **그 문단들까지 한 덩어리가
            # 되는 것**을 막는 것이다.
            close()
            while index < len(lines) and _TABLE_LINE_RE.match(lines[index]):
                current.append(lines[index])
                index += 1
            close()
            continue

        current.append(line)
        index += 1

    close()
    return blocks


def _to_chunk(raw: str) -> StreamChunk:
    """덩어리에서 꼬리 공백을 떼어 낸다. `text + suffix == raw` 다."""
    text = raw.rstrip()
    return StreamChunk(text=text, suffix=raw[len(text):])


def split_for_translation(text: str, budget: int) -> list:
    """번역 조각 목록. **이어붙이면 원문과 문자 단위로 같다.**

    Args:
        text: 번역할 본문 (전처리기 마크다운 또는 hwpx 파싱 결과).
        budget: 조각 하나의 목표 크기 (LLM 호출 한 번의 예산).

    Returns:
        `StreamChunk` 목록. 빈 입력이면 빈 목록.

    가르면 안 되는 덩어리 하나가 예산보다 크면 **그 덩어리는 그대로 둔다** — 표를
    반으로 잘라 예산을 지키는 것보다 조각 하나가 큰 편이 낫다(구조 훼손은 되돌릴 수
    없고, 큰 조각은 느릴 뿐이다).
    """
    if not text or budget <= 0:
        return []

    blocks = _split_blocks(text)
    if not blocks:
        return []

    chunks: list = []
    buffer = ""
    for block in blocks:
        if buffer and len(buffer) + len(block) > budget:
            chunks.append(_to_chunk(buffer))
            buffer = block
            continue
        buffer += block
    if buffer:
        chunks.append(_to_chunk(buffer))

    # 앞뒤가 통째로 공백인 문서에서 `text` 가 빈 조각이 나올 수 있다. LLM 에 빈 문자열을
    # 보낼 수는 없으므로 호출부가 건너뛰고 원문(=꼬리)만 되꽂는다 — 여기서 버리면
    # 무손실 계약이 깨진다.
    return chunks


def rebuild(chunks: list, translated_by_index: dict) -> str:
    """번역한 조각을 원래 자리에 되꽂아 문서를 만든다.

    Args:
        chunks: `split_for_translation` 결과.
        translated_by_index: {조각 번호: 번역 본문}. 없는 번호는 **원문을 쓴다** —
            실패한 조각을 빈 문자열로 두면 그 구간이 통째로 사라진 결과가 정상 응답처럼
            나간다(번역의 전량/부분 폴백 규약과 같다).

    Returns:
        조립된 문서. 모든 조각이 실패하면 원문과 같다.
    """
    parts: list = []
    for index, chunk in enumerate(chunks):
        body = translated_by_index.get(index)
        parts.append(chunk.text if body is None else body)
        parts.append(chunk.suffix)
    return "".join(parts)
