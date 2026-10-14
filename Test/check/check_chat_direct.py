"""006 젠포탈 직접 호출 `POST /chat` 점검 — 단위가 SSE 를 직접 낸다.

```
python Test/check/check_chat_direct.py
```

서버·Redis·LLM·CDN 불필요. `TestClient` 로 인프로세스 호출한다.
018 세 단위에는 `/chat` 직접 호출이 없다(워크플로우 파이썬 스텝이 코드서빙을 부른다).

대역은 단위 **밖에서** `check_chat_turn` 과 같은 자리(LLM 함수·Redis 클라이언트)에 꽂는다.
subprocess 로 띄운다 — 단위가 최상위 `main` 이름을 쓴다.
"""

import json
import os
import subprocess
import sys
import tempfile
import zipfile

from paths import unit_dir  # noqa: E402

_CDN_LINK = "http://cdn.test/f/result.md"
_ENV = {
    "GENOS_URL": "http://gw.test",
    "GENOS_TOKEN": "tok-test",
    "LLM_SERVING_ID": "srv-test",
    "LLM_RETRY_COUNT": "1",
    "TEXT_GUARD_MCP_ID": "guard-test",
    "GENOS_CDN_UPLOAD_URL": "http://cdn.test/upload",
    "CHAT_HEARTBEAT_SECONDS": "0",
}


# ─────────────────────────────────────────────────────────────
# 공통 — SSE 해석 · 판정
# ─────────────────────────────────────────────────────────────
def frames(response) -> list:
    """SSE 본문 → `[(event, data)]`. `{"event","data"}` 모양이 아닌 프레임은 `("?", 원문)`."""
    out = []
    for block in response.text.replace("\r\n", "\n").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if not block.startswith("data: "):
            out.append(("?", block))
            continue
        try:
            obj = json.loads(block[len("data: "):])
        except json.JSONDecodeError:
            out.append(("?", block))
            continue
        if not isinstance(obj, dict) or set(obj) != {"event", "data"}:
            out.append(("?", block))
            continue
        out.append((obj["event"], obj["data"]))
    return out


def tokens(fs: list, name: str = "token") -> str:
    return "".join(d for e, d in fs if e == name and isinstance(d, str))


def complete(fs: list, name: str = "complete"):
    found = [d for e, d in fs if e == name]
    return found[-1] if found else None


class Report:
    def __init__(self, unit: str) -> None:
        self.unit = unit
        self.rows: list = []

    def expect(self, name: str, ok: bool, detail="") -> None:
        self.rows.append(("OK" if ok else "FAIL", f"[{self.unit}] {name}", str(detail)[:160]))


# ─────────────────────────────────────────────────────────────
# 006
# ─────────────────────────────────────────────────────────────
_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_SECTION = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="' + _HP + '">'
    '<hp:p paraPrIDRef="1"><hp:run charPrIDRef="1"><hp:secPr/></hp:run>'
    "<hp:run charPrIDRef=\"1\"><hp:t>제 목 : {'제 목', 고딕, 16pt}</hp:t></hp:run></hp:p>"
    "<hp:p paraPrIDRef=\"3\"><hp:run charPrIDRef=\"3\"><hp:t>주요 내용: {'주요 내용', 휴먼명조, 11pt}"
    "</hp:t></hp:run></hp:p></hs:sec>"
)


def run_template_fill(rep: Report) -> None:
    """006 — 여러 턴. 세션 id 로 대화가 이어지는지가 관건이다."""
    template_dir = tempfile.mkdtemp(prefix="sfr006_direct_")
    os.environ["TEMPLATE_FILL_TEMPLATE_DIR"] = template_dir
    with zipfile.ZipFile(os.path.join(template_dir, "주간보고.hwpx"), "w") as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("Contents/section0.xml", _SECTION.encode("utf-8"))
        zf.writestr("Contents/header.xml", '<?xml version="1.0" encoding="UTF-8"?><h/>')

    sys.path.insert(0, unit_dir("SFR-006_template_fill"))
    import types

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from template_fill import chat_api, doc_prefill, file_store, redis_client, session_store, \
        template_index
    from template_fill.api_errors import install as install_error_handler
    from template_fill.chat_api import install as install_chat_api
    from template_fill.chat_direct import install as install_chat_direct

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

    fake_redis = FakeRedis()
    redis_client.resolve_client = lambda: fake_redis
    session_store.resolve_client = redis_client.resolve_client
    template_index.resolve_client = redis_client.resolve_client

    script: list = []
    calls: list = []

    async def fake_llm(system_prompt, user_prompt, **_kwargs):
        calls.append(user_prompt)
        content = json.dumps(script.pop(0), ensure_ascii=False) if script else "{}"
        return types.SimpleNamespace(ok=True, content=content, error_type="",
                                     is_transport_error=False)

    async def fake_stream(system_prompt, user_prompt, on_delta):
        result = await fake_llm(system_prompt, user_prompt)
        await on_delta(result.content)
        return result

    async def fake_upload(data, filename, media_type):
        return _CDN_LINK

    chat_api.llm_call_async = fake_llm
    doc_prefill.llm_call_async = fake_llm
    doc_prefill.llm_stream_async = fake_stream
    file_store.upload_bytes = fake_upload
    if hasattr(chat_api, "file_store"):
        chat_api.file_store.upload_bytes = fake_upload

    app = FastAPI()
    install_error_handler(app)
    install_chat_api(app)
    install_chat_direct(app)

    with TestClient(app) as c:
        script.append({"updates": {"제 목": "10월 둘째 주 보고"}})
        r = c.post("/chat", json={"stream": True, "socketIOClientId": "sess-1",
                                  "question": "template_id: 주간보고\n\n제목은 10월 둘째 주 보고로 해줘"})
        fs = frames(r)
        names = [e for e, _ in fs]
        result = complete(fs) or {}
        rep.expect("SSE token → complete → end", r.status_code == 200 and names[-2:] == ["complete", "end"]
                   and "token" in names, names[-4:])
        rep.expect("모든 프레임이 {event, data} 한 줄이다", fs and all(e != "?" for e, _ in fs))
        rep.expect("complete 에 text 가 없고 template_id·session_id 가 있다",
                   "text" not in result and result.get("template_id") == "주간보고"
                   and result.get("session_id") == "sess-1", result)
        rep.expect("다 채우기 전에는 download_url 이 없다", result.get("download_url") is None, result)
        rep.expect("답변에 미리보기가 붙는다", "미리보기" in tokens(fs) and "10월 둘째 주 보고" in tokens(fs),
                   tokens(fs)[:120])

        script.append({"updates": {"주요 내용": "배포 완료"}})
        r = c.post("/chat", json={"stream": False, "socketIOClientId": "sess-1",
                                  "question": "주요 내용은 배포 완료"})
        body = r.json()
        rep.expect("다음 턴은 세션의 템플릿을 이어 쓴다 (JSON)",
                   r.status_code == 200 and body.get("template_id") == "주간보고"
                   and "배포 완료" in body.get("text", ""), f"HTTP {r.status_code} {body.get('template_id')}")
        rep.expect("다 채우면 download_url 이 나온다", body.get("download_url") == _CDN_LINK,
                   body.get("download_url"))

        script.append({"updates": {"제 목": "머리말 세션"}})
        r = c.post("/chat", json={"stream": False, "question":
                                  "session_id: sess-2\ntemplate_id: 주간보고\n\n제목은 머리말 세션"})
        rep.expect("머리말 session_id 도 세션으로 받는다",
                   r.status_code == 200 and r.json().get("session_id") == "sess-2", r.json().get("session_id"))

        script.append({"updates": {}})
        r = c.post("/chat", json={"stream": False, "question": "template_id: 주간보고\n\n안녕"})
        body = r.json()
        rep.expect("세션이 없으면 세우지 않고 안내를 붙인다",
                   r.status_code == 200 and "session_id" not in body and "⚠" in body.get("text", ""),
                   f"HTTP {r.status_code}")

        r = c.post("/chat", json={"stream": True, "socketIOClientId": "sess-3",
                                  "question": "template_id: 없는양식\n\n안녕"})
        fs = frames(r)
        error = (complete(fs) or {}).get("error") or {}
        rep.expect("없는 템플릿은 SSE 오류 프레임", r.status_code == 200 and bool(error.get("error_code"))
                   and tokens(fs) == error.get("msg"), error)
        r = c.post("/chat", json={"stream": False, "socketIOClientId": "sess-3",
                                  "question": "template_id: 없는양식\n\n안녕"})
        body = r.json()
        rep.expect("없는 템플릿은 JSON 오류 (상태코드 + text·error)",
                   r.status_code >= 400 and body.get("text") == (body.get("error") or {}).get("msg"),
                   f"HTTP {r.status_code}")

        script.append({"updates": {}})
        r = c.post("/chat", json={"stream": False, "socketIOClientId": "sess-4", "question":
                                  "template_id: 주간보고\n\n[입력된 문서]\n[[GENON_SCAN doc=a1 page=1 image=http://cdn/a.png]]"})
        rep.expect("스캔 표식은 자동 채움만 건너뛰고 대화는 계속한다",
                   r.status_code == 200 and "스캔" in r.json().get("text", ""), f"HTTP {r.status_code}")

        r = c.post("/chat", content=b"not json", headers={"content-type": "application/json"})
        rep.expect("JSON 이 아닌 본문은 400", r.status_code == 400, f"HTTP {r.status_code}")


_RUNNERS = {
    "SFR-006_template_fill": run_template_fill,
}


# ─────────────────────────────────────────────────────────────
# 부모/자식
# ─────────────────────────────────────────────────────────────
def _child(unit: str) -> int:
    os.environ.update(_ENV)
    rep = Report(unit)
    try:
        _RUNNERS[unit](rep)
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 부모에게 행으로 넘긴다
        import traceback

        rep.rows.append(("FAIL", f"[{unit}] 점검 중 예외", f"{type(exc).__name__}: {exc} "
                         + traceback.format_exc().splitlines()[-3]))
    sys.stdout.write("\n__CHAT_DIRECT__" + json.dumps(rep.rows, ensure_ascii=False) + "\n")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    units = ["SFR-006_template_fill"]
    rows: list = []
    for unit in units:
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--child", unit],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=300,
        )
        line = next((l for l in proc.stdout.splitlines() if l.startswith("__CHAT_DIRECT__")), "")
        if not line:
            tail = ((proc.stderr or "") + (proc.stdout or "")).strip().splitlines()[-3:]
            rows.append(("FAIL", f"[{unit}] 기동", " / ".join(tail)))
            continue
        rows += json.loads(line[len("__CHAT_DIRECT__"):])
    ok = sum(1 for status, *_ in rows if status == "OK")
    fail = len(rows) - ok
    for status, name, detail in rows:
        print(f"[{status:4}] {name}" + ("" if status == "OK" else f"  — {detail}"))
    print(f"\nOK {ok} / {len(rows)}" + (f"  FAIL {fail}" if fail else ""))
    return 1 if fail else 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        sys.exit(_child(sys.argv[2]))
    sys.exit(main())
