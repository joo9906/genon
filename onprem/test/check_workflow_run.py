"""워크플로우 스텝 9개 **실행** 점검 — 캔버스 계약(§D)을 돌려서 확인한다.

```
python onprem/test/check_workflow_run.py
```

서버도 게이트웨이도 필요 없다. **환경변수를 일부러 비우고** 호출해 설정 부재 경로
(`CONFIG_MISSING`)를 태운다.

## `check_deploy_contract.check_workflow_steps()` 와 무엇이 다른가

그쪽은 **`ast` 로 소스만 본다** — `run` 이 하나인지, 외부 패키지가 `httpx` 뿐인지,
서로 import 하지 않는지. 전부 정적이라 **스텝을 실제로 돌려 보지는 않는다.**

이 점검은 그 아래층이다. 스텝이 캔버스에 붙었을 때 지켜야 하는 것은 소스 모양이 아니라
**반환 형태**이고, 그건 실행해야만 드러난다:

| 계약 | 근거 | 어기면 |
|---|---|---|
| 중간 스텝은 `dict` 를 돌려준다 | §D.1 | 캔버스가 다음 노드로 넘길 값을 못 찾는다 |
| 마지막 스텝은 async generator 로 `token`… 후 **`result` 정확히 1회** | 스트리밍 규약 | 0회면 화면이 비고, 2회 이상이면 답변이 겹쳐 찍힌다 |
| 오류는 예외가 아니라 `data["error"]` | §A.4 | 예외를 던지면 워크플로우가 통째로 죽어 사용자에게 안내문이 못 간다 |
| `{**data, ...}` 로 돌려준다 | §D | `genos_state`(trace_id)를 잃어 추적이 끊긴다 |
| 사용자 노출 문구는 고정 안내문 | 3.8 | 내부 사정이 화면으로 샌다 |

**설정 부재 경로를 고른 이유**는 그것이 폐쇄망 최초 배포에서 **가장 먼저 만나는 실패**이기
때문이다. 서빙 ID·게이트웨이 URL 을 아직 안 넣은 상태가 정확히 이 상태다. 그때 스텝이
예외로 죽으면 캔버스에 아무 안내도 안 뜨고, 원인이 환경변수라는 것이 드러나지 않는다.

## 왜 파일마다 따로 싣는가

스텝 9개는 **전부 자기완결**이라 `_emit_log`·`_ERRORS`·`_post_serving` 같은 같은 이름을
각자 정의한다(의도된 중복 — 공용 모듈로 빼면 캔버스에 못 붙인다). 이름이 겹치므로
`importlib` 로 **파일 경로에서 각각 다른 모듈 이름으로** 싣는다.
"""

import asyncio
import importlib.util
import inspect
import os
import sys

_ONPREM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WORKFLOW = os.path.join(_ONPREM, "workflow")

# 스텝이 게이트웨이를 찾을 때 보는 환경변수. 전부 비워야 설정 부재 경로를 탄다.
# 하나라도 남아 있으면 실제 네트워크로 나가려 해서 점검이 느려지고 결과가 환경에 좌우된다.
_CONFIG_ENV = (
    "GENOS_URL",
    "GENOS_TOKEN",
    "TEMPLATE_FILL_SERVING_ID",
    "FAQ_SERVING_ID",
    "TEXT_POLISH_SERVING_ID",
    "TRANSLATE_SERVING_ID",
    "POLISH_SERVING_ID",
    "TRANSLATION_SERVING_ID",
)

# (파일, 종류) — "중간" 은 dict 반환, "마지막" 은 async generator.
# 이 분류 자체가 계약이다. 중간 스텝이 generator 가 되거나 그 반대가 되면 캔버스에서
# 노드 종류를 바꿔 달아야 하므로 여기서 갈린 것을 잡아야 한다.
STEPS = [
    ("sfr006_01_context.py", "중간"),
    ("sfr006_02_extract.py", "중간"),
    ("sfr006_03_commit.py", "마지막"),
    ("sfr018_polish_01_policy.py", "중간"),
    ("sfr018_polish_02_polish.py", "마지막"),
    ("sfr018_translate_01_detect.py", "중간"),
    ("sfr018_translate_02_translate.py", "마지막"),
    ("sfr018_faq_01_source.py", "중간"),
    ("sfr018_faq_02_generate.py", "마지막"),
]

# 스텝이 설정 부재 판정에 닿으려면 앞단 입력 검증은 통과해야 한다. 어느 스텝이 무엇을
# 읽는지가 파일마다 달라, **모든 스텝이 쓸 법한 입력을 한 벌로 합쳐** 넣는다.
# 남는 키는 스텝이 무시한다 — 그것도 `{**data, ...}` 규약의 일부다.
_BASE_DATA = {
    "question": "이 문서를 다듬어 주세요.",
    "text": "이 문서를 다듬어 주세요.",
    "socketIOClientId": "",
    "genos_state": {"trace_id": "check-workflow-run"},
    "overrideConfig": {
        "vars": {
            "template_fill_template_id": "sample",
            "polish_doc_type": "report",
            "polish_tone": "friendly",
            "translate_target_lang": "en",
            "faq_max_count": 3,
        }
    },
    # 글다듬이·번역·FAQ 가 본문으로 읽는 키들 (스텝마다 이름이 다르다)
    "polish_source_text": "본 사업은 2026년에 완료하였습니다.",
    "source_text": "본 사업은 2026년에 완료하였습니다.",
    "markdown": "본 사업은 2026년에 완료하였습니다.",
    "faq_source_markdown": "본 사업은 2026년에 완료하였습니다.",
}


def _load_step(filename: str):
    path = os.path.join(_WORKFLOW, filename)
    mod_name = "_wf_" + filename[:-3]
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clear_config_env() -> dict:
    saved = {}
    for key in _CONFIG_ENV:
        if key in os.environ:
            saved[key] = os.environ.pop(key)
    return saved


def _restore_env(saved: dict) -> None:
    os.environ.update(saved)


def _check_error_shape(error, name: str, rep: list) -> None:
    """오류 객체가 §A.4 모양인지.

    **`error_type` 은 여기 없는 것이 정상이다.** 스텝의 `_ERRORS` 표에는 있지만
    `_error()` 가 payload 를 만들 때 뺀다 — 그건 내부 분류값이라 로그(`error_type=`)에만
    남고 사용자에게 내려가는 객체에는 싣지 않는다. 처음 이 점검을 쓸 때 넷 다 있어야
    한다고 봤다가 9개가 똑같이 걸렸고, 그게 곧 "의도된 계약" 이라는 신호였다.
    그래서 **있으면 오히려 FAIL** 로 본다 — 한 스텝만 슬그머니 실어 보내는 것을 막는다.
    """
    if not isinstance(error, dict):
        rep.append(("FAIL", name, "오류 객체", f"dict 가 아니다: {type(error).__name__}"))
        return
    missing = [k for k in ("error_code", "retryable", "msg") if k not in error]
    if missing:
        rep.append(("FAIL", name, "오류 객체", f"빠진 키: {', '.join(missing)}"))
        return
    if "error_type" in error:
        rep.append((
            "FAIL", name, "오류 객체",
            "error_type 은 내부 분류값이라 로그에만 남긴다 — 응답 객체에 실으면 안 된다",
        ))
        return
    code = str(error["error_code"])
    if not code.startswith("02-"):
        rep.append((
            "FAIL", name, "영역코드",
            f"{code} — 워크플로우 스텝의 오류는 area 02 여야 한다 (03 을 그대로 올리면 안 된다)",
        ))
        return
    msg = str(error["msg"])
    # 내부 사정이 새는 흔한 형태들. 안내문은 고정 한국어여야 한다 (3.8절).
    leaks = [t for t in ("Traceback", "http://", "https://", "Error:", "os.environ") if t in msg]
    if leaks:
        rep.append(("FAIL", name, "안내문", f"내부 정보 노출: {', '.join(leaks)}"))
        return
    rep.append(("OK", name, "오류 객체", f"{code} / 고정 안내문 / retryable={error['retryable']}"))


async def _run_intermediate(module, name: str, rep: list) -> None:
    result = await module.run(dict(_BASE_DATA))

    if not isinstance(result, dict):
        rep.append(("FAIL", name, "반환형", f"dict 여야 한다 (받은 것: {type(result).__name__})"))
        return
    rep.append(("OK", name, "반환형", "dict"))

    state = result.get("genos_state")
    if isinstance(state, dict) and state.get("trace_id") == "check-workflow-run":
        rep.append(("OK", name, "data 보존", "genos_state 가 그대로 넘어왔다"))
    else:
        rep.append((
            "FAIL", name, "data 보존",
            "genos_state 를 잃었다 — `{**data, ...}` 가 아니라 dict 를 새로 만들었을 것이다",
        ))

    error = result.get("error")
    if not error:
        rep.append((
            "FAIL", name, "설정 부재",
            "환경변수를 비웠는데 error 가 없다 — 게이트웨이로 실제로 나갔을 수 있다",
        ))
        return
    _check_error_shape(error, name, rep)


async def _run_terminal(module, name: str, rep: list) -> None:
    gen = module.run(dict(_BASE_DATA))
    if not inspect.isasyncgen(gen):
        rep.append((
            "FAIL", name, "반환형",
            f"async generator 여야 한다 (받은 것: {type(gen).__name__}) — 마지막 스텝은 스트리밍한다",
        ))
        return
    rep.append(("OK", name, "반환형", "async generator"))

    events = []
    async for item in gen:
        events.append(item)
        if len(events) > 500:  # 무한 생성 방어
            rep.append(("FAIL", name, "이벤트 수", "500개를 넘겼다 — 종료 조건이 없을 수 있다"))
            return

    kinds = [e.get("event") for e in events if isinstance(e, dict)]
    if len(kinds) != len(events):
        rep.append(("FAIL", name, "이벤트 모양", "dict 가 아니거나 event 키가 없는 항목이 있다"))
        return

    results = [e for e in events if e.get("event") == "result"]
    if len(results) == 1:
        rep.append(("OK", name, "result", "정확히 1회"))
    else:
        rep.append((
            "FAIL", name, "result",
            f"{len(results)}회 — 0회면 화면이 비고, 2회 이상이면 답변이 겹쳐 찍힌다",
        ))
        return

    if kinds[-1] != "result":
        rep.append(("FAIL", name, "result 위치", f"마지막이 아니다: {kinds[-1]}"))
        return

    if any(k == "token" for k in kinds):
        rep.append(("OK", name, "token", f"{kinds.count('token')}개를 먼저 흘렸다"))
    else:
        rep.append((
            "WARN", name, "token",
            "token 없이 result 만 냈다 — 안내문이 짧으면 정상일 수 있다",
        ))

    payload = results[0].get("data")
    if not isinstance(payload, dict):
        rep.append(("FAIL", name, "result.data", "dict 가 아니다"))
        return

    state = payload.get("genos_state")
    if isinstance(state, dict) and state.get("trace_id") == "check-workflow-run":
        rep.append(("OK", name, "data 보존", "genos_state 가 그대로 넘어왔다"))
    else:
        rep.append(("FAIL", name, "data 보존", "genos_state 를 잃었다"))

    error = payload.get("error")
    if not error:
        rep.append((
            "FAIL", name, "설정 부재",
            "환경변수를 비웠는데 error 가 없다 — 게이트웨이로 실제로 나갔을 수 있다",
        ))
        return
    _check_error_shape(error, name, rep)


async def _run_all(rep: list) -> None:
    for filename, kind in STEPS:
        name = filename[:-3]
        try:
            module = _load_step(filename)
        except Exception as exc:  # noqa: BLE001
            rep.append(("FAIL", name, "import", f"{type(exc).__name__}: {exc}"))
            continue

        if not hasattr(module, "run"):
            rep.append(("FAIL", name, "run", "함수가 없다 — 캔버스 고정 계약이다"))
            continue

        try:
            if kind == "중간":
                await _run_intermediate(module, name, rep)
            else:
                await _run_terminal(module, name, rep)
        except Exception as exc:  # noqa: BLE001
            rep.append((
                "FAIL", name, "실행",
                f"예외가 올라왔다 ({type(exc).__name__}: {exc}) — 오류는 data['error'] 로 돌려야 한다",
            ))


def main() -> int:
    try:
        import httpx  # noqa: F401
    except ImportError:
        sys.stderr.write("httpx 가 없어 스텝을 실을 수 없다. `pip install httpx` 후 실행할 것.\n")
        return 2

    saved = _clear_config_env()
    rep: list = []
    try:
        asyncio.run(_run_all(rep))
    finally:
        _restore_env(saved)

    ok = sum(1 for r in rep if r[0] == "OK")
    warn = sum(1 for r in rep if r[0] == "WARN")
    fail = sum(1 for r in rep if r[0] == "FAIL")

    width = max(len(r[1]) for r in rep)
    for status, name, item, detail in rep:
        mark = {"OK": "OK  ", "WARN": "WARN", "FAIL": "FAIL"}[status]
        print(f"[{mark}] {name:<{width}}  {item:<10} {detail}")

    print()
    print(f"FAIL {fail} / WARN {warn} / OK {ok}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
