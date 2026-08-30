"""`final_preprocessor.py` 의 PART 4 — 라우터 원문.

**이 파일은 그 자체로 동작하지 않는다.** `AttachDocumentProcessor`(PART 1) ·
`IntelligentDocumentProcessor`(PART 2) · `HwpxDocumentProcessor`·`_log_info`·
`_log_warning`(PART 3) 이 같은 네임스페이스에 있다는 전제로 쓰였고, 그 셋은 병합
단계에서 앞에 붙는다. 여기 따로 두는 이유는 하나다 — **라우터를 문자열로 들고 있으면
문법 검사도 편집기도 못 도와준다.** 빌드가 표식 줄 아래를 그대로 잘라 붙인다.

고친 뒤에는 반드시:

    python onprem/preprocessor/build_final_preprocessor.py
"""

from __future__ import annotations

# ROUTER-BODY-BEGIN


class FinalPreprocessorError(Exception):
    """라우터 자신이 내는 오류.

    hwpx 파싱 실패는 `HwpxParseError` 로, 벤더 경로의 실패는 그쪽 예외 그대로 올린다 —
    여기서 한 종류로 뭉치면 **어느 경로가 죽었는지가 로그에서 사라진다.**
    """


_FP_HWPX = "hwpx"
_FP_INTELLIGENT = "intelligent"
_FP_ATTACH = "attach"
_FP_ENGINES = (_FP_HWPX, _FP_INTELLIGENT, _FP_ATTACH)

_FP_ENGINE_AUTO = "auto"
_FP_ENGINE_NATIVE = "native"
_FP_HWPX_ENGINES = (_FP_ENGINE_AUTO, _FP_ENGINE_NATIVE, _FP_ATTACH, _FP_INTELLIGENT)

_FP_HWPX_EXTENSIONS = (".hwpx",)
_FP_ZIP_MAGIC = b"PK\x03\x04"
_FP_HWPX_MIMETYPE = b"application/hwp+zip"
_FP_SECTION_PREFIX = "Contents/section"

# ---------------------------------------------------------------------------
# 확장자 → 엔진. **형식마다 덜 잃는 쪽**으로 보낸다.
#
# 근거는 두 벤더 원본의 실제 경로다(모듈 docstring 의 표에 정리해 뒀다). 요약하면:
# 첨부용은 docx·hwp 를 **네이티브 백엔드**로 읽어 PDF 변환을 거치지 않고, 지능형은
# pdf 를 **docling layout + TableFormer + OCR** 로 읽는다. 서로의 약한 쪽이 정확히
# 반대라서 한 엔진만 고르면 어느 형식이든 손해가 난다.
#
# 여기 없는 확장자는 `_FP_DEFAULT_ENGINE` 으로 간다.
# ---------------------------------------------------------------------------
_FP_ROUTES = {
    # 우리 파서 — 표 병합·조문 위계를 지킨다
    ".hwpx": _FP_HWPX,
    # 첨부용: GenosHwp SDK / GenosMsWord 네이티브. 지능형은 이것들을 PDF 로 바꾼다
    ".hwp": _FP_ATTACH,
    ".hml": _FP_ATTACH,
    ".docx": _FP_ATTACH,
    # 첨부용: Whisper STT. 지능형에는 이 경로가 아예 없다
    ".wav": _FP_ATTACH,
    ".mp3": _FP_ATTACH,
    ".m4a": _FP_ATTACH,
    # 첨부용: TextLoader. 지능형은 텍스트 파일도 PDF 로 바꾼다
    ".txt": _FP_ATTACH,
    ".md": _FP_ATTACH,
    ".json": _FP_ATTACH,
    # 지능형: 첨부용 pdf 경로는 PyMuPDF 평문 + 문자 수 분할이라 표가 통째로 사라진다
    ".pdf": _FP_INTELLIGENT,
    # 지능형: 둘 다 PDF 변환이지만 enrichment 가 더 많다
    ".ppt": _FP_INTELLIGENT,
    ".pptx": _FP_INTELLIGENT,
    # 지능형: PDF 변환 없이 직접 처리 + tabular 모드
    ".xlsx": _FP_INTELLIGENT,
    ".xlsm": _FP_INTELLIGENT,
    ".csv": _FP_INTELLIGENT,
    # 지능형: docling OCR
    ".jpg": _FP_INTELLIGENT,
    ".jpeg": _FP_INTELLIGENT,
    ".png": _FP_INTELLIGENT,
    ".gif": _FP_INTELLIGENT,
    ".bmp": _FP_INTELLIGENT,
    ".tiff": _FP_INTELLIGENT,
    # 구버전 Word — 둘 다 PDF 변환을 거친다. 지능형 파이프라인이 낫다
    ".doc": _FP_INTELLIGENT,
}
_FP_DEFAULT_ENGINE = _FP_INTELLIGENT

# 라우터가 자기 몫으로 받는 값. 벤더 처리기로 **넘기기 전에 뺀다** — 그대로 넘기면
# 벤더가 `kwargs: {...}` 로 통째로 로그에 찍고, 언젠가 같은 이름을 쓰면 조용히 겹친다.
_FP_ROUTER_KWARGS = (
    "hwpx_engine",
    "route_overrides",
    "align_vector_schema",
    "intelligent_config_path",
    "attachment_config_path",
)

_FP_CONFIG_ENV = {
    _FP_INTELLIGENT: "GENOS_INTELLIGENT_CONFIG_PATH",
    _FP_ATTACH: "GENOS_ATTACHMENT_CONFIG_PATH",
}
_FP_CONFIG_BASENAMES = {
    _FP_INTELLIGENT: ("intelligent_processor_config.yaml",),
    _FP_ATTACH: ("attachment_processor_config.yaml", "attach_processor_config.yaml"),
}
_FP_CONFIG_KWARG = {
    _FP_INTELLIGENT: "intelligent_config_path",
    _FP_ATTACH: "attachment_config_path",
}

# 벤더 레코드에는 늘 있고 hwpx 레코드에는 없던 예약 필드. **한 등록이 한 컬렉션에 두
# 모양의 메타를 넣으면** 그 필드로 거르는 검색이 한쪽을 통째로 놓치는데, 그 상태는
# 오류가 아니라 "결과가 좀 적네" 로만 보인다. 값은 벤더가 못 채웠을 때 내는 것과 같은
# 것을 쓴다 — **지어내지 않는다.**
_FP_SCHEMA_DEFAULTS = {
    "title": "",
    "created_date": None,
    "appendix": "",
    "guardrail_categories": None,
}


def _fp_engine_error(engine: str):
    """그 엔진을 쓸 수 없게 만든 예외. 쓸 수 있으면 `None`.

    **첨부용은 지능형에도 의존한다.** 병합할 때 본문이 같은 정의 14개를 첨부용 쪽에서
    지웠고(죽은 코드였다) 그 자리를 지능형 판본이 채우기 때문이다. 지능형 절반이
    적재되지 않았으면 첨부용 코드가 `NameError` 로 죽으므로, 여기서 미리 갈라
    **어느 절반이 문제인지**를 알려 준다.
    """
    if engine == _FP_INTELLIGENT:
        return _FP_INTELLIGENT_IMPORT_ERROR
    if engine == _FP_ATTACH:
        return _FP_ATTACH_IMPORT_ERROR or _FP_INTELLIGENT_IMPORT_ERROR
    return None


def _fp_choice_kwarg(value, default: str, allowed: tuple, key: str) -> str:
    """선택지 kwargs. 잘못된 값은 **세우지 않고** 기본값으로 떨어지되 로그에 남긴다.

    GenOS 는 값이 비었을 때 `None` 이 아니라 **빈 문자열**을 주기도 한다(MCP 규약과 같다).
    """
    if value is None or value == "":
        return default
    text = str(value).strip().lower()
    if text in allowed:
        return text
    _log_warning(f"unknown {key} - falling back to '{default}'", event="final_preprocess_bad_kwarg")
    return default


def _fp_bool_kwarg(value, default: bool, key: str) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    _log_warning(f"unknown {key} - falling back to '{default}'", event="final_preprocess_bad_kwarg")
    return default


def _fp_overrides_kwarg(value) -> dict:
    """`{".pdf": "attach"}` 꼴 라우팅 덮어쓰기. 문자열(JSON)로 와도 받는다."""
    if not value:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:  # noqa: BLE001 - 형식 오류로 재적재를 막지 않는다
            _log_warning("route_overrides is not valid JSON - ignored",
                         event="final_preprocess_bad_kwarg")
            return {}
    if not isinstance(value, dict):
        _log_warning("route_overrides is not a mapping - ignored",
                     event="final_preprocess_bad_kwarg")
        return {}
    clean = {}
    for key, engine in value.items():
        ext = str(key).strip().lower()
        target = str(engine).strip().lower()
        if not ext.startswith("."):
            ext = "." + ext
        if target not in _FP_ENGINES:
            _log_warning("route_overrides names an unknown engine - that entry is ignored",
                         event="final_preprocess_bad_kwarg")
            continue
        clean[ext] = target
    return clean


def _fp_is_hwpx_container(file_path: str):
    """내용이 hwpx 인가. `(판정, 사유)`.

    확장자만 믿지 않는 이유: `.hwpx` 라는 이름을 달았을 뿐 실제로는 PDF·hwp 인 파일이
    우리 파서에 들어가면 예외가 나고 **그 문서는 검색에서 통째로 사라진다.** 여기서
    갈라 벤더로 보내면 표는 덜 정확해도 적재는 된다.
    """
    try:
        with open(file_path, "rb") as handle:
            head = handle.read(4)
    except OSError:
        return False, "read_failed"
    if head != _FP_ZIP_MAGIC:
        return False, "not_a_zip"
    try:
        with zipfile.ZipFile(file_path) as archive:
            names = archive.namelist()
            mimetype = b""
            if "mimetype" in names:
                try:
                    mimetype = archive.read("mimetype").strip()
                except (KeyError, OSError, zipfile.BadZipFile):
                    mimetype = b""
    except (OSError, zipfile.BadZipFile):
        return False, "broken_zip"
    if mimetype == _FP_HWPX_MIMETYPE:
        return True, "mimetype"
    for name in names:
        if name.startswith(_FP_SECTION_PREFIX) and name.endswith(".xml"):
            return True, "section_xml"
    # zip 이긴 한데 hwpx 가 아니다 — docx/pptx/xlsx 가 `.hwpx` 이름을 달고 온 경우다.
    return False, "zip_without_hwpx_contents"


def _fp_route(file_path: str, hwpx_engine: str, overrides: dict):
    """`(엔진, 사유)`. 사유는 고정 문자열이라 로그에 그대로 실어도 된다(3.8절)."""
    extension = os.path.splitext(file_path)[1].lower()
    engine = overrides.get(extension) or _FP_ROUTES.get(extension, _FP_DEFAULT_ENGINE)
    reason = "override" if extension in overrides else "extension"

    if engine != _FP_HWPX:
        return engine, reason

    # 여기부터는 hwpx 확장자다.
    if hwpx_engine in (_FP_ATTACH, _FP_INTELLIGENT):
        return hwpx_engine, "hwpx_engine"

    is_hwpx, why = _fp_is_hwpx_container(file_path)
    if is_hwpx:
        return _FP_HWPX, why
    if hwpx_engine == _FP_ENGINE_NATIVE:
        # 네이티브를 강제했으면 넘기지 않는다 — 확장자와 내용이 어긋났다는 사실이
        # 폴백에 묻히면 안 된다는 뜻으로 고른 값이다.
        return _FP_HWPX, why
    # 이름만 hwpx 인 파일은 첨부용으로 — 실제로 hwp 계열이면 그쪽이 네이티브로 읽는다.
    return _FP_ATTACH, why


def _fp_align_records(records: list) -> list:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key, value in _FP_SCHEMA_DEFAULTS.items():
            record.setdefault(key, value)
    return records


def _fp_forward_kwargs(kwargs: dict) -> dict:
    return {key: value for key, value in kwargs.items() if key not in _FP_ROUTER_KWARGS}


def _fp_resolve_config_path(engine: str, explicit):
    """벤더 설정 yaml 을 찾는다. 못 찾으면 `None`(벤더 기본 해석에 맡긴다).

    벤더 함수는 `Path(__file__).parent/../resource/…` 를 본다. 등록 파일이 어디에 놓이는지
    실물로 확인하지 못했으므로 **한 자리만 보고 죽지 않게** 후보를 넷 둔다.
    """
    for candidate in (explicit, os.environ.get(_FP_CONFIG_ENV[engine], "")):
        text = str(candidate or "").strip()
        if not text:
            continue
        if os.path.isfile(text):
            return text
        _log_warning("configured vendor config path does not exist - trying the next candidate",
                     event="final_preprocess_config_missing")
    vendor_resolver = globals().get(
        "_resolve_default_intelligent_config_path" if engine == _FP_INTELLIGENT
        else "_resolve_default_attachment_config_path"
    )
    if vendor_resolver is not None:
        try:
            vendor_path = vendor_resolver()
        except Exception:  # noqa: BLE001 - 경로 해석 실패는 다음 후보로 넘어갈 뿐이다
            vendor_path = ""
        if vendor_path and os.path.isfile(vendor_path):
            return vendor_path
    node = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        for sub in ("resource_dev", "resource"):
            for basename in _FP_CONFIG_BASENAMES[engine]:
                candidate = os.path.join(node, sub, basename)
                if os.path.isfile(candidate):
                    return candidate
        parent = os.path.dirname(node)
        if parent == node:
            break
        node = parent
    return None


class DocumentProcessor:
    """GenOS 가 실행하는 진입점 — 확장자와 **내용**을 보고 세 처리기 중 하나로 보낸다.

    `docs/GENOS_RULES.md` §F 계약 그대로다: 인자 없이 생성 가능하고, `__call__` 은
    비동기이며 `text` 키를 가진 dict 목록을 돌려주거나 예외를 던진다.
    """

    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = config_path
        # hwpx 처리기는 지금 만든다 — 표준 라이브러리 + lxml 뿐이라 비용이 없다.
        self._hwpx = HwpxDocumentProcessor()
        # 벤더 둘은 **그 엔진으로 갈 파일이 처음 들어올 때** 만든다. 생성자가 yaml 을
        # 읽고 토크나이저·docling 변환기를 올리기 때문에, 여기서 만들면 hwpx 만 넣는
        # 배포도 그 비용과 실패 가능성을 함께 진다.
        self._vendor: dict = {}
        self._vendor_lock = None
        for engine in (_FP_INTELLIGENT, _FP_ATTACH):
            failure = _fp_engine_error(engine)
            if failure is not None:
                _log_warning(
                    f"{engine} preprocessing path unavailable",
                    event="final_preprocess_engine_unavailable",
                    error_type=type(failure).__name__,
                )

    async def __call__(self, request, file_path: str, **kwargs) -> list:
        started = time.monotonic()
        hwpx_engine = _fp_choice_kwarg(
            kwargs.get("hwpx_engine"), _FP_ENGINE_AUTO, _FP_HWPX_ENGINES, "hwpx_engine"
        )
        overrides = _fp_overrides_kwarg(kwargs.get("route_overrides"))
        engine, reason = _fp_route(file_path, hwpx_engine, overrides)
        _log_info(f"routed to {engine} ({reason})", event="final_preprocess_routed", status=engine)

        if engine != _FP_HWPX:
            return await self._run_vendor(engine, request, file_path, **kwargs)

        try:
            records = await self._hwpx(request, file_path, **_fp_forward_kwargs(kwargs))
        except Exception as exc:  # noqa: BLE001 - 분류는 아래 두 줄이 한다
            if hwpx_engine == _FP_ENGINE_NATIVE or _fp_engine_error(_FP_ATTACH) is not None:
                raise
            # 적재가 통째로 실패하는 것보다 표가 덜 정확한 적재가 낫다는 판단이다.
            # **폴백은 첨부용으로 간다** — GenosHwp SDK 네이티브라 hwpx 를 PDF 로 바꾸는
            # 지능형보다 덜 잃는다. **다만 조용히 넘기지 않는다**: 이 로그가 없으면
            # 사용자는 표 병합이 보존됐다고 믿는다.
            _log_warning(
                "hwpx native path failed - falling back to the attachment path "
                "(표 병합/조문 위계는 보존되지 않는다)",
                event="final_preprocess_fallback",
                error_code="05-00020003",
                error_type=type(exc).__name__,
            )
            return await self._run_vendor(_FP_ATTACH, request, file_path, **kwargs)

        if _fp_bool_kwarg(kwargs.get("align_vector_schema"), True, "align_vector_schema"):
            records = _fp_align_records(records)
        _log_info(
            "hwpx native path done",
            event="final_preprocess_done",
            status=_FP_HWPX,
            item_count=len(records),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return records

    async def _run_vendor(self, engine: str, request, file_path: str, **kwargs) -> list:
        processor = await self._acquire(engine, kwargs.get(_FP_CONFIG_KWARG[engine]))
        return await processor(request, file_path, **_fp_forward_kwargs(kwargs))

    async def _acquire(self, engine: str, config_path_kwarg=None):
        existing = self._vendor.get(engine)
        if existing is not None:
            return existing

        failure = _fp_engine_error(engine)
        if failure is not None:
            # 빈 목록을 돌려주지 않는다 — 그러면 "내용이 없는 문서" 와 구별되지 않는다.
            detail = ""
            if engine == _FP_ATTACH and _FP_ATTACH_IMPORT_ERROR is None:
                # 첨부용 코드는 멀쩡한데 지능형 절반이 없어서 못 쓰는 경우다. 그렇게
                # 말하지 않으면 엉뚱한 곳(첨부용 의존성)을 뒤지게 된다.
                detail = " (첨부용 코드는 적재됐지만 그것이 쓰는 지능형 쪽 공통 정의가 없습니다)"
            raise FinalPreprocessorError(
                f"'{engine}' 전처리 경로를 사용할 수 없어 이 형식은 처리할 수 없습니다"
                f"{detail} ({type(failure).__name__}: {failure})"
            )

        if self._vendor_lock is None:
            # 이 판정과 대입 사이에 await 가 없으므로 이벤트 루프에서 갈리지 않는다.
            self._vendor_lock = asyncio.Lock()
        async with self._vendor_lock:
            if self._vendor.get(engine) is None:
                started = time.monotonic()
                # 생성이 blocking 이다(yaml·토크나이저·docling 변환기). 이벤트 루프에서
                # 그대로 돌리면 같은 워커의 다른 요청이 그 시간만큼 멈춘다.
                self._vendor[engine] = await asyncio.to_thread(
                    self._build, engine, config_path_kwarg
                )
                _log_info(
                    f"{engine} processor initialised",
                    event="final_preprocess_engine_ready",
                    status=engine,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
        return self._vendor[engine]

    def _build(self, engine: str, config_path_kwarg):
        resolved = _fp_resolve_config_path(engine, config_path_kwarg or self._config_path)
        factory = (
            IntelligentDocumentProcessor if engine == _FP_INTELLIGENT else AttachDocumentProcessor
        )
        try:
            return factory(resolved) if resolved else factory()
        except Exception as exc:  # noqa: BLE001
            # 설정 파일 부재는 **재시도로 풀리지 않는 배포 문제**다. 원래 예외
            # (FileNotFoundError 등)만 올리면 어느 파일이 없다는 건지 드러나지 않아
            # 몇 번을 다시 눌러도 같은 자리에서 실패한다.
            raise FinalPreprocessorError(
                f"'{engine}' 전처리기를 초기화하지 못했습니다({type(exc).__name__}): {exc}"
            ) from exc
