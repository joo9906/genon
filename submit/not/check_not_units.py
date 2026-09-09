"""`not/` 판본 점검 — lxml 이 정말 안 닿는가, 그리고 **정본과 결과가 같은가**.

    export PYTHONIOENCODING=utf-8
    python not/check_not_units.py

## 이 점검이 없으면 무엇을 놓치나

`not/` 은 "`lxml` 이 없어도 돌아간다"는 것이 존재 이유인데, **로컬에는 `lxml` 이 깔려
있다.** 그래서 그냥 돌려 보면 잘 도는 것처럼 보이고, 폐쇄망에 올린 뒤에야 어느 파일이
아직 `lxml` 을 끌어오는지 드러난다. 여기서는 `lxml`·`jinja2`·`openai` 를 **import 단계에서
막고** 두 단위를 실제로 띄운다.

그리고 더 중요한 것: **정본과 출력이 같은가.** 파서를 표준 라이브러리로 옮기면서 글자가
하나라도 달라지면 사용자가 받는 문서가 달라진다 — 예외가 나지 않고 결과물로만 드러나는
종류다. 실물 hwpx 와 슬롯 픽스처를 **두 구현에 같이 태워** 대조한다(정적 diff 가 아니라
동작으로 본다 — `onprem/test/check_table_grid.py` 와 같은 방식).

로컬에 `lxml` 이 없으면 그 대조는 할 수 없다. 그때 **조용히 통과시키지 않는다** —
SKIP 으로 세어 출력에 남긴다(`onprem/eval` 의 "미측정을 통과로 보이게 하지 않는다").
"""

from __future__ import annotations

import builtins
import difflib
import glob
import importlib
import io
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOT_DIR = os.path.join(ROOT, "not")
CODESERVING = os.path.join(ROOT, "onprem", "codeserving")
FAQ_DIR = os.path.join(NOT_DIR, "SFR-018_faq")
T006_DIR = os.path.join(NOT_DIR, "SFR-006_template_fill")
TRANS_DIR = os.path.join(NOT_DIR, "SFR-018_translation")
POLISH_DIR = os.path.join(NOT_DIR, "SFR-018_text_polish")
ONPREM_006 = os.path.join(CODESERVING, "SFR-006_template_fill")

# 네 단위 전부가 `not/` 에 있다. **글다듬이는 원래 `lxml` 이 없어 사본이 정본과 같지만**,
# 등록 화면에서 어느 단위가 어느 판본인지가 사람 머릿속에만 남지 않게 함께 둔다.
UNITS = ("SFR-006_template_fill", "SFR-018_text_polish", "SFR-018_translation", "SFR-018_faq")

# 이 판본이 쓰면 안 되는 패키지. `multipart` 는 넣지 않는다 — starlette 가 자기 안에서
# 선택적으로 들여오고(`try/except ModuleNotFoundError`) FAQ 는 라우트가 없어 요구하지
# 않지만, 006 은 파일 업로드 라우트가 있어 **정당하게 필요하다.**
BANNED = ("lxml", "jinja2", "openai")

_ok: list = []
_fail: list = []
_skip: list = []


def check(label: str, condition: bool, detail: str = "") -> None:
    (_ok if condition else _fail).append(label + (f" — {detail}" if detail and not condition else ""))


def skip(label: str, why: str) -> None:
    _skip.append(f"{label} — {why}")


# ───────────────────────────────────────────────────────────────
# 1. 금지 패키지를 막고 두 단위를 실제로 띄운다
# ───────────────────────────────────────────────────────────────
def _import_with_banned_blocked(path: str, module: str):
    """`BANNED` 를 `ModuleNotFoundError` 로 막고 import 한다.

    `ImportError` 가 아니라 `ModuleNotFoundError` 를 던지는 것이 중요하다 — starlette 는
    `except ModuleNotFoundError` 로 multipart 부재를 흡수한다. `ImportError` 를 던지면
    그 방어를 지나쳐 **우리 코드와 무관한 자리에서** 실패하고, 원인을 엉뚱한 데서 찾는다.
    """
    # **네 단위가 서로의 모듈을 물려받지 않게 통째로 비운다.** 번역과 글다듬이는 둘 다
    # 진입점이 단위 루트의 `main.py` 라 `sys.modules["main"]` 을 놓고 다투고, `config`·
    # `api_contract` 도 이름이 겹친다 — 안 비우면 **두 번째 단위가 첫 번째의 모듈을 그대로
    # 쓰고도 통과한다**(라우트 목록이 앞 단위 것이므로 오히려 그럴듯해 보인다).
    for name in list(sys.modules):
        head = name.split(".")[0]
        if head in ("template_fill", "faq", "translation_pipeline", "text_polish",
                    "main", "api_contract", "config", "prompt_loader"):
            del sys.modules[name]
    real = builtins.__import__

    def guard(name, *a, **k):
        if name.split(".")[0] in BANNED:
            raise ModuleNotFoundError(f"BLOCKED: {name}")
        return real(name, *a, **k)

    sys.path.insert(0, path)
    builtins.__import__ = guard
    try:
        return importlib.import_module(module)
    finally:
        builtins.__import__ = real
        sys.path.pop(0)


def check_boot() -> None:
    for label, path, module, want, unwanted in (
        ("FAQ", FAQ_DIR, "faq.main",
         {"/generate", "/download", "/faqs", "/health"}, {"/generate/upload"}),
        ("006", T006_DIR, "template_fill.main",
         {"/generate", "/preview", "/templates", "/health"}, set()),
        ("번역", TRANS_DIR, "main",
         {"/translate", "/translate/markdown", "/download", "/languages", "/health"},
         {"/translate/hwpx"}),
        ("글다듬이", POLISH_DIR, "main",
         {"/polish", "/download", "/policies", "/health"}, set()),
    ):
        try:
            mod = _import_with_banned_blocked(path, module)
        except Exception as exc:  # noqa: BLE001
            check(f"{label}: 금지 패키지 없이 기동", False, f"{type(exc).__name__}: {exc}")
            continue
        check(f"{label}: 금지 패키지({', '.join(BANNED)}) 없이 기동", True)
        paths = {getattr(r, "path", "") for r in mod.app.routes}
        check(f"{label}: 라우트 유지 {sorted(want)}", want <= paths, f"없는 것 {sorted(want - paths)}")
        if unwanted:
            check(
                f"{label}: {sorted(unwanted)} 는 없다 (hwpx 직접 파싱 경로)",
                not (unwanted & paths),
            )


# ───────────────────────────────────────────────────────────────
# 2. requirements 선언 — 코드가 안 쓰는 것을 적어 두면 배포가 막힌다
# ───────────────────────────────────────────────────────────────
def check_requirements() -> None:
    for label, path, banned in (
        ("FAQ", os.path.join(FAQ_DIR, "requirements.txt"),
         ("lxml", "jinja2", "openai", "python-multipart")),
        ("번역", os.path.join(TRANS_DIR, "requirements.txt"),
         ("lxml", "jinja2", "openai", "python-multipart")),
        ("글다듬이", os.path.join(POLISH_DIR, "requirements.txt"),
         ("lxml", "jinja2", "openai")),
        # 006 만 `python-multipart` 를 남긴다 — hwpx **읽기**는 되므로 템플릿 등록
        # (`POST /templates`)과 `/generate/upload` 가 여전히 파일을 받는다.
        ("006", os.path.join(T006_DIR, "requirements.txt"), ("lxml", "jinja2", "openai")),
    ):
        declared = {
            line.split(">=")[0].split("==")[0].strip().lower()
            for line in io.open(path, encoding="utf-8").read().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        for pkg in banned:
            check(f"{label} requirements: `{pkg}` 선언 없음", pkg not in declared)


# ───────────────────────────────────────────────────────────────
# 3. 프롬프트 사본이 정본과 같은가 (드리프트 방지)
# ───────────────────────────────────────────────────────────────
def check_prompt_copies() -> None:
    for unit in UNITS:
        src = os.path.join(ROOT, "onprem", "prompt", unit)
        dst = os.path.join(NOT_DIR, "prompt", unit)
        if not os.path.isdir(src):
            check(f"프롬프트 정본 존재: {unit}", False, src)
            continue
        names = sorted(os.listdir(src))
        check(f"프롬프트 파일 목록 일치: {unit}", names == sorted(os.listdir(dst)))
        for name in names:
            a = io.open(os.path.join(src, name), "rb").read()
            b_path = os.path.join(dst, name)
            b = io.open(b_path, "rb").read() if os.path.isfile(b_path) else b""
            check(f"프롬프트 본문 일치: {unit}/{name}", a == b)


# ───────────────────────────────────────────────────────────────
# 3-2. 글다듬이는 **정본과 코드가 같아야 한다**
# ───────────────────────────────────────────────────────────────
def _strip_module_docstring(source: str) -> str:
    """모듈 docstring 을 지운 소스. 판본 표시만 다르고 코드는 같은지 보려는 것이다."""
    import ast

    tree = ast.parse(source)
    doc = ast.get_docstring(tree, clean=False)
    if doc is None or not tree.body:
        return source
    node = tree.body[0]
    lines = source.split("\n")
    return "\n".join(lines[: node.lineno - 1] + lines[node.end_lineno:])


def check_polish_is_untouched() -> None:
    """글다듬이는 **원래부터 `lxml` 이 없다** — 그래서 고칠 것이 없었다.

    고칠 것이 없다는 사실 자체를 점검한다. 사본을 두면 언젠가 누군가 여기서 고치고,
    그러면 정본과 갈린다 — 그 어긋남은 오류가 아니라 **결과물의 문체로만** 드러난다
    (톤 프리셋 사본 대조와 같은 취지).

    `main.py` 만 **모듈 docstring 을 빼고** 대조한다. 그 파일에는 "이건 `not/` 판본이고
    정본과 같다" 는 표시를 달아 뒀는데, 그 표시가 없으면 파일만 보고는 어느 쪽인지 알
    수 없다. 코드는 한 글자도 다르면 안 된다.
    """
    src_root = os.path.join(CODESERVING, "SFR-018_text_polish")
    for base, _dirs, files in os.walk(src_root):
        if "__pycache__" in base:
            continue
        for name in sorted(files):
            rel = os.path.relpath(os.path.join(base, name), src_root)
            a_path, b_path = os.path.join(src_root, rel), os.path.join(POLISH_DIR, rel)
            if not os.path.isfile(b_path):
                check(f"글다듬이 정본 대조: {rel}", False, "사본에 파일이 없다")
                continue
            a = io.open(a_path, "rb").read()
            b = io.open(b_path, "rb").read()
            if rel == "main.py":
                same = _strip_module_docstring(a.decode("utf-8")) == _strip_module_docstring(
                    b.decode("utf-8")
                )
                check("글다듬이 정본 대조: main.py (판본 표시 제외한 코드)", same)
            else:
                check(f"글다듬이 정본 대조: {rel}", a == b, "정본과 갈렸다")


# ───────────────────────────────────────────────────────────────
# 4. **정본과 출력이 같은가** — 이 점검의 핵심
# ───────────────────────────────────────────────────────────────
def _load(path: str, names):
    for name in list(sys.modules):
        if name.startswith("template_fill"):
            del sys.modules[name]
    sys.path.insert(0, path)
    try:
        return {n: importlib.import_module("template_fill." + n) for n in names}
    finally:
        sys.path.pop(0)


_T_OPEN = "<hp:t>"
_T_CLOSE = "</hp:t>"


def _split_slot_text_nodes(xml: str) -> str:
    """슬롯이 든 `<hp:t>` 를 **둘로 쪼갠다** — 슬롯이 노드 경계를 걸치게 만든다.

    이 픽스처가 왜 따로 필요한지가 이 함수의 존재 이유다. 실물 `파워.hwpx` 는 슬롯
    글자가 `hp:t` **하나**에 다 들어 있어서, "첫 노드에 값을 넣고 나머지를 비운다"는
    규칙의 뒷부분(`nodes[1:]` 비우기)이 **한 번도 실행되지 않는다.** 그 줄을 지워도
    점검이 통과하는 것을 실제로 확인하고 이 함수를 넣었다.

    실물에서 이 모양은 흔하다 — 템플릿 작성자가 슬롯 가운데에서 글꼴을 바꾸거나
    한/글이 자동 고침을 하면 run·`hp:t` 가 갈린다. 비우지 않으면 옛 글자가 남아
    `구분 : 정기분', 14pt}` 처럼 문서에 두 번 적힌다(정본 `rewrite_slots` 주석).
    """
    out: list = []
    cursor = 0
    while True:
        start = xml.find(_T_OPEN, cursor)
        if start < 0:
            break
        body_at = start + len(_T_OPEN)
        end = xml.find(_T_CLOSE, body_at)
        if end < 0:
            break
        body = xml[body_at:end]
        out.append(xml[cursor:body_at])
        if "{'" in body and len(body) > 3:
            half = len(body) // 2
            out.append(body[:half] + _T_CLOSE + _T_OPEN + body[half:])
        else:
            out.append(body)
        cursor = end
    out.append(xml[cursor:])
    return "".join(out)


def _slot_fixture(raw: bytes, *, split_nodes: bool = False) -> bytes:
    """실물 템플릿의 따옴표 없는 중괄호를 **따옴표 슬롯**으로 바꾼다.

    저장소의 실물 hwpx 에는 따옴표 슬롯도 누름틀도 없어서 **채우기 경로가 한 번도
    태워지지 않는다.** 손으로 지은 XML 대신 실물을 고쳐 쓰는 이유는 표·구역·서식이
    실제 문서 그대로 남기 때문이다.

    Args:
        split_nodes: 슬롯을 `hp:t` 경계에 걸치게 쪼갠다 (`_split_slot_text_nodes`).
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as src, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename.startswith("Contents/section"):
                text = data.decode("utf-8")
                for name in ("제목", "본문", "소속", "성명"):
                    text = text.replace("{" + name, "{'" + name + "'")
                if split_nodes:
                    text = _split_slot_text_nodes(text)
                data = text.encode("utf-8")
            dst.writestr(
                item.filename,
                data,
                zipfile.ZIP_STORED if item.filename == "mimetype" else zipfile.ZIP_DEFLATED,
            )
    return buf.getvalue()


def _diff(a: str, b: str) -> str:
    return "\n".join(list(difflib.unified_diff(a.split("\n"), b.split("\n"), lineterm="", n=1))[:16])


def check_against_onprem() -> None:
    try:
        import lxml  # noqa: F401
    except ModuleNotFoundError:
        skip("정본 대조", "로컬에 `lxml` 이 없어 정본을 태울 수 없다 (통과가 아니다)")
        return

    samples = sorted(glob.glob(os.path.join(ROOT, "data", "*.hwpx")))
    if not samples:
        skip("정본 대조", "`data/*.hwpx` 를 찾지 못했다 — 실물을 옮겼으면 경로를 고칠 것")
        return

    mods = ("hwpx_fields", "hwpx_markdown", "document", "hwpx_blocks")

    # (1) 읽기 — 실물 전부
    for path in samples:
        raw = io.open(path, "rb").read()
        name = os.path.basename(path)
        a = _load(ONPREM_006, mods)
        ref_text = a["hwpx_markdown"].render_markdown(raw).markdown
        ref_specs = [(s.name, s.field_type, s.guide, s.occurrences) for s in a["hwpx_fields"].scan_fields(raw)]
        ref_bare = a["hwpx_fields"].bare_brace_samples(raw)
        b = _load(T006_DIR, mods)
        got_text = b["hwpx_markdown"].render_markdown(raw).markdown
        got_specs = [(s.name, s.field_type, s.guide, s.occurrences) for s in b["hwpx_fields"].scan_fields(raw)]
        got_bare = b["hwpx_fields"].bare_brace_samples(raw)
        check(f"정본 대조/문단 텍스트: {name}", ref_text == got_text, _diff(ref_text, got_text))
        check(f"정본 대조/항목 스캔: {name}", ref_specs == got_specs, f"{ref_specs} != {got_specs}")
        check(f"정본 대조/따옴표 없는 중괄호: {name}", ref_bare == got_bare)

    # (2) 채우기 — 슬롯 픽스처 두 벌
    base = io.open(os.path.join(ROOT, "data", "파워.hwpx"), "rb").read()
    for split in (False, True):
        _check_fill_parity(_slot_fixture(base, split_nodes=split), mods, split)


def _check_fill_parity(fixture: bytes, mods, split_nodes: bool) -> None:
    tag = "슬롯이 노드에 걸침" if split_nodes else "슬롯이 한 노드 안"
    values = {"제목": "2026년 사업 계획", "본문": "본문 내용입니다", "소속": "AI팀", "성명": "왕주영"}
    block_kw = dict(text="추진 배경\n첫째 줄\n둘째 줄", style_ref="제목")

    a = _load(ONPREM_006, mods)
    a_built = a["document"].build(fixture, values, [a["hwpx_blocks"].BodyBlock(**block_kw)], apply_style=False)
    ref_fill = a["hwpx_markdown"].render_markdown(a_built.hwpx_bytes).markdown
    ref_meta = (a_built.written_fields, a_built.missing_fields, a_built.unknown_keys,
                a_built.leftover_tokens, a_built.appended_blocks)
    ref_styles = a["hwpx_blocks"].block_style_names(fixture)
    ref_prev = a["hwpx_markdown"].render_filled(
        fixture, values, max_chars=None, blocks=[a["hwpx_blocks"].BodyBlock(**block_kw)]
    ).markdown

    b = _load(T006_DIR, mods)
    b_built = b["document"].build(fixture, values, [b["hwpx_blocks"].BodyBlock(**block_kw)], apply_style=False)
    got_fill = b["document"].to_text(fixture, b_built)
    got_meta = (b_built.written_fields, b_built.missing_fields, b_built.unknown_keys,
                b_built.leftover_tokens, b_built.appended_blocks)
    got_styles = b["hwpx_blocks"].block_style_names(fixture)
    got_prev = b["hwpx_markdown"].render_filled(
        fixture, values, max_chars=None, blocks=[b["hwpx_blocks"].BodyBlock(**block_kw)]
    ).markdown

    check(f"정본 대조/채운 본문 ({tag})", ref_fill == got_fill, _diff(ref_fill, got_fill))
    check(f"정본 대조/채우기 메타 ({tag})", ref_meta == got_meta, f"{ref_meta} != {got_meta}")
    check(f"정본 대조/블록 서식 이름 ({tag})", ref_styles == got_styles)
    check(f"정본 대조/미리보기 ({tag})", ref_prev == got_prev, _diff(ref_prev, got_prev))
    # 아래 셋은 위 넷이 못 잡는 자리를 본다 — **두 구현이 똑같이 아무것도 안 해도** 위
    # 넷은 통과한다(둘 다 정본과 같은 코드에서 갈라져 나왔으므로 같은 실수를 함께 한다).
    check(f"정본 대조/값이 실제로 채워졌다 ({tag})",
          "2026년 사업 계획" in got_fill and "{'제목'" not in got_fill, got_fill[:120])
    check(f"정본 대조/슬롯 표기가 남지 않았다 ({tag})",
          "16pt}" not in got_fill and "HY헤드라인M" not in got_fill, got_fill[:200])
    check(f"정본 대조/블록이 실제로 들어갔다 ({tag})", "둘째 줄" in got_fill)


# ───────────────────────────────────────────────────────────────
# 5. 006 다운로드가 **txt** 인가
# ───────────────────────────────────────────────────────────────
def check_download_is_txt() -> None:
    mods = _load(T006_DIR, ("hwpx_fields", "hwpx_markdown", "document", "hwpx_blocks", "api_download", "txt_output"))
    sample = os.path.join(ROOT, "data", "파워.hwpx")
    if not os.path.isfile(sample):
        skip("다운로드 응답", "`data/파워.hwpx` 없음")
        return
    raw = io.open(sample, "rb").read()
    built = mods["document"].build(raw, {}, None, label="파워")
    response = mods["api_download"].download_response(built, "초안.hwpx", raw)

    disposition = response.headers.get("content-disposition", "")
    check("다운로드: 확장자가 .txt", disposition.endswith(".txt"), disposition)
    check("다운로드: 옛 `.hwpx` 확장자를 겹쳐 붙이지 않는다", ".hwpx" not in disposition, disposition)
    check("다운로드: X-Document-Format=txt", response.headers.get("x-document-format") == "txt")
    check("다운로드: BOM 으로 시작 (메모장 인코딩 확정)", response.body.startswith(b"\xef\xbb\xbf"))
    check("다운로드: CRLF 줄바꿈", b"\r\n" in response.body)
    check("다운로드: 본문에 문서 글자가 있다", "제 목".encode("utf-8") in response.body)


def main() -> int:
    check_boot()
    check_requirements()
    check_prompt_copies()
    check_polish_is_untouched()
    check_against_onprem()
    check_download_is_txt()

    for line in _fail:
        print("FAIL " + line)
    for line in _skip:
        print("SKIP " + line)
    print(f"\nOK {len(_ok)} / FAIL {len(_fail)} / SKIP {len(_skip)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
