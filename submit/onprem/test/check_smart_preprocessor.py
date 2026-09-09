"""`onprem/preprocessor/smart_preprocessor.py` 점검 — 지능형 + hwpx 등록 단위.

    export PYTHONIOENCODING=utf-8
    python onprem/test/check_smart_preprocessor.py

## 이 점검이 없으면 무엇을 놓치나

이 파일은 **벤더 소스를 합쳐 만든 등록 단위**다. 합치면서 조용히 틀릴 수 있는 자리가 셋이다:

1. **개명**(`DocumentProcessor` → `IntelligentDocumentProcessor`, `_log` → `_intel_log`).
   덜 바꾸면 지능형 것이 라우터를 덮어 **hwpx 가 영영 안 탄다** — 오류가 아니라 "표가
   깨진 결과" 로만 드러난다. 더 바꾸면(정규식으로 갈면) 지능형의 `[DocumentProcessor]`
   로그 **문자열**까지 바뀐다.
2. **들여쓰기**(지능형 절반이 통째로 `try` 안에 있다). 여러 줄 문자열 안쪽에 공백을
   붙이면 **그 문자열의 내용이 바뀐다** — 프롬프트·정규식이면 동작이 달라진다.
3. **스키마 정렬.** hwpx 레코드에 벤더 예약 필드가 안 실리면 한 컬렉션에 두 모양의
   메타가 들어가고, 적재 결과 **화면에 그 문서만 안 뜬다**(빈 목록이라 오류가 없다).

그래서 이 점검은 **참조 원본에서 다시 계산해** 대조한다 — 손으로 적은 기대값이 아니다.
GenOS 가 다음 릴리스에서 지능형을 고치면 그 자리에서 잡힌다.

로컬에는 docling 스택이 없어 지능형 절반이 `try` 에 걸린다. **그 상태를 통과로 세지
않는다** — 벤더 실행 자체는 SKIP 으로 남기고, 대신 **대역을 등록 단위 밖에서 꽂아**
라우팅·kwargs 전달·스키마 정렬을 확인한다.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import io
import os
import sys
import tokenize
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
SMART = os.path.join(ROOT, "preprocessor", "smart_preprocessor.py")
FINAL = os.path.join(ROOT, "preprocessor", "final_preprocessor.py")
INTEL_REF = os.path.join(REPO, "genos_files", "intelligence_processor.py")
SAMPLE = os.path.join(REPO, "data", "파워.hwpx")

RENAMES = {"DocumentProcessor": "IntelligentDocumentProcessor", "_log": "_intel_log"}

_ok: list = []
_fail: list = []
_skip: list = []


def check(label: str, condition: bool, detail: str = "") -> None:
    _ok.append(label) if condition else _fail.append(
        label + (f" — {detail}" if detail else "")
    )


def skip(label: str, why: str) -> None:
    _skip.append(f"{label} — {why}")


def _load():
    spec = importlib.util.spec_from_file_location("smart_preprocessor", SMART)
    module = importlib.util.module_from_spec(spec)
    # `sys.modules` 에 먼저 넣어야 한다 — `dataclasses` 가 클래스 생성 중
    # `sys.modules[cls.__module__]` 를 읽는다. 안 넣으면 **우리 코드와 무관한 자리**에서
    # AttributeError 로 죽고 원인을 엉뚱한 데서 찾는다.
    sys.modules["smart_preprocessor"] = module
    spec.loader.exec_module(module)
    return module


def _slice(path: str, start_marker: str, end_marker: str | None):
    lines = io.open(path, encoding="utf-8").read().split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith(start_marker))
    end = len(lines)
    if end_marker is not None:
        end = next(i for i, l in enumerate(lines) if l.startswith(end_marker))
    while start > 0 and lines[start - 1].startswith("# ="):
        start -= 1
    while end > 0 and lines[end - 1].startswith("# ="):
        end -= 1
    return "\n".join(lines[start:end])


# ───────────────────────────────────────────────────────────────
# 1. 합치기 — 참조 원본에서 다시 계산해 대조한다
# ───────────────────────────────────────────────────────────────
def _rename_tokens(source: str, mapping: dict) -> str:
    """토큰 자리만 갈아 끼운다 (문자열·주석은 손대지 않는다)."""
    hits: dict = {}
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.NAME and tok.string in mapping:
            hits.setdefault(tok.start[0], []).append((tok.start[1], tok.end[1], tok.string))
    lines = source.split("\n")
    for row, spots in hits.items():
        line = lines[row - 1]
        for scol, ecol, name in sorted(spots, reverse=True):
            line = line[:scol] + mapping[name] + line[ecol:]
        lines[row - 1] = line
    return "\n".join(lines)


def _protected_lines(source: str) -> set:
    """여러 줄에 걸친 토큰의 **둘째 줄부터**. 들여쓰기를 더하거나 빼면 내용이 바뀌는 줄."""
    marked = set()
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.start[0] != tok.end[0]:
            marked.update(range(tok.start[0] + 1, tok.end[0] + 1))
    return marked


def _try_body_source() -> str | None:
    """생성물에서 지능형 절반(`try:` 본문)만 떼어 **들여쓰기를 되돌린** 소스.

    **보호 구간을 똑같이 가려내야 한다.** 여러 줄 문자열 안쪽 줄은 합칠 때 들여쓰지
    않았으므로 여기서도 깎으면 안 된다 — 그냥 `line[4:]` 하면 원래 4칸으로 시작하던
    docstring 줄이 깎여 **문자열 내용이 달라지고**, 그러면 이 점검이 "합치기가 원본을
    건드렸다" 고 잘못 고발한다. 실제로 한 번 그렇게 나왔다(33개 문자열이 달랐다).
    """
    src = io.open(SMART, encoding="utf-8").read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Try) and node.body:
            lo, hi = node.body[0].lineno, node.body[-1].end_lineno
            keep = _protected_lines(src)
            out = []
            for no in range(lo, hi + 1):
                line = src.split("\n")[no - 1]
                out.append(line if no in keep else (line[4:] if line.startswith("    ") else line))
            return "\n".join(out)
    return None


def check_merge_matches_reference() -> None:
    if not os.path.isfile(INTEL_REF):
        # 이관 꾸러미(`submit/`)에는 `genos_files/`(GenOS 참조 사본)가 들어가지 않는다.
        # **조용히 통과시키지 않는다** — 이 판정이 없으면 "합치기가 원본을 건드렸는가" 를
        # 보는 그물이 0건이 되고, 받은 쪽은 그 사실을 모른 채 초록불만 본다.
        skip("합치기 ↔ 참조 원본 대조", f"{os.path.relpath(INTEL_REF, REPO)} 가 없다 (통과가 아니다)")
        return
    body = _try_body_source()
    if body is None:
        check("생성물에 지능형 `try` 절반이 있다", False, "try 블록을 못 찾았다")
        return
    check("생성물에 지능형 `try` 절반이 있다", True)

    reference = io.open(INTEL_REF, encoding="utf-8").read()
    reference = reference.replace("from __future__ import annotations\n", "", 1)
    expected = _rename_tokens(reference, RENAMES)

    # **AST 로 본다.** 들여쓰기를 되돌릴 때 줄 끝 공백 같은 사소한 차이가 생길 수 있고,
    # 그건 동작과 무관하다. 반대로 **문자열 내용이 한 글자라도 달라지면 AST 가 다르다** —
    # 들여쓰기가 여러 줄 문자열을 망가뜨린 경우가 정확히 여기서 잡힌다.
    try:
        same = ast.dump(ast.parse(body)) == ast.dump(ast.parse(expected))
    except SyntaxError as exc:
        check("지능형 절반이 참조 원본과 같다 (개명 제외)", False, f"SyntaxError: {exc}")
        return
    check("지능형 절반이 참조 원본과 같다 (개명 제외)", same,
          "참조 원본이 바뀌었거나 합치기가 원본을 건드렸다")

    # 문자열 리터럴은 **하나도 바뀌면 안 된다** (정규식 개명의 함정).
    def strings(source: str):
        return [n.value for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]

    ref_strings, got_strings = strings(reference), strings(body)
    check("개명이 문자열 리터럴을 건드리지 않았다", ref_strings == got_strings,
          f"{len(ref_strings)}개 중 {sum(1 for a, b in zip(ref_strings, got_strings) if a != b)}개 다름")
    marker = [s for s in got_strings if "[DocumentProcessor]" in s]
    check("`[DocumentProcessor]` 로그 문자열이 그대로 남아 있다", len(marker) > 0,
          "정규식 개명이면 여기가 0이 된다")


def check_no_name_collisions() -> None:
    """세 조각 사이에 최상위 이름이 겹치면 **뒤엣것이 앞엣것을 덮는다.**

    표준 모듈 import(`os`·`re`·`time`…)는 겹쳐도 같은 것이라 뺀다. 그 밖의 겹침은
    "덮였다" 는 뜻이고, 그 실패는 **오류가 아니라 엉뚱한 동작**으로만 드러난다.
    """
    src = io.open(SMART, encoding="utf-8").read()
    tree = ast.parse(src)

    def defined(nodes) -> dict:
        names: dict = {}
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.setdefault(node.name, node.lineno)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.setdefault(target.id, node.lineno)
        return names

    intel_names: dict = {}
    rest_names: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Try):
            intel_names.update(defined(node.body))
        else:
            rest_names.update(defined([node]))
    overlap = sorted(set(intel_names) & set(rest_names))
    check("지능형 절반과 hwpx·라우터 사이에 겹치는 정의가 없다", not overlap, f"겹침: {overlap}")
    check("진입점 `DocumentProcessor` 는 라우터 것 하나다",
          "DocumentProcessor" in rest_names and "DocumentProcessor" not in intel_names)


def check_hwpx_half_matches_final() -> None:
    """hwpx 절반은 `final_preprocessor.py` 의 것과 **같은 코드**여야 한다.

    두 등록 단위가 같은 파서를 들고 있는데 한쪽만 고치면, **같은 hwpx 가 어느 단위로
    적재했느냐에 따라 다른 청크로 들어간다.** 오류가 아니라 검색 품질로만 드러난다.
    """
    a = _slice(FINAL, "# PART 2 ", "# PART 3 ")
    b = _slice(SMART, "# PART 2 ", "# PART 3 ")
    check("hwpx 절반이 final_preprocessor 와 같다", a.strip() == b.strip(), "두 등록 단위가 갈렸다")


# ───────────────────────────────────────────────────────────────
# 2. 라우팅
# ───────────────────────────────────────────────────────────────
def _write(tmp: str, name: str, data: bytes) -> str:
    path = os.path.join(tmp, name)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def check_routing(module) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        hwpx = SAMPLE if os.path.isfile(SAMPLE) else None
        cases = [
            (".pdf", _write(tmp, "a.pdf", b"%PDF-1.4\n"), "intel"),
            (".docx", _write(tmp, "a.docx", b"PK\x03\x04"), "intel"),
            (".pptx", _write(tmp, "a.pptx", b"PK\x03\x04"), "intel"),
            (".xlsx", _write(tmp, "a.xlsx", b"PK\x03\x04"), "intel"),
            (".png", _write(tmp, "a.png", b"\x89PNG"), "intel"),
            (".txt", _write(tmp, "a.txt", b"hello"), "intel"),
        ]
        for label, path, want in cases:
            engine, _why = module._sp_route(path, "auto", {})
            check(f"라우팅 {label} → 지능형", engine == want, f"{engine}")

        if hwpx:
            engine, why = module._sp_route(hwpx, "auto", {})
            check("라우팅 .hwpx → 우리 파서", engine == "hwpx", f"{engine}/{why}")
            check("라우팅 사유가 내용 판정이다", why in ("mimetype", "section_xml"), why)
        else:
            skip("라우팅 .hwpx", "data/파워.hwpx 없음")

        # 이름만 hwpx 인 파일 — 우리 파서에 넣으면 예외가 나고 **그 문서가 검색에서 사라진다**
        fake = _write(tmp, "fake.hwpx", b"%PDF-1.4\n")
        engine, why = module._sp_route(fake, "auto", {})
        check("이름만 .hwpx 인 파일은 지능형으로", engine == "intel", f"{engine}/{why}")
        check("그 사유가 로그에 남을 고정 문자열이다", why == "not_a_zip", why)
        engine, _ = module._sp_route(fake, "native", {})
        check("`hwpx_engine=native` 면 넘기지 않는다", engine == "hwpx", engine)

        # docx/pptx 가 .hwpx 이름을 달고 온 경우
        zip_path = os.path.join(tmp, "zip.hwpx")
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("word/document.xml", "<xml/>")
        engine, why = module._sp_route(zip_path, "auto", {})
        check("zip 이지만 hwpx 가 아니면 지능형으로",
              engine == "intel" and why == "zip_without_hwpx_contents", f"{engine}/{why}")

        # 덮어쓰기
        overrides = module._sp_overrides_kwarg('{"pdf": "hwpx"}')
        check("route_overrides 가 확장자에 `.` 을 붙인다", overrides == {".pdf": "hwpx"}, str(overrides))
        # **내용 판정이 덮어쓰기보다 뒤에 온다.** `.pdf` 를 hwpx 로 돌리라고 해도 내용이
        # hwpx 가 아니면 지능형으로 간다 — 우리 파서에 넣으면 예외가 나고 **그 문서가
        # 검색에서 통째로 사라지기** 때문이다. 등록자의 지시보다 이쪽이 우선인 것이 규약이다.
        engine, why = module._sp_route(cases[0][1], "auto", overrides)
        check("덮어쓰기로 hwpx 를 지정해도 내용이 아니면 지능형으로", engine == "intel", f"{engine}/{why}")
        if hwpx:
            engine, why = module._sp_route(hwpx, "auto", {".hwpx": "intel"})
            check("route_overrides 가 라우팅을 덮는다 (hwpx → 지능형)",
                  engine == "intel" and why == "override", f"{engine}/{why}")
        check("모르는 엔진을 적은 항목은 무시된다",
              module._sp_overrides_kwarg('{"pdf": "nope"}') == {})
        check("JSON 이 아니면 무시하고 세우지 않는다", module._sp_overrides_kwarg("{{{") == {})


def check_kwargs_not_forwarded(module) -> None:
    forwarded = module._sp_forward_kwargs(
        {"hwpx_engine": "auto", "route_overrides": "{}", "align_vector_schema": "1",
         "intelligent_config_path": "/x.yaml", "chunk_size": 800}
    )
    check("라우터 몫 kwargs 는 벤더로 넘기지 않는다", forwarded == {"chunk_size": 800}, str(forwarded))


# ───────────────────────────────────────────────────────────────
# 3. 스키마 정렬 — **UI 에서 누락되지 않게 하는 것이 요점이다**
# ───────────────────────────────────────────────────────────────
def check_schema_alignment(module) -> None:
    baseline = module._sp_schema_defaults()
    for key in ("title", "created_date", "appendix", "guardrail_categories"):
        check(f"벤더 절반이 없어도 `{key}` 는 정렬된다", key in baseline)

    # 벤더 모델이 필드를 늘리면 따라가는가 — **손으로 적은 목록이면 여기서 FAIL 한다.**
    class _StubModel:
        model_fields = {
            "text": None, "i_page": None,            # hwpx 가 이미 채우는 것 (건드리면 안 된다)
            "title": None, "appendix": None,
            "brand_new_vendor_field": None,          # 벤더가 새로 넣은 것
        }

    saved = module.__dict__.get("GenOSVectorMeta")
    module.GenOSVectorMeta = _StubModel
    try:
        widened = module._sp_schema_defaults()
        check("벤더 모델의 새 필드를 따라간다", "brand_new_vendor_field" in widened,
              "목록을 손으로 적으면 여기가 FAIL 한다")
        check("새 필드 기본값은 None (빈 문자열·0 을 지어내지 않는다)",
              widened.get("brand_new_vendor_field") is None)
        check("hwpx 가 이미 채우는 필드는 정렬 대상이 아니다",
              "text" not in widened and "i_page" not in widened, str(sorted(widened)))

        record = {"text": "본문", "i_page": 3}
        module._sp_align_records([record])
        check("정렬이 기존 값을 덮지 않는다", record["text"] == "본문" and record["i_page"] == 3)
        check("정렬이 빠진 필드를 채운다", record.get("brand_new_vendor_field", "MISSING") is None)
    finally:
        if saved is None:
            module.__dict__.pop("GenOSVectorMeta", None)
        else:
            module.GenOSVectorMeta = saved

    check("dict 아닌 레코드가 섞여도 죽지 않는다",
          module._sp_align_records([None, "x", {"text": "t"}])[2].get("title") == "")


# ───────────────────────────────────────────────────────────────
# 4. hwpx 실물 — 레코드가 화면에 뜰 모양인가
# ───────────────────────────────────────────────────────────────
def check_hwpx_records(module) -> None:
    if not os.path.isfile(SAMPLE):
        skip("hwpx 실물 레코드", f"{SAMPLE} 없음 — 실물을 옮겼으면 경로를 고칠 것")
        return
    records = asyncio.run(module.DocumentProcessor()(None, SAMPLE))
    check("hwpx 레코드가 나온다", bool(records), "빈 목록")
    if not records:
        return
    first = records[0]
    check("모든 레코드에 `text` 가 있고 비어 있지 않다",
          all(isinstance(r, dict) and r.get("text") for r in records))
    # 페이지 자리 — 이 필드가 비면 적재 결과 화면에 이 문서만 안 뜬다
    check("`i_page` 는 1-based (벤더 pdf 경로와 같은 기준)", first.get("i_page") == 1, str(first.get("i_page")))
    check("`i_chunk_on_page` 는 0-based (벤더와 같은 기준)", first.get("i_chunk_on_page") == 0)
    check("`page_basis` 가 값의 출처를 말한다", first.get("page_basis") == "section",
          str(first.get("page_basis")))
    check("`i_page` 가 `n_page` 를 넘지 않는다",
          all(1 <= r["i_page"] <= r["n_page"] for r in records))
    # 벤더가 못 찾았을 때 내는 값과 **같은 것**을 쓴다 — None 이면 화면이 읽다 멈춘다
    check("`chunk_bboxes` 가 벤더 모양(`\"[]\"`)이다", first.get("chunk_bboxes") == "[]",
          repr(first.get("chunk_bboxes")))
    check("`media_files` 가 벤더 모양(`\"\"`)이다", first.get("media_files") == "")
    for key, want in (("title", ""), ("created_date", None), ("appendix", ""),
                      ("guardrail_categories", None)):
        check(f"벤더 예약 필드 `{key}` 가 실린다", key in first and first[key] == want,
              repr(first.get(key, "MISSING")))
    check("`i_chunk_on_doc`/`n_chunk_of_doc` 가 문서 단위로 매겨진다",
          first.get("i_chunk_on_doc") == 0 and first.get("n_chunk_of_doc") == len(records))

    # 정렬을 끄면 예약 필드가 빠져야 한다 — 안 빠지면 이 손잡이가 아무 일도 안 하는 것이다
    off = asyncio.run(module.DocumentProcessor()(None, SAMPLE, align_vector_schema="0"))
    check("`align_vector_schema=0` 이면 예약 필드를 채우지 않는다",
          "title" not in off[0], sorted(off[0])[:6])


# ───────────────────────────────────────────────────────────────
# 5. 벤더 부재를 통과로 보이게 하지 않는가
# ───────────────────────────────────────────────────────────────
def check_vendor_absence(module) -> None:
    failure = module._sp_engine_error("intel")
    if failure is None:
        skip("벤더 부재 처리", "로컬에 docling 스택이 있어 지능형 절반이 떴다")
        check("지능형 절반이 떴으면 진입점이 개명돼 있다",
              hasattr(module, "IntelligentDocumentProcessor"))
        return
    skip("지능형 실행", f"로컬에 docling 스택이 없다 ({type(failure).__name__}) — 통과가 아니다")
    check("벤더 부재가 예외로 드러난다 (빈 목록이 아니다)", failure is not None)

    async def _run():
        try:
            await module.DocumentProcessor()._acquire(None)
        except module.SmartPreprocessorError as exc:
            return str(exc)
        return ""

    message = asyncio.run(_run())
    check("벤더를 쓸 수 없으면 사유가 담긴 오류를 낸다", "지능형" in message and "ModuleNotFound" in message,
          message[:120])
    check("hwpx 경로는 벤더 없이도 산다", module._sp_engine_error("hwpx") is None)


def main() -> int:
    module = _load()
    check_merge_matches_reference()
    check_no_name_collisions()
    check_hwpx_half_matches_final()
    check_routing(module)
    check_kwargs_not_forwarded(module)
    check_schema_alignment(module)
    check_hwpx_records(module)
    check_vendor_absence(module)

    for line in _fail:
        print("FAIL " + line)
    for line in _skip:
        print("SKIP " + line)
    print(f"\nOK {len(_ok)} / FAIL {len(_fail)} / SKIP {len(_skip)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
