"""통합 점검 — 워크플로우 스텝 → 게이트웨이 → 코드서빙 → LLM 게이트웨이, MCP 까지 한 줄로 돌린다.

```
python Test/check/check_integration.py
```

다른 점검은 한 층씩 본다(`check_workflow_run` 은 서빙·MCP 호출부를 대역으로, `check_unit_endpoints`
는 라우트를 직접). 여기서는 **바깥 기반시설만** 가짜로 두고 나머지는 전부 실제 코드다:

| 가짜 | 대신하는 것 |
|---|---|
| `httpx.AsyncClient` 의 전송 | 게이트웨이 라우팅. 경로를 보고 아래 셋으로 나눈다 |
| ↳ `/code_serving/<id>/…` | 실제 FastAPI 앱 (`httpx.ASGITransport`, lifespan 포함) |
| ↳ `/mcp/<id>/mcp` | 실제 MCP 도구 함수 (JSON-RPC `tools/call`, SSE 로 답한다) |
| ↳ `/rep/serving/<id>/v1/chat/completions` | 대본 LLM — 렌더된 프롬프트의 표식을 보고 답한다 |
| CDN 업로드 | 받은 바이트를 기록하고 링크를 돌려준다 |
| `redis.asyncio.from_url` | 메모리 dict |
| `main_socketio` | 방별 emit 기록 |

단위마다 `main.py`·패키지 이름이 겹치므로 기능 하나를 자식 프로세스 하나에서 돌린다.
"""

import asyncio
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import traceback
import types
import zipfile

from paths import MCP_DIR, WORKFLOW_DIR, unit_dir  # noqa: E402

_HOST = "genos.invalid"
_GENOS_URL = f"http://{_HOST}"
_TOKEN = "it-token"
_LLM_ID = "llm-main"
_CDN_HOST = "cdn.invalid"
_CDN_UPLOAD = f"http://{_CDN_HOST}/minio/upload/temp"
_MCP_FILES = {"mcp-lang": "genon_lang_policy.py", "mcp-guard": "genon_text_guard.py"}

# 자식이 물려받으면 결과가 환경에 좌우되는 값 — 비운다.
_CLEAR_ENV = (
    "DISCLAIMER_MCP_ID", "DISCLAIMER_IDS", "DISCLAIMER_AGENT_ID", "OCR_MCP_ID",
    "INPUT_CHECK_LLM_SERVING_ID", "GENOS_ADMIN_API_URL", "GENON_DEBUG",
    "POLISH_PROMPT_IDS", "TRANSLATE_PROMPT_IDS", "FAQ_PROMPT_IDS", "TEMPLATE_FILL_PROMPT_IDS",
    "TRANSLATE_GLOSSARY_API_URL", "TRANSLATE_GLOSSARY_DRIVE_ID", "TRANSLATE_GLOSSARY_WORKSPACE_ID",
    "TEXT_POLISH_SERVING_ID", "TRANSLATION_SERVING_ID", "FAQ_SERVING_ID",
    "TEMPLATE_FILL_SERVING_ID", "POLISH_DEFAULT_DOC_TYPE", "POLISH_DEFAULT_TONE",
    "TRANSLATE_DEFAULT_TARGET_LANG", "TRANSLATE_DEFAULT_SOURCE_LANG", "REDIS_URL",
)


# ─────────────────────────────────────────────────────────────
# 가짜 기반시설
# ─────────────────────────────────────────────────────────────
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


class FakeSio:
    def __init__(self) -> None:
        self.emits: list = []

    async def emit(self, event, payload, room=None):
        self.emits.append((room, event, payload))

    def text(self, room: str) -> str:
        return "".join(str(p) for r, e, p in self.emits if r == room and e == "token")


class _CollectingMCP:
    """GenOS 가 주입하는 `mcp` 자리 — `@mcp.tool()` 함수를 그대로 걷어 둔다."""

    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self, *args, **kwargs):
        def _decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return _decorator


def _load_mcp_tools(filename: str) -> dict:
    path = os.path.join(MCP_DIR, filename)
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    collector = _CollectingMCP()
    namespace = {"mcp": collector, "__name__": filename[:-3]}
    exec(compile(source, path, "exec"), namespace)
    return collector.tools


def _between(text: str, start: str, end: str) -> str:
    head = text.find(start)
    if head == -1:
        return ""
    head += len(start)
    tail = text.find(end, head)
    return text[head: tail if tail != -1 else len(text)].strip()


_EN = {
    "본 사업은 2026.12.31 에 완료되었다.": "The project was completed on 2026.12.31.",
    "총 예산은 300,000,000원이다.": "The total budget is KRW 300,000,000.",
}


class FakeLlm:
    """렌더된 프롬프트의 표식으로 어느 호출인지 가려 대본을 돌려준다."""

    def __init__(self) -> None:
        self.calls: list = []        # (종류, system, user, stream)
        self.faq_reply = ""

    def reply(self, system: str, user: str) -> tuple:
        if '"usable"' in system:
            usable = bool(re.search(r"[가-힣A-Za-z0-9]", user))
            body = {"usable": True, "reason": "ok"} if usable else {"usable": False, "reason": "gibberish"}
            return "input_check", json.dumps(body)
        if "[묶음 구성]" in user:
            document = _between(user, "[문서 내용]", "[문서 내용 끝]")
            topics = [
                {"title": line[3:].strip(), "anchor": line.strip()}
                for line in document.splitlines() if line.startswith("## ")
            ]
            return "topic", json.dumps({"topics": topics}, ensure_ascii=False)
        if "[묶음 정보]" in user:
            k = int(re.search(r"이번 묶음: (\d+)번", user).group(1))
            section = _between(user, "[문서 부분]", "[문서 부분 끝]")
            updates: dict = {}
            bullets = 0
            for line in section.splitlines():
                if line.startswith("## ") and f"본문 {k}" not in updates:
                    updates[f"본문 {k}"] = line[3:].strip()
                elif line.startswith("- "):
                    bullets += 1
                    updates[f"내용 {k}-{bullets}"] = line[2:].strip()
            return "group", json.dumps({"updates": updates}, ensure_ascii=False)
        if "[사용자 발화]" in user:
            return "extract", json.dumps({"updates": {}})
        if "[필드 목록]" in user and "[문서 내용]" in user:
            document = _between(user, "[문서 내용]", "[문서 내용 끝]")
            title = next((l[2:].strip() for l in document.splitlines() if l.startswith("# ")), "")
            return "document", json.dumps({"updates": {"제 목": title}}, ensure_ascii=False)
        if user.startswith("SOURCE_MARKDOWN:"):
            lines = user.split("\n", 1)[1].split("\n") if "\n" in user else []
            return "translate", "\n".join(_EN.get(l.strip(), l) for l in lines)
        if "<<<FAQ" in system:
            return ("faq_retry" if "이미 만든 질문" in user else "faq"), self.faq_reply
        return "polish", re.sub(r"함\.", "합니다.", user)


class Gateway:
    """게이트웨이 · CDN 자리. 모든 호출을 `calls` 에 남긴다."""

    def __init__(self, serving_id: str, app) -> None:
        import httpx

        self.serving_id = serving_id
        self.asgi = httpx.ASGITransport(app=app)
        self.mcp = {mcp_id: _load_mcp_tools(f) for mcp_id, f in _MCP_FILES.items()}
        self.llm = FakeLlm()
        self.calls: list = []      # dict(kind, name, payload, status, body, auth)
        self.uploads: list = []    # (링크, 바이트)
        self.unrouted: list = []

    def of(self, kind: str, name: str = "") -> list:
        return [c for c in self.calls if c["kind"] == kind and (not name or c["name"] == name)]

    def mark(self) -> int:
        return len(self.calls)

    def since(self, mark: int, kind: str, name: str = "") -> list:
        return [c for c in self.calls[mark:] if c["kind"] == kind and (not name or c["name"] == name)]

    async def route(self, request):
        import httpx

        body = await request.aread()
        url = request.url
        path = url.path
        auth = request.headers.get("authorization", "")
        if url.host == _CDN_HOST and path == "/minio/upload/temp":
            link = f"https://{_CDN_HOST}/files/{len(self.uploads) + 1}"
            self.uploads.append((link, body))
            return httpx.Response(200, json={"data": {"presigned_url": link}})
        if url.host == _HOST and path.startswith("/api/gateway/code_serving/"):
            serving_id, _, tail = path[len("/api/gateway/code_serving/"):].partition("/")
            if serving_id == self.serving_id:
                return await self._serving(request, "/" + tail, body, auth)
        if url.host == _HOST and path.startswith("/api/gateway/mcp/") and path.endswith("/mcp"):
            mcp_id = path[len("/api/gateway/mcp/"):-len("/mcp")]
            if mcp_id in self.mcp:
                return await self._mcp(request, mcp_id, body, auth)
        if url.host == _HOST and path == f"/api/gateway/rep/serving/{_LLM_ID}/v1/chat/completions":
            return self._llm(body, auth)
        self.unrouted.append(f"{request.method} {url}")
        return httpx.Response(404, json={"error": "unrouted"})

    async def _serving(self, request, path: str, body: bytes, auth: str):
        import httpx

        target = "http://serving.invalid" + path + (f"?{request.url.query.decode()}" if request.url.query else "")
        inner = httpx.Request(request.method, target, headers=request.headers, content=body)
        response = await self.asgi.handle_async_request(inner)
        content = await response.aread()
        try:
            payload = json.loads(body) if body else {}
        except ValueError:
            payload = {}
        self.calls.append({
            "kind": "serving", "name": f"{request.method} {path}", "payload": payload,
            "status": response.status_code, "body": content.decode("utf-8", "replace"), "auth": auth,
        })
        return httpx.Response(response.status_code, headers=response.headers, content=content)

    async def _mcp(self, request, mcp_id: str, body: bytes, auth: str):
        import httpx

        accept = request.headers.get("accept", "").lower()
        rpc = json.loads(body)
        tool = rpc["params"]["name"]
        arguments = rpc["params"].get("arguments") or {}
        record = {"kind": "mcp", "name": f"{_MCP_FILES[mcp_id][:-3]}.{tool}", "payload": arguments,
                  "status": 200, "body": "", "auth": auth}
        self.calls.append(record)
        if "application/json" not in accept or "text/event-stream" not in accept:
            record["status"] = 406
            return httpx.Response(406, text="Not Acceptable")
        try:
            text = await self.mcp[mcp_id][tool](**arguments)
            frame = {"jsonrpc": "2.0", "id": rpc.get("id"),
                     "result": {"content": [{"type": "text", "text": text}]}}
            record["body"] = text
        except Exception as exc:  # noqa: BLE001 - 계약 어긋남을 기록으로 드러낸다
            frame = {"jsonrpc": "2.0", "id": rpc.get("id"),
                     "error": {"code": -32602, "message": f"{type(exc).__name__}: {exc}"}}
            record["status"] = -1
            record["body"] = frame["error"]["message"]
        sse = "event: message\ndata: " + json.dumps(frame, ensure_ascii=False) + "\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=sse.encode("utf-8"))

    def _llm(self, body: bytes, auth: str):
        import httpx

        request = json.loads(body)
        messages = request.get("messages") or []
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        user = next((m["content"] for m in messages if m.get("role") == "user"), "")
        kind, content = self.llm.reply(system, user)
        stream = bool(request.get("stream"))
        self.llm.calls.append((kind, system, user, stream))
        self.calls.append({"kind": "llm", "name": kind, "payload": {}, "status": 200,
                           "body": content, "auth": auth})
        if not stream:
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant",
                                                                      "content": content}}]})
        frames = "".join(
            "data: " + json.dumps({"choices": [{"delta": {"content": content[i:i + 7]}}]},
                                  ensure_ascii=False) + "\n\n"
            for i in range(0, len(content), 7)
        ) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=frames.encode("utf-8"))


def _install_transport(gateway: Gateway) -> None:
    """`httpx.AsyncClient` 를 갈아 끼운다 — 스텝·서빙·업로드가 모두 이 전송을 탄다."""
    import httpx

    class _Router(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return await gateway.route(request)

    router = _Router()
    real = httpx.AsyncClient

    class _RoutedClient(real):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = router
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = _RoutedClient


def _prepare(env: dict, unit: str, redis: bool = False):
    """환경변수 · Redis · 소켓을 세우고 단위의 `main` 을 실어 온다."""
    for key in _CLEAR_ENV:
        os.environ.pop(key, None)
    os.environ.update({
        "GENOS_URL": _GENOS_URL, "GENOS_TOKEN": _TOKEN, "LLM_SERVING_ID": _LLM_ID,
        "GENOS_CDN_UPLOAD_URL": _CDN_UPLOAD, "GENOS_CDN_HOSTNAME": f"https://{_CDN_HOST}",
        "LANG_POLICY_MCP_ID": "mcp-lang", "TEXT_GUARD_MCP_ID": "mcp-guard",
        "LLM_RETRY_COUNT": "1", "LOG_LEVEL": "WARNING",
    })
    os.environ.update(env)
    fake_redis = FakeRedis()
    if redis:
        os.environ["REDIS_URL"] = "redis://redis.invalid:6379/0"
        import redis.asyncio
        redis.asyncio.from_url = lambda *_a, **_k: fake_redis
    sio = FakeSio()
    sys.modules["main_socketio"] = types.SimpleNamespace(sio_server=sio)
    sys.path.insert(0, unit_dir(unit))
    import main  # noqa: PLC0415 - 단위마다 다른 main 이라 자식에서만 싣는다
    return main.app, fake_redis, sio


def _load_step(filename: str):
    spec = importlib.util.spec_from_file_location("_it_" + filename[:-3],
                                                  os.path.join(WORKFLOW_DIR, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _drain(gen) -> tuple:
    """마지막 스텝을 끝까지 돌려 `(result.data, 흘린 글, result 횟수)` 를 돌려준다."""
    payload: dict = {}
    streamed: list = []
    results = 0
    async for item in gen:
        if item.get("event") == "result":
            payload = item.get("data") or {}
            results += 1
        elif item.get("event") == "token":
            streamed.append(str(item.get("data") or ""))
    return payload, "".join(streamed), results


def _json(text: str) -> dict:
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _done_frame(body: str) -> dict:
    for line in reversed(body.splitlines()):
        if line.startswith("data:"):
            try:
                frame = json.loads(line[5:].strip())
            except ValueError:
                continue
            if isinstance(frame, dict) and frame.get("type") == "done":
                return frame
    return {}


def _check_gateway(out: list, gw: Gateway, label: str) -> None:
    gateway_calls = [c for c in gw.calls if c["kind"] in ("serving", "mcp")]
    bad = [c["name"] for c in gateway_calls if c["auth"] != f"Bearer {_TOKEN}"]
    out.append((f"{label}: 게이트웨이 호출이 전부 토큰을 싣는다", bool(gateway_calls) and not bad,
                f"{len(gateway_calls)}건 / 어긋남 {bad[:3]}"))
    llm_bad = [c["name"] for c in gw.of("llm") if c["auth"] != f"Bearer {_TOKEN}"]
    out.append((f"{label}: 서빙의 LLM 호출이 토큰을 싣는다", bool(gw.of("llm")) and not llm_bad,
                f"{len(gw.of('llm'))}건 / 어긋남 {llm_bad[:3]}"))
    mcp_bad = [f"{c['name']}={c['status']}:{c['body'][:80]}" for c in gw.of("mcp") if c["status"] != 200]
    out.append((f"{label}: MCP 호출이 전부 도구에 닿았다", not mcp_bad, "; ".join(mcp_bad) or "OK"))
    out.append((f"{label}: 라우팅 밖 요청이 없다", not gw.unrouted, "; ".join(gw.unrouted[:3]) or "없음"))


def _upload_text(gw: Gateway, link) -> str:
    for url, data in gw.uploads:
        if url == link:
            return data.decode("utf-8", "replace")
    return ""


# ─────────────────────────────────────────────────────────────
# 글다듬이
# ─────────────────────────────────────────────────────────────
_POLISH_TEXT = "다음 주 회의 일정을 공유함. 회의는 2026년 10월 20일 오후 3시에 시작함."
_POLISH_EXPECTED = "다음 주 회의 일정을 공유합니다. 회의는 2026년 10월 20일 오후 3시에 시작합니다."
_GIBBERISH = "ㄹㅇㄹㄹㅇㄴㅁ"


async def _polish(out: list) -> None:
    app, _redis, sio = _prepare({"TEXT_POLISH_SERVING_ID": "svc-polish"}, "SFR-018_text_polish")
    gw = Gateway("svc-polish", app)
    _install_transport(gw)
    step1 = _load_step("sfr018_polish_01_policy.py")
    step2 = _load_step("sfr018_polish_02_polish.py")

    async with app.router.lifespan_context(app):
        data = {"question": _POLISH_TEXT, "socketIOClientId": "sid-polish",
                "genos_state": {"trace_id": "it-polish"},
                "polish_doc_type": "email", "polish_tone": "polite"}
        handoff = await step1.run(data)
        out.append(("다듬-1: 정책 확정",
                    not handoff.get("error") and handoff.get("polish_source_text") == _POLISH_TEXT
                    and handoff.get("polish_doc_type") == "email" and handoff.get("polish_tone") == "polite",
                    f"error={handoff.get('error')} doc={handoff.get('polish_doc_type')} tone={handoff.get('polish_tone')}"))
        checks = gw.of("serving", "POST /input/check")
        out.append(("다듬-1: 입력 판단이 서빙 → LLM 까지 갔다",
                    len(checks) == 1 and checks[0]["payload"].get("text") == _POLISH_TEXT
                    and _json(checks[0]["body"]).get("usable") is True
                    and any(c[0] == "input_check" for c in gw.llm.calls),
                    checks[0]["body"][:80] if checks else "호출 없음"))
        tone_calls = gw.of("mcp", "genon_lang_policy.resolve_tone")
        out.append(("다듬-1: MCP lang_policy.resolve_tone 실제 호출",
                    len(tone_calls) == 1 and tone_calls[0]["payload"].get("doc_type") == "email",
                    tone_calls[0]["body"][:100] if tone_calls else "호출 없음"))

        result, streamed, results = await _drain(step2.run(handoff))
        out.append(("다듬-2: 가짜 LLM 이 다듬은 글이 result 로 나온다",
                    results == 1 and result.get("polished_text") == _POLISH_EXPECTED
                    and result.get("original_text") == _POLISH_TEXT and "error" not in result,
                    str(result.get("polished_text"))[:80]))
        out.append(("다듬-2: 스트리밍 경로(/polish/stream)로 왔다",
                    len(gw.of("serving", "POST /polish/stream")) == 1
                    and not gw.of("serving", "POST /polish") and streamed == _POLISH_EXPECTED,
                    f"흘린 글={streamed[:40]!r}"))
        out.append(("다듬-2: 소켓 방으로 같은 글을 흘렸다", sio.text("sid-polish") == _POLISH_EXPECTED,
                    sio.text("sid-polish")[:40]))
        polish_llm = [c for c in gw.llm.calls if c[0] == "polish"]
        out.append(("다듬-2: 톤 프리셋 지시가 LLM 시스템 프롬프트에 실렸다",
                    bool(polish_llm) and all(c[3] for c in polish_llm)
                    and "격식 있는 존댓말" in polish_llm[0][1],
                    f"LLM {len(polish_llm)}회 / stream={[c[3] for c in polish_llm]}"))
        guards = {c["name"] for c in gw.of("mcp") if c["name"].startswith("genon_text_guard.")}
        out.append(("다듬-2: MCP text_guard 점검 둘이 실제로 돌았다",
                    guards == {"genon_text_guard.markdown_structure_issues", "genon_text_guard.fact_issues"}
                    and "notice" not in result,
                    f"{sorted(guards)} notice={result.get('notice')}"))
        link = result.get("download_url")
        out.append(("다듬-2: CDN 에 올린 md 링크가 실리고 파일이 정본을 담는다",
                    bool(link) and _POLISH_EXPECTED in _upload_text(gw, link),
                    f"download_url={link}"))
        _check_gateway(out, gw, "다듬")

        # 뜻 없는 입력 — 입력 판단에서 멈추고 다듬기를 부르지 않는다.
        mark = gw.mark()
        handoff = await step1.run({"question": _GIBBERISH, "genos_state": {"trace_id": "it-polish-g"},
                                   "polish_doc_type": "email", "polish_tone": "polite"})
        error = handoff.get("error") or {}
        verdicts = gw.since(mark, "serving", "POST /input/check")
        out.append(("다듬 [뜻 없는 입력]: 스텝 1 이 INPUT_UNUSABLE 로 멈춘다",
                    str(error.get("error_code", "")).endswith("00020003")
                    and error.get("msg") == "입력 내용을 확인해 주세요."
                    and len(verdicts) == 1 and _json(verdicts[0]["body"]).get("usable") is False
                    and not gw.since(mark, "mcp"),
                    f"error={error} 판단={verdicts[0]['body'][:60] if verdicts else '없음'}"))
        result, _, results = await _drain(step2.run(handoff))
        out.append(("다듬 [뜻 없는 입력]: 스텝 2 가 /polish 를 부르지 않고 오류로 끝난다",
                    results == 1 and (result.get("error") or {}).get("error_code") == error.get("error_code")
                    and not [c for c in gw.since(mark, "serving") if "/polish" in c["name"]],
                    str(result.get("error"))[:80]))

        # file_ids — 첨부가 실려 와도 이번 턴 id 가 없으면 질문을 다듬는다.
        uploaded = '<doc file_name="old.md" temp_doc_id="d0">지난 턴에 올린 문서 본문임.</doc>'
        question = "이번 턴에 입력한 문장을 다듬어 주기 바람."
        base = {"question": question, "genos_state": {"trace_id": "it-polish-f"},
                "polish_doc_type": "email", "polish_tone": "polite", "genosUploaded": uploaded}
        mark = gw.mark()
        handoff = await step1.run(dict(base))
        sent = gw.since(mark, "serving", "POST /input/check")
        out.append(("다듬 [file_ids 없음]: 실려 온 첨부 대신 질문을 다듬는다",
                    handoff.get("polish_source_text") == question
                    and bool(sent) and sent[0]["payload"].get("text") == question,
                    str(handoff.get("polish_source_text"))[:40]))
        result, _, _ = await _drain(step2.run(handoff))
        sent = gw.since(mark, "serving", "POST /polish/stream")
        out.append(("다듬 [file_ids 없음]: 서빙에 보낸 본문도 질문이다",
                    bool(sent) and sent[0]["payload"].get("text") == question
                    and result.get("original_text") == question,
                    str(sent[0]["payload"].get("text") if sent else "호출 없음")[:40]))
        handoff = await step1.run({**base, "overrideConfig": {"file_ids": ["f-1"]}})
        out.append(("다듬 [file_ids 있음]: 첨부 본문을 다듬는다",
                    handoff.get("polish_source_text") == "지난 턴에 올린 문서 본문임.",
                    str(handoff.get("polish_source_text"))[:40]))


# ─────────────────────────────────────────────────────────────
# 번역
# ─────────────────────────────────────────────────────────────
_KO = "본 사업은 2026.12.31 에 완료되었다.\n\n총 예산은 300,000,000원이다."
_EN_EXPECTED = "The project was completed on 2026.12.31.\n\nThe total budget is KRW 300,000,000."

async def _translate(out: list) -> None:
    app, _redis, sio = _prepare({"TRANSLATION_SERVING_ID": "svc-tr"}, "SFR-018_translation")
    gw = Gateway("svc-tr", app)
    _install_transport(gw)
    step1 = _load_step("sfr018_translate_01_detect.py")
    step2 = _load_step("sfr018_translate_02_translate.py")

    async with app.router.lifespan_context(app):
        data = {"question": _KO, "socketIOClientId": "sid-tr", "genos_state": {"trace_id": "it-tr"},
                "translate_target_lang": "en"}
        handoff = await step1.run(data)
        out.append(("번역-1: 방향 확정 (ko → en)",
                    not handoff.get("error") and handoff.get("translate_source_lang") == "ko"
                    and handoff.get("translate_target_lang") == "en"
                    and handoff.get("translate_source_text") == _KO,
                    f"error={handoff.get('error')} {handoff.get('translate_source_lang')}→{handoff.get('translate_target_lang')}"))
        direction = gw.of("mcp", "genon_lang_policy.validate_direction")
        out.append(("번역-1: 입력 판단 서빙 + MCP validate_direction 실제 호출",
                    len(gw.of("serving", "POST /input/check")) == 1 and len(direction) == 1
                    and _json(direction[0]["body"]).get("allowed") is True,
                    direction[0]["body"][:100] if direction else "호출 없음"))

        result, streamed, results = await _drain(step2.run(handoff))
        translated = str(result.get("translated_text") or "")
        out.append(("번역-2: 번역문이 result 로 나온다",
                    results == 1 and "error" not in result
                    and translated.strip() == _EN_EXPECTED,
                    translated[:80]))
        out.append(("번역-2: /translate/stream → /translate/finalize 순서로 불렀다",
                    [c["name"] for c in gw.of("serving") if "/translate" in c["name"]]
                    == ["POST /translate/stream", "POST /translate/finalize"],
                    str([c["name"] for c in gw.of("serving")])))
        out.append(("번역-2: 흘린 글과 소켓 방의 글이 정본이다",
                    streamed.strip() == _EN_EXPECTED and sio.text("sid-tr").strip() == _EN_EXPECTED,
                    repr(streamed[:50])))
        tr_llm = [c for c in gw.llm.calls if c[0] == "translate"]
        out.append(("번역-2: LLM 은 스트리밍 번역 프롬프트(대상 English)로 불렸다",
                    bool(tr_llm) and all(c[3] for c in tr_llm) and "출력 언어는 English" in tr_llm[0][1],
                    f"LLM {len(tr_llm)}회"))
        numeric = gw.of("mcp", "genon_text_guard.numeric_issues")
        out.append(("번역-2: MCP text_guard.numeric_issues 실제 호출 · 경고 없음",
                    len(numeric) == 1 and "notice" not in result,
                    (numeric[0]["body"][:80] if numeric else "호출 없음") + f" notice={result.get('notice')}"))
        link = result.get("download_url")
        out.append(("번역-2: CDN 에 올린 md 가 번역문을 담는다",
                    bool(link) and "The total budget is KRW 300,000,000." in _upload_text(gw, link),
                    f"download_url={link}"))
        _check_gateway(out, gw, "번역")

        mark = gw.mark()
        handoff = await step1.run({"question": _GIBBERISH, "genos_state": {"trace_id": "it-tr-g"},
                                   "translate_target_lang": "en"})
        error = handoff.get("error") or {}
        out.append(("번역 [뜻 없는 입력]: 스텝 1 이 INPUT_UNUSABLE 로 멈춘다",
                    str(error.get("error_code", "")).endswith("00020003")
                    and error.get("msg") == "입력 내용을 확인해 주세요."
                    and len(gw.since(mark, "serving", "POST /input/check")) == 1
                    and not gw.since(mark, "mcp"),
                    str(error)))
        result, _, _ = await _drain(step2.run(handoff))
        out.append(("번역 [뜻 없는 입력]: 스텝 2 가 번역을 부르지 않고 오류로 끝난다",
                    (result.get("error") or {}).get("error_code") == error.get("error_code")
                    and not [c for c in gw.since(mark, "serving") if "/translate" in c["name"]],
                    str(result.get("error"))[:80]))


# ─────────────────────────────────────────────────────────────
# FAQ
# ─────────────────────────────────────────────────────────────
_FAQ_DOC = (
    "# 카드 연회비 안내\n\n"
    "카드 연회비는 매년 카드 발급월에 청구됩니다.\n\n"
    "해외겸용 카드의 연회비는 2만 원입니다.\n\n"
    "전월 이용 실적이 30만 원 이상이면 다음 해 연회비가 면제됩니다."
)
_FAQ_GOOD = [
    ("카드 연회비는 매년 카드 발급월에 청구됩니다.", "연회비는 언제 청구되나요?",
     "연회비는 매년 카드를 발급받은 달에 청구됩니다."),
    ("전월 이용 실적이 30만 원 이상이면 다음 해 연회비가 면제됩니다.", "연회비를 면제받을 수 있나요?",
     "전월 이용 실적이 30만 원 이상이면 다음 해 연회비가 면제됩니다."),
]
_FAQ_FAKE = ("모든 고객의 연회비는 평생 무료로 제공됩니다.", "연회비가 평생 무료인가요?",
             "네, 모든 고객의 연회비는 평생 무료입니다.")


def _faq_block(items) -> str:
    return "\n".join(f"<<<FAQ\n근거: {e}\n질문: {q}\n답변: {a}\n>>>" for e, q, a in items)


async def _faq(out: list) -> None:
    app, fake_redis, sio = _prepare({"FAQ_SERVING_ID": "svc-faq"}, "SFR-018_faq", redis=True)
    gw = Gateway("svc-faq", app)
    gw.llm.faq_reply = _faq_block([_FAQ_FAKE, *_FAQ_GOOD])
    _install_transport(gw)
    step1 = _load_step("sfr018_faq_01_source.py")
    step2 = _load_step("sfr018_faq_02_generate.py")

    async with app.router.lifespan_context(app):
        data = {"question": "FAQ 만들어 줘", "socketIOClientId": "sid-faq",
                "genos_state": {"trace_id": "it-faq"}, "faq_count": 2,
                "genosUploaded": f'<doc file_name="fee.md" temp_doc_id="d1">{_FAQ_DOC}</doc>'}
        handoff = await step1.run(data)
        out.append(("FAQ-1: 첨부 본문 확보 + 서빙 /config 로 개수 확정",
                    not handoff.get("error") and handoff.get("faq_source_text") == _FAQ_DOC
                    and handoff.get("faq_count") == 2 and len(gw.of("serving", "GET /config")) == 1,
                    f"error={handoff.get('error')} count={handoff.get('faq_count')}"))

        result, streamed, results = await _drain(step2.run(handoff))
        items = result.get("faq_items") or []
        questions = [i.get("question") for i in items]
        out.append(("FAQ-2: 근거가 문서에 있는 항목만 채택된다",
                    results == 1 and "error" not in result
                    and questions == [q for _, q, _ in _FAQ_GOOD]
                    and all(i.get("evidence") and i["evidence"] in _FAQ_DOC for i in items),
                    str(questions)))
        streams = gw.of("serving", "POST /generate/stream")
        done = _done_frame(streams[0]["body"]) if streams else {}
        rejected = done.get("rejected") or {}
        out.append(("FAQ-2: 지어낸 근거는 기각되고 건수가 응답에 드러난다",
                    rejected.get("ungrounded") == 1 and _FAQ_FAKE[1] not in json.dumps(result, ensure_ascii=False),
                    f"rejected={rejected}"))
        out.append(("FAQ-2: 채택 항목만 흘렸다 (기각 항목은 화면에 안 나온다)",
                    all(q in streamed for _, q, _ in _FAQ_GOOD) and _FAQ_FAKE[1] not in streamed
                    and sio.text("sid-faq") == streamed and not gw.of("serving", "POST /generate"),
                    repr(streamed[:60])))
        faq_llm = [c for c in gw.llm.calls if c[0].startswith("faq")]
        out.append(("FAQ-2: LLM 은 문서를 실어 스트리밍으로 한 번 불렸다 (부족분 재요청 없음)",
                    len(faq_llm) == 1 and faq_llm[0][3] and _FAQ_DOC.splitlines()[2] in faq_llm[0][2],
                    str([(c[0], c[3]) for c in faq_llm])))
        link = result.get("download_url")
        upload = _upload_text(gw, link)
        out.append(("FAQ-2: CDN md 가 채택 항목을 담는다",
                    bool(link) and all(q in upload for _, q, _ in _FAQ_GOOD) and _FAQ_FAKE[1] not in upload,
                    f"download_url={link}"))
        stored = [v for k, v in fake_redis.store.items() if "sid-faq" in k]
        out.append(("FAQ-2: 다운로드 세션이 Redis 에 저장됐다",
                    len(stored) == 1 and _FAQ_GOOD[0][1] in stored[0],
                    str(list(fake_redis.store))[:80]))
        out.append(("FAQ-2: 개수를 채웠으니 미달 안내가 없다",
                    "disclaimer" not in result and "notice" not in result,
                    f"disclaimer={result.get('disclaimer')} notice={result.get('notice')}"))
        _check_gateway(out, gw, "FAQ")


# ─────────────────────────────────────────────────────────────
# 006 양식 채우기 — 반복 묶음
# ─────────────────────────────────────────────────────────────
_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_REPEAT_SECTION = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="{hp}">
  <hp:p paraPrIDRef="1">
    <hp:run charPrIDRef="1"><hp:secPr/></hp:run>
    <hp:run charPrIDRef="1"><hp:t>제 목 : {{'제 목'}}</hp:t></hp:run>
  </hp:p>
  <hp:p paraPrIDRef="3"><hp:run charPrIDRef="3"><hp:t>□ {{'본문 1'}}</hp:t></hp:run></hp:p>
  <hp:p paraPrIDRef="4"><hp:run charPrIDRef="3"><hp:t>  - {{'내용 1-1'}}</hp:t></hp:run></hp:p>
</hs:sec>
""".format(hp=_HP)

_PLAN_DOC = (
    "# 2026년 하반기 사업 추진 계획\n\n"
    "## 1. 디지털 전환 추진\n- 업무 시스템 클라우드 이전\n- 전자결재 고도화\n\n"
    "## 2. 고객 서비스 개선\n- 상담 챗봇 도입\n\n"
    "## 3. 보안 강화\n- 개인정보 점검 정례화\n- 접근권한 재정비"
)
_PLAN_VALUES = {
    "제 목": "2026년 하반기 사업 추진 계획",
    "본문 1": "1. 디지털 전환 추진", "내용 1-1": "업무 시스템 클라우드 이전", "내용 1-2": "전자결재 고도화",
    "본문 2": "2. 고객 서비스 개선", "내용 2-1": "상담 챗봇 도입",
    "본문 3": "3. 보안 강화", "내용 3-1": "개인정보 점검 정례화", "내용 3-2": "접근권한 재정비",
}


async def _template_fill(out: list) -> None:
    template_dir = tempfile.mkdtemp(prefix="it_sfr006_")
    with zipfile.ZipFile(os.path.join(template_dir, "사업계획.hwpx"), "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("Contents/section0.xml", _REPEAT_SECTION.encode("utf-8"))
        zf.writestr("Contents/header.xml", '<?xml version="1.0" encoding="UTF-8"?><h/>')
    app, _redis, sio = _prepare({"TEMPLATE_FILL_SERVING_ID": "svc-006",
                                 "TEMPLATE_FILL_TEMPLATE_DIR": template_dir},
                                "SFR-006_template_fill", redis=True)
    gw = Gateway("svc-006", app)
    _install_transport(gw)
    steps = [_load_step(f) for f in ("sfr006_01_context.py", "sfr006_02_extract.py", "sfr006_03_commit.py")]
    from template_fill import session_store  # noqa: PLC0415 - `_prepare` 가 sys.path 를 세운 뒤

    question = "첨부한 계획서로 양식을 채워 줘"
    data = {
        "question": question, "socketIOClientId": "sid-006",
        "genos_state": {"session_id": "it-006", "trace_id": "it-006"},
        "overrideConfig": {
            "vars": {"template_fill_template_id": "사업계획",
                     "genosUploaded": f'<doc file_name="plan.md" temp_doc_id="d6">{_PLAN_DOC}</doc>'},
            "file_ids": ["f-006"],
        },
    }
    async with app.router.lifespan_context(app):
        handoff = await steps[0].run(data)
        out.append(("006-1: /chat/context 로 템플릿 확정 + 첨부 본문 전달",
                    not handoff.get("error") and handoff.get("template_id") == "사업계획"
                    and "## 3. 보안 강화" in str(handoff.get("document") or "")
                    and len(gw.of("serving", "POST /chat/context")) == 1,
                    f"error={handoff.get('error')} template={handoff.get('template_id')}"))
        handoff = await steps[1].run(handoff)
        extract = [c for c in gw.llm.calls if c[0] == "extract"]
        out.append(("006-2: /chat/extract 가 발화를 LLM 에 실었다",
                    not handoff.get("error") and len(gw.of("serving", "POST /chat/extract")) == 1
                    and len(extract) == 1 and question in extract[0][2],
                    f"error={handoff.get('error')} LLM={len(extract)}회"))
        result, streamed, results = await _drain(steps[2].run(handoff))

        kinds = [c[0] for c in gw.llm.calls]
        groups = [int(re.search(r"이번 묶음: (\d+)번", c[2]).group(1)) for c in gw.llm.calls if c[0] == "group"]
        out.append(("006-3: 주제 경로 — 주제 뽑기 1회 · 묶음 3개를 따로 채웠다 (비상 경로 아님)",
                    kinds.count("topic") == 1 and sorted(groups) == [1, 2, 3]
                    and len(gw.of("serving", "POST /chat/prefill/stream")) == 1
                    and not gw.of("serving", "POST /chat/prefill"),
                    f"LLM 호출={kinds}"))
        out.append(("006-3: 주제 3개를 찾았다고 흘렸다",
                    "주제 3개를 찾았습니다" in streamed and sio.text("sid-006") == streamed,
                    repr(streamed[:60])))
        state = await session_store.load_session(str(handoff.get("session_id") or ""))
        values = state.get("values") or {}
        out.append(("006-3: 세션에 본문 1..3 과 묶음별 세부 내용이 저장됐다",
                    values == _PLAN_VALUES,
                    json.dumps(values, ensure_ascii=False)[:200]))
        link = result.get("download_url")
        section = ""
        for url, blob in gw.uploads:
            if url == link:
                with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                    name = next((n for n in zf.namelist() if n.endswith("section0.xml")), "")
                    section = zf.read(name).decode("utf-8") if name else ""
        out.append(("006-3: 다 채워 hwpx 를 올리고 링크가 나온다 (묶음 셋이 문서에 펼쳐졌다)",
                    results == 1 and "error" not in result and bool(link)
                    and all(v in section for v in _PLAN_VALUES.values()),
                    f"download_url={link} section={len(section)}자"))
        text = str(result.get("text") or "")
        out.append(("006-3: 답변 미리보기가 묶음 순서대로 채워져 있다",
                    "접근권한 재정비" in text
                    and text.index("전자결재 고도화") < text.index("상담 챗봇 도입") < text.index("접근권한 재정비"),
                    text[-120:]))
        _check_gateway(out, gw, "006")


# ─────────────────────────────────────────────────────────────
# 자식 / 부모
# ─────────────────────────────────────────────────────────────
CHECKS = {
    "polish": ("SFR-018 글다듬이", _polish),
    "translate": ("SFR-018 번역", _translate),
    "faq": ("SFR-018 FAQ", _faq),
    "template_fill": ("SFR-006 양식 채우기", _template_fill),
}


def _child_main(key: str) -> int:
    out: list = []
    try:
        asyncio.run(CHECKS[key][1](out))
        payload = {"ok": True, "results": out}
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                   "traceback": traceback.format_exc(), "results": out}
    sys.stdout.write("\n__IT_RESULT__" + json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return 0


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        return _child_main(sys.argv[2])

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    rep: list = []
    tracebacks: list = []
    for key, (label, _) in CHECKS.items():
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--child", key],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=300,
        )
        line = ""
        for raw in (proc.stdout or "").splitlines():
            if raw.startswith("__IT_RESULT__"):
                line = raw[len("__IT_RESULT__"):]
        if not line:
            tail = ((proc.stderr or "") + (proc.stdout or "")).strip().splitlines()[-3:]
            rep.append(("FAIL", label, "기동", " / ".join(tail) or "결과를 받지 못했다"))
            continue
        payload = json.loads(line)
        for item, passed, detail in payload.get("results", []):
            rep.append(("OK" if passed else "FAIL", label, item, detail))
        if not payload.get("ok"):
            rep.append(("FAIL", label, "실행", payload.get("error", "알 수 없는 실패")))
            if payload.get("traceback"):
                tracebacks.append((label, payload["traceback"]))

    ok = sum(1 for r in rep if r[0] == "OK")
    fail = sum(1 for r in rep if r[0] == "FAIL")
    name_w = max(len(r[1]) for r in rep)
    for status, label, item, detail in rep:
        mark = "OK  " if status == "OK" else "FAIL"
        print(f"[{mark}] {label:<{name_w}}  {item}  — {' '.join(str(detail).split())}")
    for label, tb in tracebacks:
        print()
        print(f"--- {label} 실행 실패 스택 ---")
        print(tb.rstrip())
    print()
    print(f"OK {ok} / {ok + fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
