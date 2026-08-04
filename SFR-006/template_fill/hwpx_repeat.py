"""반복 블록 — 문단 템플릿을 복제해 개수가 정해지지 않은 본문을 만든다.

누름틀 채우기(`hwpx_fields.fill_template`)는 **개수가 고정된** 필드를 채운다.
보도자료의 □/◦ 항목처럼 **개수가 입력에 따라 달라지는** 본문은 문단 자체를 늘려야
하는데, 그 조작이 이 모듈이다.

템플릿 문단 하나를 `deepcopy` 해 필요한 개수만큼 삽입하고 원본 템플릿 문단을 제거한다.
문단을 맨바닥에서 만들지 않으므로 `paraPrIDRef`·`charPrIDRef` 가 그대로 살아
서식이 보존된다 (CLAUDE.md §3.4 패턴).

`hwpx.py:expand_repeat_block` (로컬 검증 CLI) 의 이식판이다 — CLAUDE.md "남은 일" 항목.
원본은 보도자료 전용 CLI 라서 다음을 고쳤다:

- `raise SystemExit` → `TemplateError` (코드 서빙에서 프로세스를 죽일 수 없다)
- **spacer 오검출**: 원본은 다음 문단을 무조건 간격용으로 보고 **삭제**한다. 템플릿에
  실제 내용이 뒤따르면 그 문단이 사라진다 — 여기서는 **빈 문단일 때만** 인정한다.
- **run 이 쪼개진 토큰**: 원본은 XPath `contains(text(), …)` 로 찾아 `hp:t` 단위로
  치환하므로, 한/글이 `{{ma` + `in}}` 으로 쪼개 저장하면 조용히 안 채워진다.
  문단 텍스트를 이어붙여 판정하고, 쪼개진 경우 첫 `hp:t` 에 값을 넣고 나머지를 비운다.
- 한글 토큰: `TOKEN_RE` 를 `hwpx_fields` 것으로 통일했다(ASCII 전용 패턴 결함 수정).

`fill_template` 에 아직 연결하지 않았다 — `values["contents"]` 같은 입력 계약을
정한 뒤 붙인다. 지금은 독립 호출용이다.
"""

import io
import zipfile
from copy import deepcopy
from dataclasses import dataclass

from lxml import etree

from .hwpx_fields import HP_NS, NEWLINE_REPLACEMENT, TOKEN_RE, TemplateError
from .logging_utils import log_info, log_warning

_PARA = f"{{{HP_NS}}}p"
_TEXT = f"{{{HP_NS}}}t"

DEFAULT_MAIN_TOKEN = "{{main}}"
DEFAULT_DETAIL_TOKEN = "{{detail}}"


@dataclass
class RepeatResult:
    hwpx_bytes: bytes
    block_count: int          # 삽입된 블록 수
    skipped_blocks: int       # 본문이 비어 건너뛴 블록 수 (침묵 처리 금지)
    leftover_tokens: list     # 값이 없어 남은 {{token}}


def _normalize(value) -> str:
    text = str(value if value is not None else "")
    return text.replace("\r\n", "\n").replace("\n", NEWLINE_REPLACEMENT)


def _text_nodes(para) -> list:
    return list(para.iter(_TEXT))


def _paragraph_text(para) -> str:
    return "".join((node.text or "") for node in _text_nodes(para))


def _find_token_paragraph(root, token: str):
    """토큰을 포함한 첫 문단.

    XPath `contains(text(), …)` 대신 문단 텍스트를 이어붙여 판정한다 — run 이 쪼개진
    토큰도 찾고, 토큰에 따옴표가 들어가도 XPath 가 깨지지 않는다.
    """
    for para in root.iter(_PARA):
        if token in _paragraph_text(para):
            return para
    return None


def _replace_token(para, token: str, value: str) -> None:
    """문단 안의 토큰을 값으로 바꾼다.

    토큰이 `hp:t` 하나에 온전히 있으면 그 노드만 고쳐 부분 서식을 보존한다.
    쪼개져 있으면 첫 `hp:t` 에 치환 결과 전체를 넣고 나머지를 비운다(문단 서식은
    유지되고 문단 내 부분 서식만 첫 run 것으로 통일된다).
    """
    nodes = _text_nodes(para)
    if any(node.text and token in node.text for node in nodes):
        for node in nodes:
            if node.text and token in node.text:
                node.text = node.text.replace(token, value)
        return
    if not nodes:
        return
    nodes[0].text = _paragraph_text(para).replace(token, value)
    for node in nodes[1:]:
        node.text = ""


def _resolve_spacer(anchor):
    """anchor 다음 문단이 **빈 문단이면** 블록 사이 간격용으로 인정한다.

    원본 CLI 는 다음 문단을 무조건 간격용으로 보고 삭제해서, 템플릿에 실제 내용이
    뒤따르면 그 문단을 잃었다. 빈 문단만 인정해 그 사고를 막는다.
    """
    nxt = anchor.getnext()
    if nxt is None or nxt.tag != _PARA:
        return None
    return nxt if not _paragraph_text(nxt).strip() else None


def _normalize_blocks(blocks) -> list:
    """`["문단", …]` 또는 `[{"main":…, "detail":…}, …]` 를 dict 목록으로 정규화."""
    normalized = []
    for block in blocks or []:
        if isinstance(block, str):
            normalized.append({"main": block, "detail": ""})
        elif isinstance(block, dict):
            normalized.append(
                {"main": str(block.get("main", "")), "detail": str(block.get("detail") or "")}
            )
        else:
            raise TemplateError(
                "본문 블록 형식이 올바르지 않습니다. 문자열 또는 main/detail 항목이어야 합니다."
            )
    return normalized


def expand_repeat_blocks(
    root,
    blocks: list,
    main_token: str = DEFAULT_MAIN_TOKEN,
    detail_token: str = DEFAULT_DETAIL_TOKEN,
) -> tuple:
    """파싱된 섹션 root 에서 문단 템플릿을 blocks 개수만큼 복제 삽입한다.

    Returns:
        (삽입한 블록 수, 건너뛴 블록 수). 템플릿 문단이 없으면 (0, 0).
    """
    main_tpl = _find_token_paragraph(root, main_token)
    if main_tpl is None:
        return 0, 0

    detail_tpl = _find_token_paragraph(root, detail_token)
    spacer_tpl = _resolve_spacer(detail_tpl if detail_tpl is not None else main_tpl)

    parent = main_tpl.getparent()
    if parent is None:
        raise TemplateError("템플릿 본문 문단의 위치를 찾지 못했습니다.")
    position = parent.index(main_tpl)

    inserted = 0
    skipped = 0
    for block in blocks:
        if not block["main"].strip():
            skipped += 1  # 빈 본문은 문단을 만들지 않는다 (빈 줄만 늘어난다)
            continue

        main_para = deepcopy(main_tpl)
        _replace_token(main_para, main_token, _normalize(block["main"]))
        parent.insert(position, main_para)
        position += 1

        if block["detail"].strip() and detail_tpl is not None:
            detail_para = deepcopy(detail_tpl)
            _replace_token(detail_para, detail_token, _normalize(block["detail"]))
            parent.insert(position, detail_para)
            position += 1

        if spacer_tpl is not None:
            parent.insert(position, deepcopy(spacer_tpl))
            position += 1
        inserted += 1

    # 템플릿 문단 제거 — lxml 은 자식 없는 엘리먼트가 falsy 다. 반드시 `is not None`
    for template in (main_tpl, detail_tpl, spacer_tpl):
        if template is not None and template.getparent() is not None:
            template.getparent().remove(template)
    return inserted, skipped


def _fill_tokens(root, values: dict) -> None:
    """모든 hp:t 의 {{token}} 을 치환한다. 값이 없는 토큰은 건드리지 않는다."""
    for node in root.iter(_TEXT):
        if not node.text or "{{" not in node.text:
            continue
        text = node.text
        for name in set(TOKEN_RE.findall(text)):
            value = values.get(name)
            if value is None or isinstance(value, (list, dict)):
                continue
            text = text.replace("{{" + name + "}}", _normalize(value))
        node.text = text  # lxml 이 escape 를 자동 처리한다


def fill_with_repeat(
    hwpx_bytes: bytes,
    blocks,
    values: dict | None = None,
    *,
    main_token: str = DEFAULT_MAIN_TOKEN,
    detail_token: str = DEFAULT_DETAIL_TOKEN,
) -> RepeatResult:
    """반복 블록을 펼치고 `{{token}}` 을 채운 새 hwpx 바이트를 만든다.

    Args:
        hwpx_bytes: 본문 자리에 `{{main}}`(선택적으로 `{{detail}}`) 문단을 둔 템플릿.
        blocks: `["문단", …]` 또는 `[{"main": 제목, "detail": 설명}, …]`.
        values: 제목·날짜처럼 문단 밖 `{{token}}` 에 넣을 스칼라 값.

    Raises:
        TemplateError: hwpx 손상, 본문 섹션 없음, 본문 문단 표시 없음, blocks 형식 오류.
    """
    normalized_blocks = _normalize_blocks(blocks)
    scalars = {
        key: value
        for key, value in (values or {}).items()
        if not isinstance(value, (list, dict))
    }

    try:
        src = zipfile.ZipFile(io.BytesIO(hwpx_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise TemplateError("hwpx 파일이 아니거나 손상된 파일입니다.") from exc

    inserted = 0
    skipped = 0
    expanded = False
    leftover: set = set()
    with src:
        content_names = [
            name
            for name in src.namelist()
            if name.startswith("Contents/") and name.endswith(".xml")
        ]
        if not content_names:
            raise TemplateError("템플릿에서 hwpx 본문을 찾지 못했습니다.")

        roots: dict = {}
        for name in sorted(content_names):
            try:
                root = etree.fromstring(src.read(name))
            except etree.XMLSyntaxError as exc:
                raise TemplateError("템플릿 본문 XML 을 해석하지 못했습니다.") from exc
            roots[name] = root
            if not expanded:
                found = _find_token_paragraph(root, main_token) is not None
                inserted, skipped = expand_repeat_blocks(
                    root, normalized_blocks, main_token, detail_token
                )
                expanded = found
            _fill_tokens(root, scalars)

        if normalized_blocks and not expanded:
            raise TemplateError(
                "템플릿에 본문 문단 표시가 없습니다. 본문이 들어갈 문단에 "
                f"{main_token} 을 넣어 주세요."
            )

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                if item.filename in roots:
                    data = etree.tostring(
                        roots[item.filename], encoding="UTF-8", xml_declaration=True
                    )
                    # 남은 토큰은 **압축 전 XML** 에서 센다 (압축 바이트에서는 못 찾는다)
                    leftover.update(TOKEN_RE.findall(data.decode("utf-8", errors="ignore")))
                else:
                    data = src.read(item.filename)
                # mimetype 무압축 저장 규약 (§3.1)
                compress = (
                    zipfile.ZIP_STORED if item.filename == "mimetype" else zipfile.ZIP_DEFLATED
                )
                dst.writestr(item.filename, data, compress_type=compress)

    # 건수는 메시지 문자열에 끼워 넣지 않고 RepeatResult 로 돌려준다 —
    # 호출부가 자기 로깅 계약(3.8절 허용 필드)으로 기록한다.
    if skipped:
        log_warning("본문이 비어 건너뛴 블록이 있다 (건수는 RepeatResult.skipped_blocks)")
    if leftover:
        # 값이 없어 남은 토큰이 그대로 문서에 보인다 — 침묵 처리하지 않는다
        log_warning("값이 없어 남은 토큰이 있다 (목록은 RepeatResult.leftover_tokens)")
    log_info("반복 블록 펼치기 완료")
    return RepeatResult(
        hwpx_bytes=buffer.getvalue(),
        block_count=inserted,
        skipped_blocks=skipped,
        leftover_tokens=sorted(leftover),
    )
