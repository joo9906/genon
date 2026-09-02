"""통합 전처리기(`onprem/preprocessor/final_preprocessor.py`) 점검.

`python onprem/test/check_final_preprocessor.py`

## 왜 따로 보나

이 파일은 **생성물**이다 — `build_final_preprocessor.py` 가 첨부용 벤더와 hwpx 파서,
라우터를 한 등록 단위로 붙인다. 그래서 세 종류의 결함이 생길 수 있고, **셋 다 예외를
던지지 않는다**:

1. **생성물이 원본과 갈렸다** — 빌드를 안 돌리고 커밋하면 등록 화면에 올라간 파일만
   옛 코드로 남는다. 여기서 다시 만들어 대조한다.
2. **개명이 샜다** — 세 조각이 다 `DocumentProcessor` 를 정의한다. 진입점이 엉뚱한
   것으로 남으면 라우팅이 통째로 사라지고, `Document` 가 덮이면 첨부용 20개 호출부가
   **호출 시점에** 터진다(import 는 통과한다).
3. **라우팅이 틀렸다** — hwpx 가 벤더로 새면 표 병합이 깨지는데 **적재는 성공으로
   보인다.** 반대로 pdf 가 hwpx 파서로 가면 그 문서가 검색에서 통째로 사라진다.

## 지능형은 2026-09-01 에 빠졌다

그전에는 `intelligence_processor.py` 가 PART 2 로 함께 들어가 pdf·ppt·엑셀·이미지를
받았고, 첨부용과 최상위 이름 24개가 겹쳐 그 겹침 처리(제거 13 / 개명 8 / 보존 3)를
지키는 판정이 여기 한 무더기 있었다. **그 경로가 실환경에서 동작하지 않아 통째로
걷어냈다** — 겹침 판정도 함께 없어졌다.

**pdf 는 계속 첨부용으로 처리되고 조문 위계도 걸린다.** 다만 원본 문서 모양이 달라져
어댑터가 둘이 됐다(`DoclingDocument` ↔ langchain `Document` 목록) — 그 두 갈래를
각각 태우는 것이 이 점검의 새 몫이다.

## 벤더 절반이 없는 환경에서 돈다

docling·`genon.preprocessor.*` 가 로컬에 없으므로 PART 1 은 적재되지 않는다. 그것
자체가 점검 대상이다(**그 상태에서도 hwpx 경로는 살아 있어야 한다**). 벤더가 실제로
불리는 갈래는 **대역을 라우터 밖에서 꽂아** 확인한다 — 폴백·kwargs 전달·지연 생성처럼
"벤더가 있을 때만" 도는 코드가 그렇지 않으면 한 번도 검사되지 않는다.
"""

import ast
import asyncio
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

_ONPREM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(_ONPREM)
_PREPROC = os.path.join(_ONPREM, "preprocessor")
_MERGED = os.path.join(_PREPROC, "final_preprocessor.py")
_BUILDER = os.path.join(_PREPROC, "build_final_preprocessor.py")

# 실물 hwpx. 저장소에 커밋되지 않은 것이 섞여 있어 **있는 것만** 태운다.
# 2026-08-31: 기술협상서 2벌이 루트 → `data/` 로 옮겨졌다. 옛 경로를 그대로 두면
# `os.path.exists` 필터가 그 둘을 **조용히 빼고** 통과한다 — 실물 대조가 5벌에서
# 3벌로 줄어든 사실이 어디에도 안 드러난다.
_SAMPLES = [
    os.path.join(_ROOT, "data", "20260616_기술협상서_신복위 검토_V113_제논 의견.hwpx"),
    os.path.join(_ROOT, "data", "20260616_통합AI플랫폼구축사업_기술협상서_최종.hwpx"),
    os.path.join(_ROOT, "data", "파워.hwpx"),
    os.path.join(_ROOT, "data", "FAQ_결과.hwpx"),
    os.path.join(_ROOT, "data", "FAQ_템플릿.hwpx"),
]


class Report:
    def __init__(self) -> None:
        self.failures: list = []
        self.checks = 0

    def expect(self, condition: bool, label: str, detail: str = "") -> None:
        self.checks += 1
        if condition:
            print(f"[OK  ] {label}")
            return
        self.failures.append(label)
        print(f"[FAIL] {label}  {detail}")


def _load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _existing_samples() -> list:
    return [path for path in _SAMPLES if os.path.exists(path)]


# ---------------------------------------------------------------------------
# 벤더 대역 — **라우터 밖에서 꽂는다.** 배포 단위 안에 테스트용 분기를 만들지 않는다.
# ---------------------------------------------------------------------------


class _FakeVendor:
    label = "vendor"

    def __init__(self, config_path=None) -> None:
        self.config_path = config_path
        self.calls: list = []

    async def __call__(self, request, file_path, **kwargs):
        self.calls.append((file_path, dict(kwargs)))
        return [{"text": f"{self.label} 결과", "file_path": file_path}]


class _FakeAttach(_FakeVendor):
    label = "attach"


def _install_fakes(module):
    saved_flag = module._FP_ATTACH_IMPORT_ERROR
    saved_class = getattr(module, "AttachDocumentProcessor", None)
    module._FP_ATTACH_IMPORT_ERROR = None
    module.AttachDocumentProcessor = _FakeAttach

    def restore():
        module._FP_ATTACH_IMPORT_ERROR = saved_flag
        if saved_class is None:
            if hasattr(module, "AttachDocumentProcessor"):
                delattr(module, "AttachDocumentProcessor")
        else:
            module.AttachDocumentProcessor = saved_class

    return restore


# ---------------------------------------------------------------------------
# 1) 생성물이 원본 넷과 맞는가
# ---------------------------------------------------------------------------


def _check_generated_is_current(rep) -> None:
    builder = _load(_BUILDER, "_fp_builder")
    with open(_MERGED, "r", encoding="utf-8") as fh:
        on_disk = fh.read()

    # 순서가 `main()` 과 같아야 한다 — future 제거 → **선택 의존 가드** → 개명 → 표식.
    # 가드를 빼먹으면 이 판정이 "생성물이 낡았다" 고 말하는데 실제로는 점검이 낡은 것이다.
    attach = builder._rename_verified(
        builder._guard_optional_imports(
            builder._strip_future(builder._read(builder._ATTACH_SRC), "attach"),
            builder._ATTACH_OPTIONAL_IMPORTS,
            "attach",
        ),
        builder._ATTACH_RENAME,
        "attach",
    )
    attach = builder._annotate_renames(attach, builder._ATTACH_RENAME)
    rep.expect(
        builder._indent(attach.lstrip("\n")).rstrip("\n") in on_disk,
        "생성물의 첨부용 절반이 원본(개명 후)과 같다",
        "build_final_preprocessor.py 를 다시 돌릴 것",
    )

    rep.expect(
        not os.path.exists(os.path.join(_ROOT, "genos_files", "intelligence_processor.py"))
        or "IntelligentDocumentProcessor" not in on_disk,
        "지능형 절반이 생성물에 남아 있지 않다",
        "참조 사본은 남아 있어도 되지만 병합되면 안 된다",
    )

    hwpx = builder._rename_verified(
        builder._strip_future(builder._read(builder._HWPX_SRC), "hwpx"),
        builder._HWPX_RENAME,
        "hwpx",
    )
    rep.expect(hwpx.strip() in on_disk, "생성물의 hwpx 절반이 원본과 같다")

    lines = builder._strip_future(
        builder._read(builder._ROUTER_SRC), "router"
    ).splitlines(keepends=True)
    index = [i for i, line in enumerate(lines) if line.strip() == "# ROUTER-BODY-BEGIN"][0]
    rep.expect(
        "".join(lines[index + 1 :]).strip() in on_disk, "생성물의 라우터가 원본과 같다"
    )


def _check_optional_import_guard(rep) -> None:
    """사이트 설치본에 없는 벤더 모듈의 import 가 attach 절반을 죽이지 않는가.

    **실환경에서 실제로 밟은 결함이다** — `genon.preprocessor.facade.enrichment.
    page_description` 이 없는 설치본에서 PART 1 이 통째로 가드에 걸려 라우터가 **hwpx
    아닌 전 형식을 거부했다.** hwpx 는 가드 밖이라 그대로 돌아 "pdf 만 안 되는" 얼굴로
    나타난다.

    런타임으로는 볼 수 없다(이 환경엔 docling 이 없어 attach 절반이 아예 안 뜬다).
    그래서 **생성된 소스**와 **스텁 자체**를 본다.
    """
    builder = _load(_BUILDER, "_fp_builder")
    with open(_MERGED, "r", encoding="utf-8") as fh:
        on_disk = fh.read()

    # **기대값을 빌더에서 가져오지 않는다.** `_ATTACH_OPTIONAL_IMPORTS` 를 비우면 순회가
    # 0바퀴여서 판정이 조용히 사라진다 — 그때가 정확히 이 결함이 돌아오는 상태다.
    # 사이트 패키지가 이 모듈을 갖게 된 것을 확인해서 가드를 뗄 때는 여기도 같이 지운다.
    for module in ("genon.preprocessor.facade.enrichment.page_description",):
        matched = [s for s in builder._ATTACH_OPTIONAL_IMPORTS if s["module"] == module]
        rep.expect(
            len(matched) == 1,
            f"가드 명세가 `{module.rsplit('.', 1)[-1]}` 을 덮는다",
            "명세에서 빠졌다 — 빼려면 사이트 설치본에 그 모듈이 있음을 먼저 확인할 것",
        )
        if not matched:
            continue
        spec = matched[0]

        guards = [
            node
            for node in ast.walk(ast.parse(on_disk))
            if builder._guard_module(node) == module
        ]
        rep.expect(
            len(guards) == 1,
            f"선택 의존 가드가 생성물에 살아 있다({module.rsplit('.', 1)[-1]})",
            f"가드 {len(guards)}개 — build_final_preprocessor.py 를 다시 돌릴 것",
        )

        # 스텁을 따로 태운다. import 가 실패하는 설치본에서 실제로 실행되는 코드다.
        namespace: dict = {}
        exec(compile(spec["stub"], "<stub>", "exec"), namespace)  # noqa: S102
        options = namespace["PageDescriptionOptions"].from_config({}, "/tmp")
        rep.expect(
            options.enabled is False,
            "스텁 옵션은 꺼진 상태다(설명만 빠지고 파싱은 그대로다)",
        )
        rep.expect(
            namespace["describe_pages"](None, options, page_texts={1: "본문"}) == {},
            "스텁 `describe_pages` 는 빈 dict 를 준다(호출부가 native text 로 넘어간다)",
        )

        # **이 판정이 제일 값어치 있다.** GenOS 가 참조 사본을 갱신하며 호출부가 새
        # 속성을 읽으면 스텁은 그때 `AttributeError` 로 죽는데, 그 자리가 PPT 경로라
        # 여기서 안 보면 **PPT 를 올려 볼 때까지 아무도 모른다.**
        used = set(re.findall(r"_page_desc_options\.([A-Za-z_][A-Za-z0-9_]*)",
                              builder._read(builder._ATTACH_SRC)))
        missing = sorted(name for name in used if not hasattr(options, name))
        rep.expect(
            not missing,
            "스텁이 벤더 호출부가 읽는 속성을 전부 갖는다",
            f"빠진 것: {missing} — `_PAGE_DESCRIPTION_STUB` 에 더할 것",
        )


# ---------------------------------------------------------------------------
# 2) 개명 결과가 실제로 살아 있는가
# ---------------------------------------------------------------------------


def _check_overlap_handling(rep) -> None:
    """개명 결과를 **생성된 소스에서** 본다.

    런타임 속성으로 보면 안 된다 — 이 점검이 도는 환경에는 docling 스택이 없어 벤더 두
    절반이 아예 적재되지 않으므로, `hasattr` 은 개명이 맞든 틀리든 똑같이 False 다.
    그러면 판정이 **언제나 실패**하거나(지금 상태) 조건을 느슨하게 하면 **언제나 통과**한다.
    소스를 파싱하면 벤더 스택 없이도 정확히 볼 수 있다.
    """
    builder = sys.modules["_fp_builder"]
    with open(_MERGED, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    # **최상위만** 센다. `ast.walk` 로 훑으면 함수 안 지역 변수까지 세어 "겹쳤다" 는
    # 판정이 엉뚱한 이유로 깨진다.
    defined: dict = {}

    def collect(body: list) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.setdefault(node.name, []).append(node)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        defined.setdefault(target.id, []).append(node)
            elif isinstance(node, (ast.Try, ast.If)):
                collect(node.body)
                collect(node.orelse)
                collect(getattr(node, "finalbody", []))
                for handler in getattr(node, "handlers", []):
                    collect(handler.body)

    collect(tree.body)

    for name in ("AttachDocumentProcessor", "HwpxDocumentProcessor", "DocumentProcessor"):
        rep.expect(name in defined, f"처리기가 자기 이름으로 있다: {name}")

    # **진입점은 라우터 것이어야 한다.** 첨부용·hwpx 것이 그 이름으로 남으면 GenOS 가
    # 그쪽을 실행해 라우팅이 통째로 사라지는데, 적재는 성공으로 보인다.
    entry = defined.get("DocumentProcessor", [])
    rep.expect(
        len(entry) == 1 and isinstance(entry[0], ast.ClassDef)
        and any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_run_vendor"
            for node in entry[0].body
        ),
        "`DocumentProcessor` 는 라우터 것 하나뿐이다",
        f"정의 {len(entry)}개",
    )

    # 지능형이 빠진 뒤 첨부용은 자기 정의를 전부 들고 있어야 한다. 그 시절 지운 13개
    # 중 하나라도 안 돌아왔으면 **첨부용이 등록 즉시 `NameError`** 로 죽는다.
    for name in ("_detect_unsupported_file", "_resolve_tokenizer", "_parse_optional_int",
                 "_DEFAULT_TOKENIZER_ID", "upload_files"):
        rep.expect(name in defined, f"첨부용이 자기 정의를 들고 있다: {name}")

    # 지능형과 겹쳐 개명했던 것들 — 이제 겹칠 상대가 없으므로 **원래 이름**이어야 한다.
    # 개명본이 남아 있으면 첨부용 안에서 이름이 갈려 호출부가 죽는다.
    for name in ("GenOSVectorMeta", "GenosServiceException", "_load_config", "convert_to_pdf"):
        rep.expect(name in defined, f"지능형과 겹칠 일이 없어져 원래 이름으로 돌아왔다: {name}")
    for name in ("ATGenOSVectorMeta", "_at_load_config", "at_convert_to_pdf"):
        rep.expect(name not in defined, f"옛 개명본이 남아 있지 않다: {name}")

    # `_log` 만은 양쪽에 남는다 — 둘 다 `logging.getLogger(__name__)` 이고 한 모듈이라
    # `__name__` 이 같아 결국 같은 객체다.
    rep.expect(len(defined.get("_log", [])) == 2, "`_log` 는 양쪽에 있어도 같은 객체다")

    # `Document` — hwpx 데이터클래스가 langchain 것을 덮으면 첨부용 20개 호출부가
    # **호출 시점에** 터진다(import 는 통과한다).
    rep.expect("HwpxDocument" in defined, "hwpx 의 Document 가 HwpxDocument 로 비켜 있다")
    rep.expect(
        "Document" not in defined,
        "최상위에 `Document` 를 정의하지 않는다 (첨부용의 langchain import 를 덮는다)",
    )

    # 표식 주석 — 생성물만 보고도 "여기 원래 뭐가 있었나" 를 알 수 있어야 한다.
    with open(_MERGED, "r", encoding="utf-8") as fh:
        text = fh.read()
    rep.expect(
        text.count("# [병합 개명]") == len(builder._ATTACH_RENAME),
        "개명한 자리마다 표식 주석이 있다",
        f"{text.count('# [병합 개명]')} != {len(builder._ATTACH_RENAME)}",
    )
    rep.expect(
        "# [병합 제거]" not in text,
        "지운 정의가 없으므로 제거 표식도 없다 (지능형이 빠지며 전부 되돌아왔다)",
    )


# ---------------------------------------------------------------------------
# 3) 라우팅
# ---------------------------------------------------------------------------


def _check_routing(module, rep, tmpdir) -> None:
    route = module._fp_route
    HWPX, ATTACH = module._FP_HWPX, module._FP_ATTACH

    rep.expect(
        not hasattr(module, "_FP_INTELLIGENT"),
        "지능형 엔진 상수가 남아 있지 않다",
    )
    rep.expect(
        set(module._FP_ENGINES) == {HWPX, ATTACH},
        "엔진은 둘뿐이다",
        str(module._FP_ENGINES),
    )

    # 지능형이 받던 형식 — 이제 전부 첨부용이다. pdf 는 `PyMuPDFLoader` 평문이라 표
    # 격자가 남지 않지만, **적재가 통째로 안 되는 것보다는 낫다**는 판단이다.
    for name, label in (("보고서.pdf", "pdf"), ("발표.pptx", "pptx"), ("표.xlsx", "xlsx"),
                        ("사진.png", "png"), ("구형.doc", "doc")):
        rep.expect(route(f"/x/{name}", "auto", {})[0] == ATTACH, f"{label} -> 첨부용")

    # 원래부터 첨부용이던 형식 — 네이티브 백엔드라 PDF 변환을 거치지 않는다.
    for name, label in (("계약.docx", "docx"), ("구버전.hwp", "hwp"), ("옛.hml", "hml"),
                        ("녹취.mp3", "mp3"), ("메모.txt", "txt"), ("설명.md", "md")):
        rep.expect(route(f"/x/{name}", "auto", {})[0] == ATTACH, f"{label} -> 첨부용")

    rep.expect(route("/x/모르는.zzz", "auto", {})[0] == ATTACH, "모르는 확장자 -> 기본(첨부용)")
    rep.expect(
        route("/x/문서.hwpx", "auto", {".hwpx": ATTACH}) == (ATTACH, "override"),
        "route_overrides 가 확장자 라우팅을 덮는다",
    )
    rep.expect(
        module._fp_overrides_kwarg('{"pdf": "intelligent"}') == {},
        "route_overrides 로도 지능형을 되살릴 수 없다(엔진 목록에 없다)",
    )

    real = _existing_samples()
    if real:
        rep.expect(route(real[0], "auto", {})[0] == HWPX, "실물 hwpx -> hwpx 파서")
        rep.expect(route(real[0], "attach", {})[0] == ATTACH, "hwpx_engine=attach")
        rep.expect(
            route(real[0], "intelligent", {})[0] == HWPX,
            "hwpx_engine=intelligent 는 모르는 값이라 기본(auto)으로 떨어진다",
        )

    # 확장자만 hwpx 인 파일 — 세우지 않고 벤더로 넘긴다. 세우면 그 문서가 검색에서
    # 통째로 사라지고, 넘기면 표가 덜 정확해도 적재는 된다.
    not_zip = os.path.join(tmpdir, "가짜.hwpx")
    with open(not_zip, "wb") as fh:
        fh.write(b"%PDF-1.7\n")
    rep.expect(route(not_zip, "auto", {}) == (ATTACH, "not_a_zip"), "내용이 hwpx 가 아니면 첨부용")
    rep.expect(
        route(not_zip, "native", {})[0] == HWPX,
        "hwpx_engine=native 면 어긋남을 폴백에 묻지 않는다",
    )

    other_zip = os.path.join(tmpdir, "docx인척.hwpx")
    with zipfile.ZipFile(other_zip, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    rep.expect(
        route(other_zip, "auto", {}) == (ATTACH, "zip_without_hwpx_contents"),
        "zip 이지만 hwpx 가 아니면 첨부용",
    )

    by_section = os.path.join(tmpdir, "섹션만.hwpx")
    with zipfile.ZipFile(by_section, "w") as archive:
        archive.writestr("Contents/section0.xml", "<x/>")
    rep.expect(
        route(by_section, "auto", {}) == (HWPX, "section_xml"),
        "mimetype 이 없어도 section 으로 판정",
    )
    rep.expect(
        route(os.path.join(tmpdir, "없는파일.hwpx"), "auto", {}) == (ATTACH, "read_failed"),
        "읽을 수 없는 파일도 세우지 않는다",
    )


def _check_kwargs(module, rep) -> None:
    choice = module._fp_choice_kwarg
    engines = module._FP_HWPX_ENGINES
    rep.expect(choice("", "auto", engines, "hwpx_engine") == "auto", "빈 문자열 주입 -> 기본값")
    rep.expect(choice(None, "auto", engines, "hwpx_engine") == "auto", "None -> 기본값")
    rep.expect(choice(" NATIVE ", "auto", engines, "hwpx_engine") == "native", "공백·대문자 허용")
    rep.expect(choice("얼렁뚱땅", "auto", engines, "hwpx_engine") == "auto", "모르는 값 -> 기본값")

    boolean = module._fp_bool_kwarg
    rep.expect(boolean("", True, "align") is True, "bool: 빈 문자열 -> 기본값")
    rep.expect(boolean("false", True, "align") is False, "bool: 문자열 false")
    rep.expect(boolean(False, True, "align") is False, "bool: 진짜 False")
    rep.expect(boolean("아무거나", True, "align") is True, "bool: 모르는 값 -> 기본값")

    overrides = module._fp_overrides_kwarg
    rep.expect(overrides('{"pdf": "attach"}') == {".pdf": "attach"}, "overrides: JSON 문자열·점 보정")
    rep.expect(overrides({".pdf": "ATTACH"}) == {".pdf": "attach"}, "overrides: dict·대문자")
    rep.expect(overrides('{"pdf": "없는엔진"}') == {}, "overrides: 모르는 엔진은 버린다")
    rep.expect(overrides("망가진 JSON") == {}, "overrides: 형식 오류로 재적재를 막지 않는다")
    rep.expect(overrides("") == {}, "overrides: 빈 값")

    rep.expect(
        module._fp_forward_kwargs(
            {"hwpx_engine": "auto", "align_vector_schema": True, "route_overrides": {},
             "attachment_config_path": "/y", "chunk_size": 800}
        )
        == {"chunk_size": 800},
        "라우터 몫의 kwargs 는 하위 처리기로 넘기지 않는다",
    )


# ---------------------------------------------------------------------------
# 4) hwpx 경로 — 단독 전처리기와 같은 결과여야 한다
# ---------------------------------------------------------------------------


def _check_hwpx_path(module, standalone, rep) -> None:
    processor = module.DocumentProcessor()
    samples = _existing_samples()
    for sample in samples:
        name = os.path.basename(sample)
        got = asyncio.run(processor(None, sample))
        want = asyncio.run(standalone.DocumentProcessor()(None, sample))
        rep.expect(
            [record["text"] for record in got] == [record["text"] for record in want],
            f"{name}: 본문이 단독 hwpx 전처리기와 같다 ({len(got)} 청크)",
        )
        rep.expect(
            all(
                got[0][key] == want[0][key]
                for key in want[0]
                # `reg_date` 는 적재 시각이라 호출마다 다르다.
                if key in got[0] and key != "reg_date"
            ),
            f"{name}: 스키마 정렬이 기존 값을 덮지 않는다",
        )
        rep.expect(
            all(key in got[0] for key in module._FP_SCHEMA_DEFAULTS),
            f"{name}: 벤더 예약 필드가 채워졌다(한 컬렉션 안 메타 스키마)",
        )

    if samples:
        off = asyncio.run(processor(None, samples[0], align_vector_schema=False))
        rep.expect("title" not in off[0], "align_vector_schema=false 면 정렬하지 않는다")
        smaller = asyncio.run(processor(None, samples[0], chunk_size=500))
        base = asyncio.run(processor(None, samples[0]))
        rep.expect(
            len(smaller) > len(base),
            "hwpx 쪽 kwargs(chunk_size)가 그대로 전달된다",
            f"{len(base)} -> {len(smaller)}",
        )


# ---------------------------------------------------------------------------
# 5) 벤더가 없을 때 / 있을 때
# ---------------------------------------------------------------------------


def _check_vendor_absent(module, rep, tmpdir) -> None:
    processor = module.DocumentProcessor()
    pdfish = os.path.join(tmpdir, "문서.pdf")
    with open(pdfish, "wb") as fh:
        fh.write(b"%PDF-1.7\n")
    try:
        asyncio.run(processor(None, pdfish))
        rep.expect(False, "벤더 부재: 비-hwpx 는 예외", "예외가 나지 않았다")
    except module.FinalPreprocessorError as exc:
        rep.expect(
            "attach" in str(exc) and type(exc).__name__ != "NameError",
            "벤더 부재: 어느 엔진인지·왜인지를 담아 예외를 던진다",
            str(exc)[:90],
        )
    except Exception as exc:  # noqa: BLE001
        rep.expect(False, "벤더 부재: 비-hwpx 는 예외", f"{type(exc).__name__}: {exc}")

    broken = os.path.join(tmpdir, "깨진.hwpx")
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
    try:
        asyncio.run(processor(None, broken))
        rep.expect(False, "벤더 부재: hwpx 실패를 폴백으로 감추지 않는다", "예외가 나지 않았다")
    except module.HwpxParseError:
        rep.expect(True, "벤더 부재: hwpx 실패를 폴백으로 감추지 않는다")


def _check_vendor_present(module, rep, tmpdir) -> None:
    restore = _install_fakes(module)
    try:
        processor = module.DocumentProcessor()
        rep.expect(processor._vendor == {}, "벤더는 생성자에서 만들지 않는다(지연 생성)")

        pdfish = os.path.join(tmpdir, "문서.pdf")
        with open(pdfish, "wb") as fh:
            fh.write(b"%PDF-1.7\n")
        records = asyncio.run(processor(None, pdfish, chunk_size=700, hwpx_engine="auto"))
        rep.expect(records[0]["text"] == "attach 결과", "pdf 는 첨부용이 처리한다")
        called_path, called_kwargs = processor._vendor["attach"].calls[0]
        rep.expect(called_kwargs == {"chunk_size": 700}, "벤더에 라우터 kwargs 가 새지 않는다",
                   str(called_kwargs))

        docx = os.path.join(tmpdir, "계약.docx")
        with zipfile.ZipFile(docx, "w") as archive:
            archive.writestr("word/document.xml", "<w:document/>")
        records = asyncio.run(processor(None, docx))
        rep.expect(records[0]["text"] == "attach 결과", "docx 는 첨부용이 처리한다")
        rep.expect(set(processor._vendor) == {"attach"}, "벤더는 첨부용 하나뿐이다")

        asyncio.run(processor(None, pdfish))
        rep.expect(len(processor._vendor["attach"].calls) == 3, "두 번째 호출은 만들어 둔 것을 쓴다")

        # hwpx 파싱 실패 -> 폴백은 **첨부용**이다(GenosHwp SDK 네이티브라 덜 잃는다).
        broken = os.path.join(tmpdir, "깨진2.hwpx")
        with zipfile.ZipFile(broken, "w") as archive:
            archive.writestr("mimetype", "application/hwp+zip")
        try:
            fell_back = asyncio.run(processor(None, broken))
            rep.expect(fell_back[0]["text"] == "attach 결과", "hwpx 파싱 실패 -> 첨부용으로 폴백")
        except Exception as exc:  # noqa: BLE001
            rep.expect(False, "hwpx 파싱 실패 -> 첨부용으로 폴백", f"{type(exc).__name__}: {exc}")

        try:
            asyncio.run(processor(None, broken, hwpx_engine="native"))
            rep.expect(False, "hwpx_engine=native 면 폴백하지 않는다", "예외가 나지 않았다")
        except module.HwpxParseError:
            rep.expect(True, "hwpx_engine=native 면 폴백하지 않는다")

        real = _existing_samples()
        if real:
            forced = asyncio.run(processor(None, real[0], hwpx_engine="attach"))
            rep.expect(forced[0]["text"] == "attach 결과", "hwpx_engine=attach 는 hwpx 도 첨부용으로")

        # route_overrides 가 실제 호출까지 이어지는가
        records = asyncio.run(processor(None, pdfish, route_overrides={".pdf": "attach"}))
        rep.expect(records[0]["text"] == "attach 결과", "route_overrides 가 실제 호출을 바꾼다")
    finally:
        restore()


def _check_attach_stands_alone(module, rep, tmpdir) -> None:
    """첨부용이 **혼자** 서는가.

    지능형이 있던 시절 첨부용은 본문이 같아 지운 정의 13개를 지능형 판본에서 빌려
    썼고, 그래서 지능형 절반이 없으면 첨부용도 `NameError` 로 죽었다(그 사실을 갈라
    보고하는 판정이 여기 있었다). 지능형을 걷어내며 그 13개를 되돌렸으므로 **이제는
    첨부용 적재만 성공하면 도는 것이 계약**이다.

    이 점검이 도는 환경에는 docling 이 없어 첨부용이 실제로는 적재되지 않는다. 그래서
    **적재 성공 상태를 대역으로 만들어** 그때 라우터가 다른 이유로 세우지 않는지 본다.
    """
    restore = _install_fakes(module)
    try:
        rep.expect(
            module._fp_engine_error(module._FP_ATTACH) is None,
            "첨부용 가부는 첨부용 적재 결과 하나로 정해진다(다른 절반에 얽히지 않는다)",
        )
        processor = module.DocumentProcessor()
        docx = os.path.join(tmpdir, "계약2.docx")
        with open(docx, "wb") as fh:
            fh.write(b"PK\x03\x04")
        try:
            records = asyncio.run(processor(None, docx))
            rep.expect(records[0]["text"] == "attach 결과", "첨부용만 적재돼도 그 경로가 돈다")
        except Exception as exc:  # noqa: BLE001
            rep.expect(False, "첨부용만 적재돼도 그 경로가 돈다", f"{type(exc).__name__}: {exc}")
    finally:
        restore()


# ---------------------------------------------------------------------------
# 조문 위계를 벤더 경로(pdf·docx)에도 태우는 층
#
# **docling 도 langchain 도 없는 환경에서 이 층을 검사할 수 있어야 한다.** 어댑터가
# 보는 것은 docling 쪽은 `iterate_items()`·`item.text`·`item.data.table_cells`·
# `item.prov`, langchain 쪽은 `page_content`·`metadata` 뿐이라 그 모양만 갖춘 대역이면
# 된다 — 실물을 요구하면 이 층을 보는 점검이 **0건이 된다.**
#
# **원본 모양이 둘**이라 어댑터도 둘이다(2026-09-01). 지능형이 빠지며 pdf 가 첨부용
# 최상위 경로로 갔고 그쪽은 langchain `Document` 목록을 주고받는다. 가운데(위계 판정·
# 조 경계 청킹)는 하나이므로 **입구와 출구만 각각** 태운다.
#
# 되돌려 FAIL 을 본 갈래: 위계 미적용(벤더 청커 그대로) · 조 경계 미분리 · 출처 유실
# (`doc_items` 빈 목록 → `compose_vectors` 가 IndexError) · 글자 없는 항목 버리기 ·
# `headings` 채우기(제목 두 번) · 표 HTML 대신 원문 · **페이지를 구역으로 쓰기**(조가
# 반으로 갈린다) · **metadata 공유**(뒤 청크가 앞 청크의 페이지를 바꾼다).
# ---------------------------------------------------------------------------


class _FakeProv:
    def __init__(self, page_no: int) -> None:
        self.page_no = page_no


class _FakeText:
    """docling `TextItem`/`ListItem` 대역."""

    def __init__(self, text: str, page: int = 1) -> None:
        self.text = text
        self.prov = [_FakeProv(page)] if page else []


class _FakePicture:
    """글자가 없는 항목(그림). **버려지면 이미지 업로드가 통째로 빠진다.**"""

    text = None

    def __init__(self, page: int = 1) -> None:
        self.prov = [_FakeProv(page)]


class _FakeCell:
    def __init__(self, text, row, col, row_span=1, col_span=1, header=False) -> None:
        self.text = text
        self.start_row_offset_idx = row
        self.end_row_offset_idx = row + row_span
        self.start_col_offset_idx = col
        self.end_col_offset_idx = col + col_span
        self.column_header = header


class _FakeTable:
    def __init__(self, cells, page: int = 1) -> None:
        self.data = type("_Data", (), {"table_cells": cells})()
        self.prov = [_FakeProv(page)]


class _FakeDoclingDoc:
    def __init__(self, items) -> None:
        self._items = list(items)
        self.origin = "ORIGIN"

    def iterate_items(self):
        return [(item, 0) for item in self._items]

    def num_pages(self) -> int:
        return 1


class _FakeSplitOwner:
    """벤더 처리기 대역 — `split_documents` 만 있으면 된다."""

    def __init__(self) -> None:
        self.vendor_calls = 0
        self.page_chunk_counts = {}

    def split_documents(self, document, **kwargs):
        self.vendor_calls += 1
        return ["VENDOR"]


class _FakeDocMeta:
    def __init__(self, doc_items, origin=None, headings=None) -> None:
        self.doc_items = doc_items
        self.origin = origin
        self.headings = headings


class _FakeDocChunk:
    def __init__(self, text, meta) -> None:
        self.text = text
        self.meta = meta


_STATUTE_ITEMS = (
    "제2장 총칙",
    "제4조(적용 범위) 이 규정은 회사의 모든 임직원에게 적용한다.",
    "① 임직원은 이 규정을 준수하여야 한다.",
    "제5조(목적) 이 규정은 업무 처리의 기준을 정함을 목적으로 한다.",
    "② 세부 사항은 따로 정한다.",
)


def _statute_doc():
    items = [_FakeText(text) for text in _STATUTE_ITEMS]
    items.insert(3, _FakePicture())  # 조문 사이에 낀 그림
    return _FakeDoclingDoc(items)


def _plain_doc():
    return _FakeDoclingDoc(
        [_FakeText("1. 사업 개요"), _FakeText("가. 본 사업은 통합 플랫폼을 구축한다.")]
    )


class _FakeLangchainDoc:
    """langchain `Document` 대역 — 첨부용 최상위 경로(pdf)가 주고받는 모양.

    조립기가 **클래스를 이름으로 찾지 않고 `type(원본)` 으로 만드는지**를 이 대역이
    확인한다. 이름으로 찾으면 벤더 가드 밖인 라우터에서 그 전역이 없을 수 있다.
    """

    def __init__(self, page_content: str, metadata: dict) -> None:
        self.page_content = page_content
        self.metadata = metadata


def _statute_pages():
    """조가 **페이지를 걸치는** pdf 대역. 페이지를 구역으로 쓰면 여기서 갈린다."""
    return [
        _FakeLangchainDoc(
            "제2장 총칙\n제4조(적용 범위) 이 규정은 회사의 모든 임직원에게 적용한다.\n"
            "① 임직원은 이 규정을 준수하여야 한다.",
            {"source": "/x/규정.pdf", "page": 0},
        ),
        # 글자 없는 페이지 — 버리면 페이지 집계가 어긋난다.
        _FakeLangchainDoc("   \n\n", {"source": "/x/규정.pdf", "page": 1}),
        _FakeLangchainDoc(
            "② 세부 사항은 따로 정한다.\n"
            "제5조(목적) 이 규정은 업무 처리의 기준을 정함을 목적으로 한다.",
            {"source": "/x/규정.pdf", "page": 2},
        ),
    ]


def _plain_pages():
    return [
        _FakeLangchainDoc("1. 사업 개요\n가. 본 사업은 통합 플랫폼을 구축한다.",
                          {"source": "/x/보고서.pdf", "page": 0}),
    ]


def _install_docchunk(module):
    saved = {name: getattr(module, name, None) for name in ("DocChunk", "DocMeta")}
    module.DocChunk = _FakeDocChunk
    module.DocMeta = _FakeDocMeta

    def restore():
        for name, value in saved.items():
            if value is None:
                if hasattr(module, name):
                    delattr(module, name)
            else:
                setattr(module, name, value)

    return restore


def _check_outline_bridge(module, rep) -> None:
    # --- 어댑터: DoclingDocument -> Block -------------------------------------
    blocks = module._fp_docling_blocks(_statute_doc())
    rep.expect(
        [block.text for block in blocks] == list(_STATUTE_ITEMS),
        "어댑터: 문단 텍스트를 순서대로 옮긴다",
        f"{[b.text for b in blocks]}",
    )
    rep.expect(
        all(block.section == 0 for block in blocks),
        "어댑터: 구역은 전부 0 이다(페이지로 끊으면 조가 반으로 갈린다)",
    )
    rep.expect(
        all(block.origin for block in blocks),
        "어댑터: 모든 블록이 출처를 든다",
    )
    picture_carried = any(
        any(isinstance(item, _FakePicture) for item in block.origin) for block in blocks
    )
    rep.expect(picture_carried, "어댑터: 글자 없는 항목도 어느 블록엔가 실린다")

    # --- 표 -------------------------------------------------------------------
    table = _FakeTable(
        [
            _FakeCell("구분", 0, 0, header=True),
            _FakeCell("2025년 실적", 0, 1, col_span=2, header=True),
            _FakeCell("상반기", 1, 1),
            _FakeCell("하반기", 1, 2),
            _FakeCell("합계", 1, 0, row_span=2),
            _FakeCell("100", 2, 1),
            _FakeCell("2 < 3", 2, 2),
        ]
    )
    html = module._fp_table_html(table)
    rep.expect(html.startswith("<table><tbody>"), "표: 한 줄 HTML 로 낸다", html[:60])
    rep.expect('colspan="2"' in html and 'rowspan="2"' in html, "표: 병합을 살린다", html)
    # 덮인 자리에 칸을 내면 **그 행만 열이 하나 늘어난다** — 행 수는 그대로라 `<tr>`
    # 개수로는 안 잡힌다. 행별 칸 수를 직접 센다(앵커 7개가 그대로 칸 7개여야 한다).
    rows = [row for row in html.split("<tr>")[1:]]
    per_row = [row.count("<td") + row.count("<th") for row in rows]
    rep.expect(per_row == [2, 3, 2], "표: 덮인 자리에 칸을 내지 않는다", f"{per_row} {html}")
    rep.expect("<th" in html and html.count("<th") == 2, "표: 머리행을 `<th>` 로 낸다", html)
    rep.expect("2 &lt; 3" in html, "표: 셀 내용을 이스케이프한다", html)
    rep.expect("\n" not in html, "표: 개행이 없다(조립 단계 평탄화를 견딘다)")

    # --- 판정: 언제 우리 청커가 도는가 ----------------------------------------
    rep.expect(
        module._fp_outline_chunks(_plain_doc(), {}) is None,
        "일반 문서는 벤더 청커 그대로다(auto 는 `제N조` 를 세어 본다)",
    )
    rep.expect(
        module._fp_outline_chunks(_statute_doc(), {"outline_mode": "off"}) is None,
        "`outline_mode=off` 면 벤더 청커 그대로다",
    )
    chunks = module._fp_outline_chunks(_statute_doc(), {})
    rep.expect(bool(chunks), "조문 문서는 위계 청커가 받는다")

    if chunks:
        texts = [chunk.text for chunk in chunks]
        rep.expect(
            not any("제4조" in text and "제5조" in text for text in texts),
            "조 경계에서 끊는다(두 조가 한 청크에 섞이지 않는다)",
            f"{texts}",
        )
        rep.expect(
            any("제2장 총칙" in text and "제5조(목적)" in text for text in texts),
            "청크 본문에 조문 줄기 머리말이 붙는다",
            f"{texts}",
        )
        body = "\n".join(texts)
        rep.expect(
            all(item in body for item in _STATUTE_ITEMS),
            "무손실: 모든 문단이 어느 청크엔가 남는다",
        )
        rep.expect(
            all(chunk.origin for chunk in chunks),
            "모든 청크가 출처를 든다(비면 compose_vectors 가 IndexError 로 죽는다)",
        )
        carried = [item for chunk in chunks for item in chunk.origin]
        rep.expect(
            any(isinstance(item, _FakePicture) for item in carried),
            "글자 없는 항목이 청크까지 따라온다(이미지 업로드가 빠지지 않는다)",
        )

    # --- 벤더가 받는 모양 ------------------------------------------------------
    payload = module._fp_recursive_payload(chunks or [])
    rep.expect(
        all(set(entry) == {"text", "page_no", "doc_items"} for entry in payload),
        "첨부용 recursive: `{text, page_no, doc_items}` 모양이다",
        f"{[sorted(e) for e in payload][:1]}",
    )
    rep.expect(
        all(entry["doc_items"] for entry in payload),
        "첨부용 recursive: `doc_items` 가 비지 않는다",
    )
    rep.expect(
        all(entry["page_no"] == 1 for entry in payload),
        "페이지는 첫 항목의 `prov` 에서 온다(벤더 compose 와 같은 식)",
    )

    restore_chunk = _install_docchunk(module)
    try:
        doc_chunks = module._fp_docchunk_payload(chunks or [], _statute_doc())
        rep.expect(bool(doc_chunks), "지능형: DocChunk 를 만든다")
        rep.expect(
            all(chunk.meta.doc_items for chunk in doc_chunks or []),
            "지능형: `meta.doc_items` 가 비지 않는다",
        )
        rep.expect(
            all(not chunk.meta.headings for chunk in doc_chunks or []),
            "지능형: `headings` 를 채우지 않는다(본문에 이미 머리말이 있다 — 두 번 실린다)",
        )
    finally:
        restore_chunk()

    rep.expect(
        module._fp_docchunk_payload(chunks or [], _statute_doc()) is None,
        "docling 이 없으면 DocChunk 를 지어내지 않는다(벤더 청커로 돌아간다)",
    )

    # --- 설치 ------------------------------------------------------------------
    owner = _FakeSplitOwner()
    module._fp_install_outline_chunker(
        owner, "docx", reset_page_counts=True, honor_chunker_type=True
    )
    result = owner.split_documents(_statute_doc())
    rep.expect(
        owner.vendor_calls == 0 and isinstance(result[0], dict),
        "설치: 조문 문서에서 벤더 청커를 부르지 않는다",
        f"{owner.vendor_calls} {result[:1]}",
    )
    rep.expect(
        owner.page_chunk_counts[1] == len(result) and owner.page_chunk_counts[99] == 0,
        "설치: 페이지별 청크 수를 채우고, 없는 키에서 죽지 않는다",
        f"{dict(owner.page_chunk_counts)}",
    )
    owner.split_documents(_plain_doc())
    rep.expect(owner.vendor_calls == 1, "설치: 일반 문서는 벤더 청커로 넘긴다")

    owner.split_documents(_statute_doc(), chunker_type="hybrid")
    rep.expect(
        owner.vendor_calls == 2,
        "설치: hybrid 인데 docling 이 없으면 벤더 청커로 돌아간다(모양을 어기지 않는다)",
    )

    intel_owner = _FakeSplitOwner()
    module._fp_install_outline_chunker(
        intel_owner, "pdf", reset_page_counts=False, honor_chunker_type=False
    )
    intel_owner.split_documents(_statute_doc())
    rep.expect(
        intel_owner.vendor_calls == 1,
        "설치: 지능형은 언제나 DocChunk 다 — dict 를 내지 않는다",
    )

    twice = _FakeSplitOwner()
    module._fp_install_outline_chunker(
        twice, "docx", reset_page_counts=True, honor_chunker_type=True
    )
    once = twice.split_documents
    module._fp_install_outline_chunker(
        twice, "docx", reset_page_counts=True, honor_chunker_type=True
    )
    rep.expect(twice.split_documents is once, "설치: 두 번 걸어도 한 겹만 감싼다")

    class _NoSplit:
        pass

    bare = _NoSplit()
    module._fp_install_outline_chunker(
        bare, "docx", reset_page_counts=True, honor_chunker_type=True
    )
    rep.expect(
        not hasattr(bare, "split_documents"),
        "설치: `split_documents` 가 없는 처리기여도 적재를 막지 않는다",
    )

    # --- langchain 어댑터 (첨부용 최상위 = pdf) ---------------------------------
    _check_langchain_bridge(module, rep)

    # --- 어디에 거는가 ---------------------------------------------------------
    class _AttachLike(_FakeSplitOwner):
        def __init__(self) -> None:
            super().__init__()
            self.docx_processor = _FakeSplitOwner()
            self.hwp_processor = _FakeSplitOwner()

    attach_like = _AttachLike()
    module._fp_enable_outline(attach_like)
    rep.expect(
        getattr(attach_like, "_fp_outline_installed", False),
        "첨부용: 최상위(pdf 경로)에 건다",
    )
    rep.expect(
        getattr(attach_like.docx_processor, "_fp_outline_installed", False),
        "첨부용: docx 에도 건다",
    )
    rep.expect(
        not getattr(attach_like.hwp_processor, "_fp_outline_installed", False),
        "첨부용: hwp 에는 걸지 않는다(요구 범위가 pdf·docx 다)",
    )
    # 최상위에 건 것이 **langchain 모양**이어야 한다. docling 어댑터를 걸면 pdf 마다
    # `iterate_items` 가 없어 실패한 뒤 벤더 청커로 돌아간다 — 경고만 쌓이고 위계는
    # 영영 안 붙는데, 결과는 정상으로 보인다.
    produced = attach_like.split_documents(_statute_pages())
    rep.expect(
        attach_like.vendor_calls == 0 and hasattr(produced[0], "page_content"),
        "첨부용 최상위는 langchain 어댑터로 건다",
        f"vendor={attach_like.vendor_calls} {type(produced[0]).__name__}",
    )


def _check_langchain_bridge(module, rep) -> None:
    """pdf 경로 — `list[Document]` 를 받아 같은 모양으로 돌려준다."""
    blocks = module._fp_langchain_blocks(_statute_pages())
    rep.expect(
        [block.text for block in blocks][:2] == [
            "제2장 총칙", "제4조(적용 범위) 이 규정은 회사의 모든 임직원에게 적용한다."
        ],
        "langchain 어댑터: 줄 단위로 가른다(조 표기가 줄 머리에 서야 위계가 잡힌다)",
        f"{[b.text for b in blocks][:2]}",
    )
    rep.expect(
        all(block.section == 0 for block in blocks),
        "langchain 어댑터: 구역은 전부 0 이다(페이지로 끊으면 조가 반으로 갈린다)",
    )
    rep.expect(all(block.origin for block in blocks), "langchain 어댑터: 모든 블록이 출처를 든다")
    empty_carried = any(
        any(getattr(item, "metadata", {}).get("page") == 1 for item in block.origin)
        for block in blocks
    )
    rep.expect(empty_carried, "langchain 어댑터: 글자 없는 페이지도 어느 블록엔가 실린다")

    chunks = module._fp_outline_chunks(_statute_pages(), {}, module._FP_SRC_LANGCHAIN)
    rep.expect(bool(chunks), "pdf: 조문 문서는 위계 청커가 받는다")
    rep.expect(
        module._fp_outline_chunks(_plain_pages(), {}, module._FP_SRC_LANGCHAIN) is None,
        "pdf: 일반 문서는 벤더 청커 그대로다",
    )
    if chunks:
        texts = [chunk.text for chunk in chunks]
        rep.expect(
            not any("제4조" in text and "제5조" in text for text in texts),
            "pdf: 조 경계에서 끊는다(두 조가 한 청크에 섞이지 않는다)",
            f"{texts}",
        )
        # 픽스처의 `②` 는 제4조의 항인데 **다음 페이지**에 있다. 페이지를 구역으로 쓰면
        # 여기서 떨어져 나가고, 그러면 그 항만 든 청크가 무엇에 관한 것인지 알 수 없다.
        # **조문 본문으로 본다.** `"제4조" in text` 로는 못 잡는다 — 갈라져 나간 청크에도
        # `제2장 총칙 > 제4조(적용 범위)` 머리말이 붙어 그 낱말이 들어 있다.
        rep.expect(
            any("임직원에게 적용한다." in text and "② 세부 사항" in text for text in texts),
            "pdf: 페이지를 걸친 항도 그 조와 한 청크다",
            f"{texts}",
        )
        rep.expect(
            any("제2장 총칙" in text and "제5조(목적)" in text for text in texts),
            "pdf: 청크 본문에 조문 줄기 머리말이 붙는다",
            f"{texts}",
        )

    payload = module._fp_langchain_payload(chunks or [])
    rep.expect(
        payload is not None and all(isinstance(doc, _FakeLangchainDoc) for doc in payload),
        "pdf: 원본과 **같은 클래스**로 만든다(이름으로 찾지 않는다)",
    )
    rep.expect(
        payload is not None and all(doc.page_content for doc in payload),
        "pdf: 본문이 `page_content` 에 들어간다(벤더가 읽는 자리)",
    )
    # **사본인지는 정체로 본다.** 값 비교로는 못 잡는다 — 청크마다 원본 페이지가 다르면
    # 공유해도 값이 달라 통과한다(실제로 그렇게 새는 판정을 한 번 썼다).
    rep.expect(
        payload is not None and chunks
        and all(
            doc.metadata is not chunk.origin[0].metadata
            for doc, chunk in zip(payload, chunks)
        ),
        "pdf: metadata 는 청크마다 사본이다(원본을 물리면 뒤가 앞을 바꾼다)",
    )
    rep.expect(
        module._fp_langchain_payload([_Chunkless()]) is None,
        "pdf: 출처가 없으면 지어내지 않고 벤더 청커로 돌아간다",
    )

    owner = _FakeSplitOwner()
    module._fp_install_outline_chunker(
        owner, "pdf", reset_page_counts=False, honor_chunker_type=False,
        source=module._FP_SRC_LANGCHAIN,
    )
    result = owner.split_documents(_statute_pages())
    rep.expect(
        owner.vendor_calls == 0 and hasattr(result[0], "page_content"),
        "pdf 설치: 조문 문서에서 벤더 청커를 부르지 않고 같은 모양으로 돌려준다",
        f"{owner.vendor_calls} {type(result[0]).__name__}",
    )
    rep.expect(
        sum(owner.page_chunk_counts.values()) == len(result)
        and owner.page_chunk_counts[99] == 0,
        "pdf 설치: `metadata['page']` 로 페이지별 청크 수를 세고, 없는 키에서 죽지 않는다",
        f"{dict(owner.page_chunk_counts)}",
    )
    owner.split_documents(_plain_pages())
    rep.expect(owner.vendor_calls == 1, "pdf 설치: 일반 문서는 벤더 청커로 넘긴다")


class _Chunkless:
    """출처가 빈 `Chunk` 대역."""

    text = "본문"
    origin = ()


def _check_transfer_kit(rep) -> None:
    """`transfer/` 가 지금 원본과 맞는가 (2026-09-01).

    ## 왜 이게 제일 값어치 있는 판정인가

    폐쇄망에는 파일이 안 들어가고 **사람이 화면을 보며 타이핑**한다. 그래서 `transfer/`
    가 옛 코드로 남으면 **옛 코드를 손으로 옮겨 적게 되는데, 그걸 잡을 그물이 없다** —
    치는 순간에는 맞아 보이고, 온프레미스에서 이상하게 도는 것으로만 드러난다.

    생성물이 원본과 갈리는 것을 잡는다는 점에서 `final_preprocessor.py` 판정과 같은
    종류이고, **대가는 이쪽이 더 크다**(그쪽은 다시 빌드하면 되지만 이쪽은 사람이
    다시 친다).
    """
    sys.path.insert(0, _PREPROC)
    try:
        kit = _load(os.path.join(_PREPROC, "build_transfer_kit.py"), "_fp_kit")
    except Exception as exc:  # noqa: BLE001
        rep.expect(False, "이관 키트 생성기가 적재된다", f"{type(exc).__name__}: {exc}")
        return

    out_dir = os.path.join(_PREPROC, "transfer")
    if not os.path.isdir(out_dir):
        rep.expect(False, "이관 자료가 있다", "transfer/ 가 없다 — build_transfer_kit.py 를 돌릴 것")
        return

    builder = kit._bfp
    hwpx = builder._strip_future(builder._read(builder._HWPX_SRC), "hwpx")
    hwpx = builder._rename_verified(hwpx, builder._HWPX_RENAME, "hwpx")
    hwpx = kit._strip_verified(hwpx, "hwpx")

    lines = builder._strip_future(builder._read(builder._ROUTER_SRC), "router").splitlines(
        keepends=True
    )
    index = [i for i, line in enumerate(lines) if line.strip() == "# ROUTER-BODY-BEGIN"][0]
    router = kit._strip_verified("".join(lines[index + 1:]).lstrip("\n"), "router")

    expected_files = {"10_hwpx.py": hwpx, "20_router.py": router,
                      "30_verify.py": kit._VERIFY_SNIPPET}
    for name, want in expected_files.items():
        path = os.path.join(out_dir, name)
        got = ""
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                got = fh.read()
        rep.expect(
            got == want,
            f"이관 자료가 지금 원본과 같다: {name}",
            "build_transfer_kit.py 를 다시 돌릴 것 — 안 그러면 옛 코드를 손으로 옮겨 적는다",
        )

    # 기대 해시표가 자료와 맞는가. **어긋나면 검증이 통째로 쓸모없어진다** — 사람이
    # 제대로 쳤는데도 전부 틀린 것으로 보이면 그 표를 안 믿게 된다.
    expect_path = os.path.join(out_dir, "40_expect.txt")
    expect_text = ""
    if os.path.exists(expect_path):
        with open(expect_path, "r", encoding="utf-8") as fh:
            expect_text = fh.read()
    ok = True
    for name in ("10_hwpx.py", "20_router.py"):
        rows = [f"{digest} {symbol}" for digest, symbol in kit._digests(expected_files[name])]
        if not rows or not all(row in expect_text for row in rows):
            ok = False
    rep.expect(ok, "기대 해시표가 타이핑 자료와 맞는다", "40_expect.txt 가 낡았다")

    # 스니펫이 **생성 쪽과 같은 식으로** 해시를 계산하는가. 한 글자만 달라도 사람이
    # 제대로 친 코드가 전부 어긋난 것으로 보인다 — 그 상태는 오류가 아니라 "이 표는
    # 못 믿겠다" 로만 드러난다.
    snippet = os.path.join(out_dir, "30_verify.py")

    def _run(path: str) -> list:
        proc = subprocess.run(
            [sys.executable, snippet, path],
            capture_output=True, text=True, encoding="utf-8",
        )
        return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]

    wanted = [f"{d} {s}" for d, s in kit._digests(hwpx)]
    rep.expect(
        _run(os.path.join(out_dir, "10_hwpx.py")) == wanted,
        "검증 스니펫이 생성 쪽과 같은 해시를 낸다",
        "스니펫과 생성 쪽 계산식이 갈렸다",
    )

    # **줄 끝 공백을 견디는가.** 이 판정이 요점이다 — `rstrip` 규칙은 생성물이 아니라
    # **사람이 친 코드**를 위해 있다. 생성물에는 줄 끝 공백이 없어서 위 판정만으로는
    # 규칙을 지워도 통과한다(되돌려 보고 알았다). 공백을 실제로 끼워 넣고 본다.
    #
    # 견디지 못하면 사람이 제대로 친 코드가 **전부 어긋난 것으로** 보이고, 그러면
    # 그 표를 안 믿게 된다 — 검증이 통째로 쓸모없어진다.
    padded = os.path.join(tempfile.mkdtemp(prefix="fp_kit_"), "typed.py")
    with open(os.path.join(out_dir, "10_hwpx.py"), "r", encoding="utf-8") as fh:
        body = fh.read()
    with open(padded, "w", encoding="utf-8", newline="\n") as fh:
        # 사람이 친 코드에서 실제로 나오는 모양 — 줄 끝에 공백이 남는다.
        fh.write("\n".join(f"{line}  " if line.strip() else line
                           for line in body.splitlines()) + "\n")
    rep.expect(
        _run(padded) == wanted,
        "검증 스니펫이 줄 끝 공백 차이를 견딘다",
        "사람이 친 코드가 전부 어긋난 것으로 보인다 — 표를 못 믿게 된다",
    )
    shutil.rmtree(os.path.dirname(padded), ignore_errors=True)

    # 벤더에 손댈 자리가 **한 줄**인가. 늘어났다면 절차서의 표도 늘어나야 한다 —
    # 안 맞으면 사람이 한 자리만 고치고 넘어간다.
    edits = kit._locate_vendor_edit()
    rep.expect(
        len(edits) == 1 and edits[0][1].strip().startswith("class DocumentProcessor"),
        "벤더 수정은 `class DocumentProcessor:` 한 줄뿐이다",
        f"{[(n, t.strip()[:40]) for n, t in edits]}",
    )

    # 절차서가 그 줄 번호를 싣고 있는가.
    proc_path = os.path.join(out_dir, "00_이관절차.md")
    proc_text = ""
    if os.path.exists(proc_path):
        with open(proc_path, "r", encoding="utf-8") as fh:
            proc_text = fh.read()
    rep.expect(
        str(edits[0][0]) in proc_text and "AttachDocumentProcessor" in proc_text,
        "절차서가 벤더 수정 자리를 짚어 준다",
        "00_이관절차.md 가 낡았다",
    )


def _check_config_resolution(module, rep, tmpdir) -> None:
    resolve = module._fp_resolve_config_path
    good = os.path.join(tmpdir, "attachment_processor_config.yaml")
    with open(good, "w", encoding="utf-8") as fh:
        fh.write("chunking: {}\n")
    rep.expect(resolve("attach", good) == good, "설정 경로를 직접 주면 그것을 쓴다")

    env = module._FP_CONFIG_ENV["attach"]
    saved = os.environ.get(env)
    try:
        os.environ[env] = good
        rep.expect(resolve("attach", None) == good, "환경변수로도 준다")
        os.environ[env] = os.path.join(tmpdir, "없는파일.yaml")
        rep.expect(
            resolve("attach", None) != os.environ[env],
            "없는 경로를 가리키면 다음 후보로 넘어간다(세우지 않는다)",
        )
    finally:
        if saved is None:
            os.environ.pop(env, None)
        else:
            os.environ[env] = saved
    rep.expect(
        set(module._FP_CONFIG_ENV) == {"attach"} and set(module._FP_CONFIG_KWARG) == {"attach"},
        "설정 표에 지능형이 남아 있지 않다",
    )


def main() -> int:
    rep = Report()
    module = _load(_MERGED, "_fp_merged")
    standalone = _load(os.path.join(_PREPROC, "hwpx_preprocessor.py"), "_fp_standalone")

    # 이 점검이 도는 환경(표준 라이브러리 + lxml)에서는 벤더 절반이 적재되지 않는다.
    # **그 상태에서 파일이 import 되고 hwpx 가 도는 것**이 계약이다.
    rep.expect(module._FP_ATTACH_IMPORT_ERROR is not None, "로컬에는 벤더 스택이 없다(전제)")
    rep.expect(bool(module._FP_ATTACH_IMPORT_TRACE), "첨부용 적재 실패를 버리지 않고 남긴다")
    rep.expect(
        not hasattr(module, "_FP_INTELLIGENT_IMPORT_ERROR"),
        "지능형 가드가 남아 있지 않다",
    )
    rep.expect(hasattr(module, "HwpxDocumentProcessor"), "벤더가 없어도 hwpx 파서는 있다")
    rep.expect(hasattr(module, "parse") and hasattr(module, "chunk_blocks"), "hwpx 파싱 함수가 그대로 있다")

    _check_generated_is_current(rep)
    _check_optional_import_guard(rep)
    _check_overlap_handling(rep)
    _check_kwargs(module, rep)

    tmpdir = tempfile.mkdtemp(prefix="final_preproc_")
    try:
        _check_routing(module, rep, tmpdir)
        _check_hwpx_path(module, standalone, rep)
        _check_vendor_absent(module, rep, tmpdir)
        _check_attach_stands_alone(module, rep, tmpdir)
        _check_vendor_present(module, rep, tmpdir)
        _check_config_resolution(module, rep, tmpdir)
        _check_transfer_kit(rep)
        _check_outline_bridge(module, rep)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        print()
        print("생성물이 원본과 갈렸다면:  python onprem/preprocessor/build_final_preprocessor.py")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
