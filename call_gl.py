"""용어사전 API 수동 호출 — 번역 서빙(`glossary_store._fetch_items`)과 같은 요청을 requests 로 보낸다.

    export TRANSLATE_GLOSSARY_API_URL=https://.../admin-api   # 끝에 /data/ai-drive/... 는 코드가 붙인다
    export TRANSLATE_GLOSSARY_DRIVE_ID=...
    export TRANSLATE_GLOSSARY_WORKSPACE_ID=...
    export GENOS_TOKEN=...                                     # 또는 TRANSLATE_GLOSSARY_TOKEN
    python call_gl.py            # 1페이지만
    python call_gl.py --all      # 끝 페이지까지
"""
import json
import os
import sys
import urllib.parse

import requests

PAGE_SIZE = 200
MAX_PAGES = 50

base_url = os.environ.get("TRANSLATE_GLOSSARY_API_URL", "").strip().rstrip("/")
drive_id = os.environ.get("TRANSLATE_GLOSSARY_DRIVE_ID", "").strip()
workspace_id = os.environ.get("TRANSLATE_GLOSSARY_WORKSPACE_ID", "").strip()
token = (os.environ.get("TRANSLATE_GLOSSARY_TOKEN", "").strip()
         or os.environ.get("GENOS_TOKEN", "").strip())

missing = [name for name, value in [
    ("TRANSLATE_GLOSSARY_API_URL", base_url),
    ("TRANSLATE_GLOSSARY_DRIVE_ID", drive_id),
    ("TRANSLATE_GLOSSARY_WORKSPACE_ID", workspace_id),
] if not value]
if missing:
    sys.exit(f"환경변수 없음: {', '.join(missing)}")

url = f"{base_url}/data/ai-drive/{urllib.parse.quote(drive_id)}/glossary/terms"
headers = {"x-genos-workspace-id": workspace_id}
if token:
    headers["Authorization"] = f"Bearer {token}"

print(f"GET {url}")
print(f"token: {'있음' if token else '없음'}")

fetch_all = "--all" in sys.argv
items = []
for page in range(1, MAX_PAGES + 1):
    resp = requests.get(url, headers=headers,
                        params={"pg": page, "pgSize": PAGE_SIZE}, timeout=20)
    print(f"\n[page {page}] HTTP {resp.status_code}  {resp.headers.get('content-type', '')}")
    if not resp.ok:
        print(resp.text[:2000])
        break
    payload = resp.json()
    if page == 1:
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:3000])

    # 서빙과 같은 규칙으로 목록을 꺼낸다 (items / data / list / 최상위 배열)
    if isinstance(payload, list):
        page_items = payload
    elif isinstance(payload, dict):
        page_items = payload.get("items") or payload.get("data") or payload.get("list") or []
        if isinstance(page_items, dict):
            page_items = page_items.get("items") or []
    else:
        page_items = []
    print(f"-> 이 페이지 항목 {len(page_items) if isinstance(page_items, list) else 0}건")

    if not isinstance(page_items, list) or not page_items:
        break
    items.extend(page_items)
    if not fetch_all or len(page_items) < PAGE_SIZE:
        break

print(f"\n총 {len(items)}건")
for item in items[:20]:
    if isinstance(item, dict):
        print(f"  {item.get('term')!r} -> {item.get('description')!r}")
