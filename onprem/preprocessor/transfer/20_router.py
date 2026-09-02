class FinalPreprocessorError(Exception):
    pass
_FP_HWPX = "hwpx"
_FP_ATTACH = "attach"
_FP_ENGINES = (_FP_HWPX, _FP_ATTACH)
_FP_ENGINE_AUTO = "auto"
_FP_ENGINE_NATIVE = "native"
_FP_HWPX_ENGINES = (_FP_ENGINE_AUTO, _FP_ENGINE_NATIVE, _FP_ATTACH)
_FP_HWPX_EXTENSIONS = (".hwpx",)
_FP_ZIP_MAGIC = b"PK\x03\x04"
_FP_HWPX_MIMETYPE = b"application/hwp+zip"
_FP_SECTION_PREFIX = "Contents/section"
_FP_ROUTES = {
    ".hwpx": _FP_HWPX,
}
_FP_DEFAULT_ENGINE = _FP_ATTACH
_FP_ROUTER_KWARGS = (
    "hwpx_engine",
    "route_overrides",
    "align_vector_schema",
    "attachment_config_path",
)
_FP_CONFIG_ENV = {_FP_ATTACH: "GENOS_ATTACHMENT_CONFIG_PATH"}
_FP_CONFIG_BASENAMES = {
    _FP_ATTACH: ("attachment_processor_config.yaml", "attach_processor_config.yaml"),
}
_FP_CONFIG_KWARG = {_FP_ATTACH: "attachment_config_path"}
_FP_SCHEMA_DEFAULTS = {
    "title": "",
    "created_date": None,
    "appendix": "",
    "guardrail_categories": None,
}
def _fp_engine_error(engine: str):
    if engine == _FP_ATTACH:
        return _FP_ATTACH_IMPORT_ERROR
    return None
def _fp_choice_kwarg(value, default: str, allowed: tuple, key: str) -> str:
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
    if not value:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
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
    return False, "zip_without_hwpx_contents"
def _fp_route(file_path: str, hwpx_engine: str, overrides: dict):
    extension = os.path.splitext(file_path)[1].lower()
    engine = overrides.get(extension) or _FP_ROUTES.get(extension, _FP_DEFAULT_ENGINE)
    reason = "override" if extension in overrides else "extension"
    if engine != _FP_HWPX:
        return engine, reason
    if hwpx_engine == _FP_ATTACH:
        return hwpx_engine, "hwpx_engine"
    is_hwpx, why = _fp_is_hwpx_container(file_path)
    if is_hwpx:
        return _FP_HWPX, why
    if hwpx_engine == _FP_ENGINE_NATIVE:
        return _FP_HWPX, why
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
_FP_TABLE_OPEN = "<table><tbody>"
_FP_TABLE_CLOSE = "</tbody></table>"
_FP_SRC_DOCLING = "docling"
_FP_SRC_LANGCHAIN = "langchain"
class _FPPageCounts(dict):
    def __missing__(self, key):
        return 0
def _fp_table_html(item) -> str:
    data = getattr(item, "data", None)
    cells = list(getattr(data, "table_cells", None) or ())
    if not cells:
        return ""
    anchors: dict = {}
    occupied: set = set()
    header_rows: set = set()
    height = 0
    width = 0
    for cell in cells:
        row = _fp_cell_int(cell, "start_row_offset_idx", 0)
        col = _fp_cell_int(cell, "start_col_offset_idx", 0)
        row_span = max(1, _fp_cell_int(cell, "end_row_offset_idx", row + 1) - row)
        col_span = max(1, _fp_cell_int(cell, "end_col_offset_idx", col + 1) - col)
        if (row, col) in anchors:
            continue
        text = getattr(cell, "text", "")
        anchors[(row, col)] = (text if isinstance(text, str) else "", row_span, col_span)
        if getattr(cell, "column_header", False):
            header_rows.add(row)
        for d_row in range(row_span):
            for d_col in range(col_span):
                occupied.add((row + d_row, col + d_col))
        height = max(height, row + row_span)
        width = max(width, col + col_span)
    if not width or not height:
        return ""
    if not header_rows:
        header_rows = {0}
    covered = occupied - set(anchors)
    lines = [_FP_TABLE_OPEN]
    for row in range(height):
        tag = "th" if row in header_rows else "td"
        rendered = []
        for col in range(width):
            if (row, col) in covered:
                continue
            anchor = anchors.get((row, col))
            if anchor is None:
                rendered.append(f"<{tag}></{tag}>")
                continue
            text, row_span, col_span = anchor
            attrs = ""
            if row_span > 1:
                attrs += f' rowspan="{row_span}"'
            if col_span > 1:
                attrs += f' colspan="{col_span}"'
            rendered.append(f"<{tag}{attrs}>{_fp_cell_html(text)}</{tag}>")
        lines.append("<tr>" + "".join(rendered) + "</tr>")
    lines.append(_FP_TABLE_CLOSE)
    return "".join(lines)
def _fp_cell_int(cell, name: str, default: int) -> int:
    value = getattr(cell, name, None)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
def _fp_cell_html(text: str) -> str:
    escaped = _html.escape(text.strip(), quote=False)
    for raw in ("\r\n", "\r", "\n"):
        escaped = escaped.replace(raw, _CELL_LINE_BREAK)
    return escaped
def _fp_docling_blocks(document) -> list:
    blocks: list = []
    pending: list = []
    def push(kind: str, text: str, item) -> None:
        blocks.append(
            Block(kind=kind, text=text, section=0, origin=tuple(pending) + (item,))
        )
        pending.clear()
    for entry in document.iterate_items():
        item = entry[0] if isinstance(entry, tuple) else entry
        if getattr(getattr(item, "data", None), "table_cells", None) is not None:
            html = _fp_table_html(item)
            if html:
                push("table", html, item)
            else:
                pending.append(item)
            continue
        text = getattr(item, "text", "")
        text = text.strip() if isinstance(text, str) else ""
        if text:
            push("paragraph", text, item)
        else:
            pending.append(item)
    if pending and blocks:
        blocks[-1] = replace(
            blocks[-1], origin=_extend_origin(blocks[-1].origin, tuple(pending))
        )
    return blocks
def _fp_langchain_blocks(documents) -> list:
    blocks: list = []
    pending: list = []
    for document in documents:
        text = getattr(document, "page_content", "")
        lines = [line.strip() for line in text.splitlines()] if isinstance(text, str) else []
        lines = [line for line in lines if line]
        if not lines:
            pending.append(document)
            continue
        for line in lines:
            blocks.append(
                Block(
                    kind="paragraph",
                    text=line,
                    section=0,
                    origin=tuple(pending) + (document,),
                )
            )
            pending = []
    if pending and blocks:
        blocks[-1] = replace(
            blocks[-1], origin=_extend_origin(blocks[-1].origin, tuple(pending))
        )
    return blocks
def _fp_langchain_payload(chunks: list):
    payload = []
    for chunk in chunks:
        source = chunk.origin[0] if chunk.origin else None
        if source is None or not hasattr(source, "metadata"):
            return None
        try:
            payload.append(type(source)(page_content=chunk.text, metadata=dict(source.metadata)))
        except Exception:
            return None
    return payload
def _fp_outline_chunks(document, kwargs: dict, source: str = _FP_SRC_DOCLING):
    mode = _fp_choice_kwarg(
        kwargs.get("outline_mode"), _OUTLINE_AUTO, _OUTLINE_MODES, "outline_mode"
    )
    if mode == _OUTLINE_OFF:
        return None
    try:
        blocks = (
            _fp_langchain_blocks(document)
            if source == _FP_SRC_LANGCHAIN
            else _fp_docling_blocks(document)
        )
    except Exception as exc:
        _log_warning(
            "outline adapter failed - using the vendor chunker",
            event="final_preprocess_outline_skipped",
            error_code="05-00020003",
            error_type=type(exc).__name__,
        )
        return None
    if not blocks:
        return None
    resolved = _detect_outline_mode(blocks) if mode == _OUTLINE_AUTO else mode
    if resolved == _OUTLINE_OFF:
        return None
    annotated = annotate_outline(blocks, resolved)
    if not any(block.outline_level for block in annotated):
        return None
    options = ChunkOptions(
        max_chars=_int_kwarg(kwargs.get("chunk_size"), _DEFAULT_MAX_CHARS, "chunk_size"),
        overlap_chars=_int_kwarg(
            kwargs.get("chunk_overlap"), _DEFAULT_OVERLAP_CHARS, "chunk_overlap"
        ),
        outline_break_level=(
            _DOC_BREAK_LEVEL if resolved == _OUTLINE_DOCUMENT else _LEVEL_ARTICLE
        ),
    )
    chunks = chunk_blocks(annotated, options)
    if not chunks:
        return None
    if any(not chunk.origin for chunk in chunks):
        _log_warning(
            "outline chunks lost their source items - using the vendor chunker",
            event="final_preprocess_outline_skipped",
            error_code="05-00020003",
        )
        return None
    return chunks
def _fp_chunk_page(items) -> int:
    for item in items:
        prov = getattr(item, "prov", None)
        if prov:
            return getattr(prov[0], "page_no", 0) or 0
    return 0
def _fp_recursive_payload(chunks: list) -> list:
    return [
        {
            "text": chunk.text,
            "page_no": _fp_chunk_page(chunk.origin),
            "doc_items": list(chunk.origin),
        }
        for chunk in chunks
    ]
def _fp_docchunk_payload(chunks: list, document):
    doc_chunk = globals().get("DocChunk")
    doc_meta = globals().get("DocMeta")
    if doc_chunk is None or doc_meta is None:
        _log_warning(
            "docling chunk types are unavailable - using the vendor chunker",
            event="final_preprocess_outline_skipped",
            error_code="05-00020003",
        )
        return None
    origin = getattr(document, "origin", None)
    payload = []
    for chunk in chunks:
        items = list(chunk.origin)
        try:
            meta = doc_meta(doc_items=items, origin=origin)
        except Exception:
            meta = doc_meta(doc_items=items)
        payload.append(doc_chunk(text=chunk.text, meta=meta))
    return payload
def _fp_count_pages(owner, payload: list, reset: bool) -> None:
    if reset or not isinstance(getattr(owner, "page_chunk_counts", None), _FPPageCounts):
        owner.page_chunk_counts = _FPPageCounts(
            () if reset else (getattr(owner, "page_chunk_counts", None) or {})
        )
    counts = owner.page_chunk_counts
    for entry in payload:
        if isinstance(entry, dict):
            page = entry["page_no"]
        elif hasattr(entry, "metadata"):
            page = entry.metadata.get("page", 0)
        else:
            page = _fp_chunk_page(entry.meta.doc_items)
        counts[page] = counts[page] + 1
def _fp_install_outline_chunker(owner, label: str, *, reset_page_counts: bool,
                                honor_chunker_type: bool,
                                source: str = _FP_SRC_DOCLING) -> None:
    if owner is None or getattr(owner, "_fp_outline_installed", False):
        return
    original = getattr(owner, "split_documents", None)
    if original is None:
        _log_warning(
            "vendor processor has no split_documents - outline chunking is off",
            event="final_preprocess_outline_skipped",
            error_code="05-00020003",
            status=label,
        )
        return
    def split_documents(document, **kwargs):
        chunks = _fp_outline_chunks(document, kwargs, source)
        if chunks is None:
            return original(document, **kwargs)
        if source == _FP_SRC_LANGCHAIN:
            payload = _fp_langchain_payload(chunks)
        elif honor_chunker_type and kwargs.get("chunker_type", "recursive") == "recursive":
            payload = _fp_recursive_payload(chunks)
        else:
            payload = _fp_docchunk_payload(chunks, document)
        if not payload:
            return original(document, **kwargs)
        _fp_count_pages(owner, payload, reset=reset_page_counts)
        _log_info(
            "statute outline chunking applied",
            event="final_preprocess_outline",
            status=label,
            item_count=len(payload),
        )
        return payload
    owner.split_documents = split_documents
    owner._fp_outline_installed = True
def _fp_enable_outline(processor) -> None:
    _fp_install_outline_chunker(
        processor,
        "pdf",
        reset_page_counts=False,
        honor_chunker_type=False,
        source=_FP_SRC_LANGCHAIN,
    )
    _fp_install_outline_chunker(
        getattr(processor, "docx_processor", None),
        "docx",
        reset_page_counts=True,
        honor_chunker_type=True,
    )
def _fp_resolve_config_path(engine: str, explicit):
    for candidate in (explicit, os.environ.get(_FP_CONFIG_ENV[engine], "")):
        text = str(candidate or "").strip()
        if not text:
            continue
        if os.path.isfile(text):
            return text
        _log_warning("configured vendor config path does not exist - trying the next candidate",
                     event="final_preprocess_config_missing")
    vendor_resolver = globals().get("_resolve_default_attachment_config_path")
    if vendor_resolver is not None:
        try:
            vendor_path = vendor_resolver()
        except Exception:
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
    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = config_path
        self._hwpx = HwpxDocumentProcessor()
        self._vendor: dict = {}
        self._vendor_lock = None
        failure = _fp_engine_error(_FP_ATTACH)
        if failure is not None:
            _log_warning(
                f"{_FP_ATTACH} preprocessing path unavailable",
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
        except Exception as exc:
            if hwpx_engine == _FP_ENGINE_NATIVE or _fp_engine_error(_FP_ATTACH) is not None:
                raise
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
        records = await processor(request, file_path, **_fp_forward_kwargs(kwargs))
        _debug_dump(file_path, records, engine=engine)
        return records
    async def _acquire(self, engine: str, config_path_kwarg=None):
        existing = self._vendor.get(engine)
        if existing is not None:
            return existing
        failure = _fp_engine_error(engine)
        if failure is not None:
            raise FinalPreprocessorError(
                f"'{engine}' 전처리 경로를 사용할 수 없어 이 형식은 처리할 수 없습니다"
                f" ({type(failure).__name__}: {failure})"
            )
        if self._vendor_lock is None:
            self._vendor_lock = asyncio.Lock()
        async with self._vendor_lock:
            if self._vendor.get(engine) is None:
                started = time.monotonic()
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
        factory = AttachDocumentProcessor
        try:
            processor = factory(resolved) if resolved else factory()
        except Exception as exc:
            raise FinalPreprocessorError(
                f"'{engine}' 전처리기를 초기화하지 못했습니다({type(exc).__name__}): {exc}"
            ) from exc
        _fp_enable_outline(processor)
        return processor
