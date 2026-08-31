"""문서를 LLM 한 번에 실을 크기로 나누고, 생성 개수를 그 조각들에 배분한다.

## 왜 생겼나 — 문서 **앞부분만** FAQ 후보였다

그전에는 상한(`FAQ_MAX_CONTEXT_CHARS`)을 넘으면 `source[:상한]` 으로 잘라 한 번만
LLM 에 보냈다. 잘린 뒷부분은 **FAQ 후보에서 통째로 빠졌고, 기각 건수에도 잡히지
않았다** — 애초에 LLM 이 본 적이 없으니 `ungrounded` 도 `duplicate` 도 아니다.
`source_truncated` 플래그 하나가 그 사실을 말하는 유일한 흔적이었는데, 그 값은
"뒤쪽에서 FAQ 가 안 나온 이유" 를 묻기 전에는 아무도 보지 않는다.

사내 규정집·업무 매뉴얼은 대부분 그 상한을 넘는다. 즉 **상한을 넘는 문서에서는
언제나 앞부분만** FAQ 가 됐다.

지금은 문서 전체를 조각으로 나눠 **각 조각이 자기 몫의 FAQ 를 만든다.** 실질 상한은
업로드 용량(`FAQ_MAX_UPLOAD_BYTES`)이고, 그 안쪽 문서는 끝까지 후보가 된다.

## 두 가지를 여기서 정한다

1. **어디서 자르나** (`split_for_context`) — 조각 하나가 LLM 호출 한 번의 예산이다.
2. **몇 조각을 태우나** (`plan_quota`) — 조각마다 사용자가 고른 개수를 뽑고, 총량
   상한에 닿으면 멈춘다. 태울 조각은 **문서 전체에서 고르게 표집한다.** 앞에서부터
   채우면 잘라내던 시절과 결과가 같아진다(앞부분만 FAQ 가 된다).

## 개수는 조각 수로 나누지 않는다 (2026-08-31 변경)

그전에는 **총 개수를 조각들이 나눠 가졌다.** 그러면 문서가 길어질수록 한 조각의 몫이
0 에 가까워진다 — 40조각짜리 규정집에서 5개를 요청하면 조각당 0~1개이고, 그 조각을
대표하는 FAQ 가 나올 수 없다. 개수를 고르는 사람이 원한 것은 "문서 전체에서 5개" 가
아니라 "쓸 만한 FAQ" 다.

지금은 **조각당 개수가 고정**(사용자 선택)이고 **몇 조각을 태울지를 총량 상한**
(`FAQ_MAX_TOTAL_COUNT`, 기본 30)이 정한다. 구간당 5개면 여섯 구간이다. 호출 수도
그만큼이라 비용은 여전히 문서 길이가 아니라 **설정된 상한**에 묶인다.

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


def plan_quota(chunk_count: int, per_chunk: int, total_cap: int) -> list:
    """조각별 생성 개수. 조각마다 `per_chunk` 개씩이고 합은 `total_cap` 을 넘지 않는다.

    Args:
        chunk_count: 조각 수.
        per_chunk: **한 조각에서 뽑을 개수** (사용자 선택 · 조각당 상한 안으로 깎인 값).
        total_cap: 문서 하나의 총량 상한 (`FAQ_MAX_TOTAL_COUNT`).

    Returns:
        길이 `chunk_count` 의 목록. 0 인 조각은 LLM 을 부르지 않는다.
        합은 `min(chunk_count * per_chunk, total_cap)` 이다.

    **개수를 조각 수로 나누지 않는다** (2026-08-31 변경). 그전에는 총 개수를 조각들이
    나눠 가져서, 문서가 길어질수록 한 조각의 몫이 0 에 가까워졌다 — 40조각 문서에서
    5개를 요청하면 조각당 0~1개이고, 그 조각을 대표하는 FAQ 가 나올 수 없다. 지금은
    조각당 개수를 고정하고 **몇 조각을 태울지**를 총량 상한이 정한다.

    **태울 조각은 고르게 표집한다** — 앞에서부터 채우면 문서를 잘라 쓰던 시절과 결과가
    같아진다(앞부분만 FAQ 가 된다). 총량이 조각 전체를 덮지 못하는 사실은 호출부가
    `coverage_capped` 로 낸다: 조용히 건너뛰면 사용자는 문서 전체에서 뽑은 결과로 읽는다.
    """
    if chunk_count <= 0 or per_chunk <= 0 or total_cap <= 0:
        return [0] * max(0, chunk_count)

    # 태울 조각 수. 나머지가 남으면 마지막 한 조각이 그만큼만 맡는다 — 예산을 남기면
    # 사용자가 받을 수 있는 개수를 우리가 버리는 것이다.
    slots = min(chunk_count, -(-total_cap // per_chunk))

    quota = [0] * chunk_count
    budget = total_cap
    for order in range(slots):
        # 구간 중점 표집 — 조각 수와 태울 수가 어떤 조합이어도 자리가 겹치지 않고
        # 문서 앞뒤로 치우치지 않는다.
        picked = min(((2 * order + 1) * chunk_count) // (2 * slots), chunk_count - 1)
        take = min(per_chunk, budget)
        # `+=` 로 둔다 — 표집이 겹치는 경우가 생겨도 총량이 새지 않는다.
        quota[picked] += take
        budget -= take
        if budget <= 0:
            break
    return quota
