"""배포 단위 4개 기동 점검 — 앱이 실제로 떠서 요청을 받는가.

```
python onprem/test/check_service_boot.py
```

서버도 포트도 열지 않는다. `TestClient` 로 인프로세스 기동한다.

## 왜 필요한가 — `check_deploy_contract.py` 로는 안 잡히는 것들

`check_deploy_contract.py` 는 **소스를 `ast` 로 읽기만 한다.** 그래서
"`/health` 라우트를 정의하는 코드가 있다" 는 확인하지만 **"앱이 실제로 뜬다"** 는 확인하지
못한다. 그 사이에 실제로 빠져나간 결함이 넷 있었다 (2026-08-11 전수 점검):

| 결함 | 정적 점검이 못 잡은 이유 |
|---|---|
| `python-multipart` 미선언 | `File(...)` 라우트 등록 시점에 FastAPI 가 RuntimeError 를 낸다 — **import 는 통과한다** |
| `@app.get("")` 가 404 | 라우트 정의는 멀쩡하다. ASGI path 가 최소 `/` 라서 **닿지 않을 뿐**이다 |
| 프롬프트 디렉토리 유실 | 경로 해석이 런타임에 일어난다 |
| 성공/오류 Union 반환 주석 | `response_model` 생성 실패라 **라우트 등록 단계**에서 죽는다 |

넷 다 "소스는 정상, 기동은 실패" 다. 이 점검이 그 층을 맡는다.

## 왜 단위마다 subprocess 인가

단위들이 **같은 최상위 모듈 이름을 쓴다** — 번역과 글다듬이가 둘 다 `main`·`config` 다.
한 프로세스에서 차례로 import 하면 `sys.modules` 에 먼저 들어간 쪽이 뒤엣것을 가려,
**두 번째 단위부터는 첫 번째 단위의 코드를 검사하게 된다.** 그러면 전부 통과한 것처럼
보인다. 프로세스를 갈라 그 가능성을 없앤다.

## 무엇을 보는가

1. **lifespan 이 돈다** — `TestClient` 를 컨텍스트로 진입하면 기동 훅이 실제로 실행된다.
   `@app.on_event("startup")` → `lifespan` 전환(2026-08-11)이 조용히 안 도는 상태로
   바뀌지 않았는지 여기서 드러난다.
2. **`/health` 200** (가이드 11.5.3 이 요구하는 헬스체크)
3. **`/` 200** — `@app.get("")` 만 있으면 404 다. 넉 달간 세 단위가 그 상태였다.
4. **라우트가 실제로 등록됐다** (`File(...)` 라우트가 있는 단위는 이게 곧 multipart 확인)

기대값은 **"최소 몇 개 이상"** 으로 둔다. 정확한 개수를 박으면 라우트를 하나 늘릴 때마다
이 파일을 고쳐야 하는데, 그건 이 점검이 잡으려는 결함과 아무 상관이 없다.
"""

import json
import os
import subprocess
import sys

_ONPREM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (표시 이름, 단위 루트, import 할 모듈, 최소 라우트 수)
#
# 최소 라우트 수는 "라우트 등록이 통째로 실패하지 않았다" 를 보는 하한이다. FastAPI 는
# 기본 라우트 4개(openapi/docs/redoc/swagger-redirect)를 스스로 붙이므로 그보다 커야 한다.
#
# **MCP 는 여기 없다.** MCP 도구는 FastAPI 앱이 아니라 **소스 파일 한 개**이고,
# `mcp` 객체를 GenOS 런타임이 주입한다. 띄울 앱도 `/health` 도 없으므로 이 점검의
# 대상이 아니다 — `check_mcp_tools.py` 가 도구를 직접 불러 확인한다.
UNITS = [
    ("SFR-006 템플릿 채우기", "codeserving/SFR-006_template_fill", "template_fill.main", 10),
    ("SFR-018 번역", "codeserving/SFR-018_translation", "main", 10),
    ("SFR-018 글다듬이", "codeserving/SFR-018_text_polish", "main", 7),
    ("SFR-018 FAQ", "codeserving/SFR-018_faq", "faq.main", 10),
]


# --------------------------------------------------------------------------
# 자식 프로세스: 단위 하나를 기동한다
# --------------------------------------------------------------------------

def _boot_one(root: str, module: str) -> dict:
    """단위 하나를 import·기동하고 결과를 dict 로 돌려준다.

    **환경변수를 주지 않은 상태로 띄운다.** Redis·게이트웨이·볼륨 없이도 앱이 떠야
    한다 — 기동 시점에 외부 자원을 요구하면 pod 이 CrashLoopBackOff 로 돌고, 그건
    폐쇄망에서 가장 알아내기 어려운 실패 형태다. 축퇴 경로가 있다는 것을 여기서 본다.
    """
    unit_path = os.path.join(_ONPREM, root)
    sys.path.insert(0, unit_path)

    import importlib

    from fastapi.testclient import TestClient

    mod = importlib.import_module(module)
    app = mod.app

    result = {"routes": len(app.routes)}
    with TestClient(app) as client:  # __enter__ 가 lifespan 을 돌린다
        result["lifespan"] = True
        result["health"] = client.get("/health").status_code
        result["root"] = client.get("/").status_code
    return result


def _child_main(root: str, module: str) -> int:
    try:
        payload = _boot_one(root, module)
        payload["ok"] = True
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 부모에게 이름으로 전달한다
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    # 부모가 마지막 줄만 파싱한다. 단위들이 기동 로그를 stdout/stderr 로 뱉으므로
    # 구분 가능한 표지를 붙인다.
    sys.stdout.write("\n__BOOT_RESULT__" + json.dumps(payload) + "\n")
    return 0


# --------------------------------------------------------------------------
# 부모 프로세스
# --------------------------------------------------------------------------

def _run_unit(name: str, root: str, module: str, min_routes: int, results: list) -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--child", root, module],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )
    marker = "__BOOT_RESULT__"
    line = ""
    for raw in (proc.stdout or "").splitlines():
        if raw.startswith(marker):
            line = raw[len(marker):]
    if not line:
        tail = ((proc.stderr or "") + (proc.stdout or "")).strip().splitlines()[-3:]
        results.append(("FAIL", name, "기동", "결과를 받지 못했다: " + " / ".join(tail)))
        return

    payload = json.loads(line)
    if not payload.get("ok"):
        results.append(("FAIL", name, "기동", payload.get("error", "알 수 없는 실패")))
        return

    results.append(("OK", name, "lifespan", "기동 훅이 예외 없이 돌았다"))

    health = payload.get("health")
    if health == 200:
        results.append(("OK", name, "/health", "200"))
    else:
        results.append(("FAIL", name, "/health", f"{health} (200 이어야 한다)"))

    root_status = payload.get("root")
    if root_status == 200:
        results.append(("OK", name, "/", "200"))
    else:
        results.append((
            "FAIL", name, "/",
            f"{root_status} — `@app.get(\"\")` 만 있으면 404 다 (2026-08-11 결함)",
        ))

    routes = payload.get("routes", 0)
    if routes >= min_routes:
        results.append(("OK", name, "라우트 등록", f"{routes}개 (>= {min_routes})"))
    else:
        results.append((
            "FAIL", name, "라우트 등록",
            f"{routes}개 — {min_routes}개 이상이어야 한다. 라우트 등록이 통째로 실패했을 수 있다",
        ))


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        return _child_main(sys.argv[2], sys.argv[3])

    try:
        import fastapi  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "fastapi 가 없어 기동 점검을 돌릴 수 없다. "
            "`pip install fastapi httpx` 후 다시 실행할 것.\n"
        )
        return 2

    results: list = []
    for name, root, module, min_routes in UNITS:
        _run_unit(name, root, module, min_routes, results)

    ok = sum(1 for r in results if r[0] == "OK")
    fail = sum(1 for r in results if r[0] == "FAIL")

    width = max(len(r[1]) for r in results)
    for status, name, item, detail in results:
        mark = "OK  " if status == "OK" else "FAIL"
        print(f"[{mark}] {name:<{width}}  {item:<12} {detail}")

    print()
    print(f"OK {ok} / {ok + fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
