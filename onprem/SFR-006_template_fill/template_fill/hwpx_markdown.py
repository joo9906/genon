"""hwpx 본문을 마크다운으로 뽑는다 — **표시 전용 읽기 경로**.

용도: 채팅 UI 가 "지금 문서가 어떤 모양이고 어디에 무엇이 들어갔는지"를 보여줄 때 쓴다.
브라우저는 hwpx 를 렌더링하지 못하고, 다운로드 전에 사용자가 확인할 방법이 필요하다.

이 모듈은 문서를 **읽기만 한다**. 채우기(`hwpx_fields.fill_template`)와 서식
적용(`hwpx_style.apply_styles`)의 어떤 판정에도 개입하지 않는다. 미리보기는
채운 결과 바이트를 그대로 다시 읽어 만들므로(그래서 명세 표기 제거·값 반영이
화면에 그대로 드러난다), 화면과 다운로드 파일이 어긋날 수 없다.

전처리기 규약과 맞춘 점 (CLAUDE.md 전처리기 입력 원칙):
- 표는 **마크다운 표**로 낸다. 첨부형 전처리기가 docx/pdf/hwpx 를 넣을 때 쓰는
  형식과 같아서, LLM 컨텍스트로 재사용해도 표 구조 인식 규칙이 하나로 유지된다.

hwpx 표 구조 (domain — 매번 다시 알아내지 말 것):
    hp:p → hp:run → hp:tbl → hp:tr → hp:tc → hp:subList → hp:p → hp:run → hp:t
    <hp:tc><hp:cellAddr colAddr="1" rowAddr="0"/><hp:cellSpan colSpan="2" rowSpan="1"/>
- 셀 좌표는 `cellAddr` 이 정본이다. 병합 셀은 **앵커 셀 하나만 존재**하고 이어지는
  자리에는 hp:tc 가 아예 없다 → 좌표를 무시하고 순서대로 채우면 열이 밀린다.
- 마크다운에는 rowspan 이 없다. 세로 병합은 앵커 행에만 값을 두고 이어지는 행은
  빈 칸으로 남긴다 (구조를 지어내지 않는다).

경계 (알고 쓰는 한계 — 침묵 처리하지 않기 위해 명시):
- 머리말/꼬리말(hp:header/footer)·각주는 본문 흐름이 아니라 제외한다.
- 셀 안에 또 표가 있으면 그 표의 문단 텍스트를 셀 안에 이어 붙인다(구조는 평탄화).
- 상한(`max_chars`)에 걸려 자른 경우 `MarkdownResult.truncated` 로 알린다.
"""

from dataclasses import dataclass

from .hwpx_fields import (
    HP_NS,
    fill_template,
    iter_section_xml,
    nearest_para,
    normalize_text,
    own_nodes,
    parse_xml,
)

_PARA = f"{{{HP_NS}}}p"
_TEXT = f"{{{HP_NS}}}t"
_TBL = f"{{{HP_NS}}}tbl"
_TR = f"{{{HP_NS}}}tr"
_TC = f"{{{HP_NS}}}tc"
_CELL_ADDR = f"{{{HP_NS}}}cellAddr"
_CELL_SPAN = f"{{{HP_NS}}}cellSpan"

# 셀 안 줄바꿈은 마크다운 표를 깨뜨린다 — 표에서만 <br> 로 바꾼다
_CELL_LINE_BREAK = "<br>"
_TRUNCATED_MARK = "\n\n…(이후 생략)"


@dataclass(frozen=True)
class MarkdownResult:
    """변환 결과 + 무엇을 얼마나 읽었는지.

    truncated 를 함께 돌려주는 이유: 잘린 미리보기를 문서 전체로 오인하면
    사용자가 빠진 항목을 못 보고 다운로드한다 (미측정을 통과로 보이지 않게 하는
    저장소 원칙과 같은 계열).
    """

    markdown: str
    paragraph_count: int
    table_count: int
    truncated: bool


def _children(elem, tag: str) -> list:
    """직접 자식만 (중첩 표의 tr/tc 가 섞이지 않게)."""
    return [child for child in elem if child.tag == tag]


def _para_text(para) -> str:
    """이 문단이 **직접** 가진 텍스트. 표 안 하위 문단 텍스트는 섞지 않는다."""
    return normalize_text(
        "".join((node.text or "") for node in own_nodes(para, _TEXT))
    ).strip()


def _cell_text(tc) -> str:
    """셀 텍스트. 여러 문단은 <br> 로 잇고, 파이프는 이스케이프한다.

    중첩 표의 문단까지 문서 순서로 포함한다 — 구조는 평탄화되지만 내용은 잃지 않는다.
    """
    # 빈 문단은 버린다 (셀 안 빈 줄이 <br> 로 남아 표가 지저분해지지 않게)
    parts = [text for para in tc.iter(_PARA) if (text := _para_text(para))]
    return _CELL_LINE_BREAK.join(parts).replace("|", "\\|")


def _render_table(tbl) -> list:
    """hp:tbl → 마크다운 표 줄 목록. 셀 좌표(cellAddr)를 정본으로 격자를 만든다."""
    cells: dict = {}
    occupied: set = set()
    height = 0
    width = 0

    for row_index, tr in enumerate(_children(tbl, _TR)):
        cursor = 0
        for tc in _children(tr, _TC):
            addr = tc.find(_CELL_ADDR)
            span = tc.find(_CELL_SPAN)
            col_span = _int_attr(span, "colSpan", 1)
            row_span = _int_attr(span, "rowSpan", 1)
            if addr is not None:
                row = _int_attr(addr, "rowAddr", row_index)
                col = _int_attr(addr, "colAddr", cursor)
            else:
                # 좌표가 없는 문서(합성 픽스처 등) — 앞 셀 다음 빈 자리를 쓴다
                row, col = row_index, cursor
                while (row, col) in occupied:
                    col += 1
            cells[(row, col)] = _cell_text(tc)
            for d_row in range(row_span):
                for d_col in range(col_span):
                    occupied.add((row + d_row, col + d_col))
            cursor = col + col_span
            height = max(height, row + row_span)
            width = max(width, col + col_span)

    if not width or not height:
        return []

    lines = []
    for row in range(height):
        values = [cells.get((row, col), "") for col in range(width)]
        lines.append("| " + " | ".join(v or " " for v in values) + " |")
        if row == 0:
            # 마크다운 표는 구분선이 필수다. hwpx 는 머리행을 표시하지 않으므로
            # 첫 행을 머리행으로 본다 (구조를 지어내지 않는 최소 가정).
            lines.append("|" + "---|" * width)
    return lines


def _int_attr(elem, name: str, default: int) -> int:
    if elem is None:
        return default
    try:
        return int((elem.get(name) or "").strip())
    except ValueError:
        return default


def render_markdown(hwpx_bytes: bytes, max_chars: int | None = None) -> MarkdownResult:
    """hwpx 본문을 마크다운 문자열로 변환한다.

    Args:
        hwpx_bytes: 원본 또는 **채운 결과** hwpx 바이트.
        max_chars: 출력 상한. 넘으면 자르고 truncated=True 로 알린다.

    Raises:
        TemplateError: ZIP/XML 손상 (hwpx_fields 와 같은 예외·같은 안내문).
    """
    blocks: list = []
    paragraph_count = 0
    table_count = 0

    for _, xml_bytes in iter_section_xml(hwpx_bytes):
        root = parse_xml(xml_bytes)
        # lxml 프록시는 참조가 끊기면 회수되고 id 가 재사용된다 — 순회 결과를 리스트로
        # 붙들어 둔 뒤에 id 로 묶는다 (hwpx_fields._ordered_occurrences 와 같은 이유).
        paragraphs = list(root.iter(_PARA))
        tables = list(root.iter(_TBL))
        owned_tables: dict = {}
        for tbl in tables:
            owner = nearest_para(tbl)
            if owner is not None:
                owned_tables.setdefault(id(owner), []).append(tbl)

        for para in paragraphs:
            # 표 셀·머리말·각주의 문단은 상위 hp:p 안에 중첩된다. 표는 소유 문단에서
            # 따로 렌더링하고, 머리말/각주는 본문 흐름이 아니라 제외한다.
            if nearest_para(para) is not None:
                continue
            text = _para_text(para)
            if text:
                paragraph_count += 1
                blocks.append(text)
            for tbl in owned_tables.get(id(para), ()):
                lines = _render_table(tbl)
                if lines:
                    table_count += 1
                    blocks.append("\n".join(lines))

    markdown = "\n\n".join(blocks)
    truncated = False
    if max_chars is not None and len(markdown) > max_chars:
        markdown = markdown[:max_chars].rstrip() + _TRUNCATED_MARK
        truncated = True
    return MarkdownResult(
        markdown=markdown,
        paragraph_count=paragraph_count,
        table_count=table_count,
        truncated=truncated,
    )


def render_filled(
    template_bytes: bytes, values: dict, *, include_slots: bool, max_chars: int | None
) -> MarkdownResult:
    """지금 값으로 **채운 결과**를 마크다운으로 만든다 (미리보기의 유일한 경로).

    대화(area 02)와 코드 서빙(`GET /preview`, 값 수정 응답)이 모두 이 함수를 쓴다.
    각자 `fill_template` → `render_markdown` 을 이어 붙이면 한쪽만 단계가 늘어났을 때
    채팅 창과 미리보기가 같은 세션을 다르게 그린다.

    Raises:
        TemplateError: ZIP/XML 손상. 오류를 어떻게 노출할지는 호출부가 정한다
            (대화는 미리보기 없이 진행, API 는 입력 오류로 올린다).
    """
    # **서식 단계를 일부러 건너뛴다.** 마크다운에는 글꼴·크기를 담을 자리가 없다.
    # 이게 화면과 파일을 어긋나게 하지 않는 근거는 `hwpx_style` 의 계약이다 —
    # 서식 단계는 텍스트를 바꾸지 않고(`rewrite_slots` 에 texts=[None…]) run 만 쪼갠다.
    # 그 계약이 깨져 서식 단계가 `{…}` 를 지우기 시작하면 미리보기와 다운로드가
    # 갈린다 (`StyleApplyResult` 아래 주석이 그걸 금지한다).
    filled = fill_template(template_bytes, values, include_slots=include_slots)
    return render_markdown(filled.hwpx_bytes, max_chars=max_chars)
