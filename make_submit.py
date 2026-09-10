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
    # `not/` — **지금 실제로 올릴 판본**(lxml 없음). 네 단위 전부와 프롬프트가 다 있어야
    # 한다. 하나라도 빠지면 받은 쪽에서 그 단위만 정본(lxml 판본)으로 올리게 된다.
    "not/SFR-006_template_fill",
    "not/SFR-018_text_polish",
    "not/SFR-018_translation",
    "not/SFR-018_faq",
    "not/prompt",
    "not/mcp",
    "not/preprocessor",
    "not/workflow",
    # `onprem/` — 정본. mirror 에 lxml 이 들어오면 이쪽으로 돌아간다.
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
    # GenOS 벤더 참조 사본 **둘만** 넣는다. `check_smart_preprocessor` 가
    # `intelligence_processor.py` 에서 다시 계산해 합치기를 대조하고(없으면 그 판정이
    # SKIP 으로 빠진다), `attach_processor.py` 는 `final_preprocessor.py` PART 1 을
    # 손볼 때 눈으로 대조하는 원본이다. **`genos_files/` 를 통째로 넣지 않는 이유**는
    # 개발가이드 PDF·요구사항 xlsx 가 6.5MB 라 메일 꾸러미가 그것만으로 무거워진다.
    "genos_files/intelligence_processor.py",
    "genos_files/attach_processor.py",
    "onprem/ONPREM.md",
    # 받은 쪽이 점검을 돌리려면 무엇을 설치해야 하는지가 있어야 한다 —
    # 여덟 단위 목록의 합집합 + eval·전처리기·점검 스크립트까지 모은 개발용 목록이다.
    "requirements.txt",
    "onprem/README.md",
    "SFR-006/README.md",
    "SFR-018/README.md",
    "not/README.md",
    "not/PROGRESS.md",
    "not/minio.py",
    "not/check_not_units.py",
    "CLAUDE.md",
    "최종정리.md",
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
        # 손으로 쓴 문서(`submit/README.md`·`IO_FORMAT.md`)는 지우지 않는다 —
        # 다시 만드는 것은 저장소에서 복사해 오는 것뿐이다.
        #
        # **`_FILES` 에 루트 `README.md` 를 넣지 말 것** (2026-09-08 에 한 번 그렇게 해서
        # 366줄짜리 꾸러미 안내서를 덮었다). 여기서 살려 놔도 `_FILES` 복사가 그 위에
        # 덮어쓴다 — 살리는 것과 덮는 것이 같은 함수 안에 있어 눈에 안 띈다.
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

    # **빠진 것을 건너뛰고 0 으로 끝내지 않는다** (2026-09-08). 그전에는 없는 경로를
    # `없음(건너뜀)` 한 줄로 넘기고 성공으로 끝냈다 — 그래서 `_TREE` 의 쉼표 하나가
    # 빠져 `"not/SFR-018_faq" "onprem/mcp"` 가 **한 문자열로 붙었을 때**, MCP 디렉토리가
    # 꾸러미에서 통째로 빠진 채로 "완성" 되었다. 메일로 보내고 나서야 드러난다.
    missing: list = []

    files = 0
    for rel in _TREE:
        src = os.path.join(_ROOT, rel)
        if not os.path.isdir(src):
            print(f"[submit] 없음(건너뜀): {rel}")
            missing.append(rel)
            continue
        dst = os.path.join(_OUT, rel)
        shutil.copytree(src, dst, ignore=_ignore, dirs_exist_ok=True)
        files += sum(len(f) for _, _, f in os.walk(dst))

    for rel in _FILES:
        src = os.path.join(_ROOT, rel)
        if not os.path.isfile(src):
            print(f"[submit] 없음(건너뜀): {rel}")
            missing.append(rel)
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
    if missing:
        print(f"[submit] **{len(missing)}개가 빠졌다** — 이 꾸러미를 보내지 말 것:")
        for rel in missing:
            print(f"[submit]   - {rel}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
