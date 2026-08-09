"""산출물 검증 스모크 점검 — 개봉 안전 게이트 · 넘침 측정 · 파트 선언 · 누름틀 안내문.

`python onprem/test/check_output_safety.py`

## 왜 여기 있나

`onprem/` 은 `tests/` 를 두지 않고, 사본(`SFR-006/template_fill/tests`)에는 슬롯 파서가
없다 — `check_body_blocks.py` 와 같은 사정이다. 그래서 합성 픽스처 스모크를 여기 둔다.
배포 단위 **바깥**이라 이미지에 흘러가지 않는다.

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

## python-hwpx 가 없으면

3·4 는 그 라이브러리로 하므로 **건너뛴다**. 건너뛴 사실을 출력에 남기고 종료 코드는
0 이다 — 워크플로우 pod 처럼 라이브러리 없는 환경이 정상 상태이기 때문이다.
1·2 는 라이브러리 없이도 돌고, 실패하면 실패로 잡힌다.
"""

import io
import os
import sys
import zipfile

_UNIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SFR-006_template_fill")
sys.path.insert(0, _UNIT)

from template_fill.document import build as build_document  # noqa: E402
from template_fill.hwpx_fields import missing_field_names, scan_fields  # noqa: E402

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"

# 실한컴이 쓰는 CLICK_HERE 파라미터 배치를 그대로 흉내 낸다 — **Command 가 먼저다.**
# 이 순서가 이 픽스처의 전부다. 순서를 뒤집으면 옛 구현도 통과해 버려 검사가 무의미해진다.
_SECTION = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<hs:sec xmlns:hs="{hs}" xmlns:hp="{hp}">
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
  <hp:p paraPrIDRef="0">
    <hp:run charPrIDRef="0"><hp:t>제 목 : {{'제목', 16pt}}</hp:t></hp:run>
  </hp:p>
</hs:sec>
""".format(hs=HS, hp=HP)

_HEADER = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" version="1.5" secCnt="1">
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
  </hh:refList>
</hh:head>
"""


def build_fixture() -> bytes:
    """누름틀 하나 + 슬롯 하나를 담은 최소 hwpx.

    실물 hwpx 파일을 요구하지 않는다 — 폐쇄망/CI 어디서든 돌아야 한다.

    **이 픽스처는 온전한 OPC 패키지가 아니다** (container.xml·content.hpf·version.xml 이
    없다). 파서와 직렬화기를 재는 데는 충분하고, 그래서 이 픽스처를 쓰는 검사는
    `verify=False` 로 돈다 — 개봉 안전 게이트는 이걸 정당하게 거절한다(실제로 거절했다).
    게이트 검사는 아래에서 **온전한 패키지**를 따로 만들어 돌린다.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("Contents/header.xml", _HEADER)
        archive.writestr("Contents/section0.xml", _SECTION)
    return buffer.getvalue()


def _library_available() -> bool:
    try:
        import hwpx  # noqa: F401
    except ImportError:
        return False
    return True


class Report:
    def __init__(self) -> None:
        self.failures: list = []
        self.checks = 0
        self.skipped: list = []

    def expect(self, condition: bool, label: str, detail: str = "") -> None:
        self.checks += 1
        if condition:
            print(f"[OK  ] {label}")
            return
        self.failures.append(label)
        print(f"[FAIL] {label}  {detail}")

    def skip(self, label: str, reason: str) -> None:
        self.skipped.append(label)
        print(f"[SKIP] {label}  ({reason})")


def main() -> int:
    rep = Report()
    raw = build_fixture()

    # 1) 파트 XML 선언 — standalone="yes" 가 살아 있어야 한다
    #    (픽스처가 온전한 패키지가 아니라 게이트는 끈다 — build_fixture docstring 참고)
    built = build_document(raw, {"제목": "분기 실적"}, label="smoke", verify=False)
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

    if not _library_available():
        rep.skip("개봉 안전 게이트", "python-hwpx 미설치")
        rep.skip("넘침 측정", "python-hwpx 미설치")
    else:
        # 3) 게이트가 깨진 문서를 막는가 — 안 막는 게이트는 게이트가 아니다
        from hwpx import HwpxDocument  # noqa: PLC0415 - 선택 의존이라 여기서만 부른다

        from template_fill.hwpx_verify import OpenSafetyError, enforce, verify

        # 온전한 OPC 패키지가 필요하다 (위 픽스처는 파트 두 개뿐이다).
        whole = HwpxDocument.new()
        whole.add_paragraph("제 목 : {'제목', 16pt}")
        package = whole.to_bytes()

        passed = build_document(package, {"제목": "분기 실적"}, label="smoke")
        rep.expect(verify(passed.hwpx_bytes).ok, "정상 산출물은 개봉 안전 검사를 통과한다")
        rep.expect(passed.open_safety_checked, "build 가 검사를 실제로 수행했다고 보고한다")

        broken = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(passed.hwpx_bytes)) as source, zipfile.ZipFile(
            broken, "w"
        ) as target:
            for item in source.infolist():
                payload = source.read(item.filename)
                # mimetype 이 다르면 한/글은 이 파일을 hwpx 로 보지 않는다
                target.writestr(item.filename, b"application/broken" if item.filename == "mimetype" else payload)
        blocked = False
        try:
            enforce(broken.getvalue(), "smoke")
        except OpenSafetyError:
            blocked = True
        rep.expect(blocked, "깨진 문서는 게이트가 막는다 (fail-closed)")

        # 4) 넘침은 표 셀 슬롯만 잰다
        from template_fill import overflow

        document = HwpxDocument.new()
        document.add_paragraph("제 목 : {'제목'}")
        table = document.add_table(1, 2)
        table.cell(0, 0).text = "성명"
        table.cell(0, 1).text = "{'성명'}"
        template = document.to_bytes()

        long_value = "왕주영 (플랫폼팀 · 2026년 상반기 신규 제품 출시 총괄 담당자)"
        short = overflow.check(template, {"성명": "왕주영", "제목": "보고"}, "smoke")
        rep.expect(not short, "칸에 들어가는 값은 경고하지 않는다", f"warnings={short}")

        long = overflow.check(template, {"성명": long_value, "제목": long_value}, "smoke")
        names = [warning.field for warning in long]
        rep.expect(names == ["성명"], "표 셀을 넘치는 값만 경고한다", f"warnings={names}")
        rep.expect(
            all(warning.lines > 1 and warning.ratio > 1.0 for warning in long),
            "경고에 예상 줄 수와 초과 비율이 들어 있다",
            f"warnings={[w.to_dict() for w in long]}",
        )

        # 넘침은 **경고이지 차단이 아니다** — 긴 값으로도 문서는 나와야 한다
        overflowed = build_document(template, {"성명": long_value}, label="smoke")
        rep.expect(
            bool(overflowed.hwpx_bytes) and overflowed.overflow,
            "넘쳐도 문서 생성은 막지 않고 경고만 싣는다",
            f"overflow={overflowed.overflow}",
        )

    print()
    if rep.skipped:
        print(f"SKIP {len(rep.skipped)} (python-hwpx 미설치 — 그 환경에서는 검사·측정이 꺼진다)")
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
