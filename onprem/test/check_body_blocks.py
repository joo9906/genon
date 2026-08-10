"""본문 블록(템플릿 항목 밖에 이어 쓰는 내용) 스모크 점검.

`python onprem/test/check_body_blocks.py`

## 왜 여기 있나 — 이 폴더는 원래 배포 계약 점검용인데

기능 회귀 테스트의 제자리는 `SFR-006/template_fill/tests/` 다. 그런데 **그 사본에는
라벨 항목 파서가 없다** (`collect_label_occurrences`·`own_nodes`·`nearest_para` 가
onprem 에만 있다 — 루트 CLAUDE.md "남은 일" 참고). 블록은 그 파서 위에 서 있어서,
사본에 유닛테스트를 붙이려면 라벨 파서부터 통째로 이식해야 한다. 그건 별건이다.

그래서 그 이식이 끝날 때까지는 **합성 픽스처 스모크**를 여기 둔다. 배포 단위 바깥이라
이미지에 흘러가지 않는 것은 이 폴더의 다른 스크립트와 같고, 표본 hwpx 파일 없이
메모리에서 문서를 만들어 돌기 때문에 폐쇄망/CI 어디서든 실행된다.
라벨 파서를 사본에 이식하는 순간 이 파일은 `tests/` 로 옮겨 unittest 로 바꾼다.

## 무엇을 보는가

블록 경로가 문서를 깨뜨릴 수 있는 지점만 본다. 전부 **결정적**이라 LLM 도 서버도
필요 없다.

1. 표 안 라벨은 **채울 항목으로는 잡히되 서식 원본으로는 쓰이지 않는다**
   (셀 문단을 본문에 복제하면 셀 폭 기준 서식이 본문에 나온다)
2. 문단을 복제해도 **표·구역정의(secPr)·누름틀이 딸려오지 않는다** — 가장 위험한 지점
3. 블록이 지정한 항목의 `charPrIDRef`·`paraPrIDRef` 를 그대로 물려받는다
4. **header.xml 이 바뀌지 않는다** — 블록은 서식 정의를 새로 만들지 않는다
5. 미리보기(`render_filled`)와 다운로드 문서의 본문이 **글자 단위로 같다**
6. 검증(`normalize_blocks`)이 잘못된 입력을 버리되 **본문을 잃지 않는다**
"""

import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 공용 픽스처 헬퍼
_UNIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SFR-006_template_fill")
sys.path.insert(0, _UNIT)

import hwpx_package  # noqa: E402  - 온전한 OPC 패키지 뼈대 (배포 단위 바깥)
from lxml import etree  # noqa: E402

from template_fill.document import build as build_document  # noqa: E402
from template_fill.field_judge import normalize_blocks, parse_updates  # noqa: E402
from template_fill.hwpx_blocks import BodyBlock, block_style_names  # noqa: E402
from template_fill.hwpx_fields import scan_fields  # noqa: E402
from template_fill.hwpx_markdown import render_filled, render_markdown  # noqa: E402

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"

# 현장 템플릿(`data/파워.hwpx`)의 모양을 그대로 흉내 낸다. **위험한 지점을 일부러 넣는다**:
# - 첫 문단이 구역 정의(secPr)와 제목 라벨을 **한 문단에** 담는다 — 실물이 그렇다.
#   그래서 "제 목" 을 서식 원본으로 복제하면 secPr 이 딸려올 수 있다.
# - 표를 담은 문단이 **자기 텍스트도 갖고**(`첨부 : …`), 표 run 이 **텍스트 run 보다
#   앞에** 있다. 그래서 라벨로 인식돼 서식 원본 후보가 되고, "첫 run 을 그대로 쓰는"
#   식으로 복제하면 표가 통째로 복제된다.
_SECTION = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="{hp}">
  <hp:p paraPrIDRef="1">
    <hp:run charPrIDRef="1"><hp:secPr/></hp:run>
    <hp:run charPrIDRef="1"><hp:t>제 목 : {{'제 목', 고딕, 16pt, 굵게}}</hp:t></hp:run>
  </hp:p>
  <hp:p paraPrIDRef="0">
    <hp:run charPrIDRef="0"><hp:tbl rowCnt="1" colCnt="2">
      <hp:sz width="14000" widthRelTo="ABSOLUTE" height="3000" heightRelTo="ABSOLUTE"/>
      <hp:pos treatAsChar="0" vertRelTo="PARA" horzRelTo="COLUMN" vertOffset="0" horzOffset="0"/>
      <hp:outMargin left="0" right="0" top="0" bottom="0"/>
      <hp:inMargin left="510" right="510" top="141" bottom="141"/>
      <hp:tr>
        <hp:tc><hp:subList>
          <hp:p><hp:run charPrIDRef="0"><hp:t>문서명: {{'문서명'}}</hp:t></hp:run></hp:p>
        </hp:subList>
        <hp:cellAddr colAddr="0" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>
        <hp:cellSz width="7000" height="3000"/>
        <hp:cellMargin left="510" right="510" top="141" bottom="141"/></hp:tc>
        <hp:tc><hp:subList>
          <hp:p><hp:run charPrIDRef="0"><hp:t>보고자: {{'보고자'}}</hp:t></hp:run></hp:p>
        </hp:subList>
        <hp:cellAddr colAddr="1" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>
        <hp:cellSz width="7000" height="3000"/>
        <hp:cellMargin left="510" right="510" top="141" bottom="141"/></hp:tc>
      </hp:tr>
    </hp:tbl></hp:run>
    <hp:run charPrIDRef="0"><hp:t>첨부 : {{'첨부', 10pt}}</hp:t></hp:run>
  </hp:p>
  <hp:p paraPrIDRef="2"><hp:run charPrIDRef="2"/></hp:p>
  <hp:p paraPrIDRef="3"><hp:run charPrIDRef="3"><hp:t>주요 내용: {{'주요 내용', 휴먼명조, 11pt}}</hp:t></hp:run></hp:p>
</hs:sec>
""".format(hp=HP)

# charPr 4개(id 0~3) + 폰트 목록. 서식 적용 경로가 실제로 돌아야 4번 점검이 의미를 갖는다.
_HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<hh:head xmlns:hh="{hh}">
  <hh:refList>
    <hh:fontfaces>
      <hh:fontface lang="HANGUL" fontCnt="1"><hh:font id="0" face="함초롬바탕" type="TTF"/></hh:fontface>
      <hh:fontface lang="LATIN" fontCnt="1"><hh:font id="0" face="함초롬바탕" type="TTF"/></hh:fontface>
    </hh:fontfaces>
    <hh:charProperties itemCnt="4">
      <hh:charPr id="0" height="1000"><hh:fontRef hangul="0" latin="0"/></hh:charPr>
      <hh:charPr id="1" height="1000"><hh:fontRef hangul="0" latin="0"/></hh:charPr>
      <hh:charPr id="2" height="500"><hh:fontRef hangul="0" latin="0"/></hh:charPr>
      <hh:charPr id="3" height="1000"><hh:fontRef hangul="0" latin="0"/></hh:charPr>
    </hh:charProperties>
  </hh:refList>
</hh:head>
""".format(hh=HH)


def build_fixture() -> bytes:
    """**온전한 OPC 패키지**로 만든다 (`hwpx_package.build`).

    위험한 본문 모양(secPr 과 슬롯을 한 문단에, 표 run 을 텍스트 run 앞에)은 그대로다 —
    그게 이 픽스처의 요점이다. 달라진 것은 포장뿐이고, 그래야 `_build_document` 가
    개봉 안전 게이트를 켠 채로 운영과 같은 경로를 돌 수 있다.
    """
    return hwpx_package.build(_SECTION, _HEADER)


def _section_root(hwpx_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(hwpx_bytes)) as zf:
        return etree.fromstring(zf.read("Contents/section0.xml"))


def _entry(hwpx_bytes: bytes, name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(hwpx_bytes)) as zf:
        return zf.read(name)


def _top_paragraphs(root) -> list:
    return [p for p in root if p.tag == f"{{{HP}}}p"]


def _style_signature(para, value: str = "") -> tuple:
    """복제가 물려받아야 하는 값 — (문단 서식 id, **값이 놓인 run** 의 글자 서식 id).

    run 목록 전체를 비교하지 않는 이유: 원본에는 복제 대상이 아닌 run(secPr·표)이
    함께 있고, 그것들이 빠지는 것이 정상이다. 서식이 물려받아졌는지만 본다.

    첫 텍스트 run 이 아니라 **값 run** 을 보는 이유: 슬롯 문법에서 서식은 중괄호 자리에만
    걸린다. 중괄호 밖 라벨(`제 목 : `)은 원래 서식을 그대로 지키므로, 첫 run 을 집으면
    제목 서식이 아니라 라벨 서식과 비교하게 된다.
    """
    runs = [r for r in para if r.tag == f"{{{HP}}}run" and r.find(f"{{{HP}}}t") is not None]
    if value:
        for run in runs:
            if value in "".join((t.text or "") for t in run.findall(f"{{{HP}}}t")):
                return para.get("paraPrIDRef"), run.get("charPrIDRef")
    return para.get("paraPrIDRef"), (runs[0].get("charPrIDRef") if runs else None)


def _own_text(para) -> str:
    """문단이 직접 가진 텍스트 (표 셀 텍스트는 제외)."""
    return "".join(
        (t.text or "")
        for run in para
        if run.tag == f"{{{HP}}}run"
        for t in run.findall(f"{{{HP}}}t")
    )


def _build_document(template_bytes: bytes, values: dict, blocks: list) -> bytes:
    """운영이 쓰는 **바로 그 파이프라인**(`document.build`)을 부른다.

    예전에는 이 함수가 채우기 → 서식 → 블록 순서를 **여기서 다시 적었다.** 그러면 점검이
    자기가 검증하려는 순서를 스스로 복제하는 셈이라, 운영 순서가 바뀌어도 통과한다.
    지금은 운영 코드가 순서를 바꾸면 아래 "서식 적용 뒤 복제" 검사가 즉시 깨진다.

    **개봉 안전 게이트도 켠 채로 부른다.** 게이트는 2026-08-10 이후 모든 환경에서 도는데,
    그 앞에서 `verify=False` 로 비켜 가면 이 점검이 재는 파이프라인이 운영이 실제로 도는
    파이프라인과 갈린다 — 이 함수가 존재하는 이유와 정면으로 어긋난다. 대신 픽스처를
    온전한 OPC 패키지로 만들었다(`hwpx_package.build`).
    """
    return build_document(template_bytes, values, blocks, label="smoke").hwpx_bytes


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
    raw = build_fixture()

    # 1) 표 안 라벨은 채울 항목이지만 서식 원본은 아니다
    field_names = [spec.name for spec in scan_fields(raw)]
    styles = block_style_names(raw)
    rep.expect(
        {"문서명", "보고자"} <= set(field_names),
        "표 안 라벨이 채울 항목으로 잡힌다",
        f"fields={field_names}",
    )
    rep.expect(
        not ({"문서명", "보고자"} & set(styles)),
        "표 안 라벨은 블록 서식 목록에서 빠진다",
        f"styles={styles}",
    )
    rep.expect(
        set(styles) >= {"제 목", "주요 내용"},
        "본문 라벨은 블록 서식으로 쓸 수 있다",
        f"styles={styles}",
    )

    # 2~4) 복제가 표·구역정의를 끌고 오지 않고, 서식을 물려받고, header 를 안 건드린다
    values = {"문서명": "상반기 보고", "보고자": "왕주영", "제 목": "실적 보고", "주요 내용": "핵심"}
    # 서식 원본을 **위험한 문단으로 지정한다**: 제 목(secPr 동거), 첨부(표 소유).
    # 안전장치가 없으면 여기서 구역 정의와 표가 복제된다.
    blocks = [
        BodyBlock(text="1. 추진 배경", style_ref="제 목"),
        BodyBlock(text="가. 첫째 줄\n나. 둘째 줄", style_ref="주요 내용"),
        BodyBlock(text="표 문단 서식을 빌려온 줄", style_ref="첨부"),
    ]
    document = _build_document(raw, values, blocks)

    styled_only = _build_document(raw, values, [])
    root = _section_root(document)
    before = _section_root(styled_only)

    rep.expect(
        len(list(root.iter(f"{{{HP}}}tbl"))) == 1,
        "블록을 붙여도 표가 복제되지 않는다",
        f"tbl={len(list(root.iter(f'{{{HP}}}tbl')))}",
    )
    rep.expect(
        len(list(root.iter(f"{{{HP}}}secPr"))) == 1,
        "블록을 붙여도 구역 정의(secPr)가 복제되지 않는다",
        f"secPr={len(list(root.iter(f'{{{HP}}}secPr')))}",
    )
    rep.expect(
        _entry(document, "Contents/header.xml") == _entry(styled_only, "Contents/header.xml"),
        "블록은 서식 정의(header.xml)를 바꾸지 않는다",
    )

    added = _top_paragraphs(root)[len(_top_paragraphs(before)):]
    rep.expect(len(added) == 4, "줄바꿈이 문단으로 나뉜다 (블록 3개 → 문단 4개)", f"added={len(added)}")

    sources = {_own_text(p): p for p in _top_paragraphs(before)}
    title = next((p for text, p in sources.items() if text.startswith("제 목")), None)
    body = next((p for text, p in sources.items() if text.startswith("주요 내용")), None)
    attach = next((p for text, p in sources.items() if text.startswith("첨부")), None)
    if len(added) == 4 and title is not None and body is not None and attach is not None:
        for clone, source, value, label in (
            (added[0], title, values["제 목"], "제목(구역 정의와 한 문단)"),
            (added[1], body, values["주요 내용"], "본문"),
            (added[3], attach, "", "표를 담은 문단"),
        ):
            rep.expect(
                _style_signature(clone) == _style_signature(source, value),
                f"{label} 서식을 지정한 블록이 그 문단의 서식을 물려받는다",
                f"{_style_signature(clone)} != {_style_signature(source, value)}",
            )
        rep.expect(
            all(len(list(p.iter(f"{{{HP}}}tbl"))) == 0 for p in added),
            "복제된 문단 어디에도 표가 들어 있지 않다",
        )
        rep.expect(
            all(len(list(p.iter(f"{{{HP}}}secPr"))) == 0 for p in added),
            "복제된 문단 어디에도 구역 정의가 들어 있지 않다",
        )
        # 서식 명세 적용 **뒤** 문단을 복제하는지 (순서 검증). 원본 charPr(1)이 그대로면
        # 서식이 반영되기 전 모양을 물려받은 것이다.
        rep.expect(
            _style_signature(added[0])[1] != "1",
            "블록은 서식 적용 **뒤** 문단을 복제한다",
            f"charPr={_style_signature(added[0])[1]}",
        )
    else:
        rep.expect(False, "복제 원본 문단을 찾지 못했다", f"added={len(added)}")

    # 5) 미리보기와 다운로드 문서의 본문이 같다
    preview = render_filled(raw, values, max_chars=None, blocks=blocks)
    rep.expect(
        preview.markdown == render_markdown(document).markdown,
        "미리보기와 다운로드 문서의 본문이 같다",
    )

    # 6) 검증이 잘못된 입력을 버리되 본문을 잃지 않는다
    parsed, rejected = normalize_blocks(
        [
            {"text": "정상", "style_ref": "제 목"},
            {"text": "서식만 틀림", "style_ref": "없는항목"},
            {"text": "   "},
            "문자열도 허용",
        ],
        styles,
    )
    rep.expect(len(parsed) == 3, "빈 본문만 버리고 나머지는 살린다", f"parsed={len(parsed)}")
    rep.expect(
        parsed[1].style_ref == "" and any("없는항목" in r for r in rejected),
        "모르는 서식은 기본값으로 떨어뜨리고 사유를 남긴다",
        f"rejected={rejected}",
    )

    intent = parse_updates(
        '{"blocks": [{"text": "추가"}], "block_clears": [1, 9]}',
        set(field_names),
        allowed_styles=styles,
        block_count=2,
    )
    rep.expect(
        intent.block_clears == [0] and any("9" in r for r in intent.rejected),
        "블록 삭제 번호는 범위를 벗어나면 기각된다",
        f"clears={intent.block_clears} rejected={intent.rejected}",
    )

    print()
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
