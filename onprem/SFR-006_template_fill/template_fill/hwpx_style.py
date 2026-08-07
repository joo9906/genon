"""슬롯의 서식 인자(`{'제목', 16pt, 함초롬, 볼드}`)를 실제 hwpx 서식으로 적용한다.

**이 단계가 채우기보다 먼저 돈다.** 슬롯은 값을 채우면 `{…}` 가 사라지므로, 채운 뒤에는
어디에 무슨 서식을 걸어야 하는지 알 방법이 없다. 그래서 여기서 슬롯 텍스트를 **전용 run
으로 떼어내고 그 run 에 charPr 을 걸어 둔 다음**, 채우기가 그 run 안 글자만 갈아 끼운다.
순서를 되돌리면 서식이 통째로 유실된다 (`document.py` 참고).

지정하지 않은 인자는 **건드리지 않는다.** `{'제목', 16pt}` 는 크기만 바꾸고 글꼴·굵기는
그 자리 run 의 `charPrIDRef` 를 그대로 물려받는다 — 서식을 지어내지 않는 것이 원칙이다.

역할 분리 (CLAUDE.md §5 — LLM 응답을 믿지 않는다):
- **인자 해석과 XML 조작은 전부 코드가 한다.** LLM 에게 문단을 조작하게 하지 않는다.
  글자 크기·폰트 id·itemCnt 는 한 글자만 틀려도 한/글이 문서를 열지 못하는 값이고,
  LLM 출력은 매번 달라진다. 결정적으로 처리할 수 있는 일에 비결정 도구를 쓰지 않는다.
- 슬롯 인자는 자리가 정해져 있어(따옴표 뒤) **추측이 필요 없다.** 예전 라벨 방식은
  `{…}` 가 서식인지 값 안내인지 몰라 글꼴 어휘로 근거를 따져야 했고, 그래도 `{소속}` 을
  글꼴로 거는 사고가 났다. 지금은 따옴표가 그 경계를 대신한다.

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

from lxml import etree

# 같은 도메인 모듈 재사용 — 문단 소유·라벨 인식·본문 판정은 hwpx_fields 가 정본이다.
# (hwpx_fields 는 이 패키지의 어떤 모듈도 import 하지 않으므로 순환이 없다.)
from .hwpx_fields import (
    CLICK_HERE_TYPE,
    HP_NS,
    TemplateError,
    iter_slot_paragraphs,
    open_hwpx,
    own_nodes,
    parse_xml,
    rewrite_slots,
    scan_fields,
    section_order,
    split_style_args,
)
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
_TEXT = f"{{{HP_NS}}}t"
_FIELD_BEGIN = f"{{{HP_NS}}}fieldBegin"
_FIELD_END = f"{{{HP_NS}}}fieldEnd"

HEADER_ENTRY = "Contents/header.xml"

# ── 서식 인자 해석 ───────────────────────────────────────────
# 인자는 **순서·개수가 자유롭다.** `{'제목', 16pt, 고딕, 볼드}` 와 `{'제목', 볼드, 고딕}`
# 과 `{'제목'}` 이 모두 유효하다. 위치를 고정하면 가운데를 건너뛸 때 `{'제목', , 고딕}`
# 처럼 빈 자리를 남겨야 하고, 관리자가 순서를 틀리면 없는 글꼴을 걸게 된다.
_SIZE_TOKEN_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(?:pt|포인트|p|px)?$", re.IGNORECASE)
_BOLD_WORDS = ("bold", "굵게", "굵은", "진하게", "볼드", "true")
# 굵기를 **끄는** 표기. 템플릿 문단이 이미 굵을 때 "이 자리는 보통으로" 를 적을 수단이다.
_NOT_BOLD_WORDS = ("안굵게", "굵지않게", "보통", "normal", "regular", "false")
_ITALIC_WORDS = ("italic", "기울임", "이탤릭", "이태릭")
_UNDERLINE_WORDS = ("underline", "밑줄", "언더라인")
# 값이 아니라 **자리 표시어**인 낱말 — 글꼴 이름으로 오인하면 없는 글꼴을 문서에 건다.
# 문서의 문법 설명(`{'제목', 글씨크기, 폰트, 볼드여부}`)을 관리자가 그대로 복사해
# 붙이는 일이 실제로 생기므로, 그 낱말들을 여기서 삼킨다.
_PLACEHOLDER_WORDS = (
    "글꼴", "폰트", "서체", "font", "typeface", "글씨크기", "글자크기", "크기", "사이즈",
    "size", "스타일", "style", "pt", "포인트", "볼드여부", "굵기", "굵게여부", "글꼴명",
)
# "글꼴: 함초롬바탕" 처럼 이름표가 붙어 오는 경우 이름표를 떼고 값만 본다
_LABEL_PREFIX_RE = re.compile(
    r"^\s*(?:글꼴|폰트|서체|font|typeface|크기|글씨크기|size|스타일|style)\s*[:=]\s*",
    re.IGNORECASE,
)
# 레거시 경로(누름틀 안내문)에서만 쓰는 `{…}` 추출 — 아래 parse_style_spec 참고.
_SPEC_BLOCK_RE = re.compile(r"\{([^{}]+)\}")
# 글꼴 이름에 실제로 쓰이는 어휘. **누름틀 안내문에서만** 근거로 쓴다 — 거기엔 따옴표
# 경계가 없어 서식인지 값 안내인지 구분할 방법이 이것뿐이다. 슬롯 인자에는 쓰지 않는다
# (사내 전용 글꼴이 목록에 없다고 무시하면 관리자가 명시한 지시를 버리는 셈이다).
_FONT_FAMILY_WORDS = (
    "고딕", "명조", "바탕", "돋움", "굴림", "궁서", "헤드라인", "그래픽", "필기",
    "함초롬", "맑은", "나눔", "휴먼", "신명", "산돌", "윤", "안상수", "타이포",
    "hy", "md", "gothic", "batang", "gulim", "dotum", "myeongjo", "malgun",
    "arial", "times", "calibri", "segoe", "verdana", "tahoma", "courier", "roboto",
    "helvetica", "consolas", "gungsuh",
)


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
    applied_fields: list      # 서식을 적용한 항목명
    unmatched_specs: list     # 안내문 명세는 있는데 대응 누름틀이 없는 항목명
    added_char_prs: int       # 새로 만든 charPr 개수
    # `{…}` 표기 제거는 여기서 하지 않는다 — 슬롯 텍스트는 다음 단계(채우기)가
    # 값으로 바꾸면서 통째로 사라진다. 두 곳에서 지우면 순서에 따라 결과가 갈린다.


def parse_style_args(args, *, require_evidence: bool = False) -> StyleSpec | None:
    """서식 인자 토큰을 StyleSpec 으로 바꾼다. 지정하지 않은 값은 None(=원본 유지).

    토큰을 **생김새로** 판정하므로 순서와 개수에 매이지 않는다:
    - `16pt` · `16` · `16포인트` → 크기
    - `볼드` · `굵게` · `bold` · `true` → 굵게, `보통` · `normal` · `false` → 굵게 해제
    - `기울임` · `밑줄` → 그대로
    - 자리 표시어(`글씨크기` · `폰트` · `볼드여부`)는 버린다 — 문법 설명을 그대로
      복사해 붙인 템플릿에서 없는 글꼴을 거는 것을 막는다
    - 남은 첫 토큰이 글꼴 이름

    Args:
        require_evidence: 누름틀 안내문 경로 전용 플래그 (`parse_style_spec`).
            따옴표 경계가 없어 서식인지 값 안내인지 모르는 입력에만 켠다.
            **두 가지를 함께 바꾼다** — 이름만 보고 게이팅만 하리라 짐작하지 말 것:
            (1) 크기·효과·글꼴 어휘 중 근거가 하나도 없으면 None 을 돌려준다.
            (2) 글꼴을 **재선택한다** — 첫 토큰이 아니라 글꼴 어휘를 담은 토큰을
                고른다(`제 목: {제목, HY헤드라인M, 16pt}` → '제목' 아니라 'HY헤드라인M').
            슬롯 인자는 자리가 명확하므로 끄고 쓴다 — 사내 전용 글꼴이 어휘 목록에
            없다고 관리자의 명시적 지시를 버리지 않기 위해서다.
    """
    size = bold = italic = underline = None
    fonts: list = []

    for token in args or ():
        candidate = _LABEL_PREFIX_RE.sub("", str(token or "").strip()).strip()
        if not candidate:
            continue
        size_hit = _SIZE_TOKEN_RE.match(candidate)
        if size_hit:
            try:
                size = float(size_hit.group(1))
            except ValueError:  # 정규식이 통과시킨 뒤에는 사실상 오지 않는다
                pass
            continue
        # **자리 표시어를 가장 먼저 걸러낸다.** 효과 판정은 부분 문자열 매칭이라
        # `볼드여부`·`굵게여부` 가 `볼드`·`굵게` 에 걸려 굵기 지시로 읽힌다 —
        # 문법 설명(`{'제목', 글씨크기, 폰트, 볼드여부}`)을 그대로 복사해 붙인 템플릿이
        # 실제로 굵어지는 결함이었다. 자리 표시어는 완전 일치라 진짜 지시(`볼드`)를
        # 삼키지 않는다.
        if _normalize_name(candidate) in _PLACEHOLDER_SET:
            continue
        lowered = candidate.lower()
        # 부정 표기를 먼저 본다 — '안굵게' 는 '굵게' 를 품고 있다.
        if any(word in lowered for word in _NOT_BOLD_WORDS):
            bold = False
        elif any(word in lowered for word in _BOLD_WORDS):
            bold = True
        elif any(word in lowered for word in _ITALIC_WORDS):
            italic = True
        elif any(word in lowered for word in _UNDERLINE_WORDS):
            underline = True
        else:
            fonts.append(candidate)

    font = fonts[0] if fonts else None
    if require_evidence:
        known_font = next((f for f in fonts if _has_font_keyword(f)), None)
        if size is None and bold is None and not italic and not underline and known_font is None:
            return None  # 근거 없음 → 서식이 아니라 값 안내로 본다 (서식을 지어내지 않는다)
        font = known_font or font

    spec = StyleSpec(font=font, size_pt=size, bold=bold, italic=italic, underline=underline)
    return None if spec.empty else spec


def parse_style_spec(text: str, label: str | None = None) -> StyleSpec | None:
    """누름틀 **안내문**에 적힌 `{함초롬, 16pt, bold}` 표기 — 레거시 경로.

    슬롯과 달리 여기에는 따옴표 경계가 없다. 그래서 서식으로 인정하려면 근거를
    요구한다(`require_evidence`) — 근거 없는 `{…}` 는 값 안내다(`{소속} {성명}`,
    `{YYYY.MM.DD. (요일)}`). 예전에는 첫 토큰을 글꼴로 채택해 '소속' 이라는 없는
    글꼴을 문서에 걸었다.

    Args:
        label: 이 명세가 붙은 항목명. 명세 안에 항목명이 자리표시어로 다시 적힌
            경우(`제 목: {제목, HY헤드라인M, 16pt}`) 그 토큰을 글꼴로 오인하지 않도록
            제외하는 데 쓴다.
    """
    if not text:
        return None
    block = _SPEC_BLOCK_RE.search(text)
    if not block:
        return None
    body = block.group(1).strip()
    if not body:
        return None

    # 구분자 문법은 hwpx_fields 가 정본이다 — 슬롯 인자와 같은 규칙을 써야
    # `;` 하나를 추가했을 때 한쪽만 고쳐지는 일이 없다.
    parts = list(split_style_args(body))
    if label:
        normalized = _normalize_name(label)
        parts = [p for p in parts if _normalize_name(p) != normalized]
    return parse_style_args(parts, require_evidence=True)


def _normalize_name(text: str) -> str:
    """항목명 대조용 정규화 — 공백을 없애고 소문자로 (`제 목` == `제목`)."""
    return "".join((text or "").split()).lower()


_PLACEHOLDER_SET = {_normalize_name(word) for word in _PLACEHOLDER_WORDS}


def _has_font_keyword(token: str) -> bool:
    lowered = token.lower()
    return any(word in lowered for word in _FONT_FAMILY_WORDS)


# ── 템플릿에서 명세 수집 ─────────────────────────────────────
def collect_guide_styles(hwpx_bytes: bytes) -> dict:
    """**누름틀 안내문**에 적힌 서식 명세를 {항목명: StyleSpec} 으로 모은다.

    슬롯은 자기 인자를 스스로 들고 다니므로 여기 오지 않는다 (`apply_styles` 가 문단을
    돌면서 바로 읽는다). 이 함수는 한/글에서 필드를 심어 만든 템플릿 전용 폴백이다.

    Raises:
        TemplateError: XML 손상.
    """
    specs: dict = {}
    # 슬롯은 자기 인자를 스스로 들고 다니므로 여기서 스캔할 이유가 없다 —
    # include_slots=True 로 두면 전 문단 슬롯 정규식 sweep 을 돌리고 결과를 버린다.
    for spec in scan_fields(hwpx_bytes, include_slots=False):
        if spec.field_type != CLICK_HERE_TYPE:
            continue
        parsed = parse_style_spec(spec.guide, label=spec.name)
        if parsed:
            specs[spec.name] = parsed
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
def _runs_of(text_nodes) -> list:
    """텍스트 노드들을 담은 run 목록 (등장 순서, 중복 제거).

    서식은 `hp:run` 의 `charPrIDRef` 에 걸린다. 그래서 어느 경로로 자리를 찾았든
    (누름틀·라벨·문단) 마지막 한 걸음은 "이 텍스트 노드의 run" 을 구하는 같은 일이다.
    """
    runs: list = []
    for node in text_nodes:
        run = node.getparent()
        if run is not None and run.tag == _RUN and run not in runs:
            runs.append(run)
    return runs


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
            for run in _runs_of((elem,)):
                for name, _ in stack:
                    result[name]["runs"].append(run)
    return result


def _paragraph_own_runs(para) -> list:
    """이 문단에 직접 속한, 텍스트가 있는 run 만.

    표는 hp:p → hp:run → hp:tbl → … → hp:p 로 중첩되므로 para.iter(_RUN) 를 그대로
    쓰면 표 안 모든 셀에 문단 서식이 번진다 (소유 판정은 hwpx_fields 가 정본).
    """
    return _runs_of(own_nodes(para, _TEXT))


def _apply_slot_styles(root, head, scope: str, applied: list) -> int:
    """슬롯을 전용 run 으로 떼어내고 그 run 의 `charPrIDRef` 를 바꾼다.

    **텍스트는 그대로 둔다** (`texts=[None…]`) — 값은 다음 단계인 채우기가 넣는다.
    서식 인자가 하나도 없는 문단은 건드리지 않는다: 쪼갤 이유가 없고, 손대지 않는 편이
    "명시하지 않으면 원본 서식을 그대로 따른다"는 규칙을 가장 정확히 지킨다.
    """
    styled = 0
    # 슬롯 문단 판정은 hwpx_fields 가 정본이다 — 채우기 단계(`_fill_slots`)와 **같은**
    # 문단 집합을 봐야 한다. 여기서 쪼갠 run 에 저쪽이 글자를 넣는 구조라, 판정이
    # 갈리면 서식만 걸리고 값이 안 들어가거나 그 반대가 된다.
    for para, occurrences in iter_slot_paragraphs(root):
        specs = [parse_style_args(occ.style_args) for occ in occurrences]
        if not any(specs):
            continue
        spec_by_id = {id(occ): spec for occ, spec in zip(occurrences, specs)}
        # 문단 전체에 거는 것은 서식을 지정한 슬롯이 **하나뿐일 때만** 뜻이 통한다.
        # 둘 이상이면 서로 덮어쓰므로 그 문단은 슬롯 범위로 떨어뜨린다.
        whole_para = scope == "paragraph" and sum(1 for spec in specs if spec) == 1

        for occ, run in rewrite_slots(para, occurrences, [None] * len(occurrences)):
            spec = spec_by_id.get(id(occ))
            if spec is None:
                continue
            for target in (_paragraph_own_runs(para) if whole_para else [run]):
                base_id = target.get("charPrIDRef") or "0"
                target.set("charPrIDRef", _derive_char_pr(head, base_id, spec))
            applied.append(occ.name)
            styled += 1
    return styled


def _apply_guide_styles(root, head, styles: dict, scope: str, applied: list) -> int:
    """누름틀 안내문에서 모은 명세를 그 필드에 건다 (레거시 경로).

    기본은 문단 단위다 — 누름틀 템플릿에서 지금까지 그렇게 동작했고, 안내문 명세는
    슬롯 인자처럼 "이 글자 구간" 을 가리키지 않는다. `scope="run"` 이면 값 run 만.
    """
    if not styles:
        return 0
    fields = _field_runs(root)
    count = 0
    for field_name, spec in styles.items():
        target = fields.get(field_name)
        if target is None:
            continue
        runs = target["runs"]
        if scope != "run" and target["para"] is not None:
            runs = _paragraph_own_runs(target["para"])
        if not runs:
            continue
        for run in runs:
            base_id = run.get("charPrIDRef") or "0"
            run.set("charPrIDRef", _derive_char_pr(head, base_id, spec))
        applied.append(field_name)
        count += 1
    return count


def apply_styles(hwpx_bytes: bytes, *, scope: str = "slot") -> StyleApplyResult:
    """슬롯 서식 인자(+누름틀 안내문 명세)를 실제 hwpx 서식으로 반영한다.

    **채우기보다 먼저 부른다** — 모듈 docstring 참고. 적용 자체는 `charPr` 을 복제해
    크기(height)·글꼴·굵게만 바꾼 뒤 그 id 를 run 의 `charPrIDRef` 에 걸어주는 결정적
    조작이다 (LLM 호출 없음).

    Args:
        scope: 서식을 어디까지 걸지.
            - `"slot"`(기본): 슬롯은 중괄호 자리 run 에만, 누름틀은 문단 전체.
              중괄호 밖 텍스트(`제 목 : `)는 원래 서식을 지킨다.
            - `"paragraph"`: 슬롯도 문단 전체에 건다 (라벨까지 같이 커진다).
            - `"run"`: 누름틀도 값 run 에만 건다.

    Raises:
        TemplateError: 서식 정의가 없거나 XML 손상.
    """
    styles = collect_guide_styles(hwpx_bytes)

    src = open_hwpx(hwpx_bytes)
    with src:
        try:
            head = parse_xml(src.read(HEADER_ENTRY))
        except KeyError as exc:
            raise TemplateError("템플릿에 서식 정의 파일(header.xml)이 없습니다.") from exc

        before_pr_count = len(head.findall(f".//{_CHAR_PR}"))
        applied: list = []
        changed = 0
        sections: dict = {}

        for name in src.namelist():
            if section_order(name) is None:  # 본문만 (판정은 hwpx_fields 가 정본)
                continue
            root = parse_xml(src.read(name))
            changed += _apply_slot_styles(root, head, scope, applied)
            changed += _apply_guide_styles(root, head, styles, scope, applied)
            sections[name] = etree.tostring(root, encoding="UTF-8", xml_declaration=True)

        if not changed:
            # 서식 지정이 하나도 없는 템플릿 — zip 을 다시 쓰지 않고 원본을 그대로 돌려준다.
            return StyleApplyResult(hwpx_bytes, [], sorted(styles), 0)

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
        "서식 적용 완료",
        event="style_applied",
        item_count=len(set(applied)),
        status=f"scope={scope} new_char_pr={added}",
    )
    if unmatched:
        log_warning(
            "안내문 명세가 있으나 대응 누름틀을 찾지 못해 적용하지 못했다",
            event="style_apply_unmatched",
            item_count=len(unmatched),
        )
    return StyleApplyResult(
        hwpx_bytes=buf.getvalue(),
        applied_fields=sorted(set(applied)),
        unmatched_specs=unmatched,
        added_char_prs=added,
    )
