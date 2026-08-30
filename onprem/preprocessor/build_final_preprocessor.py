"""`final_preprocessor.py` 를 네 조각에서 **기계적으로** 만든다.

    python onprem/preprocessor/build_final_preprocessor.py

## 합치는 순서와 그 결과

    PART 1  genos_files/attach_processor.py        (첨부용)
    PART 2  genos_files/intelligence_processor.py  (적재용·지능형)
    PART 3  onprem/preprocessor/hwpx_preprocessor.py
    PART 4  onprem/preprocessor/router_template.py

**한 네임스페이스이므로 뒤엣것이 앞엣것을 덮는다.** 그래서 순서 자체가 계약이다 —
attach 와 intelligent 가 최상위 이름 **24개를 둘 다 정의**하는데, 합치면 전부
intelligent 판본이 이긴다. 그 24개를 두 갈래로 갈랐다(판정은 AST 대조, 손으로 읽지
않았다):

| | 개수 | 어떻게 했나 |
|---|---|---|
| 본문이 **완전히 같다** | 16 | **attach 쪽을 지웠다** (14개). 어차피 intelligent 것이 이기므로 지워도 동작이 같다 — 죽은 코드였다 |
| ↳ 그중 정의 시점에 읽히는 것 | 2 | **남겼다.** `HybridChunker` 클래스 본문(attach:1058-1061)이 값을 읽는데, 그 시점은 intelligent 정의보다 **앞**이라 지우면 import 가 `NameError` 로 죽는다 |
| 본문이 **다르다** | 8 | **개명했다.** 지우면 attach 가 intelligent 판본을 쓰게 되어 **동작이 바뀐다** |

지운 자리와 개명한 자리에는 각각 한 줄짜리 표식 주석을 남긴다 — 생성물만 보고도
"여기 원래 뭐가 있었나" 를 알 수 있어야 한다.

`Document` 도 하나 더 있다: attach 는 langchain 의 `Document` 를 import 하고 hwpx 는
같은 이름의 데이터클래스를 정의한다. **hwpx 가 마지막이라 langchain 쪽을 덮어** attach
의 20개 호출부가 전부 깨진다(import 는 통과하고 **호출할 때** 터진다). hwpx 쪽을
`HwpxDocument` 로 개명했다 — 우리 코드이고 참조가 2곳뿐이다.

## 네 가지 함정을 기계가 막는다

1. **`from __future__ import annotations` 는 파일 맨 앞에만 온다.** 세 원본이 각각 갖고
   있고 `try:` 안에도 못 들어간다. 떼어내 병합 파일 맨 앞에 한 번만 둔다.
2. **들여쓰기가 문자열 내용을 바꾼다.** 벤더 두 조각은 통째로 `try:` 안으로 들어가는데
   여러 줄 문자열이 attach 27개·intelligent 33개다. 줄마다 공백을 붙이면 그 **내용이
   바뀐다.** `tokenize` 로 문자열 안쪽 줄을 가려내 건드리지 않는다.
3. **정규식으로 이름을 갈면 문자열 리터럴까지 바뀐다.** intelligent 에는
   `[DocumentProcessor]` 로 시작하는 로그 문자열이 17개 있다. 개명은 **토큰 단위**로
   하고(문자열·주석은 `tokenize` 가 다른 종류로 주므로 안 닿는다), 속성 접근(`.name`)은
   건너뛴다.
4. **개명이 의도한 것만 건드렸는지**를 **독립 구현 둘로 교차 확인**한다 — 출력은 토큰
   치환으로 만들고(주석·서식이 그대로 남아야 한다), 검증은 AST 트랜스포머로 따로 만들어
   `ast.dump` 를 맞춘다. 토큰 쪽이 속성이나 키워드 인자를 잘못 건드리면 여기서 갈린다.

## 검증

- **PART 1·2·3 을 원본과 AST 로 대조한다** — 지운 것·개명한 것을 뺀 나머지 문장이
  원본과 하나씩 같아야 한다. 문자열이 한 글자만 달라져도 걸린다.
- **조각 사이 이름 겹침**을 다시 센다. 허용 목록 밖이 겹치면 빌드를 세운다.
- 눈으로 대조할 수 있는 크기가 아니다(생성물 8천 줄대).
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
_INTEL_SRC = os.path.join(_ROOT, "genos_files", "intelligence_processor.py")
_HWPX_SRC = os.path.join(_HERE, "hwpx_preprocessor.py")
_ROUTER_SRC = os.path.join(_HERE, "router_template.py")
_OUT = os.path.join(_HERE, "final_preprocessor.py")

_FUTURE_LINE = "from __future__ import annotations"

# ---------------------------------------------------------------------------
# attach ↔ intelligent 겹침 처리표
#
# 이 표는 **손으로 적은 기대값이 아니다** — `_classify_overlap()` 이 두 원본을 AST 로
# 대조해 다시 계산하고, 표와 어긋나면 빌드를 세운다. GenOS 가 다음 릴리스에서 어느
# 한쪽을 고치면(같던 것이 달라지면) 그 순간 여기서 잡힌다. 그게 이 표의 존재 이유다.
# ---------------------------------------------------------------------------

# 본문이 같아 attach 쪽을 지우는 것들. intelligent 판본이 이미 이기고 있었으므로
# 지워도 도는 코드는 한 줄도 바뀌지 않는다.
_ATTACH_DROP = (
    "_KNOWN_MAGIC_PREFIXES",
    "_TEXT_ALLOWED_CTRL",
    "_as_dict",
    "_detect_unsupported_file",
    "_is_encrypted_office",
    "_is_encrypted_pdf",
    "_is_protected_hwp",
    "_log",
    "_looks_like_text",
    "_parse_optional_bool",
    "_parse_optional_float",
    "_parse_optional_int",
    "_resolve_tokenizer",
)

# 본문은 같지만 **지우면 안 되는 것들.** attach 의 `HybridChunker` 클래스 본문이
# 정의 시점에 값을 읽는데(attach:1058-1061), 그 시점은 PART 2 보다 앞이다.
# 지우면 import 가 `NameError` 로 죽는다 — 런타임이 아니라 등록 즉시.
_ATTACH_KEEP_DUP = (
    "_DEFAULT_TOKENIZER_LOCAL_PATH",
    "_DEFAULT_TOKENIZER_ID",
    # `upload_files` 는 **다른 이유로** 남긴다. 값은 같지만 정의가
    #     try: from genos_utils import upload_files
    #     except ImportError: upload_files = None
    # 안에 있어서, 그 대입만 빼면 **빈 `except` 가 남아 SyntaxError** 다. try 를 통째로
    # 지우는 것도 안 된다 — `try` 쪽 import 가 같은 이름을 묶는다.
    "upload_files",
)

# 본문이 달라 개명하는 것들. 지우면 attach 가 intelligent 판본을 쓰게 되어 **동작이
# 바뀐다** — 예: `_load_config` 는 attach 판본이 설정 파일 부재를 `{}` 로 넘기는데
# intelligent 판본은 예외를 던진다.
_ATTACH_RENAME = {
    "DocumentProcessor": "AttachDocumentProcessor",
    "GenOSVectorMeta": "ATGenOSVectorMeta",
    "GenOSVectorMetaBuilder": "ATGenOSVectorMetaBuilder",
    "GenosServiceException": "ATGenosServiceException",
    "_has_any_pdf_converter": "_at_has_any_pdf_converter",
    "_load_config": "_at_load_config",
    "_warn_unresolved_placeholders": "_at_warn_unresolved_placeholders",
    "convert_to_pdf": "at_convert_to_pdf",
}

_INTEL_RENAME = {"DocumentProcessor": "IntelligentDocumentProcessor"}

_HWPX_RENAME = {
    "DocumentProcessor": "HwpxDocumentProcessor",
    # attach 가 쓰는 langchain `Document` 를 덮지 않게. hwpx 가 마지막이라 그대로 두면
    # attach 의 20개 호출부가 **호출 시점에** 터진다(import 는 통과한다).
    "Document": "HwpxDocument",
}

# 세 조각이 똑같이 정의해도 되는 이름 — 같은 표준 모듈이거나 같은 식(`_log` 는 셋 다
# `logging.getLogger(__name__)`, 합치면 `__name__` 이 같으므로 같은 객체)이다.
_ALLOWED_DUPLICATES = {
    "Any",
    "annotations",
    "datetime",
    "logging",
    "os",
    "re",
    "time",
    "_log",
    "asyncio",
    "json",
    "traceback",
    # 위 `_ATTACH_KEEP_DUP` — 값이 같고 일부러 남긴 것이다. `upload_files` 는 양쪽 다
    # 같은 try/except 이라 어느 쪽이 이겨도 결과가 같다(import 성공이면 같은 함수,
    # 실패면 둘 다 None).
    "_DEFAULT_TOKENIZER_LOCAL_PATH",
    "_DEFAULT_TOKENIZER_ID",
    "upload_files",
}


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


def _classify_overlap(attach_src: str, intel_src: str) -> None:
    """겹치는 이름을 **다시 분류해** 위 표와 맞는지 본다.

    표를 손으로 적어 두고 원본만 갱신되면, 같던 것이 달라졌는데도 계속 지워져
    **attach 가 조용히 다른 판본을 쓰게 된다.** 그 상태는 예외가 아니라 이상한 값으로만
    드러나므로 여기서 세운다.
    """
    attach_defs = _toplevel_defs(ast.parse(attach_src))
    intel_defs = _toplevel_defs(ast.parse(intel_src))
    shared = set(attach_defs) & set(intel_defs)

    same = {n for n in shared if ast.dump(attach_defs[n]) == ast.dump(intel_defs[n])}
    diff = shared - same

    expected_same = set(_ATTACH_DROP) | set(_ATTACH_KEEP_DUP)
    if same != expected_same:
        raise SystemExit(
            "[build] '본문이 같은 겹침' 목록이 원본과 다르다.\n"
            f"  표에만 있다: {sorted(expected_same - same)}\n"
            f"  원본에만 있다: {sorted(same - expected_same)}"
        )
    if diff != set(_ATTACH_RENAME):
        raise SystemExit(
            "[build] '본문이 다른 겹침' 목록이 원본과 다르다.\n"
            f"  표에만 있다: {sorted(set(_ATTACH_RENAME) - diff)}\n"
            f"  원본에만 있다: {sorted(diff - set(_ATTACH_RENAME))}"
        )


# ---------------------------------------------------------------------------
# 변환 1 — 지우기
# ---------------------------------------------------------------------------

_DROP_NOTE = (
    "# [병합 제거] `{name}` — intelligent 판본과 **본문이 완전히 같다**(AST 대조).\n"
    "#             attach → intelligent 순서라 어차피 intelligent 것이 이겼으므로,\n"
    "#             지워도 도는 코드는 그대로다. 원본: attach_processor.py:{start}-{end}\n"
)


def _drop_definitions(src: str, names: tuple) -> str:
    """`names` 의 최상위 정의를 지우고 그 자리에 표식 주석을 남긴다."""
    tree = ast.parse(src)
    defs = _toplevel_defs(tree)
    spans = []
    direct = {id(node) for node in tree.body}
    for name in names:
        node = defs.get(name)
        if node is None:
            raise SystemExit(f"[build] 지울 정의를 찾지 못했다: {name}")
        if id(node) not in direct:
            # `try:`/`if:` 안의 정의는 본문만 빼면 **빈 블록이 남아 SyntaxError** 다.
            # 실제로 `upload_files` 에서 밟았다 — `except ImportError:` 안의 대입이라
            # 지우자 그 except 가 비었다.
            raise SystemExit(
                f"[build] {name} 은 최상위 직계 문장이 아니라 지울 수 없다 "
                "(try/if 안이다 — _ATTACH_KEEP_DUP 으로 옮길 것)"
            )
        spans.append((node.lineno, node.end_lineno, name))

    lines = src.splitlines(keepends=True)
    # 아래에서부터 지운다 — 위에서부터 하면 남은 span 의 줄 번호가 밀린다.
    for start, end, name in sorted(spans, reverse=True):
        lines[start - 1 : end] = [_DROP_NOTE.format(name=name, start=start, end=end)]
    return "".join(lines)


# ---------------------------------------------------------------------------
# 변환 2 — 개명 (출력은 토큰 치환, 검증은 AST 트랜스포머)
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
    "# [병합 개명] `{old}` → `{new}` — intelligent 판본과 **본문이 다르다**. 지우면\n"
    "#             attach 가 intelligent 판본을 쓰게 되어 동작이 바뀌므로 둘 다 남긴다.\n"
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
    if len(tries) != 2:
        raise SystemExit(f"[build] 최상위 try 블록이 {len(tries)}개다(2개여야 한다)")

    _assert_ast_equal(ast.parse(parts["attach"]).body, tries[0].body, "PART 1(첨부용)")
    _assert_ast_equal(ast.parse(parts["intel"]).body, tries[1].body, "PART 2(지능형)")

    hwpx_expected = ast.parse(parts["hwpx"]).body
    start = None
    for index, node in enumerate(top):
        if ast.dump(node) == ast.dump(hwpx_expected[0]):
            start = index
            break
    if start is None:
        raise SystemExit("[build] PART 3(hwpx)의 첫 문장을 병합 파일에서 찾지 못했다")
    _assert_ast_equal(hwpx_expected, top[start:], "PART 3(hwpx)")

    named = {
        "PART 1(첨부용)": _toplevel_names(ast.parse(parts["attach"]).body),
        "PART 2(지능형)": _toplevel_names(ast.parse(parts["intel"]).body),
        "PART 3(hwpx)": _toplevel_names(hwpx_expected),
        "PART 4(라우터)": _toplevel_names(ast.parse(parts["router"]).body),
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

_HEADER = '''"""GenOS 통합 전처리기 — hwpx 는 우리 파서, 나머지는 형식마다 더 나은 벤더 처리기로.

**이 파일은 생성물이다. 직접 고치지 말 것** — 고칠 자리는 넷 중 하나이고, 고친 뒤
`python onprem/preprocessor/build_final_preprocessor.py` 로 다시 만든다:

| 고칠 것 | 자리 |
|---|---|
| hwpx 파싱·청킹 | `onprem/preprocessor/hwpx_preprocessor.py` |
| 라우팅·폴백·스키마 정렬 | `onprem/preprocessor/router_template.py` |
| pdf/pptx/이미지 처리 | `genos_files/intelligence_processor.py` (GenOS 참조 사본) |
| docx/hwp/오디오/텍스트 처리 | `genos_files/attach_processor.py` (GenOS 참조 사본) |
| 병합 방식·겹침 처리 | `onprem/preprocessor/build_final_preprocessor.py` |

## 왜 한 파일인가

GenOS 전처리기 등록은 **소스 파일 하나**를 받아 그 파일이 정의하는 `DocumentProcessor`
를 실행한다. 서로 import 할 수 없으므로(벤더 원본도 같은 이유로 `convert_to_pdf` 를
자기 안에 복제해 두고 있다) 한 등록에서 세 처리기를 쓰려면 한 파일에 있어야 한다.

## 라우팅 — 형식마다 **덜 잃는 쪽**으로 보낸다

| 입력 | 어디로 | 근거 |
|---|---|---|
| `.hwpx` (내용도 hwpx 컨테이너) | **hwpx 파서** | 표 병합(rowSpan/colSpan)·조문 위계를 지킨다 |
| `.hwp`, `.hml` | 첨부용 | GenosHwp SDK **네이티브**. 지능형은 PDF 로 바꾼다 |
| `.docx` | 첨부용 | `GenosMsWordDocumentBackend` **네이티브**. 지능형은 PDF 변환을 거쳐 표 병합이 깨질 수 있다 |
| `.pdf` | 지능형 | docling layout + TableFormer + OCR + enrichment. 첨부용은 `PyMuPDFLoader` 평문 + 문자 수 분할이라 **표 구조가 통째로 사라진다** |
| `.ppt`, `.pptx` | 지능형 | 둘 다 PDF 변환이지만 지능형이 enrichment 가 많다 |
| `.xlsx`, `.xlsm`, `.csv` | 지능형 | PDF 변환 없이 직접 처리 + tabular 모드 |
| 이미지 | 지능형 | docling OCR |
| `.wav`, `.mp3`, `.m4a` | 첨부용 | Whisper STT. **지능형에는 이 경로가 없다** |
| `.txt`, `.md`, `.json` | 첨부용 | 지능형은 이것들도 PDF 로 바꾼다 |
| 그 외 | 지능형 | 모르는 형식은 PDF 변환 + docling 쪽이 폭넓다 |

**확장자만 보고 보내지 않는다** — `.hwpx` 는 zip 을 열어 실제로 hwpx 컨테이너인지 본다.
이름만 `.hwpx` 인 파일을 우리 파서에 넣으면 예외가 나고 **그 문서는 검색에서 통째로
사라진다.** 벤더로 보내면 표는 덜 정확해도 적재는 된다.

## 합친 순서가 계약이다 — 뒤엣것이 앞엣것을 덮는다

PART 1 첨부용 → PART 2 지능형 → PART 3 hwpx → PART 4 라우터.

첨부용과 지능형이 최상위 이름 **24개를 둘 다 정의**한다. 합치면 전부 지능형 판본이
이기므로, 본문이 같은 것은 지우고(죽은 코드다) 다른 것은 개명해 둘 다 남겼다. 지운
자리·개명한 자리에 `[병합 제거]`·`[병합 개명]` 표식 주석이 있다. 판정 근거와 개수는
`build_final_preprocessor.py` 머리말에 있다.

`Document` 도 겹쳤다 — 첨부용은 langchain 것을 import 하고 hwpx 는 같은 이름의
데이터클래스를 정의한다. hwpx 가 마지막이라 그대로 두면 첨부용의 20개 호출부가
**호출 시점에** 터지므로(import 는 통과한다) hwpx 쪽을 `HwpxDocument` 로 바꿨다.

## 벤더 절반이 없는 환경에서도 이 파일은 import 된다

PART 1·2 는 각각 `try:` 안에 있다. docling·`genon.preprocessor.*` 가 없으면 그 절반만
비활성이 되고 **hwpx 경로는 그대로 돈다.** 비활성 사실은 숨기지 않는다 — 그 엔진으로
가야 할 파일이 들어오면 **사유를 담아 예외를 던진다**(조용히 빈 결과를 내지 않는다).

**주의**: 지운 14개는 지능형 판본을 쓴다. 그래서 **첨부용 경로는 지능형 절반도 함께
적재돼야 돈다.** 라우터가 그것까지 확인하고 실패를 갈라 보고한다.

## 등록 화면에서 더 받는 값

hwpx 경로는 `hwpx_preprocessor.py` 의 값(`chunk_size`·`chunk_overlap`·`outline_mode`·
`file_name`·`extra_metadata`)을, 벤더 경로는 각 원본의 값을 그대로 받는다. 라우터 몫:

| 키 | 기본값 | 의미 |
|---|---|---|
| `hwpx_engine` | `auto` | `auto`=hwpx 파서, 실패하면 첨부용으로 폴백(GenosHwp SDK 네이티브라 지능형보다 덜 잃는다) / `native`=폴백 없음 / `attach`·`intelligent`=hwpx 도 그쪽으로 |
| `route_overrides` | 없음 | `{{".pdf": "attach"}}` 꼴로 확장자별 라우팅을 덮어쓴다 |
| `align_vector_schema` | `true` | hwpx 레코드에 벤더 예약 필드(`title`·`created_date`·`appendix`·`guardrail_categories`)를 채워 **한 컬렉션 안 메타 스키마를 맞춘다** |
| `intelligent_config_path` / `attachment_config_path` | 없음 | 벤더 설정 yaml. 없으면 환경변수 → 벤더 기본 경로 → 이 파일 주변 순으로 찾는다 |

값이 잘못된 타입/범위면 에러를 내지 않고 기본값으로 떨어지되 로그에 남긴다.

## 페이지 번호는 hwpx 경로에 없다

hwpx 는 흐름 문서라 렌더링 전에는 페이지가 정해지지 않는다. 지어내지 않고 `None` 으로
둔다. 페이지·bbox 가 꼭 필요하면 `hwpx_engine="intelligent"` 로 그 문서만 PDF 경로에
태울 수 있고, 그건 표가 깨지는 쪽이다.
"""

'''


def main() -> None:
    attach_raw = _strip_future(_read(_ATTACH_SRC), "attach_processor.py")
    intel_raw = _strip_future(_read(_INTEL_SRC), "intelligence_processor.py")
    hwpx_raw = _strip_future(_read(_HWPX_SRC), "hwpx_preprocessor.py")

    # 표가 원본과 맞는지 먼저 본다 — 어긋나면 아래 변환은 전부 잘못된 전제 위에 선다.
    _classify_overlap(attach_raw, intel_raw)

    attach_body = _drop_definitions(attach_raw, _ATTACH_DROP)
    dropped_ast = ast.parse(attach_body)
    attach_body = _rename_verified(attach_body, _ATTACH_RENAME, "attach_processor.py")
    attach_body = _annotate_renames(attach_body, _ATTACH_RENAME)
    # 주석을 끼운 뒤에도 코드가 그대로인지 본다(주석은 AST 에 안 남는다).
    if ast.dump(ast.parse(attach_body)) != ast.dump(
        _RenameTransformer(dict(_ATTACH_RENAME)).visit(dropped_ast)
    ):
        raise SystemExit("[build] attach: 표식 주석을 끼우며 코드가 바뀌었다")

    intel_body = _rename_verified(intel_raw, _INTEL_RENAME, "intelligence_processor.py")
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
        _BANNER.format(title="PART 1 — 첨부용 (genos_files/attach_processor.py, 겹침 처리 후)"),
        _GUARD_HEAD.format(flag="_FP_ATTACH_IMPORT_ERROR", trace="_FP_ATTACH_IMPORT_TRACE"),
        _indent(attach_body.lstrip("\n")),
        _GUARD_TAIL.format(flag="_FP_ATTACH_IMPORT_ERROR", trace="_FP_ATTACH_IMPORT_TRACE"),
        "\n\n",
        _BANNER.format(title="PART 2 — 지능형 (genos_files/intelligence_processor.py 원문)"),
        _GUARD_HEAD.format(flag="_FP_INTELLIGENT_IMPORT_ERROR", trace="_FP_INTELLIGENT_IMPORT_TRACE"),
        _indent(intel_body.lstrip("\n")),
        _GUARD_TAIL.format(flag="_FP_INTELLIGENT_IMPORT_ERROR", trace="_FP_INTELLIGENT_IMPORT_TRACE"),
        "\n\n",
        _BANNER.format(title="PART 3 — hwpx 전용 파서 (onprem/preprocessor/hwpx_preprocessor.py 원문)"),
        hwpx_body.lstrip("\n"),
        "\n\n",
        _BANNER.format(title="PART 4 — 라우터 (onprem/preprocessor/router_template.py 원문)"),
        router_body,
    ]
    merged = "".join(parts)
    if not merged.endswith("\n"):
        merged += "\n"

    _verify(
        merged,
        {"attach": attach_body, "intel": intel_body, "hwpx": hwpx_body, "router": router_body},
    )

    with open(_OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(merged)

    original = sum(
        len(_read(path).splitlines()) for path in (_ATTACH_SRC, _INTEL_SRC, _HWPX_SRC)
    )
    print(f"[build] {_OUT}")
    print(
        f"[build] {len(merged.splitlines()):,}줄 — 원본 3벌 {original:,}줄 + 라우터, "
        f"겹침 제거 {len(_ATTACH_DROP)}개 / 개명 {len(_ATTACH_RENAME)}개. AST 대조 통과"
    )


if __name__ == "__main__":
    main()
