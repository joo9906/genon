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
_MCP = os.path.join(_ONPREM, "mcp")

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


def _load_mcp(filename: str):
    """MCP 도구 파일을 실어 온다 — 대역 응답을 **실제 도구로 만들기 위해서**다.

    응답을 손으로 적으면 MCP 가 키를 바꿔도 사본이 그대로라 대조가 성립하지 않는다.
    `translated_markdown`·`stats`·`highlighted` 가 모두 그 형태로 유실됐다.
    """
    path = os.path.join(_MCP, filename)
    spec = importlib.util.spec_from_file_location("_mcp_" + filename[:-3], path)
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


def _translation_serving_payload(*, all_failed: bool = False) -> dict:
    """번역 `/translate/markdown` 응답 — 코드서빙 `markdown_payload()` 가 만든다.

    `all_failed` 는 **유닛이 전량 원문으로 폴백된** 응답이다. 이때도 코드서빙은 200 을
    내고 `markdown` 이 비어 있지 않다(원문이 그대로 들어 있다) — 스텝이 그 둘만 보면
    사용자가 자기 글을 번역문으로 돌려받는다. 그 자리를 잡으려고 만든다.
    """
    sys.path.insert(0, os.path.join(_CODESERVING, "SFR-018_translation"))
    try:
        from api_contract import markdown_payload
        from translation_pipeline.office.glossary_report import GlossaryReport
        from translation_pipeline.office.types import (
            MarkdownTranslationArtifacts,
            TranslationStats,
        )
    finally:
        sys.path.pop(0)

    source = "# 보고서\n\n| 항목 | 값 |\n|---|---|\n| 예산 | 1,200 |"
    translated = "# Report\n\n| Item | Value |\n|---|---|\n| Budget | 1,200 |"
    if all_failed:
        return markdown_payload(
            MarkdownTranslationArtifacts(
                markdown=source,          # 폴백이므로 원문 그대로다
                source_markdown=source,
                pairs=[],
                translation_error="CONFIG_MISSING",
                stats=TranslationStats(unit_count=3, failed_unit_count=3, llm_unit_count=3),
            )
        )

    # 용어사전 하이라이트도 **실제 조립기**로 만든다 — 손으로 적으면 `as_payload()` 가
    # 키를 바꿔도 사본이 그대로라 대조가 성립하지 않는다.
    report = GlossaryReport(
        term_map={"보고서": "Report"},
        hits=[{
            "term_source": "보고서", "term_target": "Report",
            "unit_id": 0, "node_id": "md:0", "applied": True, "spans": [[2, 5]],
        }],
        matched_count=1,
        applied_count=1,
    )
    return markdown_payload(
        MarkdownTranslationArtifacts(
            markdown=translated,
            # 사전 용어에 `<mark>` 을 입힌 표시용 사본 (2026-08-14). 정본과 **달라야**
            # 이 값이 실제로 넘어오는지 대조할 수 있다 — 같으면 폴백과 구분되지 않는다.
            markdown_highlighted=translated.replace("Report", "<mark>Report</mark>"),
            source_markdown=source,
            pairs=[{"id": "md:0", "unit_id": 0, "original": "보고서", "translated": "Report"}],
            translation_error="",
            stats=TranslationStats(unit_count=3, failed_unit_count=0, llm_unit_count=3),
            glossary=report.as_payload(),
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

    async def _mcp(*args, **_kwargs):
        # 도구별로 응답이 다를 수 있다. `mcp_payload` 가 dict of dict 로 오면 도구 이름으로
        # 고르고(`_mcp_call(env, tool, arguments, ...)` 의 두 번째 인자), 아니면 그대로 쓴다.
        if isinstance(mcp_payload, dict) and callable(mcp_payload.get("__by_tool__")):
            return mcp_payload["__by_tool__"](args[1] if len(args) > 1 else "", args[2] if len(args) > 2 else {}), None
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

    # ── 용어사전 하이라이트가 화면에서 **쓸 수 있는 형태로** 넘어오는가 (2026-08-14) ──
    #
    # `glossary.hits[].unit_id` 는 유닛을 가리킨다. 그 id 를 텍스트로 되짚으려면 `pairs`
    # 가 있어야 하는데 이 스텝이 빼고 있었다 — 코드서빙을 직접 부르면 오는 값이라
    # **캔버스 경로에서만 하이라이트가 불가능**했고, 그 상태는 오류를 내지 않는다.
    glossary = out.get("glossary") or {}
    pairs = out.get("translate_pairs") or []
    unit_ids = {pair.get("unit_id") for pair in pairs}
    hit_units = {hit.get("unit_id") for hit in (glossary.get("hits") or [])}

    if glossary.get("term_map") == payload["glossary"]["term_map"]:
        rep.append(("OK", name, "하이라이트 전달", "`glossary.term_map` 이 그대로 넘어왔다"))
    else:
        rep.append(("FAIL", name, "하이라이트 전달", f"term_map={glossary.get('term_map')!r}"))

    if pairs and hit_units and hit_units <= unit_ids:
        rep.append((
            "OK", name, "유닛 되짚기",
            f"hits 의 unit_id {sorted(hit_units)} 를 `translate_pairs` 로 찾을 수 있다",
        ))
    else:
        rep.append((
            "FAIL", name, "유닛 되짚기",
            f"pairs={len(pairs)}건, hits unit_id={sorted(hit_units)}"
            " — 화면이 하이라이트 위치를 못 찾는다",
        ))

    if all(isinstance(hit.get("spans"), list) for hit in (glossary.get("hits") or [])):
        rep.append(("OK", name, "하이라이트 위치", "hits 에 원문 문자 위치(spans)가 실려 있다"))
    else:
        rep.append(("FAIL", name, "하이라이트 위치", "spans 가 빠졌다 — 문자열 검색으로 떨어진다"))

    # ── 표시용 사본과 정본이 **둘 다** 넘어오는가 (2026-08-14) ──
    #
    # 화면은 `<mark>` 이 입혀진 쪽을, 내려받기는 정본을 쓴다. 하나라도 빠지면 조용히
    # 반대쪽이 쓰이고 — 태그가 파일에 실리거나(사용자가 메모장에서 지워야 한다),
    # 하이라이트가 사라진 채 정상으로 보인다. `translated_markdown` 유실과 같은 종류다.
    highlighted = out.get("translated_markdown_highlighted")
    if highlighted == payload["markdown_highlighted"]:
        rep.append(("OK", name, "표시용 사본 전달", "`markdown_highlighted` 가 그대로 넘어왔다"))
    else:
        rep.append(("FAIL", name, "표시용 사본 전달", f"값={highlighted!r}"))

    if out.get("translated_markdown") == payload["markdown"] and highlighted != payload["markdown"]:
        rep.append((
            "OK", name, "정본과 사본을 가른다",
            "내려받기가 되돌려 보낼 값(`translated_markdown`)에는 태그가 없다",
        ))
    else:
        rep.append((
            "FAIL", name, "정본과 사본을 가른다",
            "정본이 사본으로 덮였거나 그 반대다 — 태그가 txt 에 실린다",
        ))

    # ── **화면(`text`)이 사본을 쓰는가** (2026-08-27 추가) ──
    #
    # 사본을 payload 에만 싣고 `text` 에는 정본을 흘리고 있었다. 별도 UI 가 payload 를
    # 읽는 경우에만 하이라이트가 보였고, 캔버스 채팅 화면에는 **한 번도 나타나지
    # 않았다** — 요구사항 §2 가 요구하는 표시가 통째로 빠진 상태이고, 값은 다 있으니
    # 로그·응답 어디에도 드러나지 않았다.
    if payload["markdown_highlighted"] in str(out.get("text") or ""):
        rep.append(("OK", name, "화면은 하이라이트 사본", "`text` 가 사본을 담고 있다"))
    else:
        rep.append((
            "FAIL", name, "화면은 하이라이트 사본",
            f"text={out.get('text')!r} — 정본이 흘러가 용어사전 표시가 화면에 안 나온다",
        ))

    # ── 전량 폴백을 성공으로 흘려보내지 않는다 (2026-08-14) ──
    #
    # 번역 실패 유닛은 원문이 그대로 남는 것이 코드서빙의 설계다. 그래서 LLM 이 통째로
    # 죽어도 HTTP 200 이고 `markdown` 은 비어 있지 않다. 예전 스텝은 그 둘만 봤고
    # `translation_error` 를 **한 번도 읽지 않았다** — 사용자는 자기가 넣은 글을
    # 번역문으로 받았고 화면 어디에도 실패 표시가 없었다.
    module = _load_step(name + ".py")
    failed_payload = _translation_serving_payload(all_failed=True)
    _stub_gateway(module, failed_payload, {"issues": []})

    data = dict(_BASE_DATA)
    data.update({
        "translate_source_text": failed_payload["source_markdown"],
        "translate_target_lang": "en",
        "translate_source_lang": "ko",
    })
    out = await _drain(module.run(data))

    if out.get("error"):
        rep.append((
            "OK", name, "전량 폴백 판정",
            f"원문을 번역문으로 내보내지 않고 오류로 끝냈다 ({out['error'].get('error_code')})",
        ))
    else:
        rep.append((
            "FAIL", name, "전량 폴백 판정",
            "전량 폴백인데 성공으로 끝냈다 — 사용자가 자기 원문을 번역문으로 받는다",
        ))

    # 설정 부재는 몇 번을 다시 눌러도 같은 자리에서 실패한다. 재시도 가능으로 내면
    # 캔버스가 재시도를 걸고, 로그의 error_type 도 LLM 실패와 구분되지 않는다.
    if (out.get("error") or {}).get("retryable") is False:
        rep.append(("OK", name, "설정 부재 재시도 금지", "CONFIG_MISSING 은 retryable=False"))
    else:
        rep.append((
            "FAIL", name, "설정 부재 재시도 금지",
            f"retryable={(out.get('error') or {}).get('retryable')} — 배포 설정 문제에 재시도를 권한다",
        ))


async def _check_translate_source_contract(rep: list) -> None:
    """스텝 1 — hwpx 는 우리 파서를 먼저 쓴다 (2026-08-14 배선).

    이 배선이 없을 때는 hwpx 를 올려도 지능형 전처리기 산출물(표 안 수치가 깨진다)로만
    번역됐다. 코드서빙 `POST /translate/hwpx` 는 있었지만 캔버스에서 닿을 수 없었다.
    """
    name = "sfr018_translate_01_detect"
    module = _load_step(name + ".py")

    hwpx_markdown = "# 기술협상서\n\n| 순번 | 금액 |\n|---|---|\n| 1 | 1,200 |"
    calls: list = []

    async def _mcp(env_name, tool, arguments, **_kwargs):
        calls.append(tool)
        if tool == "hwpx_to_markdown":
            return {"ok": True, "markdown": hwpx_markdown, "truncated": False}, None
        return {"allowed": True, "source_lang": "ko", "detected": True,
                "glossary_applies": True}, None

    module._mcp_call = _mcp

    data = dict(_BASE_DATA)
    data["overrideConfig"] = {"vars": {
        "translate_hwpx_path": "/mnt/shared/기술협상서.hwpx",
        "genosUploaded": "<doc file_name='x.hwpx'>전처리기가 뽑은 본문</doc>",
        "translate_target_lang": "en",
    }}
    out = await module.run(data)

    if out.get("translate_source_text") == hwpx_markdown:
        rep.append(("OK", name, "hwpx 우선", "hwpx 직접 파싱 결과를 썼다 (전처리기 산출물이 있어도)"))
    else:
        rep.append((
            "FAIL", name, "hwpx 우선",
            "전처리기 산출물을 썼다 — hwpx 전용 파서가 캔버스에서 닿지 않는 상태다",
        ))

    if out.get("translate_source_kind") == "hwpx":
        rep.append(("OK", name, "원본 경로 노출", "translate_source_kind=hwpx"))
    else:
        rep.append((
            "FAIL", name, "원본 경로 노출",
            f"translate_source_kind={out.get('translate_source_kind')!r} —"
            " 결과가 이상할 때 어느 경로였는지 알 수 없다",
        ))

    # hwpx 파싱이 실패하면 **번역을 막지 않고** 전처리기 산출물로 떨어진다.
    async def _mcp_hwpx_down(env_name, tool, arguments, **_kwargs):
        if tool == "hwpx_to_markdown":
            return None, ("execution", "MCP_TOOL_ERROR", None)
        return {"allowed": True, "source_lang": "ko", "detected": True,
                "glossary_applies": True}, None

    module._mcp_call = _mcp_hwpx_down
    out = await module.run(data)

    if out.get("translate_source_kind") == "preprocessor" and not out.get("error"):
        rep.append(("OK", name, "hwpx 실패 시 폴백", "전처리기 산출물로 진행했다"))
    else:
        rep.append((
            "FAIL", name, "hwpx 실패 시 폴백",
            f"kind={out.get('translate_source_kind')!r} error={out.get('error')} —"
            " 파서 실패가 번역 자체를 막았다",
        ))

    # 용어사전 적용 여부는 거부가 아니라 안내다 — 막지 않고 다음 스텝으로 넘긴다.
    async def _mcp_no_glossary(env_name, tool, arguments, **_kwargs):
        if tool == "hwpx_to_markdown":
            return {"ok": True, "markdown": hwpx_markdown, "truncated": False}, None
        return {"allowed": True, "source_lang": "ko", "detected": True,
                "glossary_applies": False}, None

    module._mcp_call = _mcp_no_glossary
    out = await module.run(data)

    if out.get("translate_glossary_applies") is False and not out.get("error"):
        rep.append(("OK", name, "용어사전 안내", "적용 대상이 아니어도 번역을 막지 않는다"))
    else:
        rep.append((
            "FAIL", name, "용어사전 안내",
            f"applies={out.get('translate_glossary_applies')!r} error={out.get('error')}",
        ))

    # ── 원문 언어 충돌이 경계를 넘는가 (2026-08-18) ──
    #
    # 서빙은 "§6 을 깨는 충돌" 만 거부하고 나머지는 `source_mismatch=true` 로 **통과**
    # 시킨다. 그 사실을 스텝이 안 읽으면 사용자가 원문 언어를 잘못 골랐다는 단서가
    # 여기서 사라진다 — `translated_markdown`·`stats` 와 같은 종류의 경계 유실이고,
    # 그때마다 응답 키를 안 읽는 것이 원인이었다.
    async def _mcp_mismatch(env_name, tool, arguments, **_kwargs):
        if tool == "hwpx_to_markdown":
            return {"ok": True, "markdown": hwpx_markdown, "truncated": False}, None
        return {"allowed": True, "source_lang": "th", "detected": True,
                "detected_lang": "ko", "source_mismatch": True,
                "glossary_applies": False}, None

    module._mcp_call = _mcp_mismatch
    out = await module.run(data)

    if out.get("translate_source_mismatch") is True and out.get("translate_detected_lang") == "ko":
        rep.append((
            "OK", name, "원문 언어 충돌 전달",
            "선언(th)과 감지(ko)가 다르다는 사실을 다음 스텝으로 넘긴다",
        ))
    else:
        rep.append((
            "FAIL", name, "원문 언어 충돌 전달",
            f"mismatch={out.get('translate_source_mismatch')!r} "
            f"detected={out.get('translate_detected_lang')!r} — 경계에서 유실됐다",
        ))

    # 충돌은 **거부가 아니다.** 서빙이 이미 통과시킨 것을 스텝이 다시 막으면,
    # 대상이 한국어인 정상 요청(`?→ko`)이 화면에서 막힌다.
    if not out.get("error"):
        rep.append(("OK", name, "충돌은 거부가 아니다", "번역을 계속 진행한다"))
    else:
        rep.append((
            "FAIL", name, "충돌은 거부가 아니다",
            f"error={out.get('error')} — 서빙이 통과시킨 요청을 스텝이 막았다",
        ))


async def _check_polish_contract(rep: list) -> None:
    name = "sfr018_polish_02_polish"
    module = _load_step(name + ".py")
    source = "본 사업은 2026년에 완료함."
    polished = "본 사업은 2026년에 완료하였습니다."
    # 글다듬이 `/polish` 응답 필드는 `polished_text` 다 (코드서빙 `main.polish` 반환값).
    #
    # **`diff_changes` 응답은 지어내지 않고 실제 MCP 도구로 만든다** — 손으로 적으면
    # 도구가 키를 바꿔도(`highlighted` 추가가 그런 변경이었다) 사본이 그대로라 스텝이
    # 엉뚱한 키를 읽어도 통과한다. `stats`·`translated_markdown` 이 그렇게 유실됐다.
    guard = _load_mcp("genon_text_guard.py")

    def _by_tool(tool: str, arguments: dict):
        if tool == "diff_changes":
            return guard.tgcall_tool("diff_changes", {"source": source, "revised": polished})
        return {"issues": []}

    _stub_gateway(module, {"polished_text": polished}, {"__by_tool__": _by_tool})

    data = dict(_BASE_DATA)
    data["polish_source_text"] = source
    out = await _drain(module.run(data))
    expected = guard.tgcall_tool("diff_changes", {"source": source, "revised": polished})

    if out.get("polished_text") == polished:
        rep.append(("OK", name, "다듬기 전달", "응답 `polished_text` 를 그대로 실었다"))
    else:
        rep.append(("FAIL", name, "다듬기 전달", "응답의 본문을 못 읽었다"))

    # 파일로 내려가는 값에는 경고문이 섞이면 안 된다 (`text` 는 화면용이라 섞여도 된다).
    if "⚠" not in str(out.get("polished_text") or ""):
        rep.append(("OK", name, "파일용 본문", "경고문이 섞이지 않았다"))
    else:
        rep.append(("FAIL", name, "파일용 본문", "`polished_text` 에 경고문이 섞였다 — txt 에 그대로 들어간다"))

    # ── 변경 표시는 **본문 위 하이라이트**다 (2026-08-27) ─────────────────
    #
    # 그전에는 스텝이 답변 끝에 "주요 변경 내역" 목록을 붙였다. 요구가 반대였다 —
    # 바뀐 낱말을 본문 그 자리에서 보여 달라는 것이다. 세 갈래로 갈라 본다:
    #   ① 화면(`text`)이 하이라이트 사본을 쓰는가
    #   ② 파일(`polished_text`)에 태그가 안 섞이는가 — 섞이면 메모장에서 지워야 한다
    #   ③ 좌표(`changes[].span`)가 payload 를 넘어오는가 — 없으면 프론트가 자기 방식으로
    #      칠할 수 없고, 같은 낱말이 두 번 나오면 어느 쪽인지 가릴 수 없다
    text = str(out.get("text") or "")
    if expected["highlighted"] in text and "<mark>" in text:
        rep.append(("OK", name, "화면은 하이라이트 사본", f"`<mark>` {text.count('<mark>')}개"))
    else:
        rep.append((
            "FAIL", name, "화면은 하이라이트 사본",
            f"text={text!r} — 스텝이 `highlighted` 를 안 읽었다(변경 자리가 화면에 안 나온다)",
        ))

    if "<mark>" not in str(out.get("polished_text") or ""):
        rep.append(("OK", name, "파일에는 태그가 없다", "`polished_text` 는 정본이다"))
    else:
        rep.append((
            "FAIL", name, "파일에는 태그가 없다",
            "`polished_text` 에 `<mark>` 이 섞였다 — txt 에 그대로 들어간다",
        ))

    if out.get("polished_text_highlighted") == expected["highlighted"]:
        rep.append(("OK", name, "표시용 사본 전달", "`highlighted` 가 그대로 넘어왔다"))
    else:
        rep.append((
            "FAIL", name, "표시용 사본 전달",
            f"값={out.get('polished_text_highlighted')!r}",
        ))

    spans = [c.get("span") for c in (out.get("changes") or []) if c.get("span")]
    if spans and spans == [c["span"] for c in expected["changes"] if c["span"]]:
        rep.append(("OK", name, "변경 좌표 전달", f"span {len(spans)}개"))
    else:
        rep.append((
            "FAIL", name, "변경 좌표 전달",
            f"spans={spans!r} — 좌표가 없으면 프론트가 인라인 하이라이트를 못 한다",
        ))

    # 하단 목록이 되살아나면 여기서 잡는다. `---` + "변경 내역" 이 그 형태였다.
    if "주요 변경 내역" not in text:
        rep.append(("OK", name, "하단 변경 목록 없음", "본문 뒤에 목록을 붙이지 않는다"))
    else:
        rep.append((
            "FAIL", name, "하단 변경 목록 없음",
            "답변 끝에 변경 내역 목록이 붙었다 — 본문 하이라이트로 대체된 형태다",
        ))


class _FakeResponse:
    """`_post_json` 이 보는 만큼만 흉내낸다 (status_code + json())."""

    def __init__(self, status_code: int, body) -> None:
        self.status_code = status_code
        self._body = body

    def json(self):
        if self._body is _NO_JSON:
            raise ValueError("not json")
        return self._body


_NO_JSON = object()


def _check_upstream_final(rep: list) -> None:
    """서빙이 못 박은 **재시도 불가** 판정이 스텝을 넘어오는가 (2026-08-14).

    ## 왜 이 점검이 필요한가

    스텝은 오래도록 **상태코드만** 보고 재시도 여부를 정했다 — `_RETRY_STATUS`
    (502·503·504)면 통신 실패, 나머지 4xx·5xx 는 전부 `UPSTREAM_EXECUTION`
    (retryable=True). 그래서 서빙이 `retryable=False` 로 갈라 둔 응답이 **경계에서
    통째로 뒤집혔다.**

    실제 사례: FAQ 는 2026-08-13 에 프롬프트 부재를 `ERR_API_PROMPT_UNAVAILABLE`
    (500, retryable=False)로 떼어냈다. 이미지에 프롬프트 디렉토리를 안 넣은 배포 실수라
    몇 번을 불러도 같은 자리에서 실패한다는 판단이었는데, **스텝이 그 500 을 502 와 같은
    칸에 넣어** 캔버스에는 여전히 retryable=True 로 나갔다. 서빙 쪽 `ErrorCode.retryable`
    만 보는 점검(`check_unit_endpoints`)은 통과하므로 **아무도 못 잡았다.**

    `translated_markdown`·`stats` 와 같은 종류의 결함이다 — 양쪽 다 정상인데 경계에서
    값이 사라진다. 그래서 여기서 **9개 스텝 전부** 확인한다.
    """
    for filename, _kind in STEPS:
        name = filename[:-3]
        module = _load_step(filename)

        # 1) 분류: 본문의 error_code 로 가른다 (상태코드가 아니라 — 3.9.2 코드 분류).
        cases = [
            ("00020003(그 외) 500", _FakeResponse(500, {"error_code": "03-00020003"}),
             "upstream_final"),
            ("00020002(실행 실패) 500", _FakeResponse(500, {"error_code": "03-00020002"}),
             "execution"),
            # 본문이 없거나 dict 가 아니면 **예전 그대로** 실행 실패로 둔다 —
            # 판정 못 한 응답을 재시도 불가로 올리면 일시적 장애가 최종 실패가 된다.
            ("본문 없음", _FakeResponse(500, _NO_JSON), "execution"),
            ("본문이 배열", _FakeResponse(500, [1, 2]), "execution"),
        ]
        bad = [
            f"{label}={module._upstream_kind(resp)!r}(기대 {want!r})"
            for label, resp, want in cases
            if module._upstream_kind(resp) != want
        ]
        if bad:
            rep.append(("FAIL", name, "최종실패 분류", ", ".join(bad)))
        else:
            rep.append(("OK", name, "최종실패 분류", "본문 error_code 로 가른다 (4/4)"))

        # 2) 오류표: 그 분류에 **재시도 불가** 항목이 있어야 한다.
        spec = module._ERRORS.get("UPSTREAM_FINAL")
        if not spec:
            rep.append(("FAIL", name, "최종실패 항목", "`_ERRORS['UPSTREAM_FINAL']` 이 없다"))
        elif spec["retryable"] is not False or not spec["error_code"].endswith("00020003"):
            rep.append((
                "FAIL", name, "최종실패 항목",
                f"retryable={spec['retryable']} code={spec['error_code']}",
            ))
        else:
            rep.append(("OK", name, "최종실패 항목", "retryable=False / 00020003"))


async def _check_polish_upstream_final(rep: list) -> None:
    """서빙이 낸 재시도 불가 500 이 **스텝 끝까지** 재시도 불가로 남는가.

    위 `_check_upstream_final` 은 분류 함수와 오류표를 따로 본다. 여기서는 실제 HTTP
    응답을 흘려 `_post_json` → 실패 매핑 → `result` 이벤트까지 한 번에 태운다 —
    둘 다 맞는데 매핑 분기를 안 걸어 두면 앞의 둘만으로는 통과하기 때문이다.
    """
    name = "sfr018_polish_02_polish"
    module = _load_step(name + ".py")

    async def _post_json(*_args, **_kwargs):
        # 글다듬이 서빙의 설정 부재 응답 (`ERR_CONFIG_MISSING`).
        return None, (module._upstream_kind(
            _FakeResponse(500, {"error_code": "03-00020003"})
        ), "HTTPStatusError", 500)

    module._post_json = _post_json
    os.environ["GENOS_URL"] = "http://gateway.invalid"
    os.environ["TEXT_POLISH_SERVING_ID"] = "stub"
    try:
        out = await _drain(module.run(dict(_BASE_DATA)))
    finally:
        os.environ.pop("GENOS_URL", None)
        os.environ.pop("TEXT_POLISH_SERVING_ID", None)

    error = out.get("error") or {}
    if error.get("retryable") is False and str(error.get("error_code", "")).endswith("00020003"):
        rep.append((
            "OK", name, "최종실패 전달",
            f"{error['error_code']} retryable=False — 캔버스가 재시도하지 않는다",
        ))
    else:
        rep.append((
            "FAIL", name, "최종실패 전달",
            f"error={error!r} — 배포 구성 문제가 재시도 가능으로 나갔다",
        ))


async def _run_contracts(rep: list) -> None:
    _check_upstream_final(rep)
    for check in (
        _check_faq_contract,
        _check_translate_source_contract,
        _check_translate_contract,
        _check_polish_contract,
        _check_polish_upstream_final,
    ):
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
