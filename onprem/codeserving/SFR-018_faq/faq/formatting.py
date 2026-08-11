"""FAQ → 사용자 노출 마크다운.

요구사항 §2 가 "마크다운 형식으로 UI 에서 보여줘도 상관 없으나, 생성된 FAQ 는 반드시
문서의 어떤 내용에서 추출된 것인지 명시" 를 요구한다. 그래서 근거를 **접어두지 않고
항목마다 인용구로 붙인다.**

조립을 한 곳에 모아두는 이유: 채팅(02)과 코드 서빙(03)의 마크다운 다운로드가 같은
문자열을 써야 한다. 각자 조립하면 화면과 파일이 어긋난다 (SFR-006 미리보기가
채우기와 같은 경로를 타는 것과 같은 이유).

안내문(`build_notice`)도 여기서 만든다. 개수가 깎였거나 근거 미달로 기각된 항목이
있으면 **결과 위에 먼저 알린다** — 사용자가 요청한 개수와 받은 개수가 다른 이유를
스스로 추측하게 두지 않는다.
"""


def build_notice(result) -> str:
    """결과 위에 붙일 안내문. 알릴 것이 없으면 빈 문자열."""
    lines = []
    if result.count_clamped:
        lines.append(
            f"※ 한 번에 만들 수 있는 FAQ 는 최대 {result.max_count}개입니다. "
            f"{result.max_count}개로 생성했습니다."
        )
    if result.source_truncated:
        lines.append("※ 문서가 길어 앞부분만 사용했습니다. 뒷부분 내용은 반영되지 않았습니다.")

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


def _render(rows: list, notice: str) -> str:
    """(질문, 답변, 근거) 튜플 목록 → 마크다운.

    근거는 인용구(`>`)로 붙인다. 근거 안의 줄바꿈은 인용을 끊으므로 공백으로 편다.
    """
    blocks = []
    for position, (question, answer, evidence) in enumerate(rows, start=1):
        flat_evidence = " ".join((evidence or "").split())
        blocks.append(
            f"**Q{position}. {question}**\n\n"
            f"{answer}\n\n"
            f"> 근거: {flat_evidence}"
        )
    return notice + "\n\n".join(blocks)


def to_markdown(items: list, *, notice: str = "") -> str:
    """`FaqItem` 목록을 마크다운으로 만든다 (채팅 노출용)."""
    return _render([(i.question, i.answer, i.evidence) for i in items], notice)


def rows_to_markdown(rows: list, *, notice: str = "") -> str:
    """저장된 평면 형태(`to_export_rows` 산출)를 마크다운으로 만든다.

    다운로드 경로가 쓴다 — 세션에는 `FaqItem` 이 아니라 이 형태로 저장돼 있다.
    채팅과 파일이 **같은 조립 함수**(`_render`)를 타야 화면과 파일이 어긋나지 않는다.
    """
    return _render(
        [
            (row.get("question", ""), row.get("answer", ""), row.get("sources", ""))
            for row in rows
            if isinstance(row, dict)
        ],
        notice,
    )


def to_export_rows(items: list) -> list:
    """내보내기 모듈이 쓰는 평면 형태.

    `sources` 키를 쓰는 이유: xlsx 내보내기가 '출처' 열로 이미 그 이름을 받는다
    (`exporters/xlsx_export.py`). 이름을 맞춰 두면 변환 계층이 하나 줄어든다.
    """
    return [
        {
            "question": item.question,
            "answer": item.answer,
            "sources": item.evidence,
        }
        for item in items
    ]
