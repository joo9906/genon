"""hwpx 템플릿 파서/필러 — lxml 기반. 채울 자리를 찾아 값을 쓴다.

워크플로우(run_chat.py)와 코드 서빙(main.py)이 공유하는 조작 엔진.
GenOS 런타임 의존이 없어 로컬에서 단독 검증 가능하다 (tests/ 참고).

채울 자리는 세 방식으로 찾는다. 실제 템플릿이 어떤 방식으로 만들어졌는지에 따라
쓰이는 경로가 다르고, 한 문서에 섞여 있어도 된다:

1. **슬롯**(기본) — 본문에 텍스트로 적힌 `제 목 : {'제목', 16pt, 고딕, 볼드}`.
   중괄호 **안**만 채울 자리다. 첫 인자는 **따옴표로 감싼 필수값**이고 그것이
   항목명이자 "여기에 무엇을 쓰라"는 AI 안내문이다. 뒤따르는 인자(0~3개)는
   크기·글꼴·굵게이며, 없으면 그 자리 run 의 `charPrIDRef` 를 그대로 따른다.
   채울 때는 **`{…}` 블록만** 값으로 바꾼다 — 중괄호 밖 텍스트(`제 목 : `)는
   들여쓰기·줄맞춤 공백까지 **무조건 원문 그대로** 남는다.
2. **누름틀**(CLICK_HERE 필드) — 한/글에서 필드를 심어 만든 템플릿용 폴백.
3. **레거시 `{{token}}`** — 프로토타입 호환.

따옴표가 없는 `{…}`(`담당자 : {소속} {성명}`, `{YYYY.MM.DD. (요일)}`)는 **채울 자리가
아니다.** 문서에 원문 그대로 남기고, 등록 시 경고로만 노출한다 — 지워 버리면 값 안내로
쓰던 문구가 조용히 사라지고, 등록을 거부하면 본문에 중괄호를 쓴 정상 문서를 막는다.

도메인 지식 (CLAUDE.md §3 — 매번 다시 알아내지 말 것):
- hwpx = ZIP + XML. 본문은 Contents/section{N}.xml
- hp 네임스페이스는 태그 식별자일 뿐 네트워크 주소가 아니다 (폐쇄망 접속 금지)
- 문단 id는 전부 중복(2147483648)이라 신뢰 불가 → id 기반 주소 지정 금지.
  누름틀 fieldBegin/fieldEnd 짝은 문서 순서 스택 매칭이 기본이고,
  beginIDRef 가 있으면 보조로만 사용한다.
- mimetype 엔트리는 무압축(STORED) 규약 유지, XML 선언 유지

누름틀의 XML 구조 (OWPML):
    <hp:run><hp:ctrl>
      <hp:fieldBegin id="..." type="CLICK_HERE" name="필드명" ...>
        <hp:parameters><hp:stringParam name="...">안내문</hp:stringParam></hp:parameters>
      </hp:fieldBegin>
    </hp:ctrl></hp:run>
    <hp:run><hp:t>현재 표시 텍스트(미입력이면 안내문과 동일)</hp:t></hp:run>
    <hp:run><hp:ctrl><hp:fieldEnd beginIDRef="..."/></hp:ctrl></hp:run>

"채워짐" 판단: begin~end 사이 텍스트가 비어 있지 않고 안내문과 다르면 채워진 것.

레거시 {{token}} 템플릿(SFR-006/hwpx.py 프로토타입 방식)도 함께 지원한다 —
스칼라 토큰 치환만. 반복 블록 복제는 이 모듈 범위 밖.
"""

import io
import re
import zipfile
from copy import deepcopy
from dataclasses import dataclass, field as dc_field

from lxml import etree

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_FIELD_BEGIN = f"{{{HP_NS}}}fieldBegin"
_FIELD_END = f"{{{HP_NS}}}fieldEnd"
_TEXT = f"{{{HP_NS}}}t"
_RUN = f"{{{HP_NS}}}run"
_STRING_PARAM = f"{{{HP_NS}}}stringParam"

# 토큰명에 한글을 허용한다 — 이 저장소의 필드명은 전부 한글이고, 누름틀 필드명과
# 토큰명은 같은 이름 공간을 쓴다(fill_template 이 values 하나로 둘 다 채운다).
# ASCII 전용 패턴은 {{부서}} 를 못 잡아 조용히 치환되지 않는 결함이 있었다.
TOKEN_RE = re.compile(r"\{\{\s*([^{}\r\n]+?)\s*\}\}")
CLICK_HERE_TYPE = "CLICK_HERE"
NEWLINE_REPLACEMENT = " "  # <hp:t> 안의 \n 은 문단 분리가 아니므로 치환

_PARA = f"{{{HP_NS}}}p"

# 본문 엔트리. hwpx 본문은 Contents/section{N}.xml 이고 번호가 문서 순서다.
_SECTION_ENTRY_RE = re.compile(r"^Contents/section(\d+)\.xml$")

# ── 슬롯 인식 규칙 (결정적) ───────────────────────────────────
# `{'항목명'}` / `{'항목명', 16pt}` / `{'항목명', 16pt, 맑은 고딕, 볼드}`
SLOT_FIELD_TYPE = "SLOT"

# `FieldSpec.source` 값 — 어느 방식의 템플릿인지 화면·로그가 구분하는 키다.
# 상수로 두는 이유: 예전에 라벨→슬롯으로 이름이 바뀔 때 문자열 리터럴을 쓰던
# 로그 한 곳이 따라오지 못해 `labels=0` 만 계속 찍었다 (조용히 죽은 지표).
SOURCE_SLOT = "slot"
SOURCE_FIELD = "field"

# 여는 따옴표 → 닫는 따옴표로 인정할 문자.
# 한/글 자동 고침이 `'제목'` 을 `‘제목’` 으로 바꿔 저장하므로 굽은 따옴표를 함께 받는다.
# 편집 중 한쪽만 바뀐 문서(`‘제목'`)도 열어 준다 — 관리자가 눈으로 구분할 수 없는
# 차이 때문에 항목이 통째로 사라지는 편이 훨씬 나쁘다.
_QUOTE_PAIRS = {
    "'": "'’",
    "‘": "'’",
    '"': '"”',
    "“": '"”',
}
_QUOTES = "'‘’\"“”"
# 그룹: (여는 따옴표)(항목명)(닫는 따옴표)(나머지 인자)
# 항목명에 따옴표는 넣을 수 없다 — 닫는 자리를 알 수 없어진다.
_SLOT_RE = re.compile(
    r"\{\s*(?P<open>['‘\"“])(?P<name>[^" + _QUOTES + r"{}]*)(?P<close>['’\"”])"
    r"(?P<rest>[^{}]*)\}"
)
# 따옴표가 있든 없든 `{…}` 전부. 슬롯이 아닌 나머지가 "따옴표 없는 중괄호" 경고 대상이다.
_BRACE_RE = re.compile(r"\{[^{}]*\}")
# 인자 구분자. 쉼표류로 먼저 나눈다 — 공백으로 먼저 나누면 `맑은 고딕` 이 잘린다.
_ARG_SPLIT_RE = re.compile(r"[,/·|]")


def split_style_args(rest: str) -> tuple:
    """서식 인자 문자열을 토큰으로 나눈다 (**해석은 hwpx_style 이 한다**).

    여기서 하는 일은 문법(어디서 끊는가)뿐이고, 어느 토큰이 크기·글꼴·굵게인지는
    hwpx_style 이 정한다 — 도메인 어휘를 두 모듈에 두면 갈린다.

    **슬롯 인자와 누름틀 안내문 명세가 같은 함수를 쓴다.** 구분자 규칙이 두 벌이 되면
    `;` 를 하나 추가했을 때 슬롯만 고쳐지고 안내문 경로는 조용히 옛 규칙으로 남는다
    (그래서 public 이다 — `hwpx_style.parse_style_spec` 이 이 함수를 부른다).
    """
    body = rest.strip().lstrip(",/·|").strip()
    if not body:
        return ()
    parts = [p.strip() for p in _ARG_SPLIT_RE.split(body) if p.strip()]
    if len(parts) == 1:
        # 구분자 없이 공백만 쓴 경우(`{'제목' 16pt 굵게}`). 이때 `맑은 고딕` 은 갈라진다 —
        # 여러 낱말 글꼴은 쉼표로 끊으라는 뜻이고, 그 사실을 README 에 적어 둔다.
        parts = [p for p in parts[0].split() if p]
    return tuple(parts)


class TemplateError(ValueError):
    """템플릿 파일 해석 실패 (ZIP/XML 손상 등).

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다.
    호출부가 사용자 노출 오류(user_msg)로 그대로 쓸 수 있어야 하기 때문.
    """


@dataclass
class FieldOccurrence:
    """섹션 XML 안의 누름틀 1개 (같은 이름이 여러 번 나올 수 있다)."""

    name: str
    guide: str          # 안내문 (stringParam)
    field_type: str     # CLICK_HERE 등
    current_text: str   # begin~end 사이 현재 텍스트
    section: str        # Contents/section0.xml 등
    # 내부용 — 채우기 시 조작할 lxml 노드 (스캔 전용 경로에서는 비어 있음)
    text_nodes: list = dc_field(default_factory=list, repr=False)
    begin_elem: object = dc_field(default=None, repr=False)

    @property
    def filled(self) -> bool:
        text = self.current_text.strip()
        return bool(text) and text != self.guide.strip()


@dataclass
class SlotOccurrence:
    """본문에 텍스트로 적힌 슬롯 1개 (`{'제목', 16pt, 고딕}`).

    누름틀과 달리 XML 상의 경계가 없다 — **문단 소유 텍스트 안의 글자 구간**이 자리다.
    한 문단에 여러 개가 있을 수 있다 (`담당자 : {'소속'} {'성명'}`).
    """

    name: str           # 따옴표 안 문자열 = 항목명 겸 AI 안내문
    style_args: tuple   # 뒤따르는 인자 원문 토큰 (해석은 hwpx_style)
    section: str
    start: int          # 문단 소유 텍스트를 이어 붙인 문자열 기준 시작 offset
    end: int            # 〃 끝 offset (`{` ~ `}` 를 포함한 구간)
    raw: str            # `{…}` 원문 (값이 없을 때 그대로 되돌려 쓰는 데 쓴다)
    para: object = dc_field(default=None, repr=False)
    text_nodes: list = dc_field(default_factory=list, repr=False)
    # 슬롯에는 "이미 적혀 있던 값" 이 없다 — 아래 filled 설명 참고.
    current_text: str = ""

    @property
    def field_type(self) -> str:
        return SLOT_FIELD_TYPE

    @property
    def guide(self) -> str:
        # 따옴표 안 문자열이 곧 안내문이다. 라벨 방식과 달리 "무엇을 쓰라"가 명시돼 있다.
        return self.name

    @property
    def filled(self) -> bool:
        """슬롯은 **항상 미입력이다.**

        채우고 나면 `{…}` 자체가 사라지므로, 문서에 슬롯이 남아 있다는 것은 곧 아직
        채우지 않았다는 뜻이다. 스캔 대상은 언제나 템플릿 원본이고, 완성 문서를 다시
        스캔하는 경로는 없다 (값은 세션에 있다).
        """
        return False


@dataclass(frozen=True)
class FieldSpec:
    """이름 기준으로 합친 필드 스키마 — LLM/사용자에게 보여주는 단위."""

    name: str
    guide: str
    field_type: str
    occurrences: int
    filled: bool        # 모든 occurrence 가 채워졌을 때만 True (슬롯은 언제나 False)
    current_value: str  # 채워진 occurrence 의 값 (없으면 "")
    source: str = SOURCE_FIELD  # SOURCE_FIELD(누름틀) | SOURCE_SLOT(본문 슬롯)


@dataclass
class FillResult:
    hwpx_bytes: bytes
    written_fields: list      # 이번에 값이 기록된 필드명
    missing_fields: list      # 값이 없어서 안내문 상태로 남은 필드명
    unknown_keys: list        # 템플릿에 존재하지 않는 values 키
    leftover_tokens: list     # 치환되지 않고 남은 {{token}}


# ─────────────────────────────────────────────────────────────
# XML 파싱
# ─────────────────────────────────────────────────────────────
def _first_string_param_text(begin_elem) -> str:
    """fieldBegin 하위 첫 stringParam 텍스트 = 누름틀 안내문.

    파라미터 name 속성이 한/글 버전에 따라 다를 수 있어(ClickHere 등)
    이름을 고정 매칭하지 않고 첫 stringParam 을 안내문으로 본다.
    """
    for param in begin_elem.iter(_STRING_PARAM):
        return (param.text or "").strip()
    return ""


def _collect_occurrences(root, section_name: str) -> list:
    """섹션 XML 에서 누름틀 occurrence 목록을 문서 순서로 수집한다.

    fieldBegin/fieldEnd 짝은 스택으로 매칭한다 (beginIDRef 는 보조 검증).
    중첩 필드는 텍스트를 모든 열린 필드에 귀속시킨다.
    """
    occurrences: list = []
    stack: list = []  # (begin_elem, record)

    for elem in root.iter():
        if elem.tag == _FIELD_BEGIN:
            record = FieldOccurrence(
                name=(elem.get("name") or "").strip(),
                guide=_first_string_param_text(elem),
                field_type=(elem.get("type") or "").strip(),
                current_text="",
                section=section_name,
                begin_elem=elem,
            )
            stack.append(record)
        elif elem.tag == _FIELD_END:
            if not stack:
                continue  # 짝 없는 fieldEnd — 손상 문서지만 스캔은 계속한다
            begin_id_ref = (elem.get("beginIDRef") or "").strip()
            record = stack.pop()
            begin_id = (record.begin_elem.get("id") or "").strip()
            if begin_id_ref and begin_id and begin_id_ref != begin_id:
                # id 불일치 — 문단 id 중복 문제(§3.2)와 같은 계열이므로
                # 스택(문서 순서) 매칭을 신뢰하고 그대로 진행한다.
                pass
            record.current_text = "".join(
                (t.text or "") for t in record.text_nodes
            ).strip()
            occurrences.append(record)
        elif elem.tag == _TEXT and stack:
            # fieldBegin 을 담은 ctrl 내부의 텍스트는 안내문 파라미터이므로 제외
            for open_record in stack:
                if open_record.begin_elem is not None and _is_descendant(
                    elem, open_record.begin_elem
                ):
                    break
            else:
                for open_record in stack:
                    open_record.text_nodes.append(elem)

    # 이름이 빈 누름틀 → 안내문/순번으로 대체 이름 부여 (LLM 이 지칭할 수 있어야 함)
    unnamed = 0
    for record in occurrences:
        if not record.name:
            unnamed += 1
            record.name = record.guide or f"field_{unnamed}"
    return occurrences


def nearest_para(node):
    """이 텍스트 노드를 직접 담고 있는 문단. 표 안(hp:tc→hp:subList→hp:p)까지 따라간다."""
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _PARA:
            return parent
        parent = parent.getparent()
    return None


def own_nodes(para, tag: str) -> list:
    """이 문단에 **직접** 속한 노드만 (표 셀 안의 하위 문단 것은 제외).

    hwpx 표는 hp:p → hp:run → hp:tbl → … → hp:p 로 중첩된다. 그래서 단순히
    para.iter() 를 쓰면 표 전체 텍스트가 한 문단 텍스트로 이어져 라벨 인식이 깨진다.

    이 저장소의 다른 hwpx 모듈(hwpx_style, hwpx_markdown)도 같은 판정을 쓴다 —
    문단 소유 규칙을 두 벌로 두면 "채우는 자리"와 "서식 거는 자리"가 어긋난다.
    """
    return [node for node in para.iter(tag) if nearest_para(node) is para]


def owns_any(para, tag: str) -> bool:
    """이 문단이 직접 소유한 `tag` 노드가 하나라도 있는가 (목록을 만들지 않는다)."""
    return any(nearest_para(node) is para for node in para.iter(tag))


def is_text_run(run) -> bool:
    """이 run 이 **글자만** 담고 있는가 — 자식이 `hp:t` 뿐인 run.

    슬롯을 전용 run 으로 떼어낼 때(`rewrite_slots`)와 본문 블록이 문단을 복제할 때
    (`hwpx_blocks`) 같은 판정을 쓴다. 화이트리스트인 이유: `hp:secPr`·`hp:ctrl`·`hp:tbl`
    이 하나라도 섞인 run 을 복제하면 구역 정의나 표가 통째로 따라온다. 현장 템플릿의
    첫 문단(`제 목 :`)이 실제로 secPr 을 함께 담고 있다.
    """
    return run is not None and run.tag == _RUN and all(child.tag == _TEXT for child in run)


def _mask_tokens(text: str) -> str:
    """`{{token}}` 구간을 같은 길이의 공백으로 가린다 (offset 보존).

    레거시 토큰이 처리할 자리를 슬롯 파서가 가로채지 않게 한다. 길이를 유지하므로
    가린 문자열에서 찾은 위치를 원문에 그대로 쓸 수 있다.
    """
    return TOKEN_RE.sub(lambda m: " " * len(m.group(0)), text) if "{{" in text else text


def para_text(para) -> str:
    """이 문단이 **직접** 가진 텍스트를 이어 붙인 것 (슬롯 offset 의 기준 문자열)."""
    return "".join((node.text or "") for node in own_nodes(para, _TEXT))


def slot_occurrences(para, section_name: str = "") -> list:
    """문단 하나가 가진 슬롯 목록 (등장 순서).

    한 문단에 여러 개가 올 수 있다 — `담당자 : {'소속'} {'성명'}` 은 슬롯 2개다.
    라벨 방식과 달리 문단당 1개라는 제약이 없다.
    """
    nodes = own_nodes(para, _TEXT)
    if not nodes:
        return []
    text = "".join((node.text or "") for node in nodes)
    if "{" not in text:
        return []

    found: list = []
    for match in _SLOT_RE.finditer(_mask_tokens(text)):
        if match.group("close") not in _QUOTE_PAIRS[match.group("open")]:
            continue  # `‘제목"` — 짝이 맞지 않으면 슬롯으로 보지 않는다
        name = match.group("name").strip()
        if not name:
            continue  # `{''}` — 채울 자리를 특정할 이름이 없다
        found.append(
            SlotOccurrence(
                name=name,
                style_args=split_style_args(match.group("rest")),
                section=section_name,
                start=match.start(),
                end=match.end(),
                raw=text[match.start():match.end()],
                para=para,
                text_nodes=nodes,
            )
        )
    return found


def iter_slot_paragraphs(root, section_name: str = ""):
    """슬롯이 있는 문단을 `(para, occurrences)` 로 돌려준다 (문서 순서).

    누름틀이 있는 문단은 건너뛴다 — 같은 문단을 두 경로가 고치면 값이 이중으로 들어가고,
    run 을 쪼개는 도중 begin/end 사이 구조가 흐트러진다.

    **이 판정이 한 곳에만 있어야 하는 이유**: 서식 단계(`hwpx_style._apply_slot_styles`)와
    채우기 단계(`_fill_slots`)가 **같은 문단 집합**을 봐야 한다. 서식이 run 을 쪼개 둔
    자리에 채우기가 글자를 넣는 구조라, 두 단계의 판정이 갈리면 서식만 걸리고 값이
    안 들어가거나 그 반대가 된다. 예전에는 이 순회가 세 곳에 복사돼 있었다.

    `list(root.iter(_PARA))` 로 먼저 붙들어 둔다 — 호출부가 문단 안 run 을 재구성하는
    동안 lxml 이 순회 중인 트리를 바꾸게 두지 않는다.
    """
    for para in list(root.iter(_PARA)):
        if owns_any(para, _FIELD_BEGIN):
            continue
        occurrences = slot_occurrences(para, section_name)
        if occurrences:
            yield para, occurrences


def collect_slot_occurrences(root, section_name: str = "") -> list:
    """섹션 XML 의 슬롯을 문서 순서로 평탄화해 모은다."""
    found: list = []
    for _, occurrences in iter_slot_paragraphs(root, section_name):
        found.extend(occurrences)
    return found


def bare_braces(para) -> list:
    """따옴표가 없어 **슬롯으로 보지 않은** `{…}` 원문 (등장 순서).

    등록 시 경고로만 쓴다. 값 안내(`{소속}`, `{YYYY.MM.DD. (요일)}`)일 수도 있고
    따옴표를 빠뜨린 오타일 수도 있어 코드가 판단하지 않는다 — 관리자가 본다.
    """
    text = para_text(para)
    if "{" not in text:
        return []
    masked = _mask_tokens(text)
    spans = [(occ.start, occ.end) for occ in slot_occurrences(para)]
    return [
        text[m.start():m.end()]
        for m in _BRACE_RE.finditer(masked)
        if not any(start <= m.start() and m.end() <= end for start, end in spans)
    ]


def rewrite_slots(para, occurrences: list, texts: list) -> list:
    """문단의 슬롯 자리만 새 텍스트로 갈아 끼운다.

    **중괄호 밖 텍스트는 건드리지 않는다** — 들여쓰기와 `제 목  : ` 의 줄맞춤 공백까지
    원문 그대로 남는다. 라벨 방식은 `항목명: 값` 으로 줄을 재조립하느라 이 공백을
    잃었고, 그래서 `prefix` 를 따로 보존해야 했다. 자리를 중괄호로 명시하면 그 문제가
    아예 생기지 않는다.

    Args:
        occurrences: 이 문단의 슬롯 목록. **`slot_occurrences` 가 방금 준 것**이어야
            한다 (offset 이 현재 텍스트 기준이라야 하므로).
        texts: 슬롯마다 넣을 문자열. `None` 이면 원문(`{…}`)을 그대로 둔다 —
            서식 단계가 텍스트를 남긴 채 run 만 쪼갤 때 쓴다.

    Returns:
        `[(occ, run)]` — 각 슬롯 텍스트가 들어간 run. 서식은 이 run 의 `charPrIDRef` 에
        건다. 슬롯마다 run 을 나누는 이유는 서식 인자가 **그 슬롯에만** 걸려야 하기
        때문이다. 문단 전체에 걸면 중괄호 밖 라벨까지 같이 커지고, 한 문단에 슬롯이
        둘이면 뒤엣것이 앞엣것을 덮는다.

    호출 뒤 `occurrences` 의 offset·text_nodes 는 무효다 (문단을 다시 짰다).
    """
    if not occurrences:
        return []
    nodes = own_nodes(para, _TEXT)
    if not nodes:
        return []

    bounds: list = []
    cursor = 0
    for node in nodes:
        length = len(node.text or "")
        bounds.append((node, cursor, cursor + length))
        cursor += length

    pieces: list = []  # (원본 노드, 넣을 텍스트, 슬롯 or None)

    def _literal(begin: int, stop: int) -> None:
        """중괄호 밖 구간 — 원래 노드 경계를 그대로 지켜 조각낸다 (서식 보존)."""
        for node, node_start, node_end in bounds:
            low, high = max(begin, node_start), min(stop, node_end)
            if low < high:
                pieces.append((node, (node.text or "")[low - node_start:high - node_start], None))

    def _node_at(offset: int):
        for node, node_start, node_end in bounds:
            if node_start <= offset < node_end:
                return node
        return nodes[0]

    at = 0
    for occ, replacement in zip(occurrences, texts):
        _literal(at, occ.start)
        pieces.append((_node_at(occ.start), occ.raw if replacement is None else replacement, occ))
        at = occ.end
    _literal(at, cursor)

    if not all(is_text_run(node.getparent()) for node in nodes):
        return _rewrite_flat(nodes, pieces)

    # run 별로 조각을 모은다. 프록시를 리스트에 붙들어 둬야 `getparent()` 가 같은
    # 객체를 돌려준다 — 놓아 버리면 회수됐다 다시 만들어져 id 대조가 어긋난다.
    #
    # **글자를 가진 run 을 전부 먼저 등록한다.** 슬롯이 run 을 걸치면(`{'구` / `분', 14pt}`)
    # 뒤쪽 run 은 조각을 하나도 받지 못하는데, 그때 손대지 않고 넘어가면 옛 글자가
    # 그대로 남아 `구분 : 정기분', 14pt}` 처럼 문서에 두 번 적힌다.
    grouped: list = []  # [(run, [(텍스트, 슬롯), …])]
    index: dict = {}
    for node in nodes:
        run = node.getparent()
        if id(run) not in index:
            index[id(run)] = []
            grouped.append((run, index[id(run)]))
    for node, text, occ in pieces:
        index[id(node.getparent())].append((text, occ))

    result: list = []
    for run, items in grouped:
        # 첫 조각은 원래 run 에 그대로 둔다 — charPrIDRef 를 비롯한 속성이 보존된다.
        # 조각이 하나도 없으면 비운다 (위 주석 참고).
        head_text, head_occ = items[0] if items else ("", None)
        existing = run.findall(_TEXT)
        if existing:
            existing[0].text = head_text
            for extra in existing[1:]:
                run.remove(extra)
        else:
            etree.SubElement(run, _TEXT).text = head_text
        if head_occ is not None:
            result.append((head_occ, run))

        parent = run.getparent()
        base = parent.index(run)
        for offset, (text, occ) in enumerate(items[1:], start=1):
            clone = deepcopy(run)  # 이 시점의 run 은 `hp:t` 하나짜리다
            clone.findall(_TEXT)[0].text = text
            parent.insert(base + offset, clone)
            if occ is not None:
                result.append((occ, clone))
    return result


def _rewrite_flat(nodes: list, pieces: list) -> list:
    """쪼갤 수 없는 문단 — 완성된 한 줄을 첫 노드에 넣고 나머지를 비운다.

    `hp:t` 와 `hp:ctrl`·`hp:secPr` 가 **한 run 에 섞여 있는** 경우다. 그런 run 을
    복제하면 구역 정의나 누름틀이 함께 복제된다. 텍스트는 정확히 반영되지만 슬롯마다
    다른 서식은 걸 수 없어, 슬롯이 놓인 run 을 그대로 돌려준다 (서식은 그 run 전체에
    걸리고, 호출부가 그 사실을 로그로 남긴다).
    """
    nodes[0].text = "".join(text for _, text, _ in pieces)
    for node in nodes[1:]:
        node.text = ""
    run = nodes[0].getparent()
    if run is None or run.tag != _RUN:
        return []
    return [(occ, run) for _, _, occ in pieces if occ is not None]


def _is_descendant(elem, ancestor) -> bool:
    parent = elem.getparent()
    while parent is not None:
        if parent is ancestor:
            return True
        parent = parent.getparent()
    return False


def open_hwpx(hwpx_bytes: bytes) -> zipfile.ZipFile:
    """hwpx(ZIP) 열기. 실패는 **입력 오류**(TemplateError)로 바꾼다 — 내부 오류가 아니다.

    이 패키지의 모든 hwpx 진입점(스캔·채우기·서식·미리보기)이 이 함수를 쓴다.
    사용자에게 보이는 안내문이 한 곳에만 있어야 문구가 갈리지 않는다.
    """
    try:
        return zipfile.ZipFile(io.BytesIO(hwpx_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise TemplateError("hwpx 파일이 아니거나 손상된 파일입니다.") from exc


def section_order(entry_name: str) -> int | None:
    """본문 섹션이면 섹션 번호, 아니면 None. **"무엇이 본문인가"의 판정은 이 함수뿐이다.**

    문자열 정렬을 쓰지 않는 이유: `section10` 이 `section2` 앞에 온다. 스캔 순서는
    사용자에게 묻는 순서이자 미리보기 렌더 순서라, 둘이 어긋나면 화면과 질문이 갈린다.
    header.xml 은 서식 정의(문단이 없다)라 본문이 아니다.
    """
    match = _SECTION_ENTRY_RE.match(entry_name)
    return int(match.group(1)) if match else None


def iter_section_xml(hwpx_bytes: bytes):
    """(엔트리명, xml bytes) 를 섹션 번호 순서로 순회한다 (본문만).

    Raises:
        TemplateError: ZIP 손상.
    """
    with open_hwpx(hwpx_bytes) as zf:
        for name in sorted(
            (n for n in zf.namelist() if section_order(n) is not None), key=section_order
        ):
            yield name, zf.read(name)


def parse_xml(xml_bytes: bytes):
    try:
        return etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise TemplateError("템플릿 본문 XML 을 해석하지 못했습니다.") from exc


# ─────────────────────────────────────────────────────────────
# 스캔 (읽기 전용)
# ─────────────────────────────────────────────────────────────
def missing_field_names(specs, values: dict) -> list:
    """아직 값이 필요한 항목명 (문서 등장 순서).

    "무엇이 부족한가"의 판정은 이 함수뿐이다. 예전에는 `/status`·`/preview`·값 수정 응답·
    대화 턴이 각자 같은 조건식을 적어 두고 있어서, 한 곳만 고치면 다운로드 버튼과
    대화가 서로 다른 `ready` 를 보고했다.

    Args:
        specs: FieldSpec 목록 (템플릿 색인).
        values: 세션에 모인 값. 템플릿에 이미 적혀 있던 값(`spec.filled`)은 세션에 없어도
            채워진 것으로 본다 — 문서에 그대로 남기 때문이다.
    """
    return [s.name for s in specs if s.name not in values and not s.filled]


def _ordered_occurrences(root, section_name: str, include_types: tuple, include_slots: bool) -> list:
    """한 섹션의 누름틀·슬롯을 문서 등장 순서로 합친다.

    사용자에게 "이어서 ○○ 알려주세요" 로 묻는 순서가 문서 순서와 같아야 하므로,
    두 경로를 따로 붙이지 않고 XML 등장 위치로 정렬한다. 같은 문단 안 슬롯 여럿은
    문단 안에서의 글자 위치로 갈린다 (`{'소속'} {'성명'}` 의 순서).
    """
    # 순회 결과를 리스트로 붙들어 둔다 — lxml 프록시는 참조가 끊기면 회수되고 id 가
    # 재사용되므로, 살려두지 않으면 위치 맵이 다른 노드를 가리킨다.
    walked = list(root.iter())
    position = {id(elem): idx for idx, elem in enumerate(walked)}
    items: list = []
    for occ in _collect_occurrences(root, section_name):
        if include_types and occ.field_type not in include_types:
            continue
        items.append(((position.get(id(occ.begin_elem), 0), 0), occ))
    if include_slots:
        for occ in collect_slot_occurrences(root, section_name):
            items.append(((position.get(id(occ.para), 0), occ.start), occ))
    items.sort(key=lambda pair: pair[0])
    return [occ for _, occ in items]


def scan_fields(
    hwpx_bytes: bytes,
    include_types: tuple = (CLICK_HERE_TYPE,),
    include_slots: bool = True,
) -> list:
    """hwpx 전체에서 채울 항목 스키마(FieldSpec 목록)를 추출한다.

    Args:
        hwpx_bytes: 템플릿 hwpx 파일 바이트.
        include_types: 노출할 누름틀 field type. 기본은 CLICK_HERE 만.
        include_slots: 본문에 텍스트로 적힌 `{'항목명', …}` 슬롯도 포함할지.

    Returns:
        문서 등장 순서를 유지한 FieldSpec 목록 (이름 기준 dedup).
        같은 이름이 여러 자리에 있으면 한 항목으로 묶이고 값도 모든 자리에 같이 들어간다
        (`{'성명'}` 을 머리말과 서명란에 각각 두는 템플릿이 실제로 그렇다).
        누름틀과 슬롯에 같은 이름이 있으면 누름틀 쪽을 대표로 본다.
    """
    merged: dict = {}
    order: list = []
    for section_name, xml_bytes in iter_section_xml(hwpx_bytes):
        root = parse_xml(xml_bytes)
        for occ in _ordered_occurrences(root, section_name, include_types, include_slots):
            if occ.name not in merged:
                merged[occ.name] = []
                order.append(occ.name)
            merged[occ.name].append(occ)

    specs = []
    for name in order:
        occs = merged[name]
        filled_values = [o.current_text.strip() for o in occs if o.filled]
        click_here = next((o for o in occs if o.field_type == CLICK_HERE_TYPE), None)
        representative = click_here or occs[0]
        specs.append(
            FieldSpec(
                name=name,
                guide=next((o.guide for o in occs if o.guide), ""),
                field_type=representative.field_type,
                occurrences=len(occs),
                filled=all(o.filled for o in occs),
                current_value=filled_values[0] if filled_values else "",
                source=SOURCE_FIELD if click_here is not None else SOURCE_SLOT,
            )
        )
    return specs


def bare_brace_samples(hwpx_bytes: bytes, limit: int = 10) -> list:
    """따옴표가 없어 채울 자리로 보지 않은 `{…}` 표본 (중복 제거, 등장 순서).

    `POST /templates` 응답에 경고로 싣는다. 관리자가 따옴표를 빠뜨렸는지, 아니면
    값 안내를 일부러 적어 둔 것인지는 사람만 안다 — 코드는 알리기만 한다.

    Raises:
        TemplateError: ZIP/XML 손상.
    """
    found: list = []
    for _, xml_bytes in iter_section_xml(hwpx_bytes):
        root = parse_xml(xml_bytes)
        for para in root.iter(_PARA):
            for raw in bare_braces(para):
                cleaned = raw.strip()
                if cleaned and cleaned not in found:
                    found.append(cleaned)
                    if len(found) >= limit:
                        return found
    return found


# ─────────────────────────────────────────────────────────────
# 채우기
# ─────────────────────────────────────────────────────────────
def normalize_text(value) -> str:
    """문자열로 만들고 줄바꿈을 평탄화한다.

    `<hp:t>` 안의 `\\n` 은 문단 분리가 아니라 그냥 글자다 — 그대로 두면 한/글에서
    한 줄로 붙어 보이고 마크다운 미리보기에서는 문단이 갈린다. 채우기와 미리보기가
    같은 규칙을 써야 화면과 파일이 어긋나지 않는다.
    """
    text = str(value if value is not None else "")
    return text.replace("\r\n", "\n").replace("\n", NEWLINE_REPLACEMENT)


def _write_occurrence(occ: FieldOccurrence, value: str) -> None:
    """begin~end 사이 텍스트를 value 로 교체한다.

    첫 hp:t 에 값을 넣고 나머지는 비운다 (run 서식은 deepcopy 없이 그대로 보존).
    사이에 hp:t 가 하나도 없으면 begin run 을 복제해 새 run/t 를 삽입한다 —
    새 run 을 맨바닥에서 만들면 charPrIDRef 가 빠져 서식이 깨진다 (§3.4 패턴).
    """
    if occ.text_nodes:
        occ.text_nodes[0].text = value
        for t in occ.text_nodes[1:]:
            t.text = ""
        return

    begin_run = occ.begin_elem.getparent().getparent()  # fieldBegin ← ctrl ← run
    if begin_run is None or begin_run.tag != _RUN:
        return
    new_run = deepcopy(begin_run)
    for child in list(new_run):
        new_run.remove(child)
    t = etree.SubElement(new_run, _TEXT)
    t.text = value
    parent = begin_run.getparent()
    parent.insert(parent.index(begin_run) + 1, new_run)


def _fill_scalar_tokens(root, values: dict, written: set, seen: set) -> None:
    """모든 hp:t 텍스트에서 {{token}} 치환. 값이 없는 토큰은 건드리지 않는다.

    치환 전에 발견한 토큰명을 `seen` 에 모은다 — 그래야 호출부가 "템플릿에 있는 이름"을
    판단하려고 zip 을 다시 풀지 않는다.
    """
    for t in root.iter(_TEXT):
        if not t.text or "{{" not in t.text:
            continue
        new_text = t.text
        for name in set(TOKEN_RE.findall(new_text)):
            seen.add(name)
            if name not in values:
                continue
            new_text = new_text.replace(
                "{{" + name + "}}", normalize_text(values[name])
            )
            written.add(name)
        t.text = new_text  # lxml 이 escape 자동 처리


def _strip_echoed_name(name: str, value: str) -> str:
    """LLM 이 값에 항목명을 다시 붙여 보낸 경우 떼어낸다.

    `{'제목'}` 자리에 `제목: 실적 보고` 가 들어오면 문서가 `제 목 : 제목: 실적 보고` 가
    된다. 프롬프트로도 금지하지만(규칙 10), 지시만으로 보장하지 않는다 — CLAUDE.md §5.
    """
    text = value.strip()
    for separator in (":", "："):
        prefix = name + separator
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def _fill_slots(root, section_name: str, values: dict, written: set, known: set, missing: set) -> None:
    """섹션의 슬롯을 값으로 바꾼다. **값이 없으면 `{…}` 표기를 지운다.**

    지우는 이유는 라벨 방식에서 명세를 지우던 것과 같다 — `{'제목', 16pt}` 는 작성
    지시문이라 산출 문서에 남아선 안 된다. 부분 초안이어도 마찬가지다. 대신 중괄호 밖
    텍스트(`제 목 : `)는 남으므로, 한/글에서 이어 쓸 자리는 그대로 보인다.
    """
    for para, occurrences in iter_slot_paragraphs(root, section_name):
        texts: list = []
        for occ in occurrences:
            known.add(occ.name)
            if occ.name in values:
                texts.append(_strip_echoed_name(occ.name, values[occ.name]))
                written.add(occ.name)
            else:
                texts.append("")
                missing.add(occ.name)
        rewrite_slots(para, occurrences, texts)


def fill_template(hwpx_bytes: bytes, values: dict, include_slots: bool = True) -> FillResult:
    """values 로 슬롯·누름틀·{{token}} 을 채운 새 hwpx 바이트를 만든다.

    값이 없는 누름틀은 안내문 상태로 그대로 남긴다 (부분 초안 허용 — 다운로드 후
    사용자가 한/글에서 이어서 작성). 값이 없는 **슬롯은 표기를 지운다** — `{'제목', 16pt}`
    는 작성 지시문이라 산출 문서에 남아선 안 되고, 중괄호 밖 라벨은 어차피 남는다.

    Args:
        values: {항목명(또는 토큰명): 값}. 값은 문자열로 정규화된다.
        include_slots: 본문 슬롯(`{'항목명', …}`)도 채울지.

    Raises:
        TemplateError: ZIP/XML 손상.
    """
    str_values = {
        k: normalize_text(v)
        for k, v in values.items()
        if v is not None and not isinstance(v, (list, dict))
    }

    written: set = set()
    missing: set = set()
    known_names: set = set()
    leftover: set = set()

    buf = io.BytesIO()
    with open_hwpx(hwpx_bytes) as src_zip, zipfile.ZipFile(
        buf, "w", zipfile.ZIP_DEFLATED
    ) as dst:
        for item in src_zip.infolist():
            data = src_zip.read(item.filename)
            if section_order(item.filename) is not None:
                root = parse_xml(data)
                for occ in _collect_occurrences(root, item.filename):
                    if occ.field_type != CLICK_HERE_TYPE:
                        continue
                    known_names.add(occ.name)
                    if occ.name in str_values:
                        _write_occurrence(occ, str_values[occ.name])
                        written.add(occ.name)
                    elif not occ.filled:
                        missing.add(occ.name)
                if include_slots:
                    _fill_slots(root, item.filename, str_values, written, known_names, missing)
                _fill_scalar_tokens(root, str_values, written, known_names)
                data = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
                # 남은 토큰은 방금 만든 XML 에서 센다 (결과 zip 을 다시 풀지 않는다)
                leftover.update(TOKEN_RE.findall(data.decode("utf-8", errors="replace")))
            compress = (
                zipfile.ZIP_STORED if item.filename == "mimetype"
                else zipfile.ZIP_DEFLATED  # mimetype 무압축 규약 (§3.1)
            )
            dst.writestr(item.filename, data, compress_type=compress)

    unknown = [k for k in str_values if k not in written and k not in known_names]
    # 같은 이름이 여러 자리(누름틀+라벨)에 있을 때, 한 자리라도 채웠으면 부족이 아니다
    missing -= written
    return FillResult(
        hwpx_bytes=buf.getvalue(),
        written_fields=sorted(written),
        missing_fields=sorted(missing),
        unknown_keys=sorted(unknown),
        leftover_tokens=sorted(leftover),
    )
