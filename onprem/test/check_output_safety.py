"""산출물 검증 스모크 점검 — 개봉 안전 게이트 · 넘침 측정 · 파트 선언 · 누름틀 안내문.

`python onprem/test/check_output_safety.py`

## 왜 여기 있나

`onprem/` 은 배포 단위 안에 `tests/` 를 두지 않는다. 그리고 이 점검은 **온전한 OPC
패키지 픽스처**(`hwpx_package.py`)를 요구하는데, 그 뼈대를 `check_body_blocks`·
`check_api_contract` 와 공유하므로 셋이 같은 자리에 있는 편이 맞다 —
`check_body_blocks.py` 와 같은 사정이다. 배포 단위 **바깥**이라 이미지에 흘러가지 않는다.

함수 단위 회귀 테스트는 `SFR-006/tests/` 가 맡는다. 그쪽은 2026-08-11 부터 사본이
아니라 **onprem 을 직접 태운다.**

## 무엇을 보는가

넷 다 실물에서 드러난 결함이거나, 그 결함을 다시 못 들어오게 하는 관문이다.

1. **파트 XML 선언에 `standalone="yes"` 가 남는다.** 한/글 원본은 그 선언으로 시작하는데
   `xml_declaration=True` 만 주면 lxml 이 빼고 쓴다. 실제 산출물(`data/FAQ_결과.hwpx`)이
   그 상태였다 — 원본과 다른 파일을 내보내고 있었다.
2. **누름틀 안내문은 `Direction` 파라미터다.** 실한컴 CLICK_HERE 는 원시 명령 블롭
   (`name="Command"`)을 먼저 쓴다. 그걸 안내문으로 잡으면 **미입력 필드가 입력됨으로
   판정돼** 사용자에게 묻지도 않고 안내문이 값인 채 문서가 나간다.
3. **개봉 안전 게이트가 실제로 막는다.** 이 저장소에는 한/글이 없어 "산출물이 열리는가"
   를 사람이 확인할 수 없다. 게이트가 그 판정을 대신하므로, 게이트가 **깨진 문서를
   통과시키지 않는지**를 여기서 확인한다 — 안 막는 게이트는 게이트가 아니다.
4. **넘침 측정이 표 셀 슬롯만 잡는다.** 본문 문단은 넘쳐도 다음 줄로 흐를 뿐이고,
   폭이 고정된 표 셀만 레이아웃을 깨뜨린다.

## 외부 의존이 없다 (2026-08-10)

예전에는 3·4 를 `python-hwpx` 로 했고, 없으면 SKIP 했다. 검사기·측정기를 벤더 사본으로
가져오면서(`template_fill/_vendor/`) **SKIP 경로가 사라졌다** — 네 검사가 항상 돈다.

픽스처도 라이브러리로 만들지 않는다. `HwpxDocument.new()` 로 온전한 패키지를 얻던 자리를
**손으로 쓴 OPC 패키지**(`build_package`)가 대신한다. 그 편이 오히려 정확하다: 게이트가
보는 것이 바로 그 패키지 계약(mimetype·container·manifest spine·secCnt 대조)이라,
픽스처를 직접 쓰면 무엇을 재고 있는지가 픽스처에 드러난다.
"""

import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 공용 픽스처 헬퍼
_UNIT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "codeserving",  # 2026-08-11 영역별 재배치
    "SFR-006_template_fill",
)
sys.path.insert(0, _UNIT)

import hwpx_package  # noqa: E402  - 온전한 OPC 패키지 뼈대 (배포 단위 바깥)

from template_fill import overflow  # noqa: E402
from template_fill.document import build as build_document  # noqa: E402
from template_fill.hwpx_fields import missing_field_names, scan_fields  # noqa: E402
from template_fill.hwpx_verify import OpenSafetyError, enforce, verify  # noqa: E402

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
OPF = "http://www.idpf.org/2007/opf/"
OCF = "urn:oasis:names:tc:opendocument:xmlns:container"

_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'

# 실한컴이 쓰는 CLICK_HERE 파라미터 배치를 그대로 흉내 낸다 — **Command 가 먼저다.**
# 이 순서가 이 픽스처의 전부다. 순서를 뒤집으면 옛 구현도 통과해 버려 검사가 무의미해진다.
_CLICK_HERE_PARA = """
  <hp:p paraPrIDRef="0">
    <hp:run charPrIDRef="0"><hp:secPr/></hp:run>
    <hp:run charPrIDRef="0"><hp:t>성명 : </hp:t></hp:run>
    <hp:run charPrIDRef="0"><hp:ctrl>
      <hp:fieldBegin id="1" type="CLICK_HERE" name="성명">
        <hp:parameters cnt="2" name="">
          <hp:stringParam name="Command">Clickhere:set:51:Direction:wstring:9:이름을 적으세요 HelpState:wstring:0:</hp:stringParam>
          <hp:stringParam name="Direction">이름을 적으세요</hp:stringParam>
        </hp:parameters>
      </hp:fieldBegin>
    </hp:ctrl></hp:run>
    <hp:run charPrIDRef="0"><hp:t>이름을 적으세요</hp:t></hp:run>
    <hp:run charPrIDRef="0"><hp:ctrl><hp:fieldEnd beginIDRef="1"/></hp:ctrl></hp:run>
  </hp:p>
"""

# 본문 문단 슬롯 — **넘침 측정 대상이 아니다** (넘쳐도 다음 줄로 흐를 뿐이다).
_TITLE_PARA = """
  <hp:p paraPrIDRef="0">
    <hp:run charPrIDRef="0"><hp:t>제 목 : {'제목', 16pt}</hp:t></hp:run>
  </hp:p>
"""


def _cell(col: int, text: str, width: int) -> str:
    """표 셀 하나. `cellSz`·`cellMargin`·`cellSpan`·`cellAddr`·`subList` 는 전부 필수다 —
    하나라도 빠지면 `validate_package` 가 **차단 오류**로 잡는다(한/글이 거절하는 조합).
    """
    return f"""
        <hp:tc name="" header="0" hasMargin="1" protect="0" editable="0" dirty="0" borderFillIDRef="1">
          <hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">
            <hp:p paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
              <hp:run charPrIDRef="0"><hp:t>{text}</hp:t></hp:run>
            </hp:p>
          </hp:subList>
          <hp:cellAddr colAddr="{col}" rowAddr="0"/>
          <hp:cellSpan colSpan="1" rowSpan="1"/>
          <hp:cellSz width="{width}" height="3000"/>
          <hp:cellMargin left="510" right="510" top="141" bottom="141"/>
        </hp:tc>"""


# 좁은 칸(6,000 HWPUNIT)에 슬롯을 둔다. 10pt 한글 한 글자가 1,000 HWPUNIT 이므로
# 여백·안전계수를 빼면 한 줄에 네댓 자다 — 짧은 값은 들어가고 긴 값은 넘친다.
_TABLE_PARA = f"""
  <hp:p paraPrIDRef="0">
    <hp:run charPrIDRef="0">
      <hp:tbl id="1" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="0" rowCnt="1" colCnt="2" cellSpacing="0" borderFillIDRef="1" noAdjust="0">
        <hp:sz width="14000" widthRelTo="ABSOLUTE" height="3000" heightRelTo="ABSOLUTE" protect="0"/>
        <hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>
        <hp:outMargin left="0" right="0" top="0" bottom="0"/>
        <hp:inMargin left="510" right="510" top="141" bottom="141"/>
        <hp:tr>{_cell(0, "담당", 8000)}{_cell(1, "{'담당자'}", 6000)}
        </hp:tr>
      </hp:tbl>
    </hp:run>
  </hp:p>
"""

_HEADER = f"""{_DECL}
<hh:head xmlns:hh="{HH}" version="1.5" secCnt="1">
  <hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>
  <hh:refList>
    <hh:fontfaces itemCnt="1">
      <hh:fontface lang="HANGUL" fontCnt="1">
        <hh:font id="0" face="함초롬바탕" type="TTF" isEmbedded="0"/>
      </hh:fontface>
    </hh:fontfaces>
    <hh:charProperties itemCnt="1">
      <hh:charPr id="0" height="1000" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="2">
        <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
      </hh:charPr>
    </hh:charProperties>
    <hh:paraProperties itemCnt="1">
      <hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0">
        <hh:align horizontal="JUSTIFY" vertical="BASELINE"/>
        <hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>
      </hh:paraPr>
    </hh:paraProperties>
  </hh:refList>
  <hh:compatibleDocument targetProgram="HWP201X"/>
</hh:head>
"""

def build_package(*paragraphs: str) -> bytes:
    """문단들을 온전한 OPC 패키지로 감싼다 — 외부 라이브러리를 쓰지 않는다.

    포장(container·manifest·version·preview·`mimetype` 첫 항목 STORED)은
    `hwpx_package` 가 맡는다. 파트가 두어 개뿐인 반쪽 픽스처로는 게이트를 잴 수 없다 —
    게이트가 그것을 정당하게 거절하기 때문이고, 그래서 이 뼈대가 필요하다.
    """
    section = f"""{_DECL}
<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{"".join(paragraphs)}</hs:sec>
"""
    return hwpx_package.build(section, _HEADER)


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
    raw = build_package(_CLICK_HERE_PARA, _TITLE_PARA, _TABLE_PARA)

    # 1) 파트 XML 선언 — standalone="yes" 가 살아 있어야 한다
    built = build_document(raw, {"제목": "분기 실적"}, label="smoke")
    section = zipfile.ZipFile(io.BytesIO(built.hwpx_bytes)).read("Contents/section0.xml")
    declaration = section.split(b"?>", 1)[0].decode("utf-8", errors="replace")
    rep.expect(
        "standalone" in declaration and "yes" in declaration,
        '산출 파트 XML 선언에 standalone="yes" 가 남는다',
        f"decl={declaration!r}",
    )

    # 2) 누름틀 안내문 — Command 블롭이 아니라 Direction 이어야 한다
    specs = {spec.name: spec for spec in scan_fields(raw)}
    field = specs.get("성명")
    rep.expect(field is not None, "누름틀을 항목으로 인식한다")
    if field is not None:
        rep.expect(
            field.guide == "이름을 적으세요",
            "누름틀 안내문은 Direction 파라미터다 (Command 블롭이 아니다)",
            f"guide={field.guide!r}",
        )
        rep.expect(
            not field.filled,
            "안내문만 있는 누름틀은 **미입력**으로 판정된다",
            f"filled={field.filled} current={field.current_value!r}",
        )
        rep.expect(
            "성명" in missing_field_names(list(specs.values()), {}),
            "미입력 누름틀은 사용자에게 물어볼 목록에 들어간다",
            f"missing={missing_field_names(list(specs.values()), {})}",
        )

    # 3) 게이트가 깨진 문서를 막는가 — 안 막는 게이트는 게이트가 아니다
    passed = verify(built.hwpx_bytes, "smoke")
    rep.expect(passed.ok, "정상 산출물은 개봉 안전 검사를 통과한다", f"blocking={passed.blocking}")
    rep.expect(built.open_safety_checked, "build 가 검사를 실제로 수행했다고 보고한다")
    rep.expect(
        not passed.reopen_checked,
        "재개봉은 **하지 않았다고** 보고한다 (통과로 위장하지 않는다)",
    )

    broken = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(built.hwpx_bytes)) as source, zipfile.ZipFile(
        broken, "w"
    ) as target:
        for item in source.infolist():
            payload = source.read(item.filename)
            # mimetype 이 다르면 한/글은 이 파일을 hwpx 로 보지 않는다
            target.writestr(
                item.filename,
                b"application/broken" if item.filename == "mimetype" else payload,
            )
    blocked = False
    try:
        enforce(broken.getvalue(), "smoke")
    except OpenSafetyError:
        blocked = True
    rep.expect(blocked, "깨진 문서는 게이트가 막는다 (fail-closed)")

    # 루트 요소가 어긋난 문서도 막는다 (상류 XSD 검사를 대신하는 우리 판정)
    swapped = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(built.hwpx_bytes)) as source, zipfile.ZipFile(
        swapped, "w"
    ) as target:
        for item in source.infolist():
            payload = source.read(item.filename)
            if item.filename == "Contents/header.xml":
                payload = payload.replace(b"<hh:head ", b"<hh:notahead ").replace(
                    b"</hh:head>", b"</hh:notahead>"
                )
            target.writestr(item.filename, payload)
    root_blocked = False
    try:
        enforce(swapped.getvalue(), "smoke")
    except OpenSafetyError:
        root_blocked = True
    rep.expect(root_blocked, "header 루트가 hh:head 가 아니면 막는다")

    # advisory 는 막지 않는다 — 이 픽스처는 한컴 호환 네임스페이스를 전부 선언하지 않아
    # 그 항목이 advisory 로 잡히는데, 실한컴이 열어 주는 것이 관측된 항목이라 통과해야 한다.
    rep.expect(
        passed.advisory and passed.ok,
        "advisory 오류는 경고로만 남기고 막지 않는다",
        f"advisory={passed.advisory}",
    )

    # 4) 넘침은 표 셀 슬롯만 잰다
    #
    # 먼저 **어댑터가 문서를 실제로 읽고 있는지** 수치로 못박는다. 상류 측정기는 셀·문서를
    # duck-typing 으로 받고 `getattr(…, 기본값)` 으로 방어하므로, 우리 어댑터의 속성명이
    # 하나 틀려도 예외가 나지 않고 **폭 0 · 10pt 기본값**으로 조용히 떨어진다. 그러면
    # 넘침 판정이 통째로 무의미해지는데 검사는 여전히 초록으로 보인다.
    from template_fill.overflow import _CellView, _StyleBook, _own_paragraphs  # noqa: PLC0415
    from template_fill._vendor.hwpx.form_fit import resolve_slot_metrics  # noqa: PLC0415
    from template_fill.hwpx_fields import HP_NS, open_hwpx, parse_xml, section_order  # noqa: PLC0415
    from template_fill.hwpx_style import HEADER_ENTRY  # noqa: PLC0415

    with open_hwpx(raw) as archive:
        styles = _StyleBook(parse_xml(archive.read(HEADER_ENTRY)))
        entry = next(n for n in archive.namelist() if section_order(n) is not None)
        body = parse_xml(archive.read(entry))
        slot_cell = [
            cell
            for table in body.iter(f"{{{HP_NS}}}tbl")
            for cell in table.iterfind(f"{{{HP_NS}}}tr/{{{HP_NS}}}tc")
        ][1]
        metrics = resolve_slot_metrics(
            _CellView(slot_cell, _own_paragraphs(slot_cell)), styles, max_lines=1
        )
    # cellSz.width 6000 - cellMargin(510+510) = 4980, × 안전계수 0.93 = 4631.4
    rep.expect(
        abs(metrics.available_width - (6000 - 1020) * 0.93) < 1.0,
        "어댑터가 cellSz.width 와 cellMargin 을 실제로 읽는다 (기본값 0 이 아니다)",
        f"available_width={metrics.available_width}",
    )
    rep.expect(
        metrics.font_pt == 10.0 and metrics.line_spacing_ratio == 1.6,
        "어댑터가 charPr@height 와 paraPr/lineSpacing 을 실제로 읽는다",
        f"font_pt={metrics.font_pt} line_spacing_ratio={metrics.line_spacing_ratio}",
    )

    long_value = "왕주영 (플랫폼팀 · 2026년 상반기 신규 제품 출시 총괄 담당자)"
    short = overflow.check(raw, {"담당자": "왕주영", "제목": "보고"}, "smoke")
    rep.expect(not short, "칸에 들어가는 값은 경고하지 않는다", f"warnings={short}")

    long = overflow.check(raw, {"담당자": long_value, "제목": long_value}, "smoke")
    names = [warning.field for warning in long]
    rep.expect(
        names == ["담당자"],
        "표 셀을 넘치는 값만 경고한다 (본문 문단 슬롯은 재지 않는다)",
        f"warnings={names}",
    )
    rep.expect(
        all(warning.lines > 1 and warning.ratio > 1.0 for warning in long),
        "경고에 예상 줄 수와 초과 비율이 들어 있다",
        f"warnings={[w.to_dict() for w in long]}",
    )

    # 넘침은 **경고이지 차단이 아니다** — 긴 값으로도 문서는 나와야 한다
    overflowed = build_document(raw, {"담당자": long_value}, label="smoke")
    rep.expect(
        bool(overflowed.hwpx_bytes) and overflowed.overflow,
        "넘쳐도 문서 생성은 막지 않고 경고만 싣는다",
        f"overflow={overflowed.overflow}",
    )

    print()
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
