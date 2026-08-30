"""통합 전처리기(`onprem/preprocessor/final_preprocessor.py`) 점검.

`python onprem/test/check_final_preprocessor.py`

## 왜 따로 보나

이 파일은 **생성물**이다 — `build_final_preprocessor.py` 가 벤더 둘(첨부용·지능형)과
hwpx 파서, 라우터를 한 등록 단위로 붙인다. 그래서 세 종류의 결함이 생길 수 있고,
**셋 다 예외를 던지지 않는다**:

1. **생성물이 원본과 갈렸다** — 빌드를 안 돌리고 커밋하면 등록 화면에 올라간 파일만
   옛 코드로 남는다. 여기서 다시 만들어 대조한다.
2. **겹침 처리가 틀렸다** — 첨부용·지능형이 최상위 이름 24개를 둘 다 정의한다. 지운
   것이 사실은 달랐거나, 개명이 새면 **한쪽이 다른 쪽 판본을 쓴다.** 예외가 아니라
   이상한 값으로만 드러난다.
3. **라우팅이 틀렸다** — hwpx 가 벤더로 새면 표 병합이 깨지는데 **적재는 성공으로
   보인다.** 반대로 pdf 가 hwpx 파서로 가면 그 문서가 검색에서 통째로 사라진다.

## 벤더 절반이 없는 환경에서 돈다

docling·`genon.preprocessor.*` 가 로컬에 없으므로 PART 1·2 는 적재되지 않는다. 그것
자체가 점검 대상이다(**그 상태에서도 hwpx 경로는 살아 있어야 한다**). 벤더가 실제로
불리는 갈래는 **대역을 라우터 밖에서 꽂아** 확인한다 — 폴백·kwargs 전달·지연 생성처럼
"벤더가 있을 때만" 도는 코드가 그렇지 않으면 한 번도 검사되지 않는다.
"""

import ast
import asyncio
import importlib.util
import os
import shutil
import sys
import tempfile
import zipfile

_ONPREM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(_ONPREM)
_PREPROC = os.path.join(_ONPREM, "preprocessor")
_MERGED = os.path.join(_PREPROC, "final_preprocessor.py")
_BUILDER = os.path.join(_PREPROC, "build_final_preprocessor.py")

# 실물 hwpx. 저장소에 커밋되지 않은 것이 섞여 있어 **있는 것만** 태운다.
_SAMPLES = [
    os.path.join(_ROOT, "20260616_기술협상서_신복위 검토_V113_제논 의견.hwpx"),
    os.path.join(_ROOT, "20260616_통합AI플랫폼구축사업_기술협상서_최종.hwpx"),
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


class _FakeIntelligent(_FakeVendor):
    label = "intelligent"


class _FakeAttach(_FakeVendor):
    label = "attach"


def _install_fakes(module):
    saved_flags = {
        name: getattr(module, name)
        for name in ("_FP_INTELLIGENT_IMPORT_ERROR", "_FP_ATTACH_IMPORT_ERROR")
    }
    saved_classes = {
        name: getattr(module, name, None)
        for name in ("IntelligentDocumentProcessor", "AttachDocumentProcessor")
    }
    module._FP_INTELLIGENT_IMPORT_ERROR = None
    module._FP_ATTACH_IMPORT_ERROR = None
    module.IntelligentDocumentProcessor = _FakeIntelligent
    module.AttachDocumentProcessor = _FakeAttach

    def restore():
        for name, value in saved_flags.items():
            setattr(module, name, value)
        for name, value in saved_classes.items():
            if value is None:
                if hasattr(module, name):
                    delattr(module, name)
            else:
                setattr(module, name, value)

    return restore


# ---------------------------------------------------------------------------
# 1) 생성물이 원본 넷과 맞는가
# ---------------------------------------------------------------------------


def _check_generated_is_current(rep) -> None:
    builder = _load(_BUILDER, "_fp_builder")
    with open(_MERGED, "r", encoding="utf-8") as fh:
        on_disk = fh.read()

    attach = builder._drop_definitions(
        builder._strip_future(builder._read(builder._ATTACH_SRC), "attach"), builder._ATTACH_DROP
    )
    attach = builder._rename_verified(attach, builder._ATTACH_RENAME, "attach")
    attach = builder._annotate_renames(attach, builder._ATTACH_RENAME)
    rep.expect(
        builder._indent(attach.lstrip("\n")).rstrip("\n") in on_disk,
        "생성물의 첨부용 절반이 원본(겹침 처리 후)과 같다",
        "build_final_preprocessor.py 를 다시 돌릴 것",
    )

    intel = builder._rename_verified(
        builder._strip_future(builder._read(builder._INTEL_SRC), "intel"),
        builder._INTEL_RENAME,
        "intel",
    )
    rep.expect(
        builder._indent(intel.lstrip("\n")).rstrip("\n") in on_disk,
        "생성물의 지능형 절반이 원본과 같다",
        "GenOS 참조 사본이 갱신됐다면 다시 돌릴 것",
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

    # 겹침 분류가 원본과 맞는가 — GenOS 가 어느 한쪽만 고치면(같던 것이 달라지면)
    # 지운 정의가 **다른 판본으로 바뀌어** 조용히 동작이 바뀐다.
    try:
        builder._classify_overlap(
            builder._strip_future(builder._read(builder._ATTACH_SRC), "attach"),
            builder._strip_future(builder._read(builder._INTEL_SRC), "intel"),
        )
        rep.expect(True, "첨부용↔지능형 겹침 분류가 원본과 맞는다 (제거 13 / 개명 8 / 보존 3)")
    except SystemExit as exc:
        rep.expect(False, "첨부용↔지능형 겹침 분류가 원본과 맞는다", str(exc)[:160])


# ---------------------------------------------------------------------------
# 2) 겹침 처리 결과가 실제로 살아 있는가
# ---------------------------------------------------------------------------


def _check_overlap_handling(rep) -> None:
    """겹침 처리 결과를 **생성된 소스에서** 본다.

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

    # 개명한 8개는 **옛 이름과 새 이름이 둘 다** 살아 있어야 한다. 하나라도 없으면
    # 한쪽이 다른 쪽 판본을 쓰게 되고, 그건 예외가 아니라 이상한 값으로만 드러난다.
    for old, new in builder._ATTACH_RENAME.items():
        rep.expect(new in defined, f"개명본이 살아 있다: {old} -> {new}")
        rep.expect(old in defined, f"지능형 판본도 그대로 있다: {old}")

    for name in ("IntelligentDocumentProcessor", "AttachDocumentProcessor",
                 "HwpxDocumentProcessor", "DocumentProcessor"):
        rep.expect(name in defined, f"처리기가 자기 이름으로 있다: {name}")

    # 지운 13개는 **한 번만** 정의돼야 한다(지능형 판본). 예외는 `_log` 뿐이다 —
    # hwpx 조각도 같은 식(`logging.getLogger(__name__)`)으로 자기 것을 두는데,
    # 한 모듈이라 `__name__` 이 같아 결국 같은 객체다.
    for name in builder._ATTACH_DROP:
        count = len(defined.get(name, []))
        expected = 2 if name in builder._ALLOWED_DUPLICATES else 1
        rep.expect(
            count == expected,
            f"겹침이 정리됐다: {name}",
            f"정의 {count}개 (기대 {expected})",
        )

    # 개명이 실제로 다른 물건을 가리키는지 — `_load_config` 는 첨부용 판본이 설정 파일
    # 부재를 `{}` 로 넘기고 지능형 판본은 예외를 던진다. 같아지면 첨부용 등록이 설정
    # 없이는 안 뜬다.
    pair = (defined.get("_at_load_config"), defined.get("_load_config"))
    rep.expect(
        all(pair) and ast.dump(pair[0][0]) != ast.dump(pair[1][0]),
        "`_at_load_config` 와 `_load_config` 가 실제로 다른 판본이다",
    )

    # `Document` — hwpx 데이터클래스가 langchain 것을 덮으면 첨부용 20개 호출부가
    # **호출 시점에** 터진다(import 는 통과한다).
    rep.expect("HwpxDocument" in defined, "hwpx 의 Document 가 HwpxDocument 로 비켜 있다")
    rep.expect(
        "Document" not in defined,
        "최상위에 `Document` 를 정의하지 않는다 (첨부용의 langchain import 를 덮는다)",
    )

    # `HybridChunker` 클래스 본문이 정의 시점에 읽는 두 상수 — 지웠으면 import 가 죽는다.
    for name in ("_DEFAULT_TOKENIZER_LOCAL_PATH", "_DEFAULT_TOKENIZER_ID"):
        rep.expect(len(defined.get(name, [])) == 2, f"정의 시점에 읽히는 상수는 양쪽에 남긴다: {name}")

    # 표식 주석 — 생성물만 보고도 "여기 원래 뭐가 있었나" 를 알 수 있어야 한다.
    with open(_MERGED, "r", encoding="utf-8") as fh:
        text = fh.read()
    rep.expect(
        text.count("# [병합 제거]") == len(builder._ATTACH_DROP),
        "지운 자리마다 표식 주석이 있다",
        f"{text.count('# [병합 제거]')} != {len(builder._ATTACH_DROP)}",
    )
    rep.expect(
        text.count("# [병합 개명]") == len(builder._ATTACH_RENAME),
        "개명한 자리마다 표식 주석이 있다",
        f"{text.count('# [병합 개명]')} != {len(builder._ATTACH_RENAME)}",
    )


# ---------------------------------------------------------------------------
# 3) 라우팅
# ---------------------------------------------------------------------------


def _check_routing(module, rep, tmpdir) -> None:
    route = module._fp_route
    HWPX, INTEL, ATTACH = module._FP_HWPX, module._FP_INTELLIGENT, module._FP_ATTACH

    # 지능형이 이기는 형식 — 첨부용 pdf 경로는 PyMuPDF 평문이라 표가 통째로 사라진다.
    for name, label in (("보고서.pdf", "pdf"), ("발표.pptx", "pptx"), ("표.xlsx", "xlsx"),
                        ("사진.png", "png"), ("구형.doc", "doc")):
        rep.expect(route(f"/x/{name}", "auto", {})[0] == INTEL, f"{label} -> 지능형")

    # 첨부용이 이기는 형식 — 네이티브 백엔드라 PDF 변환을 거치지 않는다.
    for name, label in (("계약.docx", "docx"), ("구버전.hwp", "hwp"), ("옛.hml", "hml"),
                        ("녹취.mp3", "mp3"), ("메모.txt", "txt"), ("설명.md", "md")):
        rep.expect(route(f"/x/{name}", "auto", {})[0] == ATTACH, f"{label} -> 첨부용")

    rep.expect(route("/x/모르는.zzz", "auto", {})[0] == INTEL, "모르는 확장자 -> 기본(지능형)")
    rep.expect(
        route("/x/보고서.pdf", "auto", {".pdf": ATTACH}) == (ATTACH, "override"),
        "route_overrides 가 확장자 라우팅을 덮는다",
    )

    real = _existing_samples()
    if real:
        rep.expect(route(real[0], "auto", {})[0] == HWPX, "실물 hwpx -> hwpx 파서")
        rep.expect(route(real[0], "intelligent", {})[0] == INTEL, "hwpx_engine=intelligent")
        rep.expect(route(real[0], "attach", {})[0] == ATTACH, "hwpx_engine=attach")

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
             "intelligent_config_path": "/x", "attachment_config_path": "/y", "chunk_size": 800}
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
            "intelligent" in str(exc) and "ModuleNotFoundError" in str(exc),
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
        rep.expect(records[0]["text"] == "intelligent 결과", "pdf 는 지능형이 처리한다")
        called_path, called_kwargs = processor._vendor["intelligent"].calls[0]
        rep.expect(called_kwargs == {"chunk_size": 700}, "벤더에 라우터 kwargs 가 새지 않는다",
                   str(called_kwargs))

        docx = os.path.join(tmpdir, "계약.docx")
        with zipfile.ZipFile(docx, "w") as archive:
            archive.writestr("word/document.xml", "<w:document/>")
        records = asyncio.run(processor(None, docx))
        rep.expect(records[0]["text"] == "attach 결과", "docx 는 첨부용이 처리한다")
        rep.expect(
            set(processor._vendor) == {"intelligent", "attach"},
            "엔진마다 따로 만들어 들고 있다",
        )

        asyncio.run(processor(None, pdfish))
        rep.expect(len(processor._vendor["intelligent"].calls) == 2, "두 번째 호출은 만들어 둔 것을 쓴다")

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


def _check_attach_depends_on_intelligent(module, rep, tmpdir) -> None:
    """첨부용만 살아 있고 지능형이 없는 상태 — **지운 13개 때문에 첨부용도 못 쓴다.**

    그 사실을 뭉뚱그리면 엉뚱한 곳(첨부용 의존성)을 뒤지게 된다.
    """
    saved_attach = module._FP_ATTACH_IMPORT_ERROR
    saved_class = getattr(module, "AttachDocumentProcessor", None)
    module._FP_ATTACH_IMPORT_ERROR = None
    module.AttachDocumentProcessor = _FakeAttach
    try:
        processor = module.DocumentProcessor()
        docx = os.path.join(tmpdir, "계약2.docx")
        with open(docx, "wb") as fh:
            fh.write(b"PK\x03\x04")
        try:
            asyncio.run(processor(None, docx))
            rep.expect(False, "첨부용만 있고 지능형이 없으면 예외", "예외가 나지 않았다")
        except module.FinalPreprocessorError as exc:
            rep.expect(
                "지능형" in str(exc),
                "첨부용이 지능형 공통 정의에 의존한다는 사실을 말해 준다",
                str(exc)[:110],
            )
        except Exception as exc:  # noqa: BLE001
            rep.expect(False, "첨부용만 있고 지능형이 없으면 예외", f"{type(exc).__name__}: {exc}")
    finally:
        module._FP_ATTACH_IMPORT_ERROR = saved_attach
        if saved_class is None:
            if hasattr(module, "AttachDocumentProcessor"):
                delattr(module, "AttachDocumentProcessor")
        else:
            module.AttachDocumentProcessor = saved_class


def _check_config_resolution(module, rep, tmpdir) -> None:
    resolve = module._fp_resolve_config_path
    good = os.path.join(tmpdir, "intelligent_processor_config.yaml")
    with open(good, "w", encoding="utf-8") as fh:
        fh.write("chunking: {}\n")
    rep.expect(resolve("intelligent", good) == good, "설정 경로를 직접 주면 그것을 쓴다")

    env = module._FP_CONFIG_ENV["intelligent"]
    saved = os.environ.get(env)
    try:
        os.environ[env] = good
        rep.expect(resolve("intelligent", None) == good, "환경변수로도 준다")
        os.environ[env] = os.path.join(tmpdir, "없는파일.yaml")
        rep.expect(
            resolve("intelligent", None) != os.environ[env],
            "없는 경로를 가리키면 다음 후보로 넘어간다(세우지 않는다)",
        )
    finally:
        if saved is None:
            os.environ.pop(env, None)
        else:
            os.environ[env] = saved
    rep.expect(
        module._FP_CONFIG_ENV["attach"] != module._FP_CONFIG_ENV["intelligent"],
        "두 엔진의 설정 환경변수가 따로다",
    )


def main() -> int:
    rep = Report()
    module = _load(_MERGED, "_fp_merged")
    standalone = _load(os.path.join(_PREPROC, "hwpx_preprocessor.py"), "_fp_standalone")

    # 이 점검이 도는 환경(표준 라이브러리 + lxml)에서는 벤더 절반이 적재되지 않는다.
    # **그 상태에서 파일이 import 되고 hwpx 가 도는 것**이 계약이다.
    rep.expect(module._FP_INTELLIGENT_IMPORT_ERROR is not None, "로컬에는 docling 스택이 없다(전제)")
    rep.expect(bool(module._FP_INTELLIGENT_IMPORT_TRACE), "지능형 적재 실패를 버리지 않고 남긴다")
    rep.expect(bool(module._FP_ATTACH_IMPORT_TRACE), "첨부용 적재 실패를 버리지 않고 남긴다")
    rep.expect(hasattr(module, "HwpxDocumentProcessor"), "벤더가 없어도 hwpx 파서는 있다")
    rep.expect(hasattr(module, "parse") and hasattr(module, "chunk_blocks"), "hwpx 파싱 함수가 그대로 있다")

    _check_generated_is_current(rep)
    _check_overlap_handling(rep)
    _check_kwargs(module, rep)

    tmpdir = tempfile.mkdtemp(prefix="final_preproc_")
    try:
        _check_routing(module, rep, tmpdir)
        _check_hwpx_path(module, standalone, rep)
        _check_vendor_absent(module, rep, tmpdir)
        _check_attach_depends_on_intelligent(module, rep, tmpdir)
        _check_vendor_present(module, rep, tmpdir)
        _check_config_resolution(module, rep, tmpdir)
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
