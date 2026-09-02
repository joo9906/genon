"""온프레미스로 **손으로 옮겨 적을** 자료를 만든다.

    python onprem/preprocessor/build_transfer_kit.py

## 왜 따로 있나 — `final_preprocessor.py` 는 이관 산출물이 **아니다**

`build_final_preprocessor.py` 가 만드는 5,795줄짜리 생성물은 **외부(이 저장소)에서
검증하기 위한 것**이다. 폐쇄망에는 파일을 넣을 수 없고 사람이 화면을 보며 타이핑하므로,
그 5,795줄을 그대로 치는 것은 이관 방법이 아니다.

**벤더 절반은 이미 온프레미스에 있다.** `genos_files/attach_processor.py` 는 그쪽에서
긁어온 참조 사본이고, 원본은 첨부용 전처리기로 이미 등록돼 있다. 그래서 에어갭을
건너야 하는 것은 **우리 코드뿐**이다:

    첨부용 2,558줄  →  이미 그쪽에 있다. 손대는 것은 **1줄**
    hwpx   2,258줄  →  타이핑 (주석·docstring 걷어내면 1,173줄)
    라우터    887줄  →  타이핑 (걷어내면 529줄)
                        ─────────────────────────────
                        타이핑 3,145줄 → **1,702줄 (54%)**

## 걷어내는 것과 남기는 것

- **주석·docstring 을 걷어낸다.** 동작에 영향이 없고(`__doc__` 를 읽는 코드가 없다 —
  확인했다) 타이핑 분량이 절반이 된다. **설명은 이 저장소가 갖는다** — 온프레미스 코드가
  왜 그런지 알아야 할 때는 여기를 본다.
- **원본 줄바꿈은 그대로 둔다.** `ast.unparse` 로 다시 찍으면 한 줄이 451자까지 늘어난다 —
  손으로 칠 때는 **긴 줄이 주석보다 나쁘다**(자리를 놓치고, 틀려도 눈에 안 띈다).
  그래서 docstring 은 줄 범위로 도려내고 주석은 `tokenize` 로만 뺀다. 최장 100자다.
- **개명은 미리 적용한다.** `DocumentProcessor` → `HwpxDocumentProcessor`,
  `Document` → `HwpxDocument`. 온프레미스에서 손으로 바꿀 일을 남기지 않는다.

## 만드는 것

    transfer/10_hwpx.py       타이핑용 — hwpx 파서
    transfer/20_router.py     타이핑용 — 라우터
    transfer/30_verify.py     타이핑용 — 오타 검출 스니펫 (9줄)
    transfer/40_expect.txt    **타이핑하지 않는다.** 화면으로 대조할 기대 해시표
    transfer/00_이관절차.md    순서·벤더 편집·검증

**타이핑은 비싸고 보는 것은 공짜다.** 그래서 기대 해시표는 치지 않고 이쪽 화면에 띄워
놓고 눈으로 맞춘다. 치는 것은 9줄짜리 스니펫뿐이다.

## 검증 — 걷어낸 코드가 원본과 같은가

두 층으로 본다.

1. **AST 대조.** docstring 을 뺀 원본과 걷어낸 판본의 `ast.dump` 가 같아야 한다.
   문자열이 한 글자만 달라져도, 연산자가 하나 바뀌어도 걸린다.
2. **실물 대조.** 걷어낸 hwpx 파서를 실제로 태워 원본과 **레코드가 같은지** 본다
   (`data/` 의 hwpx 를 있는 것만). AST 가 같으면 당연히 같지만, 걷어내는 코드 자체가
   틀렸을 때 그 사실이 여기서 드러난다.
"""

from __future__ import annotations

import ast
import hashlib
import io
import os
import sys
import tokenize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_final_preprocessor as _bfp  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_OUT_DIR = os.path.join(_HERE, "transfer")

# 벤더 쪽에서 손대는 자리. **한 줄뿐이다** — 이 값은 손으로 적은 것이 아니라
# `_locate_vendor_edit()` 이 원본에서 다시 찾아 확인한다.
_VENDOR_OLD = "DocumentProcessor"
_VENDOR_NEW = "AttachDocumentProcessor"


# ---------------------------------------------------------------------------
# 걷어내기
# ---------------------------------------------------------------------------


def _strip(src: str) -> str:
    """주석·docstring 을 걷어낸다. **원본 줄바꿈은 건드리지 않는다.**

    docstring 은 `ast` 가 준 줄 범위로 도려낸다(본문이 그것뿐이면 `pass` 를 남긴다 —
    안 남기면 빈 블록이 되어 SyntaxError). 주석은 `tokenize` 로만 뺀다 — 정규식으로
    `#` 를 지우면 **문자열 안 `#` 까지 잘라** 값이 바뀐다.
    """
    tree = ast.parse(src)
    cuts = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        body = node.body
        if not body:
            continue
        first = body[0]
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        need_pass = len(body) == 1 and not isinstance(node, ast.Module)
        cuts.append((first.lineno, first.end_lineno, first.col_offset, need_pass))

    lines = src.splitlines(keepends=True)
    # 아래에서부터 지운다 — 위에서부터 하면 남은 범위의 줄 번호가 밀린다.
    for start, end, col, need_pass in sorted(cuts, reverse=True):
        lines[start - 1:end] = [" " * col + "pass\n"] if need_pass else []
    src = "".join(lines)

    kept = [
        tok for tok in tokenize.generate_tokens(io.StringIO(src).readline)
        if tok.type != tokenize.COMMENT
    ]
    src = tokenize.untokenize(kept)
    return "\n".join(l.rstrip() for l in src.splitlines() if l.strip()) + "\n"


def _drop_docstrings(tree: ast.Module) -> ast.Module:
    """AST 대조용 — 원본에서도 docstring 을 같은 규칙으로 뺀다."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        body = node.body
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            node.body = body[1:] if len(body) > 1 else [ast.Pass()]
    return tree


def _strip_verified(src: str, origin: str) -> str:
    out = _strip(src)
    want = ast.dump(_drop_docstrings(ast.parse(src)))
    got = ast.dump(_drop_docstrings(ast.parse(out)))
    if want != got:
        raise SystemExit(f"[kit] {origin}: 걷어낸 판본이 원본과 다르다(AST 대조 실패)")
    return out


# ---------------------------------------------------------------------------
# 해시 — 온프레미스 스니펫과 **같은 식**이어야 한다
# ---------------------------------------------------------------------------
#
# 스니펫(`30_verify.py`)이 계산하는 것과 한 글자라도 다르면 전부 어긋난 것처럼 보여
# 검증이 통째로 쓸모없어진다. 그래서 여기서도 **줄 끝 공백을 떼고 `\n` 으로 이은 뒤**
# sha256 앞 8자를 쓴다 — 사람이 친 코드는 줄 끝 공백이 원본과 다를 수 있다.


def _digests(src: str) -> list:
    lines = src.splitlines()
    rows = []
    for node in ast.parse(src).body:
        name = getattr(node, "name", "")
        if not name and isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if not name:
            continue
        body = "\n".join(l.rstrip() for l in lines[node.lineno - 1:node.end_lineno])
        rows.append((hashlib.sha256(body.encode("utf-8")).hexdigest()[:8], name))
    return rows


_VERIFY_SNIPPET = '''import ast, hashlib, sys
src = open(sys.argv[1], encoding="utf-8").read()
lines = src.splitlines()
for n in ast.parse(src).body:
    name = getattr(n, "name", "")
    if not name and isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
        name = n.targets[0].id
    if not name:
        continue
    body = "\\n".join(l.rstrip() for l in lines[n.lineno - 1:n.end_lineno])
    print(hashlib.sha256(body.encode("utf-8")).hexdigest()[:8], name)
'''


# ---------------------------------------------------------------------------
# 벤더 편집 자리 — 손으로 적지 않고 원본에서 찾는다
# ---------------------------------------------------------------------------


def _locate_vendor_edit() -> list:
    """벤더 파일에서 `DocumentProcessor` 를 쓰는 줄. 속성 접근(`.name`)은 뺀다."""
    src = _bfp._read(_bfp._ATTACH_SRC)
    hits, previous = [], None
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.NAME and tok.string == _VENDOR_OLD:
            if not (previous is not None and previous.type == tokenize.OP
                    and previous.string == "."):
                hits.append(tok.start[0])
        if tok.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT,
                            tokenize.INDENT, tokenize.DEDENT):
            previous = tok
    lines = src.splitlines()
    return [(n, lines[n - 1]) for n in sorted(set(hits))]


# ---------------------------------------------------------------------------
# 실물 대조 — 걷어낸 hwpx 파서가 원본과 같은 레코드를 내는가
# ---------------------------------------------------------------------------

_SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "data")


def _samples() -> list:
    if not os.path.isdir(_SAMPLE_DIR):
        return []
    return sorted(
        os.path.join(_SAMPLE_DIR, n)
        for n in os.listdir(_SAMPLE_DIR)
        if n.lower().endswith(".hwpx")
    )


def _load(path: str, name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _compare_on_samples(stripped_path: str) -> int:
    """걷어낸 판본과 원본이 실물에서 같은 레코드를 내는가. 태운 개수를 돌려준다."""
    import asyncio

    samples = _samples()
    if not samples:
        return 0
    original = _load(_bfp._HWPX_SRC, "_kit_original")
    stripped = _load(stripped_path, "_kit_stripped")
    for sample in samples:
        want = asyncio.run(original.DocumentProcessor()(None, sample))
        got = asyncio.run(stripped.HwpxDocumentProcessor()(None, sample))
        if [r["text"] for r in want] != [r["text"] for r in got]:
            raise SystemExit(
                f"[kit] 실물 대조 실패: {os.path.basename(sample)} 의 본문이 다르다"
            )
        if len(want) != len(got):
            raise SystemExit(f"[kit] 실물 대조 실패: {os.path.basename(sample)} 청크 수가 다르다")
    return len(samples)


# ---------------------------------------------------------------------------
# 절차 문서
# ---------------------------------------------------------------------------


def _procedure(stats: dict, vendor_edits: list) -> str:
    edit_rows = "\n".join(
        f"| {lineno} | `{text.strip()}` | `{text.strip().replace(_VENDOR_OLD, _VENDOR_NEW)}` |"
        for lineno, text in vendor_edits
    )
    return f"""# 온프레미스 이관 절차 (자동 생성 — 고치지 말 것)

> `python onprem/preprocessor/build_transfer_kit.py` 가 만든다. 숫자는 매번 다시
> 계산되므로 손으로 고치면 다음 생성에 지워진다.

## 전제

- **벤더 절반은 이미 그쪽에 있다.** 첨부용 전처리기(`attach_processor.py`)가 등록돼
  있고, 그 사본을 떠서 우리 코드를 이어 붙인다. 에어갭을 건너는 것은 우리 코드뿐이다.
- **`final_preprocessor.py` 는 치지 않는다.** 그건 외부에서 검증하려고 만든 5,795줄짜리
  생성물이다. 온프레미스 결과물과 **한 군데 다르다** — 아래 "가드" 절.

## 타이핑 분량

| 조각 | 원본 | 타이핑 | 비고 |
|---|---|---|---|
| 첨부용 (벤더) | {stats['attach']:,}줄 | **{len(vendor_edits)}줄 수정** | 이미 그쪽에 있다 |
| hwpx 파서 | {stats['hwpx_raw']:,}줄 | {stats['hwpx']:,}줄 | `10_hwpx.py` |
| 라우터 | {stats['router_raw']:,}줄 | {stats['router']:,}줄 | `20_router.py` |
| 검증 스니펫 | — | {stats['verify']}줄 | `30_verify.py` |
| | | **합계 {stats['hwpx'] + stats['router'] + stats['verify']:,}줄** | |

## 순서

**1. 벤더 사본을 뜬다.** 첨부용 등록 파일을 열어 새 전처리기로 복사한다.

**2. 벤더에서 이 줄을 고친다.** 이것뿐이다.

| 줄 | 원래 | 고쳐서 |
|---|---|---|
{edit_rows}

> 왜: GenOS 는 파일이 정의하는 `DocumentProcessor` 를 실행한다. 우리 라우터가 그 이름을
> 가져야 하므로 벤더 것이 비켜야 한다. **안 고치면 라우팅이 통째로 사라지는데 적재는
> 성공으로 보인다** — 오류가 나지 않는다.

**3. `10_hwpx.py` 를 따로 만들어 친다.** 아직 이어 붙이지 않는다.

**4. `30_verify.py` 를 치고 3번을 검증한다.**

```
python 30_verify.py 10_hwpx.py
```

출력이 `40_expect.txt` 의 `[10_hwpx.py]` 절과 **줄 단위로 같아야 한다.**
`40_expect.txt` 는 **치지 않는다** — 외부 화면에 띄워 놓고 눈으로 맞춘다.
어긋난 줄의 이름이 곧 오타가 있는 함수다.

**5. `20_router.py` 도 같은 방식으로** 치고 검증한다.

**6. 벤더 사본 끝에 이어 붙인다.** 순서가 계약이다:

```
(벤더 첨부용 — 2번에서 고친 것)
_FP_ATTACH_IMPORT_ERROR = None
_FP_ATTACH_IMPORT_TRACE = ""
import time
import zipfile
(10_hwpx.py 내용)
(20_router.py 내용)
```

- **hwpx 가 벤더보다 뒤**여야 한다. `Document` 이름이 겹치는데 우리 쪽은 이미
  `HwpxDocument` 로 비켜 놨다.
- **라우터가 맨 뒤**여야 그 `DocumentProcessor` 가 살아남는다.
- `import time`·`import zipfile` 은 벤더 파일에 없고 우리 코드가 쓴다(`asyncio`·`json`·
  `os`·`re` 는 벤더가 이미 갖고 있다). 파일 맨 위 import 뭉치에 넣어도 되고 여기 둬도 된다.

**7. 등록하고 hwpx 하나를 적재해 본다.** 컨테이너 로그에 이게 떠야 한다:

```
[GENON-DEBUG] engine=hwpx file=<파일명> chunks=<개수>
[GENON-DEBUG] first200>>>
<본문 앞 200자>
[GENON-DEBUG] <<<
```

`engine=attach` 가 뜨면 hwpx 가 벤더로 샌 것이다(라우팅 확인). 아무것도 안 뜨면 6번의
붙이는 순서를 확인한다.

## 가드 — 외부 판본과 다른 **유일한** 자리

외부 `final_preprocessor.py` 는 벤더 절반을 통째로 `try:` 안에 넣는다. 이유는 **우리
쪽 사정**이다 — 로컬에 docling 이 없어도 파일이 import 되고 회귀 점검이 돌아야 한다.

**온프레미스에서는 그 가드를 두지 않는다.** 벤더 스택이 이미 있고(그 파일이 이미 돌고
있다), 2,558줄을 통째로 한 칸 들여쓰는 것은 손으로 할 일이 아니다. 대신 6번의
`_FP_ATTACH_IMPORT_ERROR = None` 두 줄이 그 자리를 메운다 — 여기까지 실행이 왔다는 것이
곧 벤더가 적재됐다는 뜻이다.

## 주석이 없는 이유

타이핑 분량을 절반으로 줄이려고 주석·docstring 을 걷어냈다. **설명은 이 저장소가
갖는다** — 온프레미스 코드가 왜 그런지 알아야 하면 `onprem/preprocessor/` 를 본다.
걷어낸 판본이 원본과 같다는 것은 빌드가 **AST 로 대조**하고 **실물 hwpx 로 태워**
확인한다.
"""


# ---------------------------------------------------------------------------


def main() -> None:
    os.makedirs(_OUT_DIR, exist_ok=True)

    hwpx_raw = _bfp._strip_future(_bfp._read(_bfp._HWPX_SRC), "hwpx_preprocessor.py")
    hwpx_raw = _bfp._rename_verified(hwpx_raw, _bfp._HWPX_RENAME, "hwpx_preprocessor.py")
    hwpx = _strip_verified(hwpx_raw, "hwpx_preprocessor.py")

    router_lines = _bfp._strip_future(
        _bfp._read(_bfp._ROUTER_SRC), "router_template.py"
    ).splitlines(keepends=True)
    marker = "# ROUTER-BODY-BEGIN"
    hits = [i for i, line in enumerate(router_lines) if line.strip() == marker]
    if len(hits) != 1:
        raise SystemExit(f"[kit] router_template.py 의 '{marker}' 표식 줄이 {len(hits)}개다")
    router_raw = "".join(router_lines[hits[0] + 1:]).lstrip("\n")
    router = _strip_verified(router_raw, "router_template.py")

    paths = {
        "10_hwpx.py": hwpx,
        "20_router.py": router,
        "30_verify.py": _VERIFY_SNIPPET,
    }
    for name, text in paths.items():
        with open(os.path.join(_OUT_DIR, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    expect = ["# 이 파일은 **치지 않는다.** 외부 화면에 띄워 놓고 눈으로 대조한다.",
              "#   python 30_verify.py 10_hwpx.py   ← 출력이 아래 절과 줄 단위로 같아야 한다",
              ""]
    for name in ("10_hwpx.py", "20_router.py"):
        expect.append(f"[{name}]")
        expect += [f"{digest} {symbol}" for digest, symbol in _digests(paths[name])]
        expect.append("")
    with open(os.path.join(_OUT_DIR, "40_expect.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(expect))

    vendor_edits = _locate_vendor_edit()
    stats = {
        "attach": len(_bfp._read(_bfp._ATTACH_SRC).splitlines()),
        "hwpx_raw": len(_bfp._read(_bfp._HWPX_SRC).splitlines()),
        "router_raw": len(_bfp._read(_bfp._ROUTER_SRC).splitlines()),
        "hwpx": len(hwpx.splitlines()),
        "router": len(router.splitlines()),
        "verify": len(_VERIFY_SNIPPET.splitlines()),
    }
    with open(os.path.join(_OUT_DIR, "00_이관절차.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_procedure(stats, vendor_edits))

    burned = _compare_on_samples(os.path.join(_OUT_DIR, "10_hwpx.py"))

    typed = stats["hwpx"] + stats["router"] + stats["verify"]
    raw = stats["hwpx_raw"] + stats["router_raw"]
    print(f"[kit] {_OUT_DIR}")
    print(
        f"[kit] 타이핑 {typed:,}줄 (원본 {raw:,}줄의 {typed / raw * 100:.0f}%)"
        f" · 벤더 수정 {len(vendor_edits)}줄 · AST 대조 통과"
        f" · 실물 hwpx {burned}벌 레코드 일치"
    )


if __name__ == "__main__":
    main()
