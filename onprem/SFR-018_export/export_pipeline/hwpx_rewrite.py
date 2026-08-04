"""원본 hwpx 되쓰기 — 문단 텍스트만 교체하고 구조는 코드가 보존한다.

SFR-018 글다듬이·번역 산출물을 **원본 문서에 되쓰기** 위한 코어. 새 문서를 만들지 않는다.

## LLM 에는 XML 을 주지 않는다

`extract_paragraphs()` 가 문단 평문 배열을 내고, LLM 은 그 텍스트만 본다.
`rewrite_paragraphs()` 가 결과를 같은 노드에 되쓴다. XML 은 이 파일만 만진다 —
`charPrIDRef`·`itemCnt` 처럼 한 글자만 틀려도 문서가 열리지 않는 값을 LLM 에 맡기지
않는다는 결정(CLAUDE.md 의 SFR-006 서식 명세 절과 같은 원칙). 토큰 낭비보다 이쪽이
훨씬 위험하다.

## 되쓰기 전략 (SFR-006 `_write_occurrence` 와 동일, 대상 범위만 다름)

문단의 **첫 `hp:t` 에 값을 넣고 같은 문단의 나머지 `hp:t` 를 비운다.** run 을 새로
만들지 않으므로 `charPrIDRef` 가 그대로 살아 문단·문자 서식이 보존된다.
다른 점은 범위다 — 누름틀(`fieldBegin`~`fieldEnd`) 이 아니라 **문단(`hp:p`) 전체**다.

대가: 한 문단 안에서 **일부만 굵게/색**이던 부분 서식은 첫 run 서식으로 통일된다.
번역은 길이가 완전히 달라져 run 별 재분배가 불가능하므로 이 손실을 택했다(2026-08-04 결정).
손실은 숨기지 않고 `style_simplified_indexes` 로 돌려준다.

표는 이 방식이 마크다운 왕복보다 안전하다 — `hp:tc` 안의 문단을 자연히 집으므로
표 구조(병합셀 포함)를 아예 건드리지 않는다 (CLAUDE.md §3.5 의 병합셀 훼손 문제 회피).

배포 단위 간 import 금지 규칙 때문에 SFR-006 코드를 import 하지 않는다.
"""

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field as dc_field

from lxml import etree

from export_pipeline.logging_utils import log_info, log_warning

# hp 네임스페이스는 태그 식별자다 — 네트워크 주소가 아니므로 폐쇄망에서 접속하지 않는다
# (CLAUDE.md §3.1)
HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_PARA = f"{{{HP_NS}}}p"
_TEXT = f"{{{HP_NS}}}t"

# 본문은 Contents/sectionN.xml 이다 (§3.1). header.xml 등 다른 Contents 엔트리는
# 서식 정의라 되쓰기 대상이 아니고, 건드리면 문서가 깨진다.
_SECTION_RE = re.compile(r"^Contents/section(\d+)\.xml$")

# <hp:t> 안의 \n 은 문단 분리가 아니다 — 그대로 넣으면 한/글에서 깨져 보인다
NEWLINE_REPLACEMENT = " "


class HwpxExportError(ValueError):
    """되쓰기 입력이 계약에 맞지 않음 (hwpx 손상, 지문 불일치 등).

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다. 호출부가
    사용자 노출 오류로 그대로 쓸 수 있어야 하므로 내부 예외 원문을 넣지 않는다.
    """


@dataclass
class Paragraph:
    """되쓰기 단위 = 문단 하나. index 는 문서 순서(0-based)."""

    index: int
    text: str
    section: str
    # 내부용 — 되쓸 lxml 노드. 추출 전용 경로에서도 채워지지만 응답에 싣지 않는다.
    text_nodes: list = dc_field(default_factory=list, repr=False)


@dataclass
class RewriteResult:
    hwpx_bytes: bytes
    paragraph_count: int
    rewritten_indexes: list         # 실제로 값이 기록된 문단
    unchanged_indexes: list         # 값이 원문과 같아 건드리지 않은 문단
    unknown_indexes: list           # 원본에 없는 index (호출부 오류 — 침묵 처리 금지)
    style_simplified_indexes: list  # 부분 서식이 첫 run 서식으로 통일된 문단


def fingerprint(hwpx_bytes: bytes) -> str:
    """되쓰기 대상 문서의 지문.

    문단 index 는 **문서 순서에서 파생**되므로 추출과 되쓰기가 같은 바이트여야 한다.
    사용자가 중간에 문서를 고치면 index 가 밀려 엉뚱한 문단에 값이 들어가는데, 그건
    조용히 망가지는 실패다 — 지문을 대조해 그 전에 막는다.
    """
    return hashlib.sha256(hwpx_bytes).hexdigest()


def _normalize_value(value) -> str:
    text = str(value if value is not None else "")
    return text.replace("\r\n", "\n").replace("\n", NEWLINE_REPLACEMENT)


def _open(hwpx_bytes: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(hwpx_bytes), "r")
    except zipfile.BadZipFile as exc:
        # hwpx 가 아닌 파일 업로드는 내부 오류가 아니라 입력 오류다
        raise HwpxExportError("hwpx 파일이 아니거나 손상된 파일입니다.") from exc


def _section_names(zf: zipfile.ZipFile) -> list:
    """본문 섹션을 **번호 순서**로 돌려준다.

    문자열 정렬은 section10 을 section2 보다 앞에 두므로 index 가 문서 순서와
    어긋난다 — 숫자로 정렬한다.
    """
    numbered = []
    for name in zf.namelist():
        matched = _SECTION_RE.match(name)
        if matched:
            numbered.append((int(matched.group(1)), name))
    if not numbered:
        raise HwpxExportError("hwpx 본문(section)을 찾지 못했습니다. hwpx 파일인지 확인해 주세요.")
    return [name for _, name in sorted(numbered)]


def _parse(xml_bytes: bytes):
    try:
        return etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise HwpxExportError("문서 본문 XML 을 해석하지 못했습니다.") from exc


def _nearest_paragraph(elem):
    """가장 가까운 조상 hp:p.

    표 셀 안 문단(`hp:tbl` > `hp:tc` > `hp:subList` > `hp:p`)이 있으므로 `hp:p` 를
    순회하면 겉 문단과 셀 문단이 같은 텍스트를 두 번 집는다. 텍스트 노드에서
    거꾸로 올라가 **가장 가까운** 문단에만 귀속시켜야 중복이 없다.
    """
    parent = elem.getparent()
    while parent is not None:
        if parent.tag == _PARA:
            return parent
        parent = parent.getparent()
    return None


def _collect(root, section: str, start_index: int) -> list:
    """섹션 하나의 문단을 문서 순서로 수집한다.

    **빈 문단은 index 를 받지 않는다** — LLM 에 보낼 것도 없고, 되쓸 것도 없다.
    추출·되쓰기가 같은 함수를 쓰므로 양쪽 index 가 자동으로 일치한다.
    """
    groups: dict = {}
    order: list = []
    for node in root.iter(_TEXT):
        para = _nearest_paragraph(node)
        if para is None:
            continue  # 문단 밖 텍스트 — 되쓰기 대상이 아니다
        key = id(para)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(node)

    collected = []
    index = start_index
    for key in order:
        nodes = groups[key]
        text = "".join((node.text or "") for node in nodes)
        if not text.strip():
            continue
        collected.append(Paragraph(index=index, text=text, section=section, text_nodes=nodes))
        index += 1
    return collected


def _load(hwpx_bytes: bytes) -> tuple:
    """(zip, {섹션명: root}, [Paragraph]) — 추출·되쓰기 공통 1단계."""
    src = _open(hwpx_bytes)
    roots: dict = {}
    paragraphs: list = []
    index = 0
    for name in _section_names(src):
        root = _parse(src.read(name))
        roots[name] = root
        found = _collect(root, name, index)
        paragraphs.extend(found)
        index += len(found)
    return src, roots, paragraphs


def extract_paragraphs(hwpx_bytes: bytes) -> dict:
    """LLM 에 넘길 문단 평문 배열을 낸다 (XML 은 넘기지 않는다).

    Returns:
        {"fingerprint": str, "paragraph_count": int,
         "paragraphs": [{"index": int, "text": str, "section": str}, …]}

    Raises:
        HwpxExportError: hwpx 손상, 본문 섹션 없음.
    """
    src, _roots, paragraphs = _load(hwpx_bytes)
    with src:
        pass
    log_info(
        "원본 문단 추출 완료",
        event="paragraphs_extracted",
        item_count=len(paragraphs),
    )
    return {
        "fingerprint": fingerprint(hwpx_bytes),
        "paragraph_count": len(paragraphs),
        "paragraphs": [
            {"index": p.index, "text": p.text, "section": p.section} for p in paragraphs
        ],
    }


def _as_mapping(segments) -> dict:
    """[{"index":n,"text":…}] 또는 {n: text} 를 {int: str} 로 정규화한다."""
    if isinstance(segments, dict):
        items = segments.items()
    else:
        try:
            items = [(seg["index"], seg.get("text")) for seg in segments]
        except (TypeError, KeyError, AttributeError) as exc:
            raise HwpxExportError(
                "되쓸 문단 목록 형식이 올바르지 않습니다. index 와 text 를 가진 항목이어야 합니다."
            ) from exc
    normalized: dict = {}
    for key, value in items:
        try:
            normalized[int(key)] = _normalize_value(value)
        except (TypeError, ValueError) as exc:
            raise HwpxExportError("문단 번호(index)는 정수여야 합니다.") from exc
    return normalized


def _write_paragraph(para: Paragraph, value: str) -> bool:
    """첫 hp:t 에 값을 넣고 나머지를 비운다. 부분 서식이 통일됐으면 True."""
    nodes = para.text_nodes
    simplified = any((node.text or "").strip() for node in nodes[1:])
    nodes[0].text = value
    for node in nodes[1:]:
        node.text = ""
    return simplified


def rewrite_paragraphs(
    hwpx_bytes: bytes,
    segments,
    *,
    expected_fingerprint: str | None = None,
) -> RewriteResult:
    """문단 텍스트를 되쓴 새 hwpx 바이트를 만든다.

    값이 원문과 같은 문단은 **건드리지 않는다** — 굳이 써봐야 부분 서식만 잃는다.
    글다듬이는 상당수 문단을 그대로 두므로 이 한 줄이 서식 손실을 크게 줄인다.

    Args:
        hwpx_bytes: 원본 hwpx. `extract_paragraphs` 에 넣은 것과 **같은 바이트**여야 한다.
        segments: `[{"index": int, "text": str}, …]` 또는 `{index: text}`.
        expected_fingerprint: `extract_paragraphs` 가 준 지문. 주면 대조한다.

    Raises:
        HwpxExportError: hwpx 손상, 지문 불일치, segments 형식 오류.
    """
    if expected_fingerprint and expected_fingerprint != fingerprint(hwpx_bytes):
        # 원본이 바뀌면 index 가 밀려 엉뚱한 문단에 값이 들어간다 — 쓰기 전에 막는다
        log_warning("원본 문서 지문 불일치", event="fingerprint_mismatch")
        raise HwpxExportError(
            "다듬기에 사용한 원본 문서와 다른 파일입니다. 같은 문서를 올려 주세요."
        )

    values = _as_mapping(segments)
    src, roots, paragraphs = _load(hwpx_bytes)

    rewritten: list = []
    unchanged: list = []
    simplified: list = []
    known: set = set()

    with src:
        for para in paragraphs:
            known.add(para.index)
            if para.index not in values:
                continue
            value = values[para.index]
            if value == para.text:
                unchanged.append(para.index)
                continue
            if _write_paragraph(para, value):
                simplified.append(para.index)
            rewritten.append(para.index)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                if item.filename in roots:
                    data = etree.tostring(
                        roots[item.filename], encoding="UTF-8", xml_declaration=True
                    )
                else:
                    data = src.read(item.filename)
                # mimetype 은 무압축 저장 규약 (§3.1)
                compress = (
                    zipfile.ZIP_STORED
                    if item.filename == "mimetype"
                    else zipfile.ZIP_DEFLATED
                )
                dst.writestr(item.filename, data, compress_type=compress)

    unknown = sorted(index for index in values if index not in known)
    if unknown:
        # 호출부가 잘못된 index 를 보낸 것이다. 조용히 버리면 "번역이 일부 빠진" 문서가
        # 정상처럼 나간다 (실패 침묵 처리 금지 컨벤션).
        log_warning(
            "원본에 없는 문단 번호가 있어 기록하지 않았다",
            event="unknown_paragraph_index",
            item_count=len(unknown),
        )
    log_info(
        "원본 문단 되쓰기 완료",
        event="paragraphs_rewritten",
        item_count=len(rewritten),
        status="styled_simplified" if simplified else "style_preserved",
    )
    return RewriteResult(
        hwpx_bytes=buffer.getvalue(),
        paragraph_count=len(paragraphs),
        rewritten_indexes=rewritten,
        unchanged_indexes=unchanged,
        unknown_indexes=unknown,
        style_simplified_indexes=simplified,
    )
