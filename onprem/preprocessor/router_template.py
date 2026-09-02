"""`final_preprocessor.py` 의 PART 3 — 라우터 원문.

**이 파일은 그 자체로 동작하지 않는다.** `AttachDocumentProcessor`(PART 1) ·
`HwpxDocumentProcessor`·`_log_info`·`_log_warning`(PART 2) 이 같은 네임스페이스에
있다는 전제로 쓰였고, 그 둘은 병합 단계에서 앞에 붙는다. 여기 따로 두는 이유는
하나다 — **라우터를 문자열로 들고 있으면 문법 검사도 편집기도 못 도와준다.**
빌드가 표식 줄 아래를 그대로 잘라 붙인다.

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
_FP_ATTACH = "attach"
_FP_ENGINES = (_FP_HWPX, _FP_ATTACH)

_FP_ENGINE_AUTO = "auto"
_FP_ENGINE_NATIVE = "native"
_FP_HWPX_ENGINES = (_FP_ENGINE_AUTO, _FP_ENGINE_NATIVE, _FP_ATTACH)

_FP_HWPX_EXTENSIONS = (".hwpx",)
_FP_ZIP_MAGIC = b"PK\x03\x04"
_FP_HWPX_MIMETYPE = b"application/hwp+zip"
_FP_SECTION_PREFIX = "Contents/section"

# ---------------------------------------------------------------------------
# 확장자 → 엔진.
#
# **2026-09-01 에 지능형이 빠지면서 이 표가 한 줄이 됐다.** 그전에는 pdf·ppt·엑셀·
# 이미지가 지능형으로 갔다(docling layout + TableFormer + OCR). 그 경로가 실환경에서
# 동작하지 않아 걷어냈고, 지금은 hwpx 가 아닌 것이 **전부 첨부용**으로 간다.
#
# **대가를 알고 있어야 한다**: 첨부용 pdf 경로는 `PyMuPDFLoader` 평문 + 문자 수 분할
# 이라 **표 구조가 남지 않는다.** 오류는 나지 않고 적재도 되므로, 그 사실은 "표를
# 물어봤는데 답이 이상하다" 로만 드러난다. 지능형이 고쳐지면 되살릴 자리는
# `build_final_preprocessor.py` 와 이 표다.
#
# 여기 없는 확장자는 `_FP_DEFAULT_ENGINE` 으로 간다.
# ---------------------------------------------------------------------------
_FP_ROUTES = {
    # 우리 파서 — 표 병합·조문 위계를 지킨다
    ".hwpx": _FP_HWPX,
}
# 나머지 전부. 첨부용 `__call__` 이 확장자별로 갈라 받는다 — `.hwp`·`.hml` 은 GenosHwp
# SDK, `.docx` 는 GenosMsWord 네이티브, 오디오는 Whisper STT, `.csv`·`.xlsx` 는
# TabularLoader, `.ppt(x)` 는 PDF 변환 후 docling, 나머지는 langchain 로더다.
_FP_DEFAULT_ENGINE = _FP_ATTACH

# 라우터가 자기 몫으로 받는 값. 벤더 처리기로 **넘기기 전에 뺀다** — 그대로 넘기면
# 벤더가 `kwargs: {...}` 로 통째로 로그에 찍고, 언젠가 같은 이름을 쓰면 조용히 겹친다.
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

    **2026-09-01 이전에는 여기가 두 갈래였다** — 지능형이 함께 있던 시절 첨부용은 본문이
    같아 지운 정의 13개를 지능형 판본에서 빌려 썼고, 그래서 지능형 절반이 없으면 첨부용
    코드가 `NameError` 로 죽었다. 지금은 첨부용이 자기 정의를 전부 들고 있어 그 얽힘이
    없다 — 첨부용의 가부는 첨부용 적재 결과 하나로 정해진다.
    """
    if engine == _FP_ATTACH:
        return _FP_ATTACH_IMPORT_ERROR
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
    if hwpx_engine == _FP_ATTACH:
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


# ---------------------------------------------------------------------------
# 조/항/호 위계를 **벤더 경로(pdf·docx)에도** 태운다
#
# ## 원본 문서 모양이 **둘**이다 (2026-09-01)
#
# 지능형이 있던 시절에는 pdf 도 `DoclingDocument` 였다. 지능형을 걷어내면서 pdf 가
# 첨부용으로 갔고, 그쪽 최상위 경로는 **langchain `Document` 목록**을 주고받는다
# (`attach_processor.py:2254-2296`, `PyMuPDFLoader` 산출물). 그래서 어댑터가 둘이다:
#
# | 자리 | 들어오는 것 | 나가는 것 | 어댑터 |
# |---|---|---|---|
# | 첨부용 최상위 (pdf·이미지·txt·md) | `list[Document]` | `list[Document]` | `_fp_langchain_blocks` |
# | 첨부용 `docx_processor` | `DoclingDocument` | dict 또는 `DocChunk` | `_fp_docling_blocks` |
#
# **가운데(위계 판정·조 경계 청킹)는 하나다.** `Block` 으로 옮기고 나면 어느 쪽에서
# 왔는지 알 필요가 없다 — 갈라지는 것은 입구의 어댑터와 출구의 payload 조립뿐이다.
#
# ## 왜 여기서 되는가
#
# 위계 층은 hwpx 를 모른다 — `annotate_outline`·`chunk_blocks` 는 `Block(kind, text,
# section)` 만 본다. hwpx 전용인 것은 `parse()` 하나다. 그래서 **벤더 문서를 블록으로
# 옮기기만 하면** 조 경계 청킹·`제2장 총칙 > 제5조(목적)` 머리말·표 분할이 그대로 돈다.
#
# ## 어디에 끼우나 — 벤더의 **청커만** 갈아 끼운다
#
# 두 벤더가 같은 3단이다: `load_documents() → split_documents() → compose_vectors()`.
# 우리는 가운데만 바꾼다. `compose_vectors` 를 그대로 두는 것이 요점이다 — 그쪽이
# bbox·이미지 업로드·**민감정보 마스킹(#315)**·페이지 카운트를 붙인다. 우회하면 그
# 값들이 조용히 사라지고, 레코드는 멀쩡해 보인다.
#
# 그래서 청크가 **어느 원본 항목에서 나왔는지**를 잃으면 안 된다. `Block.origin` /
# `Chunk.origin` 이 그 값을 실어 나른다(hwpx 경로에서는 언제나 비어 있다).
#
# ## 언제 켜지나
#
# `outline_mode` 하나로 hwpx 와 같이 움직인다. 기본 `auto` 는 `제N조` 표기를 **2개 이상**
# 세었을 때만 켜므로, **조문 문서가 아닌 pdf·docx 의 산출물은 벤더 청커 그대로다.**
# 일반 문서에 사다리를 걸면 `1.`·`가.` 목록이 전부 제목으로 승격돼 지금보다 나빠진다.
#
# 판정은 **kwargs 와 문서 내용만** 본다. 처리기 인스턴스는 요청 사이에 공유되므로,
# "이번 요청에는 켜라" 를 인스턴스 속성에 적으면 동시 요청끼리 서로의 설정을 본다.
#
# ## 되짚을 수 없으면 **벤더 청커로 돌아간다**
#
# 어댑터가 실패하든 출처가 비든, 이 경로는 예외를 올리지 않는다. 조문 위계는 있으면
# 좋은 것이고 적재는 되어야 하는 것이다 — 여기서 죽으면 그 문서가 검색에서 통째로
# 사라진다(hwpx 폴백 규약과 같다). 다만 **조용히 넘기지 않는다.**
# ---------------------------------------------------------------------------

# 벤더 표는 머리행 표시가 있다(`column_header`). 없으면 hwpx 와 같은 최소 가정 —
# 첫 행을 머리행으로 본다. 조각마다 머리행을 반복하는 것이 표 분할의 요점인데,
# 표시가 없으면 그 반복이 데이터 행으로 읽힌다.
_FP_TABLE_OPEN = "<table><tbody>"
_FP_TABLE_CLOSE = "</tbody></table>"

# 어느 어댑터를 태울지. **처리기마다 고정**이고 요청마다 바뀌지 않는다 — 설치할 때 정한다.
_FP_SRC_DOCLING = "docling"
_FP_SRC_LANGCHAIN = "langchain"


class _FPPageCounts(dict):
    """`compose_vectors` 가 `counts[page]` 로 바로 읽는다 — 없는 키에서 죽지 않는다.

    벤더는 `defaultdict(int)` 를 쓰지만 그 이름은 벤더 조각 **안**에서 import 되므로
    (그 조각은 실패할 수 있다) 라우터가 기댈 수 없다. 키가 하나라도 어긋나면
    `KeyError` 로 적재 전체가 죽는데, 그건 우리가 만들어 낸 실패다.
    """

    def __missing__(self, key):
        return 0


def _fp_table_html(item) -> str:
    """docling `TableItem` → **한 줄 HTML 표**. 못 만들면 빈 문자열.

    형태는 hwpx `_table_html` 과 같다(`<table><tbody><tr><th>…`). 마크다운으로 내지
    않는 이유도 같다 — 검색 결과가 프롬프트로 조립될 때 개행이 뭉개지면 마크다운 표는
    **행 경계가 개행뿐**이라 표가 아니게 된다.

    **덮인 자리에는 칸을 내지 않는다.** 내면 그 행만 열이 하나 늘어난다.
    """
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
            # 같은 앵커가 두 번 오면 **뒤엣것을 버린다.** 격자를 늘리면 없던 열이 생긴다.
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
                rendered.append(f"<{tag}></{tag}>")  # 빈 칸도 자리를 지켜야 한다
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
    """셀 안 개행은 `<br>` 로. 개행을 그대로 두면 표가 한 줄이라는 규약이 깨진다."""
    escaped = _html.escape(text.strip(), quote=False)
    for raw in ("\r\n", "\r", "\n"):
        escaped = escaped.replace(raw, _CELL_LINE_BREAK)
    return escaped


def _fp_docling_blocks(document) -> list:
    """`DoclingDocument` → `Block` 목록. `origin` 에 **원본 항목 그 자체**를 담는다.

    ## 구역(`section`)은 전부 0 이다

    페이지를 구역으로 쓰면 안 된다 — `chunk_blocks` 가 구역이 바뀔 때 끊으므로 **페이지를
    걸친 조가 반으로 갈린다.** 조가 검색 단위라는 이 기능의 전제와 정면으로 어긋난다.

    ## 글자 없는 항목(그림 등)은 버리지 않고 **다음 블록에 얹는다**

    그 항목을 그냥 빼면 어느 청크에도 안 실리고, 벤더가 `doc_items` 로 붙이는
    **이미지 업로드가 통째로 빠진다.** 오류는 나지 않는다 — 그림이 없는 문서로 보일 뿐이다.
    """
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
        # 문서 끝에 남은 것은 앞으로 얹는다 — 뒤에 실을 블록이 없다.
        blocks[-1] = replace(
            blocks[-1], origin=_extend_origin(blocks[-1].origin, tuple(pending))
        )
    return blocks


def _fp_langchain_blocks(documents) -> list:
    """langchain `Document` 목록 → `Block` 목록. `origin` 에 원본 Document 를 담는다.

    첨부용 최상위 경로(pdf·이미지·txt·md)가 이 모양이다. `PyMuPDFLoader` 는 **페이지마다
    Document 하나**를 내고 본문은 개행이 든 평문이다 — 표 격자는 이 단계에 이미 없다
    (그것이 첨부용 pdf 의 한계이고 위계 청킹이 되돌릴 수 있는 것이 아니다).

    ## 줄 단위로 가른다

    `_match_statute` 가 `제5조(목적)`·`①`·`1.` 을 **줄 머리에서** 읽는다. 페이지를
    통째로 한 블록에 넣으면 조 표기가 문장 가운데 파묻혀 위계가 하나도 안 잡히고,
    그러면 이 경로는 벤더 청커를 이유 없이 갈아치우는 것이 된다.

    ## 구역(`section`)은 전부 0 이다

    페이지를 구역으로 쓰면 `chunk_blocks` 가 페이지 경계에서 끊어 **한 조가 반으로
    갈린다.** 조가 검색 단위라는 이 기능의 전제와 정면으로 어긋난다.
    """
    blocks: list = []
    pending: list = []
    for document in documents:
        text = getattr(document, "page_content", "")
        lines = [line.strip() for line in text.splitlines()] if isinstance(text, str) else []
        lines = [line for line in lines if line]
        if not lines:
            # 글자 없는 페이지도 버리지 않는다 — 그 Document 의 metadata(페이지 번호)가
            # 어느 청크엔가 실려야 `compose_vectors` 의 페이지 집계가 어긋나지 않는다.
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
    """첨부용 최상위 경로가 내는 모양 — langchain `Document` 목록. 못 만들면 `None`.

    **클래스를 이름으로 찾지 않고 원본에서 가져온다**(`type(source)`). 이 라우터는 벤더
    가드 **밖**이라 `Document` 라는 전역이 있다는 보장이 없고, 있어도 그것이 이 문서를
    만든 로더의 클래스라는 보장이 없다.

    metadata 는 **첫 원본의 사본**이다. 벤더가 `dict(doc.metadata)` 로 복사하는 것과
    같다 — 원본을 그대로 물리면 여러 청크가 한 dict 를 공유해 뒤에서 고친 값이 앞
    청크에도 보인다.
    """
    payload = []
    for chunk in chunks:
        # 첫 원본을 쓴다 — `_fp_chunk_page` 가 페이지를 고르는 식과 같다. 여러 페이지를
        # 걸친 청크는 **시작한 페이지**에 달린다.
        source = chunk.origin[0] if chunk.origin else None
        if source is None or not hasattr(source, "metadata"):
            return None
        try:
            payload.append(type(source)(page_content=chunk.text, metadata=dict(source.metadata)))
        except Exception:  # noqa: BLE001 - 모양이 다르면 벤더 청커로 돌아간다
            return None
    return payload


def _fp_outline_chunks(document, kwargs: dict, source: str = _FP_SRC_DOCLING):
    """위계로 다시 청킹한 `Chunk` 목록. **벤더 청커를 써야 하면 `None`.**"""
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
    except Exception as exc:  # noqa: BLE001 - 위계는 있으면 좋은 것이고 적재는 되어야 한다
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
        # 사다리를 못 찾았다(`document` 모드가 이렇게 끝날 수 있다). 위계가 하나도 없으면
        # 우리 청커는 길이 기준만 남아 **벤더 청킹을 이유 없이 갈아치우는 것**이 된다.
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
        # 여기까지 오면 origin 전파가 깨진 것이다. 그대로 내보내면 `compose_vectors` 가
        # `doc_items[0]` 에서 IndexError 로 죽어 **적재가 통째로 실패한다.**
        _log_warning(
            "outline chunks lost their source items - using the vendor chunker",
            event="final_preprocess_outline_skipped",
            error_code="05-00020003",
        )
        return None
    return chunks


def _fp_chunk_page(items) -> int:
    """이 청크의 페이지. 벤더 `compose_vectors` 와 **같은 식으로** 고른다(첫 항목)."""
    for item in items:
        prov = getattr(item, "prov", None)
        if prov:
            return getattr(prov[0], "page_no", 0) or 0
    return 0


def _fp_recursive_payload(chunks: list) -> list:
    """첨부용 `chunker_type="recursive"` 가 내는 모양 — 평범한 dict."""
    return [
        {
            "text": chunk.text,
            "page_no": _fp_chunk_page(chunk.origin),
            "doc_items": list(chunk.origin),
        }
        for chunk in chunks
    ]


def _fp_docchunk_payload(chunks: list, document):
    """`DocChunk` 목록. docling 이 없으면 `None`(벤더 청커로 돌아간다).

    **`headings` 를 채우지 않는다.** 두 벤더의 `compose_vectors` 가 그 값을 본문 앞에
    다시 붙이는데, 우리 청크 본문에는 조문 머리말이 **이미 들어 있다** — 채우면 같은
    제목이 두 번 실린다.
    """
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
        except Exception:  # noqa: BLE001 - 릴리스마다 선택 필드가 다르다
            meta = doc_meta(doc_items=items)
        payload.append(doc_chunk(text=chunk.text, meta=meta))
    return payload


def _fp_count_pages(owner, payload: list, reset: bool) -> None:
    """`compose_vectors` 가 읽는 페이지별 청크 수. **벤더의 초기화 습관을 그대로 따른다.**

    첨부용은 호출마다 새로 만들고 지능형은 생성자에서 한 번만 만든다(요청 사이에
    누적된다). 여기서 임의로 맞추면 우리가 안 건드린 경로와 값이 달라진다 — 이 코드가
    바꾸는 것은 **청크 경계뿐**이어야 한다.
    """
    if reset or not isinstance(getattr(owner, "page_chunk_counts", None), _FPPageCounts):
        owner.page_chunk_counts = _FPPageCounts(
            () if reset else (getattr(owner, "page_chunk_counts", None) or {})
        )
    counts = owner.page_chunk_counts
    for entry in payload:
        if isinstance(entry, dict):
            page = entry["page_no"]
        elif hasattr(entry, "metadata"):
            # langchain `Document` — 벤더가 `chunk.metadata.get('page', 0)` 로 읽는
            # 그 값이다(`attach_processor.py:2294`).
            page = entry.metadata.get("page", 0)
        else:
            page = _fp_chunk_page(entry.meta.doc_items)
        counts[page] = counts[page] + 1


def _fp_install_outline_chunker(owner, label: str, *, reset_page_counts: bool,
                                honor_chunker_type: bool,
                                source: str = _FP_SRC_DOCLING) -> None:
    """벤더 처리기의 `split_documents` 를 위계 청커로 감싼다(원본은 폴백으로 남는다).

    Args:
        honor_chunker_type: `DocxProcessor` 는 `chunker_type` 에 따라 청크 모양이
            **dict 이거나 `DocChunk`** 이고 `compose_vectors` 가 같은 분기로 읽는다.
        source: 그 `split_documents` 가 **무엇을 받는가**. `_FP_SRC_LANGCHAIN` 이면
            `list[Document]` 를 받고 같은 모양으로 돌려줘야 한다 — 첨부용 최상위
            경로(pdf·이미지·txt·md)가 그쪽이다.
    """
    if owner is None or getattr(owner, "_fp_outline_installed", False):
        return
    original = getattr(owner, "split_documents", None)
    if original is None:
        # 벤더가 그 이름을 안 쓰면 걸 자리가 없다. **적재를 막지 않는다** — 위계가 안
        # 붙을 뿐이고, 그 사실은 로그에 남는다(조용히 넘기면 왜 안 붙는지 알 수 없다).
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
    """만들어진 첨부용 처리기에 위계 청커를 건다 — **pdf 와 docx 두 자리다.**

    ## pdf 는 최상위 `split_documents` 를 지난다

    첨부용 `__call__` 은 확장자로 갈라 `.docx` 는 `docx_processor` 로, `.hwp` 계열은
    `hwp_processor` 로 보내고 **나머지(pdf·이미지·txt·md·json)는 자기 안에서**
    `load_documents → split_documents → compose_vectors` 를 돈다
    (`attach_processor.py:2544-2552`). 그래서 pdf 에 위계를 걸 자리가 최상위다.

    지능형이 있던 시절 pdf 는 `DoclingDocument` 였고 지금은 langchain `Document` 목록
    이라, **어댑터만 갈아 끼운다**(`source=_FP_SRC_LANGCHAIN`). 조 경계 청킹·머리말은
    같은 코드가 그대로 돈다.

    ## 최상위에 걸면 pdf 말고도 몇 갈래가 함께 지난다

    이미지·txt·md·json, 그리고 hwp/ppt 가 실패해 PDF 변환으로 폴백한 경로가 같은
    `split_documents` 를 쓴다. **`outline_mode="auto"` 가 `제N조` 를 2개 이상 세었을
    때만 켜지므로** 조문 문서가 아닌 그 갈래들은 벤더 청커 그대로다. 지능형에 걸 때와
    같은 근거이고, `statute` 를 명시하면 전부에 걸린다(그 선택은 등록자가 한 것이다).

    ## `hwp_processor` 에는 걸지 않는다

    요구 범위가 pdf·docx 다 — 닿는 자리를 넓히면 검증하지 않은 경로의 청킹까지 바뀐다.
    넣으려면 같은 줄을 하나 더 걸면 된다(그쪽도 `DoclingDocument` 를 받고
    `chunker_type` 분기가 있다).
    """
    _fp_install_outline_chunker(
        processor,
        "pdf",
        # 첨부용 최상위 `page_chunk_counts` 는 생성자에서 한 번만 만들어져 요청 사이에
        # 누적된다(`attach_processor.py:1979`). 여기서 임의로 비우면 우리가 안 건드린
        # 경로와 값이 달라진다.
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
    """벤더 설정 yaml 을 찾는다. 못 찾으면 `None`(벤더 기본 해석에 맡긴다).

    ## 첨부용도 yaml 을 쓴다 — 지능형 잔재가 아니다 (2026-09-01 정정)

    `AttachDocumentProcessor.__init__` 이 `_resolve_default_attachment_config_path()` →
    `_load_config()` 를 타고, 그 값에서 guardrail·whisper·tokenizer 설정을 꺼낸다
    (`attach_processor.py:1809`·`:1971`).

    **없으면 죽지 않는다.** `_load_config` 가 경고를 찍고 `{}` 를 돌려준다(`:293`) —
    그래서 "yaml 을 안 올려도 돈다" 는 사실이다. 그런데 그때 이렇게 떨어진다:

        guardrail.url            → ""      민감정보 마스킹(#315)이 **빠진다**
        guardrail.masking_enabled → False   〃
        whisper.url              → 하드코딩 IP
        chunking.tokenizer_path  → 기본값   청크 경계가 달라진다

    **그것이 이 탐색이 있는 이유다.** 벤더 resolver 는 `Path(__file__)/../resource/…` 를
    보는데 우리 합친 파일은 벤더 파일과 **다른 자리에 놓일 수 있다.** 그러면 이미지에
    yaml 이 있는데도 못 찾고 위 표대로 조용히 떨어진다 — 오류가 나지 않아 "마스킹이 왜
    안 되나" 로만 드러난다.

    옛 주석은 "**한 자리만 보고 죽지 않게**" 라고 적어 뒀는데 **그건 지능형 판본 기준**
    이었다(그쪽 `_load_config` 는 예외를 던졌다). 첨부용은 죽는 것이 아니라 **조용히
    기본값으로 간다** — 더 나쁜 실패 형태이고, 탐색을 지울 이유가 아니라 남길 이유다.

    등록 파일이 어디에 놓이는지 실물로 확인하지 못했으므로 후보를 넷 둔다.
    """
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
    """GenOS 가 실행하는 진입점 — 확장자와 **내용**을 보고 두 처리기 중 하나로 보낸다.

    `docs/GENOS_RULES.md` §F 계약 그대로다: 인자 없이 생성 가능하고, `__call__` 은
    비동기이며 `text` 키를 가진 dict 목록을 돌려주거나 예외를 던진다.
    """

    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = config_path
        # hwpx 처리기는 지금 만든다 — 표준 라이브러리 + lxml 뿐이라 비용이 없다.
        self._hwpx = HwpxDocumentProcessor()
        # 첨부용은 **그 엔진으로 갈 파일이 처음 들어올 때** 만든다. 생성자가 yaml 을
        # 읽고 토크나이저·docling 변환기를 올리기 때문에, 여기서 만들면 hwpx 만 넣는
        # 배포도 그 비용과 실패 가능성을 함께 진다.
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
        records = await processor(request, file_path, **_fp_forward_kwargs(kwargs))
        # [임시 · 확인용] hwpx_preprocessor.py 맨 아래 `_debug_dump` 블록과 함께 지운다.
        # **hwpx 경로에는 걸지 않는다** — 그쪽은 `HwpxDocumentProcessor.__call__` 이
        # 이미 찍으므로 여기서 또 부르면 한 문서가 두 번 나온다.
        _debug_dump(file_path, records, engine=engine)
        return records

    async def _acquire(self, engine: str, config_path_kwarg=None):
        existing = self._vendor.get(engine)
        if existing is not None:
            return existing

        failure = _fp_engine_error(engine)
        if failure is not None:
            # 빈 목록을 돌려주지 않는다 — 그러면 "내용이 없는 문서" 와 구별되지 않는다.
            raise FinalPreprocessorError(
                f"'{engine}' 전처리 경로를 사용할 수 없어 이 형식은 처리할 수 없습니다"
                f" ({type(failure).__name__}: {failure})"
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
        factory = AttachDocumentProcessor
        try:
            processor = factory(resolved) if resolved else factory()
        except Exception as exc:  # noqa: BLE001
            # 설정 파일 부재는 **재시도로 풀리지 않는 배포 문제**다. 원래 예외
            # (FileNotFoundError 등)만 올리면 어느 파일이 없다는 건지 드러나지 않아
            # 몇 번을 다시 눌러도 같은 자리에서 실패한다.
            raise FinalPreprocessorError(
                f"'{engine}' 전처리기를 초기화하지 못했습니다({type(exc).__name__}): {exc}"
            ) from exc
        # 조문 위계 청커는 **만들어진 뒤에** 건다. 생성에 실패하면 걸 대상이 없다.
        _fp_enable_outline(processor)
        return processor
