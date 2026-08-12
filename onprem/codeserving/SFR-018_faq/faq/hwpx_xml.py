"""hwpx XML 이름과 문단 소유 판정 — **입력 파서(`hwpx_text`)가 쓴다.**

## 왜 따로 두는가

"이 문단이 **직접** 가진 텍스트 노드는 무엇인가"는 hwpx 의 함정 하나를 흡수하는
규칙이다: 표는 `hp:p → hp:run → hp:tbl → hp:tc → hp:subList → hp:p` 로 **문단 안에
문단이 중첩**되므로, `para.iter()` 결과를 그대로 쓰면 표 전체가 한 문단으로 붙는다.
그러면 마크다운이 통째로 깨지고 표 안 수치가 무엇의 값인지 사라진다.

**전에는 쓰기 경로도 이 판정을 공유했다.** FAQ 를 hwpx 로 내려주던 시절
(`exporters/hwpx_export.py`, 2026-08-12 삭제) 값을 엉뚱한 셀에 넣지 않으려면 같은 규칙이
필요했다. 지금 호출자는 읽기 하나뿐이지만 파일을 합치지 않는다 — 판정 규칙과 그 규칙을
쓰는 용도를 갈라 둔 것이 이 파일의 목적이고, hwpx 함정을 설명하는 자리도 여기다.

**배포 단위 밖과는 여전히 공유하지 않는다.** SFR-006 `hwpx_markdown.py`,
SFR-018_translation `hwpx_text.py` 에 같은 규칙의 사본이 있고 그건 의도된 것이다
(파서를 공유하면 파서 버그를 함께 놓친다). 여기서 없애는 것은 **한 배포 단위 안의**
중복뿐이다.
"""

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"

PARA = f"{{{HP_NS}}}p"
TEXT = f"{{{HP_NS}}}t"
TBL = f"{{{HP_NS}}}tbl"
TR = f"{{{HP_NS}}}tr"
TC = f"{{{HP_NS}}}tc"
CELL_ADDR = f"{{{HP_NS}}}cellAddr"
CELL_SPAN = f"{{{HP_NS}}}cellSpan"


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


def own_text_nodes(para) -> list:
    """이 문단이 **직접** 가진 `hp:t` 노드만 (중첩 문단의 것은 제외).

    쓰기 경로는 노드가 필요하고(치환 결과를 첫 노드에 몰아 쓴다), 읽기 경로는
    텍스트만 필요하다 — 그래서 노드를 돌려주고 문자열 합성은 호출부에 맡긴다.
    """
    return [node for node in para.iter(TEXT) if nearest_para(node) is para]
