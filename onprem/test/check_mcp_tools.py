"""MCP 도구 파일 4개 점검 — 결정적 판정이 실제로 나오는가, 한 서버에 같이 올려도 되는가.

```
python onprem/test/check_mcp_tools.py
```

서버도 포트도 필요 없다. 도구 파일을 그대로 실어 함수를 직접 부른다.

## MCP 는 서빙이 아니라 **파일**이다

GenOS MCP 는 **소스 파일 한 개**를 받아 실행하고, `mcp` 객체를 런타임이 전역으로 주입한다.
그래서 우리 쪽에는 FastAPI 앱도 `/health` 도 `$PORT` 도 없다. 파일이 하는 일은
`@mcp.tool()` 로 함수를 등록하는 것뿐이고, 각 함수는 **JSON 문자열**을 돌려준다.

이 점검도 같은 규약을 쓴다 — 파일 안의 `mcp` shim 자리에 도구를 걷어가는 가짜를 심고,
등록된 함수를 직접 부른다. HTTP 를 흉내 내지 않는다.

## 무엇을 보는가

### 1. 같은 서버에 올려도 서로를 덮지 않는가 (`CoexistenceTest`)

네 파일이 **한 서버에 함께 로드될 수 있다.** 그때 최상위 이름이 겹치면 나중에 로드된 쪽이
앞엣것을 덮고, 그 실패는 "도구가 이상한 결과를 낸다" 로만 드러난다. 그래서 모든 심볼에
`HX`/`TG`/`LP`/`GL` 접두어를 붙였고, 여기서 **네 파일을 한 네임스페이스에 넣어** 확인한다.

이건 가상의 위험이 아니다. 합치는 도중 실제로 두 번 밟았다 —
`languages.py` 와 `registers.py` 가 둘 다 `supported_payload` 를 정의해서 `list_languages`
가 **문체 목록**을 돌려줬고, `resolve_tone` 이 함수 이름이자 도구 이름 문자열이라
치환하다가 도구가 통째로 `UNKNOWN_TOOL` 이 됐다.

### 2. 결정적 판정이 실제로 나오는가

MCP 도구는 **LLM 을 부르지 않는다.** 그러니 같은 입력에 같은 판정이 나와야 하고, 그
판정이 실제로 일어나는지 응답으로 확인할 수 있다. 호출이 성공했는지만 보는 점검은
도구가 빈 결과를 돌려줘도 통과하므로 의미가 없다 — 각 도구에 **답이 정해진 입력**을 준다.

### 3. GenOS 의 빈 문자열 주입을 견디는가

**GenOS 는 값이 없을 때 `None` 이 아니라 `""` 를 주입한다.** 그래서 숫자·불리언 인자를
`int`/`float` 로만 선언하면 MCP 가 본문에 닿기 전에 타입 검증에서 죽는다. 선택 인자에
`""` 를 넣어 부르는 경우를 따로 본다.
"""

import asyncio
import base64
import io
import json
import os
import sys
import zipfile

_ONPREM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MCP_DIR = os.path.join(_ONPREM, "mcp")

FILES = ["genon_lang_policy.py", "genon_text_guard.py", "genon_hwpx_text.py", "genon_glossary.py"]

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"


# --------------------------------------------------------------------------
# 도구 수집 — GenOS 가 `mcp` 를 주입하는 자리에 가짜를 심는다
# --------------------------------------------------------------------------

class _CollectingMCP:
    """`@mcp.tool()` 로 등록되는 함수를 걷어간다.

    데코레이터가 **함수를 그대로 돌려줘야** 한다 — 감싸서 다른 것을 돌려주면 그 파일
    안에서 도구끼리 부르는 경우에 동작이 달라진다.
    """

    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self, *args, **kwargs):
        def _decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return _decorator


def _load(filename: str, namespace: dict = None) -> tuple:
    """도구 파일을 실행하고 `(등록된 도구, 네임스페이스)` 를 돌려준다.

    `namespace` 를 주면 **그 안에서** 실행한다 — 네 파일을 한 네임스페이스에 넣어
    서로를 덮는지 보는 데 쓴다. GenOS 가 소스를 exec 하는 방식과 같은 모양이다.
    """
    path = os.path.join(_MCP_DIR, filename)
    with open(path, encoding="utf-8") as handle:
        source = handle.read()

    if namespace is None:
        namespace = {}
    collector = namespace.get("mcp")
    if collector is None:
        collector = _CollectingMCP()
        namespace["mcp"] = collector

    before = set(collector.tools)
    # `__file__` 을 주지 않는다 — GenOS 가 소스를 exec 하면 없을 수 있고,
    # 도구 파일이 그것에 기대면 안 된다.
    namespace["__name__"] = filename[:-3]
    exec(compile(source, path, "exec"), namespace)
    added = {k: v for k, v in collector.tools.items() if k not in before}
    return added, namespace


def _call(fn, **kwargs):
    """도구를 부르고 JSON 을 파싱한다. 도구는 **반드시 JSON 문자열**을 돌려줘야 한다."""
    raw = asyncio.run(fn(**kwargs))
    if not isinstance(raw, str):
        raise AssertionError(f"JSON 문자열이 아니라 {type(raw).__name__} 를 돌려줬다")
    return json.loads(raw)


# --------------------------------------------------------------------------
# 픽스처
# --------------------------------------------------------------------------

def _hwpx_with_merged_table() -> bytes:
    """세로 병합이 든 hwpx. 병합 셀은 **앵커만 존재**하므로 순서대로 채우면 열이 밀린다."""
    def cell(row, col, text, row_span=1):
        return (
            f'<hp:tc><hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
            f'<hp:cellSpan colSpan="1" rowSpan="{row_span}"/>'
            f'<hp:subList><hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p></hp:subList>'
            f'</hp:tc>'
        )

    rows = (
        f'<hp:tr>{cell(0, 0, "항목", 2)}{cell(0, 1, "2025")}{cell(0, 2, "2026")}</hp:tr>'
        f'<hp:tr>{cell(1, 1, "1,200")}{cell(1, 2, "3,400")}</hp:tr>'
    )
    section = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<hs:sec xmlns:hp="{HP}" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section">'
        '<hp:p><hp:run><hp:t>예산 현황</hp:t></hp:run></hp:p>'
        f'<hp:p><hp:run><hp:tbl>{rows}</hp:tbl></hp:run></hp:p>'
        '</hs:sec>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Contents/section0.xml", section)
    return buf.getvalue()


_TABLE_SRC = "| 항목 | 값 |\n| --- | --- |\n| 가 | 1 |\n| 나 | 2 |"
_TABLE_BROKEN = "| 항목 | 값 |\n| --- | --- |\n| 가 | 1 |"


def _simple_hwpx() -> bytes:
    """병합도 중첩도 없는 표. 마크다운으로 손실 없이 표현되므로 형식이 바뀌면 안 된다."""
    def cell(row, col, text):
        return (
            f'<hp:tc><hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
            f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
            f'<hp:subList><hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p></hp:subList></hp:tc>'
        )

    rows = (
        f'<hp:tr>{cell(0, 0, "항목")}{cell(0, 1, "값")}</hp:tr>'
        f'<hp:tr>{cell(1, 0, "예산")}{cell(1, 1, "1,200")}</hp:tr>'
    )
    section = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<hs:sec xmlns:hp="{HP}" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section">'
        f'<hp:p><hp:run><hp:tbl>{rows}</hp:tbl></hp:run></hp:p>'
        '</hs:sec>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Contents/section0.xml", section)
    return buf.getvalue()


def _simple_encoded() -> str:
    return base64.b64encode(_simple_hwpx()).decode("ascii")


# --------------------------------------------------------------------------
# 판정 목록 — (도구, 인자, 라벨, 판정)
# --------------------------------------------------------------------------

def _cases(tools: dict) -> list:
    encoded = base64.b64encode(_hwpx_with_merged_table()).decode("ascii")
    return [
        # ── lang_policy ──
        ("detect_language", {"sample": "본 사업은 2026년에 완료하였습니다."}, "한국어 감지",
         lambda d: (d.get("lang") == "ko", f"lang={d.get('lang')!r}")),
        ("detect_language", {"sample": "123 456 789 ---"}, "감지 불가는 오류가 아니다",
         lambda d: (d.get("lang") == "" and d.get("detected") is False,
                    f"lang={d.get('lang')!r} detected={d.get('detected')!r}")),
        ("validate_direction", {"sample": "This is an English sentence.", "target_lang": "ru"},
         "비한국어 쌍 거부",
         lambda d: (d.get("allowed") is False, f"allowed={d.get('allowed')!r}")),
        ("validate_direction", {"sample": "본 사업은 완료하였습니다.", "target_lang": "en"},
         "한국어 축은 허용",
         lambda d: (d.get("allowed") is True, f"allowed={d.get('allowed')!r}")),
        ("list_languages", {}, "언어 목록이 언어를 낸다",
         lambda d: (any(x.get("code") == "ko" for x in d.get("languages") or []),
                    f"{len(d.get('languages') or [])}개")),
        # 용어사전은 한국어·영어에만 있다 (2026-08-14 요구 확정). **번역 단위
        # `languages.py` 와 같은 표여야 한다** — 갈리면 이쪽이 안내하는 값과 그쪽이
        # 적용하는 값이 달라지고, 준수율은 늘 1.0 이라 정상처럼 보인다.
        ("list_languages", {}, "용어사전 적용 언어는 한국어·영어뿐",
         lambda d: (sorted(d.get("glossary_languages") or []) == ["en", "ko"]
                    and sorted(x["code"] for x in (d.get("languages") or [])
                               if x.get("glossary_supported")) == ["en", "ko"],
                    f"list={d.get('glossary_languages')}")),
        ("validate_direction", {"sample": "본 사업은 완료하였습니다.", "target_lang": "en"},
         "ko→en 은 용어사전 대상",
         lambda d: (d.get("glossary_applies") is True,
                    f"applies={d.get('glossary_applies')!r}")),
        ("validate_direction", {"sample": "본 사업은 완료하였습니다.", "target_lang": "ru"},
         "ko→ru 는 용어사전 대상이 아니다 (거부는 아니다)",
         lambda d: (d.get("allowed") is True and d.get("glossary_applies") is False,
                    f"allowed={d.get('allowed')!r} applies={d.get('glossary_applies')!r}")),
        # ── 한국어 축 (요구사항 §6) — 네 경우를 다 본다 ─────────────────
        # 화면이 선택지를 잘못 그려도, 워크플로우가 잘못 넘겨도 **여기서 걸려야 한다.**
        ("validate_direction", {"sample": "Hello everyone.", "target_lang": "ru", "source_lang": "en"},
         "en→ru 는 거부 (비한국어 쌍)",
         lambda d: (d.get("allowed") is False and "한국어" in (d.get("reason") or ""),
                    f"allowed={d.get('allowed')!r} reason={d.get('reason')!r}")),
        ("validate_direction", {"sample": "Hello everyone, this is a test.", "target_lang": "ru"},
         "원문 미지정이어도 감지해서 en→ru 를 거부",
         lambda d: (d.get("allowed") is False,
                    f"allowed={d.get('allowed')!r} source={d.get('source_lang')!r}")),
        # 감지 불가 + 비한국어 대상 = **한국어 축을 증명할 수 없다.** 그대로 두면 사실상
        # en→ru 를 허용하는 뒷문이 된다 (2026-08-14 에 막았다).
        ("validate_direction", {"sample": "12345 67890 3.14", "target_lang": "ru"},
         "감지 불가 + 비한국어 대상은 거부 (원문 언어를 요구한다)",
         lambda d: (d.get("allowed") is False and "원문 언어" in (d.get("reason") or ""),
                    f"allowed={d.get('allowed')!r} reason={d.get('reason')!r}")),
        ("validate_direction", {"sample": "12345 67890 3.14", "target_lang": "ko"},
         "감지 불가여도 대상이 한국어면 통과 (축이 이미 성립)",
         lambda d: (d.get("allowed") is True,
                    f"allowed={d.get('allowed')!r}")),
        ("validate_direction", {"sample": "안녕하세요.", "target_lang": "ko", "source_lang": "ko"},
         "같은 언어끼리는 거부",
         lambda d: (d.get("allowed") is False, f"allowed={d.get('allowed')!r}")),

        # ── 교차검증 (2026-08-18) — 선언을 그대로 믿지 않는다 ─────────────
        # 그전에는 `source_lang` 이 오면 감지를 **건너뛰었다.** 그래서 화면에서
        # "한국어→러시아어" 를 고르고 영어 문서를 올리면 실제 방향은 `en→ru` 인데
        # 선언을 믿어 통과했다 — §6 이 막으려던 바로 그 쌍이고, 검증 대상 밖 경로가
        # 조용히 쓰인다.
        ("validate_direction",
         {"sample": "Hello everyone, this is an English document about budgets.",
          "target_lang": "ru", "source_lang": "ko"},
         "선언은 한국어인데 문서에 한글이 없으면 거부 (실제로는 en→ru)",
         lambda d: (d.get("allowed") is False and "원문 언어를 확인" in (d.get("reason") or ""),
                    f"allowed={d.get('allowed')!r} reason={(d.get('reason') or '')[:34]}")),
        # **오차단 방지.** 라틴 문자가 최빈이어도 한글이 있으면 한국어 문서다 —
        # 문턱을 최빈값(60%)으로 뒀을 때 이 문장이 거부됐다(라틴 62%). 사용자에게는
        # 우회할 방법이 없는 차단이라 "선언한 언어가 문서에 있는가" 로 근거를 바꿨다.
        ("validate_direction",
         {"sample": "본 사업 KPI 는 ROI, TCO, SLA, API, SDK 로 관리한다.",
          "target_lang": "ru", "source_lang": "ko"},
         "영문 용어가 많은 한국어 문서는 막지 않는다",
         lambda d: (d.get("allowed") is True and (d.get("declared_share") or 0) > 0.10,
                    f"allowed={d.get('allowed')!r} share={d.get('declared_share')!r}")),
        # 충돌이 **통과하는** 경우 — 그 사실을 응답에 실어야 호출부가 로그·안내에 쓴다.
        ("validate_direction",
         {"sample": "안녕하세요. 본 사업은 완료하였습니다.",
          "target_lang": "ko", "source_lang": "th"},
         "대상이 한국어면 충돌해도 통과하되 mismatch 를 낸다",
         lambda d: (d.get("allowed") is True and d.get("source_mismatch") is True
                    and d.get("detected_lang") == "ko",
                    f"allowed={d.get('allowed')!r} mismatch={d.get('source_mismatch')!r} "
                    f"detected={d.get('detected_lang')!r}")),
        # 선언이 정본이다 — 감지가 사용자의 선택을 조용히 덮으면 안 된다.
        ("validate_direction",
         {"sample": "본 사업은 2026년에 완료하였습니다.", "target_lang": "ru", "source_lang": "ko"},
         "감지가 선언을 덮지 않는다",
         lambda d: (d.get("source_lang") == "ko" and d.get("source_declared") is True
                    and d.get("source_mismatch") is False,
                    f"source={d.get('source_lang')!r} declared={d.get('source_declared')!r}")),
        # 선언이 있어도 감지를 **돌린다.** 이게 없으면 교차검증 자체가 성립하지 않는다.
        ("validate_direction",
         {"sample": "본 사업은 완료하였습니다.", "target_lang": "ru", "source_lang": "ko"},
         "선언이 있어도 감지를 돌린다",
         lambda d: (d.get("detected_lang") == "ko", f"detected_lang={d.get('detected_lang')!r}")),
        ("detect_language", {"sample": "본 사업 KPI 는 ROI 로 관리한다."},
         "감지가 지배 비율을 함께 낸다",
         lambda d: (0.0 < (d.get("ratio") or 0) <= 1.0, f"ratio={d.get('ratio')!r}")),

        ("list_registers", {}, "문체 목록이 문체를 낸다",
         lambda d: (any(x.get("code") == "written" for x in d.get("registers") or []),
                    f"{len(d.get('registers') or [])}개")),
        ("resolve_register", {"register": "아무거나"}, "알 수 없는 문체는 기본값 + fell_back",
         lambda d: (d.get("register") == "written" and d.get("fell_back") is True,
                    f"register={d.get('register')!r} fell_back={d.get('fell_back')!r}")),
        ("resolve_tone", {}, "톤 기본값 확정",
         lambda d: (bool(d.get("tone")), f"tone={d.get('tone')!r}")),

        # ── text_guard ──
        ("markdown_structure_issues", {"source": _TABLE_SRC, "revised": _TABLE_BROKEN},
         "표 행 삭제 검출",
         lambda d: (bool(d.get("issues")), f"issues={d.get('issue_count')}건")),
        ("markdown_structure_issues", {"source": _TABLE_SRC, "revised": _TABLE_SRC},
         "훼손 없으면 조용하다",
         lambda d: (not d.get("issues"), f"issues={d.get('issue_count')}건")),
        ("fact_issues", {"source": "예산은 1,200만원이다.", "revised": "예산은 2,400만원이다."},
         "숫자 변조 검출",
         lambda d: (bool(d.get("issues")), f"issues={d.get('issue_count')}건")),
        ("numeric_issues", {"source": "총 1,000건", "revised": "Total 1.000 cases"},
         "자릿수 기호 차이는 오탐이 아니다",
         lambda d: (not d.get("issues"), f"issues={d.get('issue_count')}건")),
        ("diff_changes", {"source": "완료하였다.", "revised": "완료했습니다."}, "변경 내역 산출",
         lambda d: (bool(d.get("changes")), f"changes={d.get('change_count')}건")),

        # ── hwpx_text ──
        ("hwpx_to_markdown", {"content_base64": encoded}, "본문 추출",
         lambda d: ("예산 현황" in (d.get("markdown") or ""), "제목 문단이 있다")),
        ("hwpx_to_markdown", {"content_base64": encoded}, "표 수치 보존",
         lambda d: ("1,200" in (d.get("markdown") or "") and "3,400" in (d.get("markdown") or ""),
                    "표 안 수치가 남아 있다")),
        # 병합 셀은 **마크다운으로 표현할 수 없다** — `rowspan` 문법이 없어 빈 칸이 되고,
        # LLM 은 "머리글 없는 열" 로 읽는다. 그래서 병합이 있으면 HTML 로 낸다.
        ("hwpx_to_markdown", {"content_base64": encoded}, "병합은 rowspan 으로 남는다",
         lambda d: ('rowspan="2"' in (d.get("markdown") or ""),
                    "HTML" if "<table" in (d.get("markdown") or "") else "마크다운(병합 유실)")),
        ("hwpx_to_markdown", {"content_base64": _simple_encoded()}, "단순표는 마크다운 유지",
         lambda d: ("<table" not in (d.get("markdown") or "") and "|" in (d.get("markdown") or ""),
                    "손실이 없으면 형식을 바꾸지 않는다")),
        ("hwpx_to_markdown", {"content_base64": "not-base64!!"}, "잘못된 base64 는 오류 판정",
         lambda d: (d.get("ok") is False, f"error_type={d.get('error_type')!r}")),
        ("hwpx_to_markdown", {"content_base64": "", "path": ""}, "입력이 없으면 오류 판정",
         lambda d: (d.get("ok") is False, f"error_type={d.get('error_type')!r}")),

        # ── glossary ──
        # 사전 미적재 상태를 전제한다 (부모가 용어사전 API 환경변수를 걷어낸다)
        ("glossary_status", {}, "미적재를 숨기지 않는다",
         lambda d: ((d.get("store") or {}).get("loaded") is False,
                    f"store={json.dumps(d.get('store'), ensure_ascii=False)[:70]}")),
        ("glossary_lookup", {"texts": ["본 사업은 완료하였습니다."], "target_lang": "en"},
         "사전 없으면 enabled=false",
         lambda d: (d.get("enabled") is False,
                    f"enabled={d.get('enabled')!r} reason={d.get('reason')!r}")),
        ("glossary_lookup", {"texts": ["본 사업"], "target_lang": "en"},
         "축퇴 경로도 terms 는 매핑이다",
         lambda d: (isinstance(d.get("terms"), dict), f"terms={type(d.get('terms')).__name__}")),
        # 2026-08-14: 적재 출처가 볼륨 파일 → **AI 드라이브 용어사전 API** 로 바뀌었다.
        # 설정이 없을 때 조용히 "적재됨" 으로 보이지 않는 것이 이 판정의 요점이다.
        ("glossary_reload", {}, "API 설정 미완료면 사유를 낸다",
         lambda d: (d.get("ok") is False and d.get("reason") == "api_not_configured",
                    f"reason={d.get('reason')!r}")),
        ("glossary_status", {}, "적재 출처를 상태에 싣는다",
         lambda d: ("source" in (d.get("store") or {}),
                    f"store={d.get('store')!r}")),
    ]


# GenOS 가 빈 문자열을 주입하는 상황. `int`/`float` 로만 선언한 인자가 있으면 여기서 죽는다.
_EMPTY_INJECTION = [
    ("detect_language", {"sample": ""}),
    ("validate_direction", {"sample": "본 사업", "target_lang": "en", "source_lang": ""}),
    ("resolve_tone", {"doc_type": "", "tone": ""}),
    ("resolve_register", {"register": ""}),
    ("diff_changes", {"source": "가", "revised": "나", "max_items": ""}),
    ("markdown_structure_issues", {"source": "", "revised": ""}),
    ("glossary_status", {"target_lang": ""}),
    ("glossary_lookup", {"texts": "", "target_lang": "en"}),
]


# --------------------------------------------------------------------------
# 선택지가 **도구 스키마에 실리는가** (2026-08-18)
#
# 언어·문체·문서유형·톤은 백엔드가 가진 표가 정본이고, 그 표가 **노출되는 스키마의
# `enum`** 으로 나가야 호출부(캔버스 화면·워크플로우 변수·도구를 고르는 LLM)가 자기
# 목록을 들고 있지 않게 된다. 이 검사가 없으면 주석이 `str` 로 되돌아가도 **아무것도
# 실패하지 않는다** — 도구는 그대로 돌고, 드러나는 것은 빈 드롭다운이나 "지원하지 않는
# 언어입니다" 뿐이라 백엔드가 막은 것처럼 보인다.
#
# **기대값을 손으로 적지 않는다.** 모듈의 표에서 만들어 대조한다 — 손으로 적으면 언어가
# 하나 늘 때 점검도 같이 고쳐야 하고, 그러면 대조가 성립하지 않는다.
# --------------------------------------------------------------------------

def _arg_schema(fn) -> dict:
    """도구 시그니처에서 **런타임이 노출할 입력 스키마**를 만든다.

    FastMCP 가 하는 것과 같은 방식이다 — 시그니처의 주석·기본값으로 pydantic 모델을
    세우고 JSON 스키마를 뽑는다. MCP SDK 를 설치하지 않고도 "무엇이 노출되는가" 를
    같은 경로로 볼 수 있다.
    """
    import inspect
    import warnings

    from pydantic import create_model

    fields = {}
    for param in inspect.signature(fn).parameters.values():
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param.name] = (param.annotation, default)
    with warnings.catch_warnings():
        # `register` 같은 인자 이름이 BaseModel 속성과 겹친다는 경고. 스키마에는 영향이 없다.
        warnings.simplefilter("ignore")
        model = create_model(f"{fn.__name__}Args", **fields)
    return model.model_json_schema().get("properties") or {}


def _schema_cases(tools: dict, shared: dict) -> list:
    """(도구, 인자, 라벨, 기대 선택지) 목록. 기대값은 **모듈의 표에서** 만든다."""
    languages = [lang.code for lang in shared["LPSUPPORTED_LANGUAGES"]]
    registers = [reg.key for reg in shared["LPREGISTERS"].values()]
    doc_types = list(shared["LPDOC_TYPE_POLICIES"])
    tones = list(shared["LPTONE_PRESETS"])
    gl_languages = list(shared["_GLLANGUAGE_CODES"])
    return [
        ("validate_direction", "target_lang", languages),
        ("validate_direction", "source_lang", languages),
        ("resolve_register", "register", registers),
        ("resolve_tone", "doc_type", doc_types),
        ("resolve_tone", "tone", tones),
        ("glossary_lookup", "target_lang", gl_languages),
        ("glossary_status", "target_lang", gl_languages),
    ]


def _check_schema_choices(tools: dict, shared: dict, rep: list) -> None:
    try:
        import pydantic  # noqa: F401
    except Exception:  # noqa: BLE001
        # **OK 로 세지 않는다.** 미측정을 통과로 보이게 하면 이 층은 없는 것과 같다.
        rep.append(("SKIP", "스키마 선택지", "pydantic 없음",
                    "런타임(FastMCP)에는 있다 — 로컬에서만 확인을 건너뛴다"))
        return
    for tool_name, arg, expected in _schema_cases(tools, shared):
        fn = tools.get(tool_name)
        if fn is None:
            rep.append(("FAIL", tool_name, f"{arg} 선택지", "도구가 등록되지 않았다"))
            continue
        try:
            prop = _arg_schema(fn).get(arg) or {}
            enum = prop.get("enum")
        except Exception as exc:  # noqa: BLE001
            rep.append(("FAIL", tool_name, f"{arg} 선택지", f"{type(exc).__name__}: {exc}"))
            continue
        # 빈 문자열은 **항상** 들어 있어야 한다 — GenOS 가 미지정을 `""` 로 주입하므로,
        # 빼 두면 스키마를 엄격히 검증하는 호출부가 "미지정" 을 못 보낸다.
        want = list(expected) + [""]
        if enum == want:
            rep.append(("OK", tool_name, f"{arg} 선택지", f"{len(expected)}개 + 빈 문자열"))
        elif enum is None:
            rep.append(("FAIL", tool_name, f"{arg} 선택지",
                        "enum 이 없다 — 맨 str 이면 선택지가 계약 어디에도 안 실린다"))
        else:
            rep.append(("FAIL", tool_name, f"{arg} 선택지",
                        f"표와 다르다: {enum} != {want}"))


def _check_language_copy(shared: dict, rep: list) -> None:
    """언어 표 **사본 대조** — `genon_lang_policy` ↔ `genon_glossary`.

    등록 단위 간 import 이 금지라 강제된 사본이다. 갈리면 한쪽이 허용한 값을 다른 쪽이
    못 알아보는데, 용어사전 쪽에서는 그 실패가 오류가 아니라 **`enabled=false`(사전
    없음)** 로 떨어진다 — 용어사전만 빠진 정상 응답이 나가고 준수율은 늘 1.0 이다.
    """
    policy_codes = [lang.code for lang in shared["LPSUPPORTED_LANGUAGES"]]
    glossary_codes = list(shared["_GLLANGUAGE_CODES"])
    rep.append((
        "OK" if policy_codes == glossary_codes else "FAIL",
        "사본 대조", "언어 코드",
        f"{len(policy_codes)}개 동일" if policy_codes == glossary_codes
        else f"lang_policy={policy_codes} != glossary={glossary_codes}",
    ))
    same_alias = shared["_LPlanguages_ALIASES"] == shared["_GLLANGUAGE_ALIASES"]
    rep.append((
        "OK" if same_alias else "FAIL",
        "사본 대조", "언어 별칭",
        f"{len(shared['_GLLANGUAGE_ALIASES'])}개 동일" if same_alias
        else "별칭 표가 갈렸다 — 한쪽만 아는 표기가 생긴다",
    ))


def _check_glossary_normalization(tools: dict, shared: dict, rep: list) -> None:
    """`target_lang` 표기가 달라도 **같은 사전을 찾는가.**

    `target_lang` 은 색인의 키로 그대로 쓰인다. 정규화가 없으면 `"KO"`·`"한국어"` 가
    `language_missing` 으로 떨어져 **용어사전만 조용히 빠진 번역**이 나간다 — 예외도
    오류도 없고, 대조할 용어가 없으니 준수율은 1.0 이라 정상으로 보인다.

    실제로 사전을 하나 적재해 놓고 부른다. 미적재 상태에서는 어떤 표기를 줘도 똑같이
    `enabled=false` 라 **정규화를 되돌려도 통과**하기 때문이다.
    """
    fn = tools.get("glossary_lookup")
    if fn is None:
        rep.append(("FAIL", "glossary_lookup", "언어 표기 정규화", "도구가 등록되지 않았다"))
        return
    term = shared["GLGlossaryTerm"](term_source="invoice", term_target="세금계산서")
    shared["glload_terms"]("ko", [term])
    try:
        for variant in ("ko", "KO", " ko-KR ", "한국어", "korean"):
            try:
                data = _call(fn, texts=["Please check the invoice today."], target_lang=variant)
                passed = (data.get("enabled") is True
                          and (data.get("terms") or {}).get("invoice") == "세금계산서")
                detail = f"enabled={data.get('enabled')!r} terms={data.get('terms')!r}"
            except Exception as exc:  # noqa: BLE001
                passed, detail = False, f"{type(exc).__name__}: {exc}"
            rep.append(("OK" if passed else "FAIL", "glossary_lookup",
                        f"언어 표기 정규화 ({variant!r})", detail))
    finally:
        # 뒤에 오는 판정이 이 적재를 물려받지 않게 한다.
        shared["glclear_terms"]()


def _check_admin_policy(tools: dict, shared: dict, rep: list) -> None:
    """관리자가 프롬프트 라이브러리에 등록한 톤이 **판정에 반영되는가** (2026-08-18).

    화면 드롭다운은 글다듬이 코드서빙 `GET /policies` 가 그리고, **강제 톤 판정은 이
    MCP 가** 한다. 두 벌이 갈리면 사용자가 화면에서 고른 톤을 워크플로우가 "알 수 없는
    톤" 으로 되돌린다 — 오류는 나지 않고 "고른 톤이 조용히 무시되는" 모양이다.

    admin-api 를 띄우지 않는다. 파일 안 `_LPfetch_policy` 만 대역으로 바꾼다 —
    **파싱 함수(`lpparse_policy_document`)는 진짜를 태운다.** 파싱까지 지어내면
    관리자 JSON 형식이 바뀌어도 이 점검이 통과한다.
    """
    fn = tools.get("resolve_tone")
    parse = shared.get("lpparse_policy_document")
    if fn is None or parse is None:
        rep.append(("FAIL", "resolve_tone", "관리자 정책", "도구/파서가 없다"))
        return

    body = json.dumps({
        "tones": [
            {"code": "legal", "label": "법무체", "instruction": "법률 문서 어투로 다듬는다."},
            {"code": "friendly", "disabled": True},
        ],
        "doc_types": [{"code": "contract", "label": "계약서", "forced_tone": "legal"}],
    }, ensure_ascii=False)

    real_fetch = shared["_LPfetch_policy"]
    shared["_LPfetch_policy"] = lambda: parse(body)
    shared["lpclear_policy_cache"]()
    try:
        cases = [
            ("추가한 톤을 내장 문서유형에서 고를 수 있다", {"doc_type": "email", "tone": "legal"},
             lambda d: (d.get("tone") == "legal" and d.get("tone_overridden") is False,
                        f"tone={d.get('tone')!r} overridden={d.get('tone_overridden')!r}")),
            ("추가한 문서유형이 자기 톤을 강제한다", {"doc_type": "contract", "tone": "polite"},
             lambda d: (d.get("tone") == "legal" and d.get("tone_overridden") is True,
                        f"tone={d.get('tone')!r} overridden={d.get('tone_overridden')!r}")),
            # 병합이지 대체가 아니다 — 관리자가 톤 하나를 넣었다고 내장 강제군이 풀리면
            # '고객발송문구' 가 정중함을 잃는다.
            ("내장 강제 톤은 그대로다", {"doc_type": "customer_notice", "tone": "legal"},
             lambda d: (d.get("tone") == "polite" and d.get("tone_overridden") is True,
                        f"tone={d.get('tone')!r}")),
            ("감춘 내장 톤은 기본값으로 떨어진다", {"doc_type": "email", "tone": "friendly"},
             lambda d: (d.get("tone") == "polite", f"tone={d.get('tone')!r}")),
            ("정책 출처를 응답에 싣는다", {"doc_type": "email", "tone": "legal"},
             lambda d: (d.get("policy_source") == "prompt_library",
                        f"source={d.get('policy_source')!r}")),
        ]
        for label, args, verdict in cases:
            try:
                data = _call(fn, **args)
                passed, detail = verdict(data)
            except Exception as exc:  # noqa: BLE001
                passed, detail = False, f"{type(exc).__name__}: {exc}"
            rep.append(("OK" if passed else "FAIL", "resolve_tone", label, str(detail)))

        # 조회 실패는 **내장 기본값으로 떨어지되 사유를 남긴다.** 예외로 죽으면
        # admin-api 장애가 톤 판정 전체를 멈춘다.
        shared["_LPfetch_policy"] = lambda: shared["_LPempty_policy"]("fetch_failed_404")
        shared["lpclear_policy_cache"]()
        data = _call(fn, doc_type="email", tone="legal")
        rep.append((
            "OK" if data.get("tone") == "polite" and data.get("policy_reason") == "fetch_failed_404"
            else "FAIL",
            "resolve_tone", "조회 실패는 내장값 + 사유",
            f"tone={data.get('tone')!r} reason={data.get('policy_reason')!r}",
        ))
    finally:
        shared["_LPfetch_policy"] = real_fetch
        shared["lpclear_policy_cache"]()



def main() -> int:
    # 사전 미적재 상태를 전제로 판정한다 — 주입돼 있으면 걷어낸다.
    # (2026-08-14: 출처가 볼륨 파일 → AI 드라이브 용어사전 API 로 바뀌었다.)
    for key in ("TRANSLATE_GLOSSARY_API_URL", "TRANSLATE_GLOSSARY_DRIVE_ID",
                "TRANSLATE_GLOSSARY_WORKSPACE_ID", "TRANSLATE_GLOSSARY_TOKEN",
                "TRANSLATE_GLOSSARY_PATH"):
        os.environ.pop(key, None)

    rep: list = []

    # ── 1. 한 네임스페이스에 네 파일을 모두 넣는다 ──────────────────────
    shared: dict = {}
    per_file = {}
    try:
        for filename in FILES:
            added, shared = _load(filename, shared)
            per_file[filename] = set(added)
        tools = shared["mcp"].tools
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 도구 파일 로드 실패: {type(exc).__name__}: {exc}")
        return 1

    total = sum(len(v) for v in per_file.values())
    if len(tools) == total:
        rep.append(("OK", "공존", "도구 이름 충돌 없음",
                    f"{len(tools)}개 = " + " + ".join(
                        f"{f[6:-3]}:{len(v)}" for f, v in per_file.items())))
    else:
        lost = total - len(tools)
        rep.append(("FAIL", "공존", "도구 이름 충돌",
                    f"{total}개 등록했는데 {len(tools)}개만 남았다 ({lost}개가 덮였다)"))

    # 접두어 규율: 도구 함수 **말고는** 공용 이름이 남으면 안 된다.
    # (도구 이름은 LLM 에 노출되는 계약이라 접두어를 붙이지 않는다)
    import types

    exempt = set(tools) | {"mcp", "__name__", "__builtins__"}
    # import 로 들어온 모듈·표준 심볼은 제외한다 — 파일마다 같은 것을 쓰므로 겹쳐도
    # 문제가 아니다 (같은 객체를 가리킨다).
    stdlib_symbols = {"dataclass", "field", "Counter", "List", "TypedDict", "etree", "annotations",
                      # `typing.Annotated` — 도구 인자에 선택지(enum)를 얹을 때 쓴다.
                      # 파일마다 같은 객체를 가리키므로 겹쳐도 덮는 것이 아니다.
                      "Annotated"}

    def is_prefixed(name: str) -> bool:
        """접두어가 붙었는가. **형태는 따지지 않는다.**

        `_GLrun`(합쳐진 본문)과 `_gl_run`(직접 쓴 헬퍼)은 표기가 다를 뿐 둘 다 붙은 것이다.
        여기서 볼 것은 "파일마다 다른 이름인가" 이지 대소문자 규칙이 아니다.
        """
        core = name.lstrip("_")
        return core[:2].upper() in ("HX", "TG", "LP", "GL")

    bare = [
        name for name in shared
        if name not in exempt
        and not name.startswith("__")
        and name not in stdlib_symbols
        and not isinstance(shared[name], types.ModuleType)
        and not is_prefixed(name)
    ]
    if not bare:
        rep.append(("OK", "공존", "접두어 규율", "도구 함수 외에 공용 이름 없음"))
    else:
        rep.append(("FAIL", "공존", "접두어 규율",
                    f"접두어 없는 최상위 이름: {', '.join(sorted(bare)[:8])}"))

    # ── 2. 결정적 판정 ─────────────────────────────────────────────
    for tool_name, args, label, verdict in _cases(tools):
        fn = tools.get(tool_name)
        if fn is None:
            rep.append(("FAIL", tool_name, label, "도구가 등록되지 않았다"))
            continue
        try:
            data = _call(fn, **args)
            passed, detail = verdict(data)
        except Exception as exc:  # noqa: BLE001
            passed, detail = False, f"{type(exc).__name__}: {exc}"
        rep.append(("OK" if passed else "FAIL", tool_name, label, str(detail)))

    # ── 3. 빈 문자열 주입 ──────────────────────────────────────────
    for tool_name, args in _EMPTY_INJECTION:
        fn = tools.get(tool_name)
        if fn is None:
            rep.append(("FAIL", tool_name, "빈 문자열 주입", "도구가 등록되지 않았다"))
            continue
        try:
            data = _call(fn, **args)
            passed = isinstance(data, dict)
            detail = f"ok={data.get('ok')!r}"
        except Exception as exc:  # noqa: BLE001
            passed, detail = False, f"{type(exc).__name__}: {exc}"
        rep.append(("OK" if passed else "FAIL", tool_name, "빈 문자열 주입", detail))

    # ── 4. 선택지가 도구 스키마에 실리는가 ────────────────────────
    _check_schema_choices(tools, shared, rep)
    _check_language_copy(shared, rep)

    # ── 5. 언어 표기 정규화 (사전을 실제로 적재해 놓고 본다) ───────────
    _check_glossary_normalization(tools, shared, rep)

    # ── 6. 관리자 정책(프롬프트 라이브러리)이 판정에 반영되는가 ──────
    _check_admin_policy(tools, shared, rep)

    ok = sum(1 for r in rep if r[0] == "OK")
    fail = sum(1 for r in rep if r[0] == "FAIL")
    skip = sum(1 for r in rep if r[0] == "SKIP")
    name_w = max(len(r[1]) for r in rep)
    item_w = max(len(r[2]) for r in rep)
    for status, name, item, detail in rep:
        mark = {"OK": "OK  ", "SKIP": "SKIP"}.get(status, "FAIL")
        print(f"[{mark}] {name:<{name_w}}  {item:<{item_w}}  {detail}")

    print()
    # **건너뛴 것을 OK 에 섞지 않는다** — 미측정이 통과로 보이면 그 층은 없는 것과 같다.
    print(f"OK {ok} / {ok + fail}" + (f"  (SKIP {skip})" if skip else ""))
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
