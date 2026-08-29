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
import traceback
import urllib.parse

_ONPREM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# txt 규약 대조에 쓰는 값. **여러 줄**이어야 CRLF 판정이 의미를 갖고, 제목에 금지문자가
# 있어야 파일명 정리가 실제로 돌았는지 보인다.
_TXT_TITLE = '보고/서: "초안"'
_TXT_TITLE_CLEAN = "보고서 초안.txt"

# 인라인 강조 제거 규칙(2026-08-14) 대조용. **세 단위가 같은 사본**을 쓰므로 같은 입력에
# 같은 결과가 나와야 한다 — 한 단위만 어긋나면 그 기능에서 받은 파일만 별표가 남는다.
_TXT_MARKS_SAMPLE = "\n".join((
    "# **제목** 뒤 문장",
    "- **항목**: 값 *강조* 끝",
    "**줄 전체 강조**",
    "| 구분 | **상반기** |",
    "snake_case_이름",
    "```",
    "**펜스 안**",
    "```",
))
_TXT_MARKS_EXPECTED = "\n".join((
    "# 제목 뒤 문장",          # 줄머리 `#` 는 구조라 남고, 그 뒤 인라인만 떨어진다
    "- 항목: 값 강조 끝",      # 목록 기호는 남는다
    "**줄 전체 강조**",        # 줄 전체를 감싼 것은 제목 용도라 남긴다
    "| 구분 | 상반기 |",       # 표의 `|` 는 격자다
    "snake_case_이름",         # `_` 를 강조로 오인하면 식별자가 깨진다
    "```",
    "**펜스 안**",             # 코드펜스 안은 손대지 않는다
    "```",
))


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


def _txt_marks_probe(response, kind: str = "text") -> dict:
    """인라인 강조 제거 결과만 뽑는다 (2026-08-14).

    바이트가 아니라 **디코딩한 본문**을 본다 — 여기서 재는 것은 인코딩이 아니라 규칙이고,
    BOM·CRLF 는 위 `_txt_probe` 가 이미 본다.
    """
    text = response.content.decode("utf-8-sig").replace("\r\n", "\n")
    return {"marks_status": response.status_code, "marks_text": text, "marks_kind": kind}


def _check_option_lists(out: list, payload: dict, lists: tuple, label: str) -> None:
    """화면이 드롭다운을 그릴 목록은 **전부 `{code, label}`** 이어야 한다 (2026-08-14).

    사용자는 언어·문체·문서유형을 **우리가 준 보기에서만** 고른다(자유 입력 없음).
    그래서 이 목록들이 곧 프론트 계약인데, 예전에는 같은 응답 안에서도 식별자 이름이
    갈려 있었다 — 언어는 `code`, 문체는 `key`. 화면이 목록마다 다른 키를 읽어야 하고,
    그 상태는 오류가 아니라 **빈 드롭다운**으로만 드러난다.
    """
    for name in lists:
        items = payload.get(name) or []
        ok = bool(items) and all(
            isinstance(x, dict) and x.get("code") and x.get("label") for x in items
        )
        out.append((f"{label} {name} 은 {{code, label}} 목록이다",
                    ok, f"{len(items)}건 / 첫 항목={items[0] if items else None}"))


def _check_llm_client_cache(out: list, module, label: str) -> None:
    """LLM 클라이언트 캐시가 **설정값에 묶여 있는가** (2026-08-14 추가).

    커넥션 재사용을 위해 클라이언트를 캐시하는데, `if _CLIENT is not None` 하나로 두면
    **처음 만들 때의 URL·토큰이 프로세스가 죽을 때까지 고정된다.** 그러면 같은 날 설정을
    호출 시점 읽기로 맞춘 의미가 이 경로에서만 사라지고, 토큰이 회전돼도 옛 값을 쓴다.
    되돌리기 쉬운 자리라(한 줄이면 옛 동작이다) 동작으로 본다.

    번역·글다듬이 **두 사본을 같은 판정으로** 태운다 — 한쪽만 고치면 그 단위만 옛 토큰을
    들고 있는 상태가 되고, 그건 401 이 날 때까지 드러나지 않는다.
    """
    saved = {k: os.environ.get(k) for k in ("GENOS_URL", "LLM_SERVING_ID", "GENOS_TOKEN")}
    try:
        os.environ.update({"GENOS_URL": "https://cache.example",
                           "LLM_SERVING_ID": "srv-1", "GENOS_TOKEN": "tok-1"})
        first = module._resolve_client()
        out.append((f"{label} 설정이 같으면 클라이언트를 재사용한다",
                    module._resolve_client() is first, "커넥션 재사용"))
        os.environ["GENOS_TOKEN"] = "tok-2"
        rotated = module._resolve_client()
        out.append((f"{label} 토큰이 바뀌면 클라이언트를 새로 만든다",
                    rotated is not first, "옛 토큰을 계속 쓰면 401 이 날 때까지 안 드러난다"))
        os.environ["LLM_SERVING_ID"] = "srv-2"
        out.append((f"{label} 서빙 id 가 바뀌면 클라이언트를 새로 만든다",
                    module._resolve_client() is not rotated, ""))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _check_translation(out: list, probe: dict) -> None:
    sys.path.insert(0, os.path.join(_ONPREM, "codeserving", "SFR-018_translation"))
    from fastapi.testclient import TestClient

    import main
    from config import Config

    with TestClient(main.app) as c:
        r = c.get("/languages")
        _check_option_lists(out, r.json() if r.status_code == 200 else {},
                            ("languages", "registers"), "번역")
        body = r.json()
        out.append(("지원 언어 조회",
                    r.status_code == 200 and bool(body.get("languages")),
                    f"HTTP {r.status_code}"))

        # 프론트는 이 응답만 보고 선택지를 그린다 (2026-08-14). 6개가 다 오지 않으면
        # 화면에서 고를 수 없는 언어가 생기고, 그 사실은 오류가 아니라 **없는 버튼**으로만
        # 드러난다.
        codes = [x.get("code") for x in (body.get("languages") or [])]
        out.append(("언어 6개를 화면에 넘긴다",
                    set(codes) == {"ko", "en", "zh", "th", "vi", "ru"},
                    f"{codes}"))

        # 용어사전은 한국어·영어에만 있다. **목록과 언어별 플래그가 같은 말을 해야** 한다 —
        # 갈리면 화면은 배지를 띄우는데 실행은 사전을 안 쓰는 상태가 되고, 준수율은 늘
        # 1.0 이라 정상처럼 보인다.
        flagged = sorted(x["code"] for x in body["languages"] if x.get("glossary_supported"))
        out.append(("용어사전 적용 언어는 한국어·영어뿐",
                    flagged == ["en", "ko"] and sorted(body.get("glossary_languages") or []) == ["en", "ko"],
                    f"flags={flagged} list={body.get('glossary_languages')}"))

        r = c.get("/glossary")
        out.append(("용어사전 상태 조회", r.status_code == 200, f"HTTP {r.status_code}"))

        r = c.post("/translate/markdown", json={"markdown": "안녕", "target_lang": "zz"})
        body = r.json()
        out.append(("지원하지 않는 언어 거절",
                    r.status_code >= 400 and _error_shaped(body),
                    f"HTTP {r.status_code} / {body.get('msg', '')[:40]}"))

        # ── 원문 언어 교차검증 (2026-08-18) ──
        # 그전에는 `source_lang` 이 오면 감지를 **건너뛰었다.** 화면에서 "한국어→러시아어"
        # 를 고르고 영어 문서를 올리면 실제 방향은 `en→ru` 인데 선언을 믿어 통과했다 —
        # §6 이 막으려던 바로 그 쌍이다. **MCP 와 이 단위는 사본 관계**라 둘 다 봐야 한다:
        # 직접 업로드 경로(`POST /translate/*`)는 MCP 를 지나지 않는다.
        r = c.post("/translate/markdown",
                   json={"markdown": "Hello everyone, this is an English document about budgets.",
                         "target_lang": "ru", "source_lang": "ko"})
        body = r.json()
        out.append(("선언한 원문 언어와 문서가 다르면 거절 (실제로는 en→ru)",
                    r.status_code >= 400 and "원문 언어를 확인" in body.get("msg", ""),
                    f"HTTP {r.status_code} / {body.get('msg', '')[:40]}"))

        # **오차단 방지.** 라틴 문자가 최빈이어도 한글이 있으면 한국어 문서다 — 문턱을
        # 최빈값(60%)으로 뒀을 때 이 문장이 거부됐다(라틴 62%). 사용자에게 우회할 방법이
        # 없는 차단이라 "선언한 언어가 문서에 있는가" 로 근거를 바꿨다.
        r = c.post("/translate/markdown",
                   json={"markdown": "본 사업 KPI 는 ROI, TCO, SLA, API, SDK 로 관리한다.",
                         "target_lang": "ru", "source_lang": "ko"})
        out.append(("영문 용어가 많은 한국어 문서는 막지 않는다",
                    r.status_code == 200,
                    f"HTTP {r.status_code} / {r.json().get('msg', '')[:40]}"))

        # 통과한 충돌은 **응답에 실린다.** 없으면 "왜 결과가 이상한가" 에 답할 단서가
        # 사라진다 (`source_lang_detected`·`register_fell_back` 과 같은 취지).
        r = c.post("/translate/markdown",
                   json={"markdown": "안녕하세요. 본 사업은 완료하였습니다.",
                         "target_lang": "ko", "source_lang": "th"})
        opts = (r.json().get("options") or {}) if r.status_code == 200 else {}
        out.append(("통과한 충돌을 응답에 싣는다",
                    opts.get("source_lang_mismatch") is True and opts.get("detected_lang") == "ko",
                    f"HTTP {r.status_code} / mismatch={opts.get('source_lang_mismatch')!r} "
                    f"detected={opts.get('detected_lang')!r}"))

        # ── 좌우 비교 두 값 + 다운로드 링크 (2026-08-28) ──
        #
        # 화면이 원문과 번역문을 좌우로 놓고 비교하므로 **양쪽 사본**이 응답에 있어야
        # 한다. 게이트웨이가 없어 전량 폴백되지만 두 값의 **존재와 구조 보존**은 그
        # 상태에서도 확인된다 — 항등 폴백이면 사본도 원문과 같아야 한다.
        r = c.post("/translate/markdown",
                   json={"markdown": "# 보고서\n\n| 항목 | 값 |\n|---|---|\n| 예산 | 1,200 |",
                         "target_lang": "en", "source_lang": "ko", "title": "테스트"})
        body = r.json() if r.status_code == 200 else {}
        out.append(("원문 사본을 함께 낸다",
                    "source_markdown_highlighted" in body
                    and body.get("source_markdown_highlighted") == body.get("source_markdown"),
                    f"HTTP {r.status_code} / keys={sorted(body)[:6]}"))

        # 업로드는 CDN 이 없는 점검 환경에서 반드시 실패한다. **그때 예외가 아니라
        # `None` 이 나가야** 한다 — 결과를 버리면 다듬어 놓은 번역이 통째로 사라진다.
        out.append(("업로드 실패는 결과를 버리지 않는다",
                    r.status_code == 200 and "download_url" in body
                    and body.get("download_url") is None,
                    f"HTTP {r.status_code} / download_url={body.get('download_url')!r}"))

        # ── 용어사전 적용 범위 (2026-08-14) ──
        # 게이트웨이가 없는 점검 환경이라 번역은 전량 폴백된다. 여기서 보는 것은 번역
        # 품질이 아니라 **용어사전 판정이 방향에 따라 갈리는가**이고, 그 판정은 LLM 과
        # 무관하게 코드가 한다.
        gloss = {}
        for target, expected_applies in (("ru", False), ("en", True)):
            r = c.post("/translate/markdown",
                       json={"markdown": "신용회복위원회 안내입니다", "target_lang": target})
            gloss[target] = (r.status_code, r.json().get("glossary") or {})
        out.append(("한국어·영어 밖은 용어사전을 쓰지 않는다",
                    gloss["ru"][1].get("applies") is False
                    and gloss["en"][1].get("applies") is True,
                    f"ru={gloss['ru'][1].get('applies')} en={gloss['en'][1].get('applies')}"))

        # **"대상 아님" 과 "파일이 없음" 은 다른 사건이다.** 둘 다 available=false 로만
        # 내려가면 준수율이 1.0 인 이유를 운영에서 구분할 수 없다 — 전자는 설계대로고
        # 후자는 관리자가 사전 파일을 넣어야 하는 상태다.
        ru_reason = (gloss["ru"][1].get("source") or {}).get("reason")
        en_reason = (gloss["en"][1].get("source") or {}).get("reason")
        out.append(("사전 미적용 사유가 대상 밖/파일 부재로 갈린다",
                    ru_reason == "not_applicable" and en_reason != "not_applicable",
                    f"ru={ru_reason} en={en_reason}"))

        # 설정이 없으면 **500 이 아니라** 폴백 사유가 실린 200 이다. 예전에는
        # `_resolve_client()` 의 RuntimeError 가 최종 방어선까지 올라가 "잠시 후 다시
        # 시도해 주세요"(500)가 나갔다 — 다시 눌러도 같은 자리에서 실패하는 설정 문제였다.
        out.append(("LLM 설정 부재는 500 이 아니라 폴백 사유로 드러난다",
                    gloss["en"][0] == 200,
                    f"HTTP {gloss['en'][0]}"))

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
        probe.update(_txt_marks_probe(
            c.post("/download", json={"markdown": _TXT_MARKS_SAMPLE, "title": "표시"})
        ))

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

    # 사본 둘을 같은 판정으로 태운다 (헬퍼 머리말 참고)
    from translation_pipeline.common import llm as _translation_llm

    _check_llm_client_cache(out, _translation_llm, "번역")


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

        # ── 관리자 정책 (2026-08-18) ──
        # 고객사 관리자가 프롬프트 라이브러리에 톤을 추가하면 **재배포 없이** 여기 목록에
        # 떠야 한다 (가이드 §10.5). 목록만 보면 "조회 실패" 와 "아직 등록 안 함" 이
        # 구별되지 않으므로 출처·사유를 함께 낸다.
        policy = body.get("policy") or {}
        out.append(("정책 출처를 함께 낸다",
                    policy.get("source") == "builtin" and policy.get("reason") == "not_configured",
                    f"policy={policy}"))

        # 관리자가 넣은 톤이 목록·판정에 반영되는지는 `SFR-018/tests/test_admin_policy.py`
        # 가 본다(가짜 admin-api 를 배포 단위 밖에서 꽂는다). 여기서는 **경로가 있는지**만
        # 본다 — 없으면 관리자가 리비전을 반영해도 캐시 TTL 전까지 화면이 안 바뀐다.
        r = c.post("/policies/reload")
        out.append(("정책 리로드 경로가 있다",
                    r.status_code == 200 and "tones" in r.json(),
                    f"HTTP {r.status_code}"))

        r = c.get("/")
        out.append(("루트에 /download 노출",
                    r.status_code == 200 and "/download" in (r.json().get("endpoints") or []),
                    f"HTTP {r.status_code} / {r.json().get('endpoints')}"))

        polished = "가. 첫째 줄\n나. 둘째 줄"
        r = c.post("/download", json={"polished_text": polished, "title": _TXT_TITLE})
        probe.update(_txt_probe(r))
        probe.update(_txt_marks_probe(
            c.post("/download", json={"polished_text": _TXT_MARKS_SAMPLE, "title": "표시"})
        ))

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

        # ── Gateway 설정 부재를 내부 오류와 가른다 (2026-08-14 추가) ──
        #
        # 그전에는 `llm.py` 의 `_resolve_client()` 가 `RuntimeError` 를 던져 `main.polish`
        # 의 `except Exception` 최종 방어선에 걸렸다. 사용자는 `ERR_INTERNAL`
        # ("요청을 처리하지 못했습니다. **잠시 후 다시 시도해 주세요**")를 받았고 로그
        # error_type 도 `POLISH_INTERNAL_UNCLASSIFIED` 라, **환경변수를 안 넣은 배포
        # 실수라는 사실이 화면에도 로그에도 드러나지 않았다.** 번역·FAQ 는 이미 갈라
        # 뒀는데 이 단위만 남아 있었다.
        #
        # 이 단위의 `Config` 는 환경을 **호출 시점에** 읽으므로 환경변수를 비우면 된다
        # (FAQ·번역은 import 시점에 굳혀서 그쪽 점검은 속성을 직접 비운다).
        saved = {k: os.environ.pop(k, None) for k in ("GENOS_URL", "LLM_SERVING_ID")}
        try:
            r = c.post("/polish", json={"text": "이 문장을 다듬어 주세요.", "doc_type": "report"})
            body = r.json()
            out.append((
                "설정 부재가 내부 오류와 다른 안내문",
                r.status_code >= 400
                and _error_shaped(body)
                and "관리자" in body.get("msg", ""),
                f"HTTP {r.status_code} / {body.get('msg', '')[:30]}",
            ))
            from text_polish.error_codes import ERR_CONFIG_MISSING, ERR_INTERNAL
            out.append((
                "설정 부재는 재시도 불가 · 내부 오류와 다른 error_type",
                ERR_CONFIG_MISSING.retryable is False
                and ERR_CONFIG_MISSING.error_type != ERR_INTERNAL.error_type,
                f"{ERR_CONFIG_MISSING.error_type} retryable={ERR_CONFIG_MISSING.retryable}",
            ))
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value

    # ── 긴 문서를 **조각으로 나눠** 다듬는가 (2026-08-29) ──────────────────
    #
    # 그전에는 문서 전체를 한 번에 LLM 에 보냈다. 입력 상한은 20만 자인데
    # `RES_TIMEOUT` 은 90초라 **상한에 닿기 한참 전에 타임아웃이 먼저 났고**, 그 실패는
    # 재시도 가능(00020001)으로 분류돼 같은 자리에서 또 걸렸다 — 사용자에게 긴 문서는
    # 그냥 안 되는 기능이었다.
    #
    # 규칙 자체(무손실·표·코드펜스)는 `SFR-018/tests/test_polish_chunking.py` 가 본다.
    # **여기서 보는 것은 라우트가 그 경로를 실제로 타는가**다 — 모듈이 맞아도 라우트가
    # 예전처럼 `polish_text_async` 를 직접 부르면 조각은 하나도 안 생긴다.
    from text_polish import polisher as _polisher
    from text_polish.config import Config as _PolishConfig
    from text_polish.llm import LlmResult as _PolishLlmResult

    _saved_call = _polisher.polish_text_async
    _saved_budget = _PolishConfig.MAX_CHUNK_CHARS
    document = "\n\n".join(f"{index}번째 문단입니다." for index in range(8))
    try:
        _PolishConfig.MAX_CHUNK_CHARS = 20
        calls: list = []

        async def _fake_polish(_system, user_text):
            calls.append(user_text)
            return _PolishLlmResult(content=f"[다듬음]{user_text}", error_type="")

        _polisher.polish_text_async = _fake_polish
        with TestClient(main.app) as c:
            r = c.post("/polish", json={"text": document, "doc_type": "report"})
        body = r.json() if r.status_code == 200 else {}
        out.append((
            "긴 문서를 조각으로 나눈다",
            r.status_code == 200 and int(body.get("chunk_count") or 0) > 1
            and len(calls) == int(body.get("chunk_count") or 0),
            f"HTTP {r.status_code} / chunks={body.get('chunk_count')} calls={len(calls)}",
        ))
        out.append((
            "조각을 이어붙여도 문단 경계가 남는다",
            str(body.get("polished_text") or "").count("\n\n") == 7,
            f"빈 줄 {str(body.get('polished_text') or '').count(chr(10) + chr(10))}개 (원문 7개)",
        ))
        out.append((
            "모든 조각이 다듬어졌다",
            str(body.get("polished_text") or "").count("[다듬음]") == len(calls),
            f"{str(body.get('polished_text') or '').count('[다듬음]')}/{len(calls)}",
        ))

        # 부분 실패 — **그 자리에 원문이 남아야 한다.** 빈 문자열로 두면 그 구간이
        # 통째로 사라진 결과가 정상 응답처럼 나간다.
        failed: list = []

        async def _one_fails(_system, user_text):
            failed.append(user_text)
            if len(failed) == 2:
                return _PolishLlmResult(
                    content="", error_type="APITimeoutError", is_transport_error=True
                )
            return _PolishLlmResult(content=f"[다듬음]{user_text}", error_type="")

        _polisher.polish_text_async = _one_fails
        with TestClient(main.app) as c:
            r = c.post("/polish", json={"text": document, "doc_type": "report"})
        body = r.json() if r.status_code == 200 else {}
        text = str(body.get("polished_text") or "")
        out.append((
            "조각 하나가 실패해도 결과를 낸다",
            r.status_code == 200 and int(body.get("failed_chunk_count") or 0) == 1,
            f"HTTP {r.status_code} / failed={body.get('failed_chunk_count')}",
        ))
        out.append((
            "실패한 조각 자리에 원문이 남는다",
            bool(text) and all(f"{index}번째 문단입니다." in text for index in range(8)),
            f"문단 {sum(1 for index in range(8) if str(index) + '번째 문단입니다.' in text)}/8 보존",
        ))

        # 전량 실패는 오류다 — 원문을 그대로 돌려주면 "다듬었는데 바뀐 게 없다" 로 읽힌다.
        async def _all_fail(_system, _user_text):
            return _PolishLlmResult(
                content="", error_type="APITimeoutError", is_transport_error=True
            )

        _polisher.polish_text_async = _all_fail
        with TestClient(main.app) as c:
            r = c.post("/polish", json={"text": document, "doc_type": "report"})
        out.append((
            "전량 실패는 오류로 낸다",
            r.status_code >= 400 and _error_shaped(r.json()),
            f"HTTP {r.status_code}",
        ))
    finally:
        _polisher.polish_text_async = _saved_call
        _PolishConfig.MAX_CHUNK_CHARS = _saved_budget

    with TestClient(main.app) as c:
        r = c.get("/policies")
        _check_option_lists(out, r.json() if r.status_code == 200 else {},
                            ("doc_types", "tones"), "글다듬이")

    from text_polish import llm as _polish_llm

    _check_llm_client_cache(out, _polish_llm, "글다듬이")


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
        # FAQ 는 항목 구조를 스스로 조립하므로(`Q1.` / `[근거]`) 위 두 단위와 같은 본문을
        # 넣을 수 없다. 대신 **답변 안의 인라인 강조가 떨어지는지**만 같은 규칙으로 본다.
        marks_rows = [{"question": "질문", "answer": "답변에 **강조** 가 있다", "sources": "근거"}]
        probe.update(_txt_marks_probe(
            c.post("/download", json={"items": marks_rows, "title": "표시"}), kind="faq"
        ))
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
            FAILURE_CONFIG,
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
                (FAILURE_CONFIG, 500, "설정 부재"),
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
        from faq.error_codes import (
            ERR_API_CONFIG_UNAVAILABLE,
            ERR_API_PROMPT_UNAVAILABLE,
        )
        out.append(("프롬프트 부재는 재시도 불가",
                    ERR_API_PROMPT_UNAVAILABLE.retryable is False,
                    f"retryable={ERR_API_PROMPT_UNAVAILABLE.retryable}"))
        # 설정 부재도 같다 (2026-08-14 분리). 그전에는 `is_transport_error` 가 False
        # 라는 이유만으로 실행 실패에 뭉쳐 502(재시도 가능)로 나갔다.
        out.append(("설정 부재는 재시도 불가",
                    ERR_API_CONFIG_UNAVAILABLE.retryable is False
                    and ERR_API_CONFIG_UNAVAILABLE.code.endswith("00020003"),
                    f"retryable={ERR_API_CONFIG_UNAVAILABLE.retryable} "
                    f"code={ERR_API_CONFIG_UNAVAILABLE.code}"))

        # 설정 부재 분류를 **`llm.py` 부터** 태운다 — 위 판정은 `generate_faqs` 에 대역을
        # 꽂아 분류 **뒤**만 보므로, `_record_failure` 가 `CONFIG_MISSING` 을 다시 실행
        # 실패로 되돌려도 통과한다. 여기서는 실제 그 경로를 돌린다 (LLM 호출은 없다 —
        # 설정이 비어 있으면 `llm_call_async` 가 부르기 전에 돌아선다).
        #
        # **환경변수를 비운다** (2026-08-14). 예전에는 `Config` 속성을 직접 비웠다 —
        # 그때 이 단위의 `Config` 는 import 시점에 값을 굳혀서(`GENOS_URL = os.environ.get(...)`)
        # 환경을 지워도 이미 읽은 값이 쓰였기 때문이다. 지금은 네 단위 모두 **호출 시점에**
        # 읽으므로(`Config.genos_url()`) 환경을 지우는 것이 실제 배포 상황과 같은 모양이다.
        saved = {k: os.environ.get(k) for k in ("GENOS_URL", "LLM_SERVING_ID")}
        os.environ["GENOS_URL"] = ""
        os.environ["LLM_SERVING_ID"] = ""
        try:
            r = c.post("/generate", json={"markdown": "본문입니다.", "count": 3})
            body = r.json()
            out.append(("설정 부재가 실행 실패와 갈린다 (llm.py 경로)",
                        r.status_code == 500 and _error_shaped(body)
                        and body.get("error_code", "").endswith("00020003"),
                        f"HTTP {r.status_code} / {body.get('error_code', '')}"))
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


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
        # **스택을 함께 싣는다** (2026-08-18). 그전에는 `f"{type} : {exc}"` 한 줄만 실었고,
        # 그 한 줄로는 원인을 못 찾는 예외가 실제로 있었다 — `SSL_CERT_FILE` 이 없는 경로를
        # 가리키면 `httpx` 가 `_resolve_client()` 안에서 죽는데, `OSError` 는 filename 인자
        # 없이 올라와 `str(exc)` 가 **"[Errno 2] No such file or directory"** 로만 찍힌다.
        # 어느 파일인지도 어느 층인지도 없어서 손으로 재현해야 알 수 있었다.
        # 이 점검의 존재 이유가 실패를 읽을 수 있게 만드는 것이라 그 자리에서 실패한 셈이다.
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                   "traceback": traceback.format_exc(),
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
    # 2026-08-14: 줄 **중간**의 강조만 뗀다. 줄머리·표 격자·줄 전체 강조·코드펜스는 남는다.
    # 세 단위가 같은 사본을 쓰지만 **본문 조립 방식이 달라** 판정을 둘로 나눈다.
    # 번역·글다듬이는 받은 본문을 그대로 담으므로 전체 결과를 대조하고, FAQ 는 항목을
    # 스스로 조립하므로 "인라인 강조가 떨어졌는가" 만 본다. 둘 다 같은 `to_bytes` 를 탄다.
    ("인라인 강조만 제거 (구조 기호는 보존)",
     lambda p: p.get("marks_text", "").strip() == _TXT_MARKS_EXPECTED
     if p.get("marks_kind") != "faq" else True,
     "줄머리·`|`·줄 전체 강조·펜스 안은 그대로여야 한다"),
    ("FAQ 답변 안의 강조도 떨어진다",
     lambda p: p.get("marks_kind") != "faq"
     or ("**" not in p.get("marks_text", "") and "답변에 강조 가 있다" in p.get("marks_text", "")),
     "같은 `to_bytes` 를 타는지 확인한다"),
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
    tracebacks: list = []

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
            # 표에는 한 줄만 남기고 스택은 아래에 모아 낸다 — 표 칸에 넣으면 정렬이 무너지고,
            # 버리면 원인을 못 찾는다(자식의 `_child_main` 주석 참고).
            if payload.get("traceback"):
                tracebacks.append((label, payload["traceback"]))

    _check_txt_contract(probes, rep)

    ok = sum(1 for r in rep if r[0] == "OK")
    fail = sum(1 for r in rep if r[0] == "FAIL")
    name_w = max(len(r[1]) for r in rep)
    item_w = max(len(r[2]) for r in rep)
    for status, label, item, detail in rep:
        mark = "OK  " if status == "OK" else "FAIL"
        print(f"[{mark}] {label:<{name_w}}  {item:<{item_w}}  {detail}")

    for label, tb in tracebacks:
        print()
        print(f"--- {label} 실행 실패 스택 ---")
        print(tb.rstrip())

    print()
    print(f"OK {ok} / {ok + fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
