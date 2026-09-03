"""`submit/` 을 다시 만든다 — 폐쇄망으로 **메일로 보낼** 꾸러미.

    python make_submit.py

**저장소 배치를 그대로 옮긴다.** 그래야 받은 쪽에서 `python onprem/test/check_*.py` 가
경로 손질 없이 그대로 돈다 — 옮겨 놓고 점검을 못 돌리면 무엇이 빠졌는지 알 방법이 없다.

빼는 것: `__pycache__`·`.pyc`, `genos-project/`(봉인된 참조 번들), `archive/`, `venv/`,
`.git/`, 그리고 이 스크립트 자신.
"""

from __future__ import annotations

import os
import shutil
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_OUT = os.path.join(_ROOT, "submit")

# (원본 경로, 설명) — 순서가 곧 `submit/README.md` 의 설명 순서다.
_TREE = [
    "onprem/mcp",
    "onprem/workflow",
    "onprem/codeserving",
    "onprem/prompt",
    "onprem/preprocessor",
    "onprem/eval",
    "onprem/test",
    "onprem/docs",
    "SFR-006/tests",
    "SFR-018/tests",
    "data",
]
_FILES = [
    "onprem/README.md",
    "onprem/HANDOFF.md",
    "onprem/WORK.MD",
    "onprem/ARCHITECTURE_SPLIT.md",
    "SFR-006/README.md",
    "SFR-018/README.md",
    "CLAUDE.md",
    "최종설계서.md",
]

_SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"}
_SKIP_SUFFIX = (".pyc", ".pyo")


def _ignore(_dir, names):
    return [
        name
        for name in names
        if name in _SKIP_DIRS or name.endswith(_SKIP_SUFFIX)
    ]


def main() -> int:
    if os.path.isdir(_OUT):
        # README.md 는 손으로 쓴 것이라 지우지 않는다 — 다시 만드는 것은 코드뿐이다.
        # 손으로 쓴 문서는 지우지 않는다 — 다시 만드는 것은 코드뿐이다.
        kept = {}
        for name in ("README.md", "IO_FORMAT.md"):
            path = os.path.join(_OUT, name)
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    kept[name] = fh.read()
        shutil.rmtree(_OUT)
        os.makedirs(_OUT, exist_ok=True)
        for name, body in kept.items():
            with open(os.path.join(_OUT, name), "wb") as fh:
                fh.write(body)
    else:
        os.makedirs(_OUT, exist_ok=True)

    files = 0
    for rel in _TREE:
        src = os.path.join(_ROOT, rel)
        if not os.path.isdir(src):
            print(f"[submit] 없음(건너뜀): {rel}")
            continue
        dst = os.path.join(_OUT, rel)
        shutil.copytree(src, dst, ignore=_ignore, dirs_exist_ok=True)
        files += sum(len(f) for _, _, f in os.walk(dst))

    for rel in _FILES:
        src = os.path.join(_ROOT, rel)
        if not os.path.isfile(src):
            print(f"[submit] 없음(건너뜀): {rel}")
            continue
        dst = os.path.join(_OUT, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        files += 1

    total = 0
    lines = 0
    for base, dirs, names in os.walk(_OUT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in names:
            total += 1
            if name.endswith((".py", ".j2", ".md", ".txt")):
                path = os.path.join(base, name)
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        lines += sum(1 for _ in fh)
                except OSError:
                    pass
    print(f"[submit] {_OUT}")
    print(f"[submit] 파일 {total:,}개 / 텍스트 {lines:,}줄")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
