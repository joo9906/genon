"""FAQ → 사용자 노출 마크다운. **화면과 파일이 같은 조립기를 탄다.**

요구사항 §2 가 "마크다운 형식으로 UI 에서 보여줘도 상관 없으나, 생성된 FAQ 는 반드시
문서의 어떤 내용에서 추출된 것인지 명시" 를 요구한다. 그래서 근거를 **접어두지 않고
항목마다** 인용구(`> 근거: …`)로 붙인다.

조립을 한 곳에 모아두는 이유: 채팅(02)과 코드 서빙(03)이 같은 항목을 쓴다. 각자
조립하면 화면과 파일이 어긋난다 (SFR-006 미리보기가 채우기와 같은 경로를 타는 것과
같은 이유).

## 파일은 화면 마크다운에 제목만 얹는다

내려받는 형식은 md 하나라 파일도 **화면과 같은 마크다운**이다. 다른 점은 맨 위의
`# 제목` 한 줄뿐이다 — 파일은 화면과 달리 "무슨 문서에서 뽑은 FAQ 인지" 를 스스로
말해야 한다(파일명은 사용자가 바꾼다).

안내문(`build_notice`)도 여기서 만든다. 개수가 깎였거나 근거 미달로 기각된 항목이
있으면 **결과 위에 먼저 알린다** — 사용자가 요청한 개수와 받은 개수가 다른 이유를
스스로 추측하게 두지 않는다.
"""

from faq.md_output import with_disclaimer


def build_notice(result) -> str:
    """결과 위에 붙일 안내문. 알릴 것이 없으면 빈 문자열."""
    lines = []
    if result.count_clamped:
        lines.append(
            f"※ 한 문서에서 만들 수 있는 FAQ 는 최대 {result.max_count}개입니다. "
            f"{result.max_count}개로 생성했습니다."
        )

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

    줄바꿈이 인용구(`>`)를 끊으므로 근거는 한 줄이어야 한다 — 여기서 한 번만 편다.
    """
    return " ".join((text or "").split())


def evidence_line(evidence: str, page=None) -> str:
    """근거 인용 한 줄 — 쪽을 알면 `> 근거 (3쪽): …`.

    스트리밍 화면(`main._display_text`)과 파일 · 비스트리밍 화면(`_render`)이 이 함수 하나를
    지난다. 따로 조립하면 같은 항목이 경로에 따라 쪽 표시가 달라진다.
    """
    label = f"근거 ({page}쪽)" if page else "근거"
    return f"> {label}: {_flat(evidence)}"


def _render(rows: list, notice: str) -> str:
    """(질문, 답변, 근거, 쪽) 튜플 목록 → **화면용 마크다운**."""
    blocks = []
    for position, (question, answer, evidence, page) in enumerate(rows, start=1):
        blocks.append(
            f"**Q{position}. {question}**\n\n"
            f"{answer}\n\n"
            f"{evidence_line(evidence, page)}"
        )
    return notice + "\n\n".join(blocks)


def to_markdown(items: list, *, notice: str = "") -> str:
    """`FaqItem` 목록을 마크다운으로 만든다 (채팅 노출용)."""
    return _render([(i.question, i.answer, i.evidence, i.page) for i in items], notice)


def _as_tuples(rows: list) -> list:
    """저장된 평면 형태(`to_export_rows` 산출) → (질문, 답변, 근거, 쪽) 튜플 목록.

    `page` 가 없는 행(쪽 표식이 없던 원문)은 쪽 없이 그린다.
    """
    return [
        (row.get("question", ""), row.get("answer", ""), row.get("sources", ""), row.get("page"))
        for row in rows
        if isinstance(row, dict)
    ]


def rows_to_markdown(rows: list, *, notice: str = "", disclaimer: str = "") -> str:
    """저장된 평면 형태를 **내려받을 md 본문**으로 만든다.

    미리 올리는 파일(`main._store_and_payload`)과 `POST /download` 폴백이 둘 다 이 함수를
    지난다 — 따로 조립하면 받는 경로에 따라 파일이 달라진다. 파일 순서는 열람 안내 → 안내문 →
    문답이고, 열람 안내는 `md_output.to_bytes` 가 붙인다. 글다듬이 · 번역 파일과 같은 모양이다.
    본문에 제목 줄은 넣지 않는다 — 제목은 파일명에만 쓴다.
    안내문 인용 블록은 세 기능이 같은 모양이어야 해서 `md_output.with_disclaimer` 를 쓴다.

    줄바꿈은 LF 로 만든다. CRLF 변환은 `md_output.to_bytes` 한 곳에서만 한다 —
    두 곳에서 하면 `\\r\\r\\n` 이 섞인다.
    """
    return with_disclaimer(_render(_as_tuples(rows), notice), disclaimer) + "\n"


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
            "page": item.page,
        }
        for item in items
    ]
