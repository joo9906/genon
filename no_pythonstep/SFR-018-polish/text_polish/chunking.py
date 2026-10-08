"""문서를 LLM 호출 단위로 나누고, 다듬은 조각을 **원문 그대로의 자리**에 되꽂는다.

## 왜 생겼나 — 긴 문서는 타임아웃이 먼저 왔다

이 단위는 셋 중 유일하게 **문서 전체를 한 번에** LLM 에 보냈다(문장 문맥이 필요하다는
이유였다). 그런데 입력 상한은 20만 자인데 `RES_TIMEOUT` 은 90초라, 그 사이 어딘가에서
**상한에 닿기 한참 전에 타임아웃이 먼저 난다.** 그 실패는 재시도 가능(00020001)으로
분류돼 같은 자리에서 또 걸리므로, 사용자에게는 "긴 문서는 그냥 안 되는 기능" 이다.

**나눠도 되는 이유**: 이 기능이 하는 일은 내용을 다시 쓰는 것이 아니라 **문체에 맞게
낱말·어미를 손질하는 것**이다. 판단 단위가 문장이라 조각 경계 너머의 문맥이 필요하지
않다. 번역이 유닛 단위로 도는 것과 같은 근거다.

## 이 모듈의 계약 두 개

1. **무손실 분해** — `"".join(chunk.text + chunk.suffix for chunk in chunks)` 가
   원문과 **문자 단위로 같다.** 조각이 실패하면 그 자리에 원문을 그대로 되꽂아야 하는데,
   경계에서 개행 하나라도 잃으면 그 자리에서 문단·표가 붙어 버린다.
2. **구조를 가르지 않는다** — 코드펜스 안과 여러 줄 HTML 표 가운데에서 끊지 않는다.
   절반만 LLM 에 주면 그 조각의 출력이 표·코드로 보이지 않고, `markdown_structure_issues`
   가 잡는 그 훼손을 **우리가 만들어 내는** 셈이 된다. 둘 다 **안에 빈 줄이 올 수 있어서**
   따로 다뤄야 한다 — 마크다운 표는 빈 줄이 없으므로 경계 규칙만으로 이미 안전하고,
   따로 떼는 것은 앞뒤 문단이 표에 붙어 덩어리가 커지는 것을 막기 위해서다.

## 조각의 꼬리(`suffix`)를 따로 든다

경계는 언제나 빈 줄이므로 조각 사이에는 `\\n\\n` 이 있다. 그런데 LLM 은 응답 끝의 공백을
지운다 — 다듬은 조각을 그냥 이어붙이면 **문단 경계가 사라져** 제목과 본문이 한 줄이 된다.
그래서 조각을 (본문, 꼬리 공백)으로 갈라 **본문만 LLM 에 보내고 꼬리는 코드가 되꽂는다.**
"""

import re
from dataclasses import dataclass

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_TABLE_LINE_RE = re.compile(r"^\s*\|")
_HTML_TABLE_OPEN_RE = re.compile(r"<table\b", re.IGNORECASE)
_HTML_TABLE_CLOSE_RE = re.compile(r"</table\s*>", re.IGNORECASE)


@dataclass(frozen=True)
class PolishChunk:
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
            # 빈 줄은 앞 덩어리에 붙인다 — 꼬리 공백은 `_to_chunks` 가 따로 떼어 낸다.
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
            # 되는 것**을 막는 것이다. 가르면 안 되는 덩어리가 크면 조각이 예산을 크게
            # 넘고, 그러면 나눈 의미가 없어진다.
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


def _to_chunk(raw: str) -> PolishChunk:
    """덩어리에서 꼬리 공백을 떼어 낸다. `text + suffix == raw` 다."""
    text = raw.rstrip()
    return PolishChunk(text=text, suffix=raw[len(text):])


def split_for_polish(text: str, budget: int) -> list:
    """다듬기 조각 목록. **이어붙이면 원문과 문자 단위로 같다.**

    Args:
        text: 다듬을 본문.
        budget: 조각 하나의 목표 크기 (LLM 호출 한 번의 예산).

    Returns:
        `PolishChunk` 목록. 빈 입력이면 빈 목록.

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


def rebuild(chunks: list, polished_by_index: dict) -> str:
    """다듬은 조각을 원래 자리에 되꽂아 문서를 만든다.

    Args:
        chunks: `split_for_polish` 결과.
        polished_by_index: {조각 번호: 다듬은 본문}. 없는 번호는 **원문을 쓴다** —
            실패한 조각을 빈 문자열로 두면 그 구간이 통째로 사라진 결과가 정상 응답처럼
            나간다.

    Returns:
        조립된 문서. 모든 조각이 실패하면 원문과 같다.
    """
    parts: list = []
    for index, chunk in enumerate(chunks):
        body = polished_by_index.get(index)
        parts.append(chunk.text if body is None else body)
        parts.append(chunk.suffix)
    return "".join(parts)
