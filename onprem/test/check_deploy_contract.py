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
}

# fastapi 의 Form/File/UploadFile 을 쓰면 import 없이도 이 패키지가 필요하다.
MULTIPART_MARKERS = ("UploadFile", "File(", "Form(")


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


UNITS = [
    Unit(
        name="SFR-006 템플릿 채우기",
        area="03",
        root="SFR-006_template_fill",
        entry="template_fill/main.py",
        workflow_entry="template_fill/run_chat.py",
    ),
    Unit(
        name="SFR-018 번역",
        area="03",
        root="SFR-018_translation",
        entry="main.py",
    ),
    Unit(
        # 워크플로우 단계는 pod 기본 이미지의 패키지만 쓴다 (가이드 11.5.6).
        # requirements.txt 는 설치 입력이 아니므로 요구하지 않는다.
        name="SFR-018 글다듬이",
        area="02",
        root="SFR-018_text_polish",
        workflow_entry="text_polish/main.py",
        needs_requirements=False,
    ),
    Unit(
        name="평가지표 MCP",
        area="mcp",
        root="eval",
    ),
]


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


def _third_party_imports(root: Path) -> dict[str, set[str]]:
    """{import 최상위 이름: 그 이름을 쓰는 파일 경로 집합}"""
    local = _local_names(root)
    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    found: dict[str, set[str]] = {}

    for path in _py_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # 구문 오류 자체가 결함이다
            found.setdefault("<syntax-error>", set()).add(f"{path}: {exc}")
            continue

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
                found.setdefault(top, set()).add(str(path.relative_to(ONPREM)))
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

    missing = []
    for name in sorted(imports):
        if name == "<syntax-error>":
            rep.add("FAIL", unit.name, "구문", "; ".join(sorted(imports[name])))
            continue
        dist = DIST_BY_IMPORT.get(name, name).lower()
        if dist not in declared:
            users = ", ".join(sorted(imports[name])[:3])
            missing.append(f"{dist} (import {name} — {users})")

    # fastapi 의 multipart 폼은 import 없이 python-multipart 를 요구한다
    if _uses_multipart(unit.path) and "python-multipart" not in declared:
        missing.append("python-multipart (UploadFile/File/Form 사용 — 없으면 해당 경로만 런타임 실패)")

    if missing:
        rep.add("FAIL", unit.name, "requirements", "선언 누락: " + "; ".join(missing))
    else:
        rep.add("OK", unit.name, "requirements", f"{len(declared)}개 선언, import 전부 덮음")


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
    """가이드 6.4·11.5.3 — 코드 서빙은 GET /health 가 200 을 줘야 한다."""
    if unit.area != "03":
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
    if unit.area != "03":
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
