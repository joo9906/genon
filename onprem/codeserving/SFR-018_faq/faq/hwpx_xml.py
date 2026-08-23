"""hwpx XML 이름과 **소유 판정** — 입력 파서(`hwpx_text`)가 쓴다.

## 왜 따로 두는가

"이 노드는 **누구 것인가**"는 hwpx 의 함정 하나를 흡수하는 규칙이다: 표는
`hp:p → hp:run → hp:tbl → hp:tc → hp:subList → hp:p` 로 **문단 안에 문단이 중첩**
되므로, `para.iter()` 결과를 그대로 쓰면 표 전체가 한 문단으로 붙는다. 그러면
마크다운이 통째로 깨지고 표 안 수치가 무엇의 값인지 사라진다.

**전에는 쓰기 경로도 이 판정을 공유했다.** FAQ 를 hwpx 로 내려주던 시절
(`exporters/hwpx_export.py`, 2026-08-12 삭제) 값을 엉뚱한 셀에 넣지 않으려면 같은 규칙이
필요했다. 지금 호출자는 읽기 하나뿐이지만 파일을 합치지 않는다 — 판정 규칙과 그 규칙을
쓰는 용도를 갈라 둔 것이 이 파일의 목적이고, hwpx 함정을 설명하는 자리도 여기다.

## 상자 — 글자를 담는 곳은 표 셀만이 아니다 (2026-08-23)

글상자·도형(`hp:drawText`), 캡션, 각주·미주, 머리말·꼬리말, 숨은 설명, 메모가 전부
자기 안에 `hp:subList > hp:p` 를 갖는다. 예전에는 셀(`hp:tc`)만 상자로 보고 나머지
중첩 문단을 "본문 흐름이 아니다" 로 **통째로 버렸는데**, 버린 것이 곧 문서에 보이는
글자라 FAQ 근거 대조에서는 **그 문장이 원문에 없는 것으로 취급**됐다 —
`ungrounded` 로 기각되는 것과 달리 기각 건수에도 안 잡힌다.

**상자인지는 이름 목록이 아니라 생김새(`hp:subList` 를 직접 자식으로 두는가)로
판정한다** — 목록으로 두면 거기 안 적힌 상자가 예전처럼 조용히 버려지고, 빠뜨렸다는
사실을 아무도 모른 채로 남는다.

**배포 단위 밖과는 여전히 공유하지 않는다.** SFR-006 `hwpx_markdown.py`,
SFR-018_translation `hwpx_text.py`, MCP `genon_hwpx_text.py`, 전처리기
`hwpx_preprocessor.py` 에 같은 규칙의 사본이 있고 그건 의도된 것이다 (파서를 공유하면
파서 버그를 함께 놓친다). 갈렸는지는 `onprem/test/check_table_grid.py` 가 **동작으로**
대조한다. 여기서 없애는 것은 **한 배포 단위 안의** 중복뿐이다.
"""

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"

PARA = f"{{{HP_NS}}}p"
TEXT = f"{{{HP_NS}}}t"
TBL = f"{{{HP_NS}}}tbl"
TR = f"{{{HP_NS}}}tr"
TC = f"{{{HP_NS}}}tc"
CELL_ADDR = f"{{{HP_NS}}}cellAddr"
CELL_SPAN = f"{{{HP_NS}}}cellSpan"
POS = f"{{{HP_NS}}}pos"

# 문단을 담는 상자들. **이 목록은 판정에 쓰지 않는다** — `is_box` 가 모양으로 본다.
DRAW_TEXT = f"{{{HP_NS}}}drawText"
CAPTION = f"{{{HP_NS}}}caption"
FOOT_NOTE = f"{{{HP_NS}}}footNote"
END_NOTE = f"{{{HP_NS}}}endNote"
PAGE_HEADER = f"{{{HP_NS}}}header"
PAGE_FOOTER = f"{{{HP_NS}}}footer"
HIDDEN_COMMENT = f"{{{HP_NS}}}hiddenComment"
MEMO = f"{{{HP_NS}}}memo"

SUBLIST = f"{{{HP_NS}}}subList"

# 수식은 `hp:equation > hp:script` 안에 원본 문자열로 들어 있다. `hp:t` 가 아니라서
# 예전 파서에는 아예 안 잡혔다 — 수식 하나가 통째로 빠지면 그 문단의 뜻이 바뀐다.
EQUATION = f"{{{HP_NS}}}equation"
SCRIPT = f"{{{HP_NS}}}script"

# 어디서 온 글인지 헷갈리지 않게 붙이는 이름표. **글상자·캡션은 라벨이 없다** —
# 본문과 같은 글이고, 라벨은 원문에 없던 글자를 더하는 것이라 그 글이 본문 흐름 밖에
# 있을 때만 붙인다.
BOX_LABELS = {
    DRAW_TEXT: "",
    CAPTION: "",
    FOOT_NOTE: "[각주] ",
    END_NOTE: "[미주] ",
    PAGE_HEADER: "[머리말] ",
    PAGE_FOOTER: "[꼬리말] ",
    HIDDEN_COMMENT: "[숨은 설명] ",
    MEMO: "[메모] ",
}

# `hp:t` 는 **혼합 내용**이다. 탭·강제 줄바꿈·묶음 빈칸 같은 조판 문자가 자식 원소로
# 들어가고, **그 뒤에 오는 글자는 자식의 `tail` 에 담긴다.**
INLINE_CHARS = {
    f"{{{HP_NS}}}tab": "\t",
    f"{{{HP_NS}}}lineBreak": "\n",
    f"{{{HP_NS}}}hyphen": "-",
    f"{{{HP_NS}}}nbSpace": " ",
    f"{{{HP_NS}}}fwSpace": "　",
}


def nearest_para(node):
    """이 노드를 직접 담고 있는 문단. 없으면 None.

    표 안(`hp:tc → hp:subList → hp:p`)까지 조상을 따라 올라간다.
    """
    parent = node.getparent()
    while parent is not None:
        if parent.tag == PARA:
            return parent
        parent = parent.getparent()
    return None


def is_box(elem) -> bool:
    """문단을 담는 상자인가 — `hp:subList` 를 직접 자식으로 두는가로 본다.

    표 셀(`hp:tc`)·글상자(`hp:drawText`)·캡션·각주·머리말이 전부 이 모양이다.
    **이름 목록이 아니라 모양으로 보는 이유**는 이 파일 머리말에 적었다.
    """
    return elem.find(SUBLIST) is not None


def owning_box(node):
    """이 노드를 담고 있는 **가장 가까운 상자**(표 셀 포함). 중첩을 가르는 기준이다.

    예전에는 셀(`hp:tc`)만 봤다. 그러면 셀 안 글상자·캡션·각주의 문단이 "이 셀 것이
    아니다" 로 떨어져 **어디에서도 안 나온다** — 셀 렌더링은 자기 것이 아니라고 건너뛰고,
    본문 렌더링은 중첩 문단이라고 건너뛴다.
    """
    parent = node.getparent()
    while parent is not None:
        if is_box(parent):
            return parent
        parent = parent.getparent()
    return None


def owning_object(node):
    """이 노드를 담고 있는 가장 가까운 **개체**(표·상자·셀). 없으면 `None`.

    `owned_objects` 가 "한 겹만" 고를 때 쓴다 — 표에 달린 캡션은 표가 낼 몫이지
    문단이 따로 낼 몫이 아니다(따로 내면 캡션이 표에서 떨어져 나온다).
    """
    parent = node.getparent()
    while parent is not None:
        if parent.tag == TBL or is_box(parent):
            return parent
        parent = parent.getparent()
    return None


def paras_of(box) -> list:
    """이 상자가 **직접** 가진 문단들. 안쪽 표·상자의 문단은 뺀다."""
    return [para for para in box.iter(PARA) if owning_box(para) is box]


def owned_objects(para) -> list:
    """이 문단에 매달린 개체들 — 표와 상자. **문서 순서대로, 한 겹만.**

    안쪽 것을 함께 고르면 같은 글자가 두 번 나온다(표 → 그 표의 캡션, 도형 → 그 안의
    글상자). "한 겹" 의 기준은 **이 문단과 같은 상자에 들어 있는가** 다 — 문단이 본문에
    있으면 개체도 본문에 있어야 하고, 문단이 글상자 안이면 개체도 그 글상자 것이라야
    한다. `None` 고정으로 두면 글상자 안 표가 통째로 빠진다.
    """
    box = owning_box(para)
    return [
        node
        for node in para.iter()
        if (node.tag == TBL or is_box(node))
        and nearest_para(node) is para
        and owning_object(node) is box
    ]


def captions_of(obj) -> list:
    """이 개체에 **직접** 달린 캡션(표제)."""
    return [node for node in obj.iter(CAPTION) if owning_object(node) is obj]
