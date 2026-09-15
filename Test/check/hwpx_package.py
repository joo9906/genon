"""점검용 hwpx 픽스처를 **온전한 OPC 패키지**로 감싸는 공용 헬퍼.

## 왜 생겼나

점검 스크립트 셋(`check_api_contract`·`check_body_blocks`·`check_output_safety`)이 각자
`mimetype` + `header.xml` + `section0.xml` 세 항목짜리 zip 을 만들고 있었다. 그것으로도
파서·직렬화기는 잴 수 있었지만 **온전한 hwpx 가 아니다** — `META-INF/container.xml` 과
manifest(`Contents/content.hpf`)가 없다.

2026-08-10 에 개봉 안전 검사기가 pip 의존에서 벤더 사본으로 바뀌면서 게이트가 **항상**
돌게 됐고, 그 세 픽스처가 전부 정당하게 거절됐다. `/generate` 는 운영 경로라 게이트를
끌 수 없으므로(끄면 그 점검이 검증하려던 계약 자체가 사라진다) **픽스처를 온전하게
만드는 쪽이 답이다.**

세 곳에 같은 OPC 뼈대를 복사하면 그게 곧 사본 드리프트라, 여기 한 벌만 둔다.
`onprem/test/` 는 배포 단위 **바깥**이므로 이미지에 흘러가지 않는다.

## 무엇을 해 주고 무엇을 안 해 주나

**해 준다** — 패키지 수준의 형식: container/manifest/version/preview 파트, `mimetype` 을
첫 항목·STORED 로 두기, `hh:head` 에 `version`·`secCnt` 채우기(검사기가 요구하는데 점검
픽스처는 관심사가 아니라 안 적어 왔다).

**안 해 준다** — 본문 내용의 결함. 특히 **표의 필수 자식**(`hp:sz`·`hp:pos`·`hp:outMargin`·
`hp:inMargin`, 셀의 `cellSpan`·`cellSz`·`cellMargin`)은 여기서 채우지 않는다. 그것이
빠진 문서는 한/글이 실제로 거절하고, 검사기가 그걸 잡는 것이 맞다 — 헬퍼가 조용히
채워 주면 **검사기가 잡아야 할 결함을 픽스처가 감추게 된다.** 필요한 픽스처가 직접 적는다.
"""

import io
import zipfile

from lxml import etree

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
OPF = "http://www.idpf.org/2007/opf/"
OCF = "urn:oasis:names:tc:opendocument:xmlns:container"

DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'

MIMETYPE = "mimetype"
CONTAINER = "META-INF/container.xml"
MANIFEST = "Contents/content.hpf"
HEADER = "Contents/header.xml"
VERSION = "version.xml"
PREVIEW = "Preview/PrvText.txt"

_CONTAINER_XML = f"""{DECL}
<ocf:container xmlns:ocf="{OCF}">
  <ocf:rootfiles>
    <ocf:rootfile full-path="{MANIFEST}" media-type="application/hwpml-package+xml"/>
  </ocf:rootfiles>
</ocf:container>
"""

_VERSION_XML = f"""{DECL}
<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="1" buildNumber="0" os="1" xmlVersion="1.5" application="Hancom Office Hangul" appVersion="fixture"/>
"""


def _manifest_xml(section_names: list) -> str:
    """OPF manifest + spine.

    검사기는 spine 으로 header/section 을 풀고 풀린 section 개수를 `hh:head@secCnt` 와
    대조한다 — 그 대조가 이 뼈대의 핵심이라 section 목록을 인자로 받는다.
    """
    items = [
        '    <opf:item id="header" href="header.xml" media-type="application/xml"/>',
        '    <opf:item id="version" href="../version.xml" media-type="application/xml"/>',
        '    <opf:item id="prvtext" href="../Preview/PrvText.txt" media-type="text/plain"/>',
    ]
    refs = ['    <opf:itemref idref="header" linear="yes"/>']
    for index, name in enumerate(section_names):
        base = name.rsplit("/", 1)[-1]
        items.append(
            f'    <opf:item id="section{index}" href="{base}" media-type="application/xml"/>'
        )
        refs.append(f'    <opf:itemref idref="section{index}" linear="yes"/>')
    return f"""{DECL}
<opf:package xmlns:opf="{OPF}" xmlns:dc="http://purl.org/dc/elements/1.1/" version="" unique-identifier="" id="">
  <opf:metadata><dc:title>fixture</dc:title></opf:metadata>
  <opf:manifest>
{chr(10).join(items)}
  </opf:manifest>
  <opf:spine>
{chr(10).join(refs)}
  </opf:spine>
</opf:package>
"""


def _normalize_header(header_xml: str, section_count: int) -> bytes:
    """`hh:head` 에 `version`·`secCnt` 를 채운다 (이미 있으면 그대로 둔다).

    검사기는 둘 다 요구하는데(상류 XSD 가 `use="required"` 로 단언하던 것), 점검 픽스처는
    charPr 목록에만 관심이 있어 지금껏 적지 않았다. 여기서 채우는 편이, 픽스처마다
    관심사와 무관한 속성을 적게 하는 것보다 낫다.
    """
    root = etree.fromstring(header_xml.encode("utf-8"))
    if not (root.get("version") or "").strip():
        root.set("version", "1.5")
    if not (root.get("secCnt") or "").strip():
        root.set("secCnt", str(section_count))
    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )


def build(section_xml: str, header_xml: str, *, extra_sections: dict | None = None) -> bytes:
    """본문·서식 XML 을 온전한 OPC 패키지로 감싼다.

    Args:
        section_xml: `Contents/section0.xml` 이 될 XML 문자열.
        header_xml: `Contents/header.xml` 이 될 XML 문자열. `version`·`secCnt` 는
            없으면 채워 준다.
        extra_sections: `{"Contents/section1.xml": xml}` 같은 추가 본문. `secCnt` 대조가
            깨지지 않게 manifest spine 에도 함께 등록된다.

    Returns:
        hwpx 바이트. `mimetype` 이 첫 항목이고 STORED 다 (둘 다 검사기가 본다).
    """
    sections = {"Contents/section0.xml": section_xml}
    sections.update(extra_sections or {})
    ordered = sorted(sections)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        # mimetype 은 반드시 첫 항목이고 압축하지 않는다 (OPC 계약).
        archive.writestr(MIMETYPE, "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr(VERSION, _VERSION_XML)
        archive.writestr(CONTAINER, _CONTAINER_XML)
        archive.writestr(MANIFEST, _manifest_xml(ordered))
        archive.writestr(HEADER, _normalize_header(header_xml, len(ordered)))
        for name in ordered:
            archive.writestr(name, sections[name].encode("utf-8"))
        archive.writestr(PREVIEW, "fixture")
    return buffer.getvalue()
