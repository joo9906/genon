"""배포 계약 정적 점검 — 서버를 띄우지 않고 소스만 읽는다.

개발가이드 6장(코드 서빙)·11.5 에서 나온 조항 중 **소스만 보고 판정 가능한 것**을 검사한다.
import 도 하지 않고 포트도 열지 않으므로, 의존 패키지가 설치돼 있지 않아도 돌아간다.

실행:
    python onprem/test/check_deploy_contract.py

종료 코드: FAIL 이 하나라도 있으면 1, 아니면 0.

여기서 못 잡는 것(실물 서버가 필요한 것)은 `verify_serving.py` 가 맡는다.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

ONPREM = Path(__file__).resolve().parent.parent

# GenOS 가 실행 설정으로 주입하는 이름 (가이드 6.3·6.7).
# 애플리케이션이 같은 이름을 **다른 목적으로** 쓰면 안 된다.
RESERVED_ENV = {"PORT", "OPENAPI_PATH", "LANGUAGE", "BUILD_COMMAND", "START_COMMAND"}

# import 이름 → requirements.txt 에 적히는 배포 이름
DIST_BY_IMPORT = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "lxml": "lxml",
    "redis": "redis",
    "httpx": "httpx",
    "openai": "openai",
    "mcp": "mcp",
    # import 이름과 배포 이름이 다른 경우. 이 표에 없으면 requirements 에 적어 두고도
    # "선언 누락"으로 잡힌다. 006 은 이 라이브러리를 벤더 사본으로 들여 더 이상 import
    # 하지 않지만(2026-08-10), **eval 은 `doc_diff` 교차검증에 여전히 pip 로 쓴다** —
    # 그래서 별칭은 남는다 (뺐다가 eval 이 오탐으로 잡혀 되돌렸다, 2026-08-11).
    "hwpx": "python-hwpx",
}

# pip 로 설치할 수 없고 **이미지·pod 가 제공해야 하는** 것들 (가이드 11.5.6).
# requirements 에 적는 것이 답이 아니므로 FAIL 이 아니라 WARN 으로 알린다.
IMAGE_PROVIDED = {
    "genon": "전처리기 패키지 — 코드 서빙 기본 이미지에 포함돼야 한다",
    "main_socketio": "GenOS 워크플로우 런타임이 주입한다",
}

# fastapi 의 Form/File/UploadFile 을 쓰면 import 없이도 이 패키지가 필요하다.
#
# `File(`·`Form(` 을 맨 문자열로 찾으면 **`zipfile.ZipFile(` 이 걸린다** — eval 이 그래서
# python-multipart 를 요구한다고 잘못 잡혔다(2026-08-11 수정). 이 표기들은 실제로는
# 기본값 자리에만 나오므로(`document: UploadFile = File(...)`) `= ` 를 함께 요구한다.
# `UploadFile` 은 타입 주석으로도 쓰이니 그대로 둔다.
MULTIPART_MARKERS = ("UploadFile", "= File(", "= Form(")


@dataclass
class Unit:
    """배포 단위 하나."""

    name: str
    area: str  # "03" 코드서빙 / "02" 워크플로우 / "mcp" 평가지표 MCP
    root: str  # onprem 기준 상대 경로
    entry: str = ""  # 코드서빙 진입 모듈 (uvicorn 대상), 없으면 빈 문자열
    # 워크플로우(02) 단계의 `run()` 이 있는 파일. **한 단위가 두 영역에 걸칠 수 있다** —
    # SFR-006 은 코드서빙 단위이면서 워크플로우 노드도 함께 들고 있다.
    workflow_entry: str = ""
    needs_requirements: bool = True

    @property
    def path(self) -> Path:
        return ONPREM / self.root


# 2026-08-11 영역별 재배치. 세 가지가 달라졌다:
#   1. 코드서빙 4단위가 `onprem/codeserving/` 아래로 내려갔다.
#   2. 워크플로우 노드(`run_chat.py`·`text_polish/main.py`)가 단위 밖 `onprem/workflow/`
#      단일 파일 스텝으로 빠졌다 — 그래서 `workflow_entry` 를 가진 단위가 하나도 없다.
#      대신 `check_workflow_steps()` 가 그 디렉토리를 통째로 본다.
#   3. MCP 서빙 4개가 배포 단위로 새로 생겼다. 등록하지 않으면 `SFR-018_faq` 때처럼
#      requirements 누락을 아무도 못 잡는다 (그게 이 목록의 존재 이유다).
UNITS = [
    Unit(
        name="SFR-006 템플릿 채우기",
        area="03",
        root="codeserving/SFR-006_template_fill",
        entry="template_fill/main.py",
    ),
    Unit(
        name="SFR-018 번역",
        area="03",
        root="codeserving/SFR-018_translation",
        entry="main.py",
    ),
    Unit(
        # 재배치로 **02 에서 03 이 됐다.** 그래서 requirements.txt 가 처음 필요해졌다.
        name="SFR-018 글다듬이",
        area="03",
        root="codeserving/SFR-018_text_polish",
        entry="main.py",
    ),
    Unit(
        # 2026-08-07 에 배포 단위로 들어왔는데 이 목록에 빠져 있었다 — 그래서
        # `requirements.txt` 가 아예 없는 상태를 아무도 잡지 못했다 (2026-08-11 등록).
        name="SFR-018 FAQ",
        area="03",
        root="codeserving/SFR-018_faq",
        entry="faq/main.py",
    ),
    # **MCP 는 여기 없다.** 등록 단위가 디렉토리가 아니라 **소스 파일 한 개**라서
    # `requirements.txt`·`/health`·`$PORT`·진입점이라는 개념이 아예 없다.
    # 아래 `check_mcp_files()` 가 그쪽 계약을 따로 본다 (2026-08-11 정정 —
    # 그전에는 MCP 를 FastAPI 서빙으로 잘못 만들어 두고 이 목록에 넣고 있었다).
    Unit(
        name="평가지표 MCP",
        area="mcp",
        root="eval",
    ),
]

# 워크플로우(02) 스텝이 쓸 수 있는 외부 패키지 (GENOS_RULES §D.3 — pod 기본 이미지).
# `httpx` 외에는 전부 표준 라이브러리이고, `main_socketio` 는 런타임이 주입한다.
WORKFLOW_ALLOWED = {"httpx", "opentelemetry", "main_socketio"}


@dataclass
class Finding:
    level: str  # FAIL / WARN / OK
    unit: str
    check: str
    detail: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, unit: str, check: str, detail: str) -> None:
        self.findings.append(Finding(level, unit, check, detail))

    @property
    def failed(self) -> bool:
        return any(f.level == "FAIL" for f in self.findings)


def _py_files(root: Path) -> list[Path]:
    return [p for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts]


def _local_names(root: Path) -> set[str]:
    """단위 안에서 정의된 모듈/패키지 이름 (외부 의존이 아니다)."""
    names: set[str] = set()
    for p in root.rglob("*"):
        if "__pycache__" in p.parts:
            continue
        if p.suffix == ".py":
            names.add(p.stem)
        elif p.is_dir():
            names.add(p.name)
    return names


def _guarded_import_nodes(tree: ast.AST) -> set[int]:
    """`try: import X / except ImportError: …` 안에 있는 import 노드 id 집합.

    **코드가 부재를 이미 처리하고 있다면 선언 누락이 치명적이지 않다.** 이 저장소는 그
    패턴을 의도적으로 쓴다 — `fastmcp` 는 공식 SDK(`mcp`)가 있으면 아예 안 쓰이고,
    `main_socketio` 는 워크플로우 런타임이 주입한다. 그런 것들을 FAIL 로 올리면 점검이
    **영구히 빨간색**이 되고, 그러면 아무도 안 본다 — 실제로 그 상태여서
    `SFR-018_faq` 에 requirements.txt 가 통째로 없는 것을 반년 가까이 못 잡았다.

    (2026-08-12 까지는 FAQ 의 weasyprint·markdown·openpyxl 이 이 패턴의 주된 예였다.
    "없으면 그 형식만 501" 이 그 방어의 내용이었는데, 산출 형식이 txt 로 통일되면서
    선택적 형식 자체가 없어졌다 — 지금 FAQ 는 선택적 의존이 0개다.)

    이름 하드코딩이 아니라 **코드의 방어 여부**로 판정하는 것이 요점이다.
    """
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        handles_import_error = any(
            handler.type is None  # bare except
            or (isinstance(handler.type, ast.Name) and handler.type.id in ("ImportError", "ModuleNotFoundError"))
            or (
                isinstance(handler.type, ast.Tuple)
                and any(
                    isinstance(e, ast.Name) and e.id in ("ImportError", "ModuleNotFoundError")
                    for e in handler.type.elts
                )
            )
            for handler in node.handlers
        )
        if not handles_import_error:
            continue
        # try 본문뿐 아니라 **핸들러 안의 import 도 방어된 것**으로 본다. 거기 있는 것은
        # 정의상 폴백이고(`mcp` 가 없을 때만 `fastmcp` 를 쓴다), 주 경로가 선언돼 있으면
        # 실행되지 않는다.
        for statement in list(node.body) + [s for h in node.handlers for s in h.body]:
            for inner in ast.walk(statement):
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    guarded.add(id(inner))
    return guarded


def _third_party_imports(root: Path) -> dict[str, set[str]]:
    """{import 최상위 이름: 그 이름을 쓰는 파일 경로 집합}

    `try/except ImportError` 로 감싼 import 는 이름 앞에 `?` 를 붙여 구분한다 —
    호출부가 FAIL 과 WARN 을 나누는 근거다.
    """
    local = _local_names(root)
    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    found: dict[str, set[str]] = {}

    for path in _py_files(root):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except SyntaxError as exc:  # 구문 오류 자체가 결함이다
            found.setdefault("<syntax-error>", set()).add(f"{path}: {exc}")
            continue

        guarded = _guarded_import_nodes(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # 상대 import 는 항상 로컬
                    continue
                mods = [node.module or ""]
            else:
                continue

            for mod in mods:
                top = mod.split(".")[0]
                if not top or top in stdlib or top in local:
                    continue
                key = f"?{top}" if id(node) in guarded else top
                found.setdefault(key, set()).add(str(path.relative_to(ONPREM)))

    # 한 곳이라도 무방비로 import 하면 그 패키지는 필수다 — 방어 표시를 지운다.
    for key in [k for k in found if k.startswith("?")]:
        if key[1:] in found:
            found[key[1:]] |= found.pop(key)
    return found


def _declared_dists(req: Path) -> set[str]:
    dists: set[str] = set()
    for raw in req.read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].strip()
        if not line:
            continue
        for sep in ("==", ">=", "<=", "~=", ">", "<", "[", ";"):
            line = line.split(sep)[0]
        dists.add(line.strip().lower())
    return dists


def check_requirements(unit: Unit, rep: Report) -> None:
    """가이드 6.3·11.5.6 — 빌드 커맨드가 설치할 의존성 파일이 실제 import 를 덮는가."""
    req = unit.path / "requirements.txt"

    if not unit.needs_requirements:
        imports = sorted(set(_third_party_imports(unit.path)) & set(DIST_BY_IMPORT))
        rep.add(
            "OK",
            unit.name,
            "requirements",
            f"워크플로우(02) 단위 — pod 기본 이미지에 필요: {', '.join(imports) or '없음'}",
        )
        return

    if not req.exists():
        rep.add("FAIL", unit.name, "requirements", "requirements.txt 없음 — 빌드 커맨드가 설치할 대상이 없다")
        return

    declared = _declared_dists(req)
    imports = _third_party_imports(unit.path)

    missing: list = []    # 없으면 기동하거나 동작하지 못한다 → FAIL
    tolerated: list = []  # 이미지가 주거나 코드가 부재를 처리한다 → WARN
    for name in sorted(imports):
        if name == "<syntax-error>":
            rep.add("FAIL", unit.name, "구문", "; ".join(sorted(imports[name])))
            continue
        guarded = name.startswith("?")
        bare = name[1:] if guarded else name
        dist = DIST_BY_IMPORT.get(bare, bare).lower()
        if dist in declared:
            continue
        users = ", ".join(sorted(imports[name])[:3])
        if bare in IMAGE_PROVIDED:
            tolerated.append(f"{bare} ({IMAGE_PROVIDED[bare]})")
        elif guarded:
            tolerated.append(f"{dist} (try/except ImportError 로 방어됨 — {users})")
        else:
            missing.append(f"{dist} (import {bare} — {users})")

    # fastapi 의 multipart 폼은 import 없이 python-multipart 를 요구한다.
    # **런타임 실패가 아니라 기동 실패다** — 라우트 등록 시점에 RuntimeError 가 난다.
    if _uses_multipart(unit.path) and "python-multipart" not in declared:
        missing.append("python-multipart (UploadFile/File/Form 사용 — 없으면 라우트 등록 단계에서 기동 실패)")

    if missing:
        rep.add("FAIL", unit.name, "requirements", "선언 누락: " + "; ".join(missing))
    else:
        rep.add("OK", unit.name, "requirements", f"{len(declared)}개 선언, 필수 import 전부 덮음")
    if tolerated:
        rep.add("WARN", unit.name, "requirements", "선언 밖(의도된 것): " + "; ".join(tolerated))


def _uses_multipart(root: Path) -> bool:
    for path in _py_files(root):
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in MULTIPART_MARKERS):
            return True
    return False


# 코드 서빙 전용 패키지 — `requirements.txt` 로 설치되는 것들이다.
# 워크플로우(02) pod 는 그 파일을 설치하지 않으므로(11.5.6), 워크플로우 진입점에서
# 여기 닿으면 **그 단계가 통째로 기동하지 않는다.**
SERVING_ONLY = {"fastapi", "uvicorn", "pydantic", "starlette"}


def _module_graph(root: Path) -> dict[str, tuple[set[str], set[str]]]:
    """{모듈 stem: (같은 패키지 내 import, 외부 import)} — 상대 import 만 따라간다."""
    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    graph: dict[str, tuple[set[str], set[str]]] = {}
    for path in _py_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        local: set[str] = set()
        external: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level and node.module:
                    local.add(node.module.split(".")[0])
                elif not node.level and node.module:
                    top = node.module.split(".")[0]
                    if top not in stdlib:
                        external.add(top)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in stdlib:
                        external.add(top)
        graph[path.stem] = (local, external)
    return graph


def check_workflow_deps(unit: Unit, rep: Report) -> None:
    """워크플로우(02) 진입점이 **코드 서빙 전용 패키지를 끌어오지 않는지** 본다.

    왜 필요한가: 한 단위가 두 영역에 걸치면(SFR-006) 같은 패키지 안에 워크플로우 모듈과
    FastAPI 모듈이 함께 산다. 공용 헬퍼를 만들다가 그 헬퍼가 fastapi 를 import 하면,
    **워크플로우 진입점이 전이적으로 fastapi 를 필요로 하게 된다.** 워크플로우 pod 는
    `requirements.txt` 를 설치하지 않으므로 그 순간 단계 전체가 기동하지 않는다.

    실제로 한 번 그렇게 만들었다(`ApiError` 를 fastapi 를 import 하는 파일에 뒀다).
    눈으로는 안 보이는 종류의 결함이라 여기서 기계적으로 본다.
    """
    if not unit.workflow_entry:
        return
    entry = unit.path / unit.workflow_entry
    if not entry.exists():
        rep.add("FAIL", unit.name, "워크플로우 의존", f"진입 파일 없음: {unit.workflow_entry}")
        return

    graph = _module_graph(unit.path)
    seen: set[str] = set()
    stack = [entry.stem]
    external: set[str] = set()
    while stack:
        module = stack.pop()
        if module in seen or module not in graph:
            continue
        seen.add(module)
        local, ext = graph[module]
        external |= ext
        stack.extend(local)

    leaked = sorted(external & SERVING_ONLY)
    if leaked:
        rep.add(
            "FAIL",
            unit.name,
            "워크플로우 의존",
            f"{unit.workflow_entry} 가 코드서빙 전용 패키지를 끌어온다: {', '.join(leaked)}"
            " — 워크플로우 pod 는 requirements.txt 를 설치하지 않는다 (11.5.6)",
        )
        return
    # GenOS 가 주입하는 모듈은 기본 이미지 요구 목록에서 뺀다
    needed = sorted(external - {"main_socketio"})
    rep.add(
        "OK",
        unit.name,
        "워크플로우 의존",
        f"{unit.workflow_entry} → pod 기본 이미지에 필요: {', '.join(needed) or '없음'}",
    )


def check_health_route(unit: Unit, rep: Report) -> None:
    """가이드 6.4·11.5.3 — 코드 서빙은 GET /health 가 200 을 줘야 한다.

    MCP 서빙도 같은 컨테이너 계약을 탄다(FastAPI + `$PORT`). 그래서 영역이 아니라
    **진입점 유무**로 대상을 정한다 — eval 만 진입점이 없어 빠진다.
    """
    if not unit.entry:
        return
    entry = unit.path / unit.entry
    if not entry.exists():
        rep.add("FAIL", unit.name, "/health", f"진입 파일 없음: {unit.entry}")
        return
    text = entry.read_text(encoding="utf-8")
    if '"/health"' in text or "'/health'" in text:
        rep.add("OK", unit.name, "/health", f"{unit.entry} 에 정의됨")
    else:
        rep.add("FAIL", unit.name, "/health", f"{unit.entry} 에 /health 라우트가 없다")


def check_entrypoint(unit: Unit, rep: Report) -> None:
    """가이드 6.2 — 루트 main.py 는 자동 실행 경로를 탄다.

    루트에 main.py 가 있으면 GenOS 가 그 파일을 먼저 실행하므로 기동 블록이 있어야 한다.
    진입점이 패키지 안이면 자동 경로에 안 걸리므로 시작(Run) 커맨드 등록이 필수다.
    """
    if not unit.entry:
        return

    root_main = unit.path / "main.py"
    if root_main.exists():
        text = root_main.read_text(encoding="utf-8")
        has_guard = '__name__ == "__main__"' in text or "__name__ == '__main__'" in text
        has_run = "uvicorn.run" in text
        has_bind = '"0.0.0.0"' in text or "'0.0.0.0'" in text
        if has_guard and has_run and has_bind:
            rep.add("OK", unit.name, "진입점", "루트 main.py 자동 실행 경로 + 0.0.0.0 기동 블록 있음")
        else:
            rep.add(
                "FAIL",
                unit.name,
                "진입점",
                "루트 main.py 가 자동 실행되는데 기동 블록이 불완전하다 "
                f"(__main__={has_guard}, uvicorn.run={has_run}, 0.0.0.0={has_bind})",
            )
    else:
        rep.add(
            "WARN",
            unit.name,
            "진입점",
            f"루트 main.py 없음 ({unit.entry}) — 시작(Run) 커맨드 등록이 필수다",
        )


def check_reserved_env(unit: Unit, rep: Report) -> None:
    """가이드 6.7 — GenOS 주입 이름을 다른 목적으로 쓰지 않는다."""
    hits: list[str] = []
    for path in _py_files(unit.path):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            # os.environ["X"] = ... / os.environ.setdefault("X", ...) 로 덮어쓰는 경우
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if (
                        isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.value, ast.Attribute)
                        and tgt.value.attr == "environ"
                        and isinstance(tgt.slice, ast.Constant)
                        and tgt.slice.value in RESERVED_ENV
                    ):
                        hits.append(f"{path.relative_to(ONPREM)}: {tgt.slice.value} 대입")
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "setdefault":
                    if node.args and isinstance(node.args[0], ast.Constant):
                        if node.args[0].value in RESERVED_ENV:
                            hits.append(
                                f"{path.relative_to(ONPREM)}: {node.args[0].value} setdefault"
                            )
    if hits:
        rep.add("FAIL", unit.name, "예약 환경변수", "; ".join(hits))
    else:
        rep.add("OK", unit.name, "예약 환경변수", f"{', '.join(sorted(RESERVED_ENV))} 덮어쓰지 않음")


def check_no_print(unit: Unit, rep: Report) -> None:
    """GENOS_RULES §C — print() 금지 (로그 시스템에 안 잡히고 stdout 을 오염시킨다)."""
    hits: list[str] = []
    for path in _py_files(unit.path):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                hits.append(f"{path.relative_to(ONPREM)}:{node.lineno}")
    if hits:
        rep.add("FAIL", unit.name, "print 금지", "; ".join(hits))
    else:
        rep.add("OK", unit.name, "print 금지", "없음")


def check_workflow_steps(rep: Report) -> None:
    """`onprem/workflow/` 스텝 파일 하나하나가 캔버스에 붙을 수 있는 상태인지 본다.

    **이 재배치의 요점이 전부 여기 걸려 있다.** 스텝은 코드 한 덩어리로 등록되므로:

    1. `run` 이 있어야 한다 (GenOS 고정 계약 — 이름·인자 1개).
    2. 외부 패키지는 `httpx` 뿐이어야 한다. `lxml`·`redis`·`jinja2` 가 다시 들어오면
       기본 이미지 변경 요청(11.5.6)에 다시 묶인다 — 그게 재배치 이유였다.
    3. **다른 스텝 파일을 import 하면 안 된다.** 공용 모듈로 빼는 순간 캔버스에 붙일 수
       없게 되는데, 로컬에서는 잘 돌아 보여서 등록 시점에야 드러난다.

    파일마다 로깅·오류표가 반복되는 것은 그 대가이고, 의도된 중복이다.
    """
    root = ONPREM / "workflow"
    if not root.exists():
        rep.add("FAIL", "워크플로우 스텝", "존재", "디렉토리 없음: workflow")
        return

    steps = _py_files(root)
    if not steps:
        rep.add("FAIL", "워크플로우 스텝", "존재", "workflow/ 에 스텝 파일이 없다")
        return

    step_names = {p.stem for p in steps}
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    bad_run: list[str] = []
    leaked: list[str] = []
    cross: list[str] = []

    for path in steps:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            rep.add("FAIL", "워크플로우 스텝", "구문", f"{path.name}: {type(exc).__name__}")
            continue

        run_defs = [
            n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "run"
        ]
        if len(run_defs) != 1 or len(run_defs[0].args.args) != 1:
            bad_run.append(path.name)

        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                names = [node.module.split(".")[0]]
            for top in names:
                if top in step_names:
                    cross.append(f"{path.name} → {top}")
                elif top not in stdlib and top not in WORKFLOW_ALLOWED:
                    leaked.append(f"{path.name}: {top}")

    rep.add(
        "FAIL" if bad_run else "OK",
        "워크플로우 스텝",
        "run 시그니처",
        "; ".join(bad_run) + " — `run(data)` 하나여야 한다" if bad_run
        else f"{len(steps)}개 스텝 전부 `run(data)` 단일 정의",
    )
    rep.add(
        "FAIL" if leaked else "OK",
        "워크플로우 스텝",
        "허용 패키지",
        "; ".join(sorted(set(leaked))) + " — 워크플로우 pod 에 없다 (§D.3)" if leaked
        else f"외부 패키지는 {', '.join(sorted(WORKFLOW_ALLOWED))} 뿐",
    )
    rep.add(
        "FAIL" if cross else "OK",
        "워크플로우 스텝",
        "자기완결",
        "; ".join(sorted(set(cross))) + " — 스텝끼리 import 하면 캔버스에 붙일 수 없다"
        if cross else "스텝 간 import 없음 (파일 하나를 그대로 복사해 등록 가능)",
    )


MCP_PREFIXES = {
    "genon_hwpx_text": "HX",
    "genon_text_guard": "TG",
    "genon_lang_policy": "LP",
    "genon_glossary": "GL",
}


def check_logging_copies(rep: Report) -> None:
    """네 코드서빙 단위의 `logging_utils.py` 가 **같은 함수 묶음**인지 본다 (2026-08-14).

    `onprem/README.md` 는 이 파일들을 "같은 계약을 가진 사본" 이라고 적어 뒀는데,
    실제로는 **글다듬이만 `log_error` 가 없었다.** 그래서 그 단위는 내부 오류를
    `log_warning` 으로 남기고 있었고 — 운영이 `level >= ERROR` 로 내부 오류를 거르면
    **그 단위만 안 보인다.** 사본이 갈렸다는 사실을 아무도 보고 있지 않았다.

    이름만 본다(본문 비교는 하지 않는다). 로거 이름·허용 필드는 단위마다 다르고,
    같아야 하는 것은 **호출부가 기대하는 함수 집합**이다.
    """
    units = {
        "006": ONPREM / "codeserving/SFR-006_template_fill/template_fill/logging_utils.py",
        "번역": ONPREM / "codeserving/SFR-018_translation/translation_pipeline/common/logging_utils.py",
        "글다듬이": ONPREM / "codeserving/SFR-018_text_polish/text_polish/logging_utils.py",
        "FAQ": ONPREM / "codeserving/SFR-018_faq/faq/logging_utils.py",
    }
    found: dict = {}
    for label, path in units.items():
        if not path.exists():
            rep.add("FAIL", "로깅 사본", label, f"파일 없음: {path.name}")
            return
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found[label] = {
            n.name for n in tree.body
            if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
        }

    everywhere = set.intersection(*found.values())
    anywhere = set.union(*found.values())
    missing = {
        label: sorted(anywhere - names) for label, names in found.items() if anywhere - names
    }
    rep.add(
        "FAIL" if missing else "OK", "로깅 사본", "함수 묶음 일치",
        "; ".join(f"{label}: {', '.join(names)} 없음" for label, names in missing.items())
        + " — 같은 사건을 단위마다 다른 레벨로 남기게 된다" if missing
        else f"네 단위가 같은 {len(everywhere)}개: {', '.join(sorted(everywhere))}",
    )


def check_workflow_step_copies(rep: Report) -> None:
    """스텝 9개가 **같은 헬퍼를 같은 코드로** 들고 있는지 본다 (2026-08-14 추가).

    스텝은 자기완결이라 로깅·오류표·게이트웨이 클라이언트가 **파일마다 반복된다.**
    그 중복은 의도한 것이지만(`check_workflow_steps` 가 공용 모듈화를 막는다),
    **사본이 갈리는 것까지 의도한 것은 아니다.** 그리고 지금까지 갈렸는지 보는 점검이
    하나도 없었다 — `check_workflow_steps` 는 "무엇을 import 하는가" 만 봤다.

    실제로 갈려 있었다: `_post_serving` 이 **세 가지 모양**이었다. 다섯 스텝은 전송·재시도를
    `_post_json` 으로 빼 뒀는데 나머지 넷은 같은 로직을 `_post_serving` 안에 인라인으로
    복제하고 있었다. 그 안에는 **재시도 가능 여부 판정(`_upstream_kind`)** 이 들어 있다 —
    2026-08-14 에 아홉 스텝을 한꺼번에 고쳐야 했던 바로 그 로직이고, 모양이 둘이면
    다음 사람이 한쪽만 고친다.

    독스트링은 비교하지 않는다. 같은 함수라도 그 스텝에서 왜 쓰는지는 다를 수 있고,
    문구까지 맞추라고 하면 주석을 지우는 쪽으로 도망가게 된다.
    """
    root = ONPREM / "workflow"
    files = sorted(root.glob("*.py"))
    if not files:
        return

    bodies: dict = {}
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue          # 구문 오류는 check_workflow_steps 가 이미 잡는다
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name == "run":
                continue      # 스텝의 본체 — 같을 이유가 없다
            body = list(node.body)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body = body[1:]
            code = ast.unparse(ast.Module(body=body, type_ignores=[]))
            bodies.setdefault(node.name, {})[path.stem] = code

    shared = {name: per for name, per in bodies.items() if len(per) >= 2}
    drifted = []
    for name, per in sorted(shared.items()):
        variants: dict = {}
        for stem, code in per.items():
            variants.setdefault(code, []).append(stem)
        if len(variants) > 1:
            groups = sorted(variants.values(), key=len, reverse=True)
            minority = ", ".join(sorted(s for g in groups[1:] for s in g))
            drifted.append(f"{name}({len(per)}벌 → {len(variants)}가지, 소수파: {minority})")

    rep.add(
        "FAIL" if drifted else "OK", "워크플로우 스텝", "사본 일치",
        "; ".join(drifted) + " — 사본이 갈리면 한쪽만 고쳐진다" if drifted
        else f"공유 헬퍼 {len(shared)}종이 스텝마다 같은 코드다",
    )


def check_mcp_files(rep: Report) -> None:
    """`onprem/mcp/*.py` 가 GenOS MCP 등록 계약을 지키는지 본다.

    **MCP 는 서빙이 아니라 파일이다.** GenOS 는 소스 파일 **한 개**를 받아 실행하고
    `mcp` 객체를 런타임이 전역으로 주입한다. 그래서 여기에는 FastAPI 앱도 `/health` 도
    `$PORT` 도 없고, 그런 게 있다면 그건 이 계약을 오해한 코드다
    (2026-08-11 이전에 실제로 그렇게 만들어 뒀다가 전부 갈아엎었다).

    보는 것:

    1. **`@mcp.tool()` 이 하나 이상.** 없으면 등록해도 도구가 안 생긴다.
    2. **`mcp` 미정의 대비 shim.** 런타임이 주입하지만, 없을 때 `NameError` 로 죽으면
       로컬에서 파일을 열어 볼 수조차 없다. 점검도 이 경로로 도구를 걷어간다.
    3. **도구는 `async def` 이고 `-> str`.** MCP 도구는 JSON **문자열**을 돌려주는
       계약이다. dict 를 돌려주면 런타임이 알아서 감싸 주지 않는다.
    4. **상대 import 금지.** 파일 하나가 전부라 `from .x import y` 는 있을 수 없다.
    5. **최상위 심볼에 파일별 접두어.** 한 서버에 여러 도구 파일이 함께 로드될 수 있고,
       겹치면 나중 것이 앞엣것을 덮는다 — 그 실패는 "도구가 이상한 값을 낸다" 로만
       드러난다. 도구 함수 이름만 예외다(LLM 에 노출되는 계약이라 접두어를 못 붙인다).
    6. **비표준 패키지는 부팅 설치 절차를 지나야 한다.** MCP 기본 이미지에 무엇이 있는지
       보장이 없으므로, `lxml` 같은 것을 그냥 import 하면 등록 시점에 죽는다.

    7. **`print()` 금지** (2026-08-14 추가 — 그전에는 일부러 열어 뒀다). 이유가 바뀌었다:
       MCP 는 **stdout 이 전송 채널이 될 수 있고**(stdio 방식) 그러면 로그 한 줄이
       프로토콜을 깨뜨린다 — `eval/` 이 stderr 전용 로깅을 쓰는 이유와 같고, §C 도
       print 를 금지한다. "로깅 설정이 없다" 는 옛 근거는 각 파일이 자기 **stderr
       핸들러**를 붙이면서 없어졌다(`_XXsetup_logging`). 그 설정이 없으면 `logger.info`
       가 **아무 데도 안 나오므로**(기본 최후 핸들러가 WARNING 부터다) 그냥 logger 로
       바꾸기만 하는 것은 print 보다 나쁘다 — 그래서 둘을 함께 본다.
    """
    root = ONPREM / "mcp"
    if not root.exists():
        rep.add("FAIL", "MCP 도구", "존재", "디렉토리 없음: mcp")
        return

    files = sorted(p for p in root.glob("*.py") if not p.name.startswith("_"))
    if not files:
        rep.add("FAIL", "MCP 도구", "존재", "mcp/ 에 도구 파일이 없다")
        return

    stdlib = set(getattr(sys, "stdlib_module_names", ()))

    for path in files:
        label = f"MCP {path.stem.replace('genon_', '')}"
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except SyntaxError as exc:
            rep.add("FAIL", label, "구문", f"{path.name}: {type(exc).__name__}")
            continue

        # 1·3. 도구 정의
        tools = []
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(target, ast.Attribute) and target.attr == "tool":
                    tools.append(node)
                    break
        if tools:
            rep.add("OK", label, "도구 정의", f"{len(tools)}개: "
                    + ", ".join(t.name for t in tools))
        else:
            rep.add("FAIL", label, "도구 정의", "@mcp.tool() 이 하나도 없다")

        bad_sig = [
            t.name for t in tools
            if not isinstance(t, ast.AsyncFunctionDef)
            or not (isinstance(t.returns, ast.Name) and t.returns.id == "str")
        ]
        rep.add(
            "FAIL" if bad_sig else "OK", label, "도구 시그니처",
            f"{', '.join(bad_sig)} — `async def … -> str` 이어야 한다 (JSON 문자열 반환)"
            if bad_sig else "전부 async + JSON 문자열 반환",
        )

        # 7. print 금지 + stderr 로깅 준비 (둘은 한 쌍이다 — 위 docstring 참고)
        prints = [
            n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"
        ]
        rep.add(
            "FAIL" if prints else "OK", label, "print 금지",
            f"{len(prints)}건 (줄 {', '.join(map(str, prints[:5]))}) — stdout 이 전송 채널이면 "
            "프로토콜이 깨진다" if prints else "stdout 에 직접 쓰지 않는다",
        )
        has_stderr_log = "StreamHandler(sys.stderr)" in source
        rep.add(
            "OK" if has_stderr_log else "FAIL", label, "stderr 로깅",
            "자기 stderr 핸들러를 붙인다" if has_stderr_log
            else "핸들러가 없으면 `logger.info` 가 아무 데도 안 나온다 (기본 최후 핸들러는 WARNING 부터)",
        )

        # 2. shim
        has_shim = "except NameError" in source and "mcp = " in source
        rep.add(
            "OK" if has_shim else "FAIL", label, "mcp shim",
            "런타임 미주입 시 최소 shim 사용" if has_shim
            else "`try: mcp / except NameError:` shim 이 없다 — 로컬에서 열 수 없다",
        )

        # 4·6. import
        relative = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level]
        rep.add(
            "FAIL" if relative else "OK", label, "상대 import",
            f"{len(relative)}건 — 파일 하나가 등록 단위라 형제 모듈이 없다" if relative
            else "없음 (파일 자기완결)",
        )

        third_party = set()
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                names = [node.module.split(".")[0]]
            for top in names:
                if top not in stdlib:
                    third_party.add(top)
        if not third_party:
            rep.add("OK", label, "외부 패키지", "stdlib 만 쓴다")
        elif "pip" in source and "install" in source:
            rep.add("OK", label, "외부 패키지",
                    f"{', '.join(sorted(third_party))} — 부팅 설치 절차 있음")
        else:
            rep.add("FAIL", label, "외부 패키지",
                    f"{', '.join(sorted(third_party))} — 설치 절차 없이 import 하면 등록 시 죽는다")

        # 5. 접두어
        prefix = MCP_PREFIXES.get(path.stem)
        if prefix is None:
            rep.add("WARN", label, "접두어", "이 파일의 접두어가 등록돼 있지 않다")
        else:
            tool_names = {t.name for t in tools}
            bare = []
            for node in tree.body:
                names = []
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names = [node.name]
                elif isinstance(node, ast.Assign):
                    names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    names = [node.target.id]
                for name in names:
                    if name in tool_names or name.startswith("__") or name == "mcp":
                        continue
                    if name.lstrip("_")[:2].upper() != prefix:
                        bare.append(name)
            rep.add(
                "FAIL" if bare else "OK", label, "심볼 접두어",
                f"{', '.join(sorted(bare)[:6])} — `{prefix}` 접두어가 없다 "
                "(다른 도구 파일과 같은 서버에 로드되면 덮인다)" if bare
                else f"도구 함수 외 전부 `{prefix}` 접두어",
            )


def check_no_tests_in_units(rep: Report) -> None:
    """onprem 규칙 — 배포 단위 안에는 tests/ 와 mock 경로를 두지 않는다.

    이 점검 폴더(onprem/test)는 배포 단위 **바깥**이라 대상이 아니다.
    """
    for unit in UNITS:
        offenders = [
            str(p.relative_to(ONPREM))
            for p in unit.path.rglob("*")
            if p.is_dir() and p.name in {"tests", "test"}
        ]
        if offenders:
            rep.add("FAIL", unit.name, "tests 미보유", "; ".join(offenders))
        else:
            rep.add("OK", unit.name, "tests 미보유", "배포 단위 안에 tests/ 없음")


def main() -> int:
    rep = Report()
    for unit in UNITS:
        if not unit.path.exists():
            rep.add("FAIL", unit.name, "존재", f"디렉토리 없음: {unit.root}")
            continue
        check_requirements(unit, rep)
        check_workflow_deps(unit, rep)
        check_health_route(unit, rep)
        check_entrypoint(unit, rep)
        check_reserved_env(unit, rep)
        check_no_print(unit, rep)
    check_workflow_steps(rep)
    check_workflow_step_copies(rep)
    check_logging_copies(rep)
    check_mcp_files(rep)
    check_no_tests_in_units(rep)

    width = max(len(f.unit) for f in rep.findings)
    for level in ("FAIL", "WARN", "OK"):
        for f in rep.findings:
            if f.level == level:
                print(f"[{f.level:4}] {f.unit:<{width}}  {f.check:<12} {f.detail}")

    counts = {lv: sum(1 for f in rep.findings if f.level == lv) for lv in ("FAIL", "WARN", "OK")}
    print(f"\nFAIL {counts['FAIL']} / WARN {counts['WARN']} / OK {counts['OK']}")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
