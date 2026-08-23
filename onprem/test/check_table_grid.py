"""hwpx 파싱 코어 사본 대조 — 갈렸는지 **동작으로** 확인한다.

`python onprem/test/check_table_grid.py`

## 왜 여기 있나

hwpx 를 마크다운으로 펴는 규칙이 **네 곳에 각각 구현돼 있다**(전처리기까지 다섯).
배포 단위 간 import 가 금지돼 있어서다. 파일마다 "고칠 때는 함께 본다" 고 적어 뒀지만
그건 사람 사이의 약속일 뿐이고, **같은 구조에서 톤 프리셋은 실제로 갈렸다**
(그래서 `check_tone_policy.py` 가 생겼다).

## 세 층으로 나눠 본다 (2026-08-11 두 층 → 2026-08-23 세 층)

병합·중첩 표는 **마크다운으로 표현할 수 없다.** `rowspan`/`colspan` 문법이 없어 빈 칸이
되고, 중첩 표는 텍스트로 뭉개진다 — 수치는 남는데 **그 수치가 무엇의 값인지가 사라진다.**
그래서 LLM 입력 경로 세 벌은 그런 표를 **HTML** 로 내도록 바꿨다. 006 은 채팅 화면
미리보기용이라 마크다운을 유지한다. 대조 대상이 층마다 다른 이유가 이것이다.

| 층 | 픽스처 | 대조 대상 | 무엇을 보나 |
|---|---|---|---|
| **단순표** | 병합·중첩 없음 | **4벌** (006 포함) | 파이프 이스케이프·다문단 `<br>`·좌표 없는 표 폴백·열 수 일관성. **HTML 로 바꾸지 않는 것**도 계약이다 |
| **병합표** | 병합·중첩 있음 | **3벌** (LLM 입력 경로) | `rowspan`/`colspan` 보존, 중첩 표 보존, 덮인 자리에 `td` 를 내지 않음 |
| **누락 방지** | 탭·상자·수식·자동 번호 | **4벌 + 전처리기** | 표가 아닌 **글자가 남는가**. 형식이 아니라 내용이라 006 도 대상이고, 전처리기가 **정본**이다 |

픽스처는 **일부러 고약하게** 만든다. 안전한 표는 어떤 구현으로도 통과해서 검사가
무의미해진다. 병합표 픽스처에 담은 것:

1. **세로 병합**(`rowSpan=2`) — 앵커 셀만 존재한다. 순서대로 채우면 아래 행의 열이 밀린다
2. **가로 병합**(`colSpan=2`)
3. **셀 안 파이프**(`a|b`)
4. **빈 셀** — 빈 칸도 자리를 지켜야 한다
5. **중첩 표** — `hp:p` 안에 `hp:p` 가 들어가는 구조라 `iter()` 를 그대로 쓰면 붙어 버린다
6. **한 셀 안 여러 문단** — `<br>` 로 이어야 한다
7. **좌표 없는 표** — `cellAddr` 이 없는 문서의 폴백 경로

python-hwpx 나 실물 hwpx 파일이 필요 없다. XML 을 직접 써서 zip 으로 묶는다 —
구현들이 읽는 것은 `Contents/sectionN.xml` 과 (3층에서) `Contents/header.xml` 뿐이다.
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
# 2026-08-11 영역별 재배치: 코드서빙 3벌 + MCP 1벌 = **4벌**이 됐다.
for _unit in (
    os.path.join("codeserving", "SFR-006_template_fill"),
    os.path.join("codeserving", "SFR-018_translation"),
    os.path.join("codeserving", "SFR-018_faq"),
):
    sys.path.insert(0, os.path.join(_ONPREM, _unit))

from faq.hwpx_text import to_markdown as faq_to_markdown  # noqa: E402
from template_fill.hwpx_markdown import render_markdown  # noqa: E402
from translation_pipeline.office.hwpx_text import to_markdown as trans_to_markdown  # noqa: E402

# MCP 사본. **파일 하나가 등록 단위**라 패키지가 아니고, 파서가 그 파일 안에 들어 있다.
# 모든 심볼에 `HX` 접두어가 붙어 있으므로 `to_markdown` 이 아니라 `hxto_markdown` 이다
# (같은 서버에 다른 도구 파일이 함께 로드돼도 덮이지 않게 한 것 —
# `check_mcp_tools.py` 의 "공존" 절 참고).
import importlib.util as _importlib_util  # noqa: E402

_MCP_HWPX = os.path.join(_ONPREM, "mcp", "genon_hwpx_text.py")
_spec = _importlib_util.spec_from_file_location("_mcp_hwpx_text", _MCP_HWPX)
_mcp_hwpx_text = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_mcp_hwpx_text)
mcp_to_markdown = _mcp_hwpx_text.hxto_markdown

# 전처리기(area 05) — **파싱 코어의 정본이다.** 3층(누락 방지)에서만 대조한다:
# 표 렌더링은 일부러 다르고(그쪽은 언제나 HTML + `<th>`) 문단 텍스트만 같아야 한다.
sys.path.insert(0, _ONPREM)
from preprocessor import hwpx_preprocessor as preproc  # noqa: E402

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = "http://www.hancom.co.kr/hwpml/2011/head"


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


def build_simple_fixture() -> bytes:
    """**병합도 중첩도 없는** 표만 담은 hwpx — 네 구현이 모두 마크다운을 내는 경우.

    파이프 이스케이프·다문단 `<br>`·좌표 없는 표 폴백은 형식과 무관한 규칙이라
    여기서 네 벌을 함께 본다.
    """
    table = (
        "<hp:tbl>"
        f"<hp:tr>{_cell(0, 0, '항목')}{_cell(0, 1, '값')}</hp:tr>"
        f"<hp:tr>{_cell(1, 0, 'a|b')}{_cell(1, 1, '')}</hp:tr>"
        "<hp:tr>"
        + _cell(2, 0, "", extra="<hp:p><hp:run><hp:t>첫 줄</hp:t></hp:run></hp:p>"
                                "<hp:p><hp:run><hp:t>둘째 줄</hp:t></hp:run></hp:p>")
        + _cell(2, 1, "옆")
        + "</hp:tr>"
        "</hp:tbl>"
    )

    def bare(text: str) -> str:
        return f"<hp:tc><hp:subList><hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p></hp:subList></hp:tc>"

    no_addr = (
        "<hp:tbl>"
        f"<hp:tr>{bare('좌')}{bare('우')}</hp:tr>"
        f"<hp:tr>{bare('하좌')}{bare('하우')}</hp:tr>"
        "</hp:tbl>"
    )

    section = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">'
        "<hp:p><hp:run><hp:secPr/></hp:run><hp:run><hp:t>보고서</hp:t></hp:run></hp:p>"
        f"<hp:p><hp:run>{table}</hp:run></hp:p>"
        "<hp:p><hp:run><hp:t>좌표 없는 표</hp:t></hp:run></hp:p>"
        f"<hp:p><hp:run>{no_addr}</hp:run></hp:p>"
        "</hs:sec>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("Contents/section0.xml", section)
    return buffer.getvalue()


def build_lossless_fixture() -> bytes:
    """**표가 아닌 글자**를 잃던 네 자리를 한 문서에 담는다 (3층 픽스처).

    전처리기가 2026-08-19·08-20 에 고치고 2026-08-23 에 네 사본으로 옮긴 층이다.
    전부 **예외를 던지지 않고 조용히 사라지는** 종류라, 남은 문장이 멀쩡해 보여서
    그 문장을 물어봤을 때까지 드러나지 않는다:

    1. **탭 뒤 글자** — `hp:t` 는 혼합 내용이라 `가.<hp:tab/>지원 대상` 의 뒷글자가
       자식의 `tail` 에 있다. `node.text` 만 읽으면 `가.` 만 남는다
    2. **자동 번호·글머리표** — 본문 XML 에 없고 `header.xml` 정의에서 나온다
    3. **상자 안 글** — 글상자·각주의 문단은 `hp:subList > hp:p` 라 "중첩 문단" 으로
       통째로 버려졌다
    4. **수식** — `hp:equation > hp:script` 에 있어 `hp:t` 만 보면 안 잡힌다

    **`@idRef="0"`** 을 쓰는 이유: 실물 한/글이 그 모양인데 `@id` 는 1 부터 시작한다.
    id 로만 찾는 구현은 여기서 번호가 전부 빠진다 (손으로 지은 픽스처가 `id="1"` ↔
    `idRef="1"` 로 맞아 있어서 실물에서 100% 실패하는 코드가 통과했던 전례가 있다).

    **번호가 안 붙은 빈 문단**(`나.` 자리)을 넣은 것도 계약이다 — 번호는 누적 상태라
    글자 없는 문단에서 `advance()` 를 건너뛰면 뒤 번호가 전부 밀린다.

    표는 **병합도 중첩도 없는 것 하나**만 둔다. 그래야 네 벌이 모두 마크다운을 내
    출력을 통째로 대조할 수 있다(형식 차이는 1·2층이 본다). 대신 그 셀 안에 글상자를
    넣어 **상자 판정이 셀 안에서도 도는지**를 함께 본다.

    **1칸 표(제목상자)도 넣는다.** hwpx 는 제목을 1칸 표로 만드는 일이 흔하고(저장소
    실물 기술협상서 2벌이 그렇다) 다섯 벌 모두 그것을 **문단으로** 내야 한다 — 표로
    내면 본문 행이 0개인 퇴화된 표(`| 제목 |` + `|---|`)가 결과물에 남는다.
    """
    boxed_cell = (
        "<hp:p><hp:run><hp:t>셀 본문</hp:t></hp:run>"
        "<hp:run><hp:rect><hp:drawText><hp:subList>"
        "<hp:p><hp:run><hp:t>셀 안 글상자</hp:t></hp:run></hp:p>"
        "</hp:subList></hp:drawText></hp:rect></hp:run></hp:p>"
    )
    table = (
        "<hp:tbl>"
        f"<hp:tr>{_cell(0, 0, '구분')}{_cell(0, 1, '내용')}</hp:tr>"
        f"<hp:tr>{_cell(1, 0, '비고')}{_cell(1, 1, '', extra=boxed_cell)}</hp:tr>"
        "</hp:tbl>"
    )

    # 제목상자 — 칸이 하나뿐인 표는 표가 아니다
    title_box = f"<hp:tbl><hp:tr>{_cell(0, 0, '『종합』 사업 계획서')}</hp:tr></hp:tbl>"

    section = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">'
        f"<hp:p><hp:run>{title_box}</hp:run></hp:p>"
        # 자동 번호 — 개요 1단계
        '<hp:p paraPrIDRef="1"><hp:run><hp:t>사업 개요</hp:t></hp:run></hp:p>'
        # 개요 2단계 → `가.`
        '<hp:p paraPrIDRef="2"><hp:run><hp:t>추진 배경</hp:t></hp:run></hp:p>'
        # 글자 없는 번호 문단 — `나.` 를 소비해야 다음이 `다.` 가 된다
        '<hp:p paraPrIDRef="2"><hp:run><hp:t></hp:t></hp:run></hp:p>'
        '<hp:p paraPrIDRef="2"><hp:run><hp:t>추진 경과</hp:t></hp:run></hp:p>'
        # 글머리표
        '<hp:p paraPrIDRef="3"><hp:run><hp:t>지원 대상</hp:t></hp:run></hp:p>'
        # 탭 뒤 글자 — 뒷부분이 `hp:tab` 의 tail 에 있다
        "<hp:p><hp:run><hp:t>가.<hp:tab/>지원 자격</hp:t></hp:run></hp:p>"
        # 수식
        "<hp:p><hp:run><hp:equation><hp:script>E=mc2</hp:script></hp:equation></hp:run></hp:p>"
        # 본문 글상자 — 라벨 없이 본문과 같이 낸다
        "<hp:p><hp:run><hp:rect><hp:drawText><hp:subList>"
        "<hp:p><hp:run><hp:t>글상자 안 문장</hp:t></hp:run></hp:p>"
        "</hp:subList></hp:drawText></hp:rect></hp:run></hp:p>"
        # 각주 — 본문 흐름 밖이라 라벨이 붙는다
        "<hp:p><hp:run><hp:t>본문 문장</hp:t></hp:run>"
        "<hp:run><hp:footNote><hp:subList>"
        "<hp:p><hp:run><hp:t>각주 내용</hp:t></hp:run></hp:p>"
        "</hp:subList></hp:footNote></hp:run></hp:p>"
        f"<hp:p><hp:run>{table}</hp:run></hp:p>"
        "</hs:sec>"
    )

    # `idRef="0"` ↔ `id="1"` — 실물 한/글의 모양이다. 인덱스 폴백이 없으면 여기서
    # 번호·글머리표가 전부 빠진다.
    header = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
        f'<hh:head xmlns:hh="{HH}">'
        "<hh:refList>"
        '<hh:numberings><hh:numbering id="1">'
        '<hh:paraHead level="1" start="1" numFormat="DIGIT">^1.</hh:paraHead>'
        '<hh:paraHead level="2" start="1" numFormat="HANGUL_SYLLABLE">^2.</hh:paraHead>'
        "</hh:numbering></hh:numberings>"
        '<hh:bullets><hh:bullet id="1" char="●"/></hh:bullets>'
        "<hh:paraProperties>"
        '<hh:paraPr id="1"><hh:heading type="OUTLINE" idRef="0" level="0"/></hh:paraPr>'
        '<hh:paraPr id="2"><hh:heading type="OUTLINE" idRef="0" level="1"/></hh:paraPr>'
        '<hh:paraPr id="3"><hh:heading type="BULLET" idRef="0" level="0"/></hh:paraPr>'
        "</hh:paraProperties>"
        "</hh:refList></hh:head>"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("Contents/header.xml", header)
        archive.writestr("Contents/section0.xml", section)
    return buffer.getvalue()


def _render_all(data: bytes) -> dict:
    """네 구현의 출력. 값 접근 경로가 달라 여기서 맞춰 준다."""
    return {
        "SFR-006": render_markdown(data).markdown,
        **_render_llm_path(data),
    }


def _render_llm_path(data: bytes) -> dict:
    """**LLM 입력 경로 세 벌**. 병합·중첩 표를 HTML 로 내도록 함께 바뀐 구현들이다.

    006(`hwpx_markdown`)은 여기 없다 — 그쪽 출력은 채팅 **화면 미리보기**용이라
    마크다운을 유지하기로 했다. 그래서 병합·중첩 표의 대조 대상은 셋이다.
    """
    return {
        "SFR-018 번역": trans_to_markdown(data).markdown,
        "SFR-018 FAQ": faq_to_markdown(data).markdown,
        "MCP hwpx_text": mcp_to_markdown(data).markdown,
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


def _top_level_td_count(row_html: str) -> int:
    """이 행이 **직접** 가진 `<td>` 수. 중첩 표 안의 셀은 세지 않는다."""
    stripped = row_html
    while True:
        reduced = re.sub(r"<table\b[^>]*>.*?</table\s*>", "", stripped, flags=re.DOTALL)
        if reduced == stripped:
            return stripped.count("<td")
        stripped = reduced


def _compare(rendered: dict, rep, label: str) -> str:
    """구현들의 출력이 서로 같은지. 기준값(첫 구현의 출력)을 돌려준다."""
    names = list(rendered)
    baseline = rendered[names[0]]
    for name in names[1:]:
        same = rendered[name].strip() == baseline.strip()
        rep.expect(
            same,
            f"[{label}] {names[0]} ↔ {name} 출력이 같다",
            "" if same else (
                f"\n--- {names[0]} ---\n{baseline}"
                f"\n--- {name} ---\n{rendered[name]}"
            ),
        )
    return baseline


def main() -> int:
    rep = Report()

    # ── 1층: 단순표 — 네 벌이 모두 마크다운을 낸다 ──────────────────────
    simple = _render_all(build_simple_fixture())
    base_simple = _compare(simple, rep, "단순표")

    blocks = _table_blocks(base_simple)
    rep.expect(len(blocks) == 2, "[단순표] 표 두 개가 모두 렌더된다", f"blocks={len(blocks)}")
    rep.expect(
        "\\|" in base_simple,
        "[단순표] 셀 안 파이프가 이스케이프된다 (안 하면 그 행부터 열이 밀린다)",
        base_simple,
    )
    rep.expect("<br>" in base_simple, "[단순표] 한 셀의 여러 문단이 <br> 로 이어진다", base_simple)
    rep.expect(
        "하좌" in base_simple and "하우" in base_simple,
        "[단순표] cellAddr 이 없는 표도 격자로 펴진다 (폴백 경로)",
        base_simple,
    )
    ragged = [
        (index, sorted(_columns(block)))
        for index, block in enumerate(blocks)
        if len(_columns(block)) != 1
    ]
    rep.expect(
        not ragged,
        "[단순표] 표 안 모든 행의 열 수가 같다",
        f"어긋난 표={ragged}\n{base_simple}",
    )
    rep.expect(
        "<table" not in base_simple,
        "[단순표] 손실이 없으면 HTML 로 바꾸지 않는다",
        base_simple,
    )

    # ── 2층: 병합·중첩표 — LLM 입력 경로 세 벌이 HTML 을 낸다 ────────────
    #
    # 006 은 여기 없다. 그쪽은 채팅 화면 미리보기용이라 마크다운을 유지한다.
    nasty_data = build_fixture()
    nasty = _render_llm_path(nasty_data)
    base_nasty = _compare(nasty, rep, "병합표")

    rep.expect("<table><tbody>" in base_nasty, "[병합표] HTML 표로 낸다", base_nasty)
    rep.expect(
        'colspan="2"' in base_nasty,
        "[병합표] 가로 병합이 colspan 으로 남는다 (마크다운은 표현 못 한다)",
        base_nasty,
    )
    rep.expect(
        'rowspan="2"' in base_nasty,
        "[병합표] 세로 병합이 rowspan 으로 남는다 (마크다운은 빈 칸이 됐다)",
        base_nasty,
    )
    rep.expect(
        base_nasty.count("<table><tbody>") >= 2 and "중첩" in base_nasty and "셀" in base_nasty,
        "[병합표] 중첩 표가 표로 남는다 (마크다운은 텍스트로 뭉갰다)",
        base_nasty,
    )
    rep.expect("<br>" in base_nasty, "[병합표] 한 셀의 여러 문단이 <br> 로 이어진다", base_nasty)
    # 병합 앵커가 아닌 자리는 td 를 내면 안 된다 — 내면 그 행만 열이 하나 늘어난다.
    #
    # **중첩 표 안의 td 를 빼고 세야 한다.** 처음엔 그냥 `row.count("<td")` 로 셌다가
    # 중첩 표가 든 행이 5개로 잡혀 걸렸다 — 렌더링은 멀쩡했고 세는 쪽이 틀렸다.
    rows = [line for line in base_nasty.splitlines() if line.startswith("<tr>")]
    counts = [_top_level_td_count(row) for row in rows]
    # 표는 3열이다. 1행 2개(colspan=2), 2행 3개, 3행 2개(rowspan 에 덮임).
    rep.expect(
        counts == [2, 3, 2],
        "[병합표] 병합으로 덮인 자리에 td 를 내지 않는다",
        f"행별 최상위 td 수={counts} (기대 [2, 3, 2])\n{base_nasty}",
    )
    # 006 은 같은 문서를 넣어도 마크다운이어야 한다 (미리보기 계약)
    preview = render_markdown(nasty_data).markdown
    rep.expect(
        "<table" not in preview and "|" in preview,
        "[병합표] 006 미리보기는 마크다운을 유지한다",
        preview,
    )

    # ── 3층: 누락 방지 — 네 벌 + **전처리기**가 같은 글자를 낸다 ──────────
    #
    # 표 형식이 아니라 **글자가 남는가**를 본다. 그래서 006 도 대상이고(미리보기에서
    # 빠진 글자는 "템플릿에 그 내용이 없다" 로 읽힌다) 전처리기도 대상이다.
    lossless_data = build_lossless_fixture()
    lossless = _render_all(lossless_data)
    base_lossless = _compare(lossless, rep, "누락 방지")

    # 값 하나하나를 따로 본다 — 상호 대조만으로는 **다섯이 똑같이 잃는 것**을 못 잡는다.
    for expected, why in (
        ("1. 사업 개요", "개요 번호(`@idRef=0` → 인덱스 폴백)"),
        ("가. 추진 배경", "개요 2단계 번호 서식(HANGUL_SYLLABLE)"),
        ("다. 추진 경과", "글자 없는 번호 문단이 번호를 소비한다"),
        ("● 지원 대상", "글머리표"),
        ("가. 지원 자격", "탭 **뒤** 글자 (`hp:t` 자식의 tail)"),
        ("E=mc2", "수식 (`hp:equation > hp:script`)"),
        ("글상자 안 문장", "본문 글상자 — 라벨 없이"),
        ("[각주] 각주 내용", "각주 — 본문 흐름 밖이라 라벨이 붙는다"),
        ("셀 안 글상자", "셀 **안** 글상자 (상자 판정이 셀 안에서도 돈다)"),
    ):
        rep.expect(
            expected in base_lossless,
            f"[누락 방지] {why}",
            f"기대 문자열={expected!r} 없음\n{base_lossless}",
        )
    # 1칸 표는 표가 아니라 제목상자다 — 문단으로 나와야 한다.
    rep.expect(
        "『종합』 사업 계획서" in base_lossless
        and "| 『종합』 사업 계획서 |" not in base_lossless,
        "[누락 방지] 1칸 표(제목상자)는 표가 아니라 문단으로 낸다",
        base_lossless,
    )
    # 각주가 본문 문장에 붙어 버리면 라벨만 있고 경계가 없다 — 따로 낸 블록이라야 한다.
    rep.expect(
        "본문 문장" in base_lossless.split("[각주]")[0],
        "[누락 방지] 각주가 본문 문단과 **따로** 나온다",
        base_lossless,
    )

    # 전처리기는 표를 언제나 HTML 로 내므로(일부러 다르다) **문단 텍스트만** 대조한다.
    preproc_paras = [
        block.text
        for block in preproc.parse(lossless_data).blocks
        if block.kind == "paragraph"
    ]
    copy_paras = [
        part
        for part in base_lossless.split("\n\n")
        if not part.startswith("|") and not part.startswith("<table")
    ]
    rep.expect(
        preproc_paras == copy_paras,
        "[누락 방지] 전처리기(정본) ↔ 사본 네 벌의 문단 텍스트가 같다",
        f"\n--- 전처리기 ---\n{preproc_paras}\n--- 사본 ---\n{copy_paras}",
    )

    print()
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        print()
        print("hwpx 파싱 코어 사본이 갈렸다. 어느 층이 FAIL 했는지로 범위가 갈린다:")
        print("  [병합표]   LLM 입력 경로 세 벌 — 표 형식 규칙")
        print("             mcp/genon_hwpx_text.py                                  (정본)")
        print("             codeserving/SFR-018_translation/.../office/hwpx_text.py")
        print("             codeserving/SFR-018_faq/faq/hwpx_text.py")
        print("  [단순표]   위 셋 + codeserving/SFR-006_template_fill/.../hwpx_markdown.py")
        print("  [누락 방지] 위 넷 + preprocessor/hwpx_preprocessor.py  (이 층의 **정본**)")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
