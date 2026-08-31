"""FAQ → 사용자 노출 문자열. **화면용 마크다운과 파일용 평문, 두 가지를 만든다.**

요구사항 §2 가 "마크다운 형식으로 UI 에서 보여줘도 상관 없으나, 생성된 FAQ 는 반드시
문서의 어떤 내용에서 추출된 것인지 명시" 를 요구한다. 그래서 근거를 **접어두지 않고
항목마다** 붙인다 — 화면은 인용구(`>`), 파일은 `[근거]` 표지다.

조립을 한 곳에 모아두는 이유: 채팅(02)과 코드 서빙(03)이 같은 항목을 쓴다. 각자
조립하면 화면과 파일이 어긋난다 (SFR-006 미리보기가 채우기와 같은 경로를 타는 것과
같은 이유).

## 파일은 마크다운이 아니라 평문이다 (2026-08-12)

내려받는 형식이 txt 하나가 되면서(hwpx/pdf/xlsx 는 걷어냈다) 파일은 **메모장에서 그대로
읽는 것**이 됐다. `**Q1.**`·`> 근거:` 를 그대로 넣으면 메모장에서는 별표와 꺾쇠가 글자로
보인다. 그래서 화면 마크다운과 파일 평문을 **다른 함수**로 낸다:

| | 화면(채팅·UI) | 파일(.txt) |
|---|---|---|
| 항목 머리 | `**Q1. 질문**` | `Q1. 질문` |
| 근거 | `> 근거: …` | `[근거] …` |
| 항목 사이 | 빈 줄 | 빈 줄 + 구분선 |

**두 함수가 같은 항목 목록을 받는다**는 것이 계약이다 — 내용이 갈리지 않게 근거 평탄화
(`_flat`)와 항목 순서 부여는 공유한다.

안내문(`build_notice`)도 여기서 만든다. 개수가 깎였거나 근거 미달로 기각된 항목이
있으면 **결과 위에 먼저 알린다** — 사용자가 요청한 개수와 받은 개수가 다른 이유를
스스로 추측하게 두지 않는다. 안내문은 기호를 쓰지 않아 화면·파일에 같은 문장이 나간다.
"""

# 파일에서 항목을 가르는 선. 메모장에는 수평선 문법이 없으므로 문자로 긋는다.
_ITEM_SEPARATOR = "-" * 40


def build_notice(result) -> str:
    """결과 위에 붙일 안내문. 알릴 것이 없으면 빈 문자열."""
    lines = []
    if result.count_clamped:
        lines.append(
            f"※ 문서 한 구간에서 만들 수 있는 FAQ 는 최대 {result.max_count}개입니다. "
            f"{result.max_count}개로 생성했습니다."
        )
    if result.coverage_capped:
        # 총량 상한에 걸려 일부 구간만 태웠다 (2026-08-31). 조용히 넘기면 사용자는
        # 문서 전체에서 뽑은 결과로 읽는다 — 안 나온 내용이 문서에 없는 것으로 보인다.
        lines.append(
            f"※ 문서가 길어 전체 {result.source_chunks}개 구간 중 "
            f"{result.chunks_planned}개 구간에서 FAQ 를 만들었습니다"
            f"(한 번에 최대 {result.total_cap}개). "
            "나머지 구간 내용은 반영되지 않았습니다."
        )
    if result.source_truncated:
        lines.append("※ 문서가 매우 길어 뒷부분은 FAQ 생성에서 제외했습니다.")

    shortfall = result.requested_count - len(result.items)
    if shortfall > 0:
        reasons = []
        if result.rejected_ungrounded:
            reasons.append(f"근거 확인 실패 {result.rejected_ungrounded}건")
        if result.rejected_duplicate:
            reasons.append(f"중복 {result.rejected_duplicate}건")
        if result.rejected_schema:
            reasons.append(f"형식 오류 {result.rejected_schema}건")
        detail = f" ({', '.join(reasons)})" if reasons else ""
        lines.append(
            f"※ 요청하신 {result.requested_count}개 중 {len(result.items)}개를 만들었습니다{detail}."
        )
    return "\n".join(lines) + "\n\n" if lines else ""


def _flat(text: str) -> str:
    """근거 안의 줄바꿈·연속 공백을 한 칸으로 편다.

    화면에서는 줄바꿈이 인용구(`>`)를 끊고, 파일에서는 `[근거]` 표지와 본문이 갈린다 —
    두 형식 모두 한 줄이어야 하므로 여기서 한 번만 편다.
    """
    return " ".join((text or "").split())


def _render(rows: list, notice: str) -> str:
    """(질문, 답변, 근거) 튜플 목록 → **화면용 마크다운**."""
    blocks = []
    for position, (question, answer, evidence) in enumerate(rows, start=1):
        blocks.append(
            f"**Q{position}. {question}**\n\n"
            f"{answer}\n\n"
            f"> 근거: {_flat(evidence)}"
        )
    return notice + "\n\n".join(blocks)


def _render_plain(rows: list, notice: str, title: str) -> str:
    """(질문, 답변, 근거) 튜플 목록 → **파일용 평문** (메모장에서 그대로 읽는다).

    마크다운 기호를 쓰지 않는다. 제목은 있으면 맨 위에 한 번 적는다 — 파일은 화면과 달리
    "무슨 문서에서 뽑은 FAQ 인지" 를 스스로 말해야 한다(파일명은 사용자가 바꾼다).

    줄바꿈은 LF 로 만든다. CRLF 변환은 `txt_output.to_bytes` 한 곳에서만 한다 —
    두 곳에서 하면 `\\r\\r\\n` 이 섞인다.
    """
    blocks = []
    for position, (question, answer, evidence) in enumerate(rows, start=1):
        blocks.append(
            f"Q{position}. {question}\n\n"
            f"{answer}\n\n"
            f"[근거] {_flat(evidence)}"
        )
    body = f"\n\n{_ITEM_SEPARATOR}\n\n".join(blocks)

    head = ""
    if title.strip():
        head = f"{title.strip()}\n\n"
    return head + notice + body + "\n"


def to_markdown(items: list, *, notice: str = "") -> str:
    """`FaqItem` 목록을 마크다운으로 만든다 (채팅 노출용)."""
    return _render([(i.question, i.answer, i.evidence) for i in items], notice)


def _as_tuples(rows: list) -> list:
    """저장된 평면 형태(`to_export_rows` 산출) → (질문, 답변, 근거) 튜플 목록."""
    return [
        (row.get("question", ""), row.get("answer", ""), row.get("sources", ""))
        for row in rows
        if isinstance(row, dict)
    ]


def rows_to_plain_text(rows: list, *, notice: str = "", title: str = "") -> str:
    """저장된 평면 형태를 **내려받을 txt 본문**으로 만든다 (2026-08-12).

    다운로드 경로가 쓰는 유일한 조립 함수다. 항목 내용 자체는 화면과 같고
    (`_as_tuples` 공유), 다른 것은 기호뿐이다.
    """
    return _render_plain(_as_tuples(rows), notice, title)


def to_export_rows(items: list) -> list:
    """세션 저장·다운로드가 쓰는 평면 형태.

    `sources` 키 이름은 hwpx/pdf/xlsx 내보내기 시절 xlsx 의 '출처' 열에서 왔다.
    그 형식들은 걷어냈지만(2026-08-12) **키 이름은 그대로 둔다** — 이미 저장된 세션이
    이 이름으로 들어 있고, 이름을 바꾸면 배포 시점에 진행 중인 대화의 다운로드가 빈
    근거로 나간다(`session_store._STATE_VERSION` 을 올려 버리는 편보다 낫다).
    """
    return [
        {
            "question": item.question,
            "answer": item.answer,
            "sources": item.evidence,
        }
        for item in items
    ]
