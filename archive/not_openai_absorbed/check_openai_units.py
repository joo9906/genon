# -*- coding: utf-8 -*-
"""`not/openai/` 판본 점검 — SDK 전송 규약 + 번역 스트리밍.

    python not/openai/check_openai_units.py

**게이트웨이도 LLM 도 필요 없다.** 대역을 배포 단위 **밖에서** 꽂는다 — 안에 mock
분기를 두면 운영 코드에 테스트용 갈래가 생긴다(저장소 규약).

## 이 판본이 정본과 갈리는 자리만 본다

`not/openai/` 는 `onprem/codeserving/` 의 사본이고 **다른 것은 전송 계층 하나**다
(`llm.py` 4벌 + 번역 스트리밍 경로). 나머지 파일의 회귀는 정본의 그물
(`onprem/test/*`)이 이미 보므로 여기서 다시 보지 않는다 — 두 벌로 검사하면 정본을
고칠 때 이쪽만 옛 판정을 들고 남는다.

층은 셋이다:

1. **정적** — 네 `llm.py` 가 같은 전송 규약을 쓰는가 (전역 클라이언트 없음·
   `max_retries=0`·`model` 실림·`stream` 명시). 한 단위만 어긋나면 그 단위만 다른
   요청을 보내고, 게이트웨이가 그것을 무시하면 **아무 일도 일어나지 않는다.**
2. **기동** — 네 단위가 실제로 import 되고 앱이 뜨는가. SDK 로 바꾸면서 import 하나만
   틀려도 여기서 죽는다.
3. **동작** — 번역 스트리밍이 문서 순서대로 흐르고, 실패해도 원문을 잃지 않고,
   전량 실패에서 **한 글자도 흘리지 않는가**. finalize 의 좌표가 실제로 그 낱말을
   가리키는가.
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

    # 스트리밍은 두 단위만 갖는다 — FAQ·006 은 JSON 스키마라 흘릴 것이 없다.
    for label, has_stream in (("글다듬이", True), ("번역", True), ("FAQ", False), ("006", False)):
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


async def _append(bucket: list, text: str) -> None:
    bucket.append(text)


def main() -> int:
    check_transport_contract()
    check_boot()
    asyncio.run(_stream_checks())
    print()
    print(f"OK {_OK} / FAIL {len(_FAILED)}")
    if _FAILED:
        for name in _FAILED:
            print("  -", name)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
