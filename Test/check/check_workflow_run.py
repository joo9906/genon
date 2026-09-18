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
import json
import os
import sys

import httpx

from paths import MCP_DIR as _MCP, WORKFLOW_DIR as _WORKFLOW, unit_dir  # noqa: E402

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
    if not code.startswith("ERR-02-"):
        rep.append((
            "FAIL", name, "영역코드",
            f"{code} — 워크플로우 스텝의 오류는 `ERR-02-…` 여야 한다 (03 을 그대로 올리면 안 된다)",
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
    # 네 스텝이 다 흘리지만(FAQ 는 2026-09-02, 캔버스 배선은 2026-09-09) **서빙 결과를
    # 받은 뒤에만** 흘린다 — 그 앞에서 흘리면 화면에 글을 뿌려
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



def _faq_serving_payload(*, coverage_capped: bool = False) -> dict:
    """FAQ `/generate` 응답 — 코드서빙 `FaqResult.as_payload()` 가 만든다.

    `coverage_capped` 는 **호출 수 상한에 걸려 일부 구간만 태운** 응답이다. 총 개수는
    지켜지지만 그 개수를 문서 일부 구간에서만 뽑았다는 뜻이라, 사용자는 "문서 전체에서
    뽑은 결과" 로 읽을 위험이 있다 — 스텝이 이 사실을 안내문으로 내는지 본다.
    """
    sys.path.insert(0, unit_dir("SFR-018_faq"))
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
        # 사용자가 고른 총 개수 그대로다 — 구간이 몇이든 이 값은 안 바뀐다
        # (2026-09-03 요구 확정). 구간 배분은 서빙 안에서 끝난다.
        requested_count=5,
        max_count=30,
        call_cap=2 if coverage_capped else 6,
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
    sys.path.insert(0, unit_dir("SFR-018_translation"))
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
    async def _serving(*args, **_kwargs):
        # 한 스텝이 서빙을 **두 경로**로 부를 수 있다 (번역: 스트리밍 뒤 `/translate/
        # finalize`). 경로마다 다른 응답이 필요하면 `{"__by_path__": fn}` 을 준다 —
        # 하나로 뭉치면 "폴백이 불렸다" 와 "마무리가 불렸다" 를 가릴 수 없다.
        if isinstance(serving_payload, dict) and callable(serving_payload.get("__by_path__")):
            path = next((a for a in args if isinstance(a, str) and a.startswith("/")), "")
            return serving_payload["__by_path__"](path), None
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

# 토큰 스트리밍을 하지 않는 스텝 — **이제 없다** (2026-09-09). FAQ 는 2026-09-02 에
# 되살아났는데 **그때 이 목록에서 빼지 않아** 그물이 "FAQ 는 흘리지 않는다" 를 계속
# 지키고 있었다(그 상태로는 FAQ 스트리밍이 한 번도 검사되지 않는다). 네 스텝이 다
# 흘리므로 남은 판정은 아래 "오류 경로에서는 흘리지 않는다" 뿐이다.
_NO_STREAM_STEPS = frozenset()

# 스트리밍하는 스텝 중 **오류 경로에서는 한 개도 흘리면 안 되는** 것들 (2026-09-01).
#
# 이 둘은 서빙 결과를 받은 **뒤에만** 흘린다. 그 앞에서 흘리면 화면에 글을 뿌려 놓고
# 오류로 갈아엎게 되는데, 사용자에게는 **답이 나왔다가 사라지는** 것으로 보인다.
# `_run_terminal` 은 설정 부재(= 서빙 호출 전 실패)를 태우므로 여기서 그 규약이 잡힌다.
_NO_STREAM_ON_ERROR = frozenset({
    "sfr018_polish_02_polish",
    "sfr018_translate_02_translate",
    # FAQ 도 2026-09-09 부터 여기다 — 스트리밍 경로로 흘리므로 오류 경로에서 흘리면
    # 같은 문제가 된다(답이 나왔다가 사라진다).
    "sfr018_faq_02_generate",
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
    """스텝 1 — 원본은 **전처리기 산출물 하나**다 (2026-09-07 변경).

    ## 그전 계약과 무엇이 다른가

    2026-08-14 ~ 09-06 에는 `translate_hwpx_path` 가 있으면 MCP `hwpx_to_markdown` 으로
    원본을 **다시 파싱**했고, 이 함수는 "hwpx 우선" 을 지키고 있었다. 그 배선을 걷어낸
    이유는 스텝 머리말에 있다 — 실환경에서 그 호출이 전부 406 이었고(Accept 헤더),
    실패는 조용히 전처리기 산출물로 폴백해서 **표가 깨진 번역문으로만** 드러났다.

    지금 지켜야 하는 것은 반대다: **문서를 MCP 로 파싱하지 않는다.** 첨부용 등록이
    `preprocessor/only_me.py`(파싱 전용·청킹 없음)이므로 `genosUploaded` 가 곧 원문이고,
    두 번 파싱하면 그 둘이 갈릴 수 있다(파싱 코어 사본이 여섯 벌이다).
    """
    name = "sfr018_translate_01_detect"
    module = _load_step(name + ".py")

    uploaded = "# 기술협상서\n\n<table><tbody><tr><td>순번</td><td>금액</td></tr></tbody></table>"
    calls: list = []

    async def _mcp(env_name, tool, arguments, **_kwargs):
        calls.append(tool)
        if tool == "hwpx_to_markdown":
            # **불리면 안 되는 도구다.** 그래도 그럴듯한 응답을 준다 — 오류를 주면
            # 아래 판정이 "호출했다" 가 아니라 "번역이 실패했다" 로 드러나 진단이 흐려진다.
            return {"ok": True, "markdown": "MCP 가 파싱한 본문", "truncated": False}, None
        return {"allowed": True, "source_lang": "ko", "detected": True,
                "glossary_applies": True}, None

    module._mcp_call = _mcp

    data = dict(_BASE_DATA)
    data["overrideConfig"] = {"vars": {
        # **옛 캔버스 변수가 남아 있어도** 동작이 갈리지 않아야 한다 — 배포마다 다른
        # 원본을 쓰면 "어떤 캔버스에서만 표가 깨진다" 가 된다.
        "translate_hwpx_path": "/mnt/shared/기술협상서.hwpx",
        "genosUploaded": f"<doc file_name='x.hwpx'>{uploaded}</doc>",
        "translate_target_lang": "en",
    }}
    out = await module.run(data)

    if "hwpx_to_markdown" not in calls:
        rep.append((
            "OK", name, "문서 파싱 없음",
            "MCP 로 문서를 다시 파싱하지 않는다 (전처리기 산출물이 원문이다)",
        ))
    else:
        rep.append((
            "FAIL", name, "문서 파싱 없음",
            "MCP `hwpx_to_markdown` 을 불렀다 — 첨부 문서를 두 번 파싱한다"
            " (그 경로는 실환경에서 406 이었고 실패가 조용히 폴백된다)",
        ))

    if out.get("translate_source_text") == uploaded:
        rep.append(("OK", name, "원본 확보", "전처리기 산출물을 원문으로 쓴다"))
    else:
        rep.append((
            "FAIL", name, "원본 확보",
            f"translate_source_text={str(out.get('translate_source_text'))[:40]!r} —"
            " `genosUploaded` 의 본문이 그대로 넘어가지 않았다",
        ))

    if out.get("translate_source_kind") == "preprocessor":
        rep.append(("OK", name, "원본 경로 노출", "translate_source_kind=preprocessor"))
    else:
        rep.append((
            "FAIL", name, "원본 경로 노출",
            f"translate_source_kind={out.get('translate_source_kind')!r} —"
            " 결과가 이상할 때 어느 경로였는지 알 수 없다",
        ))

    # 용어사전 적용 여부는 거부가 아니라 안내다 — 막지 않고 다음 스텝으로 넘긴다.
    async def _mcp_no_glossary(env_name, tool, arguments, **_kwargs):
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
    # **2026-09-17 에 낱말 diff 하이라이트(`diff_changes`)를 뺐다.** 이 스텝은 이제
    # `diff_changes` 를 부르지 않는다 — `_by_tool` 이 그 이름을 가리지 않아도 된다.
    # `guard` 는 아래에서 "하이라이트를 만들면 이런 값이 나온다" 는 대조군을 만드는
    # 데만 쓴다 (스트리밍이 우연히 그 값과 같아지지 않는가를 본다).
    guard = _load_mcp("genon_text_guard.py")

    def _by_tool(tool: str, arguments: dict):
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

    # ── 변경 표시(낱말 하이라이트)는 뺐다 (2026-09-17) ──────────────────────
    #
    # 2026-08-27~28 에는 스텝이 `<mark>` 사본 둘(원문·결과)을 좌우로 냈다. 지금은 그
    # 사본이 없다 — `original_text`/`polished_text` 가 각각 **원문·다듬은 글 그대로**다.
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

    if out.get("polished_text") == polished:
        rep.append(("OK", name, "결과 그대로 전달", "`<mark>` 없이 다듬은 글 그대로다"))
    else:
        rep.append((
            "FAIL", name, "결과 그대로 전달",
            f"값={out.get('polished_text')!r}",
        ))

    # 원문도 그대로다 — 좌우 비교의 왼쪽이지만 더는 하이라이트를 입히지 않는다.
    if out.get("original_text") == source:
        rep.append(("OK", name, "원문 그대로 전달", "`<mark>` 없이 원문 그대로다"))
    else:
        rep.append((
            "FAIL", name, "원문 그대로 전달",
            f"값={out.get('original_text')!r}",
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
    """`_post_json` 이 보는 만큼만 흉내낸다 (status_code + headers + text + json()).

    `headers`·`text` 는 2026-09-07 에 붙었다 — MCP 는 응답을 `text/event-stream` 프레임에
    담아 주고, 거절 사유(406 의 이유)는 **본문에만** 적혀 있다.
    """

    def __init__(self, status_code: int, body, *, text: str = "",
                 content_type: str = "application/json") -> None:
        self.status_code = status_code
        self._body = body
        self.text = text
        self.headers = {"content-type": content_type}

    def json(self):
        if self._body is _NO_JSON:
            raise ValueError("not json")
        return self._body


_NO_JSON = object()


class _HttpxProxy:
    """스텝의 모듈 전역 `httpx` 를 가리는 대역 — 실제 httpx 모듈은 건드리지 않는다.

    `module.httpx.AsyncClient` 를 직접 갈아 끼우면 **같은 프로세스의 다른 점검까지**
    그 대역을 쓴다 (httpx 모듈 객체는 하나다).
    """

    def __init__(self, seen: dict):
        self._seen = seen
        self.Timeout = httpx.Timeout
        self.TimeoutException = httpx.TimeoutException
        self.ConnectError = httpx.ConnectError

    def AsyncClient(self, *args, **kwargs):  # noqa: N802 - httpx 이름 그대로
        return _RecordingClient(self._seen, *args, **kwargs)

# ─────────────────────────────────────────────────────────────
# MCP 전송 규약 — 406 을 잡는 그물 (2026-09-07)
# ─────────────────────────────────────────────────────────────
# 실환경에서 MCP 경로가 통째로 `406 Not Acceptable` 이었다. MCP 스트리머블 HTTP 서버는
# POST 본문을 읽기 **전에** Accept 헤더를 보고, `application/json` 과 `text/event-stream`
# 을 **둘 다** 열거하지 않으면 도구를 부르지도 않고 끊는다. httpx 기본값은 `Accept: */*`
# 다 — 즉 **도구를 아무리 고쳐도 닿지 않는** 상태였고, 스텝은 그것을 다른 4xx 와 같은
# 칸(`upstream_final`)에 넣어 "요청을 처리하지 못했습니다" 로만 보였다.
#
# 이 층을 보는 점검이 **하나도 없었다.** `_stub_gateway` 는 `_mcp_call` 을 통째로 대역으로
# 바꾸므로 그 아래(헤더·본문 해석)는 검사된 적이 없다 — `translated_markdown`·`stats` 가
# 유실됐던 것과 같은 형태의 공백이다. 그래서 **HTTP 경계에 대역을 꽂는다**: 스텝이 실제로
# 내보내는 헤더를 받아 보고, 서버가 SSE 프레임으로 답할 때 결과를 꺼내는지 본다.
# MCP 를 부르는 스텝과 **그 스텝이 실제로 부르는 도구**. FAQ 스텝 1 은 2026-09-07 에
# 목록에서 빠졌다 — 그 스텝의 유일한 MCP 호출이 hwpx 파싱이었고, 첨부 문서를 두 번
# 파싱하지 않기로 하면서 `_mcp_call` 자체가 없어졌다.
_MCP_STEPS = (
    ("sfr018_polish_01_policy.py", "LANG_POLICY_MCP_ID", "resolve_tone"),
    ("sfr018_polish_02_polish.py", "TEXT_GUARD_MCP_ID", "fact_issues"),
    ("sfr018_translate_01_detect.py", "LANG_POLICY_MCP_ID", "validate_direction"),
    ("sfr018_translate_02_translate.py", "TEXT_GUARD_MCP_ID", "numeric_issues"),
)

_SSE_BODY = (
    # 진행 알림이 응답보다 **먼저** 온다 — 마지막 프레임을 집으면 알림을 응답으로 읽는다.
    'event: message\n'
    'data: {"jsonrpc":"2.0","method":"notifications/progress"}\n'
    '\n'
    'event: message\n'
    'data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text",'
    '"text":"{\\"ok\\": true, \\"echo\\": 7}"}]}}\n'
    '\n'
)


class _RecordingClient:
    """`httpx.AsyncClient` 대역 — 스텝이 보낸 헤더를 기록하고 SSE 로 답한다."""

    def __init__(self, seen: dict, *args, **kwargs):
        self._seen = seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, json=None, headers=None):
        self._seen["url"] = url
        self._seen["headers"] = dict(headers or {})
        accept = (self._seen["headers"].get("Accept") or "").lower()
        if "application/json" not in accept or "text/event-stream" not in accept:
            # 실제 서버(mcp python-sdk)가 하는 판정 그대로다.
            return _FakeResponse(
                406, {"error": "Not Acceptable"},
                text="Not Acceptable: Client must accept both application/json and "
                     "text/event-stream",
            )
        return _FakeResponse(200, None, text=_SSE_BODY,
                             content_type="text/event-stream")


# ─────────────────────────────────────────────────────────────
# 글다듬이 스트리밍 전송 규약 (2026-09-09)
# ─────────────────────────────────────────────────────────────
# 서빙이 `POST /polish/stream` 으로 증분을 SSE 로 준다. 스텝은 그것을 읽어 `token` 으로
# 흘린다 — 그전에는 서빙이 다 끝난 뒤 준 **완성된 글**을 조각내 흘려서, 사용자가 기다리는
# 수십 초 동안 화면이 비어 있었다.
#
# **이 층을 보는 점검이 없다.** `_stub_gateway` 는 `_post_serving`·`_mcp_call` 만 대역으로
# 바꾸므로 `_stream_polish` 는 실제 네트워크를 때리고, 그러면 실패해서 **폴백으로 지나간다**
# — 스트리밍 경로를 한 줄도 태우지 않은 채 통과한다(MCP 406 이 넉 달을 살아남은 것과
# 같은 형태의 공백이다). 그래서 **HTTP 경계에 대역을 꽂는다.**
#
# 여기서 보는 것 넷:
#   ① Accept 에 `text/event-stream` 을 싣는가 (안 싣으면 SSE 를 안 내주는 서버가 있다)
#   ② 델타를 `token` 으로 흘리는가
#   ③ **두 번 흘리지 않는가** — 스트리밍으로 받았는데 `_stream_chunks` 로 또 흘리면
#      같은 글이 화면에 두 번 나온다(조건부로 만든 자리다)
#   ④ SSE 가 아니면 비스트리밍으로 되돌아가는가 (서빙 판본 어긋남·프록시가 SSE 를 막는 경우)
_POLISH_STREAM_SSE = (
    'data: {"type":"delta","text":"본 사업은 "}\n'
    '\n'
    ': keepalive\n'
    '\n'
    'data: {"type":"delta","text":"2026년에 완료하였습니다."}\n'
    '\n'
    'data: {"type":"done","polished_text":"본 사업은 2026년에 완료하였습니다.",'
    '"download_url":"https://genos.genon.ai/minio/temp/polished.txt",'
    '"doc_type":"mail","tone":"polite","tone_overridden":false,'
    '"chunk_count":2,"failed_chunk_count":0,'
    '"stream_diverged":false,"stream_fallback":false}\n'
    '\n'
)


class _StreamResponse:
    """`client.stream(...)` 이 돌려주는 응답 대역."""

    def __init__(self, status: int, text: str, content_type: str):
        self.status_code = status
        self.text = text
        self.headers = {"content-type": content_type}

    async def aread(self) -> bytes:
        return self.text.encode("utf-8")

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self.text.splitlines():
            yield line


class _StreamingClient:
    """`httpx.AsyncClient` 대역 — 스텝이 보낸 헤더를 기록하고 SSE(또는 JSON)로 답한다."""

    def __init__(self, seen: dict, sse: bool, sse_body: str = "", json_body: str = ""):
        self._seen = seen
        self._sse = sse
        # 단위마다 프레임이 다르다 — 글다듬이는 `delta` 하나지만 FAQ 는 항목을 열고 닫는
        # 프레임도 낸다. 본문을 대역에 박아 두면 그 단위의 판정이 **글다듬이 프레임을
        # 태우게 되어** 정작 그 단위의 계약을 보지 않는다.
        self._sse_body = sse_body or _POLISH_STREAM_SSE
        self._json_body = json_body or '{"polished_text":"x"}'

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def stream(self, method, url, json=None, headers=None):
        self._seen["method"] = method
        self._seen["url"] = url
        self._seen["headers"] = dict(headers or {})
        self._seen["payload_keys"] = sorted(json or {})
        client = self

        class _Ctx:
            async def __aenter__(self):
                if client._sse:
                    return _StreamResponse(200, client._sse_body, "text/event-stream")
                # 서빙이 스트리밍 라우트를 안 들고 있는 판본 = 평범한 JSON 이 온다.
                return _StreamResponse(200, client._json_body, "application/json")

            async def __aexit__(self, *exc_info):
                return False

        return _Ctx()


class _StreamHttpxProxy:
    """스텝의 모듈 전역 `httpx` 를 가리는 대역 (실제 httpx 모듈은 건드리지 않는다)."""

    def __init__(self, seen: dict, sse: bool, sse_body: str = "", json_body: str = ""):
        self._seen = seen
        self._sse = sse
        self._sse_body = sse_body
        self._json_body = json_body
        self.Timeout = httpx.Timeout
        self.TimeoutException = httpx.TimeoutException
        self.ConnectError = httpx.ConnectError

    def AsyncClient(self, *args, **kwargs):  # noqa: N802 - httpx 이름 그대로
        return _StreamingClient(self._seen, self._sse, self._sse_body, self._json_body)


async def _check_polish_stream_transport(rep: list) -> None:
    name = "sfr018_polish_02_polish"
    source = "본 사업은 2026년에 완료함."
    streamed_canonical = "본 사업은 2026년에 완료하였습니다."
    saved = {k: os.environ.get(k) for k in ("GENOS_URL", "GENOS_TOKEN")}
    os.environ["GENOS_URL"] = "https://genos.example"
    os.environ["GENOS_TOKEN"] = "test-token"
    try:
        guard = _load_mcp("genon_text_guard.py")

        def _by_tool(tool: str, arguments: dict):
            if tool == "diff_changes":
                return guard.tgcall_tool(
                    "diff_changes", {"source": source, "revised": streamed_canonical}
                )
            return {"issues": []}

        # ── SSE 경로
        module = _load_step(name + ".py")
        # 폴백이 **불리지 않아야** 한다는 것도 함께 본다 — 불리면 두 번 흘린다.
        _stub_gateway(module, {"polished_text": "폴백이 불렸다"}, {"__by_tool__": _by_tool})
        seen: dict = {}
        module.httpx = _StreamHttpxProxy(seen, sse=True)
        os.environ["TEXT_POLISH_SERVING_ID"] = "7"

        data = dict(_BASE_DATA)
        data["polish_source_text"] = source
        out, streamed = await _drain_with_tokens(module.run(data))

        accept = str(seen.get("headers", {}).get("Accept") or "")
        has_sse = "text/event-stream" in accept
        rep.append((
            "OK" if has_sse else "FAIL", name, "스트림 Accept",
            "`text/event-stream` — SSE 를 받겠다고 밝힌다"
            if has_sse else
            f"Accept={accept!r} — 밝히지 않으면 SSE 를 안 내주는 서버가 있다 (MCP 406 과 같은 자리)",
        ))

        url_ok = str(seen.get("url", "")).endswith("/code_serving/7/polish/stream")
        rep.append((
            "OK" if url_ok else "FAIL", name, "스트림 경로",
            f"{seen.get('url')} — `/code_serving/<id>/polish/stream` 이어야 한다",
        ))

        # ② 델타를 흘렸고 ③ 두 번 흘리지 않았는가. 두 번 흘리면 길이가 2배가 된다.
        if streamed == streamed_canonical:
            rep.append((
                "OK", name, "스트림 흘림",
                f"SSE 델타를 그대로 흘렸다 ({len(streamed)}자, 중복 없음)",
            ))
        else:
            doubled = streamed == streamed_canonical * 2
            rep.append((
                "FAIL", name, "스트림 흘림",
                "스트리밍으로 받은 뒤 `_stream_chunks` 로 **또** 흘렸다 — 같은 글이 화면에 두 번 나온다"
                if doubled else
                f"흘림 {len(streamed)}자 / 기대 {len(streamed_canonical)}자 — {streamed!r}",
            ))

        # `done` 프레임을 결과로 읽었는가. 폴백 응답(`폴백이 불렸다`)이 실렸으면 스트림을
        # 읽지 못하고 되돌아간 것이다.
        shown = str(out.get("polished_text") or "")
        used_done = "완료하였습니다" in shown and "폴백" not in shown
        rep.append((
            "OK" if used_done else "FAIL", name, "스트림 done",
            "`done` 프레임을 결과로 읽는다 (폴백을 부르지 않았다)"
            if used_done else
            f"polished_text={shown[:40]!r} — done 을 못 읽고 비스트리밍으로 되돌아갔다",
        ))

        # ── SSE 가 아닌 응답 → 되돌아가는가
        module2 = _load_step(name + ".py")
        _stub_gateway(
            module2,
            {"polished_text": streamed_canonical,
             "download_url": "https://genos.genon.ai/minio/temp/polished.txt"},
            {"__by_tool__": _by_tool},
        )
        seen2: dict = {}
        module2.httpx = _StreamHttpxProxy(seen2, sse=False)
        out2, streamed2 = await _drain_with_tokens(module2.run(dict(data)))
        fell_back = (
            str(out2.get("polished_text") or "") != ""
            and streamed2 == streamed_canonical
        )
        rep.append((
            "OK" if fell_back else "FAIL", name, "스트림 폴백",
            "SSE 가 아니면 `POST /polish` 로 되돌아가고 거기서 조각내 흘린다"
            if fell_back else
            f"흘림 {len(streamed2)}자 / payload={sorted(out2)} — 되돌아가지 못하면 "
            "서빙 판본이 어긋난 배포에서 기능이 통째로 죽는다",
        ))
        os.environ.pop("TEXT_POLISH_SERVING_ID", None)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ─────────────────────────────────────────────────────────────
# 번역·FAQ 스트리밍 전송 규약 (2026-09-09 신설)
# ─────────────────────────────────────────────────────────────
#
# **이 층을 보는 판정이 0건이었다.** `_stub_gateway` 는 `_post_serving` 만 바꾸므로
# 그대로 두면 `_stream_serving` 이 실패해 **폴백으로 지나가고 스트리밍 경로를 한 줄도
# 태우지 않는다** — 글다듬이에서 이미 겪은 공백이고(MCP 406 이 넉 달을 살아남은 것과
# 같은 형태다), 번역·FAQ 는 캔버스 배선 자체가 없어 더 조용했다.


def _sse_body(frames: list) -> str:
    """프레임 목록 → SSE 본문. **손으로 적지 않는다** — 이스케이프가 어긋나면 판정이
    프레임을 못 읽고, 그 상태는 "스트리밍을 안 했다" 와 구분되지 않는다."""
    return "".join(
        "data: " + json.dumps(frame, ensure_ascii=False) + "\n\n" for frame in frames
    )


_TRANSLATE_STREAM_TEXT = "The project was completed in 2026."
_TRANSLATE_SOURCE_TEXT = "본 사업은 2026년에 완료되었다."
_TRANSLATE_STREAM_SSE = _sse_body([
    {"type": "delta", "text": "The project "},
    {"type": "delta", "text": "was completed in 2026."},
    {
        "type": "done",
        "translated_text": _TRANSLATE_STREAM_TEXT,
        "chunk_count": 2,
        "failed_chunk_count": 0,
        "translation_error": "",
        "stream_diverged": False,
        "stream_fallback": False,
        "finalize_endpoint": "/translate/finalize",
    },
])


async def _check_translate_stream_transport(rep: list) -> None:
    """번역: SSE 로 흘리고 `finalize` 로 마무리하는가 (2026-09-09)."""
    name = "sfr018_translate_02_translate"
    keys = ("GENOS_URL", "GENOS_TOKEN", "TRANSLATION_SERVING_ID")
    saved = {k: os.environ.get(k) for k in keys}
    os.environ["GENOS_URL"] = "https://genos.example"
    os.environ["GENOS_TOKEN"] = "test-token"
    os.environ["TRANSLATION_SERVING_ID"] = "9"

    highlighted_target = "The <mark>project</mark> was completed in 2026."
    highlighted_source = "본 <mark>사업</mark>은 2026년에 완료되었다."

    def _by_path(path: str):
        if path.endswith("/translate/finalize"):
            return {
                "original_text": _TRANSLATE_SOURCE_TEXT,
                "translated_text": _TRANSLATE_STREAM_TEXT,
                "markdown_highlighted": highlighted_target,
                "source_markdown_highlighted": highlighted_source,
                "glossary": {"term_map": {"사업": "project"}, "compliance": 1.0},
                "download_url": "https://genos.genon.ai/minio/temp/translated.txt",
            }
        # 폴백 경로. 이 값이 화면에 보이면 스트리밍을 못 읽고 되돌아간 것이다.
        return {
            "markdown": "폴백이 불렸다",
            "stats": {"unit_count": 1, "failed_unit_count": 0},
        }

    try:
        module = _load_step(name + ".py")
        _stub_gateway(module, {"__by_path__": _by_path}, {"issues": []})
        seen: dict = {}
        module.httpx = _StreamHttpxProxy(seen, sse=True, sse_body=_TRANSLATE_STREAM_SSE)

        data = dict(_BASE_DATA)
        data.update({
            "translate_source_text": _TRANSLATE_SOURCE_TEXT,
            "translate_target_lang": "en",
            "translate_source_lang": "ko",
        })
        out, streamed = await _drain_with_tokens(module.run(data))

        accept = str(seen.get("headers", {}).get("Accept") or "")
        has_sse = "text/event-stream" in accept
        rep.append((
            "OK" if has_sse else "FAIL", name, "스트림 Accept",
            "`text/event-stream` — SSE 를 받겠다고 밝힌다" if has_sse else
            f"Accept={accept!r} — 밝히지 않으면 SSE 를 안 내주는 서버가 있다 (MCP 406 과 같은 자리)",
        ))

        url_ok = str(seen.get("url", "")).endswith("/code_serving/9/translate/stream")
        rep.append((
            "OK" if url_ok else "FAIL", name, "스트림 경로",
            f"{seen.get('url')} — `/code_serving/<id>/translate/stream` 이어야 한다",
        ))

        # 흘린 것이 **정본**이고 **한 번만** 나갔는가. 두 번 흘리면 길이가 2배가 된다.
        if streamed == _TRANSLATE_STREAM_TEXT:
            rep.append((
                "OK", name, "스트림 흘림",
                f"SSE 델타를 정본 그대로 흘렸다 ({len(streamed)}자, 중복 없음)",
            ))
        else:
            doubled = streamed == _TRANSLATE_STREAM_TEXT * 2
            copy_leaked = "<mark>" in streamed
            rep.append((
                "FAIL", name, "스트림 흘림",
                "스트리밍으로 받은 뒤 `_stream_chunks` 로 **또** 흘렸다 — 같은 글이 두 번 나온다"
                if doubled else
                "표시용 사본(`<mark>`)을 흘렸다 — 하이라이트가 스트리밍 중에 먼저 나타난다"
                if copy_leaked else
                f"흘림 {len(streamed)}자 / 기대 {len(_TRANSLATE_STREAM_TEXT)}자 — {streamed!r}",
            ))

        # `finalize` 를 실제로 불렀는가 = 화면이 **양쪽 사본**과 링크를 받았는가.
        # 안 불렀으면 좌우 하이라이트가 통째로 사라지는데 오류로는 드러나지 않는다.
        shown = str(out.get("translated_text") or "")
        source_shown = str(out.get("original_text") or "")
        link = str(out.get("download_url") or "")
        finalized = (
            shown == highlighted_target
            and source_shown == highlighted_source
            and link.endswith("translated.txt")
        )
        rep.append((
            "OK" if finalized else "FAIL", name, "스트림 마무리",
            "`/translate/finalize` 로 양쪽 사본·링크를 받아 화면에 실었다" if finalized else
            "폴백이 불렸다 — 스트림 결과를 못 읽었다" if "폴백" in shown else
            f"사본/링크가 안 실렸다 — translated={shown[:40]!r} link={link!r}",
        ))

        # ── SSE 가 아닌 응답 = 스트리밍 라우트가 없는 판본. 되돌아가야 한다.
        module2 = _load_step(name + ".py")
        _stub_gateway(module2, {"__by_path__": _by_path}, {"issues": []})
        module2.httpx = _StreamHttpxProxy({}, sse=False, json_body='{"markdown":"x"}')
        out2, _streamed2 = await _drain_with_tokens(module2.run(dict(data)))
        fell_back = "폴백이 불렸다" in str(out2.get("translated_text") or "")
        rep.append((
            "OK" if fell_back else "FAIL", name, "스트림 미지원 폴백",
            "SSE 가 아니면 `/translate/markdown` 으로 되돌아간다 — 정본 서빙 판본에서도 돈다"
            if fell_back else
            "되돌아가지 않았다 — 스트리밍 라우트가 없는 배포에서 기능이 통째로 죽는다",
        ))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# 흘린 조각을 이어 붙인 것 == `done` 의 `markdown`. **이 등식이 요점이다** — FAQ 화면
# 형식이 서빙의 조각 함수(`_display_text`)와 최종 조립(`formatting._render`) 두 곳에
# 있는데, 갈리면 스트리밍으로 본 화면과 결과가 달라지고 오류로는 드러나지 않는다.
_FAQ_STREAM_TEXT = (
    "**Q1. 수수료는?**" + "\n\n" + "연 2.5%입니다." + "\n\n" + "> 근거: 제5조"
)
_FAQ_ITEMS = [{"question": "수수료는?", "answer": "연 2.5%입니다.", "evidence": "제5조"}]
_FAQ_STREAM_SSE = _sse_body([
    {
        "type": "item_open", "index": 0, "question": "수수료는?",
        "text": "**Q1. 수수료는?**" + "\n\n",
    },
    {"type": "delta", "index": 0, "text": "연 2.5%입니다."},
    {
        "type": "item_close", "index": 0, "evidence": "제5조",
        "text": "\n\n" + "> 근거: 제5조",
    },
    {
        "type": "done",
        "faq_items": _FAQ_ITEMS,
        "items": _FAQ_ITEMS,
        "count": 1,
        "requested_count": 1,
        "rejected": {"schema": 0, "ungrounded": 0, "duplicate": 0},
        "markdown": _FAQ_STREAM_TEXT,
        "download_url": "https://genos.genon.ai/minio/temp/faq.txt",
        "download_ready": True,
        "stream_fallback": False,
    },
])


async def _check_faq_stream_transport(rep: list) -> None:
    """FAQ: 항목 프레임을 SSE 로 흘리는가 (2026-09-09).

    **FAQ 스트리밍은 2026-09-02 에 되살아났는데 그물이 따라오지 않아 그때까지 한 번도
    검사된 적이 없었다** — 점검이 이 스텝을 `_NO_STREAM_STEPS` 로 분류하고 있었다.
    """
    name = "sfr018_faq_02_generate"
    keys = ("GENOS_URL", "GENOS_TOKEN", "FAQ_SERVING_ID")
    saved = {k: os.environ.get(k) for k in keys}
    os.environ["GENOS_URL"] = "https://genos.example"
    os.environ["GENOS_TOKEN"] = "test-token"
    os.environ["FAQ_SERVING_ID"] = "11"

    fallback_items = [{"question": "폴백이 불렸다", "answer": "x", "evidence": "y"}]
    fallback_body = {
        "faq_items": fallback_items,
        "items": fallback_items,
        "count": 1,
        "requested_count": 1,
        "rejected": {"schema": 0, "ungrounded": 0, "duplicate": 0},
        "markdown": "**Q1. 폴백이 불렸다**",
        "download_ready": True,
    }
    try:
        module = _load_step(name + ".py")
        _stub_gateway(module, fallback_body, {"issues": []})
        seen: dict = {}
        module.httpx = _StreamHttpxProxy(seen, sse=True, sse_body=_FAQ_STREAM_SSE)

        data = dict(_BASE_DATA)
        data.update({
            "faq_source_text": "수수료는 연 2.5% 이다. (제5조)",
            "faq_count": 1,
        })
        out, streamed = await _drain_with_tokens(module.run(data))

        accept = str(seen.get("headers", {}).get("Accept") or "")
        has_sse = "text/event-stream" in accept
        rep.append((
            "OK" if has_sse else "FAIL", name, "스트림 Accept",
            "`text/event-stream` — SSE 를 받겠다고 밝힌다" if has_sse else
            f"Accept={accept!r} — 밝히지 않으면 SSE 를 안 내주는 서버가 있다",
        ))

        url_ok = str(seen.get("url", "")).endswith("/code_serving/11/generate/stream")
        rep.append((
            "OK" if url_ok else "FAIL", name, "스트림 경로",
            f"{seen.get('url')} — `/code_serving/<id>/generate/stream` 이어야 한다",
        ))

        # **등식**: 흘린 조각을 이어 붙이면 최종 마크다운과 같다.
        if streamed == _FAQ_STREAM_TEXT:
            rep.append((
                "OK", name, "스트림 흘림",
                f"항목 프레임을 이어 붙인 것이 최종 마크다운과 같다 ({len(streamed)}자)",
            ))
        else:
            doubled = streamed == _FAQ_STREAM_TEXT * 2
            rep.append((
                "FAIL", name, "스트림 흘림",
                "스트리밍으로 받은 뒤 `_stream_chunks` 로 **또** 흘렸다 — 목록이 두 번 나온다"
                if doubled else
                f"흘림 {len(streamed)}자 / 기대 {len(_FAQ_STREAM_TEXT)}자 — {streamed!r}",
            ))

        items = out.get("faq_items") or []
        first_q = str((items[0] or {}).get("question") or "") if items else ""
        used_stream = first_q == "수수료는?"
        rep.append((
            "OK" if used_stream else "FAIL", name, "스트림 결과 채택",
            "`done` 프레임의 문답 목록을 payload 로 냈다" if used_stream else
            f"폴백 결과가 실렸다 — 스트림을 못 읽었다 (question={first_q!r})",
        ))

        # ── SSE 가 아닌 응답 → 폴백
        module2 = _load_step(name + ".py")
        _stub_gateway(module2, fallback_body, {"issues": []})
        module2.httpx = _StreamHttpxProxy({}, sse=False, json_body='{"count":0}')
        out2, _streamed2 = await _drain_with_tokens(module2.run(dict(data)))
        items2 = out2.get("faq_items") or []
        fell_back = bool(items2) and "폴백" in str((items2[0] or {}).get("question") or "")
        rep.append((
            "OK" if fell_back else "FAIL", name, "스트림 미지원 폴백",
            "SSE 가 아니면 `/generate` 로 되돌아간다 — 정본 서빙 판본에서도 돈다"
            if fell_back else
            "되돌아가지 않았다 — 스트리밍 라우트가 없는 배포에서 기능이 통째로 죽는다",
        ))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def _check_mcp_transport(rep: list) -> None:
    saved = {k: os.environ.get(k) for k in ("GENOS_URL", "GENOS_TOKEN")}
    os.environ["GENOS_URL"] = "https://genos.example"
    os.environ["GENOS_TOKEN"] = "test-token"
    try:
        for filename, env_name, tool in _MCP_STEPS:
            name = filename[:-3]
            os.environ[env_name] = "13"
            module = _load_step(filename)
            seen: dict = {}
            module.httpx = _HttpxProxy(seen)
            body, failure = await module._mcp_call(
                env_name, tool, {"x": 1}, read_timeout=5.0
            )

            accept = (seen.get("headers", {}).get("Accept") or "")
            has_both = "application/json" in accept and "text/event-stream" in accept
            rep.append((
                "OK" if has_both else "FAIL", name, "MCP Accept",
                f"Accept={accept!r} — json·event-stream 을 둘 다 열거해야 한다 "
                "(아니면 서버가 도구를 부르지도 않고 406 이다)"
                if not has_both else
                "`application/json, text/event-stream` — 406 게이트를 지난다",
            ))

            url_ok = str(seen.get("url", "")).endswith("/api/gateway/mcp/13/mcp")
            rep.append((
                "OK" if url_ok else "FAIL", name, "MCP 경로",
                f"{seen.get('url')} — `{{GENOS_URL}}/api/gateway/mcp/<id>/mcp` 여야 한다 (§H)",
            ))

            decoded = failure is None and isinstance(body, dict) and body.get("echo") == 7
            rep.append((
                "OK" if decoded else "FAIL", name, "MCP SSE 해석",
                f"failure={failure} body={body} — 서버가 SSE 프레임으로 답하면 그 안의 "
                "JSON-RPC 응답을 꺼내야 한다 (못 꺼내면 도구는 돌았는데 결과만 사라진다)"
                if not decoded else
                "`text/event-stream` 프레임에서 결과를 꺼낸다 (진행 알림을 응답으로 읽지 않는다)",
            ))
            os.environ.pop(env_name, None)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


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
            ("00020003(그 외) 500", _FakeResponse(500, {"error_code": "ERR-03-00020003"}),
             "upstream_final"),
            ("00020002(실행 실패) 500", _FakeResponse(500, {"error_code": "ERR-03-00020002"}),
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
            _FakeResponse(500, {"error_code": "ERR-03-00020003"})
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
        _check_mcp_transport,
        _check_polish_stream_transport,
        _check_translate_stream_transport,
        _check_faq_stream_transport,
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
