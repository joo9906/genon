"""`final_preprocessor.py` 를 세 조각에서 **기계적으로** 만든다.

    python onprem/preprocessor/build_final_preprocessor.py

## 합치는 순서와 그 결과

    PART 1  genos_files/attach_processor.py        (첨부용)
    PART 2  onprem/preprocessor/hwpx_preprocessor.py
    PART 3  onprem/preprocessor/router_template.py

**한 네임스페이스이므로 뒤엣것이 앞엣것을 덮는다.** 그래서 순서 자체가 계약이다.

## 지능형은 2026-09-01 에 걷어냈다

그전에는 `genos_files/intelligence_processor.py` 가 PART 2 로 들어가 pdf·ppt·엑셀·
이미지를 받았다. **그 경로가 실환경에서 동작하지 않아 통째로 뺐다.** 뺀 결과 병합은
훨씬 단순해졌다 — 겹침 24개(제거 13 / 개명 8 / 보존 3)와 그것을 지키던 `_classify_overlap`
이 전부 없어졌다. 지금 겹치는 것은 셋뿐이다:

| 이름 | 어디서 겹치나 | 어떻게 했나 |
|---|---|---|
| `DocumentProcessor` | attach·hwpx·router 셋 다 정의한다 | attach → `AttachDocumentProcessor`, hwpx → `HwpxDocumentProcessor`. **router 것이 진입점이라 그 이름을 가진다** |
| `Document` | attach 는 langchain 것을 import, hwpx 는 같은 이름의 데이터클래스를 정의 | hwpx → `HwpxDocument`. hwpx 가 뒤라 그대로 두면 attach 의 20개 호출부가 **호출 시점에** 터진다(import 는 통과한다) |
| `_log` | attach·hwpx 둘 다 `logging.getLogger(__name__)` | 그대로 둔다 — 한 모듈이라 `__name__` 이 같아 **결국 같은 객체**다 |

**되살릴 일이 생기면** `git show f7c4aec:onprem/preprocessor/build_final_preprocessor.py`
에 겹침 처리표와 `_drop_definitions`·`_classify_overlap` 이 그대로 있다.

## 조각을 하나 더 붙이려면 — 고치는 자리 **아홉**

지능형을 되살리든 새 벤더를 넣든 절차가 같다. **순서대로 고친다** — 앞을 건너뛰면
뒤에서 나는 오류가 엉뚱한 곳을 가리킨다.

| # | 자리 | 무엇을 |
|---|---|---|
| 1 | `_XXX_SRC` (이 파일 위쪽) | 원본 경로 상수 |
| 2 | `_XXX_RENAME` | **`DocumentProcessor` 를 반드시 비킨다.** 아래 "순서" 참고 |
| 3 | `_ALLOWED_DUPLICATES` / 겹침 처리 | 새 조각이 기존 것과 최상위 정의를 겹치면 — 아래 표 |
| 4 | `main()` 읽기 | `_strip_future` → `_rename_verified` → (지웠으면 `_annotate_renames`) |
| 5 | `main()` 의 `parts` | `_BANNER` + (벤더면) `_GUARD_HEAD`/`_GUARD_TAIL` + `_indent(...)` |
| 6 | `_verify()` | `try` 블록 **개수**, `_assert_ast_equal` 한 줄, `named` 딕셔너리 한 줄 |
| 7 | `_HEADER` | 생성물 머리말(라우팅 표·PART 순서) |
| 8 | `router_template.py` | 엔진 상수·`_FP_ROUTES`·`_FP_ENGINES`·`_fp_engine_error`·`_FP_CONFIG_*`·`_build` 의 factory·`_fp_enable_outline` |
| 9 | `onprem/test/check_final_preprocessor.py` | 대역·라우팅·겹침 판정 |

**순서가 계약이다: 벤더들 → hwpx → 라우터.** 이유가 셋이고 전부 뒤집으면 조용히 깨진다.

- **라우터가 마지막**이어야 그 `DocumentProcessor` 가 살아남는다. GenOS 는 파일이
  정의하는 그 이름의 클래스를 실행하므로, 다른 것이 남으면 **라우팅이 통째로 사라지는데
  적재는 성공으로 보인다.**
- **hwpx 는 가드 밖**이다. 벤더 스택이 없어도 hwpx 경로와 회귀 점검이 돌아야 한다.
- **hwpx 가 벤더보다 뒤**라 `Document` 같은 이름이 벤더 것을 덮는다 → `_HWPX_RENAME`.
  이 실패는 **import 를 통과하고 호출할 때** 난다.

**겹치는 최상위 정의를 만나면** 셋 중 하나다(판정은 손으로 읽지 말고 AST 로 대조할 것):

| 상황 | 처리 | 주의 |
|---|---|---|
| 본문이 **같다** | 앞 조각 쪽을 지운다(죽은 코드) | `_drop_definitions`·`_DROP_NOTE` 를 되살려야 한다 — 지능형을 뺄 때 지웠다. `git show f7c4aec:…build_final_preprocessor.py` |
| 본문이 **다르다** | 개명해 **둘 다 남긴다** | 지우면 앞 조각이 뒤 조각 판본을 쓰게 되어 **동작이 바뀐다** |
| 겹쳐도 **같은 물건** | `_ALLOWED_DUPLICATES` | `_log` 처럼 근거가 있을 때만. 넉넉히 두면 진짜 충돌을 놓친다 |

**지우지 못하는 것 둘**(둘 다 지능형 시절에 실제로 밟았다):

- **최상위 직계가 아닌 정의** — `try:`/`except:` 안이면 본문만 빼면 **빈 블록이 남아
  SyntaxError**. `_drop_definitions` 에 가드가 있었다.
- **클래스 본문이 정의 시점에 읽는 값** — 지우면 **등록 즉시 `NameError`** 다.

## 네 가지 함정을 기계가 막는다

1. **`from __future__ import annotations` 는 파일 맨 앞에만 온다.** 세 원본이 각각 갖고
   있고 `try:` 안에도 못 들어간다. 떼어내 병합 파일 맨 앞에 한 번만 둔다.
2. **들여쓰기가 문자열 내용을 바꾼다.** attach 조각은 통째로 `try:` 안으로 들어가는데
   여러 줄 문자열이 27개다. 줄마다 공백을 붙이면 그 **내용이 바뀐다.** `tokenize` 로
   문자열 안쪽 줄을 가려내 건드리지 않는다.
3. **정규식으로 이름을 갈면 문자열 리터럴까지 바뀐다.** attach 에도
   `[DocumentProcessor]` 로 시작하는 로그 문자열이 있다. 개명은 **토큰 단위**로
   하고(문자열·주석은 `tokenize` 가 다른 종류로 주므로 안 닿는다), 속성 접근(`.name`)은
   건너뛴다.
4. **개명이 의도한 것만 건드렸는지**를 **독립 구현 둘로 교차 확인**한다 — 출력은 토큰
   치환으로 만들고(주석·서식이 그대로 남아야 한다), 검증은 AST 트랜스포머로 따로 만들어
   `ast.dump` 를 맞춘다. 토큰 쪽이 속성이나 키워드 인자를 잘못 건드리면 여기서 갈린다.

## 검증

- **PART 1·2 를 원본과 AST 로 대조한다** — 개명한 것을 뺀 나머지 문장이 원본과 하나씩
  같아야 한다. 문자열이 한 글자만 달라져도 걸린다.
- **조각 사이 이름 겹침**을 다시 센다. 허용 목록 밖이 겹치면 빌드를 세운다.
- **선택 의존 가드를 다시 벗겨 원본 AST 와 맞춘다** (`_guard_optional_imports`) —
  스텁을 끼우며 다른 문장이 바뀌거나 밀렸으면 걸린다. 근거는 `_ATTACH_OPTIONAL_IMPORTS`
  위 주석.
- 눈으로 대조할 수 있는 크기가 아니다(생성물 5천 줄대).
"""

from __future__ import annotations

import ast
import io
import os
import tokenize

_HERE = os.path.dirname(os.path.abspath(__file__))
_ONPREM = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_ONPREM)

_ATTACH_SRC = os.path.join(_ROOT, "genos_files", "attach_processor.py")
_HWPX_SRC = os.path.join(_HERE, "hwpx_preprocessor.py")
_ROUTER_SRC = os.path.join(_HERE, "router_template.py")
_OUT = os.path.join(_HERE, "final_preprocessor.py")

_FUTURE_LINE = "from __future__ import annotations"

# ---------------------------------------------------------------------------
# 개명표 — **진입점 이름 `DocumentProcessor` 를 누가 갖느냐**가 전부다
#
# 세 조각이 다 그 이름의 클래스를 정의하는데, GenOS 가 실행하는 것은 **마지막에 남는
# 하나**다. 라우터 것이 남아야 하므로 앞의 둘을 비킨다.
# ---------------------------------------------------------------------------

_ATTACH_RENAME = {"DocumentProcessor": "AttachDocumentProcessor"}

_HWPX_RENAME = {
    "DocumentProcessor": "HwpxDocumentProcessor",
    # attach 가 쓰는 langchain `Document` 를 덮지 않게. hwpx 가 뒤라 그대로 두면
    # attach 의 20개 호출부가 **호출 시점에** 터진다(import 는 통과한다).
    "Document": "HwpxDocument",
}

# 두 조각이 똑같이 정의해도 되는 이름. `_log` 는 양쪽 다 `logging.getLogger(__name__)`
# 이고 합치면 `__name__` 이 같으므로 **결국 같은 객체**다.
#
# 여기 없는 이름이 겹치면 빌드를 세운다. 목록을 넉넉히 두지 않는 것이 요점이다 —
# GenOS 가 참조 사본을 갱신하며 hwpx 와 같은 이름을 새로 정의하면 그 순간 잡혀야 한다.
# (같은 모듈에서 같은 이름을 import 하는 것은 덮여도 같은 물건이라 `_verify` 가 따로
# 넘긴다. 이 목록은 **정의가 겹치는 것** 전용이다.)
_ALLOWED_DUPLICATES = {"_log"}


# ---------------------------------------------------------------------------
# 사이트 설치본에 없는 벤더 모듈 — 그 import **하나만** 가드로 감싼다 (2026-09-02)
#
# 실환경에서 pdf 적재가 이 오류로 막혔다:
#
#     ModuleNotFoundError: No module named
#         'genon.preprocessor.facade.enrichment.page_description'
#
# `genos_files/attach_processor.py`(v.2.2.4 참조 사본)가 그 모듈을 **최상위에서** 들여
# 오는데 사이트에 설치된 `genon.preprocessor` 에는 없다. 그러면 PART 1 이 통째로
# `_GUARD_HEAD` 에 걸려 `_FP_ATTACH_IMPORT_ERROR` 가 서고, 라우터가 **hwpx 아닌 전
# 형식을 거부한다.** hwpx 는 가드 밖이라 그대로 돌기 때문에 이 실패는 "pdf 만 안 되는"
# 얼굴로 나타난다 — 원인이 import 한 줄이라는 것이 드러나지 않는다.
#
# **PPT 페이지 단위 이미지 설명 전용 심볼이다.** 쓰는 자리가 둘뿐이고
# (`attach_processor.py:1831` 옵션 파싱 · `:2050` PPT→PDF 경로) pdf 경로는 지나지
# 않는다. 그래서 없을 때 `enabled=False` 스텁으로 떨어뜨리면 **PPT 페이지 설명만
# 빠지고**(벤더의 `page_description.enable=false` 와 같은 상태) 나머지 전 형식이 살아난다.
#
# ## 벤더 원본에서 벗어나는 **두 번째** 자리다
#
# 첫째는 `_ATTACH_RENAME`(진입점 개명)이고 이게 둘째다. 이관 절차(`transfer/`)는 벤더
# 절반을 **사이트 자기 파일**로 뜨므로 그쪽에는 이 가드가 필요 없다 — 사이트 파일은 그
# 사이트 패키지와 짝이 맞는다. 이 가드는 **우리가 만든 `final_preprocessor.py` 를 그대로
# 등록할 때**를 위한 것이다.
#
# ## 다음 오류가 나도 반사적으로 여기 더하지 말 것
#
# 가드는 **첫 실패에서 멈춘다** — 뒤에 또 없는 모듈이 있으면 그것이 다음 오류로 나온다.
# 그때는 목록을 늘리기 전에 사이트 패키지 버전을 확인한다(어긋난 심볼이 여럿이면 판본을
# 맞추는 것이 답이다). 특히 `:460` 의 `guardrail` 은 **민감정보 마스킹(#315)** 이 걸린
# 자리라 스텁으로 덮으면 마스킹이 **조용히** 빠진다 — 여기 넣을 것이 아니다.
# ---------------------------------------------------------------------------

_PAGE_DESCRIPTION_STUB = """\
class PageDescriptionOptions:
    # 모듈이 없는 설치본에서는 `enabled=False` 로 둔다 — 호출부가 이 값으로
    # `generate_page_images`(`:2009`)와 로그(`:2084`)를 정하므로 속성이 있어야 한다.
    enabled = False
    images_scale = 1.0

    @classmethod
    def from_config(cls, *_args, **_kwargs):
        return cls()


def describe_pages(_document, _options, page_texts=None, **_kwargs):
    # 빈 dict = 설명 0건. 호출부(`:2063`)가 native text 만으로 페이지 청크를 만든다.
    return {}
"""

_ATTACH_OPTIONAL_IMPORTS = (
    {
        "module": "genon.preprocessor.facade.enrichment.page_description",
        "names": ("PageDescriptionOptions", "describe_pages"),
        "stub": _PAGE_DESCRIPTION_STUB,
    },
)


# ---------------------------------------------------------------------------
# 원본 읽기·해석
# ---------------------------------------------------------------------------


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _strip_future(src: str, origin: str) -> str:
    lines = src.splitlines(keepends=True)
    hits = [i for i, line in enumerate(lines) if line.strip() == _FUTURE_LINE]
    if len(hits) != 1:
        raise SystemExit(f"[build] {origin}: future import 가 {len(hits)}개다(1개여야 한다)")
    lines[hits[0]] = ""
    return "".join(lines)


def _toplevel_defs(tree: ast.Module) -> dict:
    """최상위 이름 → 그 이름을 마지막으로 묶는 문장 노드."""
    found: dict = {}

    def walk(body: list) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found[node.name] = node
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found[target.id] = node
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                found[node.target.id] = node
            elif isinstance(node, (ast.Try, ast.If)):
                walk(node.body)
                walk(node.orelse)
                walk(getattr(node, "finalbody", []))
                for handler in getattr(node, "handlers", []):
                    walk(handler.body)

    walk(tree.body)
    return found


def _toplevel_names(body: list) -> dict:
    """최상위 이름 → 출처. `("def",)` 이거나 `("import", 모듈, 원래이름)`.

    **정의와 import 를 갈라 두는 것이 요점이다.** 두 조각이 같은 모듈에서 같은 이름을
    import 하는 것(`from docling... import DocChunk`)은 겹쳐도 결과가 같아 무해하고,
    실제로 attach ↔ intelligent 사이에 50개 넘게 있다. 위험한 것은 **정의가 겹치는
    것**과 **정의가 import 에 덮이는 것**이다 — 그건 조용히 다른 물건을 쓰게 만든다.
    """
    names: dict = {}
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names[node.name] = ("def",)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names[target.id] = ("def",)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names[node.target.id] = ("def",)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                names[bound] = ("import", alias.name, alias.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound = alias.asname or alias.name
                names[bound] = ("import", node.module or "", alias.name)
        elif isinstance(node, (ast.Try, ast.If)):
            for branch in (node.body, node.orelse, getattr(node, "finalbody", [])):
                names.update(_toplevel_names(branch))
            for handler in getattr(node, "handlers", []):
                names.update(_toplevel_names(handler.body))
    return names


# ---------------------------------------------------------------------------
# 변환 — 개명 (출력은 토큰 치환, 검증은 AST 트랜스포머)
# ---------------------------------------------------------------------------


def _rename_tokens(src: str, mapping: dict) -> str:
    """NAME 토큰만 바꾼다. 문자열·주석은 다른 토큰 종류라 닿지 않는다.

    `.name` 형태의 속성 접근은 건너뛴다 — 다른 객체의 같은 이름 속성까지 바꾸면
    **그 호출이 조용히 사라진다.**
    """
    if not mapping:
        return src
    edits: dict = {}
    previous = None
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.NAME and tok.string in mapping:
            if not (previous is not None and previous.type == tokenize.OP and previous.string == "."):
                edits.setdefault(tok.start[0], []).append(
                    (tok.start[1], tok.end[1], mapping[tok.string])
                )
        if tok.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT,
                            tokenize.DEDENT):
            previous = tok

    lines = src.splitlines(keepends=True)
    for row, row_edits in edits.items():
        line = lines[row - 1]
        for start, end, replacement in sorted(row_edits, reverse=True):
            line = line[:start] + replacement + line[end:]
        lines[row - 1] = line
    return "".join(lines)


class _RenameTransformer(ast.NodeTransformer):
    """검증 전용 **독립 구현.** 출력은 이걸로 만들지 않는다(주석·서식이 날아간다)."""

    def __init__(self, mapping: dict) -> None:
        self.mapping = mapping

    def visit_Name(self, node):
        node.id = self.mapping.get(node.id, node.id)
        return node

    def _rename_def(self, node):
        node.name = self.mapping.get(node.name, node.name)
        self.generic_visit(node)
        return node

    visit_FunctionDef = _rename_def
    visit_AsyncFunctionDef = _rename_def
    visit_ClassDef = _rename_def

    def visit_arg(self, node):
        node.arg = self.mapping.get(node.arg, node.arg)
        return node

    def visit_alias(self, node):
        if node.asname:
            node.asname = self.mapping.get(node.asname, node.asname)
        else:
            node.name = self.mapping.get(node.name, node.name)
        return node

    def visit_Global(self, node):
        node.names = [self.mapping.get(n, n) for n in node.names]
        return node

    def visit_Nonlocal(self, node):
        node.names = [self.mapping.get(n, n) for n in node.names]
        return node


def _rename_verified(src: str, mapping: dict, origin: str) -> str:
    """토큰 치환으로 만들고, AST 트랜스포머와 결과가 같은지 교차 확인한다."""
    if not mapping:
        return src
    renamed = _rename_tokens(src, mapping)
    want = _RenameTransformer(dict(mapping)).visit(ast.parse(src))
    if ast.dump(ast.parse(renamed)) != ast.dump(want):
        raise SystemExit(
            f"[build] {origin}: 개명 결과가 AST 트랜스포머와 다르다 "
            "(토큰 치환이 속성·키워드 인자를 건드렸을 수 있다)"
        )
    return renamed


_RENAME_NOTE = (
    "# [병합 개명] `{old}` → `{new}` — 세 조각이 다 `DocumentProcessor` 를 정의한다.\n"
    "#             GenOS 가 실행하는 것은 마지막에 남는 하나라 라우터 것에 자리를 내준다.\n"
)


def _annotate_renames(src: str, mapping: dict) -> str:
    """개명한 정의 위에 표식 주석을 한 줄 붙인다."""
    tree = ast.parse(src)
    defs = _toplevel_defs(tree)
    marks = []
    for old, new in mapping.items():
        node = defs.get(new)
        if node is None:
            continue
        marks.append((node.lineno, old, new))
    lines = src.splitlines(keepends=True)
    for lineno, old, new in sorted(marks, reverse=True):
        lines.insert(lineno - 1, _RENAME_NOTE.format(old=old, new=new))
    return "".join(lines)


# ---------------------------------------------------------------------------
# 변환 3 — 들여쓰기 (문자열 안쪽은 건드리지 않는다)
# ---------------------------------------------------------------------------


def _string_interior_lines(src: str) -> set:
    interior = set()
    fstring_middle = getattr(tokenize, "FSTRING_MIDDLE", -1)
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type not in (tokenize.STRING, fstring_middle):
            continue
        if tok.end[0] > tok.start[0]:
            interior.update(range(tok.start[0] + 1, tok.end[0] + 1))
    return interior


def _indent(src: str, prefix: str = "    ") -> str:
    interior = _string_interior_lines(src)
    out = []
    for number, line in enumerate(src.splitlines(keepends=True), start=1):
        out.append(line if (number in interior or not line.strip()) else prefix + line)
    return "".join(out)


# ---------------------------------------------------------------------------
# 변환 4 — 선택 의존 import 가드 (근거는 `_ATTACH_OPTIONAL_IMPORTS` 위 주석)
# ---------------------------------------------------------------------------


def _guard_module(node) -> str | None:
    """**우리가** 씌운 가드면 그 모듈 이름, 아니면 `None`.

    원본에도 같은 모양이 있다(`try: from genos_utils import upload_files` /
    `except ImportError:`). 모양만 보고 벗기면 **원본 가드까지 벗겨 놓고 "원본과
    같다" 고 판정**하므로, 호출부가 모듈 이름으로 한 번 더 거른다.
    """
    if not isinstance(node, ast.Try) or len(node.body) != 1 or len(node.handlers) != 1:
        return None
    inner = node.body[0]
    if not isinstance(inner, ast.ImportFrom):
        return None
    caught = node.handlers[0].type
    if not (isinstance(caught, ast.Name) and caught.id == "ImportError"):
        return None
    return inner.module


def _guard_optional_imports(src: str, specs: tuple, origin: str) -> str:
    """최상위 `from <module> import ...` 를 `try/except ImportError` + 스텁으로 감싼다.

    출력은 **줄 단위 치환**으로 만든다(주석·서식이 그대로 남아야 한다). 검증은
    **가드를 다시 벗겨 원본 AST 와 맞추는** 것으로 한다 — 스텁을 끼우며 다른 문장이
    바뀌거나 밀리면 거기서 걸린다.
    """
    if not specs:
        return src

    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    edits = []

    for spec in specs:
        module = spec["module"]
        targets = [
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module == module
        ]
        if len(targets) != 1:
            raise SystemExit(
                f"[build] {origin}: '{module}' 최상위 import 가 {len(targets)}개다"
                "(1개여야 한다). 참조 사본이 갱신됐다면 이 가드가 아직 필요한지부터 볼 것"
            )
        node = targets[0]
        bound = tuple(alias.asname or alias.name for alias in node.names)
        if bound != tuple(spec["names"]):
            raise SystemExit(
                f"[build] {origin}: '{module}' 이 세우는 이름이 {bound} 다"
                f"(기대 {tuple(spec['names'])}). 스텁을 같이 고칠 것"
            )
        edits.append(
            (
                node.lineno - 1,
                node.end_lineno,
                "try:\n"
                + _indent("".join(lines[node.lineno - 1 : node.end_lineno]))
                + "except ImportError:\n"
                + _indent(spec["stub"].strip("\n") + "\n"),
            )
        )

    for start, end, replacement in sorted(edits, reverse=True):
        lines[start:end] = [replacement]
    patched = "".join(lines)

    wanted = {spec["module"]: spec for spec in specs}
    seen = set()
    unwrapped = []
    for node in ast.parse(patched).body:
        module = _guard_module(node)
        if module in wanted:
            stub_names = set(_toplevel_names(node.handlers[0].body))
            if stub_names != set(wanted[module]["names"]):
                raise SystemExit(
                    f"[build] {origin}: '{module}' 스텁이 세우는 이름이"
                    f" {sorted(stub_names)} 다(기대 {sorted(wanted[module]['names'])})"
                    " — import 가 실패하는 설치본에서 NameError 가 난다"
                )
            seen.add(module)
            unwrapped.extend(node.body)
        else:
            unwrapped.append(node)

    if seen != set(wanted):
        raise SystemExit(
            f"[build] {origin}: 가드가 안 걸린 모듈 {sorted(set(wanted) - seen)}"
        )
    if ast.dump(ast.Module(body=unwrapped, type_ignores=[])) != ast.dump(
        ast.Module(body=tree.body, type_ignores=[])
    ):
        raise SystemExit(f"[build] {origin}: 가드를 벗기면 원본과 같아야 하는데 다르다")
    return patched


# ---------------------------------------------------------------------------
# 검증
# ---------------------------------------------------------------------------


def _assert_ast_equal(expected: list, actual: list, label: str) -> None:
    if len(actual) < len(expected):
        raise SystemExit(
            f"[build] {label}: 문장 수가 줄었다 (기대 {len(expected)} > 생성 {len(actual)})"
        )
    for index, (want, got) in enumerate(zip(expected, actual)):
        if ast.dump(want) != ast.dump(got):
            raise SystemExit(
                f"[build] {label}: {index}번째 최상위 문장이 다르다 "
                f"(기대 쪽 {getattr(want, 'lineno', '?')}줄)"
            )


def _verify(merged: str, parts: dict) -> None:
    tree = ast.parse(merged)
    top = tree.body

    tries = [node for node in top if isinstance(node, ast.Try)]
    if len(tries) != 1:
        raise SystemExit(f"[build] 최상위 try 블록이 {len(tries)}개다(1개여야 한다)")

    _assert_ast_equal(ast.parse(parts["attach"]).body, tries[0].body, "PART 1(첨부용)")

    hwpx_expected = ast.parse(parts["hwpx"]).body
    start = None
    for index, node in enumerate(top):
        if ast.dump(node) == ast.dump(hwpx_expected[0]):
            start = index
            break
    if start is None:
        raise SystemExit("[build] PART 2(hwpx)의 첫 문장을 병합 파일에서 찾지 못했다")
    _assert_ast_equal(hwpx_expected, top[start:], "PART 2(hwpx)")

    named = {
        "PART 1(첨부용)": _toplevel_names(ast.parse(parts["attach"]).body),
        "PART 2(hwpx)": _toplevel_names(hwpx_expected),
        "PART 3(라우터)": _toplevel_names(ast.parse(parts["router"]).body),
    }
    labels = list(named)
    clashes = {}
    for index, left in enumerate(labels):
        for right in labels[index + 1 :]:
            bad = []
            for name in set(named[left]) & set(named[right]):
                if name in _ALLOWED_DUPLICATES:
                    continue
                origin_l, origin_r = named[left][name], named[right][name]
                # 같은 모듈에서 같은 이름을 가져온 것이면 덮여도 같은 물건이다.
                if origin_l[0] == "import" and origin_l == origin_r:
                    continue
                bad.append(f"{name}({origin_l[0]}↔{origin_r[0]})")
            if bad:
                clashes[f"{left} <-> {right}"] = sorted(bad)
    if clashes:
        raise SystemExit(f"[build] 조각 사이 최상위 이름이 겹친다(뒤엣것이 앞엣것을 덮는다): {clashes}")

    classes = [node.name for node in top if isinstance(node, ast.ClassDef)]
    for required in ("DocumentProcessor", "HwpxDocumentProcessor"):
        if required not in classes:
            raise SystemExit(f"[build] {required} 가 최상위에 없다")


# ---------------------------------------------------------------------------
# 조립
# ---------------------------------------------------------------------------

_BANNER = """# ===========================================================================
# {title}
# ===========================================================================
"""

_GUARD_HEAD = """# 통째로 try 안에 있다. docling/genon 스택이 없는 환경에서도 이 파일이 import 되고
# hwpx 경로가 살아 있어야 하기 때문이다 — 무거운 의존 하나가 빠졌을 때 hwpx 적재까지
# 같이 죽으면 안 되고, 회귀 점검이 로컬(표준 라이브러리 + lxml)에서 이 파일을 태울 수
# 있어야 한다. 실패 사실은 숨기지 않는다 — 라우터가 그대로 드러낸다.
{flag} = None
{trace} = ""
try:
"""

_GUARD_TAIL = """
except Exception as _fp_exc:  # noqa: BLE001 - 무엇이 빠졌든 hwpx 경로는 살린다
    {flag} = _fp_exc
    {trace} = traceback.format_exc()
"""

_HEADER = '''"""GenOS 통합 전처리기 — hwpx 는 우리 파서, 나머지는 첨부용 벤더 처리기로.

**이 파일은 생성물이다. 직접 고치지 말 것** — 고칠 자리는 넷 중 하나이고, 고친 뒤
`python onprem/preprocessor/build_final_preprocessor.py` 로 다시 만든다:

| 고칠 것 | 자리 |
|---|---|
| hwpx 파싱·청킹 | `onprem/preprocessor/hwpx_preprocessor.py` |
| 라우팅·폴백·스키마 정렬 | `onprem/preprocessor/router_template.py` |
| hwpx 아닌 전 형식의 처리 | `genos_files/attach_processor.py` (GenOS 참조 사본) |
| 병합 방식·개명 | `onprem/preprocessor/build_final_preprocessor.py` |

## 왜 한 파일인가

GenOS 전처리기 등록은 **소스 파일 하나**를 받아 그 파일이 정의하는 `DocumentProcessor`
를 실행한다. 서로 import 할 수 없으므로(벤더 원본도 같은 이유로 `convert_to_pdf` 를
자기 안에 복제해 두고 있다) 한 등록에서 두 처리기를 쓰려면 한 파일에 있어야 한다.

## 지능형은 2026-09-01 에 뺐다

그전에는 `intelligence_processor.py`(적재용·지능형)가 함께 들어가 pdf·ppt·엑셀·이미지를
받았다. **그 경로가 실환경에서 동작하지 않아 통째로 걷어냈다.** 그 형식들은 이제 전부
첨부용으로 간다.

**pdf 는 계속 처리되고 조/항/호 위계도 그대로 걸린다** — 첨부용 pdf 는 langchain
`Document` 목록으로 오므로 라우터에 어댑터를 하나 더 뒀다(`_fp_langchain_blocks`).
잃은 것은 **표 격자 하나**다: 첨부용 pdf 는 `PyMuPDFLoader` 평문이라 표가 문장으로
풀린다(지능형은 TableFormer 로 격자를 복원했다). 오류는 나지 않고 적재도 되므로 그
사실은 "표를 물어봤는데 답이 이상하다" 로만 드러난다.

## 라우팅

| 입력 | 어디로 | 근거 |
|---|---|---|
| `.hwpx` (내용도 hwpx 컨테이너) | **hwpx 파서** | 표 병합(rowSpan/colSpan)·조문 위계를 지킨다 |
| 그 밖의 전 형식 | 첨부용 | `.hwp`·`.hml`·`.docx` 는 GenosHwp/GenosMsWord **네이티브**, 오디오는 Whisper STT, `.csv`·`.xlsx` 는 TabularLoader, `.ppt(x)` 는 PDF 변환 후 docling, 나머지는 langchain 로더 |

**확장자만 보고 보내지 않는다** — `.hwpx` 는 zip 을 열어 실제로 hwpx 컨테이너인지 본다.
이름만 `.hwpx` 인 파일을 우리 파서에 넣으면 예외가 나고 **그 문서는 검색에서 통째로
사라진다.** 벤더로 보내면 표는 덜 정확해도 적재는 된다.

## 합친 순서가 계약이다 — 뒤엣것이 앞엣것을 덮는다

PART 1 첨부용 → PART 2 hwpx → PART 3 라우터.

셋 다 `DocumentProcessor` 를 정의하는데 GenOS 가 실행하는 것은 **마지막에 남는 하나**
이므로 앞의 둘을 `AttachDocumentProcessor`·`HwpxDocumentProcessor` 로 비켰다. `Document`
도 겹친다 — 첨부용은 langchain 것을 import 하고 hwpx 는 같은 이름의 데이터클래스를
정의한다. hwpx 가 뒤라 그대로 두면 첨부용의 20개 호출부가 **호출 시점에** 터지므로
(import 는 통과한다) hwpx 쪽을 `HwpxDocument` 로 바꿨다. 개명한 자리에 `[병합 개명]`
표식 주석이 있다.

## 벤더 절반이 없는 환경에서도 이 파일은 import 된다

PART 1 은 `try:` 안에 있다. docling·`genon.preprocessor.*` 가 없으면 그 절반만 비활성이
되고 **hwpx 경로는 그대로 돈다.** 비활성 사실은 숨기지 않는다 — 그 엔진으로 가야 할
파일이 들어오면 **사유를 담아 예외를 던진다**(조용히 빈 결과를 내지 않는다).

## 등록 화면에서 더 받는 값

hwpx 경로는 `hwpx_preprocessor.py` 의 값(`chunk_size`·`chunk_overlap`·`outline_mode`·
`file_name`·`extra_metadata`)을, 첨부용 경로는 원본의 값을 그대로 받는다. 라우터 몫:

| 키 | 기본값 | 의미 |
|---|---|---|
| `hwpx_engine` | `auto` | `auto`=hwpx 파서, 실패하면 첨부용으로 폴백(GenosHwp SDK 네이티브라 덜 잃는다) / `native`=폴백 없음 / `attach`=hwpx 도 첨부용으로 |
| `route_overrides` | 없음 | `{{".pdf": "attach"}}` 꼴로 확장자별 라우팅을 덮어쓴다 |
| `align_vector_schema` | `true` | hwpx 레코드에 벤더 예약 필드(`title`·`created_date`·`appendix`·`guardrail_categories`)를 채워 **한 컬렉션 안 메타 스키마를 맞춘다** |
| `outline_mode` | `auto` | **hwpx·pdf·docx 에 걸린다.** `제N조` 를 2개 이상 세면 조/항/호 위계로 청킹하고 `제2장 총칙 > 제5조(목적)` 머리말을 붙인다. 조문 문서가 아니면 벤더 청커 그대로다 |
| `attachment_config_path` | 없음 | 벤더 설정 yaml. 없으면 환경변수 → 벤더 기본 경로 → 이 파일 주변 순으로 찾는다 |

값이 잘못된 타입/범위면 에러를 내지 않고 기본값으로 떨어지되 로그에 남긴다.

## 페이지 번호는 hwpx 경로에 없다

hwpx 는 흐름 문서라 렌더링 전에는 페이지가 정해지지 않는다. 지어내지 않고 `None` 으로
둔다. 페이지·bbox 가 꼭 필요하면 `hwpx_engine="attach"` 로 그 문서만 벤더 경로에 태울
수 있고, 그건 표가 깨지는 쪽이다.
"""

'''


def main() -> None:
    attach_raw = _strip_future(_read(_ATTACH_SRC), "attach_processor.py")
    # 사이트 설치본에 없는 벤더 모듈의 import 를 가드로 감싼다. **개명보다 먼저** 한다 —
    # 아래 개명·표식 검증이 이 결과를 원본으로 삼아야 두 변환이 서로를 가리지 않는다.
    attach_raw = _guard_optional_imports(
        attach_raw, _ATTACH_OPTIONAL_IMPORTS, "attach_processor.py"
    )
    hwpx_raw = _strip_future(_read(_HWPX_SRC), "hwpx_preprocessor.py")

    attach_body = _rename_verified(attach_raw, _ATTACH_RENAME, "attach_processor.py")
    attach_body = _annotate_renames(attach_body, _ATTACH_RENAME)
    # 주석을 끼운 뒤에도 코드가 그대로인지 본다(주석은 AST 에 안 남는다).
    if ast.dump(ast.parse(attach_body)) != ast.dump(
        _RenameTransformer(dict(_ATTACH_RENAME)).visit(ast.parse(attach_raw))
    ):
        raise SystemExit("[build] attach: 표식 주석을 끼우며 코드가 바뀌었다")

    hwpx_body = _rename_verified(hwpx_raw, _HWPX_RENAME, "hwpx_preprocessor.py")

    router_lines = _strip_future(_read(_ROUTER_SRC), "router_template.py").splitlines(keepends=True)
    marker = "# ROUTER-BODY-BEGIN"
    hits = [i for i, line in enumerate(router_lines) if line.strip() == marker]
    if len(hits) != 1:
        raise SystemExit(f"[build] router_template.py 의 '{marker}' 표식 줄이 {len(hits)}개다")
    router_body = "".join(router_lines[hits[0] + 1 :]).lstrip("\n")

    parts = [
        _HEADER,
        _FUTURE_LINE + "\n\n",
        # 라우터가 쓰는 표준 모듈. 벤더 두 조각이 각각 import 하지만 **그 둘은 실패할 수
        # 있고**(try 안이다) 라우터는 그때도 돌아야 한다. os/re/time/zipfile 은 PART 3
        # (hwpx, 가드 밖)이 가져오므로 여기서는 나머지만 세운다.
        "import asyncio\nimport json\nimport traceback\n\n",
        _BANNER.format(title="PART 1 — 첨부용 (genos_files/attach_processor.py, 개명 후)"),
        _GUARD_HEAD.format(flag="_FP_ATTACH_IMPORT_ERROR", trace="_FP_ATTACH_IMPORT_TRACE"),
        _indent(attach_body.lstrip("\n")),
        _GUARD_TAIL.format(flag="_FP_ATTACH_IMPORT_ERROR", trace="_FP_ATTACH_IMPORT_TRACE"),
        "\n\n",
        _BANNER.format(title="PART 2 — hwpx 전용 파서 (onprem/preprocessor/hwpx_preprocessor.py 원문)"),
        hwpx_body.lstrip("\n"),
        "\n\n",
        _BANNER.format(title="PART 3 — 라우터 (onprem/preprocessor/router_template.py 원문)"),
        router_body,
    ]
    merged = "".join(parts)
    if not merged.endswith("\n"):
        merged += "\n"

    _verify(merged, {"attach": attach_body, "hwpx": hwpx_body, "router": router_body})

    with open(_OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(merged)

    original = sum(len(_read(path).splitlines()) for path in (_ATTACH_SRC, _HWPX_SRC))
    print(f"[build] {_OUT}")
    print(
        f"[build] {len(merged.splitlines()):,}줄 — 원본 2벌 {original:,}줄 + 라우터, "
        f"개명 {len(_ATTACH_RENAME) + len(_HWPX_RENAME)}개. AST 대조 통과"
    )


if __name__ == "__main__":
    main()
