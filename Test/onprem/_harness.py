"""폐쇄망 실측 검증 — 네 기능 공통 배선.

`Test/check/*.py` 는 게이트웨이를 대역(mock)으로 갈아 끼워 **로직**이 맞는지만
본다(그물 15개가 그렇게 짜여 있다). 이 디렉토리는 반대다 — **실제 LLM 게이트웨이**
(`GENOS_URL`/`LLM_SERVING_ID`/`GENOS_TOKEN`)를 그대로 두고 `final/<기능>/request/`
를 실제로 띄워, 진짜 응답을 `Test/eval/eval_mcp`(통과율·숫자 유지 등을 내는 채점기)
에 먹인다. 그래서 **여기서 하는 assert 는 없다** — 있는 그대로의 수치를 리포트로
낸다(합불은 리포트를 보고 사람이 판단한다).

**등록 단위가 아니고, `check_*`/`test_*` 그물과도 다르다.** LLM 을 실제로 부르므로
비용이 들고, 게이트웨이가 없는 이 저장소(코드스페이스) 환경에서는 애초에 돌지
않는다 — 폐쇄망에서 `GENOS_URL` 등을 실제 값으로 채운 뒤에만 의미가 있다.

**`request`(httpx) 판본만 태운다.** `open_ai` 오버레이는 프롬프트 디렉토리를
상위 탐색으로 찾는 경로 자체가 달라져(파일이 임시 디렉토리로 복사되면 그 탐색이
깨진다) 여기서 흉내 내면 또 다른 버그를 만들 위험이 크다 — 그 판본을 검증하려면
실제로 그 판본을 등록해서 본다.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# ── 경로 ──────────────────────────────────────────────────────────────────
# `Test/check/paths.py` 와 같은 규약 — 경로를 아는 자리를 하나로 모은다. 여기 말고
# 각 run_*.py 에 경로를 흩어 두면, 저장소를 옮길 때 몇 곳이 조용히 안 따라온다.
ONPREM_DIR = Path(__file__).resolve().parent
REPO_ROOT = ONPREM_DIR.parent.parent
FINAL_DIR = REPO_ROOT / "final"
DATA_DIR = REPO_ROOT / "Test" / "data"
REPORTS_DIR = ONPREM_DIR / "reports"
EVAL_DIR = REPO_ROOT / "Test" / "eval"
PREPROCESSOR_DIR = FINAL_DIR / "preprocessor"

# 기능 이름 → (등록 폴더, 부팅에 필요한 sys.path, import 할 앱 모듈).
# `verify_final.py` 의 FOLDER 분기와 같은 매핑이다 — 두 파일이 갈리면 한쪽만
# 고쳐진 채 굳는다(사본이면 대조라도 되는데 이건 성격이 달라 그냥 맞춰 둔다).
UNIT_SPECS = {
    "template_fill": {"folder": "SFR-006", "app_module": "template_fill.main"},
    "text_polish": {"folder": "SFR-018-polish", "app_module": "main"},
    "translation": {"folder": "SFR-018-translate", "app_module": "main"},
    "faq": {"folder": "SFR-018-faq", "app_module": "faq.main"},
}

GATEWAY_ENV_VARS = ("GENOS_URL", "LLM_SERVING_ID", "GENOS_TOKEN")

# 문서 하나가 여러 LLM 호출(조각 분할·배치)을 거칠 수 있어 기본 타임아웃보다 넉넉히
# 둔다. 각 단위 자신의 `RES_TIMEOUT`(90초)·재시도까지 감안한 값이다.
REQUEST_TIMEOUT = 300.0


def print_gateway_status() -> None:
    """게이트웨이 환경변수가 채워져 있는지 눈으로 보여준다.

    막지는 않는다 — `GENOS_TOKEN` 없이도 받는 배포가 있을 수 있고, 진짜 판정은
    각 단위의 `Config`가 이미 하고 있다(`CONFIG_MISSING` 오류로 응답에 그대로
    나온다). 여기서는 "설정을 깜빡했다" 를 빨리 알아채게 하는 것만 한다.
    """
    for name in GATEWAY_ENV_VARS:
        value = os.environ.get(name, "")
        shown = "설정됨" if value else "미설정"
        print(f"[게이트웨이] {name}: {shown}")


def _import_app(feature: str):
    """`final/<기능>/request/` 를 sys.path 맨 앞에 놓고 실제 앱을 import 한다.

    `sys.path.insert(0, ...)` 이지 `append` 가 아니다 — 이 프로세스 안에서 같은
    이름의 모듈(`main`, `config` 등)을 다른 기능이 이미 import 했을 수 있고, 그때
    `append` 로 두면 파이썬이 **먼저 찾은 옛 모듈**을 그대로 쓴다. 그래서 run_*.py
    는 한 프로세스에서 기능 하나만 부팅한다(여러 기능을 한 스크립트에서 순서대로
    돌리지 않는다) — 두 번째 기능을 부팅하면 첫 번째 기능의 `main`/`config` 가
    이미 `sys.modules` 에 있어 그대로 재사용되고, 그 상태는 import 에러 없이
    **조용히 엉뚱한 설정으로 도는 것**으로만 드러난다.
    """
    spec = UNIT_SPECS[feature]
    request_dir = FINAL_DIR / spec["folder"] / "request"
    if not request_dir.is_dir():
        raise SystemExit(f"등록 폴더를 찾지 못했습니다: {request_dir}")
    sys.path.insert(0, str(request_dir))

    module_name = spec["app_module"]
    if module_name in sys.modules:
        raise SystemExit(
            f"'{module_name}' 이 이미 import 돼 있습니다 — 이 프로세스에서는 기능을 "
            "하나만 부팅합니다(여러 run_*.py 를 한 파이썬 프로세스에서 잇달아 부르지 "
            "말 것). 별도 프로세스로 다시 실행해 주세요."
        )
    import importlib

    module = importlib.import_module(module_name)
    return module.app


def boot_client(feature: str):
    """`fastapi.testclient.TestClient` — 실제 네트워크 포트 없이 앱을 띄운다.

    포트를 안 여는 이유는 이것도 **인프로세스 호출**이라서다(`verify_final.py` 와
    같은 기법). LLM 호출만은 대역으로 안 갈아 끼우므로 그 부분은 진짜 게이트웨이로
    나간다 — TestClient 는 앱의 라우팅·직렬화만 대신하고, 앱 안의 `httpx.AsyncClient`
    호출은 그대로 인터넷/사내망으로 나간다.
    """
    from fastapi.testclient import TestClient

    app = _import_app(feature)
    # `TestClient.__init__` 에 전역 timeout 인자가 없다(설치된 starlette 버전 기준) —
    # LLM 호출은 오래 걸릴 수 있으니 **호출부가 매 요청에 `timeout=` 을 넘긴다**
    # (`REQUEST_TIMEOUT` 상수, 아래).
    return TestClient(app)


def hwpx_files(subdir: str) -> list[Path]:
    """`Test/data/<subdir>/*.hwpx` 를 이름 순으로."""
    folder = DATA_DIR / subdir
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.hwpx") if p.is_file())


def hwpx_to_markdown(hwpx_bytes: bytes) -> str:
    """hwpx → 마크다운. **전처리기(정본) 파서를 그대로 쓴다.**

    글다듬이(hwpx 업로드 경로가 없다)와 006(자동 채움의 `document` 는 원래
    `genosUploaded`, 즉 전처리기 산출물이다)에 필요하다 — 이 저장소가 이미
    "새 hwpx 파서를 만들지 않는다" 로 정한 것과 같은 이유로, 여기서도 새로
    만들지 않고 `final_preprocessor.parse()` 를 부른다.
    """
    if str(PREPROCESSOR_DIR) not in sys.path:
        sys.path.insert(0, str(PREPROCESSOR_DIR))
    import final_preprocessor as fp

    document = fp.parse(hwpx_bytes)
    return document.to_markdown()


def eval_run_suite(feature: str, payload: dict) -> dict:
    """`Test/eval/eval_mcp.suites.run_suite` 를 직접 부른다.

    MCP 서버(`server.py`)를 거치지 않는다 — 그건 `@mcp.tool()` 어댑터일 뿐이고
    계산은 이 함수가 다 한다(패키지 머리말: "스크립트·노트북에서 그대로 import
    해 쓸 수 있다").
    """
    if str(EVAL_DIR) not in sys.path:
        sys.path.insert(0, str(EVAL_DIR))
    from eval_mcp import suites

    return suites.run_suite(feature, payload)


@dataclass
class DocResult:
    """문서 한 건의 실행 결과 + 채점 결과를 함께 들고 다니는 그릇."""

    doc_id: str
    ok: bool
    error: str = ""
    raw: dict | None = None       # 서빙 응답 원본(일부) — 사람이 직접 볼 때 참고
    eval_report: dict | None = None


def summarize(feature_label: str, results: list[DocResult]) -> dict:
    """문서별 결과를 "몇 건 중 몇 건 통과" 로 압축한다.

    통과 판정은 **eval 리포트의 `verdict`(`passed`)를 그대로 따른다** — 여기서
    다시 임계를 재지 않는다(같은 기준을 두 곳에 두면 갈린다). `verdict` 는
    `pass`/`fail`/`pass_but_incomplete`(측정 못 한 기준이 있다)/`not_measured`
    (하나도 못 쟀다) 넷 중 하나다(`eval_mcp.suites.run_suite`).
    """
    total = len(results)
    executed = [r for r in results if r.ok]
    passed = [r for r in executed if r.eval_report and r.eval_report.get("passed")]
    return {
        "feature": feature_label,
        "documents_total": total,
        "documents_executed": len(executed),
        "documents_failed_to_run": total - len(executed),
        "documents_passed": len(passed),
        "documents": [
            {
                "id": r.doc_id,
                "ran_ok": r.ok,
                "error": r.error,
                "eval_verdict": (r.eval_report or {}).get("verdict"),
            }
            for r in results
        ],
    }


def save_report(name: str, data: dict) -> Path:
    """`Test/onprem/reports/<name>_<타임스탬프>.json` 로 저장하고 경로를 돌려준다."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"{name}_{stamp}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def print_summary(summary: dict) -> None:
    print(
        f"\n[{summary['feature']}] 문서 {summary['documents_total']}건 중 "
        f"실행 성공 {summary['documents_executed']}건, "
        f"채점 통과 {summary['documents_passed']}건"
    )
    for doc in summary["documents"]:
        mark = "OK" if doc["ran_ok"] else "FAIL(실행)"
        verdict = doc["eval_verdict"] or "-"
        detail = f" — {doc['error']}" if doc["error"] else ""
        print(f"  [{mark:>10}] {doc['id']:<40} eval={verdict}{detail}")
