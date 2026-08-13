"""SFR-018 세 단위 엔드포인트 점검 — `check_api_contract.py` 가 안 보는 자리.

```
python onprem/test/check_unit_endpoints.py
```

서버·Redis·LLM 불필요. `TestClient` 로 인프로세스 호출한다.

## 왜 이 파일이 따로 필요한가

`check_api_contract.py`(42건)는 **006 전용**이다. 018 세 단위는 그동안 `check_service_boot`
의 "떴다 / `/health` 200 / 라우트 수" 밖에 없었다 — 즉 **라우트 안에서 무슨 일이
일어나는지는 아무도 안 봤다.**

그 구멍이 실제로 문제가 된 지점이 2026-08-11 진입점 분해다. 세 `main.py` 에서 요청 검증·
응답 조립·형식 생성을 별도 모듈로 옮겼는데, 006 은 특성화 점검 42건이 "동작이 안 바뀌었다"
를 보증한 반면 **018 은 보증할 그물이 없었다.** 이 파일이 그 그물이다.

## 무엇을 고르는가 — 전수가 아니라 **경계**를 고른다

LLM 이 필요한 경로(실제 번역·실제 FAQ 생성)는 여기서 태울 수 없다. 대신 **LLM 앞에서
갈리는 경계**를 고른다. 분해로 옮겨진 코드가 정확히 거기 있기 때문이다:

| 보는 것 | 어느 코드를 태우나 |
|---|---|
| 지원 언어·용어사전 상태 조회 | 라우트 → 도메인 조회 |
| 잘못된 언어 코드 거절 | `api_contract.input_error_response` |
| 업로드 상한 초과 / 빈 파일 | `api_contract.read_upload_capped` — **두 경우가 다른 안내문**이어야 한다 |
| 옛 내려받기 형식 거절 | FAQ `/download` 의 형식 판정 |
| txt 실제 생성 | `txt_output.to_bytes` + 본문 조립 — 바이트가 실제로 나오는지 |

## txt 규약은 **세 단위를 대조**해 본다 (2026-08-12)

산출 형식이 txt 하나로 통일되면서 `txt_output.py` 가 세 배포 단위에 사본으로 들어갔다
(단위 간 import 금지). 사본은 갈린다 — 그래서 정적 diff 가 아니라 **응답 바이트**로 본다:

- **UTF-8 BOM 으로 시작**한다 (없으면 옛 메모장이 cp949 로 읽어 한글이 깨진다)
- 줄바꿈이 **전부 CRLF** 다 (LF 만 있으면 옛 메모장이 한 줄로 붙여 보여준다)
- `Content-Type` 이 `text/plain; charset=utf-8`, 파일명은 RFC 5987(`filename*`)
- 제목의 경로 구분자·따옴표가 파일명에서 사라진다 (헤더가 갈라지지 않게)

세 단위 결과를 한자리에 모아 대조하는 `_check_txt_contract` 가 그 판정을 한다.
하나만 규약을 벗어나면 "어떤 기능에서 받은 파일만 메모장에서 깨진다" 가 되는데,
그건 사용자 제보로만 드러나고 재현이 어렵다.

## 오류 응답은 모양까지 본다

`{error_code, msg}` 가 **둘 다** 있어야 한다 (3.9.5절). 채팅 연계에서는 사용자에게
`msg` 만 가고 로그 대조에는 `error_code` 가 필요하다 — 하나만 있으면 둘 중 한쪽이 막힌다.
"""

import io
import json
import os
import subprocess
import sys
import urllib.parse

_ONPREM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# txt 규약 대조에 쓰는 값. **여러 줄**이어야 CRLF 판정이 의미를 갖고, 제목에 금지문자가
# 있어야 파일명 정리가 실제로 돌았는지 보인다.
_TXT_TITLE = '보고/서: "초안"'
_TXT_TITLE_CLEAN = "보고서 초안.txt"


# --------------------------------------------------------------------------
# 자식 프로세스 — 단위 하나를 띄우고 경계를 태운다
#
# 번역과 FAQ 가 둘 다 최상위 `config` 모듈을 만든다. 한 프로세스에서 이어 import 하면
# 먼저 들어간 쪽이 뒤엣것을 가려 **엉뚱한 단위의 상한값으로 판정**하게 된다.
# --------------------------------------------------------------------------

def _error_shaped(body) -> bool:
    return isinstance(body, dict) and "error_code" in body and bool(body.get("msg"))


def _txt_probe(response) -> dict:
    """내려받기 응답에서 txt 규약 판정에 필요한 사실만 뽑는다 (2026-08-12).

    바이트를 그대로 부모 프로세스로 넘기지 않는다 — JSON 으로 오가야 하고, 여기서 재는
    것은 내용이 아니라 **인코딩·줄바꿈·헤더**다.
    """
    data = response.content
    disposition = response.headers.get("content-disposition", "")
    filename = ""
    marker = "filename*=UTF-8''"
    if marker in disposition:
        filename = urllib.parse.unquote(disposition.split(marker, 1)[1])
    return {
        "status": response.status_code,
        "bom": data[:3] == b"\xef\xbb\xbf",
        # 줄바꿈이 하나는 있어야 하고, CRLF 를 지운 뒤 LF 가 남지 않아야 한다
        "crlf_only": b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""),
        "content_type": response.headers.get("content-type", ""),
        "rfc5987": marker in disposition,
        "filename": filename,
        "bytes": len(data),
    }


def _check_translation(out: list, probe: dict) -> None:
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

        # ── txt 내려받기 (2026-08-12) ──
        # 본문은 **표를 그대로 담는다.** 번역의 계약이 "구조는 입력과 동일" 이므로
        # 파일에서 표가 평문으로 풀리면 그 계약이 마지막 단계에서 깨진 것이다.
        table = "| 항목 | 값 |\n|---|---|\n| 매출 | 1,000 |"
        r = c.post("/download", json={"markdown": table, "title": _TXT_TITLE})
        probe.update(_txt_probe(r))
        out.append(("번역문 txt 생성",
                    r.status_code == 200 and table.replace("\n", "\r\n").encode() in r.content,
                    f"HTTP {r.status_code} / {len(r.content)} bytes"))

        # `/translate` 응답은 `text`, 마크다운 경로는 `markdown` 이다. 화면이 방금 받은
        # 필드를 그대로 되돌려 보낼 수 있어야 이름을 옮겨 적는 층이 안 생긴다.
        r = c.post("/download", json={"text": "한 줄\n두 줄"})
        out.append(("text 별칭도 받는다", r.status_code == 200, f"HTTP {r.status_code}"))

        r = c.post("/download", json={"text": "   "})
        body = r.json()
        out.append(("빈 본문은 빈 파일이 아니라 오류",
                    r.status_code >= 400 and _error_shaped(body),
                    f"HTTP {r.status_code} / {body.get('msg', '')[:40]}"))


def _check_text_polish(out: list, probe: dict) -> None:
    """글다듬이 — 2026-08-12 에 `POST /download` 가 붙어 점검 대상이 됐다.

    이 단위는 상태가 없어(Redis 미사용) 경계가 단순하다. 대신 **정책 목록**과 **txt 규약**
    두 가지를 본다: 앞엣것은 UI 선택지의 원천이고, 뒤엣것은 세 단위 대조에 들어간다.
    """
    sys.path.insert(0, os.path.join(_ONPREM, "codeserving", "SFR-018_text_polish"))
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as c:
        r = c.get("/policies")
        body = r.json()
        out.append(("문서유형·톤 목록 조회",
                    r.status_code == 200 and bool(body.get("doc_types")) and bool(body.get("tones")),
                    f"HTTP {r.status_code}"))

        r = c.get("/")
        out.append(("루트에 /download 노출",
                    r.status_code == 200 and "/download" in (r.json().get("endpoints") or []),
                    f"HTTP {r.status_code} / {r.json().get('endpoints')}"))

        polished = "가. 첫째 줄\n나. 둘째 줄"
        r = c.post("/download", json={"polished_text": polished, "title": _TXT_TITLE})
        probe.update(_txt_probe(r))
        out.append(("다듬은 본문 txt 생성",
                    r.status_code == 200 and polished.replace("\n", "\r\n").encode() in r.content,
                    f"HTTP {r.status_code} / {len(r.content)} bytes"))

        r = c.post("/download", json={"text": "한 줄\n두 줄"})
        out.append(("text 별칭도 받는다", r.status_code == 200, f"HTTP {r.status_code}"))

        r = c.post("/download", json={})
        empty_body = r.json()
        out.append(("빈 본문은 빈 파일이 아니라 오류",
                    r.status_code >= 400 and _error_shaped(empty_body),
                    f"HTTP {r.status_code} / {empty_body.get('msg', '')[:40]}"))

        # ── 상한 초과와 빈 입력을 가른다 (2026-08-13 추가) ──
        #
        # 그전에는 20만 자를 붙여 넣은 사용자가 `ERR_INPUT_EMPTY` 를 받아
        # **"다듬을 문서나 텍스트를 입력해 주세요"** 라는 안내를 봤다 — 무엇을 하라는
        # 건지 알 수 없고, 로그 error_type 도 `POLISH_INPUT_EMPTY` 라 운영에서는
        # "빈 입력이 왜 이렇게 많나" 로 보였다. 두 사건은 사용자가 할 일이 반대다.
        from text_polish.config import Config as PolishConfig

        too_long = "가" * (PolishConfig.MAX_INPUT_CHARS + 1)
        for path, payload in (("/polish", {"text": too_long}), ("/download", {"text": too_long})):
            r = c.post(path, json=payload)
            body = r.json()
            out.append((
                f"{path} 상한 초과는 빈 입력과 다른 안내문",
                r.status_code >= 400
                and _error_shaped(body)
                and body.get("msg") != empty_body.get("msg"),
                f"HTTP {r.status_code} / {body.get('msg', '')[:30]}",
            ))

        # 영역코드 03 — 이 단위는 2026-08-11 재배치로 코드 서빙이 됐다. 02 를 그대로
        # 내면 워크플로우 스텝이 내는 오류와 로그에서 구분되지 않는다 (3.9.1절).
        out.append((
            "오류 영역코드가 03 (코드 서빙)",
            str(empty_body.get("error_code", "")).startswith("03-"),
            f"error_code={empty_body.get('error_code')}",
        ))


def _check_faq(out: list, probe: dict) -> None:
    sys.path.insert(0, os.path.join(_ONPREM, "codeserving", "SFR-018_faq"))
    from fastapi.testclient import TestClient

    from faq import main
    from faq.config import Config

    with TestClient(main.app) as c:
        r = c.get("/config")
        body = r.json()
        # 형식 목록은 이제 항상 `["txt"]` 다. 배열 모양 자체가 UI 계약이라 함께 본다.
        out.append(("형식 목록은 txt 하나",
                    r.status_code == 200 and body.get("formats") == ["txt"],
                    f"HTTP {r.status_code} / formats={body.get('formats')}"))

        r = c.post("/download", json={"format": "docx", "session_id": "x"})
        body = r.json()
        out.append(("지원하지 않는 형식 거절",
                    r.status_code >= 400 and _error_shaped(body),
                    f"HTTP {r.status_code} / {body.get('msg', '')[:40]}"))

        # 옛 형식으로 오는 요청을 조용히 txt 로 바꿔 주면, 화면은 xlsx 를 받았다고 믿는데
        # 파일은 txt 인 상태가 되고 그 어긋남은 아무 기록도 남지 않는다.
        items = [{"question": "질문1", "answer": "답변1", "sources": "근거1"}]
        for stale in ("xlsx", "pdf", "hwpx"):
            r = c.post("/download", json={"format": stale, "items": items})
            out.append((f"옛 형식 {stale} 은 거절",
                        r.status_code >= 400 and _error_shaped(r.json()),
                        f"HTTP {r.status_code}"))

        r = c.post("/download", json={"format": "txt"})
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
        # 근거는 **여러 줄로** 준다 — 파일에서 한 줄로 펴져야 `[근거]` 표지와 갈리지 않는다.
        rows = [
            {"question": "질문1", "answer": "답변1", "sources": "근거\n첫째 줄"},
            {"question": "질문2", "answer": "답변2", "sources": "근거2"},
        ]
        r = c.post("/download", json={"items": rows, "title": _TXT_TITLE})
        probe.update(_txt_probe(r))
        text = r.content.decode("utf-8-sig").replace("\r\n", "\n")
        out.append(("txt 실제 생성 (형식 미지정)",
                    r.status_code == 200 and "Q1. 질문1" in text and "Q2. 질문2" in text,
                    f"HTTP {r.status_code} / {len(r.content)} bytes"))
        # 화면 마크다운(`**Q1.**` / `> 근거:`)이 파일에 그대로 새어 나오면 메모장에서
        # 별표와 꺾쇠가 글자로 보인다. 파일은 평문이라는 것이 이 판정이다.
        out.append(("파일은 평문 — 마크다운 기호 없음",
                    "**" not in text and "> 근거" not in text and "[근거] 근거 첫째 줄" in text,
                    text.splitlines()[4] if len(text.splitlines()) > 4 else text[:40]))
        out.append(("제목이 파일 첫 줄에 들어간다",
                    text.startswith("보고/서: \"초안\"") or text.startswith(_TXT_TITLE),
                    text.splitlines()[0] if text else ""))

        # ── 생성 실패 분류가 서로 다른 상태코드로 갈리는가 (2026-08-13 추가) ──
        #
        # 그전에는 통신 실패만 갈리고 **근거 미확보·프롬프트 부재·실행 실패 셋이 전부
        # 502** 였다. 셋은 사용자가 할 일이 다르다(문서를 바꿔라 / 관리자에게 문의 /
        # 잠시 후 다시). 특히 근거 미확보는 워크플로우 스텝이 `upstream_status == 422`
        # 로 분기를 걸어 뒀는데 서빙이 422 를 낸 적이 없어 **닿을 수 없는 코드**였다.
        #
        # LLM 없이 태우려고 `generate_faqs` 경계에 대역을 꽂는다 — 실패 분류를 만드는
        # 것이 그 함수이므로, 그 뒤(=상태코드 매핑)가 검사 대상이다.
        from faq.generator import (
            FAILURE_EXECUTION,
            FAILURE_NO_GROUNDED,
            FAILURE_PROMPT,
            FAILURE_TRANSPORT,
            FaqResult,
        )

        original_generate = main.generate_faqs
        try:
            for failure, expected_status, label in (
                (FAILURE_TRANSPORT, 504, "통신 실패"),
                (FAILURE_NO_GROUNDED, 422, "근거 미확보"),
                (FAILURE_PROMPT, 500, "프롬프트 부재"),
                (FAILURE_EXECUTION, 502, "실행 실패"),
            ):
                async def _fake(_doc, _count, _admin=None, _f=failure):
                    return FaqResult(failure=_f, requested_count=3, max_count=10)

                main.generate_faqs = _fake
                r = c.post("/generate", json={"markdown": "본문", "count": 3})
                body = r.json()
                out.append((
                    f"생성 실패 분류 — {label}",
                    r.status_code == expected_status and _error_shaped(body),
                    f"HTTP {r.status_code} (기대 {expected_status}) / {body.get('error_code', '')}",
                ))
        finally:
            main.generate_faqs = original_generate

        # 프롬프트 부재는 **재시도로 풀리지 않는다.** 502(재시도 가능)로 나가면 캔버스가
        # 같은 자리에서 반복해서 실패한다 — 배포 구성 문제라는 사실이 드러나야 한다.
        from faq.error_codes import ERR_API_PROMPT_UNAVAILABLE
        out.append(("프롬프트 부재는 재시도 불가",
                    ERR_API_PROMPT_UNAVAILABLE.retryable is False,
                    f"retryable={ERR_API_PROMPT_UNAVAILABLE.retryable}"))


CHECKS = {
    "translation": ("SFR-018 번역", _check_translation),
    "text_polish": ("SFR-018 글다듬이", _check_text_polish),
    "faq": ("SFR-018 FAQ", _check_faq),
}


def _child_main(key: str) -> int:
    out: list = []
    probe: dict = {}
    try:
        CHECKS[key][1](out, probe)
        payload = {"ok": True, "results": out, "probe": probe}
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                   "results": out, "probe": probe}
    sys.stdout.write("\n__EP_RESULT__" + json.dumps(payload, ensure_ascii=False) + "\n")
    return 0


# --------------------------------------------------------------------------
# 세 단위 txt 규약 대조 (2026-08-12)
#
# `txt_output.py` 는 세 배포 단위에 **사본**으로 있다 (단위 간 import 금지). 사본은 갈리므로
# 정적 diff 가 아니라 **응답 바이트**로 본다 — 한 단위만 규약을 벗어나면 "그 기능에서 받은
# 파일만 메모장에서 깨진다" 가 되고, 그건 사용자 제보로만 드러난다.
# --------------------------------------------------------------------------

_TXT_RULES = (
    ("BOM 으로 시작", lambda p: p.get("bom") is True,
     "없으면 옛 메모장이 cp949 로 읽어 한글이 깨진다"),
    ("줄바꿈이 전부 CRLF", lambda p: p.get("crlf_only") is True,
     "LF 만 있으면 옛 메모장이 한 줄로 붙여 보여준다"),
    ("Content-Type text/plain; charset=utf-8",
     lambda p: p.get("content_type") == "text/plain; charset=utf-8", ""),
    ("파일명은 RFC 5987", lambda p: p.get("rfc5987") is True, ""),
    ("파일명 확장자 .txt", lambda p: str(p.get("filename", "")).endswith(".txt"), ""),
    ("파일명에서 경로 구분자·따옴표 제거",
     lambda p: p.get("filename") == _TXT_TITLE_CLEAN,
     f"기대 {_TXT_TITLE_CLEAN}"),
)


def _check_txt_contract(probes: dict, rep: list) -> None:
    label = "txt 규약 대조"
    for rule, predicate, note in _TXT_RULES:
        offenders = [unit for unit, probe in probes.items() if not predicate(probe)]
        detail = ", ".join(f"{u}={probes[u].get('filename') or probes[u]}" for u in offenders)
        rep.append((
            "OK" if not offenders else "FAIL",
            label,
            rule,
            (f"세 단위 동일" if not offenders else f"어긋남: {detail}") + (f" — {note}" if note and offenders else ""),
        ))
    rep.append((
        "OK" if len(probes) == len(CHECKS) else "FAIL",
        label,
        "세 단위 모두 응답을 냈다",
        f"{len(probes)}/{len(CHECKS)} 단위",
    ))


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
    probes: dict = {}

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
        if payload.get("probe"):
            probes[label] = payload["probe"]
        if not payload.get("ok"):
            rep.append(("FAIL", label, "실행", payload.get("error", "알 수 없는 실패")))

    _check_txt_contract(probes, rep)

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
