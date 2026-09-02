"""대화(02) 답변 조립 — 사용자가 채팅 창에서 **읽는 것**만 만든다.

`run_chat.py` 에서 떼어 낸 이유: 한 턴의 흐름(무엇을 뽑고 어떻게 판정해 어디에 저장하는가)과
그 결과를 어떤 문장으로 보여줄 것인가는 바뀌는 이유가 다르다. 문구를 다듬는 일이 상태
전이 코드를 건드리게 두지 않는다.

## 답변이 반드시 담아야 하는 것

이 저장소의 규율이 "실패·변경을 침묵 처리하지 않는다" 인데, **그 약속이 실제로 지켜지는
마지막 지점이 여기다.** 로그에만 남기면 사용자는 모른다:

- **새로 채운 항목과 고친 항목을 구분한다.** LLM 이 사용자가 건드릴 의도가 없던 항목을
  덮어쓸 수 있고, `이전 → 새 값` 표시가 그것을 알아챌 유일한 수단이다.
- **기각 건수를 노출한다.** 템플릿에 없는 항목이라 못 넣었다는 사실을 사용자가 알아야
  다른 방법(본문 추가)을 택할 수 있다.
- **본문 추가 내용에 번호를 붙인다.** 사용자가 "2번 빼줘" 라고 지칭할 수단이고,
  LLM 도 같은 번호를 `block_clears` 로 돌려준다 — 화면의 번호와 LLM 이 보는 번호가
  같아야 엉뚱한 문단이 지워지지 않는다.
"""

from .hwpx_fields import missing_field_names

# 채팅 표시용 값 축약 길이 (현황표와 같은 기준)
_SHOWN_VALUE_CHARS = 30

# 토큰 스트리밍(`STREAM_CHUNK_CHARS`·`stream_chunks`)은 2026-08-14 에 이 파일에서 뺐다 —
# 2026-08-11 영역 재배치로 **스트리밍이 워크플로우 스텝의 일**이 됐고(`sfr006_03_commit.py`
# 의 `_stream_chunks`), 코드서빙에 남은 사본은 그때부터 아무도 부르지 않았다.
# 스텝은 자기완결이라 이쪽을 import 할 수도 없다.


def shorten(text: str) -> str:
    value = (text or "").strip()
    return value if len(value) <= _SHOWN_VALUE_CHARS else value[:_SHOWN_VALUE_CHARS] + "…"


def _change_notices(accepted: dict, previous: dict, cleared: list, rejected: list) -> list:
    """이번 턴에 무엇이 새로 들어가고, 무엇이 바뀌고, 무엇이 빠졌는지."""
    lines: list = []
    added = {k: v for k, v in accepted.items() if not (previous.get(k) or "").strip()}
    changed = {
        k: v for k, v in accepted.items() if (previous.get(k) or "").strip() and previous[k] != v
    }
    if added:
        lines.append("다음 내용을 반영했습니다.")
        lines.extend(f"- **{name}**: {value}" for name, value in added.items())
        lines.append("")
    if changed:
        lines.append("다음 항목을 고쳤습니다.")
        lines.extend(
            f"- **{name}**: {shorten(previous[name])} → {value}" for name, value in changed.items()
        )
        lines.append("")
    if cleared:
        lines.append("다음 항목을 비웠습니다.")
        for name in cleared:
            before = f" (이전: {shorten(previous[name])})" if previous.get(name) else ""
            lines.append(f"- **{name}**{before}")
        lines.append("")
    if rejected:
        # **이름을 함께 낸다** (2026-08-28). 건수만 말하면 사용자가 무엇을 다시 말해야
        # 하는지 모른다 — 그리고 payload 에서 `fields_rejected` 를 뺐으므로(채팅이 곧
        # 화면이다) 여기서 안 말하면 그 정보가 어디에도 남지 않는다.
        names = ", ".join(str(name) for name in rejected)
        lines.append(
            f"※ 템플릿에 없는 항목이라 반영하지 못한 내용이 {len(rejected)}건 있습니다: {names}"
        )
        lines.append("")
    return lines


def _status_table(specs, values: dict) -> tuple:
    """채움 현황표 + 아직 값이 필요한 항목 목록.

    부족 판정은 `missing_field_names` 하나만 쓴다 — 코드 서빙 `/status` 와 같은 함수다.
    갈라지면 채팅은 "다 됐다" 는데 다운로드 버튼은 꺼져 있는 상태가 된다.
    """
    still_needed = set(missing_field_names(specs, values))
    missing = [s for s in specs if s.name in still_needed]
    filled_count = len(specs) - len(missing)

    lines = [f"**작성 현황** ({filled_count}/{len(specs)})", "", "| 항목 | 상태 | 내용 |", "|---|---|---|"]
    for spec in specs:
        value = values.get(spec.name) or spec.current_value
        if value:
            lines.append(f"| {spec.name} | ✅ | {shorten(value)} |")
        else:
            lines.append(f"| {spec.name} | ⬜ 미입력 | {spec.guide or ''} |")
    lines.append("")
    return lines, missing


def _block_list(blocks) -> list:
    if not blocks:
        return []
    lines = [f"**본문 추가 내용** ({len(blocks)}문단)", ""]
    for number, block in enumerate(blocks, start=1):
        style = f" _{block.style_ref}_" if block.style_ref else ""
        lines.append(f"{number}.{style} {shorten(block.text)}")
    lines.append("")
    return lines


def _next_step(missing: list) -> list:
    """다음에 무엇을 하면 되는지. 남은 항목이 없으면 다운로드와 **본문 추가**를 함께 안내한다."""
    if missing:
        next_field = missing[0]
        hint = f" ({next_field.guide})" if next_field.guide else ""
        lines = [f"이어서 **{next_field.name}**{hint} 내용을 알려주세요."]
        if len(missing) > 1:
            others = ", ".join(s.name for s in missing[1:4])
            more = " 등" if len(missing) > 4 else ""
            lines.append(f"남은 항목: {others}{more}")
        return lines
    return [
        "모든 항목이 준비되었습니다. **다운로드 버튼**을 누르면 초안 파일을 생성해 드립니다.",
        "수정하고 싶은 항목이 있으면 말씀해 주세요. (예: 제목을 ○○로 바꿔줘)",
        # 항목이 다 찼다고 문서가 끝난 것은 아니다 — 본문을 더 쓸 수 있다는 사실을
        # 여기서 알리지 않으면 사용자는 템플릿 칸이 곧 문서 전부라고 생각한다.
        "본문에 내용을 더 넣고 싶으면 그대로 말씀해 주세요. "
        "(예: 아래에 추진 배경과 기대 효과를 덧붙여줘)",
    ]


def _prefill_notices(prefilled: dict, prefill_failed: bool, skipped_reason: str = "") -> list:
    """업로드 문서에서 자동으로 채운 것 (2026-08-31).

    **값까지 전부 나열한다.** 006 에는 값의 진위를 대조하는 층이 없다(요구 확정) — 항목명
    화이트리스트는 이름만 막고, 문서에 없는 값을 모델이 지어냈는지는 코드가 모른다.
    이 기능은 전용 UI 가 없어 **대화가 곧 화면**이므로, 여기 나열하는 것이 사용자가 잘못
    채워진 값을 발견하고 그 자리에서 고칠 수 있는 유일한 수단이다. 건수만 말하면 사용자는
    문서를 열어 하나하나 대조해야 한다.

    실패했다는 사실도 여기서 말한다. 조용히 넘기면 "문서를 올렸는데 아무 일도 일어나지
    않았다" 가 되고, 사용자는 기능이 없는 것으로 읽는다.

    **채울 자리가 없어 건너뛴 것도 말한다** (2026-09-02). 대화 중간에도 파일을 올릴 수
    있게 되면서 **항목을 다 채운 뒤 파일을 올리는 것이 정상 흐름**이 됐다 — 그때 아무
    말도 안 하면 위와 똑같이 "올렸는데 아무 일도 일어나지 않았다" 다. 이 문구가 한 번만
    나가는 것은 `/chat/prefill` 이 그 턴에 해시를 기록하기 때문이다(다음 턴부터는
    `already_applied` 로 조용히 빠진다).
    """
    lines: list = []
    if prefilled:
        lines.append(f"올려주신 문서에서 {len(prefilled)}개 항목을 채웠습니다. 확인해 주세요.")
        lines.extend(f"- **{name}**: {shorten(value)}" for name, value in prefilled.items())
        lines.append("틀린 값이 있으면 말씀해 주세요. (예: 제목을 ○○로 바꿔줘)")
        lines.append("")
    elif prefill_failed:
        lines.append(
            "※ 올려주신 문서에서 값을 자동으로 채우지 못했습니다. "
            "필요한 항목을 말씀해 주시면 채워 드리겠습니다."
        )
        lines.append("")
    elif skipped_reason == "no_pending_fields":
        # **값을 바꿔 주지 않는 이유를 함께 말한다.** 안 그러면 사용자는 "파일을 올렸는데
        # 왜 안 반영되나" 로 읽는다 — 기존 값을 덮지 않는 것이 요구다.
        lines.append(
            "※ 이미 모든 항목이 채워져 있어 올려주신 문서에서 추가로 채울 항목이 없습니다. "
            "값을 바꾸시려면 말씀해 주세요. (예: 제목을 ○○로 바꿔줘)"
        )
        lines.append("")
    return lines


def compose_status_reply(
    specs,
    values: dict,
    accepted: dict,
    rejected: list,
    *,
    previous: dict | None = None,
    cleared: list | None = None,
    blocks: list | None = None,
    added_blocks: list | None = None,
    dropped_blocks: list | None = None,
    prefilled: dict | None = None,
    prefill_failed: bool = False,
    prefill_skipped_reason: str = "",
) -> str:
    """이번 턴 반영 결과 + 채움 현황 + 다음 질문을 채팅 답변 하나로 조립한다."""
    # 문서 자동 채움을 **맨 위**에 둔다. 파일을 올린 턴에 사용자가 가장 먼저 확인해야
    # 하는 것이 "문서에서 무엇을 가져왔나" 다. (2026-09-02: 첫 턴 전용이 아니다 —
    # 대화 중간에 올린 파일도 같은 자리에 보고된다.)
    lines = _prefill_notices(prefilled or {}, prefill_failed, prefill_skipped_reason)
    lines += _change_notices(accepted, previous or {}, cleared or [], rejected)
    if added_blocks:
        lines += [f"본문에 {len(added_blocks)}개 문단을 추가했습니다.", ""]
    if dropped_blocks:
        lines += [f"본문에서 {len(dropped_blocks)}개 문단을 뺐습니다.", ""]

    table, missing = _status_table(specs, values)
    lines += table
    lines += _block_list(blocks)
    lines += _next_step(missing)
    return "\n".join(lines)
