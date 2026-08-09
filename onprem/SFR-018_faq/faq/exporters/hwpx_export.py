"""FAQ → hwpx — **관리자가 등록한 FAQ 템플릿의 반복 블록을 복제해서** 만든다.

## 왜 백지에서 만들지 않는가

hwpx 를 처음부터 조립하려면 `header.xml` 의 `charPr`·`paraPr`·`fontface` 목록과
`itemCnt` 를 손으로 맞춰야 한다. **한 글자만 틀려도 한/글이 문서를 열지 못하고**,
이 저장소에는 그걸 확인할 한/글이 없다. SFR-006 이 서식 XML 조작을 코드가 직접 하되
반드시 **원본 서식을 복제**해서 하는 것도 같은 이유다.

그래서 관리자가 사내 FAQ 서식으로 만든 hwpx 를 볼륨에 두면, 그 문서의 문단을
`deepcopy` 해서 항목 수만큼 늘린다. 서식은 관리자가 한/글에서 정한 그대로 나온다.

**템플릿이 없으면 hwpx 다운로드를 미지원(501)으로 알린다.** 빈 문서나 서식 없는
문서를 만들어 내려주지 않는다 — 가짜 산출물을 만들 수 있게 열어 두면 그게 운영에
흘러간다(SFR-006 PDF 규약과 같은 판단).

## 템플릿 작성 규약

반복 블록에 쓰는 토큰 (한/글에서 **한 번에 타이핑**할 것 — 서식이 섞여 run 이
쪼개져도 이 코드가 문단 단위로 이어 붙여 처리하지만, 문단을 넘어가면 못 잡는다):

    {{question}}   질문       (필수 — 이 토큰이 있는 문단이 반복 블록의 시작이다)
    {{answer}}     답변       (선택)
    {{evidence}}   근거 원문  (선택. 요구사항 §2 가 근거 명시를 요구하므로 넣기를 권장)

문서 어디서든 쓸 수 있는 스칼라 토큰:

    {{title}}  문서 제목    {{count}}  FAQ 개수    {{date}}  생성일

반복 블록 = `{{question}}` 문단부터 마지막 반복 토큰 문단까지 + 바로 뒤 빈 문단(있으면
항목 사이 간격으로 함께 복제된다).

## 되쓰기 방식

문단의 **첫 `hp:t` 에 치환 결과를 넣고 같은 문단의 나머지 `hp:t` 를 비운다.**
run 을 새로 만들지 않으므로 `charPrIDRef` 가 살아 문자 서식이 보존된다
(SFR-006 `_write_occurrence`·태그의 `hwpx_rewrite` 와 같은 전략).
대가로 한 문단 안의 부분 서식은 첫 run 서식으로 통일된다.
"""

import io
import re
import zipfile
from copy import deepcopy

from lxml import etree

from ..config import Config
from ..hwpx_xml import PARA, own_text_nodes
from ..logging_utils import log_info, log_warning
from .errors import ExportError, ExporterUnavailable, ensure_exportable_items

_TOKEN_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")

# 반복 토큰. question 이 앵커다 (없으면 반복 블록이 없는 템플릿).
_ANCHOR_TOKEN = "question"
_REPEAT_TOKENS = (_ANCHOR_TOKEN, "answer", "evidence")

# <hp:t> 안의 \n 은 문단 분리가 아니다 — 그대로 넣으면 한/글에서 깨져 보인다
_NEWLINE_REPLACEMENT = " "


def available() -> bool:
    """`GET /formats` 용 — 템플릿이 등록돼 있고 읽을 수 있는가."""
    import os

    return bool(Config.HWPX_TEMPLATE_PATH) and os.path.isfile(Config.HWPX_TEMPLATE_PATH)


def _normalize(value) -> str:
    text = str(value if value is not None else "")
    return text.replace("\r\n", "\n").replace("\n", _NEWLINE_REPLACEMENT)


def _para_text(para) -> str:
    return "".join((node.text or "") for node in own_text_nodes(para))


def _substitute_in_para(para, values: dict) -> bool:
    """문단 텍스트의 토큰을 치환한다. 바뀌었으면 True.

    토큰이 여러 run 으로 쪼개져 있어도(한/글이 서식 경계마다 run 을 나눈다) 문단
    텍스트를 이어 붙여 판정하므로 잡힌다. 치환 결과는 첫 노드에 몰아 쓰고 나머지를
    비운다.
    """
    nodes = own_text_nodes(para)
    if not nodes:
        return False
    joined = "".join((node.text or "") for node in nodes)
    if "{{" not in joined:
        return False

    replaced = joined
    for name in set(_TOKEN_RE.findall(joined)):
        if name not in values:
            continue  # 값이 없는 토큰은 건드리지 않는다 (잔존 검사로 드러난다)
        replaced = replaced.replace("{{" + name + "}}", _normalize(values[name]))
    if replaced == joined:
        return False

    nodes[0].text = replaced  # lxml 이 escape 를 자동 처리한다 (<, &, > 안전)
    for node in nodes[1:]:
        node.text = ""
    return True


def _find_repeat_block(root) -> list:
    """반복 블록 문단 목록. 없으면 빈 목록.

    `{{question}}` 문단을 앵커로 잡고, **같은 부모 아래 이어지는 형제**를 훑어
    마지막 반복 토큰 문단까지를 블록으로 본다. 그 뒤에 빈 문단이 하나 있으면
    항목 사이 간격이므로 블록에 포함한다.
    """
    anchor = None
    for para in root.iter(PARA):
        if "{{" + _ANCHOR_TOKEN + "}}" in _para_text(para):
            anchor = para
            break
    if anchor is None:
        return []

    parent = anchor.getparent()
    if parent is None:
        return []

    siblings = [child for child in parent if child.tag == PARA]
    try:
        start = siblings.index(anchor)
    except ValueError:
        return []

    block = [anchor]
    last_token_offset = 0
    for offset, para in enumerate(siblings[start + 1:], start=1):
        text = _para_text(para)
        has_token = any("{{" + token + "}}" in text for token in _REPEAT_TOKENS)
        if has_token:
            block.append(para)
            last_token_offset = offset
            continue
        if not text.strip():
            block.append(para)  # 후보(간격 문단) — 뒤에 토큰 문단이 더 없으면 남긴다
            continue
        break

    # 마지막 토큰 문단 이후의 빈 문단은 **하나만** 간격으로 인정한다.
    # 여러 개를 통째로 반복하면 항목 사이가 페이지 하나씩 벌어진다.
    keep = last_token_offset + 1
    trimmed = block[: keep + 1] if len(block) > keep + 1 else block
    return trimmed


def _expand(root, items: list) -> bool:
    """반복 블록을 항목 수만큼 복제해 삽입하고 원본 블록을 제거한다."""
    block = _find_repeat_block(root)
    if not block:
        return False

    parent = block[0].getparent()
    insert_at = list(parent).index(block[0])

    for position, item in enumerate(items, start=1):
        values = {
            "question": item.get("question", ""),
            "answer": item.get("answer", ""),
            "evidence": item.get("sources", ""),
            "no": position,  # 번호를 쓰고 싶은 템플릿을 위해 함께 넘긴다
        }
        for template_para in block:
            copied = deepcopy(template_para)
            _substitute_in_para(copied, values)
            parent.insert(insert_at, copied)
            insert_at += 1

    # 템플릿 문단 제거 — lxml truthiness 함정 회피: 반드시 `is not None`
    # (자식 없는 element 는 False 로 평가된다)
    for template_para in block:
        if template_para.getparent() is not None:
            template_para.getparent().remove(template_para)
    return True


def _fill_scalars(root, scalars: dict) -> None:
    for para in root.iter(PARA):
        _substitute_in_para(para, scalars)


def _remaining_tokens(data: bytes) -> set:
    return set(_TOKEN_RE.findall(data.decode("utf-8", errors="replace")))


def build_faq_hwpx(items: list, *, title: str = "", created_on: str = "") -> bytes:
    """FAQ 항목을 등록된 템플릿에 채워 hwpx 바이트로 만든다.

    Args:
        items: `[{"question", "answer", "sources"}]` (`formatting.to_export_rows` 형태).
        title: `{{title}}` 에 넣을 문서 제목.
        created_on: `{{date}}` 에 넣을 생성일 문자열. 호출부가 만든다
            (이 모듈이 시각을 읽으면 같은 세션을 두 번 내려받을 때 값이 달라진다).

    Raises:
        ExporterUnavailable: 템플릿이 등록되지 않았거나 파일이 없다.
        ExportError: 항목이 없거나 템플릿이 손상됐거나 반복 블록이 없다.
    """
    ensure_exportable_items(items)
    if not available():
        raise ExporterUnavailable(
            "이 환경에서는 hwpx 내보내기를 사용할 수 없습니다. 관리자에게 FAQ 템플릿 등록을 요청해 주세요."
        )

    scalars = {"title": title, "count": len(items), "date": created_on}
    buffer = io.BytesIO()
    expanded = False

    try:
        with zipfile.ZipFile(Config.HWPX_TEMPLATE_PATH, "r") as source, zipfile.ZipFile(
            buffer, "w", zipfile.ZIP_DEFLATED
        ) as target:
            for entry in source.infolist():
                data = source.read(entry.filename)
                if entry.filename.startswith("Contents/") and entry.filename.endswith(".xml"):
                    root = etree.fromstring(data)
                    if not expanded:
                        expanded = _expand(root, items)
                    _fill_scalars(root, scalars)
                    # standalone="yes" 는 한/글 원본 파트의 선언이다. 빼고 쓰면
                    # OWPML 패키지 검사가 파트 오류로 잡는다 (006 serialize_part 와 같은
                    # 규약 — 배포 단위가 달라 import 하지 않고 같은 규칙을 각자 적는다).
                    data = etree.tostring(
                        root, encoding="UTF-8", xml_declaration=True, standalone=True
                    )
                # mimetype 은 무압축이어야 한다 — 압축하면 한/글이 열지 못한다
                compress = (
                    zipfile.ZIP_STORED if entry.filename == "mimetype" else zipfile.ZIP_DEFLATED
                )
                target.writestr(entry.filename, data, compress_type=compress)
    except (zipfile.BadZipFile, etree.XMLSyntaxError) as exc:
        # 3.8절: 파싱 예외 원문은 담지 않고 분류만 로그로 남긴다
        log_warning(
            "FAQ hwpx 템플릿을 해석하지 못했다",
            event="faq_hwpx_template_invalid",
            resource_id="faq_hwpx_template",
            error_type=type(exc).__name__,
        )
        raise ExportError("FAQ 템플릿 파일을 해석하지 못했습니다.") from exc

    if not expanded:
        # 반복 블록이 없으면 항목이 한 건도 문서에 들어가지 않는다. 그런 파일을
        # 성공으로 내려보내면 사용자는 빈 FAQ 문서를 받는다.
        raise ExportError(
            "FAQ 템플릿에 반복 블록({{question}} 문단)이 없습니다. 템플릿을 확인해 주세요."
        )

    result = buffer.getvalue()
    leftover = set()
    with zipfile.ZipFile(io.BytesIO(result)) as produced:
        for name in produced.namelist():
            if name.startswith("Contents/") and name.endswith(".xml"):
                leftover |= _remaining_tokens(produced.read(name))
    if leftover:
        # 문서는 내려보내되(부분 초안 계약) 잔존 토큰을 조용히 넘기지 않는다.
        # 대개 한/글이 토큰을 문단 경계로 쪼갠 템플릿이다.
        log_warning(
            "FAQ hwpx 에 치환되지 않은 토큰이 남았다",
            event="faq_hwpx_tokens_remaining",
            resource_id="faq_hwpx_template",
            item_count=len(leftover),
        )

    log_info("FAQ hwpx 생성 완료", event="faq_hwpx_built", item_count=len(items))
    return result
