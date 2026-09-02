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
import logging
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

    # `_run_terminal` 이 태우는 것은 **설정 부재 경로**다 — 서빙을 부르기도 전에 끝난다.
    #
    # FAQ 는 산출물이 문답 목록이라 아예 흘리지 않는다. 번역·글다듬이는 2026-09-01 부터
    # 흘리지만 **서빙 결과를 받은 뒤에만** 흘린다 — 그 앞에서 흘리면 화면에 글을 뿌려
    # 놓고 오류로 갈아엎게 되고, 사용자에게는 **답이 나왔다가 사라지는** 것으로 보인다.
    # 그래서 이 경로에서 토큰이 나오면 셋 다 FAIL 이다.
    token_count = kinds.count("token")
    if name in _NO_STREAM_ON_ERROR:
        if token_count:
            rep.append((
                "FAIL", name, "token",
                f"오류 경로에서 {token_count}개를 흘렸다 — 답이 나왔다가 사라진다",
            ))
        else:
            rep.append(("OK", name, "token", "오류 경로에서는 흘리지 않는다(서빙 결과 뒤에만)"))
    elif name in _NO_STREAM_STEPS:
        if token_count:
            rep.append((
                "FAIL", name, "token",
                f"{token_count}개를 흘렸다 — 이 스텝은 한 번에 그린다(2026-08-28)",
            ))
        else:
            rep.append(("OK", name, "token", "흘리지 않는다 — 화면이 한 번에 그린다"))
    elif token_count:
        rep.append(("OK", name, "token", f"{token_count}개를 먼저 흘렸다"))
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


def _faq_serving_payload(*, coverage_capped: bool = False) -> dict:
    """FAQ `/generate` 응답 — 코드서빙 `FaqResult.as_payload()` 가 만든다.

    `coverage_capped` 는 **총량 상한에 걸려 일부 구간만 태운** 응답이다 (2026-08-31).
    개수를 구간 수로 나누던 것을 구간당 고정으로 바꾸면서 생긴 상태이고, 이때 사용자는
    "문서 전체에서 뽑은 결과" 로 읽을 위험이 있다 — 스텝이 이 사실을 안내문으로
    내는지 본다.
    """
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
        requested_count=10 if coverage_capped else 5,
        per_chunk_count=5,
        max_count=10,
        total_cap=10 if coverage_capped else 30,
        # 기각이 **실제로 일어난** 응답이어야 한다. 전부 0 이면 스텝이 엉뚱한 키를 읽어도
        # 0 이 나와 통과해 버린다 — 이 점검이 잡으려는 결함이 정확히 그것이다.
        rejected_schema=1,
        rejected_ungrounded=2,
        rejected_duplicate=3,
        source_chunks=4 if coverage_capped else 1,
        chunks_planned=2 if coverage_capped else 1,
        chunks_used=2 if coverage_capped else 1,
        coverage_capped=coverage_capped,
    )
    payload = result.as_payload()
    payload["markdown"] = faq_markdown(result.items)
    payload["download_ready"] = True
    # 서빙이 미리 굳혀 올린 링크 (2026-08-28). 스텝이 그대로 실어야 파일을 받는다.
    payload["download_url"] = "https://genos.genon.ai/minio/temp/faq.txt"
    return payload


def _translation_serving_payload(*, all_failed: bool = False, unapplied: bool = False) -> dict:
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
        # **번역문이 쓰지 않은 사전 용어** (2026-08-29). 준수율만으로는 "지킬 것이 없어서
        # 1.0" 과 "다 지켜서 1.0" 이 구분되지 않는다 — 그래서 스텝은 이 목록의 건수를 본다.
        term_map_unapplied={"예산": "budget"} if unapplied else {},
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
            # 원문 사본 (2026-08-28). 정본과 **달라야** 실제로 넘어오는지 대조된다.
            source_markdown_highlighted=source.replace("보고서", "<mark>보고서</mark>"),
            pairs=[{"id": "md:0", "unit_id": 0, "original": "보고서", "translated": "Report"}],
            translation_error="",
            stats=TranslationStats(unit_count=3, failed_unit_count=0, llm_unit_count=3),
            glossary=report.as_payload(),
        ),
        # 서빙이 미리 굳혀 올린 링크. 스텝이 그대로 실어야 사용자가 파일을 받는다.
        "https://genos.genon.ai/minio/temp/translated.txt",
    )


async def _drain(gen) -> dict:
    """마지막 스텝을 끝까지 돌려 `result` 이벤트의 data 를 돌려준다."""
    payload, _ = await _drain_with_tokens(gen)
    return payload


async def _drain_with_tokens(gen):
    """`(result.data, 흘린 토큰을 이어 붙인 문자열)`.

    **성공 경로의 스트리밍을 보려면 토큰을 버리면 안 된다** (2026-09-01). `_drain` 은
    `result` 만 남기므로 "무엇을 흘렸나" 가 검사된 적이 없었다 — 정본 대신 `<mark>`
    사본을 흘려도, 아예 안 흘려도 통과한다.
    """
    payload: dict = {}
    streamed: list = []
    async for item in gen:
        if not isinstance(item, dict):
            continue
        if item.get("event") == "result":
            payload = item.get("data") or {}
        elif item.get("event") == "token":
            streamed.append(str(item.get("data") or ""))
    return payload, "".join(streamed)


def _check_streaming(rep: list, name: str, module, streamed: str, *, canonical: str,
                     highlighted: str) -> None:
    """흘린 것이 **정본이고 사본이 아닌가.**

    갈래가 셋이다:

    ① **흘리기는 하는가** — 안 흘리면 화면이 몇십 초 비어 있다. 되살린 이유가 그것이다.
    ② **정본을 흘렸는가** — 무손실이어야 한다. 조각 경계에서 글자가 새면 화면에 흘린
       글과 `result` 가 어긋나는데, 화면이 갈아 끼우므로 **눈으로는 안 드러난다.**
    ③ **사본이 아닌가** — 사본을 흘리면 하이라이트가 스트리밍 중에 이미 나타나 요구가
       말한 순서("스트리밍부터 하고 끝나면 한 번에 하이라이트")와 어긋나고, 태그가 조각
       경계에서 갈려 `<ma` 같은 부스러기가 남는다.
    """
    if not streamed:
        rep.append((
            "FAIL", name, "스트리밍",
            "토큰을 하나도 흘리지 않았다 — 결과가 나올 때까지 화면이 비어 있다",
        ))
        return
    # **사본 판정이 먼저다.** 무손실 판정을 앞에 두면 사본을 흘렸을 때 그쪽이 먼저 걸려
    # 이 판정은 **영영 FAIL 할 수 없다** — 되돌려 보고 그것을 확인한 뒤 순서를 바꿨다.
    # 진단도 이쪽이 정확하다("길이가 다르다" 가 아니라 "사본을 흘렸다").
    if highlighted and highlighted != canonical and streamed == highlighted:
        rep.append((
            "FAIL", name, "스트리밍 정본 여부",
            "`<mark>` 사본을 흘렸다 — 하이라이트가 스트리밍 중에 이미 나타난다",
        ))
    else:
        rep.append((
            "OK", name, "스트리밍 정본 여부",
            "사본이 아니라 정본을 흘린다 (하이라이트는 result 가 갈아 끼운다)",
        ))

    if streamed != canonical:
        rep.append((
            "FAIL", name, "스트리밍",
            f"흘린 글이 정본과 다르다 (흘림 {len(streamed)}자 / 정본 {len(canonical)}자)",
        ))
        return
    rep.append(("OK", name, "스트리밍", f"정본을 무손실로 흘렸다 ({len(streamed)}자)"))

    # ④ **emit 수가 문서 길이에 비례하지 않는가.** 32자 고정이면 20만 자 문서가 emit
    # 6,250회다 — 소켓 메시지 수가 그렇게 늘면 긴 문서에서 그 자체가 부하가 된다.
    # 픽스처 본문은 짧아 이 상한에 닿지 않으므로 **조각 생성기를 직접 태운다.**
    long_text = "가" * 200_000
    parts = list(module._stream_chunks(long_text))
    if "".join(parts) != long_text:
        rep.append((
            "FAIL", name, "스트리밍 조각",
            "긴 글을 조각내며 글자가 새거나 겹쳤다",
        ))
    elif len(parts) > module._STREAM_MAX_EMITS:
        rep.append((
            "FAIL", name, "스트리밍 조각",
            f"20만 자에 emit {len(parts)}회 — 상한 {module._STREAM_MAX_EMITS} 를 넘겼다",
        ))
    else:
        rep.append((
            "OK", name, "스트리밍 조각",
            f"긴 글에서도 emit 수를 묶는다 (20만 자 → {len(parts)}회, 무손실)",
        ))


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


# 토큰 스트리밍을 하지 않는 스텝 (2026-08-28) — 화면이 결과를 한 번에 그린다.
# 마지막 스텝이 프론트로 내보내도 되는 키 (2026-08-28) — 화면값 + 플랫폼 추적.
# `notice` 는 2026-08-29 에 들어왔다 — **결과는 냈지만 사용자가 알아야 하는 것**
# (용어사전 미반영·부분 실패·구조/숫자 경고)이다. `error` 와 같이 **있을 때만** 실리고,
# 없을 때 빈 배열을 내지 않는다(늘 있는 빈 배열은 읽는 쪽이 "확인했다" 고 믿게 만든다).
# 그전에는 이 판정들이 "disclaimer 가 확정되면 붙인다" 며 화면에 나가지 않고 있었다.
_ALLOWED_KEYS = {
    "sfr018_polish_02_polish": {
        "genos_state", "original_text", "polished_text", "download_url",
        "notice", "error"},
    "sfr018_translate_02_translate": {
        "genos_state", "original_text", "translated_text", "download_url",
        "notice", "error"},
    "sfr018_faq_02_generate": {
        "genos_state", "faq_items", "download_url", "notice", "error"},
}

# 토큰 스트리밍을 하지 않는 스텝. **FAQ 하나만 남았다** (2026-09-01) — 산출물이 흐르는
# 글이 아니라 문답 목록이라 흘릴 것이 없다. 번역·글다듬이는 요구가 바뀌어 되살렸다.
_NO_STREAM_STEPS = frozenset({
    "sfr018_faq_02_generate",
})

# 스트리밍하는 스텝 중 **오류 경로에서는 한 개도 흘리면 안 되는** 것들 (2026-09-01).
#
# 이 둘은 서빙 결과를 받은 **뒤에만** 흘린다. 그 앞에서 흘리면 화면에 글을 뿌려 놓고
# 오류로 갈아엎게 되는데, 사용자에게는 **답이 나왔다가 사라지는** 것으로 보인다.
# `_run_terminal` 은 설정 부재(= 서빙 호출 전 실패)를 태우므로 여기서 그 규약이 잡힌다.
_NO_STREAM_ON_ERROR = frozenset({
    "sfr018_polish_02_polish",
    "sfr018_translate_02_translate",
})


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
    # 기각 건수는 2026-08-28 부터 **payload 가 아니라 로그**가 갖는다 (사용자가 보는
    # 값만 싣는 규약). 그래도 "응답에 없는 키를 읽어 영원히 0" 이라는 결함은 그대로
    # 살아 있으므로, 그물을 로그로 옮긴다 — 안 옮기면 그 결함을 보는 판정이 0건이 된다.
    records: list = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture()
    step_log = logging.getLogger("faq_generate")
    # 스텝은 `configure_logging` 을 부르지 않으므로 로거 레벨이 기본값(WARNING)이다 —
    # 낮춰 두지 않으면 INFO 가 핸들러에 닿기 전에 걸러져 판정이 조용히 통과한다.
    previous_level = step_log.level
    step_log.setLevel(logging.INFO)
    step_log.addHandler(handler)
    try:
        out = await _drain(module.run(data))
    finally:
        step_log.removeHandler(handler)
        step_log.setLevel(previous_level)

    done = next(
        (r for r in records if getattr(r, "event", "") == "faq_done"), None
    )
    status = str(getattr(done, "status", "")) if done is not None else ""

    items = out.get("faq_items") or []
    if len(items) == len(payload["items"]):
        rep.append(("OK", name, "항목 전달", f"{len(items)}건이 그대로 넘어왔다"))
    else:
        rep.append(("FAIL", name, "항목 전달", f"{len(items)}건 (응답은 {len(payload['items'])}건)"))

    expected = payload["rejected"]
    wanted = (
        f"schema={expected['schema']}"
        f" ungrounded={expected['ungrounded']}"
        f" duplicate={expected['duplicate']}"
    )
    if wanted in status:
        rep.append(("OK", name, "기각 건수", f"로그가 사유별 건수를 싣는다 — {wanted}"))
    else:
        rep.append((
            "FAIL", name, "기각 건수",
            f"status={status!r} — 응답은 {expected}. 스텝이 응답에 없는 키를 읽고 있다"
            " (기각 사유가 로그에 영원히 0 으로 찍힌다)",
        ))

    if f"requested={payload['requested_count']}" in status:
        rep.append(("OK", name, "요청 개수", "로그가 요청 개수를 싣는다"))
    else:
        rep.append(("FAIL", name, "요청 개수", f"status={status!r} — requested_count 가 유실됐다"))

    # payload 에 **화면 밖 값이 새지 않는가** (2026-08-28). `faq_stats`·
    # `faq_download_ready` 뿐 아니라 `{**data}` 가 실어 나르던 앞 스텝 값까지 함께 본다.
    leaked = sorted(set(out) - _ALLOWED_KEYS[name])
    if not leaked:
        rep.append(("OK", name, "화면 밖 값 미노출", "payload 가 화면값 + genos_state 뿐이다"))
    else:
        rep.append((
            "FAIL", name, "화면 밖 값 미노출",
            f"{leaked} 가 payload 에 실렸다 — 로그가 갖거나 화면이 안 읽는 값이다",
        ))

    # ── 일부 구간만 태운 사실을 **화면에 말하는가** (2026-08-31) ──────────────
    #
    # 개수를 구간당으로 바꾸면서 총량 상한이 "몇 구간을 태울까" 를 정하게 됐다. 상한에
    # 걸려 건너뛴 구간의 내용은 결과에 없는데, 조용히 넘기면 사용자는 **문서 전체에서
    # 뽑은 결과**로 읽는다 — 안 나온 내용이 문서에 없는 것으로 보인다. `coverage_capped`
    # 키를 스텝이 안 읽으면(또는 서빙이 이름을 바꾸면) 그 상태가 정상 응답과 구분되지
    # 않는다: 기각 건수·`translated_markdown` 과 같은 종류의 경계 유실이다.
    module = _load_step(name + ".py")
    capped = _faq_serving_payload(coverage_capped=True)
    _stub_gateway(module, capped, {"issues": []})
    capped_data = dict(_BASE_DATA)
    capped_data.update({
        "faq_source_text": "연차 휴가는 15일이며 결재 상신으로 신청한다.",
        "faq_count": 5,
        "faq_session_id": "check-session",
    })
    capped_out = await _drain(module.run(capped_data))
    notices = capped_out.get("notice") or []
    joined = " ".join(str(item) for item in notices)
    wanted_share = (
        f"{capped['source_chunks']}개 구간 중 {capped['chunks_planned']}개 구간"
    )
    if wanted_share in joined:
        rep.append((
            "OK", name, "구간 축소 안내",
            f"안내문이 태운 구간 수를 말한다 — {wanted_share}",
        ))
    else:
        rep.append((
            "FAIL", name, "구간 축소 안내",
            f"notice={notices!r} — `coverage_capped` 를 읽지 않는다"
            " (일부 구간만 태운 결과가 문서 전체에서 뽑은 것으로 보인다)",
        ))


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
    out, streamed = await _drain_with_tokens(module.run(data))

    # 흘린 것이 **정본**인가 (2026-09-01). 번역은 사본이 서빙 응답에 **이미 와 있어서**
    # 그것을 흘리기 쉬운데, 흘리면 하이라이트가 스트리밍 중에 나타난다.
    _check_streaming(
        rep, name, module, streamed,
        canonical=payload["markdown"],
        highlighted=str(payload.get("markdown_highlighted") or ""),
    )

    # 정본(`translated_markdown`)·유닛 쌍(`translate_pairs`)은 2026-08-28 에 payload 에서
    # 뺐다 — 내려받기가 링크가 되고 좌우 비교가 문서 전체 단위가 됐다. 되살아나면 잡는다.
    if "translated_markdown" not in out and "translate_pairs" not in out:
        rep.append(("OK", name, "정본·유닛쌍 미노출", "화면이 읽지 않는 값이 payload 에 없다"))
    else:
        rep.append((
            "FAIL", name, "정본·유닛쌍 미노출",
            "링크 방식·문서 단위 비교에서는 필요 없는 값이 되살아났다",
        ))

    if out.get("download_url") == payload["download_url"]:
        rep.append(("OK", name, "다운로드 링크 전달", "서빙이 낸 `download_url` 을 그대로 실었다"))
    else:
        rep.append((
            "FAIL", name, "다운로드 링크 전달",
            "응답의 번역문을 못 읽었다 — 2026-08-12 이전에 이 자리에서 번역이 매번"
            " '결과가 비어 있음' 으로 끝나고 있었다",
        ))

    if out.get("error"):
        rep.append(("FAIL", name, "성공 판정", f"정상 응답인데 error 를 냈다: {out['error']}"))
    else:
        rep.append(("OK", name, "성공 판정", "정상 응답에 error 를 내지 않는다"))

    # ── 용어사전은 **본문의 형광**으로만 화면에 닿는다 (2026-08-28) ──
    #
    # `glossary`(준수율·미적용 사유)는 검수용이라 payload 에서 뺐다. 사용자가 보는 것은
    # 사본에 입혀진 `<mark>` 뿐이고, 그 사본이 실제로 넘어오는지는 아래에서 본다.
    if "glossary" not in out and "translate_stats" not in out:
        rep.append(("OK", name, "검수값 미노출", "`glossary`·`translate_stats` 는 payload 에 없다"))
    else:
        rep.append((
            "FAIL", name, "검수값 미노출",
            "화면이 읽지 않는 값이 payload 에 되살아났다 — 로그가 갖는 값이다",
        ))

    # 원문 사본 — 좌우 비교의 왼쪽. 한쪽만 오면 미준수 용어가 화면에서 안 보인다.
    if out.get("original_text") == payload["source_markdown_highlighted"]:
        rep.append((
            "OK", name, "원문 사본 전달",
            "`source_markdown_highlighted` 가 그대로 넘어왔다",
        ))
    else:
        rep.append((
            "FAIL", name, "원문 사본 전달",
            f"값={out.get('original_text')!r} — 원문 쪽 하이라이트가 화면에 안 나온다",
        ))

    # `hits[].spans` 가 원문의 그 낱말을 실제로 가리키는지는 유닛 테스트가 본다
    # (`test_glossary_policy.test_spans_point_at_the_real_occurrences`). 여기서는
    # 그 좌표로 만든 **사본이 스텝 경계를 넘어오는지**만 본다.

    # ── 표시용 사본과 정본이 **둘 다** 넘어오는가 (2026-08-14) ──
    #
    # 화면은 `<mark>` 이 입혀진 쪽을, 내려받기는 정본을 쓴다. 하나라도 빠지면 조용히
    # 반대쪽이 쓰이고 — 태그가 파일에 실리거나(사용자가 메모장에서 지워야 한다),
    # 하이라이트가 사라진 채 정상으로 보인다. `translated_markdown` 유실과 같은 종류다.
    highlighted = out.get("translated_text")
    if highlighted == payload["markdown_highlighted"]:
        rep.append(("OK", name, "표시용 사본 전달", "`markdown_highlighted` 가 그대로 넘어왔다"))
    else:
        rep.append(("FAIL", name, "표시용 사본 전달", f"값={highlighted!r}"))

    if "<mark>" in str(out.get("original_text") or "") and highlighted != payload["markdown"]:
        rep.append((
            "OK", name, "양쪽에 사본을 쓴다",
            "원문·번역문 둘 다 `<mark>` 가 입힌 사본이다 (좌우 비교)",
        ))
    else:
        rep.append((
            "FAIL", name, "정본과 사본을 가른다",
            "정본이 사본으로 덮였거나 그 반대다 — 태그가 txt 에 실린다",
        ))

    # ── 화면에 닿는 값이 **사본인가** ────────────────────────────────────
    #
    # 2026-08-27 에는 사본을 payload 에만 싣고 `text` 로 정본을 흘리고 있었다 —
    # 요구사항 §2 의 표시가 통째로 빠진 상태였고 값은 다 있으니 아무 데도 안 드러났다.
    # `text` 는 2026-08-28 에 없앴고(전용 UI 가 좌우 비교를 그린다) 그 자리를
    # `original_text`/`translated_text` 가 물려받았다. **둘 다 사본이어야 한다.**
    # payload 에 **화면 밖 값이 새지 않는가** (2026-08-28). `{**data}` 를 쓰면 앞 스텝이
    # 넣은 값과 캔버스 입력(`question`·`overrideConfig`…)이 전부 프론트로 간다 —
    # 스텝에서 필드를 빼도 겉모양만 지켜진다.
    leaked = sorted(set(out) - _ALLOWED_KEYS[name])
    if not leaked:
        rep.append(("OK", name, "화면 밖 값 미노출", "payload 가 화면값 + genos_state 뿐이다"))
    else:
        rep.append((
            "FAIL", name, "화면 밖 값 미노출",
            f"{leaked} 가 payload 에 실렸다 — 화면이 안 읽는 값이다",
        ))

    # ── 용어사전 미준수를 **화면에 말하는가** (2026-08-29) ──────────────────
    #
    # 요구 확정: 미준수를 발견해도 **우리가 다시 번역하지 않는다.** 사실을 알리고 다시
    # 번역할지는 사용자가 정한다. 그러려면 그 사실이 화면에 닿아야 하는데, 2026-08-28
    # 까지 이 판정은 payload 로도 화면으로도 나가지 않는 "의도한 공백" 이었다 —
    # 값(`term_map_unapplied`)은 응답에 있고 아무도 안 읽는 상태였다.
    if not out.get("notice"):
        rep.append(("OK", name, "안내문 없음(정상)", "경고가 없으면 `notice` 키 자체가 없다"))
    else:
        rep.append((
            "FAIL", name, "안내문 없음(정상)",
            f"정상 응답에 안내문이 실렸다: {out.get('notice')}",
        ))

    module = _load_step(name + ".py")
    unapplied_payload = _translation_serving_payload(unapplied=True)
    _stub_gateway(module, unapplied_payload, {"issues": []})
    data = dict(_BASE_DATA)
    data.update({
        "translate_source_text": unapplied_payload["source_markdown"],
        "translate_target_lang": "en",
        "translate_source_lang": "ko",
    })
    unapplied_out = await _drain(module.run(data))

    notices = unapplied_out.get("notice") or []
    joined = " ".join(str(item) for item in notices)
    if "용어사전" in joined and "1개" in joined:
        rep.append((
            "OK", name, "용어 미준수 안내",
            "반영되지 않은 용어 **건수**를 화면에 말한다",
        ))
    else:
        rep.append((
            "FAIL", name, "용어 미준수 안내",
            f"notice={notices!r} — `term_map_unapplied` 를 읽지 않는다"
            " (미준수가 화면 어디에도 드러나지 않는다)",
        ))

    if "다시 번역" in joined:
        rep.append((
            "OK", name, "재번역은 사용자가 정한다",
            "자동 재번역 대신 다시 번역하도록 유도한다",
        ))
    else:
        rep.append((
            "FAIL", name, "재번역은 사용자가 정한다",
            f"notice={notices!r} — 사용자가 무엇을 할 수 있는지 말하지 않는다",
        ))

    # 안내문에 **용어 자체나 본문**이 실리면 안 된다 (3.8절). 자리는 화면의 형광이
    # 이미 가리키고 있고, 여기서 말할 것은 건수뿐이다.
    if "예산" not in joined and "budget" not in joined:
        rep.append(("OK", name, "안내문에 값 미포함", "건수만 말한다 (3.8절)"))
    else:
        rep.append((
            "FAIL", name, "안내문에 값 미포함",
            f"notice={notices!r} — 용어·본문이 안내문에 실렸다",
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

    _stub_gateway(
        module,
        {
            "polished_text": polished,
            "download_url": "https://genos.genon.ai/minio/temp/polished.txt",
        },
        {"__by_tool__": _by_tool},
    )

    data = dict(_BASE_DATA)
    data["polish_source_text"] = source
    out, streamed = await _drain_with_tokens(module.run(data))
    expected = guard.tgcall_tool("diff_changes", {"source": source, "revised": polished})

    # 흘린 것이 **정본**인가 (2026-09-01). 사본은 아래 `diff_changes` 가 만든다 —
    # 그것을 흘리면 하이라이트가 스트리밍 중에 이미 나타난다.
    _check_streaming(
        rep, name, module, streamed,
        canonical=polished, highlighted=expected["highlighted"],
    )

    # 사용자가 보는 값만 남았는가 (2026-08-28). `polished_text` 는 이제 **정본이 아니라
    # 사본**이다 — 정본은 파일이 됐고 접미어를 뗀 이름이 그 자리를 물려받았다.
    leaked = [k for k in ("changes", "structure_warnings", "fact_warnings",
                          "tone_overridden", "tone_notice") if k in out]
    if not leaked:
        rep.append(("OK", name, "검수값 미노출", "좌표·경고 배열은 payload 에 없다"))
    else:
        rep.append((
            "FAIL", name, "검수값 미노출",
            f"{leaked} 가 payload 에 되살아났다 — `text` 와 로그가 갖는 값이다",
        ))

    if out.get("download_url") == "https://genos.genon.ai/minio/temp/polished.txt":
        rep.append(("OK", name, "다운로드 링크 전달", "서빙이 낸 `download_url` 을 그대로 실었다"))
    else:
        rep.append((
            "FAIL", name, "다운로드 링크 전달",
            f"값={out.get('download_url')!r} — 없으면 사용자가 파일을 받을 길이 없다",
        ))

    # ── 변경 표시는 **본문 위 하이라이트**다 (2026-08-27, 08-28 양쪽 확장) ──
    #
    # 그전에는 스텝이 답변 끝에 "주요 변경 내역" 목록을 붙였다. 요구가 반대였다 —
    # 바뀐 낱말을 본문 그 자리에서 보여 달라는 것이다. 갈래는 셋이다:
    #   ① 결과 쪽 사본이 넘어오는가
    #   ② **원문 쪽 사본**도 넘어오는가 — 화면이 좌우로 놓고 비교하므로 삭제된 낱말은
    #      원문에만 자리가 있다. 한쪽만 오면 삭제가 영영 안 보인다
    #   ③ 다운로드 링크가 넘어오는가
    # payload 에 **화면 밖 값이 새지 않는가** (2026-08-28). `{**data}` 를 쓰면 앞 스텝이
    # 넣은 값과 캔버스 입력(`question`·`overrideConfig`…)이 전부 프론트로 간다 —
    # 스텝에서 필드를 빼도 겉모양만 지켜진다.
    leaked = sorted(set(out) - _ALLOWED_KEYS[name])
    if not leaked:
        rep.append(("OK", name, "화면 밖 값 미노출", "payload 가 화면값 + genos_state 뿐이다"))
    else:
        rep.append((
            "FAIL", name, "화면 밖 값 미노출",
            f"{leaked} 가 payload 에 실렸다 — 화면이 안 읽는 값이다",
        ))

    if out.get("polished_text") == expected["highlighted"]:
        rep.append(("OK", name, "결과 사본 전달", "`highlighted` 가 그대로 넘어왔다"))
    else:
        rep.append((
            "FAIL", name, "결과 사본 전달",
            f"값={out.get("polished_text")!r}",
        ))

    # 원문 사본 — 좌우 비교의 왼쪽이다. **삭제된 낱말은 여기에만 자리가 있다.**
    if out.get("original_text") == expected["source_highlighted"]:
        rep.append(("OK", name, "원문 사본 전달", "`source_highlighted` 가 그대로 넘어왔다"))
    else:
        rep.append((
            "FAIL", name, "원문 사본 전달",
            f"값={out.get('original_text')!r} — 원문 쪽 하이라이트가 화면에 안 나온다",
        ))

    # 하단 목록이 되살아나면 여기서 잡는다. `---` + "변경 내역" 이 그 형태였다.
    if "주요 변경 내역" not in str(out.get("polished_text") or ""):
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
