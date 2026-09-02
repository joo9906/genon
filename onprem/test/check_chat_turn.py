"""SFR-006 대화 한 턴 계약 점검 — LLM·Redis·GenOS·서버 없이 돌린다.

`python onprem/test/check_chat_turn.py`

## 무엇을 보나

대화 한 턴은 이제 **워크플로우 파이썬 스텝 3개**로 나뉘어 있고, 각 스텝은 코드서빙의
`/chat/*` 을 부른다. 이 점검은 **그 체인을 통째로** 돌린다:

```
sfr006_01_context.py ──▶ POST /chat/context ──┐
sfr006_02_extract.py ──▶ POST /chat/extract ──┤ chat_api.install(app)
sfr006_03_commit.py  ──▶ POST /chat/commit  ──┘
```

스텝 사이는 `data` dict 하나로만 이어지고(§I), 마지막 스텝만 async generator 로
`token`…`result` 를 낸다. 못 박는 것:

- 스트리밍 규약: `token` 이벤트가 여러 번, `result` 이벤트가 **정확히 마지막 1회**
- 값 추출 → 화이트리스트 기각 → 세션 누적
- 본문 블록 추가/삭제, **삭제 번호는 추가 이전 목록 기준**
- 다음 턴이 이전 턴의 값을 이어받는다 (세션 왕복)
- 오류(템플릿 없음)도 `result` 로 끝나고 `data["error"]` 를 담는다
- **스텝 경계가 값을 잃지 않는다** — 이 재배치로 새로 생긴 위험이라 여기서 지킨다.
  예전에는 한 함수 안의 지역 변수였던 것이 지금은 HTTP 를 두 번 건넌다.

## 서버를 띄우지 않는 이유

스텝의 `httpx` 를 **ASGI 전송으로 갈아 끼운다.** 그래서 URL 조립(`/api/gateway`
prefix·serving id)·재시도·상태코드 분류·pydantic 검증·`ApiError`→HTTP 변환이 전부
실제 코드로 돈다. 포트를 열지 않을 뿐 경로는 진짜다.

게이트웨이 앞단(`{GENOS_URL}/api/gateway/code_serving/{id}`)만 잘라내고 나머지 경로를
앱에 넘긴다 — 그 앞단은 GenOS 가 라우팅하는 구간이라 우리 앱에 존재하지 않는다.

LLM 은 대본을 돌려주는 가짜로 갈아 끼운다 — 무엇을 보내는지 검증하려는 것이 아니라,
**LLM 응답이 주어졌을 때 코드가 어떻게 판정하는지**가 이 점검의 대상이다.
(판정 책임이 코드에 있다는 것이 006 의 설계 전제다 — 루트 CLAUDE.md §5.)

## 여기 있는 이유

`check_api_contract.py` 와 같다. 가짜 LLM·가짜 Redis 주입은 배포 단위 **바깥**에서만
한다 — 운영 코드에 테스트 분기를 만들지 않기 위해서다(`onprem/` 규칙).
"""

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import types
import zipfile

_ONPREM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UNIT = os.path.join(_ONPREM, "codeserving", "SFR-006_template_fill")
_WORKFLOW = os.path.join(_ONPREM, "workflow")
sys.path.insert(0, _UNIT)

_TEMPLATE_DIR = tempfile.mkdtemp(prefix="sfr006_chat_")
os.environ["TEMPLATE_FILL_TEMPLATE_DIR"] = _TEMPLATE_DIR

# 스텝이 게이트웨이 URL 을 조립하는 데 쓴다. 값 자체는 ASGI 전송이 흡수하지만,
# **비어 있으면 스텝이 CONFIG_MISSING 으로 즉시 끝나므로** 반드시 있어야 한다.
os.environ["GENOS_URL"] = "http://genos.invalid"
os.environ["TEMPLATE_FILL_SERVING_ID"] = "sfr006"
os.environ.setdefault("GENOS_TOKEN", "test-token")

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"

_SECTION = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="{hp}">
  <hp:p paraPrIDRef="1">
    <hp:run charPrIDRef="1"><hp:secPr/></hp:run>
    <hp:run charPrIDRef="1"><hp:t>제 목 : {{'제 목', 고딕, 16pt}}</hp:t></hp:run>
  </hp:p>
  <hp:p paraPrIDRef="3"><hp:run charPrIDRef="3"><hp:t>주요 내용: {{'주요 내용', 휴먼명조, 11pt}}</hp:t></hp:run></hp:p>
</hs:sec>
""".format(hp=HP)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def setex(self, key, ttl, value):
        self.store[key] = value

    async def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)

    async def ping(self):
        return True


class LlmScript:
    """`llm_call_async(system, user)` 자리에 꽂히는 가짜. 대본을 순서대로 돌려준다."""

    def __init__(self) -> None:
        self.queue: list = []
        self.calls: list = []

    def push(self, payload) -> None:
        self.queue.append(json.dumps(payload, ensure_ascii=False))

    async def __call__(self, system_prompt, user_prompt, **kwargs):
        self.calls.append((system_prompt, user_prompt))
        content = self.queue.pop(0) if self.queue else "{}"
        return types.SimpleNamespace(
            ok=True, content=content, error_type="", is_transport_error=False
        )


def write_template(name: str) -> None:
    path = os.path.join(_TEMPLATE_DIR, f"{name}.hwpx")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("Contents/section0.xml", _SECTION.encode("utf-8"))
        zf.writestr("Contents/header.xml", '<?xml version="1.0" encoding="UTF-8"?><h/>')


# ─────────────────────────────────────────────────────────────
# 코드서빙 앱 — 진짜 라우트를 올리고 ASGI 로만 부른다
# ─────────────────────────────────────────────────────────────
def build_app(script: LlmScript):
    """`chat_api` 를 실제 FastAPI 앱에 붙인다.

    `main.py` 를 통째로 import 하지 않는 이유: 그쪽은 템플릿 볼륨·PDF 변환기까지 들고
    오고, 이 점검의 대상은 대화 3경로뿐이다. **배선 자체(`install_chat_api`)는 여기서
    쓰는 것과 `main.py` 가 부르는 것이 같은 함수**라, 배선이 빠지면 여기서도 죽는다.
    """
    from fastapi import FastAPI

    from template_fill.api_errors import install as install_error_handler
    from template_fill.chat_api import install as install_chat_api
    from template_fill import chat_api

    # LLM 은 chat_api 가 `from .llm import llm_call_async` 로 **이름을 복사**해 갔다.
    # 원본(`llm.py`)만 갈아 끼우면 복사본이 계속 쓰인다.
    chat_api.llm_call_async = script
    # **문서 자동 채움도 자기 사본을 들고 있다** (2026-08-31). 여기를 안 꽂으면 그 경로만
    # 진짜 게이트웨이를 부르려 들고, 실패가 fail-open 이라 **점검이 조용히 통과한다** —
    # 실제로 그렇게 한 번 통과했다(자동 채움이 안 돌았는데 값은 채워져 있었다: 대본을
    # 발화 추출이 먹었기 때문이다).
    from template_fill import doc_prefill

    doc_prefill.llm_call_async = script

    app = FastAPI()
    install_error_handler(app)
    install_chat_api(app)
    return app


class _RoutedClient:
    """스텝이 만드는 `httpx.AsyncClient` 자리에 들어가 ASGI 앱으로 보낸다."""

    def __init__(self, app, **_kwargs) -> None:
        import httpx

        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://serving.invalid"
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        await self._client.aclose()

    @staticmethod
    def _strip_gateway(url: str) -> str:
        """`…/api/gateway/code_serving/{id}/chat/commit` → `/chat/commit`.

        앞단은 GenOS 게이트웨이가 라우팅하는 구간이라 앱에는 없다. 잘라내지 않으면
        전부 404 가 되어 "코드가 틀렸다" 로 보인다.
        """
        marker = "/code_serving/"
        if marker in url:
            tail = url.split(marker, 1)[1]
            return "/" + tail.split("/", 1)[1] if "/" in tail else "/"
        return url

    async def post(self, url, *, json=None, headers=None):
        return await self._client.post(self._strip_gateway(url), json=json, headers=headers)

    async def get(self, url, *, headers=None):
        return await self._client.get(self._strip_gateway(url), headers=headers)


def load_step(filename: str, app):
    """워크플로우 스텝을 파일에서 그대로 불러오고 `httpx` 만 갈아 끼운다.

    스텝은 캔버스에 붙는 **자기완결 코드 뭉치**라 패키지가 아니다 — 경로로 로드한다.
    `httpx` 를 통째로 대역으로 바꾸므로 스텝 코드는 한 줄도 수정하지 않는다.
    """
    import httpx as real_httpx

    path = os.path.join(_WORKFLOW, filename)
    spec = importlib.util.spec_from_file_location(filename[:-3], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module.httpx = types.SimpleNamespace(
        AsyncClient=lambda **kwargs: _RoutedClient(app, **kwargs),
        Timeout=real_httpx.Timeout,
        TimeoutException=real_httpx.TimeoutException,
        ConnectError=real_httpx.ConnectError,
    )
    return module


def install_fakes():
    """가짜 Redis·LLM 을 꽂고 (스텝 3개, 대본) 을 돌려준다.

    **import 보다 먼저 꽂아야 한다.** `session_store`·`template_index` 는
    `from .redis_client import resolve_client` 로 **이름을 복사**하므로, 모듈이 로드된
    뒤에 `redis_client` 쪽만 갈아 끼우면 이미 복사된 원본이 계속 쓰인다
    (그러면 Redis 접속 실패로 세션이 매 턴 초기화돼 점검이 통째로 무의미해진다).
    """
    from template_fill import redis_client

    fake_redis = FakeRedis()
    redis_client.resolve_client = lambda: fake_redis

    from template_fill import session_store, template_index

    session_store.resolve_client = redis_client.resolve_client
    template_index.resolve_client = redis_client.resolve_client

    # 상태를 **세션에서 직접** 읽는 창구. 2026-08-28 에 payload 가 화면용 값만 담게
    # 되면서 `field_values`·`blocks` 가 응답에서 빠졌는데, 이 점검이 보려던 것은
    # 애초에 화면 표시가 아니라 **상태 전이**다(값이 누적되나·블록이 순서대로 바뀌나).
    # 그래서 payload 대신 저장된 세션을 읽는다 — 오히려 정본을 보는 셈이다.
    global _READ_SESSION
    _READ_SESSION = session_store.load_session

    script = LlmScript()
    app = build_app(script)
    steps = [
        load_step("sfr006_01_context.py", app),
        load_step("sfr006_02_extract.py", app),
        load_step("sfr006_03_commit.py", app),
    ]
    return steps, script


_READ_SESSION = None


def read_session(session_id: str) -> dict:
    """저장된 세션 상태 — `{template_id, values, raw_values, blocks}`."""
    return asyncio.run(_READ_SESSION(session_id))


async def _run_chain(steps, data: dict) -> tuple:
    """스텝 1 → 2 → 3. 마지막만 generator 다 (§D.1).

    **중간 `data` 도 함께 돌려준다** (2026-08-28). 마지막 스텝이 payload 를 화면값만으로
    새로 조립하면서, 스텝 사이 전달값(`block_styles` 등)은 최종 응답에 없다 — 그 값이
    다음 스텝에 닿는지는 여기서 봐야 한다.
    """
    handoff = await steps[0].run(data)
    handoff = await steps[1].run(handoff)
    events = [event async for event in steps[2].run(handoff)]
    result = next((e["data"] for e in events if e.get("event") == "result"), None)
    return events, result, handoff


def run_turn(
    steps, question: str, session_id: str, template_id: str, uploaded: str = ""
) -> tuple:
    """한 턴(스텝 3개)을 끝까지 돌리고 (이벤트 목록, result data) 를 돌려준다.

    `uploaded` 는 캔버스 첨부(`genosUploaded`) — 전처리기 산출물 자리다. 채우면 스텝 1 이
    `/chat/prefill` 을 이어 부른다 (2026-08-31).
    """
    variables = {"template_fill_template_id": template_id}
    if uploaded:
        variables["genosUploaded"] = uploaded
    data = {
        "question": question,
        "genos_state": {"session_id": session_id, "trace_id": "trace-1"},
        "overrideConfig": {"vars": variables},
    }
    return asyncio.run(_run_chain(steps, data))


class Report:
    def __init__(self) -> None:
        self.failures: list = []
        self.checks = 0

    def expect(self, condition: bool, label: str, detail="") -> None:
        self.checks += 1
        if condition:
            print(f"[OK  ] {label}")
            return
        self.failures.append(label)
        print(f"[FAIL] {label}")
        if detail:
            for line in str(detail).splitlines()[:6]:
                print(f"        {line}")


def main() -> int:
    rep = Report()
    steps, script = install_fakes()
    write_template("주간보고")

    # ── 1턴: 값 추출 + 화이트리스트 기각 ──
    script.push(
        {
            "updates": {"제 목": "8월 첫째 주 보고", "없는항목": "버려져야 함"},
            "clears": [],
        }
    )
    events, result, handoff = run_turn(steps, "제목은 8월 첫째 주 보고야", "s1", "주간보고")

    rep.expect(result is not None, "result 이벤트가 있다")
    rep.expect(
        events and events[-1].get("event") == "result",
        "result 가 마지막 이벤트다 (가이드 5.2)",
        [e.get("event") for e in events[-3:]],
    )
    rep.expect(
        sum(1 for e in events if e.get("event") == "result") == 1,
        "result 는 정확히 한 번만 나온다",
    )
    rep.expect(
        any(e.get("event") == "token" for e in events),
        "token 스트리밍이 있다",
    )
    # payload 에 **화면 밖 값이 새지 않는가** (2026-08-28). `{**data}` 를 쓰면 앞 스텝이
    # 넣은 `field_names`·`block_styles`·`fields_updated` 가 전부 프론트로 간다.
    allowed = {"genos_state", "session_id", "template_id",
               "text", "ready_for_download", "document_markdown", "error"}
    leaked = sorted(set(result) - allowed)
    rep.expect(not leaked, "화면 밖 값이 새지 않는다", leaked)

    # 상태는 **세션**이 정본이다 (payload 는 화면용 값만 담는다, 2026-08-28)
    state = read_session("s1")
    rep.expect(state.get("values") == {"제 목": "8월 첫째 주 보고"}, "값이 누적된다", state.get("values"))
    # 기각은 payload 가 아니라 **안내문**이 말한다 (2026-08-28) — 감추면 사용자가
    # 반영된 줄 알고 문서를 받는다. 그 문장이 사라지면 여기서 잡힌다.
    rep.expect("없는항목" in str(result.get("text") or ""),
               "템플릿에 없는 항목은 기각", str(result.get("text") or "")[:120])
    rep.expect(result.get("ready_for_download") is False, "미입력이 남으면 ready=false", result.get("fields_missing"))
    # 스텝 사이 전달값이라 최종 payload 에는 없다 — **다음 스텝에 닿는지**를 본다.
    rep.expect(
        set(handoff.get("block_styles") or []) == {"제 목", "주요 내용"},
        "블록 서식 목록이 다음 스텝에 닿는다",
        result.get("block_styles"),
    )
    # 스텝 1이 확정한 템플릿 id 가 마지막까지 살아 있어야 다운로드 버튼이 같은 문서를 받는다
    rep.expect(
        result.get("template_id") == "주간보고",
        "스텝 1이 확정한 template_id 가 result 까지 이어진다",
        result.get("template_id"),
    )

    # ── 2턴: 이전 값 유지 + 본문 블록 추가 ──
    script.push(
        {
            "updates": {"주요 내용": "핵심 요약"},
            "blocks": [
                {"style_ref": "제 목", "text": "1. 추진 배경"},
                {"style_ref": "주요 내용", "text": "전사 차원의 과제를 재정렬하였습니다."},
            ],
        }
    )
    _, result, handoff = run_turn(steps, "주요 내용은 핵심 요약. 아래에 배경도 넣어줘", "s1", "주간보고")

    state = read_session("s1")
    rep.expect(
        state.get("values", {}).get("제 목") == "8월 첫째 주 보고",
        "이전 턴 값이 세션으로 이어진다",
        state.get("values"),
    )
    rep.expect(len(state.get("blocks") or []) == 2, "본문 블록이 추가된다", state.get("blocks"))
    rep.expect("본문에 2개 문단을 추가했습니다" in str(result.get("text") or ""),
               "이번 턴 추가를 안내문이 말한다", str(result.get("text") or "")[:120])
    rep.expect(result.get("ready_for_download") is True, "항목이 다 차면 ready=true", result.get("fields_missing"))
    rep.expect(
        "1. 추진 배경" in (result.get("document_markdown") or ""),
        "대화 미리보기에 블록이 보인다",
        result.get("document_markdown"),
    )
    rep.expect(
        "본문 추가 내용" in (result.get("text") or ""),
        "답변에 본문 추가 목록이 번호로 표시된다",
        result.get("text"),
    )

    # ── 3턴: 삭제 번호는 '추가 이전' 목록 기준 ──
    script.push({"blocks": [{"style_ref": "제 목", "text": "2. 기대 효과"}], "block_clears": [1]})
    _, result, handoff = run_turn(steps, "1번 빼고 기대 효과 넣어줘", "s1", "주간보고")

    state = read_session("s1")
    texts = [b["text"] for b in (state.get("blocks") or [])]
    rep.expect(
        texts == ["전사 차원의 과제를 재정렬하였습니다.", "2. 기대 효과"],
        "삭제(1번)를 먼저 하고 추가를 나중에 한다",
        texts,
    )
    # 삭제 건수는 payload 에서 뺐다 — 안내문이 번호를 붙여 말한다. 그 문장을 본다.
    # 삭제 건수는 payload 에서 뺐다 (2026-08-28) — `chat_reply` 가 문장으로 말한다.
    # 그 문장이 사라지면 사용자는 자기가 지운 문단이 실제로 빠졌는지 알 수 없다.
    rep.expect(
        "본문에서 1개 문단을 뺐습니다" in str(result.get("text") or ""),
        "이번 턴 삭제를 안내문이 말한다",
        str(result.get("text") or "")[:120],
    )

    # ── 오류 경로: 템플릿 없음 ──
    events, result, handoff = run_turn(steps, "아무 말", "s3", "없는템플릿")
    rep.expect(
        events and events[-1].get("event") == "result" and result.get("error"),
        "오류도 result 로 끝나고 error 를 담는다 (가이드 3.9.6)",
        result.get("error") if result else None,
    )
    rep.expect(
        (result.get("error") or {}).get("error_code", "").startswith("02-"),
        "워크플로우 영역코드(02)를 쓴다",
        result.get("error"),
    )
    rep.expect(
        any(e.get("event") == "token" for e in events),
        "오류도 사용자에게 스트리밍된다 (중간 스텝은 화면에 말하지 않는다)",
        [e.get("event") for e in events],
    )

    # ── 오류 경로: Gateway 설정 부재 (2026-08-14 추가) ──
    #
    # `llm.py` 는 설정이 비면 `LlmResult(error_type="CONFIG_MISSING")` 를 돌려준다.
    # 그런데 `is_transport_error` 는 False 라, 예전에는 `chat_api` 가 이것을 실행 실패
    # (`ERR_CHAT_UPSTREAM_EXECUTION`, 00020002, **retryable=True**)로 뭉쳤다.
    # 환경변수를 안 넣은 배포 실수라 몇 번을 다시 눌러도 같은 자리에서 실패하는데
    # "잠시 후 다시 시도해 주세요" 가 나갔고, 로그의 error_type 도 LLM 실패와 같았다.
    #
    # **끝까지 태운다** — 서빙에서 갈라도 스텝이 되돌리면 소용없기 때문이다
    # (같은 종류의 경계 유실은 `check_workflow_run._check_upstream_final` 이 9개 스텝
    # 전부를 본다).
    async def _config_missing(_system, _user, **_kwargs):
        return types.SimpleNamespace(
            ok=False, content="", error_type="CONFIG_MISSING", is_transport_error=False
        )

    # ── 업로드 문서로 알아서 채운다 (2026-08-31) ──────────────────────────
    #
    # 요구 변경: 채팅 시작 시 문서를 올리면 그 내용으로 빈 항목을 채운다. 세 가지를 본다 —
    # (1) 실제로 채워지나, (2) **같은 턴 사용자 발화가 이기나**, (3) 다음 턴에 같은 문서가
    # 다시 실려 와도 **지운 값을 되살리지 않나**.
    document = "\n".join([
        "<doc>",
        "# 사업 개요",
        "제 목 : 통합 플랫폼 구축 사업",
        "주요 내용: 사내 문서 자동화 고도화",
        "</doc>",
    ])
    script.push({"updates": {"제 목": "문서에서 읽은 제목", "주요 내용": "문서에서 읽은 내용"}})
    script.push({"updates": {"제 목": "사용자가 말한 제목"}})
    calls_before = len(script.calls)
    _, result, _ = run_turn(steps, "제목은 사용자가 말한 제목이야", "s5", "주간보고", document)

    rep.expect(
        len(script.calls) - calls_before == 2,
        "문서가 오면 자동 채움과 발화 추출이 각각 한 번 돈다",
        f"{len(script.calls) - calls_before}회",
    )
    prefill_prompt = script.calls[calls_before][1] if len(script.calls) > calls_before else ""
    rep.expect(
        "통합 플랫폼 구축 사업" in prefill_prompt,
        "문서 본문이 자동 채움 프롬프트에 실린다",
        prefill_prompt[:120],
    )
    rep.expect(
        "제목은 사용자가 말한 제목이야" not in prefill_prompt,
        "발화는 자동 채움 프롬프트에 섞이지 않는다 (프롬프트가 다르다)",
    )

    state = read_session("s5")
    rep.expect(
        state.get("values", {}).get("주요 내용") == "문서에서 읽은 내용",
        "문서에서 읽은 값이 빈 항목에 들어간다",
        state.get("values"),
    )
    rep.expect(
        state.get("values", {}).get("제 목") == "사용자가 말한 제목",
        "같은 턴 사용자 발화가 문서 값을 이긴다 (덮어쓰기 순서)",
        state.get("values"),
    )
    rep.expect(
        len(state.get("source_doc_hashes") or []) == 1,
        "이미 태운 문서의 표식이 세션에 남는다",
        state.get("source_doc_hashes"),
    )
    # 채운 값을 **답변에 나열한다.** 006 에는 값의 진위를 대조하는 층이 없어서(요구 확정)
    # 사용자가 그 자리에서 확인·수정하는 것이 유일한 방어선이다. 건수만 말하면 사용자는
    # 문서를 열어 하나하나 대조해야 한다.
    reply = str((result or {}).get("text") or "")
    rep.expect("올려주신 문서에서" in reply, "문서에서 채웠다는 사실을 답변이 말한다", reply[:160])
    rep.expect("문서에서 읽은 내용" in reply, "채운 값을 답변에 나열한다", reply[:200])

    # 2턴: **같은 문서가 다시 실려 온다** (캔버스가 변수를 유지하는 배선). 여기서 문서를
    # 또 태우면 방금 지운 값을 우리가 되살린다 — 오류가 나지 않아 제보로만 드러난다.
    script.push({"updates": {}, "clears": ["주요 내용"]})
    calls_before = len(script.calls)
    run_turn(steps, "주요 내용은 비워줘", "s5", "주간보고", document)
    rep.expect(
        len(script.calls) - calls_before == 1,
        "이미 태운 문서는 다음 턴에 다시 태우지 않는다",
        f"{len(script.calls) - calls_before}회 — 자동 채움이 또 돌았다",
    )
    state = read_session("s5")
    rep.expect(
        "주요 내용" not in state.get("values", {}),
        "지운 값이 문서 자동 채움으로 되살아나지 않는다",
        state.get("values"),
    )

    # **표식이 유일한 방어선인 경우.** 위 판정은 "값이 있으니 대화가 시작됐다" 로도 막히지만,
    # 문서에 항목 값이 하나도 없었으면(정상 답이다) 값이 0개라 그 판정이 걸리지 않는다.
    # 그때 표식이 없으면 매 턴 같은 문서로 LLM 을 다시 부른다 — 비용만 들고 결과는 같다.
    script.push({"updates": {}})   # 자동 채움: 문서에 항목 값이 없다
    script.push({"updates": {}})   # 발화 추출: 값 없는 인사말
    run_turn(steps, "안녕하세요", "s6", "주간보고", document)
    calls_before = len(script.calls)
    script.push({"updates": {}})
    run_turn(steps, "다시 안녕하세요", "s6", "주간보고", document)
    rep.expect(
        len(script.calls) - calls_before == 1,
        "값을 못 뽑은 문서도 다시 태우지 않는다 (표식이 유일한 방어선인 경우)",
        f"{len(script.calls) - calls_before}회 — 같은 문서로 LLM 을 또 불렀다",
    )

    # ── 대화 **중간에도** 올릴 수 있다 · 파일이 **여러 번** 온다 (2026-09-02) ──────
    #
    # 요구 변경 셋을 그대로 태운다: (1) 첫 턴이 아니어도 돈다, (2) **이미 채운 값은 절대
    # 안 밀고 남은 항목만** 채운다, (3) 파일이 여러 번 오므로 표식이 **누적**된다.
    #
    # (3)이 이 블록의 핵심이다. 표식을 목록이 아니라 문자열 하나로 두면 두 번째 문서를
    # 태운 순간 첫 문서를 잊고, 캔버스가 둘을 계속 실어 올 때 **번갈아 가며 다시 태운다** —
    # 사용자가 지운 값이 되살아나는 그 결함이 파일이 둘일 때만 나타나는 형태로 남는다.
    doc_b = "<doc># 회의록\n주요 내용: 문서에서 온 내용\n</doc>"
    doc_c = "<doc># 다른 문서\n제 목 : 또 다른 제목\n</doc>"

    # 1턴 — 문서 없이 대화로 제목만 채운다.
    script.push({"updates": {"제 목": "대화로 넣은 제목"}})
    run_turn(steps, "제목은 대화로 넣은 제목이야", "s7", "주간보고")

    # 2턴 — **대화 도중** 파일이 올라온다. 첫 턴 전용이던 시절에는 여기서 통째로 스킵됐다.
    # 자동 채움 대본은 `제 목` 까지 돌려준다 — 프롬프트에서 뺐는데도 오는 경우이고,
    # 그것을 버리는지(`conflicts`)가 "이미 채운 내용을 밀어버리지 않는다" 의 두 번째 층이다.
    script.push({"updates": {"제 목": "문서가 덮으려는 제목", "주요 내용": "문서에서 온 내용"}})
    script.push({"updates": {}})
    calls_before = len(script.calls)
    _, result, _ = run_turn(steps, "이 파일도 참고해줘", "s7", "주간보고", doc_b)
    rep.expect(
        len(script.calls) - calls_before == 2,
        "대화 중간에 올린 문서도 자동 채움이 돈다 (첫 턴 전용이 아니다)",
        f"{len(script.calls) - calls_before}회 — 자동 채움이 안 돌았다",
    )
    state = read_session("s7")
    rep.expect(
        state.get("values", {}).get("주요 내용") == "문서에서 온 내용",
        "중간에 올린 문서가 **남은 빈 항목**을 채운다",
        state.get("values"),
    )
    rep.expect(
        state.get("values", {}).get("제 목") == "대화로 넣은 제목",
        "이미 채운 값은 중간 업로드로 밀리지 않는다",
        state.get("values"),
    )

    # 3턴 — 항목이 다 찼다. **LLM 을 부르지 않고** 그 사실을 답변이 말한다. 조용히
    # 넘기면 "파일을 올렸는데 아무 일도 일어나지 않았다" 가 된다.
    script.push({"updates": {}})
    calls_before = len(script.calls)
    _, result, _ = run_turn(steps, "이 문서도 반영해줘", "s7", "주간보고", doc_c)
    rep.expect(
        len(script.calls) - calls_before == 1,
        "채울 자리가 없으면 자동 채움 LLM 을 부르지 않는다",
        f"{len(script.calls) - calls_before}회 — 값이 전부 버려질 호출을 했다",
    )
    rep.expect(
        "추가로 채울 항목이 없습니다" in str((result or {}).get("text") or ""),
        "채울 자리가 없다는 사실을 답변이 말한다",
        str((result or {}).get("text") or "")[:200],
    )

    # 4턴 — **첫 문서(doc_b)가 다시 실려 온다.** 표식을 덮어썼다면 여기서 잊혀 다시
    # 태워지고, 방금 사용자가 고친 값 위로 문서 값이 돌아온다.
    state = read_session("s7")
    rep.expect(
        len(state.get("source_doc_hashes") or []) == 2,
        "문서 표식이 **누적**된다 (덮어쓰지 않는다)",
        state.get("source_doc_hashes"),
    )
    script.push({"updates": {}})
    calls_before = len(script.calls)
    run_turn(steps, "그대로 진행해줘", "s7", "주간보고", doc_b)
    rep.expect(
        len(script.calls) - calls_before == 1,
        "앞서 태운 문서는 뒤 문서를 태운 뒤에도 다시 태우지 않는다",
        f"{len(script.calls) - calls_before}회 — 첫 문서를 잊었다",
    )

    from template_fill import chat_api  # `build_app` 이 이미 sys.path 를 세워 뒀다

    saved_llm = chat_api.llm_call_async
    chat_api.llm_call_async = _config_missing
    try:
        _, result, handoff = run_turn(steps, "제목은 설정 점검", "s4", "주간보고")
    finally:
        chat_api.llm_call_async = saved_llm

    error = (result or {}).get("error") or {}
    rep.expect(
        error.get("retryable") is False,
        "설정 부재는 재시도 불가로 나간다 (실행 실패와 뭉치지 않는다)",
        error,
    )
    rep.expect(
        str(error.get("error_code", "")).endswith("00020003"),
        "설정 부재 코드 분류가 00020003 (실행 실패 00020002 가 아니다)",
        error.get("error_code"),
    )

    print()
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
