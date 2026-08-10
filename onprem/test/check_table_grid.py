"""표 격자 규칙 3벌 대조 점검 — 사본이 갈렸는지 **동작으로** 확인한다.

`python onprem/test/check_table_grid.py`

## 왜 여기 있나

hwpx 표를 마크다운 격자로 펴는 규칙(`cellAddr` 좌표, 병합 앵커, 셀 안 파이프 이스케이프,
문단 잇기)이 **세 배포 단위에 각각 구현돼 있다.** 배포 단위 간 import 가 금지돼 있어서다.

| 단위 | 파일 |
|---|---|
| SFR-006 | `template_fill/hwpx_markdown.py` |
| SFR-018 번역 | `translation_pipeline/office/hwpx_text.py` |
| SFR-018 FAQ | `faq/hwpx_text.py` |

세 파일 모두 머리말에 "표 격자 규칙을 고칠 때는 셋을 함께 본다" 고 적어 두었다. 그런데
그건 사람 사이의 약속일 뿐이고, **같은 구조에서 톤 프리셋은 실제로 갈렸다**(006 `friendly`
에서 한 문장 누락 — 그래서 `check_tone_policy.py` 가 생겼다). 이 스크립트는 표 격자에
같은 그물을 친다.

## 무엇을 보는가

텍스트 diff 가 아니라 **출력 대조**다. 주석·docstring·헬퍼 배치는 단위마다 다른 것이
정상이고(실제로 FAQ 는 `hwpx_xml.py` 로 상수를 따로 뺐다), 갈리면 안 되는 것은 같은
문서를 넣었을 때 나오는 격자다. 그래서 픽스처 하나를 세 구현에 먹이고 결과를 맞춰 본다.

픽스처는 **일부러 고약하게** 만든다. 안전한 표는 어떤 구현으로도 통과해서 검사가 무의미해진다.

1. **세로 병합**(`rowSpan=2`) — 앵커 셀만 존재한다. 순서대로 채우면 아래 행의 열이 밀린다
2. **가로 병합**(`colSpan=2`)
3. **셀 안 파이프**(`a|b`) — escape 하지 않으면 그 행부터 열이 밀린다
4. **빈 셀** — 마크다운 표는 빈 칸도 자리를 지켜야 한다
5. **중첩 표** — `hp:p` 안에 `hp:p` 가 들어가는 구조라 `iter()` 를 그대로 쓰면 붙어 버린다
6. **한 셀 안 여러 문단** — `<br>` 로 이어야 한다
7. **좌표 없는 표** — `cellAddr` 이 없는 문서의 폴백 경로

python-hwpx 나 실물 hwpx 파일이 필요 없다. 섹션 XML 을 직접 써서 zip 으로 묶는다 —
세 구현 모두 `Contents/sectionN.xml` 만 읽기 때문이다.
"""

import io
import os
import re
import sys
import zipfile

# 열 경계는 **이스케이프되지 않은** 파이프만이다. `a\|b` 의 파이프를 세면 그 행만 열이
# 하나 많아 보여 정상 표를 어긋났다고 잡는다 (`markdown_guard` 와 같은 정의).
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")

_ONPREM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _unit in ("SFR-006_template_fill", "SFR-018_translation", "SFR-018_faq"):
    sys.path.insert(0, os.path.join(_ONPREM, _unit))

from faq.hwpx_text import to_markdown as faq_to_markdown  # noqa: E402
from template_fill.hwpx_markdown import render_markdown  # noqa: E402
from translation_pipeline.office.hwpx_text import to_markdown as trans_to_markdown  # noqa: E402

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"


def _cell(row: int, col: int, text: str, *, row_span: int = 1, col_span: int = 1, extra: str = "") -> str:
    """셀 하나. `text` 가 빈 문자열이면 문단은 두되 글자를 넣지 않는다."""
    paragraphs = extra or f'<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>'
    return (
        f'<hp:tc><hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
        f'<hp:cellSpan colSpan="{col_span}" rowSpan="{row_span}"/>'
        f"<hp:subList>{paragraphs}</hp:subList></hp:tc>"
    )


def _nested_table() -> str:
    """셀 안에 든 표 — 문단 구조가 한 단계 더 깊어진다."""
    inner = (
        "<hp:tbl><hp:tr>"
        + _cell(0, 0, "중첩")
        + _cell(0, 1, "셀")
        + "</hp:tr></hp:tbl>"
    )
    return f'<hp:p><hp:run><hp:t>안내</hp:t></hp:run><hp:run>{inner}</hp:run></hp:p>'


def build_fixture() -> bytes:
    """위험 요소 일곱 개를 한 문서에 담은 최소 hwpx."""
    # 표 1 — 병합·파이프·빈 칸·중첩·다문단
    rows = [
        "<hp:tr>"
        + _cell(0, 0, "항목")
        + _cell(0, 1, "2025", col_span=2)   # 가로 병합
        + "</hp:tr>",
        "<hp:tr>"
        + _cell(1, 0, "매출", row_span=2)   # 세로 병합 — 앵커만 존재
        + _cell(1, 1, "1,000")
        + _cell(1, 2, "", extra=_nested_table())  # 중첩 표
        + "</hp:tr>",
        "<hp:tr>"
        + _cell(2, 1, "a|b")                # 파이프
        + _cell(2, 2, "")                   # 빈 셀
        + "</hp:tr>",
    ]
    table_one = "<hp:tbl>" + "".join(rows) + "</hp:tbl>"

    # 표 2 — cellAddr 이 없는 문서 (폴백 경로)
    def bare(text: str) -> str:
        return f"<hp:tc><hp:subList><hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p></hp:subList></hp:tc>"

    table_two = (
        "<hp:tbl>"
        f"<hp:tr>{bare('좌')}{bare('우')}</hp:tr>"
        f"<hp:tr>{bare('하좌')}{bare('하우')}</hp:tr>"
        "</hp:tbl>"
    )

    # 다문단 셀 — <br> 로 이어져야 한다
    multi = (
        "<hp:tbl><hp:tr>"
        + _cell(
            0,
            0,
            "",
            extra="<hp:p><hp:run><hp:t>첫 줄</hp:t></hp:run></hp:p>"
            "<hp:p><hp:run><hp:t>둘째 줄</hp:t></hp:run></hp:p>",
        )
        + _cell(0, 1, "옆")
        + "</hp:tr></hp:tbl>"
    )

    section = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">'
        "<hp:p><hp:run><hp:secPr/></hp:run><hp:run><hp:t>보고서</hp:t></hp:run></hp:p>"
        f"<hp:p><hp:run>{table_one}</hp:run></hp:p>"
        "<hp:p><hp:run><hp:t>좌표 없는 표</hp:t></hp:run></hp:p>"
        f"<hp:p><hp:run>{table_two}</hp:run></hp:p>"
        f"<hp:p><hp:run>{multi}</hp:run></hp:p>"
        "</hs:sec>"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("Contents/section0.xml", section)
    return buffer.getvalue()


def _render_all(data: bytes) -> dict:
    """세 구현의 출력. 값 접근 경로가 달라 여기서 맞춰 준다."""
    return {
        "SFR-006": render_markdown(data).markdown,
        "SFR-018 번역": trans_to_markdown(data).markdown,
        "SFR-018 FAQ": faq_to_markdown(data).markdown,
    }


def _table_blocks(markdown: str) -> list:
    """마크다운에서 표 블록(연속된 `|` 줄)만 뽑는다.

    문서 안 표끼리는 열 수가 다른 것이 정상이므로, 열 수 일관성은 **한 표 안에서만**
    따져야 한다. 구분선(`|---|`)은 열 수 세기에서 제외한다 — 셀이 아니다.
    """
    blocks: list = []
    current: list = []
    for line in markdown.splitlines():
        if line.startswith("|"):
            if not line.startswith("|---"):
                current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _columns(block: list) -> set:
    """표 블록의 행별 열 수 집합. 원소가 하나면 격자가 반듯한 것이다."""
    return {len(_UNESCAPED_PIPE_RE.findall(line)) - 1 for line in block}


class Report:
    def __init__(self) -> None:
        self.failures: list = []
        self.checks = 0

    def expect(self, condition: bool, label: str, detail: str = "") -> None:
        self.checks += 1
        if condition:
            print(f"[OK  ] {label}")
            return
        self.failures.append(label)
        print(f"[FAIL] {label}  {detail}")


def main() -> int:
    rep = Report()
    data = build_fixture()
    rendered = _render_all(data)
    names = list(rendered)
    baseline = rendered[names[0]]

    # 1) 세 구현이 같은 격자를 내는가 — 이 스크립트의 본론
    for name in names[1:]:
        same = rendered[name].strip() == baseline.strip()
        rep.expect(
            same,
            f"{names[0]} ↔ {name} 출력이 같다",
            "" if same else f"\n--- {names[0]} ---\n{baseline}\n--- {name} ---\n{rendered[name]}",
        )

    # 2) 격자 자체가 맞는가 — 셋이 똑같이 틀렸을 수도 있다
    blocks = _table_blocks(baseline)
    rep.expect(len(blocks) == 3, "표 세 개가 모두 렌더된다", f"blocks={len(blocks)}")
    rep.expect(
        "\\|" in baseline,
        "셀 안 파이프가 이스케이프된다 (안 하면 그 행부터 열이 밀린다)",
        baseline,
    )
    rep.expect(
        "<br>" in baseline,
        "한 셀의 여러 문단이 <br> 로 이어진다",
        baseline,
    )
    rep.expect(
        "중첩" in baseline and "셀" in baseline,
        "중첩 표의 글자가 사라지지 않는다",
        baseline,
    )
    rep.expect(
        "하좌" in baseline and "하우" in baseline,
        "cellAddr 이 없는 표도 격자로 펴진다 (폴백 경로)",
        baseline,
    )
    # 병합 앵커를 순서대로 채우면 아래 행의 열이 밀린다 — **표 안에서** 행마다 열 수가
    # 같아야 한다. 표끼리는 열 수가 달라도 정상이라 블록 단위로 본다.
    ragged = [
        (index, sorted(_columns(block)))
        for index, block in enumerate(blocks)
        if len(_columns(block)) != 1
    ]
    rep.expect(
        not ragged,
        "병합이 있어도 표 안 모든 행의 열 수가 같다",
        f"어긋난 표={ragged}\n{baseline}",
    )
    # 세로 병합의 아래 칸은 **빈 칸으로 자리를 지킨다** (앵커 텍스트를 복제하지 않는다)
    first = blocks[0] if blocks else []
    rep.expect(
        len(first) == 3 and first[-1].startswith("|   |"),
        "세로 병합 아래 행은 빈 칸으로 자리를 지킨다 (앵커 텍스트를 복제하지 않는다)",
        f"first_table={first}",
    )

    print()
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        print("\n표 격자 규칙 사본이 갈렸다. 세 파일을 함께 고쳐야 한다:")
        print("  SFR-006_template_fill/template_fill/hwpx_markdown.py")
        print("  SFR-018_translation/translation_pipeline/office/hwpx_text.py")
        print("  SFR-018_faq/faq/hwpx_text.py")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
