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
_DOC = "본 사업은 2026년에 완료하였다."


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

        ("list_registers", {}, "문체 목록이 문체를 낸다",
         lambda d: (any(x.get("key") == "written" for x in d.get("registers") or []),
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
        ("evidence_check", {"document": _DOC, "evidences": [_DOC]}, "실제 근거는 통과",
         lambda d: (_ev(d, 0), _ev_desc(d))),
        ("evidence_check", {"document": _DOC, "evidences": ["예산은 50억원으로 증액되었다."]},
         "지어낸 근거는 기각",
         lambda d: (not _ev(d, 0), _ev_desc(d))),
        ("evidence_check", {"document": _DOC, "evidences": json.dumps([_DOC])},
         "근거를 JSON 문자열로 줘도 된다",
         lambda d: (_ev(d, 0), _ev_desc(d))),

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
        # 사전 미적재 상태를 전제한다 (부모가 TRANSLATE_GLOSSARY_PATH 를 걷어낸다)
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
        ("glossary_reload", {}, "경로 미설정이면 사유를 낸다",
         lambda d: (d.get("ok") is False and d.get("reason") == "path_not_configured",
                    f"reason={d.get('reason')!r}")),
    ]


def _ev(d, idx) -> bool:
    items = d.get("results") or []
    return bool(items[idx].get("grounded")) if idx < len(items) else False


def _ev_desc(d) -> str:
    return json.dumps(d.get("results") or [], ensure_ascii=False)[:80]


# GenOS 가 빈 문자열을 주입하는 상황. `int`/`float` 로만 선언한 인자가 있으면 여기서 죽는다.
_EMPTY_INJECTION = [
    ("detect_language", {"sample": ""}),
    ("validate_direction", {"sample": "본 사업", "target_lang": "en", "source_lang": ""}),
    ("resolve_tone", {"doc_type": "", "tone": ""}),
    ("resolve_register", {"register": ""}),
    ("diff_changes", {"source": "가", "revised": "나", "max_items": ""}),
    ("evidence_check", {"document": "가나다", "evidences": "", "min_ratio": ""}),
    ("markdown_structure_issues", {"source": "", "revised": ""}),
    ("glossary_status", {"target_lang": ""}),
    ("glossary_lookup", {"texts": "", "target_lang": "en"}),
]


def main() -> int:
    # 사전 미적재 상태를 전제로 판정한다 — 주입돼 있으면 걷어낸다.
    os.environ.pop("TRANSLATE_GLOSSARY_PATH", None)

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
    stdlib_symbols = {"dataclass", "field", "Counter", "List", "TypedDict", "etree", "annotations"}

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

    ok = sum(1 for r in rep if r[0] == "OK")
    fail = sum(1 for r in rep if r[0] == "FAIL")
    name_w = max(len(r[1]) for r in rep)
    item_w = max(len(r[2]) for r in rep)
    for status, name, item, detail in rep:
        mark = "OK  " if status == "OK" else "FAIL"
        print(f"[{mark}] {name:<{name_w}}  {item:<{item_w}}  {detail}")

    print()
    print(f"OK {ok} / {ok + fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
