"""병합 검증 — 대화 수정과 화면 직접 수정이 같은 세션을 번갈아 건드릴 때의 일관성.

두 경로를 한 배포 단위로 합쳤으므로, 한쪽이 쓴 값을 다른 쪽이 그대로 보고 이어서
고칠 수 있어야 한다. 세션 스키마(values/raw_values)를 한쪽만 갱신하면 여기서 깨진다.
"""
import asyncio
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture import bootstrap, install_fake_redis, make_fake_llm  # noqa: E402

TEMPLATE_DIR = bootstrap("tf_cross_", write_template=True)

from fastapi.testclient import TestClient  # noqa: E402

from template_fill import main as api, run_chat  # noqa: E402
from template_fill.config import Config  # noqa: E402

fake = install_fake_redis()
client = TestClient(api.app)

SESSION = "cross-1"
SESSION_KEY = f"{Config.REDIS_KEY_PREFIX}:{SESSION}"

stub = {"content": '{"updates": {}}'}
fake_llm = make_fake_llm(stub)
run_chat.llm_call_async = fake_llm


async def turn(question: str, reply_json: str) -> dict:
    stub["content"] = reply_json
    data = {
        "question": question,
        "genos_state": {"session_id": SESSION, "trace_id": "t"},
        "overrideConfig": {"vars": {"template_fill_template_id": "파워"}},
    }
    out = None
    async for event in run_chat.run(data):
        if event.get("event") == "result":
            out = event["data"]
    return out


def state() -> dict:
    raw = fake.store.get(SESSION_KEY)
    return json.loads(raw) if raw else {}


print("== 1) 대화로 채운다 ==")
res = asyncio.run(turn("제목은 초안 보고, 본문은 초안 내용",
                       '{"updates": {"제 목": "초안 보고", "본문": "초안 내용"}}'))
print("  대화 값:", res["field_values"])
assert state()["values"] == {"제 목": "초안 보고", "본문": "초안 내용"}

print("\n== 2) 화면 폼이 같은 세션을 고친다 ==")
patched = client.patch(
    "/values",
    json={"session_id": SESSION, "values": {"제 목": "2026년 상반기 실적 보고", "담당자": "왕주영"}},
).json()
print("  updated:", patched["updated_fields"], "값:", patched["values"])
assert state()["values"]["제 목"] == "2026년 상반기 실적 보고"
assert state()["raw_values"]["제 목"] == "2026년 상반기 실적 보고", "톤 원본이 갱신되지 않았다"

print("\n== 3) 다음 대화 턴이 폼 수정값을 그대로 본다 ==")
res = asyncio.run(turn("지금 상태 알려줘", '{"updates": {}}'))
print("  LLM 프롬프트에 실린 수집값:", "2026년 상반기 실적 보고" in fake_llm.last_user_prompt)
assert "2026년 상반기 실적 보고" in fake_llm.last_user_prompt, "대화가 폼 수정값을 못 봤다"
assert "왕주영" in res["text"], "현황표에 폼으로 넣은 값이 없다"
assert res["field_values"]["담당자"] == "왕주영"

print("\n== 4) 대화로 지운 값이 폼/미리보기에도 반영된다 ==")
res = asyncio.run(turn("담당자 지워줘", '{"clears": ["담당자"]}'))
print("  cleared:", res["fields_cleared"])
prev = client.get("/preview", params={"session_id": SESSION}).json()
assert "담당자" not in state()["values"]
assert "담당자" in prev["fields_missing"]
assert "왕주영" not in prev["markdown"]
assert [f["value"] for f in prev["fields"] if f["name"] == "담당자"] == [""]

print("\n== 5) 폼으로 지운 값이 다음 대화 턴에도 반영된다 ==")
client.patch("/values", json={"session_id": SESSION, "values": {"본문": ""}})
res = asyncio.run(turn("상태 확인", '{"updates": {}}'))
print("  본문 상태:", "본문" in res["fields_missing"])
assert "본문" in res["fields_missing"]
assert "초안 내용" not in fake_llm.last_user_prompt

print("\n== 6) 두 경로를 섞어 전부 채운 뒤 다운로드 ==")
asyncio.run(turn("본문은 매출이 12% 증가했다", '{"updates": {"본문": "매출이 전년 대비 12% 증가했다."}}'))
client.patch(
    "/values",
    json={
        "session_id": SESSION,
        "values": {"배포일": "2026. 8. 5. (수)", "담당자": "경영지원실 왕주영", "주요 내용": "신규 계약 3건."},
    },
)
status = client.get("/status", params={"session_id": SESSION}).json()
print("  ready:", status["ready_for_download"], "missing:", status["fields_missing"])
assert status["ready_for_download"] is True

prev = client.get("/preview", params={"session_id": SESSION}).json()
print("  --- 미리보기 ---")
print(prev["markdown"])
chat = asyncio.run(turn("", '{"updates": {}}'))
assert chat["document_markdown"] == prev["markdown"], "대화 미리보기와 /preview 가 다르다"

gen = client.post("/generate", json={"session_id": SESSION})
print("  다운로드:", gen.status_code, len(gen.content), "bytes, missing 헤더:", gen.headers.get("x-missing-fields"))
assert gen.status_code == 200 and gen.content[:2] == b"PK"
assert gen.headers["x-missing-fields"] == "", "전부 채웠는데 미입력이 남았다"
assert fake.store.get(SESSION_KEY) is None

print("\n== 7) 세션 종료 후 폼 수정은 새 세션으로 시작된다 ==")
after = client.patch("/values", json={"session_id": SESSION, "template_id": "파워", "values": {"제 목": "새 문서"}}).json()
print("  값:", after["values"], "missing:", after["fields_missing"])
assert after["values"] == {"제 목": "새 문서"}

shutil.rmtree(TEMPLATE_DIR, ignore_errors=True)
print("\nALL OK")
