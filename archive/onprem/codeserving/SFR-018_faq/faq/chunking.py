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
2. **누구에게 몇 개를 맡기나** (`plan_quota`) — 사용자가 고른 **총 개수**를 조각들에
   나눈다. 태울 조각은 **문서 전체에서 고르게 표집한다.** 앞에서부터 채우면 잘라내던
   시절과 결과가 같아진다(앞부분만 FAQ 가 된다).

## 사용자는 총 개수만 고른다 (2026-09-03 요구 확정)

**사용자 선택 = 문서 하나에서 만들 총 개수**이고, 그것을 어느 구간에서 몇 개씩 뽑을지는
우리가 정한다. 고른 숫자가 곧 받는 개수다.

2026-08-31~09-02 에는 선택이 **구간당** 개수였다(총량은 `FAQ_MAX_TOTAL_COUNT` 가 잡았다).
긴 문서에서 구간당 몫이 0 에 가까워지는 것을 막으려던 것인데, 대신 **고른 숫자와 받는
개수가 달라졌다** — 구간이 여섯이면 5를 골라도 30개가 나온다.

그 결함(몫 0)은 이제 **호출 수 상한**(`FAQ_MAX_CHUNK_CALLS`, 기본 6)이 막는다: 태울
조각 수를 그 값으로 묶으므로 조각이 40개여도 여섯 조각이 총 개수를 나눠 갖고, 각
조각의 몫은 1 밑으로 내려가지 않는다. **개수는 사용자가, 비용은 배포가** 정한다 —
둘을 한 손잡이에 묶으면 둘 중 하나를 못 지킨다.

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


def plan_quota(chunk_count: int, total: int, max_calls: int) -> list:
    """조각별 생성 개수. **합은 정확히 `total` 이다** (조각이 없을 때만 0).

    Args:
        chunk_count: 조각 수.
        total: 이 문서에서 만들 **총 개수** (사용자 선택 · 상한 안으로 깎인 값).
        max_calls: LLM 호출 수 상한 (`FAQ_MAX_CHUNK_CALLS`). 태울 조각 수가 곧 호출 수다.

    Returns:
        길이 `chunk_count` 의 목록. 0 인 조각은 LLM 을 부르지 않는다. 합은 `total`.

    **총 개수를 우리가 조각에 배분한다** (2026-09-03 요구 확정). 사용자는 "몇 개를
    받을지" 만 고르고 배분은 코드가 정한다 — 그전(2026-08-31~09-02)에는 사용자 선택이
    구간당 개수여서 고른 숫자와 받는 개수가 달랐다(구간이 여섯이면 5를 골라도 30개).

    **몫은 태울 조각들에 고르게 나눈다.** 나누어떨어지지 않는 나머지는 앞쪽 조각부터
    한 개씩 얹는다 — 한 조각에 몰아주면 그 구간만 과대표된다.

    **호출 수는 `max_calls` 가 잡는다.** 이것이 없으면 30개를 30조각에 1개씩 배정해
    호출이 30번이 되고, 비용이 문서 길이에 비례한다. 조각당 몫이 1 밑으로 내려갈 수
    없으므로 태울 조각 수는 `total` 로도 제한된다 (총 3개면 세 조각만 태운다).

    **태울 조각은 고르게 표집한다** — 앞에서부터 채우면 문서를 잘라 쓰던 시절과 결과가
    같아진다(앞부분만 FAQ 가 된다). 조각 전체를 덮지 못하는 사실은 호출부가
    `coverage_capped` 로 낸다: 조용히 건너뛰면 사용자는 문서 전체에서 뽑은 결과로 읽는다.
    """
    if chunk_count <= 0 or total <= 0 or max_calls <= 0:
        return [0] * max(0, chunk_count)

    # 태울 조각 수 = 호출 수. 총 개수보다 많이 태울 수 없다 — 몫이 0 인 조각을 부르는
    # 것은 빈 요청이다.
    slots = min(chunk_count, total, max_calls)
    base, remainder = divmod(total, slots)

    quota = [0] * chunk_count
    for order in range(slots):
        # 구간 중점 표집 — 조각 수와 태울 수가 어떤 조합이어도 자리가 겹치지 않고
        # 문서 앞뒤로 치우치지 않는다.
        picked = min(((2 * order + 1) * chunk_count) // (2 * slots), chunk_count - 1)
        # `+=` 로 둔다 — 표집이 겹치는 경우가 생겨도 총량이 새지 않는다.
        quota[picked] += base + (1 if order < remainder else 0)
    return quota
