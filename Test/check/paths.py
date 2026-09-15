"""점검 스크립트가 **`final/` 어디를 보는가** — 경로를 아는 유일한 자리.

## 왜 한 곳인가

2026-08-11 재배치로 배포 단위가 한 겹 내려갔을 때 `SFR-006/smoke/fixture.py` 가 옛
경로를 들고 있어 **스모크 6개가 전부 죽어 있었다** — 그것도 오류가 아니라
`ModuleNotFoundError` 로 조용히. 경로를 파일마다 적으면 다음 이동 때 같은 일이 반복된다.
2026-09-15 에 `onprem/` 을 `final/` 로 합칠 때 실제로 열다섯 파일을 고쳐야 했고,
그래서 이번에는 **여기 한 곳만** 고치면 되게 바꿨다.

## `final/` 배치는 `onprem/` 과 다르다

| 그전 (`onprem/`) | 지금 (`final/`) |
|---|---|
| `codeserving/SFR-006_template_fill/` | `SFR-006/request/` |
| `prompt/SFR-006_template_fill/` | `SFR-006/prompt/SFR-006_template_fill/` |
| `mcp/` · `workflow/` · `preprocessor/` | 같다 |
| `eval/` | `Test/eval/` (등록 대상이 아니라 채점 도구다) |

**프롬프트가 기능 폴더 안으로 들어간 것이 요점이다.** 로더가 배포 단위에서 위로
올라가며 `prompt/<배포단위이름>` 을 찾으므로, `final/SFR-006/request/` 에서 한 겹 올라간
`final/SFR-006/prompt/SFR-006_template_fill/` 이 그대로 걸린다 — 배치가 달라도 **같은
코드가 같은 자리를 찾는다.**
"""

from __future__ import annotations

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
TEST_ROOT = os.path.dirname(_HERE)
ROOT = os.path.dirname(TEST_ROOT)

FINAL = os.path.join(ROOT, "final")
MCP_DIR = os.path.join(FINAL, "mcp")
WORKFLOW_DIR = os.path.join(FINAL, "workflow")
PREPROC_DIR = os.path.join(FINAL, "preprocessor")
EVAL_DIR = os.path.join(TEST_ROOT, "eval")
ARCHIVE = os.path.join(ROOT, "archive")
# 실물 hwpx 5벌·벤더 참조 사본은 **코드가 아니라 점검 입력**이라 2026-09-15 정리에서
# `archive/` 로 갔다. 여기 한 줄로 두는 이유가 그거다 — 점검마다 경로를 들면
# 옮길 때 한둘이 빠지고, 그 상태는 **FAIL 이 아니라 건수가 조용히 줄어드는**
# 모양으로만 드러난다(`check_final_preprocessor` 가 있는 것만 태우기 때문).
DATA_DIR = os.path.join(ARCHIVE, "data")
GENOS_FILES = os.path.join(ARCHIVE, "genos_files")

# 배포 단위 이름 → `final/` 폴더 이름. **배포 단위 이름이 키다** — 그 이름이 등록
# 화면·프롬프트 디렉토리·로그에 다 쓰이는 정본이고, 폴더 이름은 읽기 편하라고 줄인 것뿐이다.
FOLDER = {
    "SFR-006_template_fill": "SFR-006",
    "SFR-018_text_polish": "SFR-018-polish",
    "SFR-018_translation": "SFR-018-translate",
    "SFR-018_faq": "SFR-018-faq",
}

UNITS = tuple(FOLDER)


def unit_dir(unit: str, *rest: str) -> str:
    """배포 단위 루트 (`final/<폴더>/request`). 뒤에 상대 경로를 이어 붙일 수 있다."""
    return os.path.join(FINAL, FOLDER[unit], "request", *rest)


def open_ai_dir(unit: str, *rest: str) -> str:
    """SDK 판에서 **갈리는 파일만** 있는 자리 (`final/<폴더>/open_ai`)."""
    return os.path.join(FINAL, FOLDER[unit], "open_ai", *rest)


def prompt_dir(unit: str, *rest: str) -> str:
    """그 단위의 프롬프트 디렉토리 (`final/<폴더>/prompt/<배포단위이름>`)."""
    return os.path.join(FINAL, FOLDER[unit], "prompt", unit, *rest)
