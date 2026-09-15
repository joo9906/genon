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
    return _pack(SECTION0_XML)


# ─────────────────────────────────────────────────────────────
# 슬롯 픽스처 — 2026-08-06 이후의 기본 인식 방식
# ─────────────────────────────────────────────────────────────
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"

# 따옴표 표기 3종. 한/글 자동 고침이 곧은 따옴표를 굽은 것으로 바꿔 저장하는데,
# **관리자는 그 차이를 눈으로 구분할 수 없다** — 한쪽만 받으면 항목이 통째로 사라진다.
_QUOTES = {
    "straight": ("&apos;", "&apos;"),
    "curly": ("‘", "’"),
    "half": ("‘", "&apos;"),  # 자동 고침이 여는 쪽만 바꾼 문서
}


def _para(text: str) -> str:
    return f'<hp:p><hp:run charPrIDRef="0"><hp:t>{text}</hp:t></hp:run></hp:p>'


def build_slot_hwpx(quote_style: str = "straight") -> bytes:
    """슬롯 문법이 든 최소 hwpx.

    일부러 네 가지를 한 문서에 담는다 — 안전한 픽스처는 어떤 구현으로도 통과해서
    검사가 무의미해지기 때문이다:

    1. **서식 인자가 붙은 슬롯** + 콜론 앞뒤 **줄맞춤 공백**(`제 목  : `)
    2. 인자 없는 슬롯 (그 자리 서식을 그대로 물려받아야 한다)
    3. **한 문단에 슬롯 둘** (`{'소속'} {'성명'}`)
    4. **따옴표 없는 중괄호** — 채울 자리가 아니라 값 안내다
    """
    open_q, close_q = _QUOTES[quote_style]

    def slot(name: str, extra: str = "") -> str:
        return "{" + open_q + name + close_q + extra + "}"

    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">'
        + _para("제 목  : " + slot("제목", ", 16pt, 맑은 고딕, 볼드"))
        + _para("작성자 : " + slot("작성자"))
        + _para("담당자 : " + slot("소속") + " " + slot("성명"))
        + _para("배포일 : {YYYY.MM.DD. (요일)}")
        + "</hs:sec>"
    )
    return _pack(section)


def _pack(section_xml: str) -> bytes:
    """섹션 XML 하나를 hwpx zip 으로 묶는다.

    `mimetype` 은 반드시 **무압축(STORED)** 이어야 한다 — OPC 규약이고, 압축하면
    한/글이 문서를 못 연다.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("Contents/section0.xml", section_xml.encode("utf-8"))
        zf.writestr("Contents/header.xml", '<?xml version="1.0" encoding="UTF-8"?><h/>')
    return buf.getvalue()
