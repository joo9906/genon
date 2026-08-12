"""산출물 검증 스모크 점검 — 파트 선언 · 누름틀 안내문.

`python onprem/test/check_output_safety.py`

## 왜 여기 있나

`onprem/` 은 배포 단위 안에 `tests/` 를 두지 않는다. 그리고 이 점검은 **온전한 OPC
패키지 픽스처**(`hwpx_package.py`)를 요구하는데, 그 뼈대를 `check_body_blocks`·
`check_api_contract` 와 공유하므로 셋이 같은 자리에 있는 편이 맞다 —
`check_body_blocks.py` 와 같은 사정이다. 배포 단위 **바깥**이라 이미지에 흘러가지 않는다.

함수 단위 회귀 테스트는 `SFR-006/tests/` 가 맡는다. 그쪽은 2026-08-11 부터 사본이
아니라 **onprem 을 직접 태운다.**

## 무엇을 보는가

둘 다 실물에서 드러난 결함이거나, 그 결함을 다시 못 들어오게 하는 관문이다.

1. **파트 XML 선언에 `standalone="yes"` 가 남는다.** 한/글 원본은 그 선언으로 시작하는데
   `xml_declaration=True` 만 주면 lxml 이 빼고 쓴다. 실제 산출물(`data/FAQ_결과.hwpx`)이
   그 상태였다 — 원본과 다른 파일을 내보내고 있었다.
2. **누름틀 안내문은 `Direction` 파라미터다.** 실한컴 CLICK_HERE 는 원시 명령 블롭
   (`name="Command"`)을 먼저 쓴다. 그걸 안내문으로 잡으면 **미입력 필드가 입력됨으로
   판정돼** 사용자에게 묻지도 않고 안내문이 값인 채 문서가 나간다.

## 개봉 안전 게이트·넘침 측정은 뺐다 (2026-08-12)

예전에는 이 파일이 넷을 봤다. 셋째(개봉 안전 게이트)·넷째(넘침 측정)는
`hwpx_verify.py`·`overflow.py`와 그 둘이 쓰던 벤더 사본(`template_fill/_vendor/`,
상류 python-hwpx)째로 지웠다 — 실제 배포 템플릿 3개가 전부 표 없는 1~2쪽짜리라
두 검사 다 실질적으로 아무 판정도 하지 않고 있었다(넘침은 표 셀 슬롯만 잰다).
지운 코드는 `archive/hwpx-genon-vendor` 브랜치에 남아 있다.
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

from template_fill.document import build as build_document  # noqa: E402
from template_fill.hwpx_fields import missing_field_names, scan_fields  # noqa: E402

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = "http://www.hancom.co.kr/hwpml/2011/head"

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

_TITLE_PARA = """
  <hp:p paraPrIDRef="0">
    <hp:run charPrIDRef="0"><hp:t>제 목 : {'제목', 16pt}</hp:t></hp:run>
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
    `hwpx_package` 가 맡는다.
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
    raw = build_package(_CLICK_HERE_PARA, _TITLE_PARA)

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

    print()
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
