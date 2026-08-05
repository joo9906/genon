"""직접 수정(PATCH/DELETE /values) 스모크 — 화이트리스트·지움·저장·미리보기 일관성."""
import io
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture import bootstrap, install_fake_redis, template_bytes  # noqa: E402

TEMPLATE_DIR = bootstrap("tf_direct_")

from fastapi.testclient import TestClient  # noqa: E402

from template_fill import main as api  # noqa: E402
from template_fill.config import Config  # noqa: E402

fake = install_fake_redis()  # 9) 에서 세션 키 쓰기만 실패시킨다
client = TestClient(api.app)
SESSION = "sess-edit"
SESSION_KEY = f"{Config.REDIS_KEY_PREFIX}:{SESSION}"

TEMPLATE_BYTES, _source = template_bytes()

res = client.post(
    "/templates",
    files={"template": ("파워.hwpx", io.BytesIO(TEMPLATE_BYTES), "application/octet-stream")},
    data={"template_id": "파워"},
)
assert res.status_code == 201, res.text


def session_state() -> dict:
    raw = fake.store.get(SESSION_KEY)
    return json.loads(raw) if raw else {}


print("== 1) 빈 세션에서 첫 수정 ==")
res = client.patch(
    "/values",
    json={"session_id": SESSION, "template_id": "파워", "values": {"제 목": "상반기 실적 보고"}},
)
body = res.json()
print("  status:", res.status_code, "updated:", body["updated_fields"], "missing:", body["fields_missing"])
print("  ready:", body["ready_for_download"])
assert res.status_code == 200
assert body["updated_fields"] == ["제 목"]
assert body["values"] == {"제 목": "상반기 실적 보고"}
assert session_state()["values"] == {"제 목": "상반기 실적 보고"}
assert session_state()["raw_values"] == {"제 목": "상반기 실적 보고"}, "톤 원본도 갱신돼야 한다"
assert "제 목 : 상반기 실적 보고" in body["markdown"]

print("\n== 2) 여러 항목 + 템플릿에 없는 이름 기각 ==")
res = client.patch(
    "/values",
    json={
        "session_id": SESSION,
        "values": {
            "본문": "매출이 전년 대비 12% 증가했다.",
            "배포일": "2026. 8. 5. (수)",
            "담당자": "경영지원실 왕주영",
            "주요 내용": "신규 계약 3건 체결.",
            "없는항목": "무시돼야 한다",
        },
    },
)
body = res.json()
print("  updated:", body["updated_fields"])
print("  rejected:", body["rejected_fields"], "ready:", body["ready_for_download"])
assert body["rejected_fields"] == ["없는항목"], body
assert body["ready_for_download"] is True
assert "없는항목" not in session_state()["values"]
print("  --- markdown ---")
print(body["markdown"])
assert "담당자 : 경영지원실 왕주영" in body["markdown"]

print("\n== 3) 빈 문자열은 '지움' 으로 처리하고 알린다 ==")
res = client.patch("/values", json={"session_id": SESSION, "values": {"담당자": "   "}})
body = res.json()
print("  cleared:", body["cleared_fields"], "missing:", body["fields_missing"], "ready:", body["ready_for_download"])
assert body["cleared_fields"] == ["담당자"]
assert body["fields_missing"] == ["담당자"] and body["ready_for_download"] is False
assert "담당자" not in session_state()["values"]
assert "담당자 :" in body["markdown"] and "경영지원실" not in body["markdown"]

print("\n== 4) DELETE /values — 여러 항목 비우기 ==")
res = client.request(
    "DELETE", "/values", json={"session_id": SESSION, "fields": ["본문", "배포일", "없는것"]}
)
body = res.json()
print("  deleted:", body["deleted_fields"], "rejected:", body["rejected_fields"])
print("  missing:", body["fields_missing"], "template_filled:", body["still_filled_in_template"])
assert body["deleted_fields"] == ["배포일", "본문"]
assert body["rejected_fields"] == ["없는것"]
assert body["still_filled_in_template"] == [], "이 템플릿은 원래 비어 있어야 한다"
assert sorted(session_state()["values"]) == ["제 목", "주요 내용"]

print("\n== 5) 미리보기(GET)와 수정 응답의 상태가 같다 ==")
patched = client.patch("/values", json={"session_id": SESSION, "values": {"본문": "재작성한 본문"}}).json()
viewed = client.get("/preview", params={"session_id": SESSION}).json()
for key in ("markdown", "fields_missing", "ready_for_download", "values", "truncated"):
    assert patched[key] == viewed[key], (key, patched[key], viewed[key])
print("  일치: markdown/fields_missing/ready_for_download/values/truncated")

print("\n== 6) preview=false 면 마크다운을 만들지 않는다 ==")
light = client.patch(
    "/values", json={"session_id": SESSION, "values": {"본문": "가벼운 저장"}, "preview": False}
).json()
print("  markdown 길이:", len(light["markdown"]), "fields_missing:", light["fields_missing"])
assert light["markdown"] == "" and light["values"]["본문"] == "가벼운 저장"

print("\n== 7) 상한: values 개수 ==")
too_many = {f"항목{i}": "x" for i in range(Config.MAX_FIELDS + 1)}
res = client.patch("/values", json={"session_id": SESSION, "values": too_many})
print("  ", res.status_code, res.json()["msg"])
assert res.status_code == 400

print("\n== 8) 값 길이 상한 절단 ==")
res = client.patch("/values", json={"session_id": SESSION, "values": {"본문": "가" * (Config.MAX_VALUE_CHARS + 50)}})
stored = session_state()["values"]["본문"]
print("  저장 길이:", len(stored), "(상한", Config.MAX_VALUE_CHARS, ")")
assert len(stored) == Config.MAX_VALUE_CHARS

print("\n== 9) 세션 저장 실패는 오류로 올린다 (조용히 성공하지 않는다) ==")
# 세션 키 쓰기만 실패시킨다 — 색인 캐시는 살려 두어야 "저장 실패"만 따로 볼 수 있다
fake.fail_set_prefix = Config.REDIS_KEY_PREFIX
res = client.patch("/values", json={"session_id": SESSION, "values": {"본문": "저장 실패 확인"}})
print("  ", res.status_code, res.json()["error_code"], res.json()["msg"])
assert res.status_code == 500
fake.fail_set_prefix = None

print("\n== 10) 템플릿 없음 / 잘못된 세션 ==")
res = client.patch("/values", json={"session_id": SESSION, "template_id": "없는템플릿", "values": {}})
print("  없는 템플릿:", res.status_code)
assert res.status_code == 404
res = client.patch("/values", json={"session_id": "  ", "values": {}})
print("  빈 세션 id:", res.status_code, res.json()["msg"])
assert res.status_code == 400

print("\n== 11) 직접 수정한 값으로 다운로드까지 ==")
client.patch(
    "/values",
    json={
        "session_id": SESSION,
        "values": {"본문": "최종 본문", "배포일": "2026. 8. 5. (수)", "담당자": "왕주영"},
    },
)
gen = client.post("/generate", json={"session_id": SESSION})
print("  status:", gen.status_code, "written:", gen.headers.get("x-written-fields")[:40], "...")
assert gen.status_code == 200 and gen.content[:2] == b"PK"
assert fake.store.get(SESSION_KEY) is None, "생성 후 세션이 종료돼야 한다"

shutil.rmtree(TEMPLATE_DIR, ignore_errors=True)
print("\nALL OK")
