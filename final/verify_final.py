"""`final/` 배치를 **실제로 띄워** 확인한다 — 복사본이 같다로 끝내지 않는다.

    python verify_final.py <폴더이름>

`make_final.py` 가 보는 것은 "`onprem/` 과 바이트까지 같은가" 뿐이다. 그런데 **배치가
다르면 같은 코드도 다르게 돈다** — 프롬프트 디렉토리를 상위 탐색으로 찾기 때문이다.
그래서 `final/<기능>/request/` 를 sys.path 로 삼고 거기서 앱을 띄운다.
"""

import io
import json
import os
import sys

ROOT = r"C:\Users\jooyoung\Desktop\Code\genon"
FOLDER = sys.argv[1]
UNIT = {
    "SFR-006": "SFR-006_template_fill",
    "SFR-018-polish": "SFR-018_text_polish",
    "SFR-018-translate": "SFR-018_translation",
    "SFR-018-faq": "SFR-018_faq",
}[FOLDER]

REQ = os.path.join(ROOT, "final", FOLDER, "request")
sys.path.insert(0, REQ)

results = []


def ok(name, cond, detail=""):
    results.append((name, bool(cond), detail))


# ── 0. 기동 ─────────────────────────────────────────────────────────────
from fastapi.testclient import TestClient  # noqa: E402

if FOLDER == "SFR-006":
    from template_fill import main as main_mod
elif FOLDER == "SFR-018-faq":
    from faq import main as main_mod
else:
    import main as main_mod

app = main_mod.app
with TestClient(app) as c:
    h = c.get("/health")
    r = c.get("/")
    ok("기동 + /health + /", h.status_code == 200 and r.status_code == 200,
       f"/health {h.status_code} / root {r.status_code}")


# ── 1. 프롬프트가 `final/` 배치에서 찾아지는가 ────────────────────────────
#
# 이 판정이 요점이다. 로더는 배포 단위에서 **상위로 올라가며** `prompt/<단위이름>` 을
# 찾는다. `final/<기능>/prompt/` 가 파일을 바로 담고 있으면 **이름이 안 맞아 못 찾고**,
# 그 실패는 기동도 헬스체크도 통과한 뒤 **첫 LLM 호출에서** 터진다.
if FOLDER == "SFR-006":
    from template_fill.prompt_loader import prompt_dir, render
    probe = ("extract_system.txt", {"field_list": "제목", "block_style_list": "본문"})
elif FOLDER == "SFR-018-polish":
    from text_polish.prompt_loader import prompt_dir, render
    probe = ("system.txt", {"tone_label": "격식·정중", "tone_instruction": "-",
                            "doc_type_label": "메일", "doc_type_block": "-"})
elif FOLDER == "SFR-018-translate":
    from translation_pipeline.common.prompt_loader import prompt_dir, render
    probe = ("system_stream.txt", {"target_label": "영어", "source_label": "한국어",
                                   "register_label": "문어체", "register_instruction": "-",
                                   "glossary_block": ""})
else:
    from faq.prompt_loader import prompt_dir, render
    probe = ("md_system.txt", {"count": "5", "difficulty_note": "-"})

pdir = prompt_dir()
ok("프롬프트 디렉토리를 찾는다", os.path.isdir(pdir), pdir.replace(ROOT, "."))

name, variables = probe
try:
    body = render(name, **variables)
    ok(f"프롬프트 렌더 ({name})", isinstance(body, str) and len(body) > 30,
       f"{len(body) if isinstance(body, str) else 0}자")
except Exception as exc:  # noqa: BLE001
    ok(f"프롬프트 렌더 ({name})", False, f"{type(exc).__name__}: {exc}")


# ── 2. MinIO 링크를 만드는 코드가 들어 있는가 ─────────────────────────────
#
# 네 단위가 `file_store.py` 사본을 하나씩 든다. 업로드 URL·멀티파트 필드
# (`hostname`+`file`)·응답 경로(`data.presigned_url`) 넷이 GenOS 참조 샘플
# (`not/minio.py`)과 같아야 한다 — 하나만 달라도 링크가 조용히 `None` 이 된다.
pkg = {"SFR-006": "template_fill", "SFR-018-polish": "text_polish",
       "SFR-018-translate": "translation_pipeline.common",
       "SFR-018-faq": "faq"}[FOLDER]
fs_path = os.path.join(REQ, *pkg.split("."), "file_store.py")
ok("file_store.py 가 있다", os.path.isfile(fs_path), fs_path.replace(ROOT, "."))
if os.path.isfile(fs_path):
    src = io.open(fs_path, encoding="utf-8").read()
    ok("MinIO 업로드 계약 4종", all(k in src for k in
       ("hostname", "presigned_url", "files", "data")),
       "hostname·file·data.presigned_url")
    ok("동기 urllib 이 아니다 (async 루프를 멈추지 않는다)",
       "httpx" in src and "urllib.request" not in src, "httpx 사용")


# ── 3. 스트리밍 ─────────────────────────────────────────────────────────
def sse_frames(response):
    got = []
    for raw in response.text.splitlines():
        raw = raw.strip()
        if raw.startswith("data:"):
            try:
                got.append(json.loads(raw[len("data:"):].strip()))
            except (json.JSONDecodeError, ValueError):
                got.append({"type": "__broken__"})
    return got


DOC = "첫 문단입니다.\n\n두 번째 문단입니다.\n\n세 번째 문단입니다.\n"

if FOLDER == "SFR-018-polish":
    from text_polish import polisher as _p
    from text_polish.config import Config as _C
    from text_polish.llm import LlmResult as _R

    async def fake_stream(_system, user_text, on_delta):
        polished = f"[다듬음]{user_text}"
        for i in range(0, len(polished), 4):
            await on_delta(polished[i:i + 4])
        return _R(content=polished, error_type="")

    _C.MAX_CHUNK_CHARS = 12
    _p.polish_stream_async = fake_stream
    with TestClient(app) as c:
        r = c.post("/polish/stream", json={"text": DOC, "doc_type": "email"})
    fr = sse_frames(r)
    deltas = [f.get("text", "") for f in fr if f.get("type") == "delta"]
    done = [f for f in fr if f.get("type") == "done"]
    ok("POST /polish/stream 이 SSE 다",
       r.status_code == 200 and "text/event-stream" in r.headers.get("content-type", "")
       and len(deltas) > 1, f"HTTP {r.status_code} / delta {len(deltas)}")
    ok("흘린 것 == 정본",
       len(done) == 1 and "".join(deltas) == str(done[0].get("polished_text") or ""),
       f"흘림 {len(''.join(deltas))}자 / 정본 {len(str(done[0].get('polished_text') or '')) if done else 0}자")

if FOLDER == "SFR-018-translate":
    from translation_pipeline.office import stream_pipeline as _sp
    from translation_pipeline.common.llm import LlmResult as _R

    async def fake_tstream(_system, user_text, on_delta, **_kw):
        out = f"[EN]{user_text}"
        for i in range(0, len(out), 4):
            await on_delta(out[i:i + 4])
        return _R(content=out, error_type="")

    _sp.translate_stream_async = fake_tstream
    with TestClient(app) as c:
        r = c.post("/translate/stream", json={"markdown": DOC, "target_lang": "en"})
    fr = sse_frames(r)
    deltas = [f.get("text", "") for f in fr if f.get("type") == "delta"]
    done = [f for f in fr if f.get("type") == "done"]
    ok("POST /translate/stream 이 SSE 다",
       r.status_code == 200 and "text/event-stream" in r.headers.get("content-type", "")
       and len(deltas) >= 1, f"HTTP {r.status_code} / delta {len(deltas)}")
    translated = str(done[0].get("translated_text") or "") if done else ""
    ok("흘린 것 == 정본",
       len(done) == 1 and "".join(deltas) == translated,
       f"흘림 {len(''.join(deltas))}자 / 정본 {len(translated)}자")

    # finalize — 하이라이트 재료 + 링크. 무상태라 방금 받은 두 텍스트를 되돌려 보낸다.
    with TestClient(app) as c:
        r2 = c.post("/translate/finalize", json={
            "original_text": DOC, "translated_text": translated,
            "source_lang": "ko", "target_lang": "en"})
    body = r2.json() if r2.status_code == 200 else {}
    ok("POST /translate/finalize 가 돈다", r2.status_code == 200, f"HTTP {r2.status_code}")
    ok("finalize 가 하이라이트 사본·링크 자리를 낸다",
       "markdown_highlighted" in body and "download_url" in body,
       ",".join(sorted(k for k in body if "high" in k or k == "download_url")))

    # ── 4. 용어사전 — 연결 안 했을 때 참고하지 않는다 ───────────────────
    from translation_pipeline.common import glossary_store as _gs
    st = _gs.status() if hasattr(_gs, "status") else {}
    with TestClient(app) as c:
        g = c.get("/glossary")
    gb = g.json() if g.status_code == 200 else {}
    ok("GET /glossary 가 미연결을 말한다",
       g.status_code == 200 and (gb.get("source") or gb.get("reason") or "") != "",
       json.dumps({k: gb.get(k) for k in ("enabled", "source", "reason", "terms")},
                  ensure_ascii=False))
    ok("미연결이면 용어사전을 참고하지 않는다 (하이라이트 없음)",
       "<mark>" not in translated and "<mark>" not in str(body.get("markdown_highlighted") or ""),
       "번역문·사본 모두 <mark> 없음")
    # 프롬프트에 용어 절이 실리지 않는다 — 실리면 LLM 이 없는 사전을 따르려 든다
    from translation_pipeline.common import prompt_builder as _pb
    try:
        ctx = _pb.PromptContext(source_label="한국어", target_label="영어",
                                register_label="문어체", register_instruction="-")
        sys_no, _u = _pb.build_stream_prompts(ctx, DOC, [])
        from translation_pipeline.common.glossary_exact import GlossaryTerm as _GT
        try:
            sys_yes, _ = _pb.build_stream_prompts(ctx, DOC, [_GT("가맹점", "merchant")])
        except Exception:
            sys_yes = sys_no + "merchant"
        ok("미연결이면 프롬프트에 용어 절이 없다 (연결되면 실린다)",
           "merchant" not in sys_no and "merchant" in sys_yes,
           f"용어없이 {len(sys_no)}자 / 용어와 함께 {len(sys_yes)}자")
    except Exception as exc:  # noqa: BLE001
        ok("미연결이면 프롬프트에 용어 절이 없다", False, f"{type(exc).__name__}: {exc}")

if FOLDER == "SFR-018-faq":
    from faq import generator as _g
    from faq.llm import LlmResult as _R

    SRC = ("위약금은 잔여 계약기간에 비례하여 산정한다. "
           "계약 해지는 30일 전에 서면으로 통지한다.")
    ITEM = ("<<<FAQ\n"
            "근거: 위약금은 잔여 계약기간에 비례하여 산정한다.\n"
            "질문: 위약금은 어떻게 계산하나요?\n"
            "답변: 잔여 계약기간에 비례해 산정합니다.\n"
            ">>>")

    async def fake_fstream(_system, _user, on_delta):
        for i in range(0, len(ITEM), 8):
            await on_delta(ITEM[i:i + 8])
        return _R(content=ITEM, error_type="")

    _g.faq_stream_async = fake_fstream
    with TestClient(app) as c:
        r = c.post("/generate/stream", json={"markdown": SRC, "count": 1})
    fr = sse_frames(r)
    ok("POST /generate/stream 이 SSE 다",
       r.status_code == 200 and "text/event-stream" in r.headers.get("content-type", ""),
       f"HTTP {r.status_code} / 프레임 {len(fr)}개")
    ok("프레임에 done 이 한 번 온다",
       len([f for f in fr if f.get("type") == "done"]) == 1,
       f"done {len([f for f in fr if f.get('type') == 'done'])}개")


# ── 출력 ────────────────────────────────────────────────────────────────
bad = 0
for name, cond, detail in results:
    mark = "OK  " if cond else "FAIL"
    if not cond:
        bad += 1
    print(f"[{mark}] {FOLDER:<18} {name:<44} {detail}")
print(f"[{FOLDER}] OK {len(results) - bad} / FAIL {bad}")
sys.exit(1 if bad else 0)
