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


# ---------------------------------------------------------------------------
# 성공 경로 — 스텝이 읽는 키가 코드서빙 응답에 **실제로 있는가** (2026-08-13 신규)
#
# ## 왜 필요한가 — 위 점검들이 통째로 못 보는 층이다
#
# 여기까지의 판정은 전부 **설정 부재 경로**를 태운다. 그 경로에서 스텝은 게이트웨이
# 응답을 한 번도 읽지 않으므로, 응답에서 무슨 키를 꺼내는지는 검사된 적이 없다.
# 그래서 이런 결함이 살아남는다:
#
# | 언제 | 무엇 | 증상 |
# |---|---|---|
# | ~2026-08-12 | 번역 스텝이 `translated_markdown` 을 읽었다 (응답 키는 `markdown`) | 번역이 **매번** "결과가 비어 있음" 으로 끝났다 |
# | ~2026-08-13 | FAQ 스텝이 `stats` 를 읽었다 (응답에 그런 키가 없다) | 기각 건수가 **영원히 0** 이었다 |
#
# 둘 다 예외를 던지지 않는다. `.get()` 이 조용히 기본값을 주므로 **정상 동작처럼 보이고**,
# 로그에도 `schema=0 ungrounded=0` 처럼 "문제 없음" 으로 찍힌다. 실행해서 값을 대조하는
# 것 말고는 드러날 방법이 없다.
#
# ## 대조 방식 — 응답을 지어내지 않고 **코드서빙 자기 코드로 만든다**
#
# 페이로드를 이 파일에 손으로 적으면 대조가 성립하지 않는다(코드서빙이 키 이름을 바꿔도
# 여기 사본은 그대로다). 그래서 각 단위의 **실제 payload 조립 함수**를 불러 응답을 만든다 —
# `FaqResult.as_payload()`·`api_contract.markdown_payload()`. 한쪽이 이름을 바꾸면 여기서
# 갈린 것이 드러난다.
#
# 게이트웨이 호출부(`_post_serving`/`_mcp_call`)만 대역으로 바꾼다. 스텝의 응답 해석
# 코드는 그대로 돈다 — 그게 검사 대상이다.
# ---------------------------------------------------------------------------

_CODESERVING = os.path.join(_ONPREM, "codeserving")


def _faq_serving_payload() -> dict:
    """FAQ `/generate` 응답 — 코드서빙 `FaqResult.as_payload()` 가 만든다."""
    sys.path.insert(0, os.path.join(_CODESERVING, "SFR-018_faq"))
    try:
        from faq.formatting import to_markdown as faq_markdown
        from faq.generator import FaqItem, FaqResult
    finally:
        sys.path.pop(0)

    result = FaqResult(
        items=[
            FaqItem("연차는 며칠인가요?", "15일입니다.", "연차 휴가는 15일", 1.0),
            FaqItem("신청은 어떻게 하나요?", "결재로 신청합니다.", "결재 상신", 0.9),
        ],
        requested_count=5,
        max_count=10,
        # 기각이 **실제로 일어난** 응답이어야 한다. 전부 0 이면 스텝이 엉뚱한 키를 읽어도
        # 0 이 나와 통과해 버린다 — 이 점검이 잡으려는 결함이 정확히 그것이다.
        rejected_schema=1,
        rejected_ungrounded=2,
        rejected_duplicate=3,
    )
    payload = result.as_payload()
    payload["markdown"] = faq_markdown(result.items)
    payload["download_ready"] = True
    return payload


def _translation_serving_payload() -> dict:
    """번역 `/translate/markdown` 응답 — 코드서빙 `markdown_payload()` 가 만든다."""
    sys.path.insert(0, os.path.join(_CODESERVING, "SFR-018_translation"))
    try:
        from api_contract import markdown_payload
        from translation_pipeline.office.types import MarkdownTranslationArtifacts
    finally:
        sys.path.pop(0)

    return markdown_payload(
        MarkdownTranslationArtifacts(
            markdown="# Report\n\n| Item | Value |\n|---|---|\n| Budget | 1,200 |",
            source_markdown="# 보고서\n\n| 항목 | 값 |\n|---|---|\n| 예산 | 1,200 |",
            pairs=[{"id": "md:0", "unit_id": 0, "original": "보고서", "translated": "Report"}],
            translation_error="",
        )
    )


async def _drain(gen) -> dict:
    """마지막 스텝을 끝까지 돌려 `result` 이벤트의 data 를 돌려준다."""
    payload: dict = {}
    async for item in gen:
        if isinstance(item, dict) and item.get("event") == "result":
            payload = item.get("data") or {}
    return payload


def _stub_gateway(module, serving_payload: dict, mcp_payload: dict) -> None:
    """게이트웨이 호출만 대역으로 바꾼다 — 응답 해석 코드는 그대로 둔다.

    스텝마다 `_post_serving` 시그니처가 다르다(FAQ 는 서빙 ID 를 상수로 들고 있어 인자가
    하나 적다). 대역은 인자를 보지 않으므로 `*args` 로 받는다.
    """
    async def _serving(*_args, **_kwargs):
        return serving_payload, None

    async def _mcp(*_args, **_kwargs):
        return mcp_payload, None

    module._post_serving = _serving
    if hasattr(module, "_mcp_call"):
        module._mcp_call = _mcp


async def _check_faq_contract(rep: list) -> None:
    name = "sfr018_faq_02_generate"
    module = _load_step(name + ".py")
    payload = _faq_serving_payload()
    _stub_gateway(module, payload, {"issues": []})

    data = dict(_BASE_DATA)
    data.update({
        "faq_source_text": "연차 휴가는 15일이며 결재 상신으로 신청한다.",
        "faq_count": 5,
        "faq_session_id": "check-session",
    })
    out = await _drain(module.run(data))

    items = out.get("faq_items") or []
    if len(items) == len(payload["items"]):
        rep.append(("OK", name, "항목 전달", f"{len(items)}건이 그대로 넘어왔다"))
    else:
        rep.append(("FAIL", name, "항목 전달", f"{len(items)}건 (응답은 {len(payload['items'])}건)"))

    rejected = (out.get("faq_stats") or {}).get("rejected") or {}
    expected = payload["rejected"]
    if rejected == expected:
        rep.append((
            "OK", name, "기각 건수",
            f"schema={rejected['schema']} ungrounded={rejected['ungrounded']}"
            f" duplicate={rejected['duplicate']}",
        ))
    else:
        rep.append((
            "FAIL", name, "기각 건수",
            f"{rejected} — 응답은 {expected}. 스텝이 응답에 없는 키를 읽고 있다"
            " (기각 사유가 화면·로그에 영원히 0 으로 찍힌다)",
        ))

    if (out.get("faq_stats") or {}).get("requested_count") == payload["requested_count"]:
        rep.append(("OK", name, "요청 개수", "요청/생성 개수가 함께 넘어왔다"))
    else:
        rep.append(("FAIL", name, "요청 개수", "requested_count 가 유실됐다"))


async def _check_translate_contract(rep: list) -> None:
    name = "sfr018_translate_02_translate"
    module = _load_step(name + ".py")
    payload = _translation_serving_payload()
    _stub_gateway(module, payload, {"issues": []})

    data = dict(_BASE_DATA)
    data.update({
        "translate_source_text": payload["source_markdown"],
        "translate_target_lang": "en",
        "translate_source_lang": "ko",
    })
    out = await _drain(module.run(data))

    if out.get("translated_markdown") == payload["markdown"]:
        rep.append(("OK", name, "번역문 전달", "응답 `markdown` 을 그대로 실었다"))
    else:
        rep.append((
            "FAIL", name, "번역문 전달",
            "응답의 번역문을 못 읽었다 — 2026-08-12 이전에 이 자리에서 번역이 매번"
            " '결과가 비어 있음' 으로 끝나고 있었다",
        ))

    if out.get("error"):
        rep.append(("FAIL", name, "성공 판정", f"정상 응답인데 error 를 냈다: {out['error']}"))
    else:
        rep.append(("OK", name, "성공 판정", "정상 응답에 error 를 내지 않는다"))


async def _check_polish_contract(rep: list) -> None:
    name = "sfr018_polish_02_polish"
    module = _load_step(name + ".py")
    polished = "본 사업은 2026년에 완료했습니다."
    # 글다듬이 `/polish` 응답 필드는 `polished_text` 다 (코드서빙 `main.polish` 반환값).
    _stub_gateway(module, {"polished_text": polished}, {"issues": [], "changes": []})

    data = dict(_BASE_DATA)
    data["polish_source_text"] = "본 사업은 2026년에 완료하였습니다."
    out = await _drain(module.run(data))

    if out.get("polished_text") == polished:
        rep.append(("OK", name, "다듬기 전달", "응답 `polished_text` 를 그대로 실었다"))
    else:
        rep.append(("FAIL", name, "다듬기 전달", "응답의 본문을 못 읽었다"))

    # 파일로 내려가는 값에는 경고문이 섞이면 안 된다 (`text` 는 화면용이라 섞여도 된다).
    if "⚠" not in str(out.get("polished_text") or ""):
        rep.append(("OK", name, "파일용 본문", "경고문이 섞이지 않았다"))
    else:
        rep.append(("FAIL", name, "파일용 본문", "`polished_text` 에 경고문이 섞였다 — txt 에 그대로 들어간다"))


async def _run_contracts(rep: list) -> None:
    for check in (_check_faq_contract, _check_translate_contract, _check_polish_contract):
        try:
            await check(rep)
        except Exception as exc:  # noqa: BLE001
            rep.append((
                "FAIL", check.__name__, "응답 대조",
                f"{type(exc).__name__}: {exc}",
            ))


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
        # 성공 경로는 환경변수와 무관하다 (게이트웨이 호출부를 대역으로 바꾼다).
        # 그래도 같은 블록 안에서 돌려 env 복원이 한 자리에서만 일어나게 둔다.
        asyncio.run(_run_contracts(rep))
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
