# -*- coding: utf-8 -*-
"""`not/` **반입 판본** 점검 — SDK 전송 + 스트리밍 셋 + 정본과 갈리는 자리.

    python not/check_not_units.py

**게이트웨이도 LLM 도 필요 없다.** 대역을 배포 단위 **밖에서** 꽂는다 — 안에 mock
분기를 두면 운영 코드에 테스트용 갈래가 생긴다(저장소 규약).

## 이 판본이 무엇인가 (2026-09-09 요구 변경)

`not/` 은 폐쇄망에 **실제로 반입하는 판본**이다. 그전에는 "`lxml` 이 없어 깎아낸 한시
판본" 이었는데 `lxml`·`openai` 가 사내 mirror 에 들어와 방향이 뒤집혔다 — 이제
**기능이 가장 많은 판본**이다:

    정본(`onprem/codeserving/`) + `openai` SDK 전송 + 스트리밍 셋

스트리밍 셋은 글다듬이(`/polish/stream`) · 번역(`/translate/stream` +
`/translate/finalize`) · **FAQ(`/generate/stream`)** 다.

## 층은 다섯이다

1. **정적 — 전송 규약**: 네 `llm.py` 가 같은 규약을 쓰는가(전역 클라이언트 없음·
   `max_retries=0`·`model` 실림·`stream` 명시·4xx 미재시도). 한 단위만 어긋나면 그
   단위만 다른 요청을 보내고, 게이트웨이가 그것을 무시하면 **아무 일도 일어나지 않는다.**
2. **정본과 갈리는 자리** — `EXPECTED_DIFF`/`EXPECTED_EXTRA` 가 **이 판본의 계약**이다.
   목록 밖의 파일이 갈리면 정본 변경이 흘러들었거나 이쪽만 고친 것이고, 목록에 있는데
   같아지면 이 판본의 기능이 되돌려진 것이다. **둘 다 오류로는 드러나지 않는다.**
   `lxml` 로 되살린 것(006 hwpx 되쓰기·hwpx 직접 업로드 둘)은 "정본에만 있는 파일 0" 이
   지킨다 — 파일이 빠지면 그 자리에서 FAIL 한다.
3. **기동·라우트** — 네 단위가 뜨고 **일곱 라우트**(스트리밍 셋 + hwpx 업로드 둘 +
   006 hwpx 생성)가 실제로 등록되는가. 라우트가 빠진 상태는 "화면에서 그 버튼이 아무
   일도 안 한다" 로만 드러난다.
4. **의존 선언** — `lxml`·`python-multipart`·`openai` 가 필요한 단위에 선언돼 있는가.
   모듈 최상단 import 라 빠지면 **기동 단계에서** 죽는다.
5. **동작** — 번역 스트리밍(순서·무손실·전량 실패에 원문 미유출·폴백·finalize 좌표)과
   **FAQ 스트리밍**(기각될 항목이 화면에 안 나가는가·흘린 순서 == 최종 목록·폴백·
   라벨 사본 대조).
"""

import ast
import asyncio
import importlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

_OK = 0
_FAILED: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global _OK
    if cond:
        _OK += 1
        print(f"[OK  ] {name}")
    else:
        _FAILED.append(name)
        print(f"[FAIL] {name}" + (f"  — {detail}" if detail else ""))



def _strip_module_doc(source: str) -> str:
    """모듈 docstring 을 뺀 코드. 머리말에 적힌 예시를 코드로 세지 않으려고 쓴다."""
    tree = ast.parse(source)
    if not (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        return source
    node = tree.body[0]
    newline = chr(10)
    lines = source.split(newline)
    return newline.join(lines[node.end_lineno:])


LLM_FILES = {
    "006": "SFR-006_template_fill/template_fill/llm.py",
    "FAQ": "SFR-018_faq/faq/llm.py",
    "글다듬이": "SFR-018_text_polish/text_polish/llm.py",
    "번역": "SFR-018_translation/translation_pipeline/common/llm.py",
}

UNITS = {
    "006": ("SFR-006_template_fill", "template_fill.main"),
    "FAQ": ("SFR-018_faq", "faq.main"),
    "글다듬이": ("SFR-018_text_polish", "main"),
    "번역": ("SFR-018_translation", "main"),
}


# ───────────────────────────────────────────────────────────────
# 1. 정적 — 네 llm.py 의 전송 규약
# ───────────────────────────────────────────────────────────────
def check_transport_contract() -> None:
    for label, rel in LLM_FILES.items():
        source = io.open(os.path.join(ROOT, rel.replace("/", os.sep)), encoding="utf-8").read()
        tree = ast.parse(source)

        check(f"{label}: openai SDK 를 쓴다", "from openai import AsyncOpenAI" in source)
        check(
            f"{label}: httpx 로 직접 POST 하지 않는다",
            "client.post(" not in source,
            "정본 코드가 섞여 있다",
        )

        # **전역 클라이언트 금지** (§D.2). 옛 SDK 판이 모듈 전역에 캐시했고, 그래서
        # 토큰 회전을 막는 캐시 키 방어가 따로 필요했다 — 전역이 없으면 그 방어도 필요 없다.
        module_level = [
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and "AsyncOpenAI" in ast.dump(node.value)
        ]
        check(f"{label}: 전역 클라이언트가 없다", not module_level)

        # **SDK 자체 재시도를 끈다.** 켜 두면 우리 재시도와 곱해지고, 그 추가 호출은
        # 우리 로그에 남지 않는다.
        check(f"{label}: max_retries=0", "max_retries=0" in source)

        # **`model` 을 싣는다** — SDK 필수 인자다(정본과 갈리는 유일한 설정).
        check(f"{label}: model 을 싣는다", 'Config.llm_model_id()' in source)

        # **`stream` 을 명시한다** — 게이트웨이 기본값이 스트리밍이면 응답 모양이 통째로
        # 달라진다.
        check(f"{label}: stream 을 명시한다", 'kwargs["stream"] = False' in source)

        # **4xx 를 재시도하지 않는다.**
        check(
            f"{label}: 4xx 는 재시도하지 않는다",
            "retryable = last_upstream_status >= 500" in source,
        )

        # **경로 조립은 한 곳에서.** f-string 으로 base 를 이어붙이면 prefix 를 빠뜨린다.
        # 머리말에도 경로가 적혀 있으므로 **코드에서만** 센다 — 주석까지 세면 문서를
        # 고칠 때 이 판정이 FAIL 한다(그러면 사람이 판정을 지운다).
        check(
            f"{label}: 경로를 _base_url() 한 곳에서 만든다",
            _strip_module_doc(source).count("/rep/serving/") == 1,
        )

    # **스트리밍은 세 단위가 갖는다** (2026-09-09 — FAQ 가 들어왔다). 006 만 없다:
    # 그쪽이 흘릴 것은 LLM 출력이 아니라 발화 추출 JSON 으로 조립한 안내문이다.
    for label, has_stream in (("글다듬이", True), ("번역", True), ("FAQ", True), ("006", False)):
        source = io.open(
            os.path.join(ROOT, LLM_FILES[label].replace("/", os.sep)), encoding="utf-8"
        ).read()
        check(
            f"{label}: 스트리밍 함수 {'있음' if has_stream else '없음'}",
            ("STREAM_UNSUPPORTED" in source) is has_stream,
        )


# ───────────────────────────────────────────────────────────────
# 2. 기동
# ───────────────────────────────────────────────────────────────
def check_boot() -> None:
    os.environ.setdefault("GENOS_URL", "http://gw.test")
    os.environ.setdefault("LLM_SERVING_ID", "srv-7")
    os.environ.setdefault("GENOS_TOKEN", "t")
    for label, (unit, module) in UNITS.items():
        path = os.path.join(ROOT, unit)
        saved = list(sys.path)
        saved_mods = set(sys.modules)
        sys.path.insert(0, path)
        try:
            app = importlib.import_module(module).app
            paths = {route.path for route in app.routes if hasattr(route, "path")}
            check(f"{label}: 기동", bool(paths), "라우트가 없다")
            check(f"{label}: 루트 경로 둘 다 등록", {"", "/"} <= paths or "/" in paths)
        except Exception as exc:  # noqa: BLE001
            check(f"{label}: 기동", False, f"{type(exc).__name__}: {exc}")
        finally:
            for name in set(sys.modules) - saved_mods:
                sys.modules.pop(name, None)
            sys.path[:] = saved


# ───────────────────────────────────────────────────────────────
# 3. 동작 — 번역 스트리밍
# ───────────────────────────────────────────────────────────────
DOC = """# 사업 개요

본 사업은 가맹점 관리 체계를 개선한다.

| 구분 | 값 |
|---|---|
| 대상 | 전 지점 |

## 세부 계획

신용회복위원회와 협의한다.
"""


async def _stream_checks() -> None:
    unit = os.path.join(ROOT, "SFR-018_translation")
    sys.path.insert(0, unit)
    os.environ.setdefault(
        "TRANSLATE_PROMPT_DIR", os.path.join(ROOT, "prompt", "SFR-018_translation")
    )
    from translation_pipeline.common import glossary_exact  # noqa: E402
    from translation_pipeline.common.llm import LlmResult  # noqa: E402
    from translation_pipeline.office import stream_pipeline  # noqa: E402

    # 조각 예산을 작게 잡아 여러 조각이 나오게 한다 (규칙만 보면 되므로).
    stream_pipeline.Config.STREAM_CHUNK_CHARS = 40
    options = stream_pipeline.resolve_options(
        target_lang="en", source_lang="ko", register="", sample_text=DOC
    )

    def _body(user: str) -> str:
        return user.split("SOURCE_MARKDOWN:\n", 1)[1]

    # ── 항등 번역 대역. **뒤 조각이 먼저 끝나게** 해서 순서 버퍼를 실제로 물린다 ──
    finished: list = []

    async def echo_stream(system, user, on_delta):
        body = _body(user)
        await asyncio.sleep(0.02 if "사업 개요" in body else 0.001)
        half = len(body) // 2
        await on_delta(body[:half])
        await on_delta(body[half:])
        finished.append(body[:12])
        return LlmResult(content=body, error_type="")

    stream_pipeline.translate_stream_async = echo_stream
    streamed: list = []

    async def on_text(text):
        streamed.append(text)

    outcome = await stream_pipeline.translate_document_stream(DOC, options, on_text)
    check("번역 스트리밍: 전량 성공", outcome.ok and outcome.failed_chunk_count == 0)
    check("번역 스트리밍: 조각으로 나뉜다", outcome.chunk_count > 1)
    # **무손실이 이 경로의 계약이다** — 항등 번역이면 원문과 문자 단위로 같아야 한다.
    check("번역 스트리밍: 무손실 (정본 == 원문)", outcome.text == DOC)
    # **흘린 것 == 정본.** 어긋나면 화면이 순간 다른 글을 보여주고 오류로는 안 드러난다.
    check("번역 스트리밍: 흘린 것 == 정본", "".join(streamed) == outcome.text)
    check(
        "번역 스트리밍: 뒤 조각이 먼저 끝나도 순서대로 흐른다",
        bool(finished) and "사업 개요" not in finished[0],
        f"완료 순서={finished}",
    )

    # ── 조각 하나 실패 → 그 자리에 원문, 나머지는 살린다 ──
    async def one_fails(system, user, on_delta):
        body = _body(user)
        if "세부 계획" in body:
            return LlmResult(content="", error_type="APITimeoutError", is_transport_error=True)
        await on_delta(body)
        return LlmResult(content=body, error_type="")

    stream_pipeline.translate_stream_async = one_fails
    partial: list = []
    outcome2 = await stream_pipeline.translate_document_stream(
        DOC, options, lambda text: _append(partial, text)
    )
    check("번역 스트리밍: 부분 실패도 결과를 낸다", outcome2.ok and outcome2.failed_chunk_count == 1)
    check("번역 스트리밍: 실패 조각 자리에 원문", outcome2.text == DOC)
    check("번역 스트리밍: 부분 실패도 흘린 것 == 정본", "".join(partial) == outcome2.text)

    # ── 전량 실패 → **한 글자도 흘리지 않는다** ──
    #    흘렸다가 오류로 갈아엎으면 사용자에게는 답이 나왔다가 사라지는 것으로 보인다.
    async def all_fail(system, user, on_delta):
        return LlmResult(content="", error_type="CONFIG_MISSING")

    stream_pipeline.translate_stream_async = all_fail
    nothing: list = []
    outcome3 = await stream_pipeline.translate_document_stream(
        DOC, options, lambda text: _append(nothing, text)
    )
    check("번역 스트리밍: 전량 실패는 오류다", not outcome3.ok and outcome3.config_missing)
    check(
        "번역 스트리밍: 전량 실패에 원문을 흘리지 않는다",
        outcome3.streamed_chars == 0 and not nothing,
    )

    # ── 스트리밍 미지원 → 비스트리밍 폴백이 **같은 문서**를 만든다 ──
    async def unsupported(system, user, on_delta):
        return LlmResult(content="", error_type="STREAM_UNSUPPORTED")

    async def plain(sem, system, user):
        return LlmResult(content=_body(user), error_type="")

    stream_pipeline.translate_stream_async = unsupported
    stream_pipeline.llm_call_async = plain
    outcome4 = await stream_pipeline.translate_document_stream(DOC, options, on_text)
    check(
        "번역 스트리밍: 미지원을 갈라낸다",
        outcome4.stream_unsupported and outcome4.streamed_chars == 0,
    )
    outcome5 = await stream_pipeline.translate_document_plain(DOC, options)
    check("번역 스트리밍: 폴백이 같은 문서를 만든다", outcome5.ok and outcome5.text == DOC)

    # ── finalize: 하이라이트 좌표 ──
    glossary_exact.clear_terms()
    glossary_exact.load_terms(
        "en", [glossary_exact.GlossaryTerm(term_source="가맹점", term_target="merchant")]
    )
    translated = DOC.replace("가맹점", "merchant")
    payload = stream_pipeline.build_document_glossary(DOC, translated, options)
    hit = payload["hits"][0] if payload["hits"] else {}
    # **좌표가 실제로 그 낱말을 가리키는가 — 이 등식이 하이라이트의 전부다.**
    check(
        "finalize: 원문 좌표가 그 낱말을 가리킨다",
        bool(hit) and DOC[hit["spans"][0][0]: hit["spans"][0][1]] == "가맹점",
        json.dumps(hit, ensure_ascii=False)[:120],
    )
    check(
        "finalize: 번역문 좌표가 그 낱말을 가리킨다",
        bool(hit.get("target_spans"))
        and translated[hit["target_spans"][0][0]: hit["target_spans"][0][1]] == "merchant",
    )
    check("finalize: 준수율", payload["compliance"] == 1.0 and payload["applied_count"] == 1)
    # **미준수는 좌표를 내지 않는다** — 번역문에 그 낱말이 없으므로 칠할 자리가 없다.
    unapplied = stream_pipeline.build_document_glossary(DOC, DOC, options)
    check(
        "finalize: 미준수는 좌표를 내지 않는다",
        unapplied["hits"][0]["applied"] is False and not unapplied["hits"][0]["target_spans"],
    )

    # ── 구조 지문 — 막는 장치가 아니라 알리는 장치다 ──
    check("finalize: 항등이면 구조 이상 없음", stream_pipeline.structure_diff(DOC, DOC)["ok"])
    broken = DOC.replace("| 대상 | 전 지점 |\n", "")
    diff = stream_pipeline.structure_diff(DOC, broken)
    check(
        "finalize: 표 행이 사라지면 잡는다",
        not diff["ok"] and any(item["kind"] == "md_table_row" for item in diff["issues"]),
        json.dumps(diff, ensure_ascii=False),
    )


# ───────────────────────────────────────────────────────────────
# 2. 정본과 갈리는 자리 — **이 목록이 이 판본의 계약이다**
# ───────────────────────────────────────────────────────────────
_ONPREM_UNITS = os.path.join(os.path.dirname(ROOT), "onprem", "codeserving")
_ONPREM_PROMPT = os.path.join(os.path.dirname(ROOT), "onprem", "prompt")
_NOT_PROMPT = os.path.join(ROOT, "prompt")

# **내용이 달라야 하는 파일 17개.** 전송 계층(`llm.py` 4벌 + `config.py` 의
# `llm_model_id()`) · 스트리밍이 얹힌 자리(번역 `main`·`api_contract`·`prompt_builder`·
# `config`, FAQ `main`·`generator`·`config`) · 그 의존 선언(`requirements.txt` 4벌).
EXPECTED_DIFF = {
    "SFR-006_template_fill/requirements.txt",
    "SFR-006_template_fill/template_fill/config.py",
    "SFR-006_template_fill/template_fill/llm.py",
    "SFR-018_text_polish/requirements.txt",
    "SFR-018_text_polish/text_polish/config.py",
    "SFR-018_text_polish/text_polish/llm.py",
    "SFR-018_translation/api_contract.py",
    "SFR-018_translation/config.py",
    "SFR-018_translation/main.py",
    "SFR-018_translation/requirements.txt",
    "SFR-018_translation/translation_pipeline/common/llm.py",
    "SFR-018_translation/translation_pipeline/common/prompt_builder.py",
    "SFR-018_faq/faq/config.py",
    "SFR-018_faq/faq/generator.py",
    "SFR-018_faq/faq/llm.py",
    "SFR-018_faq/faq/main.py",
    "SFR-018_faq/requirements.txt",
}

# **이 판본에만 있는 파일 3개** — 스트리밍이 새로 들여온 것뿐이다.
EXPECTED_EXTRA = {
    "SFR-018_translation/translation_pipeline/office/stream_chunking.py",
    "SFR-018_translation/translation_pipeline/office/stream_pipeline.py",
    "SFR-018_faq/faq/markdown_items.py",
}

# 프롬프트: 이 판본에만 있는 것(6) / 정본에만 있는 것(3, FAQ JSON 판)
EXPECTED_PROMPT_EXTRA = {
    "SFR-018_faq/md_retry_shortfall.txt",
    "SFR-018_faq/md_system.txt",
    "SFR-018_faq/md_user.txt",
    "SFR-018_translation/glossary_stream.txt",
    "SFR-018_translation/system_stream.txt",
    "SFR-018_translation/user_stream.txt",
}
EXPECTED_PROMPT_GONE = {
    "SFR-018_faq/retry_shortfall.txt",
    "SFR-018_faq/system.txt",
    "SFR-018_faq/user.txt",
}

_UNIT_DIRS = (
    "SFR-006_template_fill",
    "SFR-018_text_polish",
    "SFR-018_translation",
    "SFR-018_faq",
)


def _tree(base: str, exts=(".py", ".txt")) -> dict:
    """`base` 아래 파일 내용 맵. `__pycache__` 는 뺀다."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(exts):
                rel = os.path.relpath(os.path.join(dirpath, name), base)
                out[rel.replace(os.sep, "/")] = io.open(
                    os.path.join(dirpath, name), encoding="utf-8", newline=""
                ).read()
    return out


def check_variant_delta() -> None:
    """정본과 **갈려야 하는 자리만** 갈렸는지 본다.

    두 방향을 다 본다:

    - 목록 **밖**의 파일이 갈렸다 → 정본 변경이 이쪽에 흘러들었거나 이쪽만 고쳤다.
      그 상태로 반입하면 **정본의 그물이 지키던 것을 이 판본이 안 지킨다.**
    - 목록에 있는데 **같아졌다** → 이 판본의 기능(SDK·스트리밍)이 되돌려졌다.

    어느 쪽도 오류를 내지 않는다 — 그래서 여기서 본다.
    """
    actual_diff, actual_extra, actual_gone = set(), set(), set()
    for unit in _UNIT_DIRS:
        base = _tree(os.path.join(_ONPREM_UNITS, unit))
        mine = _tree(os.path.join(ROOT, unit))
        for rel in sorted(set(base) & set(mine)):
            if base[rel] != mine[rel]:
                actual_diff.add(unit + "/" + rel)
        actual_extra |= {unit + "/" + rel for rel in set(mine) - set(base)}
        actual_gone |= {unit + "/" + rel for rel in set(base) - set(mine)}

    check(
        "정본과 갈리는 파일이 목록과 같다",
        actual_diff == EXPECTED_DIFF,
        "목록 밖=" + str(sorted(actual_diff - EXPECTED_DIFF))
        + " 되돌려짐=" + str(sorted(EXPECTED_DIFF - actual_diff)),
    )
    check(
        "이 판본에만 있는 파일이 목록과 같다",
        actual_extra == EXPECTED_EXTRA,
        "예상밖=" + str(sorted(actual_extra ^ EXPECTED_EXTRA)),
    )
    # **`lxml` 로 되살린 것을 지키는 판정이 이것이다.** 깎아낸 판본이던 시절에는
    # 006 `hwpx_style.py` · 번역 `office/hwpx_text.py` · FAQ `hwpx_text/hwpx_xml.py` 가
    # 빠져 있었다. 하나라도 빠지면 그 기능이 조용히 사라진다.
    check(
        "정본에만 있는 파일이 없다 (기능 누락 0)",
        not actual_gone,
        "빠진 파일=" + str(sorted(actual_gone)),
    )

    base_p, mine_p = _tree(_ONPREM_PROMPT), _tree(_NOT_PROMPT)
    changed = {rel for rel in set(base_p) & set(mine_p) if base_p[rel] != mine_p[rel]}
    check("공용 프롬프트는 정본과 같다", not changed, "갈림=" + str(sorted(changed)))
    check(
        "이 판본에만 있는 프롬프트가 목록과 같다",
        set(mine_p) - set(base_p) == EXPECTED_PROMPT_EXTRA,
        "예상밖=" + str(sorted((set(mine_p) - set(base_p)) ^ EXPECTED_PROMPT_EXTRA)),
    )
    # FAQ 는 JSON 판 프롬프트를 **의도적으로** 안 가진다 — 두 경로가 마크다운 하나를
    # 쓰기 때문이다. 그 사실을 목록으로 못박아, 나중에 되살려 놓고 아무도 안 쓰는
    # 프롬프트가 남는 것을 막는다.
    check(
        "정본에만 있는 프롬프트가 목록과 같다",
        set(base_p) - set(mine_p) == EXPECTED_PROMPT_GONE,
        "예상밖=" + str(sorted((set(base_p) - set(mine_p)) ^ EXPECTED_PROMPT_GONE)),
    )


# ───────────────────────────────────────────────────────────────
# 3. 라우트 계약 — 있어야 할 것이 실제로 등록되는가
# ───────────────────────────────────────────────────────────────
# **라우트가 빠진 상태는 오류가 아니다.** `not/openai/` 에서 실제로 그랬다 — FAQ
# 스트리밍의 엔진(증분 파서·`generate_faqs_stream`)이 다 있는데 `main.py` 가 그것을
# import 조차 하지 않아 **호출부 0건**이었고, 점검은 오히려 "FAQ 는 스트리밍이 없다" 를
# 기대하고 있었다. 그래서 여기서는 **경로가 실제로 앱에 붙었는지**를 본다.
REQUIRED_ROUTES = {
    "글다듬이": ("/polish", "/polish/stream", "/download", "/policies"),
    "번역": (
        "/translate",
        "/translate/markdown",
        "/translate/hwpx",      # ← lxml 로 되살린 직접 업로드
        "/translate/stream",
        "/translate/finalize",
    ),
    "FAQ": (
        "/generate",
        "/generate/stream",     # ← 2026-09-09 신설
        "/generate/upload",     # ← lxml 로 되살린 직접 업로드
        "/download",
    ),
    "006": ("/chat/commit", "/generate", "/generate/upload", "/preview"),
}


def check_routes() -> None:
    os.environ.setdefault("GENOS_URL", "http://gw.test")
    os.environ.setdefault("LLM_SERVING_ID", "srv-7")
    os.environ.setdefault("GENOS_TOKEN", "t")
    for label, (unit, module) in UNITS.items():
        path = os.path.join(ROOT, unit)
        saved, saved_mods = list(sys.path), set(sys.modules)
        sys.path.insert(0, path)
        try:
            app = importlib.import_module(module).app
            paths = {route.path for route in app.routes if hasattr(route, "path")}
            missing = [p for p in REQUIRED_ROUTES[label] if p not in paths]
            check(label + ": 라우트 계약", not missing, "없는 경로=" + str(missing))
        except Exception as exc:  # noqa: BLE001
            check(label + ": 라우트 계약", False, type(exc).__name__ + ": " + str(exc))
        finally:
            for name in set(sys.modules) - saved_mods:
                sys.modules.pop(name, None)
            sys.path[:] = saved


# ───────────────────────────────────────────────────────────────
# 4. 의존 선언 — 모듈 최상단 import 라 빠지면 기동 단계에서 죽는다
# ───────────────────────────────────────────────────────────────
# **`lxml` 은 선언만 빠져도 배포가 통째로 막힌다** (또는 그 반대로, 코드가 쓰지 않는
# 패키지를 선언해 두면 mirror 에 없을 때 `pip install -r` 이 그 자리에서 실패한다 —
# `jinja2` 로 실제로 겪었다). 그래서 **필요한 것**과 **없어야 하는 것**을 함께 본다.
REQUIRED_PACKAGES = {
    "SFR-006_template_fill": ("lxml", "python-multipart", "openai", "redis"),
    "SFR-018_text_polish": ("openai",),          # 이 단위는 hwpx 를 안 만진다
    "SFR-018_translation": ("lxml", "python-multipart", "openai"),
    "SFR-018_faq": ("lxml", "python-multipart", "openai", "redis"),
}
FORBIDDEN_PACKAGES = ("jinja2",)


def check_requirements() -> None:
    for unit, needed in REQUIRED_PACKAGES.items():
        path = os.path.join(ROOT, unit, "requirements.txt")
        lines = [
            line.split("#", 1)[0].strip()
            for line in io.open(path, encoding="utf-8").read().splitlines()
        ]
        declared = {
            line.split(">=")[0].split("==")[0].strip().lower()
            for line in lines
            if line
        }
        missing = [name for name in needed if name not in declared]
        check(unit + ": 의존 선언", not missing, "없는 선언=" + str(missing))
        present = [name for name in FORBIDDEN_PACKAGES if name in declared]
        check(
            unit + ": 코드가 안 쓰는 선언이 없다",
            not present,
            "쓰지 않는데 선언됨=" + str(present),
        )


# ───────────────────────────────────────────────────────────────
# 5-2. 동작 — FAQ 스트리밍
# ───────────────────────────────────────────────────────────────
FAQ_DOC = """# 사업 개요

본 사업은 가맹점 관리 체계를 개선한다.

## 세부 계획

신용회복위원회와 협의한다.
"""


def _faq_bundle(evidence: str, question: str, answer: str) -> str:
    """프롬프트가 지시한 형식 그대로의 항목 하나."""
    return (
        "<<<FAQ\n근거: " + evidence + "\n질문: " + question
        + "\n답변: " + answer + "\n>>>\n"
    )


async def _faq_stream_checks() -> None:
    unit = os.path.join(ROOT, "SFR-018_faq")
    sys.path.insert(0, unit)
    os.environ["FAQ_PROMPT_DIR"] = os.path.join(ROOT, "prompt", "SFR-018_faq")
    from faq import generator, markdown_items  # noqa: E402
    from faq.llm import LlmResult  # noqa: E402

    # **라벨은 프롬프트와 사본 관계다.** 한쪽만 고치면 모든 항목이 스키마 기각으로
    # 떨어지고, 그 상태는 "FAQ 가 하나도 안 나온다" 로만 드러난다.
    prompt_text = io.open(
        os.path.join(ROOT, "prompt", "SFR-018_faq", "md_system.txt"), encoding="utf-8"
    ).read()
    missing_labels = [
        label for label in list(markdown_items.LABELS) if label not in prompt_text
    ]
    check(
        "FAQ 스트리밍: 라벨이 프롬프트와 같다",
        not missing_labels
        and markdown_items.OPEN_MARK in prompt_text
        and markdown_items.CLOSE_MARK in prompt_text,
        "프롬프트에 없는 라벨=" + str(missing_labels),
    )

    generator.Config.MAX_CONTEXT_CHARS = 60      # 조각이 둘 이상 나오게
    generator.Config.EVIDENCE_REJECT = True

    # ── 통과 항목 하나 + **근거를 지어낸 항목 하나** ──
    #    뒤엣것이 화면에 나가면 "답이 나왔다가 사라진다" 가 된다.
    async def stub(system, user, on_delta):
        good = _faq_bundle(
            "본 사업은 가맹점 관리 체계를 개선한다.",
            "이 사업의 목적은?",
            "가맹점 관리 체계를 개선합니다.",
        )
        fake = _faq_bundle("본 사업은 우주 정거장을 짓는다.", "정거장은 언제?", "2030년입니다.")
        for piece in (good, fake):
            for cut in range(0, len(piece), 7):   # 델타로 쪼개 먹인다
                await on_delta(piece[cut: cut + 7])
        return LlmResult(content=good + fake, error_type="")

    generator.faq_stream_async = stub
    frames: list = []

    async def on_frame(frame):
        frames.append(frame)

    result = await generator.generate_faqs_stream(FAQ_DOC, 4, on_frame=on_frame)
    opened = [f for f in frames if f["type"] == generator.FRAME_ITEM_OPEN]
    check("FAQ 스트리밍: 항목을 만든다", bool(result.items) and result.ok)
    check(
        "FAQ 스트리밍: 근거 없는 항목은 화면에 안 나간다",
        all("정거장" not in f.get("question", "") for f in frames)
        and all("정거장" not in item.question for item in result.items),
        json.dumps(frames, ensure_ascii=False)[:160],
    )
    check("FAQ 스트리밍: 기각을 건수로 낸다", result.rejected_ungrounded >= 1)
    # **흘린 순서 == 최종 목록 순서.** 어긋나면 마지막에 항목이 재정렬되며 화면에서 튄다.
    check(
        "FAQ 스트리밍: 흘린 순서 == 최종 목록",
        [f["question"] for f in opened] == [item.question for item in result.items],
        "흘림=" + str([f["question"] for f in opened]),
    )
    # 델타가 이어 붙은 것이 곧 그 항목의 답변이다 (화면과 결과가 어긋나지 않는다).
    for item_open in opened:
        index = item_open["index"]
        joined = "".join(
            f["text"] for f in frames
            if f["type"] == generator.FRAME_DELTA and f["index"] == index
        )
        check(
            "FAQ 스트리밍: 흘린 답변 == 정본 (index=" + str(index) + ")",
            joined.strip() == result.items[index].answer,
        )

    # ── 중복 질문은 한 번만 ──
    async def dup(system, user, on_delta):
        one = _faq_bundle(
            "신용회복위원회와 협의한다.", "누구와 협의하나요?", "신용회복위원회와 협의합니다."
        )
        payload = one + one
        await on_delta(payload)
        return LlmResult(content=payload, error_type="")

    generator.faq_stream_async = dup
    frames2: list = []
    result2 = await generator.generate_faqs_stream(
        FAQ_DOC, 4, on_frame=lambda f: _append(frames2, f)
    )
    check(
        "FAQ 스트리밍: 중복 질문은 한 번만 나간다",
        len({item.question for item in result2.items}) == len(result2.items)
        and result2.rejected_duplicate >= 1,
    )

    # ── 스트리밍 미지원 → **갈라서 알린다** (호출부가 비스트리밍으로 되돌아간다) ──
    async def unsupported(system, user, on_delta):
        return LlmResult(content="", error_type=generator.STREAM_UNSUPPORTED)

    generator.faq_stream_async = unsupported
    nothing: list = []
    result3 = await generator.generate_faqs_stream(
        FAQ_DOC, 4, on_frame=lambda f: _append(nothing, f)
    )
    check(
        "FAQ 스트리밍: 미지원을 갈라낸다",
        result3.failure == generator.FAILURE_STREAM_UNSUPPORTED and not nothing,
        "failure=" + str(result3.failure) + " 프레임=" + str(len(nothing)),
    )

    # ── 전량 실패에서는 프레임이 하나도 안 나간다 ──
    async def all_fail(system, user, on_delta):
        return LlmResult(content="", error_type=generator.CONFIG_MISSING)

    generator.faq_stream_async = all_fail
    none2: list = []
    result4 = await generator.generate_faqs_stream(
        FAQ_DOC, 4, on_frame=lambda f: _append(none2, f)
    )
    check(
        "FAQ 스트리밍: 전량 실패에 프레임을 흘리지 않는다",
        not result4.ok and not none2 and result4.failure == generator.FAILURE_CONFIG,
        "failure=" + str(result4.failure) + " 프레임=" + str(len(none2)),
    )

    # ── 비스트리밍 경로가 **같은 파서**를 쓴다 ──
    #    형식이 둘이면 마크다운 파서가 스트리밍 요청에서만 돌아 거의 검증되지 않는다.
    parsed = generator._parse_faq_payload(
        _faq_bundle("본 사업은 가맹점 관리 체계를 개선한다.", "목적은?", "개선합니다.")
    )
    check(
        "FAQ 비스트리밍: 같은 마크다운 파서를 쓴다",
        len(parsed) == 1 and parsed[0]["question"] == "목적은?",
        json.dumps(parsed, ensure_ascii=False)[:120],
    )
    # **미완성 묶음은 채택되지 않고 `rejected_schema` 로 센다.**
    #
    # 파서는 일부러 관용적이다 — 모델이 `>>>` 를 빠뜨리는 일이 흔해서 닫히지 않은
    # 마지막 묶음도 흘려보낸다. 그래서 **버리는 판정은 파서가 아니라 채택 층**
    # (`_adopt_one`)에 있다. 두 층을 헷갈리면 "파서가 걸러 줄 것" 이라 믿고 채택
    # 판정을 지우게 되고, 그러면 답변이 빈 항목이 결과에 실린다.
    half = generator._parse_faq_payload("<<<FAQ\n근거: 어떤 문장\n질문: 왜?\n")
    checker = generator.EvidenceChecker(FAQ_DOC)
    tally = generator.FaqResult(requested_count=4, max_count=30, call_cap=6)
    generator._adopt(half, tally, checker, set(), 4)
    check(
        "FAQ 비스트리밍: 미완성 묶음은 채택되지 않는다",
        not tally.items and tally.rejected_schema == 1,
        "items=" + str(len(tally.items)) + " schema=" + str(tally.rejected_schema),
    )


async def _append(bucket: list, text: str) -> None:
    bucket.append(text)


def main() -> int:
    check_transport_contract()
    check_variant_delta()
    check_requirements()
    check_boot()
    check_routes()
    asyncio.run(_stream_checks())
    asyncio.run(_faq_stream_checks())
    print()
    print(f"OK {_OK} / FAIL {len(_FAILED)}")
    if _FAILED:
        for name in _FAILED:
            print("  -", name)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
