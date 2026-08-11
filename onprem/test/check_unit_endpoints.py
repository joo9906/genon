"""번역·FAQ 엔드포인트 점검 — `check_api_contract.py` 가 안 보는 두 단위.

```
python onprem/test/check_unit_endpoints.py
```

서버·Redis·LLM 불필요. `TestClient` 로 인프로세스 호출한다.

## 왜 이 파일이 따로 필요한가

`check_api_contract.py`(42건)는 **006 전용**이다. 번역·FAQ 는 그동안 `check_service_boot`
의 "떴다 / `/health` 200 / 라우트 수" 밖에 없었다 — 즉 **라우트 안에서 무슨 일이
일어나는지는 아무도 안 봤다.**

그 구멍이 실제로 문제가 된 지점이 2026-08-11 진입점 분해다. 세 `main.py` 에서 요청 검증·
응답 조립·형식 생성을 별도 모듈로 옮겼는데, 006 은 특성화 점검 42건이 "동작이 안 바뀌었다"
를 보증한 반면 **번역·FAQ 는 보증할 그물이 없었다.** 이 파일이 그 그물이다.

## 무엇을 고르는가 — 전수가 아니라 **경계**를 고른다

LLM 이 필요한 경로(실제 번역·실제 FAQ 생성)는 여기서 태울 수 없다. 대신 **LLM 앞에서
갈리는 경계**를 고른다. 분해로 옮겨진 코드가 정확히 거기 있기 때문이다:

| 보는 것 | 어느 코드를 태우나 |
|---|---|
| 지원 언어·용어사전 상태 조회 | 라우트 → 도메인 조회 |
| 잘못된 언어 코드 거절 | `api_contract.input_error_response` |
| 업로드 상한 초과 / 빈 파일 | `api_contract.read_upload_capped` — **두 경우가 다른 안내문**이어야 한다 |
| 지원하지 않는 내려받기 형식 | `download_formats.FORMATS` + `error_response` |
| xlsx 실제 생성 | `download_formats.build_bytes` — 바이트가 실제로 나오는지 |

**xlsx 만 실제로 만든다.** hwpx 는 관리자 템플릿이 있어야 하고 pdf 는 weasyprint 가
있어야 해서 환경에 좌우된다 — 그런 것을 넣으면 점검이 환경에 따라 켜졌다 꺼졌다 한다.
xlsx 는 openpyxl(순수 파이썬)만 있으면 되므로 어디서든 같은 결과가 나온다.

## 오류 응답은 모양까지 본다

`{error_code, msg}` 가 **둘 다** 있어야 한다 (3.9.5절). 채팅 연계에서는 사용자에게
`msg` 만 가고 로그 대조에는 `error_code` 가 필요하다 — 하나만 있으면 둘 중 한쪽이 막힌다.
"""

import io
import json
import os
import subprocess
import sys

_ONPREM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------
# 자식 프로세스 — 단위 하나를 띄우고 경계를 태운다
#
# 번역과 FAQ 가 둘 다 최상위 `config` 모듈을 만든다. 한 프로세스에서 이어 import 하면
# 먼저 들어간 쪽이 뒤엣것을 가려 **엉뚱한 단위의 상한값으로 판정**하게 된다.
# --------------------------------------------------------------------------

def _error_shaped(body) -> bool:
    return isinstance(body, dict) and "error_code" in body and bool(body.get("msg"))


def _check_translation(out: list) -> None:
    sys.path.insert(0, os.path.join(_ONPREM, "codeserving", "SFR-018_translation"))
    from fastapi.testclient import TestClient

    import main
    from config import Config

    with TestClient(main.app) as c:
        r = c.get("/languages")
        out.append(("지원 언어 조회",
                    r.status_code == 200 and bool(r.json().get("languages")),
                    f"HTTP {r.status_code}"))

        r = c.get("/glossary")
        out.append(("용어사전 상태 조회", r.status_code == 200, f"HTTP {r.status_code}"))

        r = c.post("/translate/markdown", json={"markdown": "안녕", "target_lang": "zz"})
        body = r.json()
        out.append(("지원하지 않는 언어 거절",
                    r.status_code >= 400 and _error_shaped(body),
                    f"HTTP {r.status_code} / {body.get('msg', '')[:40]}"))

        big = b"x" * (Config.MAX_UPLOAD_BYTES + 4096)
        r = c.post("/translate/hwpx",
                   files={"document": ("big.hwpx", io.BytesIO(big))},
                   data={"target_lang": "en"})
        body = r.json()
        out.append(("업로드 상한 초과 거절",
                    r.status_code >= 400 and "상한" in body.get("msg", ""),
                    f"HTTP {r.status_code} / {body.get('msg', '')[:40]}"))

        r = c.post("/translate/hwpx",
                   files={"document": ("empty.hwpx", io.BytesIO(b""))},
                   data={"target_lang": "en"})
        body = r.json()
        # 상한 초과(None)와 빈 파일(b"")이 같은 안내문이면 사용자가 무엇을 고쳐야 할지 모른다
        out.append(("빈 파일은 상한과 다른 안내문",
                    r.status_code >= 400 and "비어" in body.get("msg", ""),
                    f"HTTP {r.status_code} / {body.get('msg', '')[:40]}"))


def _check_faq(out: list) -> None:
    sys.path.insert(0, os.path.join(_ONPREM, "codeserving", "SFR-018_faq"))
    from fastapi.testclient import TestClient

    from faq import main
    from faq.config import Config

    with TestClient(main.app) as c:
        r = c.get("/config")
        body = r.json()
        out.append(("형식 가용성 조회",
                    r.status_code == 200 and isinstance(body.get("formats"), list),
                    f"HTTP {r.status_code} / formats={body.get('formats')}"))

        r = c.post("/download", json={"format": "docx", "session_id": "x"})
        body = r.json()
        out.append(("지원하지 않는 형식 거절",
                    r.status_code >= 400 and _error_shaped(body),
                    f"HTTP {r.status_code} / {body.get('msg', '')[:40]}"))

        r = c.post("/download", json={"format": "xlsx"})
        body = r.json()
        out.append(("session_id·items 모두 없으면 거절",
                    r.status_code >= 400 and _error_shaped(body),
                    f"HTTP {r.status_code} / {body.get('msg', '')[:40]}"))

        big = b"x" * (Config.MAX_UPLOAD_BYTES + 4096)
        r = c.post("/generate/upload",
                   files={"document": ("big.hwpx", io.BytesIO(big))}, data={"count": "3"})
        body = r.json()
        out.append(("업로드 상한 초과 거절",
                    r.status_code >= 400 and "상한" in body.get("msg", ""),
                    f"HTTP {r.status_code} / {body.get('msg', '')[:40]}"))

        r = c.post("/generate/upload",
                   files={"document": ("empty.hwpx", io.BytesIO(b""))}, data={"count": "3"})
        body = r.json()
        out.append(("빈 파일은 상한과 다른 안내문",
                    r.status_code >= 400 and "비어" in body.get("msg", ""),
                    f"HTTP {r.status_code} / {body.get('msg', '')[:40]}"))

        # 실제 파일 생성. LLM 을 부르지 않는 유일한 산출 경로다 (items 를 직접 준다).
        items = [{"question": "질문1", "answer": "답변1", "evidence": "근거1"}]
        r = c.post("/download", json={"format": "xlsx", "items": items, "title": "점검"})
        out.append(("xlsx 실제 생성",
                    r.status_code == 200 and len(r.content) > 1000,
                    f"HTTP {r.status_code} / {len(r.content)} bytes"))


CHECKS = {
    "translation": ("SFR-018 번역", _check_translation),
    "faq": ("SFR-018 FAQ", _check_faq),
}


def _child_main(key: str) -> int:
    out: list = []
    try:
        CHECKS[key][1](out)
        payload = {"ok": True, "results": out}
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "results": out}
    sys.stdout.write("\n__EP_RESULT__" + json.dumps(payload, ensure_ascii=False) + "\n")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        return _child_main(sys.argv[2])

    try:
        import fastapi  # noqa: F401
    except ImportError:
        sys.stderr.write("fastapi 가 없어 엔드포인트 점검을 돌릴 수 없다.\n")
        return 2

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    rep: list = []

    for key, (label, _) in CHECKS.items():
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--child", key],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=180,
        )
        line = ""
        for raw in (proc.stdout or "").splitlines():
            if raw.startswith("__EP_RESULT__"):
                line = raw[len("__EP_RESULT__"):]
        if not line:
            tail = ((proc.stderr or "") + (proc.stdout or "")).strip().splitlines()[-3:]
            rep.append(("FAIL", label, "기동", " / ".join(tail) or "결과를 받지 못했다"))
            continue
        payload = json.loads(line)
        for item, passed, detail in payload.get("results", []):
            rep.append(("OK" if passed else "FAIL", label, item, detail))
        if not payload.get("ok"):
            rep.append(("FAIL", label, "실행", payload.get("error", "알 수 없는 실패")))

    ok = sum(1 for r in rep if r[0] == "OK")
    fail = sum(1 for r in rep if r[0] == "FAIL")
    name_w = max(len(r[1]) for r in rep)
    item_w = max(len(r[2]) for r in rep)
    for status, label, item, detail in rep:
        mark = "OK  " if status == "OK" else "FAIL"
        print(f"[{mark}] {label:<{name_w}}  {item:<{item_w}}  {detail}")

    print()
    print(f"OK {ok} / {ok + fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
