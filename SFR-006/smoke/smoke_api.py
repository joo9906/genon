"""코드 서빙 API 스모크 — 등록/색인/미리보기/PDF/삭제 + 캐시·degrade 확인.

가짜 Redis 로 돌린다 (폐쇄망 검증용 mock 규약과 같은 취지). 실제 Redis 없이
색인 캐시 히트/미스와 장애 degrade 를 확인할 수 있어야 한다.
"""
import io
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture import bootstrap, install_fake_redis, patch_hwpx, template_bytes  # noqa: E402

TEMPLATE_DIR = bootstrap("tf_templates_")

from fastapi.testclient import TestClient  # noqa: E402

from template_fill import main as api  # noqa: E402
from template_fill import template_index  # noqa: E402
from template_fill.config import Config  # noqa: E402

fake = install_fake_redis()


# ── 전처리기 PDF 변환 모듈 스텁 ────────────────────────────────
# 운영 코드에는 모의 변환 경로가 없다. 전처리기 패키지는 이 저장소에 없으므로,
# 검증은 **패키지 경계에 스텁 모듈을 주입**해 실제 호출 규약
# (convert_hwp_to_pdf(path, order=[...]) → 출력 경로 | None) 을 그대로 확인한다.
import types  # noqa: E402

from template_fill import pdf_convert  # noqa: E402

convert_calls: list = []


def install_converter(*, behavior="ok", backends=True):
    def convert_hwp_to_pdf(file_path, order=None):
        with open(file_path, "rb") as handle:
            head = handle.read(2)
        convert_calls.append({"path": file_path, "order": order, "magic": head})
        if behavior == "none":
            return None            # 전처리기는 실패 시 예외 없이 None 을 준다
        if behavior == "raise":
            raise RuntimeError("변환기 내부 오류")
        out_path = os.path.splitext(file_path)[0] + ".pdf"
        payload = b"%PDF-1.4\n% stub converted\n" if behavior == "ok" else b"not a pdf"
        with open(out_path, "wb") as handle:
            handle.write(payload)
        return out_path

    hwp_to_pdf = types.ModuleType("genon.preprocessor.converters.hwp_to_pdf")
    hwp_to_pdf.convert_hwp_to_pdf = convert_hwp_to_pdf
    availability = types.ModuleType(
        "genon.preprocessor.converters.hwp_to_pdf.availability"
    )
    availability.pdf_sdk_available = lambda: backends
    availability.rhwp_available = lambda: backends
    availability.libreoffice_available = lambda: False
    for name, module in (
        ("genon", types.ModuleType("genon")),
        ("genon.preprocessor", types.ModuleType("genon.preprocessor")),
        ("genon.preprocessor.converters", types.ModuleType("genon.preprocessor.converters")),
        ("genon.preprocessor.converters.hwp_to_pdf", hwp_to_pdf),
        ("genon.preprocessor.converters.hwp_to_pdf.availability", availability),
    ):
        sys.modules[name] = module
    pdf_convert._AVAILABLE = None  # 가용성은 프로세스당 1회 판정 — 스텁 교체마다 되돌린다


def remove_converter():
    for name in list(sys.modules):
        if name == "genon" or name.startswith("genon."):
            del sys.modules[name]
    pdf_convert._AVAILABLE = None  # 가용성은 프로세스당 1회 판정 — 스텁 교체마다 되돌린다

# 파싱 횟수를 센다 — 캐시가 실제로 재파싱을 없애는지 확인하려면 이게 유일한 증거다
parse_calls = {"n": 0}
_real_build = template_index.build_index


def counting_build(template_id, template_bytes):
    parse_calls["n"] += 1
    return _real_build(template_id, template_bytes)


# build_index 하나만 바꿔도 등록·조회 양쪽이 잡힌다 — build_index_async 가
# 호출 시점에 이 모듈 전역을 찾아 스레드로 넘기기 때문이다.
template_index.build_index = counting_build

client = TestClient(api.app)

TEMPLATE_BYTES, _source = template_bytes()


def upload(name="파워", overwrite=None, data=None, headers=None):
    form = {"template_id": name}
    if overwrite is not None:
        form["overwrite"] = str(overwrite).lower()
    return client.post(
        "/templates",
        files={"template": ("파워.hwpx", io.BytesIO(data or TEMPLATE_BYTES), "application/octet-stream")},
        data=form,
        headers=headers or {},
    )


print("== 1) 등록 (POST /templates) ==")
res = upload()
print("  status:", res.status_code)
body = res.json()
print("  template_id:", body["template_id"], "fields:", [f["name"] for f in body["fields"]])
print("  markdown 첫 줄:", body["markdown"].splitlines()[0])
assert res.status_code == 201, res.text
assert [f["name"] for f in body["fields"]] == ["제 목", "본문", "배포일", "담당자", "주요 내용"]
assert os.path.exists(os.path.join(TEMPLATE_DIR, "파워.hwpx"))
assert parse_calls["n"] == 1, parse_calls

print("\n== 2) 중복 등록 → 409, overwrite=true → 200 ==")
dup = upload()
print("  중복:", dup.status_code, dup.json()["error_code"], dup.json()["msg"])
assert dup.status_code == 409
over = upload(overwrite=True)
print("  덮어쓰기:", over.status_code, "overwritten:", over.json()["overwritten"])
assert over.status_code == 200 and over.json()["overwritten"] is True

print("\n== 3) 깨진 파일 등록 거부 (파일이 볼륨에 남지 않아야 한다) ==")
broken = upload(name="깨진것", data=b"not a hwpx")
print("  status:", broken.status_code, broken.json()["msg"])
assert broken.status_code == 400
assert not os.path.exists(os.path.join(TEMPLATE_DIR, "깨진것.hwpx")), "깨진 템플릿이 등록됐다"

print("\n== 4) 목록 (GET /templates) ==")
listing = client.get("/templates").json()
print("  ", listing["items"], "formats:", listing["formats"])
assert listing["templates"] == ["파워"]
assert listing["items"][0]["indexed"] is True and listing["items"][0]["field_count"] == 5

print("\n== 5) /fields 는 캐시를 쓴다 (재파싱 0) ==")
before = parse_calls["n"]
for _ in range(3):
    fields = client.get("/fields", params={"template_id": "파워"}).json()
print("  from_cache:", fields["from_cache"], "파싱 증가:", parse_calls["n"] - before)
assert fields["from_cache"] is True
assert parse_calls["n"] == before, "캐시가 있는데 다시 파싱했다"

print("\n== 6) 템플릿 파일이 교체되면 자동 무효화 ==")
with open(os.path.join(TEMPLATE_DIR, "파워.hwpx"), "rb") as f:
    original = f.read()

patched = patch_hwpx(original, "주요 내용", "핵심 내용")
assert patched != original
with open(os.path.join(TEMPLATE_DIR, "파워.hwpx"), "wb") as f:
    f.write(patched)
before = parse_calls["n"]
fields = client.get("/fields", params={"template_id": "파워"}).json()
print("  파싱 증가:", parse_calls["n"] - before, "항목:", [f["name"] for f in fields["fields"]])
assert parse_calls["n"] == before + 1, "내용이 바뀌었는데 캐시를 그대로 썼다"
assert "핵심 내용" in [f["name"] for f in fields["fields"]]
with open(os.path.join(TEMPLATE_DIR, "파워.hwpx"), "wb") as f:
    f.write(original)  # 되돌린다

print("\n== 7) 파서 스키마 버전이 올라가면 옛 색인 폐기 ==")
client.get("/fields", params={"template_id": "파워"})  # 색인 재생성
before = parse_calls["n"]
template_index.SCHEMA_VERSION += 1
client.get("/fields", params={"template_id": "파워"})
assert parse_calls["n"] == before + 1, "스키마 버전이 달라도 옛 색인을 썼다"
template_index.SCHEMA_VERSION -= 1
print("  OK")

print("\n== 8) Redis 장애 → 직접 파싱으로 degrade ==")
fake.fail = True
before = parse_calls["n"]
res = client.get("/fields", params={"template_id": "파워"})
print("  status:", res.status_code, "from_cache:", res.json()["from_cache"], "파싱:", parse_calls["n"] - before)
assert res.status_code == 200 and res.json()["from_cache"] is False
fake.fail = False
client.get("/fields", params={"template_id": "파워"})

print("\n== 9) 세션 값으로 /status, /preview ==")
session_key = f"{Config.REDIS_KEY_PREFIX}:sess-1"
fake.store[session_key] = json.dumps(
    {
        "version": 1,
        "template_id": "파워",
        "values": {
            "제 목": "2026년 상반기 실적 보고",
            "본문": "매출이 전년 대비 12% 증가했다.",
            "배포일": "2026. 8. 5. (수)",
        },
        "raw_values": {},
        "updated_at": 0.0,
    },
    ensure_ascii=False,
)
status = client.get("/status", params={"session_id": "sess-1"}).json()
print("  missing:", status["fields_missing"], "ready:", status["ready_for_download"])
assert status["fields_missing"] == ["담당자", "주요 내용"] and status["ready_for_download"] is False

prev = client.get("/preview", params={"session_id": "sess-1"}).json()
print("  --- preview markdown ---")
print(prev["markdown"])
assert "제 목 : 2026년 상반기 실적 보고" in prev["markdown"]
assert "담당자 :" in prev["markdown"] and "{" not in prev["markdown"]
assert prev["truncated"] is False
assert [f["value"] for f in prev["fields"] if f["name"] == "본문"] == ["매출이 전년 대비 12% 증가했다."]
assert prev["fields_missing"] == ["담당자", "주요 내용"]
assert fake.store.get(session_key) is not None, "미리보기가 세션을 지웠다"

print("\n== 10) /generate hwpx ==")
gen = client.post("/generate", json={"template_id": "파워", "session_id": "sess-1"})
print("  status:", gen.status_code, "bytes:", len(gen.content), "format:", gen.headers.get("x-document-format"))
print("  missing 헤더:", gen.headers.get("x-missing-fields"), "styled:", gen.headers.get("x-styled-fields"))
assert gen.status_code == 200 and gen.content[:2] == b"PK"
assert gen.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")
assert fake.store.get(session_key) is None, "생성 성공 후 세션이 남았다"

print("\n== 11) 전처리기 패키지가 없으면 501 + formats 에서 제외 ==")
remove_converter()
assert client.get("/templates").json()["formats"] == ["hwpx"]
absent = client.post("/generate", json={"template_id": "파워", "format": "pdf"})
print("  status:", absent.status_code, absent.json()["error_code"], absent.json()["msg"])
assert absent.status_code == 501

print("\n== 12) /generate pdf — 전처리기 호출 규약 확인 ==")
install_converter()
convert_calls.clear()
assert client.get("/templates").json()["formats"] == ["hwpx", "pdf"]
pdf = client.post("/generate", json={"template_id": "파워", "values": {"제 목": "PDF 확인"}, "format": "pdf"})
print("  status:", pdf.status_code, "magic:", pdf.content[:8], "format:", pdf.headers.get("x-document-format"))
print("  파일명:", pdf.headers.get("content-disposition"))
print("  변환기 호출:", [{k: v for k, v in c.items() if k != "path"} for c in convert_calls])
print("  넘긴 파일:", os.path.basename(convert_calls[0]["path"]))
assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
assert pdf.headers["content-disposition"].endswith(".pdf")
assert pdf.headers["content-type"] == "application/pdf"
assert len(convert_calls) == 1
assert convert_calls[0]["order"] == ["pdf_sdk", "rhwp", "libreoffice"], convert_calls[0]
assert convert_calls[0]["path"].endswith(".hwpx")
assert convert_calls[0]["magic"] == b"PK", "변환기에 hwpx(zip) 를 넘겨야 한다"
assert not os.path.exists(os.path.dirname(convert_calls[0]["path"])), "임시 디렉토리가 남았다"

print("\n== 13) 변환기가 None 을 주면 500, 세션은 유지 ==")
fake.store[session_key] = json.dumps(
    {"version": 1, "template_id": "파워", "values": {"제 목": "유지 확인"}, "raw_values": {}, "updated_at": 0.0},
    ensure_ascii=False,
)
install_converter(behavior="none")
failed = client.post("/generate", json={"template_id": "파워", "session_id": "sess-1", "format": "pdf"})
print("  status:", failed.status_code, failed.json()["error_code"], failed.json()["msg"])
assert failed.status_code == 500
assert fake.store.get(session_key) is not None, "변환 실패인데 세션을 종료했다"

print("\n== 14) 변환기가 PDF 아닌 산출물/예외를 주면 500 ==")
install_converter(behavior="not_pdf")
bad_out = client.post("/generate", json={"template_id": "파워", "values": {"제 목": "x"}, "format": "pdf"})
print("  PDF 아님:", bad_out.status_code, bad_out.json()["error_code"])
assert bad_out.status_code == 500
install_converter(behavior="raise")
raised = client.post("/generate", json={"template_id": "파워", "values": {"제 목": "x"}, "format": "pdf"})
print("  변환기 예외:", raised.status_code, raised.json()["error_code"])
assert raised.status_code == 500

print("\n== 15) 백엔드가 0개면 501 (시도하지 않는다) ==")
install_converter(backends=False)
convert_calls.clear()
no_backend = client.post("/generate", json={"template_id": "파워", "values": {"제 목": "x"}, "format": "pdf"})
print("  status:", no_backend.status_code, no_backend.json()["msg"])
assert no_backend.status_code == 501
assert convert_calls == [], "백엔드가 없는데 변환을 시도했다"
assert client.get("/templates").json()["formats"] == ["hwpx"]
remove_converter()

print("\n== 16) 업로드 경로도 pdf 를 낸다 ==")
install_converter()
up_pdf = client.post(
    "/generate/upload",
    files={"template": ("파워.hwpx", io.BytesIO(TEMPLATE_BYTES), "application/octet-stream")},
    data={"values": json.dumps({"제 목": "업로드 PDF"}, ensure_ascii=False), "format": "pdf"},
)
print("  status:", up_pdf.status_code, "magic:", up_pdf.content[:8])
assert up_pdf.status_code == 200 and up_pdf.content.startswith(b"%PDF-")
remove_converter()

print("\n== 17) 잘못된 format ==")
bad = client.post("/generate", json={"template_id": "파워", "format": "docx"})
print("  ", bad.status_code, bad.json()["msg"])
assert bad.status_code == 400

print("\n== 18) 관리자 토큰 ==")
Config.ADMIN_TOKEN = "secret"
denied = upload(name="파워2")
print("  토큰 없음:", denied.status_code, denied.json()["msg"])
assert denied.status_code == 403
allowed = upload(name="파워2", headers={"X-Admin-Token": "secret"})
assert allowed.status_code == 201, allowed.text
del_denied = client.delete("/templates/파워2")
assert del_denied.status_code == 403
del_ok = client.delete("/templates/파워2", headers={"X-Admin-Token": "secret"})
print("  삭제:", del_ok.status_code, del_ok.json())
assert del_ok.status_code == 200
Config.ADMIN_TOKEN = ""

print("\n== 19) 경로 조작 차단 ==")
for bad_id in ("../../etc/passwd", "..", ".hidden", "a/b"):
    res = client.delete(f"/templates/{bad_id}")
    print(f"  {bad_id!r:20} -> {res.status_code}")
    assert res.status_code in (400, 404), (bad_id, res.status_code, res.text)

print("\n== 20) 삭제 후 색인도 사라진다 ==")
gone = client.delete("/templates/파워")
assert gone.status_code == 200
assert not os.path.exists(os.path.join(TEMPLATE_DIR, "파워.hwpx"))
after = client.get("/fields", params={"template_id": "파워"})
print("  /fields:", after.status_code, after.json()["msg"])
assert after.status_code == 404
assert client.get("/templates").json()["templates"] == []

shutil.rmtree(TEMPLATE_DIR, ignore_errors=True)
print("\nALL OK  (총 파싱 횟수:", parse_calls["n"], ")")
