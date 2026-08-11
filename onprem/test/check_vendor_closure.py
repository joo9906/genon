"""벤더 사본 폐포 점검 — `_vendor/` 가 stdlib + lxml 로 닫히는가.

`python onprem/test/check_vendor_closure.py`

## 왜 필요한가

`template_fill/_vendor/hwpx` 는 상류 python-hwpx 의 **일부**다. 상류 패키지에는 문서 모델
40k 줄이 더 있고, 우리는 `__init__.py` 를 빈 스텁으로 갈아 끼워 그 아래를 끊어 뒀다.
이 절연은 **눈에 보이지 않는다** — 재동기화 때 파일 하나를 상류 것으로 덮어쓰면
`from ..oxml.body import ...` 같은 줄이 딸려 들어오고, 그 순간 배포 단위가 없는 모듈을
import 하다 **기동 시점에** 죽는다. 그때는 이미 폐쇄망이다.

여기서 보는 것 셋:

1. 벤더 트리 안 모든 import 가 **stdlib · lxml · 벤더 트리 내부**로만 향한다.
2. 잘라낸 상류 심볼(`validate_editor_open_safety` 등)을 아무도 다시 참조하지 않는다.
3. 배포 단위 코드가 **`hwpx` 를 직접 import 하지 않는다** — pip 의존을 되살리는 실수 방지.

## 왜 import 시도로 때우지 않는가

`import template_fill.overflow` 가 성공한다고 폐포가 닫힌 것은 아니다. 함수 안에 숨은
지연 import(상류가 실제로 그렇게 쓴다 — `validate_editor_open_safety` 가 그 예다)는
호출 전까지 조용하다. 그래서 **소스를 읽어** 판정한다.
"""

import ast
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UNIT = os.path.join(_ROOT, "codeserving", "SFR-006_template_fill")  # 2026-08-11 재배치
_PACKAGE = os.path.join(_UNIT, "template_fill")
_VENDOR = os.path.join(_PACKAGE, "_vendor")

# 벤더 트리가 기대도 되는 외부 최상위 모듈. lxml 은 이 배포 단위가 이미 쓰고 있고
# (`hwpx_fields`·`hwpx_style`), 워크플로우 pod 기본 이미지에도 들어 있다.
_ALLOWED_THIRD_PARTY = {"lxml"}

# 상류에서 잘라낸 심볼 — 되살아나면 `HwpxDocument` 가 딸려 온다 (`_vendor/README.md`).
_REMOVED_SYMBOLS = ("validate_editor_open_safety", "EditorOpenSafetyReport")

_STDLIB = set(getattr(sys, "stdlib_module_names", ()))


class Report:
    def __init__(self) -> None:
        self.failures: list = []
        self.checks = 0

    def expect(self, condition: bool, label: str, detail: str = "") -> None:
        self.checks += 1
        if condition:
            print(f"[OK  ] {label}")
            return
        self.failures.append(label)
        print(f"[FAIL] {label}  {detail}")


def _python_files(root: str):
    for base, _dirs, files in os.walk(root):
        if "__pycache__" in base:
            continue
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(base, name)


def _parse(path: str, broken: list):
    """소스를 AST 로 읽는다. 못 읽으면 `broken` 에 남기고 None — 트레이스백으로 죽지 않는다.

    벤더 사본이 파싱조차 안 되는 것도 결함이므로 조용히 넘기지는 않는다.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            return ast.parse(handle.read(), filename=path)
    except (SyntaxError, UnicodeDecodeError) as exc:
        broken.append(f"{os.path.relpath(path, _PACKAGE)} ({type(exc).__name__})")
        return None


def _imported_roots(tree: ast.AST):
    """이 모듈이 참조하는 **최상위 외부 모듈** 이름들 (상대 import 는 내부이므로 제외)."""
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # `from .x import` / `from ..x import` — 벤더 트리 내부
                continue
            if node.module:
                roots.add(node.module.split(".", 1)[0])
    return roots


def main() -> int:
    rep = Report()

    rep.expect(os.path.isdir(_VENDOR), "벤더 트리가 있다", _VENDOR)
    if not os.path.isdir(_VENDOR):
        return 1

    # 1) 폐포 — 벤더 트리의 외부 의존
    broken: list = []
    outside: dict = {}
    self_absolute: list = []
    for path in _python_files(_VENDOR):
        tree = _parse(path, broken)
        if tree is None:
            continue
        relative = os.path.relpath(path, _PACKAGE)
        roots = _imported_roots(tree)
        # 상류 자기 자신을 절대 경로로 부르는 줄도 폐포를 뚫는다
        # (`from hwpx.document import …` — 설치된 pip 패키지를 집어 온다).
        if "hwpx" in roots:
            self_absolute.append(relative)
        for root in roots:
            if root in _STDLIB or root in _ALLOWED_THIRD_PARTY:
                continue
            outside.setdefault(root, []).append(relative)

    rep.expect(not broken, "벤더 트리의 모든 파일이 파싱된다", f"파싱 실패={broken}")
    rep.expect(
        not outside,
        "벤더 트리의 import 가 stdlib + lxml 로 닫힌다",
        f"외부 참조={outside}",
    )
    rep.expect(
        not self_absolute,
        "벤더 트리가 자기 자신을 절대 import 하지 않는다 (상대 import 만)",
        f"파일={self_absolute}",
    )

    # 2) 잘라낸 심볼이 되살아나지 않았는가
    revived: dict = {}
    for path in _python_files(_VENDOR):
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        for symbol in _REMOVED_SYMBOLS:
            # 주석·docstring 의 설명(README 가 이유를 적어 둔다)은 정의가 아니다 —
            # `def`/`class` 선언으로만 판정한다.
            if f"def {symbol}" in source or f"class {symbol}" in source:
                revived.setdefault(symbol, []).append(os.path.relpath(path, _PACKAGE))
    rep.expect(
        not revived,
        "잘라낸 상류 심볼이 다시 들어오지 않았다",
        f"되살아남={revived}",
    )

    # 3) 배포 단위가 pip 패키지 `hwpx` 를 직접 부르지 않는가
    direct: list = []
    for path in _python_files(_PACKAGE):
        if path.startswith(_VENDOR):
            continue
        tree = _parse(path, broken)
        if tree is not None and "hwpx" in _imported_roots(tree):
            direct.append(os.path.relpath(path, _PACKAGE))
    rep.expect(
        not direct,
        "배포 단위 코드가 pip 패키지 `hwpx` 를 import 하지 않는다",
        f"파일={direct}",
    )

    # 4) requirements 에 python-hwpx 가 남아 있지 않은가 (벤더 사본과 이중 설치 방지)
    requirements = os.path.join(_UNIT, "requirements.txt")
    with open(requirements, encoding="utf-8") as handle:
        declared = [
            line.strip()
            for line in handle
            if line.strip() and not line.strip().startswith("#")
        ]
    rep.expect(
        not any("hwpx" in line for line in declared),
        "requirements.txt 에 python-hwpx 선언이 없다 (벤더 사본이 대신한다)",
        f"선언={[l for l in declared if 'hwpx' in l]}",
    )

    print()
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
