"""006 E2E 멀티턴 시나리오 지표 (`Numeric` + `Structure`).

README:
- `Numeric`: 시나리오별 최종 완성 성공률, 완성까지 턴 수
- `Structure`: 세션 누적 정확성 — 이전 턴 값 유실·덮어쓰기 오류 없음

세션 누적 정확성 정의 (파일 기반 세션 저장소의 실패 모드에 맞춘 것):
- **유실**: 이전 턴 세션에 있던 필드가 다음 턴 세션에서 사라짐
- **덮어쓰기 오류**: 그 턴에서 추출하지 않은 필드의 값이 바뀜

두 실패 모두 사용자가 다시 말하지 않은 값이 조용히 없어지는 경우라
"채워짐 판정 일치율 100%" 계약과 직접 연결된다.
"""

from .error_codes import ERR_EMPTY_ITEMS, ERR_GOLD_REQUIRED, fail
from .normalize import normalize


def score_scenario(scenario: dict) -> dict:
    """시나리오 1건 채점.

    scenario: {
      "id": "...",
      "required_fields": ["문서제목", ...],       # 완성 판정 기준 (필수)
      "turns": [{"extracted": {필드:값}, "session_after": {필드:값}}, ...]
    }
    """
    required = [str(f) for f in scenario.get("required_fields") or []]
    if not required:
        fail(ERR_GOLD_REQUIRED, event="scenario_required_fields_missing")
    turns = scenario.get("turns") or []
    if not turns:
        fail(ERR_EMPTY_ITEMS, event="scenario_no_turns")

    lost, overwritten = [], []
    turns_to_complete = None
    previous: dict = {}

    for index, turn in enumerate(turns, start=1):
        session = {str(k): str(v) for k, v in (turn.get("session_after") or {}).items()}
        extracted = {str(k) for k in (turn.get("extracted") or {})}

        for name, value in previous.items():
            if name not in session:
                lost.append({"turn": index, "field": name})
            elif normalize(session[name]) != normalize(value) and name not in extracted:
                overwritten.append(
                    {"turn": index, "field": name, "before": value, "after": session[name]}
                )

        if turns_to_complete is None and all(
            name in session and str(session[name]).strip() for name in required
        ):
            turns_to_complete = index
        previous = session

    return {
        "id": scenario.get("id"),
        "turns": len(turns),
        "completed": turns_to_complete is not None,
        "turns_to_complete": turns_to_complete,
        "lost_values": lost,
        "overwritten_values": overwritten,
        "session_accuracy_passed": not lost and not overwritten,
        "missing_at_end": [
            name for name in required if not str(previous.get(name, "")).strip()
        ],
    }


def aggregate_scenarios(scenarios: list) -> dict:
    """시나리오 묶음 집계 — 완성 성공률, 완성 턴 수 분포, 세션 누적 실패 건."""
    if not scenarios:
        fail(ERR_EMPTY_ITEMS, event="scenario_input_empty")

    scored = [score_scenario(s) for s in scenarios]
    completed = [s for s in scored if s["completed"]]
    turn_counts = sorted(s["turns_to_complete"] for s in completed)
    session_failures = [s for s in scored if not s["session_accuracy_passed"]]

    mid = len(turn_counts) // 2
    return {
        "scenarios": len(scored),
        "completion_rate": round(len(completed) / len(scored), 4),
        "turns_to_complete": {
            "mean": round(sum(turn_counts) / len(turn_counts), 2) if turn_counts else None,
            "median": (
                turn_counts[mid]
                if turn_counts and len(turn_counts) % 2
                else (turn_counts[mid - 1] + turn_counts[mid]) / 2 if turn_counts else None
            ),
            "max": turn_counts[-1] if turn_counts else None,
        },
        "session_accuracy_rate": round((len(scored) - len(session_failures)) / len(scored), 4),
        "session_failures": [
            {
                "id": s["id"],
                "lost_values": s["lost_values"],
                "overwritten_values": s["overwritten_values"],
            }
            for s in session_failures
        ],
        "incomplete": [
            {"id": s["id"], "missing_at_end": s["missing_at_end"]}
            for s in scored
            if not s["completed"]
        ],
    }
