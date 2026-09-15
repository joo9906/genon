"""`final/` 을 다시 만든다 — **기능별로 갈라 놓은 읽기용 배치.**

    python make_final.py

## 왜 있나

실제로 도는 코드는 `onprem/`(정본, `httpx`)과 `not/`(반입 판본, `openai` SDK) 둘인데,
그 둘이 저장소 **다른 자리**에 통째로 놓여 있어 "이 기능의 코드가 어디 있나" 와
"두 판본이 뭐가 다른가" 가 한눈에 안 보였다. `final/` 은 그 둘을 **기능별로 모아**
놓는다:

    final/<기능>/request/   ← 정본(`httpx`) **전체 트리**. 그대로 등록할 수 있다
    final/<기능>/open_ai/   ← `openai` SDK 판에서 **갈리는 파일만**
    final/<기능>/prompt/<배포단위이름>/
                            ← 그 기능의 프롬프트 (배포 단위 **밖**에 넣는다).
                              **하위 디렉토리 이름이 계약이다** — 로더가 상위로
                              올라가며 `prompt/<배포단위이름>` 을 찾는다.
    final/workflow/         ← 캔버스 파이썬 스텝 9개 (판본 무관)
    final/mcp/              ← MCP 도구 파일 4개 (판본 무관)

`openai` 로 올릴 때는 `request/` 를 복사한 뒤 그 위에 `open_ai/` 를 **덮어쓴다.**

## 손으로 고치지 않는다

`final/` 은 **파생물이다.** 여기서 고치면 `onprem/`·`not/` 과 갈리고, 그 어긋남은
오류로 드러나지 않는다 — 등록한 코드가 저장소의 어느 판본도 아닌 상태가 된다.
기능을 고칠 때는 `onprem/`(그리고 전송 계층이면 `not/`)을 고치고 이 스크립트를 다시 돈다.

## 이 스크립트가 세우는 계약

두 판본이 갈리는 자리는 **전송 계층 하나뿐**이라야 한다 — 네 단위 × (`llm.py` ·
`config.py` · `requirements.txt`) = 12개. 그 밖이 갈리거나, 한쪽에만 있는 파일이
생기거나, 프롬프트가 갈리면 **여기서 선다.** 그런 상태는 "기능이 한 판본에만
들어갔다" 는 뜻이고, 그대로 `final/` 을 만들면 **어느 쪽으로 등록하느냐에 따라 기능이
사라지는데 오류로는 드러나지 않는다.** (같은 계약을 `not/check_not_units.py` 의
`EXPECTED_DIFF` 가 반대편에서 지킨다 — 둘 다 고쳐야 통과한다.)
"""

from __future__ import annotations

import os
import re
import shutil

_ROOT = os.path.dirname(os.path.abspath(__file__))
_OUT = os.path.join(_ROOT, "final")

# (배포 단위 이름, `final/` 폴더 이름). 폴더 이름은 **사람이 읽는 이름**이라 짧게 두고,
# 원본 경로는 배포 단위 이름 그대로다 — 등록 화면에서 고르는 이름이 그쪽이다.
_UNITS = [
    ("SFR-006_template_fill", "SFR-006"),
    ("SFR-018_text_polish", "SFR-018-polish"),
    ("SFR-018_translation", "SFR-018-translate"),
    ("SFR-018_faq", "SFR-018-faq"),
]

# **갈려도 되는 자리.** 이 12개가 전송 계층이고, 여기 없는 파일이 갈리면 기능이 한쪽에만
# 들어간 것이다 (위 머리말).
_EXPECTED_DIFF = {
    "SFR-006_template_fill": {
        "requirements.txt",
        "template_fill/config.py",
        "template_fill/llm.py",
    },
    "SFR-018_text_polish": {
        "requirements.txt",
        "text_polish/config.py",
        "text_polish/llm.py",
    },
    "SFR-018_translation": {
        "requirements.txt",
        "config.py",
        "translation_pipeline/common/llm.py",
    },
    "SFR-018_faq": {
        "requirements.txt",
        "faq/config.py",
        "faq/llm.py",
    },
}

# **두 판본이 완전히 같아야 하는 등록 단위.** (디렉토리, 파일 수)
#
# 코드 서빙 네 단위와 달리 이쪽은 게이트웨이의 **LLM 경로를 직접 부르지 않는다** —
# 스텝은 서빙·MCP 를 `httpx` 로 부르고(그 외 패키지가 없다), MCP 파일은 표 판정만
# 한다. 그래서 `openai` SDK 든 `httpx` 든 갈릴 자리가 없고, 갈렸다면 한쪽에만 고친
# 것이다. 파일 수까지 못박는 이유는 **하나가 빠져도 나머지가 그대로 복사되기**
# 때문이다 — 그 상태는 "그 스텝만 캔버스에 없는" 형태로만 드러난다.
_SHARED = [
    ("workflow", 9),   # 캔버스 파이썬 스텝. 파일 1개 = 스텝 1개
    ("mcp", 4),        # MCP 도구 파일. 파일 1개 = 등록 1개
]

_SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"}
_SKIP_SUFFIX = (".pyc", ".pyo")


def _tree(base: str) -> dict:
    """`base` 아래 파일 내용 맵 (상대경로 → 바이트)."""
    out = {}
    for cur, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in names:
            if name.endswith(_SKIP_SUFFIX):
                continue
            path = os.path.join(cur, name)
            with open(path, "rb") as fh:
                out[os.path.relpath(path, base).replace("\\", "/")] = fh.read()
    return out


def _write(dst: str, body: bytes) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(body)


def main() -> int:
    problems: list = []

    # 손으로 쓴 안내서는 지우지 않는다 — 다시 만드는 것은 코드를 복사해 오는 것뿐이다.
    # (`make_submit.py` 가 `submit/README.md` 를 살리는 것과 같은 규약이다.)
    kept = {}
    if os.path.isdir(_OUT):
        for name in ("README.md", "verify_final.py"):
            path = os.path.join(_OUT, name)
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    kept[name] = fh.read()
        shutil.rmtree(_OUT)
    os.makedirs(_OUT, exist_ok=True)
    for name, body in kept.items():
        _write(os.path.join(_OUT, name), body)

    files = 0
    for unit, folder in _UNITS:
        base = os.path.join(_ROOT, "onprem", "codeserving", unit)
        mine = os.path.join(_ROOT, "not", unit)
        if not os.path.isdir(base) or not os.path.isdir(mine):
            problems.append(f"{unit}: 원본 디렉토리가 없다")
            continue

        req = _tree(base)          # 정본 = request 판
        sdk = _tree(mine)          # openai SDK 판

        # ── 계약 점검 ───────────────────────────────────────────
        only_req = sorted(set(req) - set(sdk))
        only_sdk = sorted(set(sdk) - set(req))
        actual_diff = {k for k in set(req) & set(sdk) if req[k] != sdk[k]}
        expected = _EXPECTED_DIFF.get(unit, set())
        if only_req:
            problems.append(f"{unit}: 정본에만 있는 파일 {only_req}")
        if only_sdk:
            problems.append(f"{unit}: openai 판에만 있는 파일 {only_sdk}")
        if actual_diff != expected:
            problems.append(
                f"{unit}: 갈리는 자리가 목록과 다르다 — "
                f"목록 밖={sorted(actual_diff - expected)} "
                f"되돌려짐={sorted(expected - actual_diff)}"
            )

        # ── request/ = 정본 전체 ────────────────────────────────
        for rel, body in req.items():
            _write(os.path.join(_OUT, folder, "request", rel), body)
            files += 1

        # ── open_ai/ = 갈리는 파일만 ────────────────────────────
        for rel in sorted(actual_diff):
            _write(os.path.join(_OUT, folder, "open_ai", rel), sdk[rel])
            files += 1

        # ── 덮어쓰면 정말 `not/` 이 되는가 ──────────────────────
        #
        # **이것이 이 배치의 계약이다.** 위 세 판정(한쪽에만 있는 파일 없음 · 갈리는
        # 자리가 목록과 같음)이 다 맞아도, 여기서 **실제로 합쳐 대조**하지 않으면
        # "덮어썼는데 SDK 판이 아닌 무언가가 되는" 상태를 못 잡는다 — 그 상태는 등록해
        # 돌려 보기 전까지 아무 데도 안 드러난다.
        merged = dict(req)
        merged.update({rel: sdk[rel] for rel in actual_diff})
        if merged != sdk:
            problems.append(
                f"{unit}: request/ 에 open_ai/ 를 덮어써도 openai 판이 되지 않는다"
            )

        # ── prompt/ = 그 기능의 프롬프트 (두 판본이 같다) ───────
        prompt_src = os.path.join(_ROOT, "onprem", "prompt", unit)
        if not os.path.isdir(prompt_src):
            problems.append(f"{unit}: 프롬프트 디렉토리가 없다")
            continue
        base_p = _tree(prompt_src)
        mine_p = _tree(os.path.join(_ROOT, "not", "prompt", unit))
        if base_p != mine_p:
            # 프롬프트는 전송 계층을 모르는 값이라 갈릴 이유가 없다. 갈렸다면 한쪽에만
            # 지시문을 고친 것이고, 그 차이는 **결과물의 문체·형식으로만** 드러난다.
            problems.append(f"{unit}: 프롬프트가 두 판본에서 갈린다")
        # **배포 단위 이름의 하위 디렉토리에 넣는다.** 로더는 배포 단위에서 상위로
        # 올라가며 `prompt/<단위이름>` 을 찾으므로(`prompt_loader._search_upward`),
        # 파일을 `prompt/` 바로 밑에 두면 **이름이 안 맞아 못 찾는다.** 그 실패는
        # 기동도 `/health` 도 통과한 뒤 **첫 LLM 호출에서** `PromptRenderError` 로
        # 터진다 — 등록해서 눌러 보기 전까지 아무 데도 안 드러난다.
        # (2026-09-14 에 실제로 그 상태였고, `verify_final` 이 500 으로 잡았다.)
        for rel, body in base_p.items():
            _write(os.path.join(_OUT, folder, "prompt", unit, rel), body)
            files += 1

    # ── 프롬프트가 이 배치에서 **찾아지는가** ───────────────────
    #
    # 파일을 복사해 놓는 것과 **로더가 찾는 것**은 다른 일이다. 로더는 배포 단위에서
    # 상위로 올라가며 `prompt/<배포단위이름>` 을 찾으므로(`_search_upward`), 배치가
    # 바뀌면 같은 코드가 프롬프트를 못 찾는다 — 그 실패는 기동도 `/health` 도 통과한
    # 뒤 **첫 LLM 호출에서** `PromptRenderError` 로 터진다. 2026-09-14 에 실제로 그
    # 상태였고(`prompt/` 바로 밑에 파일을 뒀다) 네 단위가 전부 500 이었다.
    #
    # 값은 **로더 소스에서 읽는다** — 여기에 베껴 두면 로더가 깊이나 이름을 바꿀 때
    # 이 판정만 옛 값을 지킨다.
    for unit, folder in _UNITS:
        req = os.path.join(_OUT, folder, "request")
        loaders = [
            os.path.join(cur, name)
            for cur, dirs, names in os.walk(req)
            for name in names
            if name == "prompt_loader.py" and not any(d in cur for d in _SKIP_DIRS)
        ]
        if not loaders:
            problems.append(f"{unit}: prompt_loader.py 가 없다")
            continue
        with open(loaders[0], encoding="utf-8") as fh:
            loader_src = fh.read()
        dirname = re.search(
            r'_DEFAULT_PROMPT_DIRNAME\s*=\s*os\.path\.join\(\s*"([^"]+)"\s*,\s*"([^"]+)"',
            loader_src,
        )
        depth = re.search(r"_SEARCH_DEPTH\s*=\s*(\d+)", loader_src)
        if not dirname or not depth:
            problems.append(f"{unit}: 로더에서 프롬프트 경로 규약을 읽지 못했다")
            continue
        wanted = os.path.join(*dirname.groups())
        here, found = os.path.dirname(loaders[0]), ""
        for _ in range(int(depth.group(1))):
            if os.path.isdir(os.path.join(here, wanted)):
                found = os.path.join(here, wanted)
                break
            parent = os.path.dirname(here)
            if parent == here:
                break
            here = parent
        if not found:
            problems.append(
                f"{unit}: 로더가 프롬프트를 못 찾는다 — `{wanted}` 를 "
                f"{depth.group(1)}단계 위까지 뒤져도 없다"
            )

    # ── workflow/ · mcp/ = 판본과 무관한 등록 단위 ──────────────
    #
    # 기능별로 가르지 않는다. 스텝 하나가 **여러 기능을 지나는 것이 아니라** 반대로
    # 캔버스에 붙이는 순서가 그 기능의 흐름이라, 아홉 개를 한자리에 놓고 표로 읽는
    # 편이 맞다. MCP 는 한 도구를 여러 기능이 부른다(`text_guard` 는 글다듬이·번역).
    for name, expect in _SHARED:
        src = os.path.join(_ROOT, "onprem", name)
        alt = os.path.join(_ROOT, "not", name)
        if not os.path.isdir(src) or not os.path.isdir(alt):
            problems.append(f"{name}: 원본 디렉토리가 없다")
            continue
        # 등록 단위는 최상위 `.py` 뿐이다 — README 는 설계 문서라 `onprem/` 에 둔다.
        units = {k: v for k, v in _tree(src).items() if k.endswith(".py") and "/" not in k}
        mirror = {k: v for k, v in _tree(alt).items() if k.endswith(".py") and "/" not in k}
        if len(units) != expect:
            problems.append(f"{name}: 파일이 {len(units)}개다 (기대 {expect}개)")
        if units != mirror:
            only = sorted(set(units) ^ set(mirror))
            drift = sorted(k for k in set(units) & set(mirror) if units[k] != mirror[k])
            problems.append(
                f"{name}: 두 판본이 갈린다 — 한쪽에만={only} 내용이 다름={drift}"
            )
        for rel, body in units.items():
            _write(os.path.join(_OUT, name, rel), body)
            files += 1

    print(f"[final] {_OUT}")
    print(f"[final] 파일 {files:,}개 / 기능 {len(_UNITS)}개 + {len(_SHARED)}개 공용")
    if problems:
        # **빠진 것을 건너뛰고 0 으로 끝내지 않는다** (`make_submit.py` 와 같은 규약).
        print(f"[final] **계약 위반 {len(problems)}건** — 이 배치를 쓰지 말 것:")
        for line in problems:
            print(f"[final]   - {line}")
        return 1
    print("[final] 두 판본이 갈리는 자리는 전송 계층 12개뿐이다 (스텝 9·MCP 4 는 동일) — 계약 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
1