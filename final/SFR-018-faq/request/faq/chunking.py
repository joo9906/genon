"""문서를 LLM 한 번에 실을 크기로 나누고, 생성 개수를 그 조각들에 배분한다.

## 왜 생겼나 — 문서 **앞부분만** FAQ 후보가 되는 것을 막는다

예산(`FAQ_MAX_CONTEXT_CHARS`)을 넘는 문서를 `source[:예산]` 으로 잘라 한 번만 LLM 에
보내면, 잘린 뒷부분은 **FAQ 후보에서 통째로 빠지고 기각 건수에도 잡히지 않는다** —
LLM 이 본 적이 없으니 `ungrounded` 도 `duplicate` 도 아니다. 사내 규정집·업무 매뉴얼은
대부분 그 예산을 넘으므로, 자르는 방식으로는 **언제나 앞부분만** FAQ 가 된다.

그래서 문서 전체를 조각으로 나눠 **각 조각이 자기 몫의 FAQ 를 만든다.**

## 두 가지를 여기서 정한다

1. **어디서 자르나** (`split_for_context`) — 조각 하나가 LLM 호출 한 번의 예산이다.
2. **누구에게 몇 개를 맡기나** (`plan_quota`) — 사용자가 고른 **총 개수**를 조각들에
   나눈다. 모든 조각이 최소 1개를 받는다.

## 조각은 하나도 건너뛰지 않는다

**모든 조각이 LLM 호출 한 번씩을 받는다.** 호출 수·조각 수에 상한이 없으므로 문서의
어느 구간도 LLM 이 보지 못한 채 남지 않는다. 사용자가 고른 **총 개수**는 조각들이 나눠
갖고, 조각당 몫은 1 밑으로 내려가지 않는다 — 조각이 고른 개수보다 많으면 받는 개수가
조각 수만큼 늘어난다. 조각을 건너뛰어 개수를 맞추면 그 구간의 내용은 FAQ 후보에서
조용히 빠진다.

## 근거 대조는 조각이 아니라 **문서 전체**로 한다 (호출부 규약)

조각 경계가 문장 가운데를 지나면 그 문장을 근거로 든 항목이 **조각으로 대조할 때만**
기각된다. `EvidenceChecker` 를 전문으로 만들면 그 오탐이 없다 — 이 모듈이 조각을
겹치게 만들지 않는 이유이기도 하다.
"""

# 제목 줄에서 새 조각을 시작할지 판단하는 문턱. 예산의 이 비율을 넘겼을 때 제목을
# 만나면 거기서 끊는다. 낮추면 조각이 잘게 쪼개져 호출당 문맥이 얇아지고, 높이면
# 제목 경계를 못 살리고 예산에서 잘린다.
_HEADING_BREAK_RATIO = 0.6


def _is_heading(line: str) -> bool:
    """마크다운 제목 줄. 전처리기·hwpx 파서 산출물이 모두 `#` 표기를 쓴다."""
    stripped = line.lstrip()
    return stripped.startswith("#") and stripped.lstrip("#").startswith((" ", "\t"))


def _hard_split(line: str, budget: int) -> list:
    """한 줄이 예산보다 긴 경우(한 줄 HTML 표가 대표적)에만 쓰는 최후 수단."""
    return [line[start: start + budget] for start in range(0, len(line), budget)]


def split_for_context(text: str, budget: int) -> list:
    """문서를 `budget` 자 이하 조각들로 나눈다. **버리는 글자는 없다.**

    Args:
        text: 전처리기 마크다운 또는 hwpx 직접 파싱 결과.
        budget: 조각 하나의 최대 길이 (LLM 호출 한 번의 예산).

    Returns:
        조각 목록. 빈 문서면 빈 목록.

    자르는 자리는 **줄 경계**이고, 예산의 60% 를 넘긴 뒤 제목을 만나면 그 앞에서
    끊는다 — 조각이 절 단위로 떨어져야 그 안에서 뽑은 FAQ 가 한 주제로 묶인다.
    """
    if not text or budget <= 0:
        return []

    chunks: list = []
    current: list = []
    size = 0

    def flush() -> None:
        nonlocal current, size
        if current:
            chunk = "\n".join(current).strip()
            if chunk:
                chunks.append(chunk)
        current, size = [], 0

    for line in text.split("\n"):
        if len(line) > budget:
            # 줄 하나가 예산을 넘는다 — 여기서 나누지 않으면 이 조각이 통째로 상한을
            # 넘겨 LLM 이 뒤를 잘라 버린다(그 절단은 우리에게 보이지 않는다).
            flush()
            chunks.extend(piece for piece in _hard_split(line, budget) if piece.strip())
            continue

        # +1 은 join 이 넣을 개행. 이걸 빼면 조각이 예산을 조금씩 넘는다.
        if current and size + len(line) + 1 > budget:
            flush()
        elif current and size >= budget * _HEADING_BREAK_RATIO and _is_heading(line):
            flush()

        current.append(line)
        size += len(line) + 1

    flush()
    return chunks


def plan_quota(chunk_count: int, total: int) -> list:
    """조각별 생성 개수. **모든 조각이 최소 1개를 받는다.**

    Args:
        chunk_count: 조각 수.
        total: 이 문서에서 만들 **총 개수** (사용자 선택 · 상한 안으로 깎인 값).

    Returns:
        길이 `chunk_count` 의 목록. 합은 `max(total, chunk_count)` 이다 — 조각이 총 개수보다
        많으면 조각당 1개씩이라 합이 조각 수가 된다. 조각이 없거나 `total` 이 0 이하면 전부 0.

    나누어떨어지지 않는 나머지는 앞쪽 조각부터 한 개씩 얹는다. 한 조각에 몰아주면 그
    구간만 과대표된다.
    """
    if chunk_count <= 0:
        return []
    if total <= 0:
        return [0] * chunk_count

    base, remainder = divmod(max(total, chunk_count), chunk_count)
    return [base + (1 if index < remainder else 0) for index in range(chunk_count)]
