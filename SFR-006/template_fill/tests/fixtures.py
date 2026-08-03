"""테스트용 합성 hwpx 생성.

실제 한/글 산출물 대신 누름틀(CLICK_HERE) 구조를 그대로 흉내 낸 최소 hwpx 를
메모리에서 만든다 — 폐쇄망/CI 어디서든 샘플 파일 없이 파서를 검증하기 위함.
구조 근거는 hwpx_fields.py 모듈 docstring 의 OWPML 누름틀 스키마.
"""

import io
import zipfile

SECTION0_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  <hp:p id="2147483648" paraPrIDRef="1">
    <hp:run charPrIDRef="0">
      <hp:ctrl>
        <hp:fieldBegin id="100" type="CLICK_HERE" name="title" editable="true" dirty="false">
          <hp:parameters count="1">
            <hp:stringParam name="ClickHere">이곳을 눌러 제목 입력</hp:stringParam>
          </hp:parameters>
        </hp:fieldBegin>
      </hp:ctrl>
    </hp:run>
    <hp:run charPrIDRef="5"><hp:t>이곳을 눌러 제목 입력</hp:t></hp:run>
    <hp:run charPrIDRef="0"><hp:ctrl><hp:fieldEnd beginIDRef="100"/></hp:ctrl></hp:run>
  </hp:p>
  <hp:p id="2147483648" paraPrIDRef="2">
    <hp:run charPrIDRef="0">
      <hp:ctrl>
        <hp:fieldBegin id="101" type="CLICK_HERE" name="" editable="true" dirty="false">
          <hp:parameters count="1">
            <hp:stringParam name="ClickHere">시행일자 입력</hp:stringParam>
          </hp:parameters>
        </hp:fieldBegin>
      </hp:ctrl>
    </hp:run>
    <hp:run charPrIDRef="5"><hp:t>시행일자 입력</hp:t></hp:run>
    <hp:run charPrIDRef="0"><hp:ctrl><hp:fieldEnd beginIDRef="101"/></hp:ctrl></hp:run>
  </hp:p>
  <hp:p id="2147483648" paraPrIDRef="3">
    <hp:run charPrIDRef="0">
      <hp:ctrl>
        <hp:fieldBegin id="102" type="CLICK_HERE" name="manager" editable="true" dirty="true">
          <hp:parameters count="1">
            <hp:stringParam name="ClickHere">담당자 입력</hp:stringParam>
          </hp:parameters>
        </hp:fieldBegin>
      </hp:ctrl>
    </hp:run>
    <hp:run charPrIDRef="5"><hp:t>김철수 과장</hp:t></hp:run>
    <hp:run charPrIDRef="0"><hp:ctrl><hp:fieldEnd beginIDRef="102"/></hp:ctrl></hp:run>
  </hp:p>
  <hp:p id="2147483648" paraPrIDRef="4">
    <hp:run charPrIDRef="0">
      <hp:ctrl>
        <hp:fieldBegin id="103" type="CLICK_HERE" name="memo" editable="true" dirty="false">
          <hp:parameters count="1">
            <hp:stringParam name="ClickHere">비고 입력</hp:stringParam>
          </hp:parameters>
        </hp:fieldBegin>
      </hp:ctrl>
    </hp:run>
    <hp:run charPrIDRef="0"><hp:ctrl><hp:fieldEnd beginIDRef="103"/></hp:ctrl></hp:run>
  </hp:p>
  <hp:p id="2147483648" paraPrIDRef="5">
    <hp:run charPrIDRef="0"><hp:t>부서: {{dept}}</hp:t></hp:run>
  </hp:p>
</hs:sec>
"""


def build_sample_hwpx() -> bytes:
    """누름틀 4개(title/시행일자 입력/manager(기입력)/memo(빈 본문)) +
    {{dept}} 토큰 1개를 가진 최소 hwpx 바이트를 만든다."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("Contents/section0.xml", SECTION0_XML.encode("utf-8"))
        zf.writestr("Contents/header.xml", '<?xml version="1.0" encoding="UTF-8"?><h/>')
    return buf.getvalue()
