"""점검 스크립트가 **`final/` 어디를 보는가** — 경로를 아는 유일한 자리.

## 왜 한 곳인가

경로를 파일마다 적으면 폴더를 옮길 때 몇 파일이 옛 경로를 들고 남는다. 그 점검은
오류가 아니라 `ModuleNotFoundError` 로 조용히 죽거나, 실물을 못 찾아 건수만 준다.
그래서 **여기 한 곳만** 고치면 되게 한다.

## `final/` 배치

| 무엇 | 자리 |
|---|---|
| 코드서빙 단위 | `final/<기능>/request/` (예: `final/SFR-006/request/`) |
| 프롬프트 | `final/<기능>/prompt/<배포단위이름>/` |
| MCP · 워크플로우 · 전처리기 | `final/mcp/` · `final/workflow/` · `final/preprocessor/` |
| 평가지표 | `Test/eval/` (등록 대상이 아니라 채점 도구다) |

**프롬프트가 기능 폴더 안에 있는 것이 요점이다.** 로더가 배포 단위에서 위로
올라가며 `prompt/<배포단위이름>` 을 찾으므로, `final/SFR-006/request/` 에서 한 겹 올라간
`final/SFR-006/prompt/SFR-006_template_fill/` 이 그대로 걸린다 — 코드가 자기 위치에서
**같은 규칙으로 프롬프트 자리를 찾는다.**
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
# 실물 hwpx 5벌·벤더 참조 사본은 **코드가 아니라 점검 입력**이라
# `archive/` 에 있다. 여기 한 줄로 두는 이유가 그거다 — 점검마다 경로를 들면
# 옮길 때 한둘이 빠지고, 그 상태는 **FAIL 이 아니라 건수가 조용히 줄어드는**
# 모양으로만 드러난다(`check_final_preprocessor` 가 있는 것만 태우기 때문).
DATA_DIR = os.path.join(ARCHIVE, "data")
GENOS_FILES = os.path.join(ARCHIVE, "genos_files")
# pdf 실물(`check_high_preprocessor` 가 있는 것만 태운다).
PDF_SAMPLES_DIR = os.path.join(TEST_ROOT, "data", "preprocessor")

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


def prompt_dir(unit: str, *rest: str) -> str:
    """그 단위의 프롬프트 디렉토리 (`final/<폴더>/prompt/<배포단위이름>`)."""
    return os.path.join(FINAL, FOLDER[unit], "prompt", unit, *rest)
