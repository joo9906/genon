"""대화로 값 수정·삭제 스모크 — LLM 응답을 스텁으로 주입해 판정·표시·저장을 확인한다."""
import asyncio
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture import bootstrap, install_fake_redis, make_fake_llm  # noqa: E402

TEMPLATE_DIR = bootstrap("tf_chat_", write_template=True)

from template_fill import run_chat  # noqa: E402
from template_fill.config import Config  # noqa: E402
from template_fill.field_judge import parse_updates  # noqa: E402

fake = install_fake_redis()

SESSION = "chat-1"
SESSION_KEY = f"{Config.REDIS_KEY_PREFIX}:{SESSION}"

stub_reply = {"content": '{"updates": {}}'}
fake_llm = make_fake_llm(stub_reply)
run_chat.llm_call_async = fake_llm


async def turn(question: str, reply_json: str) -> dict:
    """한 턴 실행 → result 이벤트의 data."""
    stub_reply["content"] = reply_json
    data = {
        "question": question,
        "genos_state": {"session_id": SESSION, "trace_id": "t-1"},
        "overrideConfig": {"vars": {"template_fill_template_id": "파워"}},
    }
    result = None
    async for event in run_chat.run(data):
        if event.get("event") == "result":
            result = event["data"]
    return result


def session_values() -> dict:
    raw = fake.store.get(SESSION_KEY)
    return json.loads(raw)["values"] if raw else {}


print("== 0) 파서 단위 확인 ==")
allowed = {"제 목", "본문", "담당자"}
cases = [
    ('{"updates": {"제 목": "보고"}, "clears": ["담당자"]}', "정상"),
    ('{"clears": ["담당자"]}', "clears 만"),
    ('{"updates": {"제 목": ""}}', "빈 값 → 기각(추측 삭제 금지)"),
    ('{"updates": {"없는것": "x"}, "clears": ["없는것2"]}', "화이트리스트 밖"),
    ('{"updates": {"제 목": "A"}, "clears": ["제 목"]}', "모순 (파서가 수정 채택)"),
    ('{"clears": "담당자"}', "clears 배열 아님"),
    ("설명을 덧붙인 응답 {\"updates\": {\"본문\": \"B\"}} 입니다", "관대한 JSON 추출"),
    ("완전히 깨진 응답", "JSON 파싱 실패"),
]
for raw, label in cases:
    intent = parse_updates(raw, allowed)
    print(
        f"  {label:28} updates={intent.updates} clears={intent.clears}"
        f" rejected={intent.rejected} conflicts={intent.conflicts}"
    )

# 모순 해소는 파서 계약이다 — updates 와 clears 는 겹쳐서 나오지 않는다
_conflicted = parse_updates('{"updates": {"제 목": "A"}, "clears": ["제 목"]}', allowed)
assert _conflicted.updates == {"제 목": "A"} and _conflicted.clears == []
assert _conflicted.conflicts == ["제 목"]

assert parse_updates('{"clears": ["담당자"]}', allowed).clears == ["담당자"]
assert parse_updates('{"updates": {"제 목": ""}}', allowed).rejected == ["제 목"]
assert parse_updates('{"clears": "담당자"}', allowed).rejected == ["<clears: 배열 아님>"]
assert parse_updates("완전히 깨진 응답", allowed).rejected == ["<응답 전체: JSON 파싱 실패>"]
assert parse_updates('{"updates": "문자열"}', allowed).rejected == ["<updates: 객체 아님>"]
assert parse_updates("{}", allowed).rejected == ["<응답 전체: updates/clears 없음>"]

print("\n== 1) 첫 턴: 값 채우기 ==")
res = asyncio.run(turn("제목은 상반기 실적 보고, 본문은 매출이 12% 늘었다",
                       '{"updates": {"제 목": "상반기 실적 보고", "본문": "매출이 전년 대비 12% 증가했다."}}'))
print(res["text"].split("**작성 현황**")[0].strip())
print("  updated:", res["fields_updated"], "missing:", res["fields_missing"])
assert res["fields_updated"] == ["본문", "제 목"]
assert "다음 내용을 반영했습니다." in res["text"]
assert session_values()["제 목"] == "상반기 실적 보고"

print("\n== 2) 대화로 수정 — 이전 → 새 값 표시 ==")
res = asyncio.run(turn("제목을 2026년 상반기 실적 보고로 바꿔줘",
                       '{"updates": {"제 목": "2026년 상반기 실적 보고"}}'))
head = res["text"].split("**작성 현황**")[0].strip()
print(head)
assert "다음 항목을 고쳤습니다." in head
assert "상반기 실적 보고 → 2026년 상반기 실적 보고" in head, head
assert session_values()["제 목"] == "2026년 상반기 실적 보고"

print("\n== 3) 대화로 삭제 ==")
asyncio.run(turn("담당자는 왕주영", '{"updates": {"담당자": "왕주영"}}'))
res = asyncio.run(turn("담당자는 지워줘", '{"clears": ["담당자"]}'))
head = res["text"].split("**작성 현황**")[0].strip()
print(head)
print("  cleared:", res["fields_cleared"], "missing:", res["fields_missing"])
assert res["fields_cleared"] == ["담당자"]
assert "다음 항목을 비웠습니다." in head and "이전: 왕주영" in head
assert "담당자" not in session_values()
assert "담당자" in res["fields_missing"]

print("\n== 4) 세션에 없던 항목 삭제 요청 — 비웠다고 말하지 않는다 ==")
res = asyncio.run(turn("배포일 지워줘", '{"clears": ["배포일"]}'))
print("  cleared:", res["fields_cleared"])
assert res["fields_cleared"] == []
assert "다음 항목을 비웠습니다." not in res["text"]

print("\n== 5) 수정·삭제 모순 → 수정 채택 ==")
res = asyncio.run(turn("본문 고쳐줘 아니 지워줘",
                       '{"updates": {"본문": "고친 본문"}, "clears": ["본문"]}'))
print("  updated:", res["fields_updated"], "cleared:", res["fields_cleared"])
assert res["fields_updated"] == ["본문"] and res["fields_cleared"] == []
assert session_values()["본문"] == "고친 본문"

print("\n== 6) 템플릿에 없는 항목명은 기각하고 건수를 알린다 ==")
res = asyncio.run(turn("결재란도 채워줘", '{"updates": {"결재란": "x"}, "clears": ["없는것"]}'))
print("  rejected:", res["fields_rejected"])
assert sorted(res["fields_rejected"]) == ["결재란", "없는것"]
assert "반영하지 못한 내용이 2건" in res["text"]

print("\n== 7) 채운 문서 미리보기가 매 턴 실린다 ==")
print(res["document_markdown"])
assert "제 목 : 2026년 상반기 실적 보고" in res["document_markdown"]
assert "{" not in res["document_markdown"], "명세 표기가 미리보기에 남았다"
assert res["template_markdown"] and "{제목, HY헤드라인M, 16pt}" in res["template_markdown"], \
    "template_markdown 은 채우기 전 모양이어야 한다"
assert res["document_markdown_truncated"] is False

print("\n== 8) 미리보기 끄기 (TEMPLATE_FILL_CHAT_PREVIEW=0) ==")
Config.CHAT_PREVIEW = False
res = asyncio.run(turn("주요 내용은 신규 계약 3건", '{"updates": {"주요 내용": "신규 계약 3건 체결."}}'))
print("  document_markdown 길이:", len(res["document_markdown"]))
assert res["document_markdown"] == ""
Config.CHAT_PREVIEW = True

print("\n== 9) 발화 없는 턴은 LLM 을 부르지 않고 현황만 ==")
fake_llm.last_user_prompt = None
res = asyncio.run(turn("", '{"updates": {"제 목": "부르면 안 됨"}}'))
print("  LLM 호출 여부:", fake_llm.last_user_prompt is not None)
assert fake_llm.last_user_prompt is None
assert session_values()["제 목"] == "2026년 상반기 실적 보고"

print("\n== 10) 전부 채우면 다운로드 안내 ==")
res = asyncio.run(turn("배포일은 2026. 8. 5. (수), 담당자는 왕주영",
                       '{"updates": {"배포일": "2026. 8. 5. (수)", "담당자": "왕주영"}}'))
print("  ready:", res["ready_for_download"], "missing:", res["fields_missing"])
assert res["ready_for_download"] is True
assert "다운로드 버튼" in res["text"]

shutil.rmtree(TEMPLATE_DIR, ignore_errors=True)
print("\nALL OK")
