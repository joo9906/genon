"""템플릿 항목을 다 채운 뒤 **본문을 더 이어 쓰는** 경로 (본문 블록).

왜 필요한가: 템플릿의 항목(라벨·누름틀·토큰)은 **개수가 고정**이다. 항목을 전부
채우고 나면 더 쓸 자리가 없어서 "그 아래에 추진 배경과 기대 효과도 넣어 달라" 같은
요구를 처리할 방법이 없었다. 본문 블록은 그 자리를 만든다 — 개수 제한이 없고,
서식은 템플릿에 이미 있는 문단에서 가져온다.

설계 원칙 — **서식 명세를 다시 해석하지 않는다. 템플릿 문단을 통째로 복제한다.**
    `제 목 : {볼드체, HY헤드라인M, 16pt}` 같은 명세를 파싱해 문단을 처음부터 조립하면
    글자 서식(charPr)만 재현되고 **문단 서식(paraPr — 여백·줄간격·정렬·들여쓰기)은
    재현되지 않는다.** 이 패키지에는 paraPr 을 만드는 코드가 아예 없고, 만든다면
    `itemCnt` 하나만 틀려도 한/글이 문서를 열지 못한다.
    반면 문단을 deepcopy 하면 `paraPrIDRef`·`charPrIDRef` 가 통째로 따라오므로
    파서가 모르는 속성까지 그대로 보존된다. **새로 만드는 서식 정의가 0개**라
    header.xml 을 건드리지 않는다 — 이 경로가 문서를 깨뜨릴 수 없는 이유다.

복제할 때 버리는 것 (안전장치의 핵심):
- `hp:secPr` 를 담은 run — 구역 정의가 복제되면 문서 구조가 깨진다. 실제 현장
  템플릿(`data/파워.hwpx`)의 첫 문단(`제 목 :`)이 정확히 이 경우다.
- `hp:ctrl`(누름틀)·`hp:tbl`(표)·그림·도형 등 **텍스트가 아닌 모든 것** — 표가 통째로
  복제되는 사고를 막는다. 판정은 화이트리스트다(`hp:t` 만 허용) — 모르는 제어 요소가
  나와도 자동으로 걸러진다. 블랙리스트였다면 새 요소를 만날 때마다 뚫린다.
- `hp:linesegarray` — 줄 배치 캐시. 글자 수가 달라졌으니 남기면 오히려 방해다.

표 셀 안 문단은 서식 원본으로 쓰지 않는다 (`nearest_para` 로 걸러낸다). 셀 폭 기준으로
잡힌 문단 모양을 본문에 붙이면 어긋난다.

이 모듈은 hwpx_fields 와 같은 성질을 유지한다 — **GenOS 런타임·Config 의존이 없다.**
입력 검증(개수·길이 상한, 화이트리스트)은 호출부(field_judge)가 하고, 여기서는
"주어진 블록을 결정적으로 문서에 넣는 일"만 한다.
"""

import io
import zipfile
from copy import deepcopy
from dataclasses import dataclass, field as dc_field

from lxml import etree

from .hwpx_fields import (
    HP_NS,
    TemplateError,
    collect_slot_occurrences,
    is_text_run,
    iter_section_xml,
    nearest_para,
    normalize_text,
    open_hwpx,
    own_nodes,
    parse_xml,
    serialize_part,
)
from .logging_utils import log_info, log_warning

_PARA = f"{{{HP_NS}}}p"
_RUN = f"{{{HP_NS}}}run"
_TEXT = f"{{{HP_NS}}}t"
_FIELD_BEGIN = f"{{{HP_NS}}}fieldBegin"


@dataclass(frozen=True)
class BodyBlock:
    """템플릿 항목 밖에 추가로 넣을 본문 한 덩어리.

    Attributes:
        text: 문서에 들어갈 내용. 줄바꿈이 있으면 **문단이 나뉜다** (한 줄 = 한 문단).
        style_ref: 서식을 가져올 템플릿 항목명 (`제목`, `주요 내용` 등).
            비었거나 템플릿에 없으면 기본 본문 서식으로 떨어지고, 그 사실을
            `BlockApplyResult.unknown_refs` 로 알린다 — 내용을 버리지는 않는다.
            서식 이름이 틀렸다고 사용자가 쓴 내용을 지우는 편이 더 나쁘다.
        raw_text: 톤(글다듬이) 적용 **전** 원문. 이 모듈은 쓰지 않고 그대로 실어 나른다 —
            항목 값의 `raw_values` 와 같은 역할이고(세션 저장·톤 재적용 근거),
            블록은 목록이라 값처럼 별도 dict 로 두면 인덱스가 어긋난다. 비어 있으면
            `text` 가 곧 원문이라는 뜻이다.
    """

    text: str
    style_ref: str = ""
    raw_text: str = ""


@dataclass
class BlockApplyResult:
    hwpx_bytes: bytes
    appended: int             # 실제로 삽입한 문단 수 (블록 수가 아니다 — 줄바꿈으로 나뉜다)
    unknown_refs: list = dc_field(default_factory=list)  # 대응 문단을 못 찾은 style_ref
    anchor: str = ""          # 삽입 기준 (빈 값이면 문서 끝)


def _clone_for_text(para, text: str, keep_run=None):
    """문단을 복제해 텍스트만 갈아 끼운다. 복제할 수 없는 문단이면 None.

    `paraPrIDRef`(여백·줄간격·정렬)와 남긴 run 의 `charPrIDRef`(글꼴·크기·굵기)가
    그대로 따라온다 — 서식을 계산하지 않고 물려받는 것이 이 모듈의 요지다.

    Args:
        keep_run: 남길 run 을 지정한다 (원본 문단의 자식). **슬롯 문단에서 반드시
            필요하다** — `제 목 : {'제목', 16pt}` 는 서식 단계를 거치면 run 이 둘로
            갈리고, 16pt 는 **뒤쪽(슬롯) run** 에 걸린다. 첫 run 을 집으면 제목 서식이
            아니라 라벨 서식을 복제하게 된다. 지정하지 않거나 복제 불가능한 run 이면
            첫 텍스트 run 으로 떨어진다.
    """
    keep_index = None
    if keep_run is not None:
        for index, child in enumerate(para):
            if child is keep_run:
                keep_index = index
                break

    clone = deepcopy(para)
    children = list(clone)
    keeper = None
    if keep_index is not None and keep_index < len(children):
        candidate = children[keep_index]
        if candidate.tag == _RUN and is_text_run(candidate):
            keeper = candidate
    for child in children:
        if child is keeper:
            continue
        if keeper is None and child.tag == _RUN and is_text_run(child):
            keeper = child
            continue
        # 텍스트가 아닌 run, 남기기로 한 것 외의 run, linesegarray 등은 전부 버린다
        clone.remove(child)
    if keeper is None:
        return None

    texts = keeper.findall(_TEXT)
    if texts:
        texts[0].text = text
        for extra in texts[1:]:
            keeper.remove(extra)
    else:
        etree.SubElement(keeper, _TEXT).text = text
    return clone


def _is_top_level(para) -> bool:
    """구역(sec) 바로 아래 문단인가 — 표 셀·머리말 안 문단을 걸러낸다."""
    return nearest_para(para) is None


def _top_level_paras(root) -> list:
    """구역(sec) 바로 아래 문단 목록. 문서 간 위치 대조의 기준이다."""
    return [child for child in root if child.tag == _PARA]


def _slot_run(para, occ):
    """슬롯 글자가 들어 있는 run — 서식 단계가 charPr 을 걸어 둔 그 run.

    서식을 거친 템플릿에서 슬롯은 자기 run 을 갖는다. 그 run 을 집어야 블록이
    라벨(`제 목 : `)이 아니라 **값의 서식**을 물려받는다.
    """
    cursor = 0
    for node in own_nodes(para, _TEXT):
        length = len(node.text or "")
        if cursor <= occ.start < cursor + length:
            run = node.getparent()
            return run if is_text_run(run) else None
        cursor += length
    return None


def _anchor_paragraphs(root) -> dict:
    """{항목명: (문단, 복제할 run)} — 서식 원본으로 쓸 수 있는 최상위 문단.

    슬롯이 우선이고 누름틀은 보완이다. 인식 규칙은 채우기와 **같은 함수**를 쓴다 —
    파서를 두 벌로 두면 대화가 제시하는 서식 목록과 실제로 복제되는 문단이 어긋난다.
    """
    anchors: dict = {}
    for occ in collect_slot_occurrences(root):
        para = occ.para
        if para is None or not _is_top_level(para) or occ.name in anchors:
            continue
        keeper = _slot_run(para, occ)
        if _clone_for_text(para, "", keeper) is None:
            continue
        anchors[occ.name] = (para, keeper)

    for begin in root.iter(_FIELD_BEGIN):
        name = (begin.get("name") or "").strip()
        if not name or name in anchors:
            continue
        para = nearest_para(begin)
        if para is None or not _is_top_level(para):
            continue
        if _clone_for_text(para, "") is None:
            continue
        anchors[name] = (para, None)
    return anchors


def _has_own_text(para) -> bool:
    return any((node.text or "").strip() for node in own_nodes(para, _TEXT))


def _default_paragraph(roots: list, anchors: dict):
    """`style_ref` 를 못 찾았을 때 쓸 기본 본문 문단.

    고르는 순서에 근거가 있다:
    1. **항목이 아닌, 글자가 있는 문단** — 템플릿에 이미 있는 '평범한 본문' 이다.
    2. 없으면 마지막 항목 문단. 현장 템플릿은 본문이 전부 `항목: {명세}` 라 여기 걸린다.
    3. 그래도 없으면 복제 가능한 아무 최상위 문단.

    빈 문단을 우선하지 않는 이유: 실제 템플릿의 빈 줄은 `여백: (5pt)` 처럼 **간격용**
    이라 그 서식을 물려받으면 본문이 5pt 로 나온다.
    """
    anchor_ids = {id(para) for para, _ in anchors.values()}
    fallback = None
    for root in reversed(roots):
        for para in reversed(_top_level_paras(root)):
            if _clone_for_text(para, "") is None:
                continue
            if fallback is None:
                fallback = para
            if id(para) in anchor_ids:
                continue
            if _has_own_text(para):
                return para
    if anchors:
        return list(anchors.values())[-1][0]
    return fallback


def _prepare(blocks) -> list:
    """입력을 (style_ref, 한 줄 텍스트) 목록으로 편다.

    블록 텍스트의 줄바꿈은 **문단 분리**로 본다. `<hp:t>` 안의 `\\n` 은 한/글에서
    줄바꿈이 아니라 그냥 글자라(hwpx_fields.normalize_text 참고), 한 문단에 몰아넣으면
    한 줄로 붙어 버린다.
    """
    prepared: list = []
    for item in blocks or ():
        if isinstance(item, BodyBlock):
            text, style_ref = item.text, item.style_ref
        elif isinstance(item, dict):
            text, style_ref = item.get("text"), item.get("style_ref")
        else:
            text, style_ref = item, ""
        raw = str(text if text is not None else "")
        style_ref = str(style_ref or "").strip()
        for line in raw.replace("\r\n", "\n").split("\n"):
            cleaned = normalize_text(line).strip()
            if cleaned:
                prepared.append((style_ref, cleaned))
    return prepared


def block_style_names(hwpx_bytes: bytes) -> list:
    """블록 서식으로 지정할 수 있는 항목명 (문서 등장 순서).

    대화 프롬프트의 화이트리스트이자 화면의 선택지가 된다.

    Raises:
        TemplateError: ZIP/XML 손상.
    """
    names: list = []
    for _, xml_bytes in iter_section_xml(hwpx_bytes):
        root = parse_xml(xml_bytes)
        for name in _anchor_paragraphs(root):
            if name not in names:
                names.append(name)
    return names


def _resolve_anchor(sections: dict, positions: dict, name: str):
    """삽입 기준 문단을 **대상 문서에서** 찾는다 (위치로 짚는다).

    이름으로 다시 찾을 수 없다 — 값을 채운 문서에는 `{'제목', …}` 이 남아 있지 않다.
    채우기·서식은 문단을 더하거나 빼지 않으므로 (엔트리, 최상위 문단 순번) 은 그대로다.
    """
    position = positions.get(name)
    if position is None:
        return None
    entry, index = position
    root = sections.get(entry)
    if root is None:
        return None
    paragraphs = _top_level_paras(root)
    return paragraphs[index] if 0 <= index < len(paragraphs) else None


def _load_style_source(hwpx_bytes: bytes) -> tuple:
    """서식 원본을 뜰 문서를 읽어 {항목명: (문단, run)} 과 위치표를 만든다.

    Returns:
        (roots, anchors, positions) — `roots` 는 **붙들고 있어야 한다.** 놓으면 lxml
        프록시가 회수되면서 anchors 가 가리키는 요소가 무효가 된다.
        `positions` 는 {항목명: (엔트리명, 최상위 문단 인덱스)} 로, 삽입 기준 문단을
        **다른 문서(값을 채운 결과물)에서** 같은 자리로 찾아가는 데 쓴다.
    """
    roots: list = []
    anchors: dict = {}
    positions: dict = {}
    for entry, xml_bytes in iter_section_xml(hwpx_bytes):
        root = parse_xml(xml_bytes)
        roots.append(root)
        order = {id(para): index for index, para in enumerate(_top_level_paras(root))}
        for name, (para, keeper) in _anchor_paragraphs(root).items():
            if name in anchors:
                continue
            anchors[name] = (para, keeper)
            if id(para) in order:
                positions[name] = (entry, order[id(para)])
    return roots, anchors, positions


def append_blocks(
    hwpx_bytes: bytes,
    blocks,
    *,
    after: str = "",
    style_source: bytes | None = None,
) -> BlockApplyResult:
    """본문 블록을 문서에 삽입한 새 hwpx 바이트를 만든다.

    Args:
        blocks: BodyBlock 목록 (dict 도 허용 — 세션 JSON 에서 그대로 온다).
        after: 삽입 기준 항목명. 그 항목의 문단 **바로 뒤**에 차례로 넣는다.
            비우면 문서 맨 끝에 붙인다. 서명란처럼 마지막에 고정돼야 하는 문단이
            있는 템플릿은 이 값으로 위치를 지정한다.
        style_source: 서식을 복제해 올 원본 문서. **슬롯 문법에서는 필수다** —
            `hwpx_bytes` 는 이미 값을 채운 문서라 `{'제목', 16pt}` 가 사라져 있고,
            그러면 어느 문단이 '제목' 이었는지 알 수 없다. 그래서 서식을 거친 템플릿을
            따로 넘긴다. 생략하면 자기 자신에서 찾는다(누름틀 템플릿·단위 점검용).

    Raises:
        TemplateError: ZIP/XML 손상, 또는 본문이 없어 붙일 자리가 없는 경우.
    """
    prepared = _prepare(blocks)
    if not prepared:
        return BlockApplyResult(hwpx_bytes, 0)

    sections: dict = {}
    for name, xml_bytes in iter_section_xml(hwpx_bytes):
        sections[name] = parse_xml(xml_bytes)
    if not sections:
        raise TemplateError("템플릿에 본문이 없어 내용을 추가할 수 없습니다.")

    # 서식 원본은 문서 전체에서 찾는다 (문단 서식 id 는 header.xml 에 있어 구역을 가리지
    # 않는다). 삽입은 한 구역에서만 한다. source_roots 는 프록시 유지용으로 붙든다.
    source_roots, anchors, positions = _load_style_source(
        hwpx_bytes if style_source is None else style_source
    )
    default_para = _default_paragraph(source_roots, anchors)

    after_name = (after or "").strip()
    anchor_para = _resolve_anchor(sections, positions, after_name) if after_name else None
    if after_name and anchor_para is None:
        log_warning(
            "블록 삽입 기준 항목을 찾지 못해 문서 끝에 붙인다",
            event="blocks_anchor_missing",
            resource_id=after_name,
        )

    # 서식을 지정하지 않은 블록은 삽입 기준 항목의 모양을 따른다 (예전과 같은 규칙).
    fallback = anchors.get(after_name) if after_name else None
    if fallback is None:
        fallback = (default_para, None)

    unknown: list = []
    clones: list = []
    for style_ref, text in prepared:
        source, keeper = anchors.get(style_ref, (None, None)) if style_ref else (None, None)
        if style_ref and source is None and style_ref not in unknown:
            unknown.append(style_ref)
        if source is None:
            source, keeper = fallback
        if source is None:
            raise TemplateError("템플릿에서 서식을 가져올 문단을 찾지 못했습니다.")
        clone = _clone_for_text(source, text, keeper)
        if clone is None:
            # _anchor_paragraphs / _default_paragraph 가 이미 복제 가능성을 확인하므로
            # 여기 걸리면 앵커 선정 규칙이 깨진 것이다 — 조용히 넘기지 않는다.
            raise TemplateError("템플릿에서 서식을 가져올 문단을 찾지 못했습니다.")
        clones.append(clone)

    if anchor_para is not None:
        parent = anchor_para.getparent()
        start = parent.index(anchor_para) + 1
        for offset, clone in enumerate(clones):
            parent.insert(start + offset, clone)
    else:
        target = list(sections.values())[-1]
        for clone in clones:
            target.append(clone)

    rendered = {name: serialize_part(root) for name, root in sections.items()}

    buf = io.BytesIO()
    with open_hwpx(hwpx_bytes) as src, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = rendered.get(item.filename) or src.read(item.filename)
            dst.writestr(
                item.filename,
                data,
                # mimetype 무압축 규약 (§3.1) — 채우기·서식 경로와 같은 규칙
                compress_type=(
                    zipfile.ZIP_STORED if item.filename == "mimetype" else zipfile.ZIP_DEFLATED
                ),
            )

    log_info(
        "본문 블록 삽입 완료",
        event="blocks_appended",
        item_count=len(clones),
        status=f"anchor={'end' if anchor_para is None else after_name} unknown_ref={len(unknown)}",
    )
    if unknown:
        # 서식 이름이 틀리면 기본 서식으로 들어간다 — 조용히 넘기면 사용자는 지정한
        # 서식이 적용된 줄 안다 (침묵 처리 금지 규약).
        log_warning(
            "블록 서식 항목을 찾지 못해 기본 본문 서식을 적용했다",
            event="blocks_style_unmatched",
            item_count=len(unknown),
        )
    return BlockApplyResult(
        hwpx_bytes=buf.getvalue(),
        appended=len(clones),
        unknown_refs=unknown,
        anchor="" if anchor_para is None else after_name,
    )
