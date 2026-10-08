"""젠포탈 직접 호출 `POST /chat` 점검 — no_pythonstep 단위가 SSE 를 직접 낸다.

```
python Test/check/check_chat_direct.py
```

서버·Redis·LLM·CDN 불필요. `TestClient` 로 인프로세스 호출한다.
018 세 단위(번역·글다듬이·FAQ)는 늘 보고, 006 은 `GENON_SFR006_SOURCE=no_pythonstep` 일 때만 본다
(`paths.SFR006_SOURCE` — 기본은 final 이고 final 006 에는 `/chat` 직접 호출이 없다).

대역은 단위 **밖에서** 꽂는다. 018 은 `httpx.AsyncClient` 에 `MockTransport` 를 씌워 게이트웨이
(LLM·MCP)와 CDN 업로드를 흉내 낸다 — URL 조립·재시도·스트림 해석이 실제 코드로 돈다.
006 은 `check_chat_turn` 과 같은 자리(LLM 함수·Redis 클라이언트)에 꽂는다.

단위마다 subprocess 로 띄운다 — 네 단위가 최상위 `main`·`config`·`chat_api` 이름을 겹쳐 쓴다.
"""

import json
import os
import subprocess
import sys
import tempfile
import zipfile

from paths import SFR006_SOURCE, unit_dir  # noqa: E402

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
# 공통 — 게이트웨이 대역 · SSE 해석 · 판정
# ─────────────────────────────────────────────────────────────
class Gateway:
    """`httpx.AsyncClient` 가 보내는 요청을 URL 로 갈라 답한다."""

    def __init__(self) -> None:
        self.reply = ""
        self.llm_status = 200
        self.upload_status = 200
        self.guard_issues: dict = {}
        self.llm_calls: list = []

    def route(self, request):
        import httpx

        url = str(request.url)
        if url.startswith("http://cdn.test"):
            if self.upload_status != 200:
                return httpx.Response(self.upload_status, json={})
            return httpx.Response(200, json={"data": {"presigned_url": _CDN_LINK}})
        if "/mcp/" in url:
            body = json.loads(request.content or b"{}")
            tool = body.get("params", {}).get("name", "")
            text = json.dumps({"issues": self.guard_issues.get(tool, [])}, ensure_ascii=False)
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1,
                           "result": {"content": [{"type": "text", "text": text}]}},
            )
        if url.endswith("/chat/completions"):
            body = json.loads(request.content or b"{}")
            self.llm_calls.append(body)
            if self.llm_status != 200:
                return httpx.Response(self.llm_status, json={"error": "down"})
            if body.get("stream"):
                frames = [
                    "data: " + json.dumps(
                        {"choices": [{"delta": {"content": self.reply[i:i + 5]}}]},
                        ensure_ascii=False,
                    ) + "\n\n"
                    for i in range(0, len(self.reply), 5)
                ]
                return httpx.Response(
                    200, headers={"content-type": "text/event-stream"},
                    content=("".join(frames) + "data: [DONE]\n\n").encode("utf-8"),
                )
            return httpx.Response(200, json={"choices": [{"message": {"content": self.reply}}]})
        return httpx.Response(404, json={})

    def user_prompts(self) -> str:
        return "\n".join(
            str(m.get("content") or "")
            for call in self.llm_calls for m in call.get("messages", []) if m.get("role") == "user"
        )


def install_gateway(gateway: Gateway) -> None:
    import httpx

    real = httpx.AsyncClient

    class _Mocked(real):
        def __init__(self, **kwargs):
            kwargs.pop("timeout", None)
            kwargs.pop("transport", None)
            super().__init__(transport=httpx.MockTransport(gateway.route), **kwargs)

    httpx.AsyncClient = _Mocked


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


def check_success_stream(rep: Report, client, question: str, keys: set, link_text: str,
                         reply_marker: str) -> list:
    """정상 스트리밍 한 건 — 모든 단위가 같은 프레임 규약을 지킨다."""
    r = client.post("/chat", json={"question": question, "stream": True})
    fs = frames(r)
    rep.expect("SSE 로 답한다", r.status_code == 200
               and r.headers.get("content-type", "").startswith("text/event-stream"),
               f"HTTP {r.status_code} {r.headers.get('content-type')}")
    rep.expect("모든 프레임이 {event, data} 한 줄이다", fs and all(e != "?" for e, _ in fs),
               [d for e, d in fs if e == "?"][:1])
    names = [e for e, _ in fs]
    rep.expect("token → complete → end 순서로 끝난다",
               len(names) >= 3 and names[-2:] == ["complete", "end"] and "token" in names[:-2],
               names[-5:])
    result = complete(fs) or {}
    rep.expect("complete 에 text 가 없다 (채팅이 다시 그리지 않는다)", "text" not in result,
               sorted(result))
    rep.expect("complete 에 결과 값이 있다", keys <= set(result), sorted(result))
    rep.expect("complete 의 download_url 이 업로드 링크다", result.get("download_url") == _CDN_LINK,
               result.get("download_url"))
    shown = tokens(fs)
    rep.expect("token 으로 결과 글이 흐른다", reply_marker in shown, shown[:80])
    rep.expect("token 끝에 내려받기 링크가 붙는다", f"[{link_text}]({_CDN_LINK})" in shown, shown[-120:])
    return fs


def check_error_stream(rep: Report, client, name: str, question: str, msg_part: str = "") -> None:
    """입력 오류도 HTTP 200 SSE — 문구는 token, 값은 complete.error, 마지막은 end."""
    r = client.post("/chat", json={"question": question, "stream": True})
    fs = frames(r)
    result = complete(fs) or {}
    error = result.get("error") or {}
    ok = (r.status_code == 200 and [e for e, _ in fs][-1:] == ["end"]
          and bool(error.get("error_code")) and bool(error.get("msg"))
          and tokens(fs) == error.get("msg") and (msg_part in error.get("msg", "")))
    rep.expect(f"{name} — SSE 오류 프레임 (token·complete.error·end)", ok,
               f"HTTP {r.status_code} {[e for e, _ in fs]} {error}")


def check_error_json(rep: Report, client, name: str, question: str, statuses=(400, 422)) -> None:
    r = client.post("/chat", json={"question": question, "stream": False})
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    error = body.get("error") or {}
    rep.expect(f"{name} — JSON 오류 (상태코드 + text·error)",
               r.status_code in statuses and body.get("text") == error.get("msg")
               and bool(error.get("error_code")),
               f"HTTP {r.status_code} {body}")


def check_common_transport(rep: Report, client, ok_question: str, gateway: Gateway) -> None:
    """이벤트 이름·heartbeat·본문 형식 — 네 단위 공통 환경변수 계약."""
    r = client.post("/chat", content=b"not json", headers={"content-type": "application/json"})
    body = r.json()
    rep.expect("JSON 이 아닌 본문은 400 {text, error}",
               r.status_code == 400 and body.get("error", {}).get("msg") == body.get("text"),
               f"HTTP {r.status_code} {body}")

    r = client.post("/chat", json={"question": ok_question, "stream": "true"})
    rep.expect('stream 값 "true" 문자열도 스트리밍이다',
               r.headers.get("content-type", "").startswith("text/event-stream"),
               r.headers.get("content-type"))

    os.environ["CHAT_HEARTBEAT_SECONDS"] = "5"
    try:
        fs = frames(client.post("/chat", json={"question": ok_question, "stream": True}))
    finally:
        os.environ["CHAT_HEARTBEAT_SECONDS"] = "0"
    first = fs[0] if fs else ("", None)
    rep.expect("heartbeat 를 켜면 시작에 한 번 보낸다",
               first[0] == "heartbeat" and isinstance(first[1], dict)
               and isinstance(first[1].get("elapsed_seconds"), int), fs[:1])

    fs = frames(client.post("/chat", json={"question": ok_question, "stream": True}))
    rep.expect("heartbeat 를 끄면(0) 보내지 않는다", all(e != "heartbeat" for e, _ in fs),
               [e for e, _ in fs][:3])

    os.environ.update({"CHAT_TOKEN_EVENT": "delta", "CHAT_RESULT_EVENT": "result",
                       "CHAT_END_EVENT": ""})
    try:
        fs = frames(client.post("/chat", json={"question": ok_question, "stream": True}))
    finally:
        for key in ("CHAT_TOKEN_EVENT", "CHAT_RESULT_EVENT", "CHAT_END_EVENT"):
            os.environ.pop(key, None)
    names = [e for e, _ in fs]
    rep.expect("이벤트 이름을 환경변수로 바꾸고 end 를 끌 수 있다",
               "delta" in names and names[-1:] == ["result"] and "token" not in names
               and "end" not in names, names[-4:])

    gateway.upload_status = 500
    try:
        fs = frames(client.post("/chat", json={"question": ok_question, "stream": True}))
    finally:
        gateway.upload_status = 200
    result = complete(fs) or {}
    rep.expect("업로드 실패는 결과를 버리지 않는다 (download_url None)",
               "download_url" in result and result["download_url"] is None
               and "error" not in result and "내려받기" not in tokens(fs),
               result)


# ─────────────────────────────────────────────────────────────
# 단위별
# ─────────────────────────────────────────────────────────────
def run_translation(rep: Report) -> None:
    gateway = Gateway()
    install_gateway(gateway)
    sys.path.insert(0, unit_dir("SFR-018_translation"))
    from fastapi.testclient import TestClient

    import main

    gateway.reply = "Hello. The meeting starts at three in the afternoon."
    ok_q = "target_lang: en\ntitle: 보도자료\n\n안녕하세요. 회의는 오후 세 시에 시작합니다."
    with TestClient(main.app) as c:
        check_success_stream(rep, c, ok_q, {"original_text", "translated_text", "download_url"},
                             "번역 결과 내려받기 (.md)", "Hello.")
        prompts = gateway.user_prompts()
        rep.expect("머리말 줄은 옵션이고 원문에 섞이지 않는다",
                   "회의는 오후" in prompts and "target_lang" not in prompts, prompts[:80])

        r = c.post("/chat", json={"question": ok_q, "stream": False})
        body = r.json()
        rep.expect("stream:false 는 text 를 실은 JSON 이다",
                   r.status_code == 200 and "Hello." in body.get("text", "")
                   and _CDN_LINK in body.get("text", "")
                   and {"original_text", "translated_text", "download_url"} <= set(body),
                   f"HTTP {r.status_code} {sorted(body)}")

        r = c.post("/chat", json={"question": json.dumps(
            {"target_lang": "en", "text": "안녕하세요. 반갑습니다."}, ensure_ascii=False),
            "stream": False})
        rep.expect("question 이 JSON 문자열이어도 받는다", r.status_code == 200, f"HTTP {r.status_code}")

        r = c.post("/chat", json={"question": "안녕하세요.", "target_lang": "en", "stream": False})
        rep.expect("최상위 키가 옵션으로 쓰인다", r.status_code == 200, f"HTTP {r.status_code}")

        gateway.llm_calls.clear()
        c.post("/chat", json={"stream": True, "question": (
            "target_lang: en\n이 줄은 사용자 지시입니다\n[입력된 문서]\n"
            "<doc name='a.hwpx'>첨부 문서 본문입니다.</doc>")})
        prompts = gateway.user_prompts()
        rep.expect("[입력된 문서] 뒤 <doc> 안만 원문이다",
                   "첨부 문서 본문" in prompts and "사용자 지시" not in prompts
                   and "<doc" not in prompts, prompts[:80])

        gateway.llm_calls.clear()
        check_error_stream(rep, c, "대상 언어 누락", "안녕하세요.", "언어를 선택")
        rep.expect("입력 오류에서는 LLM 을 부르지 않는다", not gateway.llm_calls, len(gateway.llm_calls))
        check_error_json(rep, c, "대상 언어 누락", "안녕하세요.")
        os.environ["TRANSLATE_DEFAULT_TARGET_LANG"] = "en"
        try:
            r = c.post("/chat", json={"question": "안녕하세요.", "stream": False})
        finally:
            os.environ.pop("TRANSLATE_DEFAULT_TARGET_LANG", None)
        rep.expect("대상 언어가 없으면 TRANSLATE_DEFAULT_TARGET_LANG 을 쓴다",
                   r.status_code == 200, f"HTTP {r.status_code}")
        check_error_stream(rep, c, "한국어 축 위반 (en→ru)",
                           "target_lang: ru\n\nHello everyone, this is an English document.")
        check_error_json(rep, c, "한국어 축 위반 (en→ru)",
                         "target_lang: ru\n\nHello everyone, this is an English document.")
        check_error_stream(rep, c, "스캔 표식 거절",
                           "target_lang: en\n\n[[GENON_SCAN page=1 image=a/scan-p001.png]]", "스캔")
        check_error_stream(rep, c, "빈 본문", "target_lang: en\n\n")

        r = c.post("/chat", json={"question": "target_lang: en\n날짜: 2026-10-08\n회의록입니다.",
                                  "stream": False})
        rep.expect("본문 첫 줄 `날짜: …` 는 옵션으로 먹히지 않는다",
                   "날짜" in (r.json().get("original_text") or ""), r.json().get("original_text"))

        gateway.llm_status = 500
        try:
            check_error_stream(rep, c, "LLM 전량 실패", ok_q, "번역에 실패")
            check_error_json(rep, c, "LLM 전량 실패", ok_q, statuses=(502,))
        finally:
            gateway.llm_status = 200

        check_common_transport(rep, c, ok_q, gateway)


def run_polish(rep: Report) -> None:
    gateway = Gateway()
    install_gateway(gateway)
    sys.path.insert(0, unit_dir("SFR-018_text_polish"))
    from fastapi.testclient import TestClient

    import main

    gateway.reply = "회의는 오후 세 시에 시작합니다."
    ok_q = "title: 안내\n\n회의는 오후 세시에 시작 합니다."
    with TestClient(main.app) as c:
        check_success_stream(
            rep, c, ok_q,
            {"original_text", "polished_text", "download_url", "doc_type", "tone", "tone_overridden"},
            "다듬은 결과 내려받기 (.md)", "회의는 오후 세 시에")

        r = c.post("/chat", json={"question": ok_q, "stream": False})
        body = r.json()
        rep.expect("stream:false 는 text 를 실은 JSON 이다",
                   r.status_code == 200 and "회의는 오후 세 시에" in body.get("text", "")
                   and body.get("polished_text") == gateway.reply,
                   f"HTTP {r.status_code} {sorted(body)}")

        gateway.llm_calls.clear()
        c.post("/chat", json={"stream": True, "question": (
            "이 줄은 사용자 지시입니다\n[입력된 문서]\n<doc>첨부 문서 본문입니다.</doc>")})
        prompts = gateway.user_prompts()
        rep.expect("[입력된 문서] 뒤만 다듬는다",
                   "첨부 문서 본문" in prompts and "사용자 지시" not in prompts, prompts[:80])

        gateway.guard_issues = {"markdown_structure_issues": ["표 열 수가 다릅니다"],
                                "fact_issues": ["숫자 3 이 사라졌습니다"]}
        try:
            fs = frames(c.post("/chat", json={"question": ok_q, "stream": True}))
        finally:
            gateway.guard_issues = {}
        notices = (complete(fs) or {}).get("notice") or []
        rep.expect("text_guard MCP 결과가 안내문이 된다 (구조·숫자)",
                   any("문서 구조" in n for n in notices) and any("숫자" in n for n in notices),
                   notices)

        os.environ.pop("TEXT_GUARD_MCP_ID", None)
        try:
            r = c.post("/chat", json={"question": ok_q, "stream": False})
        finally:
            os.environ["TEXT_GUARD_MCP_ID"] = _ENV["TEXT_GUARD_MCP_ID"]
        rep.expect("TEXT_GUARD_MCP_ID 가 없어도 결과는 낸다", r.status_code == 200, f"HTTP {r.status_code}")

        check_error_stream(rep, c, "빈 본문", "title: 안내\n\n")
        check_error_json(rep, c, "빈 본문", "title: 안내\n\n")
        check_error_stream(rep, c, "스캔 표식 거절",
                           "[[GENON_SCAN page=1 image=a/scan-p001.png]]")
        check_error_json(rep, c, "스캔 표식 거절", "[[GENON_SCAN page=1 image=a/scan-p001.png]]")

        gateway.llm_status = 500
        try:
            check_error_stream(rep, c, "LLM 전량 실패", ok_q)
            check_error_json(rep, c, "LLM 전량 실패", ok_q, statuses=(500, 502, 504))
        finally:
            gateway.llm_status = 200

        check_common_transport(rep, c, ok_q, gateway)


_FAQ_DOC = "수수료는 매월 25일에 정산합니다. 정산 내역은 포털에서 확인할 수 있습니다."
_FAQ_REPLY = ("<<<FAQ\n근거: 수수료는 매월 25일에 정산합니다.\n질문: 수수료 정산일은 언제인가요?\n"
              "답변: 매월 25일에 정산합니다.\n>>>\n")


def run_faq(rep: Report) -> None:
    gateway = Gateway()
    install_gateway(gateway)
    sys.path.insert(0, unit_dir("SFR-018_faq"))
    from fastapi.testclient import TestClient

    import main

    gateway.reply = _FAQ_REPLY
    ok_q = f"faq_count: 1\ntitle: 정산 FAQ\n\n[입력된 문서]\n<doc>{_FAQ_DOC}</doc>"
    with TestClient(main.app) as c:
        fs = check_success_stream(rep, c, ok_q, {"faq_items", "download_url"},
                                  "FAQ 내려받기 (.md)", "매월 25일에 정산합니다")
        items = (complete(fs) or {}).get("faq_items") or []
        rep.expect("faq_items 에 근거 확인된 항목이 실린다",
                   len(items) == 1 and "정산일" in json.dumps(items, ensure_ascii=False), items)

        r = c.post("/chat", json={"question": ok_q, "stream": False})
        body = r.json()
        rep.expect("stream:false 는 text 를 실은 JSON 이다",
                   r.status_code == 200 and "정산일" in body.get("text", "")
                   and len(body.get("faq_items") or []) == 1, f"HTTP {r.status_code} {sorted(body)}")

        gateway.llm_calls.clear()
        c.post("/chat", json={"stream": False, "question": (
            f"faq_count: 1\n이 줄은 사용자 지시입니다\n[입력된 문서]\n<doc>{_FAQ_DOC}</doc>")})
        prompts = gateway.user_prompts()
        rep.expect("[입력된 문서] 뒤 <doc> 안만 원문이다",
                   "포털에서 확인" in prompts and "사용자 지시" not in prompts, prompts[:80])

        r = c.post("/chat", json={"question": "faq_count: 1", "genosUploaded": _FAQ_DOC,
                                  "stream": False})
        rep.expect("최상위 genosUploaded 를 원문으로 쓴다", r.status_code == 200, f"HTTP {r.status_code}")

        gateway.reply = ("<<<FAQ\n근거: 문서에 없는 문장입니다.\n질문: 지어낸 질문?\n"
                         "답변: 지어낸 답.\n>>>\n")
        try:
            r = c.post("/chat", json={"question": ok_q, "stream": False})
        finally:
            gateway.reply = _FAQ_REPLY
        rep.expect("근거가 문서에 없으면 항목을 싣지 않는다",
                   r.status_code >= 400 or not r.json().get("faq_items"), f"HTTP {r.status_code}")

        check_error_stream(rep, c, "빈 문서", "faq_count: 3\n\n")
        check_error_json(rep, c, "빈 문서", "faq_count: 3\n\n")
        check_error_stream(rep, c, "개수 0", f"faq_count: 0\n\n[입력된 문서]\n{_FAQ_DOC}", "1개 이상")
        check_error_stream(rep, c, "스캔 표식 거절",
                           "[입력된 문서]\n[[GENON_SCAN page=1 image=a/scan-p001.png]]", "스캔")

        gateway.llm_status = 500
        try:
            check_error_stream(rep, c, "LLM 전량 실패", ok_q)
            check_error_json(rep, c, "LLM 전량 실패", ok_q, statuses=(500, 502, 504))
        finally:
            gateway.llm_status = 200

        check_common_transport(rep, c, ok_q, gateway)


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
                                  "template_id: 주간보고\n\n[입력된 문서]\n[[GENON_SCAN page=1 image=a.png]]"})
        rep.expect("스캔 표식은 자동 채움만 건너뛰고 대화는 계속한다",
                   r.status_code == 200 and "스캔" in r.json().get("text", ""), f"HTTP {r.status_code}")

        r = c.post("/chat", content=b"not json", headers={"content-type": "application/json"})
        rep.expect("JSON 이 아닌 본문은 400", r.status_code == 400, f"HTTP {r.status_code}")


_RUNNERS = {
    "SFR-018_translation": run_translation,
    "SFR-018_text_polish": run_polish,
    "SFR-018_faq": run_faq,
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
    units = ["SFR-018_translation", "SFR-018_text_polish", "SFR-018_faq"]
    if SFR006_SOURCE == "no_pythonstep":
        units.append("SFR-006_template_fill")
    else:
        print("[SKIP] 006 은 final 기준이다 — GENON_SFR006_SOURCE=no_pythonstep 이면 함께 본다")
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
