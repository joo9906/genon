"""FAQ → 사용자 노출 마크다운. **화면과 내려받는 파일(.md)이 같은 형식을 쓴다.**

요구사항 §2 가 "마크다운 형식으로 UI 에서 보여줘도 상관 없으나, 생성된 FAQ 는 반드시
문서의 어떤 내용에서 추출된 것인지 명시" 를 요구한다. 그래서 근거를 **접어두지 않고
항목마다** 인용구(`> 근거:`)로 붙인다.

조립을 한 곳에 모아두는 이유: 채팅(02)과 코드 서빙(03)이 같은 항목을 쓴다. 각자
조립하면 화면과 파일이 어긋난다 (SFR-006 미리보기가 채우기와 같은 경로를 타는 것과
같은 이유).

## 파일은 화면 마크다운 + 제목 한 줄이다

파일은 화면과 달리 "무슨 문서에서 뽑은 FAQ 인지" 를 스스로 말해야 한다(파일명은
사용자가 바꾼다). 그래서 제목이 있으면 맨 위에 `# 제목` 을 붙인다. 그 밖의 형식은
`_render` 하나가 정한다 — 화면과 파일이 다른 함수를 쓰면 한쪽만 고쳐진다.

안내문(`build_notice`)도 여기서 만든다. 개수가 깎였거나 근거 미달로 기각된 항목이
있으면 **결과 위에 먼저 알린다** — 사용자가 요청한 개수와 받은 개수가 다른 이유를
스스로 추측하게 두지 않는다.
"""


def build_notice(result) -> str:
    """결과 위에 붙일 안내문. 알릴 것이 없으면 빈 문자열."""
    lines = []
    if result.count_clamped:
        lines.append(
            f"※ 한 문서에서 만들 수 있는 FAQ 는 최대 {result.max_count}개입니다. "
            f"{result.max_count}개로 생성했습니다."
        )
    if result.coverage_capped:
        # 호출 수 상한에 걸려 일부 구간만 태웠다. 조용히 넘기면 사용자는 문서 전체에서
        # 뽑은 결과로 읽는다 — 안 나온 내용이 문서에 없는 것으로 보인다.
        lines.append(
            f"※ 문서가 길어 전체 {result.source_chunks}개 구간 중 "
            f"{result.chunks_planned}개 구간에서 나눠 만들었습니다. "
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

    줄바꿈이 있으면 인용구(`>`)가 끊겨 근거 뒷부분이 본문으로 새어 보인다.
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


def rows_to_markdown(rows: list, *, notice: str = "", title: str = "") -> str:
    """저장된 평면 형태를 **내려받을 md 본문**으로 만든다.

    파일을 만드는 두 경로(생성 직후 업로드·`POST /download`)가 쓰는 유일한 조립 함수다.
    항목 형식은 화면과 같고(`_render`), 제목이 있으면 맨 위에 `# 제목` 을 붙인다.
    줄바꿈은 LF 로 만든다. CRLF 변환은 `txt_output.to_bytes` 한 곳에서만 한다 —
    두 곳에서 하면 `\\r\\r\\n` 이 섞인다.
    """
    head = f"# {title.strip()}\n\n" if (title or "").strip() else ""
    return head + _render(_as_tuples(rows), notice) + "\n"


def to_export_rows(items: list) -> list:
    """세션 저장·다운로드가 쓰는 평면 형태.

    `sources` 키 이름은 그대로 둔다 — 이미 저장된 세션이 이 이름으로 들어 있고,
    이름을 바꾸면 배포 시점에 진행 중인 대화의 다운로드가 빈 근거로 나간다
    (`session_store._STATE_VERSION` 을 올려 버리는 편보다 낫다).
    """
    return [
        {
            "question": item.question,
            "answer": item.answer,
            "sources": item.evidence,
        }
        for item in items
    ]
