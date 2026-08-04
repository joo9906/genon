"""템플릿에 적힌 서식 명세(`제목: {함초롬, 16pt, bold}`)를 실제 hwpx 서식으로 적용한다.

역할 분리 (CLAUDE.md §5 — LLM 응답을 믿지 않는다):
- **명세 파싱과 XML 조작은 전부 코드가 한다.** LLM 에게 문단을 조작하게 하지 않는다.
  글자 크기·폰트 id·itemCnt 는 한 글자만 틀려도 한/글이 문서를 열지 못하는 값이고,
  LLM 출력은 매번 달라진다. 결정적으로 처리할 수 있는 일에 비결정 도구를 쓰지 않는다.
- LLM 이 필요한 지점은 딱 하나다: 명세가 자유 표기일 때
  ("제목은 좀 크고 굵게") → `{font, size_pt, bold}` 로 정규화. 그 산출물도 여기서
  화이트리스트로 검증한 뒤에만 반영한다. 정형 명세(`{함초롬, 16pt, bold}`)는
  `parse_style_spec` 만으로 처리되므로 LLM 호출이 없다.

hwpx 서식 구조 (domain — 매번 다시 알아내지 말 것):
    Contents/section0.xml  <hp:run charPrIDRef="3"><hp:t>텍스트</hp:t></hp:run>
    Contents/header.xml    <hh:charPr id="3" height="1600">   ← 1pt = 100
                             <hh:fontRef hangul="1" latin="1" .../>
                             <hh:bold/> <hh:italic/> <hh:underline .../>
                           <hh:font id="1" face="함초롬돋움"/>  (fontface lang 별 목록)

- 크기 단위: `height` 는 1/100 pt (16pt → "1600")
- 굵게/기울임은 속성이 아니라 **자식 요소의 존재**로 표현된다
- `charProperties`/`fontface` 의 `itemCnt`/`fontCnt` 를 갱신하지 않으면 한/글이
  목록 개수를 신뢰하지 못한다 → 반드시 다시 센다
- 폰트는 언어(lang)별 목록이 따로 있다. 한글만 바꾸면 라틴 문자가 다른 폰트로 남는다
  → 존재하는 모든 fontface 에 등록하고 fontRef 의 모든 언어 속성을 함께 바꾼다
"""

import copy
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from lxml import etree

from .hwpx_fields import HP_NS, TemplateError, _parse_xml  # 같은 도메인 모듈 재사용
from .logging_utils import log_info, log_warning

HH_NS = "http://www.hancom.co.kr/hwpml/2011/head"

_CHAR_PROPERTIES = f"{{{HH_NS}}}charProperties"
_CHAR_PR = f"{{{HH_NS}}}charPr"
_FONT_REF = f"{{{HH_NS}}}fontRef"
_FONTFACE = f"{{{HH_NS}}}fontface"
_FONT = f"{{{HH_NS}}}font"
_BOLD = f"{{{HH_NS}}}bold"
_ITALIC = f"{{{HH_NS}}}italic"
_UNDERLINE = f"{{{HH_NS}}}underline"

_RUN = f"{{{HP_NS}}}run"
_PARA = f"{{{HP_NS}}}p"
_TEXT = f"{{{HP_NS}}}t"
_FIELD_BEGIN = f"{{{HP_NS}}}fieldBegin"
_FIELD_END = f"{{{HP_NS}}}fieldEnd"

HEADER_ENTRY = "Contents/header.xml"

# ── 명세 표기 파싱 ───────────────────────────────────────────
# "제목: {함초롬, 16pt, bold}" / "{함초롬돋움 16 굵게}" / "{돋움,12pt,밑줄}"
_SPEC_BLOCK_RE = re.compile(r"\{([^{}]+)\}")
_LABELLED_SPEC_RE = re.compile(r"([^\s:：][^:：]*)[:：]\s*\{([^{}]+)\}")
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:pt|포인트|p)?\b", re.IGNORECASE)
_BOLD_WORDS = ("bold", "굵게", "진하게", "볼드")
_ITALIC_WORDS = ("italic", "기울임", "이탤릭", "이태릭")
_UNDERLINE_WORDS = ("underline", "밑줄", "언더라인")
_STYLE_WORDS = _BOLD_WORDS + _ITALIC_WORDS + _UNDERLINE_WORDS
# 값이 아니라 항목 이름인 단어들 — 폰트명으로 오인하면 안 된다.
# 예: "{볼드체, 16pt, 글꼴}" 의 '글꼴' 은 폰트 이름이 아니라 자리 표시다.
_META_WORDS = ("글꼴", "폰트", "서체", "font", "typeface", "크기", "size", "스타일", "style", "pt", "포인트")
# "글꼴: 함초롬바탕" 처럼 라벨이 붙어 오는 경우 라벨을 떼고 값만 본다
_LABEL_PREFIX_RE = re.compile(
    r"^\s*(?:글꼴|폰트|서체|font|typeface|크기|size|스타일|style)\s*[:=]\s*", re.IGNORECASE
)
_PART_SPLIT_RE = re.compile(r"[,/·|]")


@dataclass(frozen=True)
class StyleSpec:
    """문단/필드에 적용할 글자 서식. None 은 '원본 유지'를 뜻한다."""

    font: str | None = None
    size_pt: float | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None

    @property
    def empty(self) -> bool:
        return all(
            v is None for v in (self.font, self.size_pt, self.bold, self.italic, self.underline)
        )


@dataclass
class StyleApplyResult:
    hwpx_bytes: bytes
    applied_fields: list      # 서식을 적용한 필드명
    unmatched_specs: list     # 명세는 있는데 대응 누름틀이 없는 항목명
    stripped_annotations: int  # 문서에서 지운 명세 표기 개수
    added_char_prs: int        # 새로 만든 charPr 개수


def parse_style_spec(text: str) -> StyleSpec | None:
    """`{함초롬, 16pt, bold}` 같은 표기를 StyleSpec 으로 바꾼다. 없으면 None.

    구분자는 쉼표/공백 모두 허용한다(관대한 파서 — 규칙 문서 §4.1 취지).
    인식하지 못한 토큰은 폰트 이름 후보로 본다. 여러 개면 첫 번째를 쓴다.
    """
    if not text:
        return None
    block = _SPEC_BLOCK_RE.search(text)
    if not block:
        return None

    body = block.group(1).strip()
    if not body:
        return None
    lowered = body.lower()

    size = None
    size_hit = _SIZE_RE.search(body)
    if size_hit:
        try:
            size = float(size_hit.group(1))
        except ValueError:
            size = None

    bold = True if any(w in lowered for w in _BOLD_WORDS) else None
    italic = True if any(w in lowered for w in _ITALIC_WORDS) else None
    underline = True if any(w in lowered for w in _UNDERLINE_WORDS) else None

    font = _find_font(body)
    spec = StyleSpec(font=font, size_pt=size, bold=bold, italic=italic, underline=underline)
    return None if spec.empty else spec


def _is_font_candidate(token: str) -> bool:
    """폰트 이름 후보인가 — 크기·효과·항목이름 토큰을 걸러낸다."""
    if not token:
        return False
    lowered = token.lower()
    if _SIZE_RE.fullmatch(token) or token.replace(".", "").isdigit():
        return False
    if any(word in lowered for word in _STYLE_WORDS):
        return False  # '볼드체', 'bold' 등 (단 '바탕체'·'굴림체' 는 걸리지 않는다)
    # 항목 이름만 남은 토큰('글꼴', '크기')은 값이 아니다
    return not any(lowered == word or lowered.rstrip(":= ") == word for word in _META_WORDS)


def _find_font(body: str) -> str | None:
    """명세 본문에서 폰트 이름을 찾는다.

    쉼표/슬래시로 먼저 나눈다 — 공백으로 먼저 나누면 '맑은 고딕' 같은 이름이 잘린다.
    구분자가 없을 때만 공백으로 나눈다("{함초롬돋움 16pt 굵게}" 형태 지원).
    """
    parts = [p.strip() for p in _PART_SPLIT_RE.split(body) if p.strip()]
    if len(parts) == 1:
        parts = [p for p in parts[0].split() if p]

    for part in parts:
        candidate = _LABEL_PREFIX_RE.sub("", part).strip()
        if _is_font_candidate(candidate):
            return candidate
        # "글꼴 함초롬바탕" 처럼 라벨과 값이 공백으로만 붙은 경우
        pieces = candidate.split()
        if len(pieces) > 1 and pieces[0].lower() in _META_WORDS:
            rest = " ".join(pieces[1:])
            if _is_font_candidate(rest):
                return rest
    return None


# ── 템플릿에서 명세 수집 ─────────────────────────────────────
def _open_hwpx(hwpx_bytes: bytes) -> zipfile.ZipFile:
    """ZIP 열기 실패는 입력 오류(TemplateError)로 변환한다 — 내부 오류가 아니다."""
    try:
        return zipfile.ZipFile(io.BytesIO(hwpx_bytes))
    except zipfile.BadZipFile as exc:
        raise TemplateError("hwpx 파일이 아니거나 손상된 파일입니다.") from exc


def _iter_content_xml(hwpx_bytes: bytes):
    with _open_hwpx(hwpx_bytes) as archive:
        for name in archive.namelist():
            if name.startswith("Contents/") and name.endswith(".xml"):
                yield name, archive.read(name)


def collect_style_specs(hwpx_bytes: bytes) -> dict:
    """템플릿에 적힌 서식 명세를 {필드명: StyleSpec} 으로 모은다.

    두 위치를 모두 본다 — 실제 템플릿이 어느 방식인지에 따라 달라지기 때문이다.
    1) 누름틀 안내문(stringParam) 안의 `{…}` — 그 필드에 직접 적용
    2) 본문 텍스트의 `항목명: {…}` — 항목명과 같은 이름의 누름틀에 적용

    Raises:
        TemplateError: XML 손상.
    """
    from .hwpx_fields import scan_fields

    specs: dict = {}
    field_names = {spec.name for spec in scan_fields(hwpx_bytes)}

    # 1) 안내문에 붙은 명세
    for spec in scan_fields(hwpx_bytes):
        parsed = parse_style_spec(spec.guide)
        if parsed:
            specs[spec.name] = parsed

    # 2) 본문에 적힌 "항목명: {…}"
    for name, xml_bytes in _iter_content_xml(hwpx_bytes):
        if PurePosixPath(name).name == "header.xml":
            continue
        root = _parse_xml(xml_bytes, name)
        for text_node in root.iter(_TEXT):
            for label, body in _LABELLED_SPEC_RE.findall(text_node.text or ""):
                parsed = parse_style_spec("{" + body + "}")
                if not parsed:
                    continue
                label = label.strip()
                # 안내문 명세가 이미 있으면 그것을 우선한다 (필드에 더 가까운 선언)
                specs.setdefault(label, parsed)
    unmatched = sorted(k for k in specs if k not in field_names)
    if unmatched:
        log_warning(
            "서식 명세에 대응하는 누름틀이 없다",
            event="style_spec_unmatched",
            item_count=len(unmatched),
        )
    return specs


# ── header.xml 서식 등록 ─────────────────────────────────────
def _font_id_for(head, face: str) -> str:
    """모든 fontface(lang)에 face 를 등록하고 공통으로 쓸 font id 를 돌려준다.

    lang 마다 목록이 따로라 한글만 바꾸면 라틴 문자가 옛 폰트로 남는다.
    """
    faces = head.findall(f".//{_FONTFACE}")
    if not faces:
        raise TemplateError("템플릿에 폰트 정의(fontface)가 없어 서식을 적용할 수 없습니다.")

    existing_ids = set()
    for face_list in faces:
        fonts = face_list.findall(_FONT)
        hit = next((f for f in fonts if (f.get("face") or "") == face), None)
        if hit is not None:
            existing_ids.add(hit.get("id"))
    if len(existing_ids) == 1:
        return existing_ids.pop()

    # 모든 목록에서 비어 있는 공통 id 를 고른다
    used = {
        int(f.get("id"))
        for face_list in faces
        for f in face_list.findall(_FONT)
        if (f.get("id") or "").isdigit()
    }
    new_id = str(max(used) + 1 if used else 0)
    for face_list in faces:
        if not any((f.get("face") or "") == face for f in face_list.findall(_FONT)):
            etree.SubElement(
                face_list,
                _FONT,
                {"id": new_id, "face": face, "type": "TTF", "isEmbedded": "0"},
            )
        face_list.set("fontCnt", str(len(face_list.findall(_FONT))))
    return new_id


def _toggle(char_pr, tag: str, enabled: bool | None) -> None:
    """굵게/기울임/밑줄은 자식 요소의 존재로 표현된다."""
    if enabled is None:
        return
    found = char_pr.find(tag)
    if enabled and found is None:
        etree.SubElement(char_pr, tag)
    elif not enabled and found is not None:
        char_pr.remove(found)


def _derive_char_pr(head, base_id: str, spec: StyleSpec) -> str:
    """base_id 의 글자모양을 복제해 spec 을 적용한 새 charPr id 를 만든다.

    같은 (base, spec) 조합이면 이미 만든 것을 재사용한다 — 필드가 많을 때
    charPr 목록이 무한히 늘어나지 않게 한다.
    """
    props = head.find(f".//{_CHAR_PROPERTIES}")
    if props is None:
        raise TemplateError("템플릿에 글자모양 정의(charProperties)가 없어 서식을 적용할 수 없습니다.")

    all_prs = props.findall(_CHAR_PR)
    base = next((p for p in all_prs if p.get("id") == base_id), None)
    if base is None:
        base = all_prs[0] if all_prs else None
    if base is None:
        raise TemplateError("템플릿에 글자모양 정의(charPr)가 없어 서식을 적용할 수 없습니다.")

    new_pr = copy.deepcopy(base)
    if spec.size_pt is not None:
        new_pr.set("height", str(int(round(spec.size_pt * 100))))  # 1pt = 100
    if spec.font:
        font_id = _font_id_for(head, spec.font)
        ref = new_pr.find(_FONT_REF)
        if ref is None:
            ref = etree.SubElement(new_pr, _FONT_REF)
        for lang_attr in ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user"):
            ref.set(lang_attr, font_id)
    _toggle(new_pr, _BOLD, spec.bold)
    _toggle(new_pr, _ITALIC, spec.italic)
    _toggle(new_pr, _UNDERLINE, spec.underline)

    signature = etree.tostring(new_pr, encoding="unicode")
    for existing in all_prs:
        candidate = copy.deepcopy(existing)
        candidate.set("id", new_pr.get("id"))
        if etree.tostring(candidate, encoding="unicode") == signature:
            return existing.get("id")  # 동일한 서식이 이미 있다

    used = {int(p.get("id")) for p in all_prs if (p.get("id") or "").isdigit()}
    new_id = str(max(used) + 1 if used else 0)
    new_pr.set("id", new_id)
    props.append(new_pr)
    props.set("itemCnt", str(len(props.findall(_CHAR_PR))))  # 개수 갱신 필수
    return new_id


# ── 본문에 적용 ──────────────────────────────────────────────
def _field_runs(root) -> dict:
    """{필드명: (값 run 목록, 문단 요소)} — begin/end 를 문서 순서 스택으로 매칭한다."""
    result: dict = {}
    stack: list = []
    for elem in root.iter():
        if elem.tag == _FIELD_BEGIN:
            name = (elem.get("name") or "").strip()
            run = elem.getparent().getparent() if elem.getparent() is not None else None
            para = run.getparent() if run is not None else None
            stack.append((name, para))
            result.setdefault(name, {"runs": [], "para": para})
        elif elem.tag == _FIELD_END:
            if stack:
                stack.pop()
        elif elem.tag == _TEXT and stack:
            run = elem.getparent()
            if run is not None and run.tag == _RUN:
                for name, _ in stack:
                    result[name]["runs"].append(run)
    return result


def apply_styles(
    hwpx_bytes: bytes,
    styles: dict,
    *,
    scope: str = "paragraph",
    strip_annotations: bool = True,
) -> StyleApplyResult:
    """{필드명: StyleSpec} 을 문서에 적용한다.

    Args:
        scope: "paragraph" 는 그 필드가 놓인 문단의 모든 run 에 적용(문단 단위 서식),
               "run" 은 누름틀 값 run 에만 적용.
        strip_annotations: 본문에 적힌 `항목명: {…}` 명세 표기를 결과에서 지운다.
            명세는 작성 지시문이라 산출 문서에 남아선 안 된다.

    Raises:
        TemplateError: 서식 정의가 없거나 XML 손상.
    """
    if not styles:
        return StyleApplyResult(hwpx_bytes, [], [], 0, 0)

    src = _open_hwpx(hwpx_bytes)
    with src:
        try:
            head = _parse_xml(src.read(HEADER_ENTRY), HEADER_ENTRY)
        except KeyError as exc:
            raise TemplateError("템플릿에 서식 정의 파일(header.xml)이 없습니다.") from exc

        before_pr_count = len(head.findall(f".//{_CHAR_PR}"))
        applied: list = []
        stripped = 0
        sections: dict = {}

        for name in src.namelist():
            if not (name.startswith("Contents/") and name.endswith(".xml")):
                continue
            if PurePosixPath(name).name == "header.xml":
                continue
            root = _parse_xml(src.read(name), name)
            fields = _field_runs(root)

            for field_name, spec in styles.items():
                target = fields.get(field_name)
                if target is None:
                    continue
                runs = target["runs"]
                if scope == "paragraph" and target["para"] is not None:
                    runs = [r for r in target["para"].iter(_RUN) if r.find(_TEXT) is not None]
                if not runs:
                    continue
                for run in runs:
                    base_id = run.get("charPrIDRef") or "0"
                    run.set("charPrIDRef", _derive_char_pr(head, base_id, spec))
                applied.append(field_name)

            if strip_annotations:
                for text_node in root.iter(_TEXT):
                    original = text_node.text or ""
                    if not original or "{" not in original:
                        continue
                    cleaned = _LABELLED_SPEC_RE.sub(lambda m: f"{m.group(1)}:", original)
                    if cleaned != original:
                        stripped += 1
                        text_node.text = re.sub(r"\s{2,}", " ", cleaned).rstrip()
            sections[name] = etree.tostring(root, encoding="UTF-8", xml_declaration=True)

        header_bytes = etree.tostring(head, encoding="UTF-8", xml_declaration=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                if item.filename == HEADER_ENTRY:
                    data = header_bytes
                elif item.filename in sections:
                    data = sections[item.filename]
                else:
                    data = src.read(item.filename)
                dst.writestr(
                    item.filename,
                    data,
                    compress_type=(
                        zipfile.ZIP_STORED if item.filename == "mimetype" else zipfile.ZIP_DEFLATED
                    ),
                )

    added = len(head.findall(f".//{_CHAR_PR}")) - before_pr_count
    unmatched = sorted(set(styles) - set(applied))
    log_info(
        "서식 명세 적용 완료",
        event="style_applied",
        item_count=len(set(applied)),
        status=f"scope={scope} new_char_pr={added} stripped={stripped}",
    )
    if unmatched:
        log_warning(
            "명세가 있으나 대응 누름틀을 찾지 못해 적용하지 못했다",
            event="style_apply_unmatched",
            item_count=len(unmatched),
        )
    return StyleApplyResult(
        hwpx_bytes=buf.getvalue(),
        applied_fields=sorted(set(applied)),
        unmatched_specs=unmatched,
        stripped_annotations=stripped,
        added_char_prs=added,
    )
