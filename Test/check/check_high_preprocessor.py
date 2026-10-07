<<<<<<< HEAD:Test/check/check_dev_preprocessor.py
"""`final/preprocessor/dev_preprocessor.py` pdf · hwp 경로 점검 — 단 순서 · 문단 복원 · 머리말 · 병합 표.
=======
"""`final/preprocessor/high_preprocessor.py` pdf 경로 점검 — 단 순서 · 문단 복원 · 머리말.
>>>>>>> refs/remotes/origin/main:Test/check/check_high_preprocessor.py

`python Test/check/check_high_preprocessor.py`

## 무엇을 보는가

pdf 는 줄 좌표만 있고 문단이 없다. 그래서 **원문 문단을 알고 있는 pdf 를 여기서 만들어**
(PyMuPDF 내장 한글 글꼴) 다시 읽었을 때 문단이 하나씩, 원래 순서대로 나오는지 본다.
글자를 글자 단위로 꺾어 조판하므로 줄 끝이 단을 거의 채운다(양쪽 맞춤과 같은 모양).

1. **1단 조문** — 조/항/호 표기가 문단을 열고, 쪽을 넘는 조문이 한 문단으로 이어진다.
   `…있` / `다. …` 로 꺾인 줄은 목 표기(`다.`)가 아니라 이음이다. 조 경계에서 청크가 끊긴다.
2. **2단** — 전폭 제목 · 초록이 단보다 먼저, 좌 · 우 단이 섞이지 않고, 단 · 쪽을 넘는
   문단이 이어진다. 가운데 전폭 표는 표 블록으로 제자리에 선다.
3. **3단** — 같은 판정을 단 셋으로.
4. **스캔 pdf OCR** — 1단 조문을 쪽마다 이미지로 바꾼 pdf 를 로컬 대역 OCR 서버(지능형과
   같은 요청 · 응답 모양)로 읽어, 텍스트 레이어 판과 같은 문단이 나오는지 본다. 텍스트
   레이어가 있는 쪽은 서버에 보내지 않고, 서버 실패 · 오류 응답은 문서를 세운다.
5. **스캔 OCR 미룸 (`ocr_defer`)** — 첨부 경로. 전처리기가 스캔 쪽을 PNG(NFS) + 표식으로
   남기고, MCP `genon_ocr` 가 그 쪽들을 대역 OCR 서버로 읽어 **텍스트 레이어 판과 같은
   문단**(1 · 2 · 3단, 되풀이 머리말 제거, 쪽을 넘는 문단 잇기)을 내는지 본다. 청크 겹침이
   표식을 자르지 않는지, NFS 루트 밖 · 루트 없음은 세우는지, 원본이 지워졌거나 서버가
   실패하면 `ok=false` 인지, 스텝 사본(번역 스텝 1)이 표식을 바꾸고 실패를 오류로 내는지.
6. **hwp** — 리더(GenosHwp SDK)는 온프레미스 이미지에만 있어 `_hwp_convert` 자리에 대역을
   꽂고 docling_core 로 만든 `DoclingDocument` 를 돌려준다. 병합 칸이 **한 번만** 실리는지
   (덮인 자리에 같은 칸이 또 와도), 조/항/호 · 목록 번호 · 쪽 필드, 표 칸 안 항목이 문단으로
   또 나오지 않는지, SDK 실패 · 빈 결과 → 레거시 폴백, 둘 다 실패 · 리더 없음 → 세운다.
   docling_core 가 없으면 건너뛴다(건수가 줄어 EXPECTED 가 잡는다).
7. **실물 `Test/data/preprocessor/01.pdf`**(2단 OCR 논문) — **있을 때만** 탄다. 없으면
   건수가 줄어 `run_all` 의 EXPECTED 가 잡는다.

머리말 · 쪽번호는 세 합성 문서 모두 쪽마다 찍혀 있고 본문에 남으면 FAIL 이다.
스캔 쪽의 그림 속 OCR 글자 조각은 보지 않는다(보류된 범위다).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import random
import re
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import MCP_DIR, PDF_SAMPLES_DIR, PREPROC_DIR, WORKFLOW_DIR  # noqa: E402

sys.path.insert(0, PREPROC_DIR)
logging.disable(logging.CRITICAL)

import pymupdf  # noqa: E402

import high_preprocessor as dp  # noqa: E402

_SAMPLE_01 = os.path.join(PDF_SAMPLES_DIR, "01.pdf")

_WIDTH, _HEIGHT = 595.0, 842.0
_MARGIN = 50.0
_TOP, _BOTTOM = 90.0, 780.0
_SIZE, _LEAD = 9.0, 14.0
_INDENT = 9.0
_HEADER = "사내 복무 규정 (2026 개정판)"
_FONT = pymupdf.Font("korea")

_WORDS = (
    "대학의 기술이전은 연구성과를 사회로 환원하는 과정이며 기업과 연구기관이 함께 참여하는 "
    "협력체계를 전제로 한다 이러한 체계는 제도와 조직 그리고 인력의 뒷받침이 있어야 작동하고 "
    "지원기구의 역할이 분명해야 성과가 쌓인다 연구공원 입주기업은 교수와 학생의 기술을 바탕으로 "
    "창업하며 보육센터는 공간과 자문을 제공한다"
).split()


class Report:
    def __init__(self) -> None:
        self.checks = 0
        self.failures: list = []

    def expect(self, ok: bool, label: str, detail: str = "") -> None:
        self.checks += 1
        if ok:
            print(f"[OK  ] {label}")
        else:
            self.failures.append(label)
            print(f"[FAIL] {label}  {detail[:300]}")


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _sentences(rng: random.Random, count: int) -> str:
    out = []
    for _ in range(count):
        words = [rng.choice(_WORDS) for _ in range(rng.randint(6, 12))]
        out.append(" ".join(words) + "다.")
    return " ".join(out)


def _wrap(text: str, first_width: float, width: float) -> list:
    """글자 단위로 꺾는다. 줄 머리 공백은 버린다."""
    lines, current, limit = [], "", first_width
    for char in text:
        if not current and char == " ":
            continue
        if _FONT.text_length(current + char, _SIZE) > limit:
            lines.append(current.rstrip())
            current, limit = ("" if char == " " else char), width
            continue
        current += char
    if current.strip():
        lines.append(current.rstrip())
    return lines


class Flow:
    """단 조판기. 문단은 단 → 다음 단 → 다음 쪽으로 흐르고, 전폭 요소는 띠를 가른다."""

    def __init__(self, columns: int, gutter: float = 24.0) -> None:
        self.doc = pymupdf.open()
        self.columns = columns
        self.col_width = (_WIDTH - 2 * _MARGIN - gutter * (columns - 1)) / columns
        self.gutter = gutter
        self.page = None
        self._new_page()

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=_WIDTH, height=_HEIGHT)
        self.page.insert_font(fontname="kr", fontbuffer=_FONT.buffer)
        number = self.doc.page_count
        self._text(_MARGIN, 40, _HEADER, 8)
        self._text(_WIDTH / 2 - 10, 815, f"- {number} -", 8)
        self.band_top = self.y = self.band_max = _TOP
        self.column = 0

    def _text(self, x: float, y: float, text: str, size: float = _SIZE) -> None:
        self.page.insert_text((x, y), text, fontname="kr", fontsize=size)

    def _x(self) -> float:
        return _MARGIN + self.column * (self.col_width + self.gutter)

    def _advance(self) -> None:
        if self.column + 1 < self.columns:
            self.column += 1
            self.y = self.band_top
        else:
            self._new_page()

    def paragraph(self, text: str, indent: bool = True, size: float = _SIZE, gap: float = 0.0) -> list:
        """→ 이 문단이 놓인 쪽 번호(0-based) 목록."""
        self.y += gap
        first = self.col_width - (_INDENT if indent else 0)
        pages = []
        for index, line in enumerate(_wrap(text, first, self.col_width)):
            if self.y + _LEAD > _BOTTOM:
                self._advance()
            x = self._x() + (_INDENT if indent and index == 0 else 0)
            self._text(x, self.y + _LEAD, line, size)
            self.y += _LEAD
            self.band_max = max(self.band_max, self.y)
            if self.doc.page_count - 1 not in pages:
                pages.append(self.doc.page_count - 1)
        return pages

    def lines(self, lines: list) -> None:
        """줄을 그대로 싣는다 — 꺾이는 자리를 정해야 하는 판정용."""
        for line in lines:
            if self.y + _LEAD > _BOTTOM:
                self._advance()
            self._text(self._x(), self.y + _LEAD, line)
            self.y += _LEAD
            self.band_max = max(self.band_max, self.y)

    def wide_text(self, text: str, size: float = _SIZE) -> None:
        width = _WIDTH - 2 * _MARGIN
        wrapped = _wrap(text, width, width)
        top = self._room(len(wrapped) * _LEAD * size / _SIZE)
        for line in wrapped:
            self._text(_MARGIN, top + _LEAD, line, size)
            top += _LEAD * size / _SIZE
        self._reband(top + _LEAD)

    def wide_table(self, rows: list) -> None:
        width = _WIDTH - 2 * _MARGIN
        height = 20.0
        top = self._room(len(rows) * height + _LEAD)
        cell_w = width / len(rows[0])
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                rect = pymupdf.Rect(_MARGIN + c * cell_w, top + r * height,
                                    _MARGIN + (c + 1) * cell_w, top + (r + 1) * height)
                self.page.draw_rect(rect, color=(0, 0, 0), width=0.6)
                self._text(rect.x0 + 4, rect.y0 + 14, cell)
        self._reband(top + len(rows) * height + _LEAD)

    def _room(self, height: float) -> float:
        """전폭 요소가 놓일 y. 이 쪽에 안 들어가면 다음 쪽 맨 위다."""
        top = self.band_max + (_LEAD if self.band_max > _TOP else 0)
        if top + height > _BOTTOM:
            self._new_page()
            top = _TOP
        return top

    def _reband(self, top: float) -> None:
        self.band_top = self.y = self.band_max = top
        self.column = 0

    def save(self) -> str:
        handle, path = tempfile.mkstemp(suffix=".pdf")
        os.close(handle)
        self.doc.save(path)
        self.doc.close()
        return path


def _texts(blocks: list) -> list:
    return [_norm(block.text) for block in blocks]


def _check_order(rep: Report, tag: str, blocks: list, expected: list) -> None:
    got = _texts(blocks)
    want = [_norm(text) for text in expected]
    rep.expect(got == want, f"[{tag}] 문단이 원문과 하나씩 · 같은 순서로 나온다",
               f"블록 {len(got)} / 원문 {len(want)} — 첫 차이: "
               + next((f"#{i} {g[:60]} ≠ {w[:60]}" for i, (g, w) in enumerate(zip(got, want)) if g != w),
                      "길이만 다름"))


def _check_running(rep: Report, tag: str, blocks: list) -> None:
    joined = " ".join(block.text for block in blocks)
    rep.expect(_norm(_HEADER) not in _norm(joined), f"[{tag}] 머리말이 본문에 없다")
    rep.expect(not re.search(r"-\s*\d+\s*-", joined), f"[{tag}] 쪽번호가 본문에 없다")


def _page_spanning(blocks: list) -> list:
    return [block for block in blocks if len({source.page for source in block.origin}) > 1]


def case_statute(rep: Report) -> None:
    rng = random.Random(1)
    flow = Flow(columns=1)
    expected = []
    articles = []
    for number in range(1, 13):
        head = f"제{number}조(규정 {number}) " + _sentences(rng, rng.randint(2, 5))
        flow.paragraph(head, indent=False)
        expected.append(head)
        articles.append(f"제{number}조")
        for mark in "①②":
            item = f"{mark} " + _sentences(rng, rng.randint(1, 3))
            flow.paragraph(item, indent=False)
            expected.append(item)
        for sub in (1, 2):
            item = f"{sub}. " + _sentences(rng, 1)
            flow.paragraph(item, indent=False)
            expected.append(item)
        if number == 3:
            # `…있` 에서 꺾인 줄 다음의 `다.` 는 이음이다. 목 항목 `가.` 는 새 문단이다.
            filler = "연구공원의 운영은 보육센터와 기술이전기구가 함께 맡는 것을 원칙으로 하고 있"
            while _FONT.text_length(filler + "는", _SIZE) <= flow.col_width:
                filler = "그 " + filler
            flow.lines([filler, "다. 다만 위원회가 달리 정하면 그에 따른다."])
            expected.append(filler + "다. 다만 위원회가 달리 정하면 그에 따른다.")
            item = "가. 보육센터의 입주 심사는 위원회가 한다."
            flow.paragraph(item, indent=False)
            expected.append(item)
    pages = flow.doc.page_count
    path = flow.save()
    try:
        rep.expect(pages >= 3, "[1단 조문] 합성 문서가 3쪽 이상이다 (머리말 반복 판정의 전제)", str(pages))
        blocks = dp.parse_pdf(path)[0]
        _check_order(rep, "1단 조문", blocks, expected)
        _check_running(rep, "1단 조문", blocks)
        rep.expect(bool(_page_spanning(blocks)), "[1단 조문] 쪽을 넘는 문단이 한 블록으로 이어진다")
        ending = [b for b in blocks if "하고 있 다. 다만" in b.text or "하고있다.다만" in _norm(b.text)]
        rep.expect(len(ending) == 1, "[1단 조문] `…있` / `다.` 로 꺾인 줄은 한 문단이다")
        rep.expect(any(b.text.startswith("가. 보육센터") for b in blocks),
                   "[1단 조문] 문장 뒤의 목 표기 `가.` 는 새 문단을 연다")

        records = dp.DocumentProcessor()._process(path, save_images=False)[0]
        starts = [
            {m for m in re.findall(r"^(제\d+조)\(", r["text"], re.M)} for r in records
        ]
        rep.expect(all(len(s) <= 1 for s in starts), "[1단 조문] 청크 하나에 조 머리가 둘 이상 없다",
                   str(starts))
        rep.expect(set().union(*starts) == set(articles), "[1단 조문] 조 열둘이 전부 청크에 실린다",
                   str(sorted(set().union(*starts))))
        rep.expect(all(r["page_basis"] == "page" and r["i_page"] >= 1 for r in records),
                   "[1단 조문] 레코드 페이지가 pdf 쪽(1-based)이다")
    finally:
        os.remove(path)


def _columns_case(rep: Report, columns: int, tag: str, with_table: bool) -> None:
    rng = random.Random(columns)
    flow = Flow(columns=columns)
    expected = []
    title = "대학의 기술이전 체제 분석"
    flow.wide_text(title, size=14)
    expected.append(title)
    abstract = "요약 : " + _sentences(rng, 4)
    flow.wide_text(abstract)
    expected.append(abstract)
    for index in range(30 if columns == 2 else 40):
        text = _sentences(rng, rng.randint(3, 7))
        flow.paragraph(text)
        expected.append(text)
        if with_table and index == 17:
            rows = [["구분", "건수", "비율"], ["특허", "12", "40%"], ["실용신안", "18", "60%"]]
            flow.wide_table(rows)
            expected.append("<table>")
    pages = flow.doc.page_count
    path = flow.save()
    try:
        rep.expect(pages >= 3, f"[{tag}] 합성 문서가 3쪽 이상이다 (머리말 반복 판정의 전제)", str(pages))
        blocks = dp.parse_pdf(path)[0]
        tables = [i for i, b in enumerate(blocks) if b.kind == "table"]
        if with_table:
            position = expected.index("<table>")
            rep.expect(tables == [position], f"[{tag}] 전폭 표가 표 블록으로 제자리에 선다",
                       f"표 위치 {tables} / 기대 {position}")
            table = blocks[tables[0]] if tables else None
            rep.expect(table is not None and all(c in table.text for c in ("실용신안", "60%")),
                       f"[{tag}] 표 칸 글자가 표 블록에 있다", table.text[:200] if table else "")
            expected = [e for e in expected if e != "<table>"]
            blocks = [b for b in blocks if b.kind != "table"]
        else:
            rep.expect(not tables, f"[{tag}] 표가 없는 문서에서 표를 지어내지 않는다")
        _check_order(rep, tag, blocks, expected)
        _check_running(rep, tag, blocks)
        rep.expect(bool(_page_spanning(blocks)), f"[{tag}] 쪽을 넘는 문단이 한 블록으로 이어진다")
    finally:
        os.remove(path)


class _FakeOcr:
    """지능형이 부르는 Paddle OCR 서빙과 같은 모양으로 답하는 로컬 서버.

    `pages` 는 요청 순서대로 돌려줄 `[(글, 점수, (x0, y0, x1, y1) pt)]` 목록이다. 상자는
    요청의 dpi 로 픽셀 좌표로 바꿔 보낸다."""

    def __init__(self, pages: list, dpi: int, status: int = 200, error_code: int = 0) -> None:
        self.pages = list(pages)
        self.requests: list = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server 계약
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append(body)
                if status != 200:
                    self.send_response(status)
                    self.end_headers()
                    return
                items = owner.pages.pop(0) if owner.pages else []
                scale = dpi / 72.0
                pruned = {
                    "rec_texts": [text for text, _, _ in items],
                    "rec_scores": [score for _, score, _ in items],
                    "rec_boxes": [[round(v * scale) for v in box] for _, _, box in items],
                }
                payload = {"errorCode": error_code, "result": {"ocrResults": [{"prunedResult": pruned}]}}
                data = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = f"http://127.0.0.1:{self.server.server_address[1]}/ocr"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _page_line_items(page) -> list:
    items = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text:
                items.append((text, 0.98, tuple(line["bbox"])))
    return items


def _scanned_copy(path: str, keep_text_pages: int = 0) -> str:
    """쪽마다 이미지 한 장으로 바꾼 사본. 앞 `keep_text_pages` 쪽은 텍스트 레이어 그대로다."""
    source = pymupdf.open(path)
    out = pymupdf.open()
    for number, page in enumerate(source):
        if number < keep_text_pages:
            out.insert_pdf(source, from_page=number, to_page=number)
            continue
        target = out.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(target.rect, pixmap=page.get_pixmap(dpi=72))
    handle, scanned = tempfile.mkstemp(suffix=".pdf")
    os.close(handle)
    out.save(scanned)
    out.close()
    source.close()
    return scanned


def case_scanned(rep: Report) -> None:
    rng = random.Random(7)
    flow = Flow(columns=1)
    for number in range(1, 21):
        flow.paragraph(f"제{number}조(규정 {number}) " + _sentences(rng, rng.randint(3, 5)), indent=False)
        for mark in "①②":
            flow.paragraph(f"{mark} " + _sentences(rng, rng.randint(2, 4)), indent=False)
    path = flow.save()
    source = pymupdf.open(path)
    lines = [_page_line_items(page) for page in source]
    source.close()
    scanned = _scanned_copy(path)
    mixed = _scanned_copy(path, keep_text_pages=1)
    dpi = dp._PDF_OCR_DPI
    try:
        want = _texts(dp.parse_pdf(path)[0])
        rep.expect(len(lines) >= 3, "[스캔] 합성 문서가 3쪽 이상이다 (머리말 반복 판정의 전제)", str(len(lines)))
        rep.expect(not dp.parse_pdf(scanned)[0], "[스캔] OCR 없이는 스캔 쪽에서 글자가 안 나온다")

        server = _FakeOcr(lines, dpi)
        try:
            blocks = dp.parse_pdf(scanned, None, dp.PdfOcr(endpoint=server.endpoint))[0]
        finally:
            server.close()
        _check_order(rep, "스캔", blocks, want)
        _check_running(rep, "스캔", blocks)
        rep.expect(len(server.requests) == len(lines), "[스캔] 스캔 쪽마다 OCR 요청이 한 번씩 간다",
                   f"{len(server.requests)} / {len(lines)}")
        first = server.requests[0] if server.requests else {}
        png = base64.b64decode(first.get("file", "")) if first else b""
        rep.expect(first.get("fileType") == 1 and png.startswith(b"\x89PNG"),
                   "[스캔] 요청이 지능형과 같은 모양이다 (base64 PNG · fileType 1)")

        server = _FakeOcr(lines[1:], dpi)
        try:
            blocks = dp.parse_pdf(mixed, None, dp.PdfOcr(endpoint=server.endpoint))[0]
        finally:
            server.close()
        rep.expect(len(server.requests) == len(lines) - 1, "[스캔] 텍스트 레이어가 있는 쪽은 OCR 에 보내지 않는다",
                   f"{len(server.requests)} / {len(lines) - 1}")
        rep.expect(_texts(blocks) == want, "[스캔] 텍스트 쪽 + 스캔 쪽 섞인 문서도 원문 문단 그대로다")

        noisy = [page + [("잡음", 0.1, (60.0, 60.0, 90.0, 70.0))] for page in lines]
        server = _FakeOcr(noisy, dpi)
        try:
            blocks = dp.parse_pdf(scanned, None, dp.PdfOcr(endpoint=server.endpoint))[0]
        finally:
            server.close()
        rep.expect(not any("잡음" in block.text for block in blocks), "[스캔] 인식 점수가 낮은 상자는 버린다")

        for label, kwargs in (("HTTP 500", {"status": 500}), ("errorCode≠0", {"error_code": 7})):
            server = _FakeOcr(lines, dpi, **kwargs)
            try:
                dp.parse_pdf(scanned, None, dp.PdfOcr(endpoint=server.endpoint))
                raised = ""
            except dp.PreprocessError as exc:
                raised = str(exc)
            finally:
                server.close()
            rep.expect("OCR 에 실패" in raised, f"[스캔] OCR 서버 실패({label})는 문서를 세운다", raised)

        processor = dp.DocumentProcessor()
        try:
            processor._process(scanned, save_images=False, ocr=False)
            raised = ""
        except dp.PreprocessError as exc:
            raised = str(exc)
        rep.expect("본문 글자를 찾지 못했습니다" in raised, "[스캔] `ocr=False` 면 빈 결과가 아니라 예외다", raised)

        server = _FakeOcr(lines, dpi)
        try:
            records = processor._process(scanned, save_images=False, ocr_endpoint=server.endpoint)[0]
        finally:
            server.close()
        rep.expect(bool(records) and all(r["page_basis"] == "page" and r["i_page"] >= 1 for r in records),
                   "[스캔] 등록 파라미터 `ocr_endpoint` 로 적재 경로가 OCR 을 탄다", str(len(records)))
    finally:
        for name in (path, scanned, mixed):
            os.remove(name)


def _deferred_copy(path: str, root: str) -> str:
    """스캔 사본을 NFS 루트 아래 `up/doc.pdf` 로 둔다."""
    target = os.path.join(root, "up", "doc.pdf")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    os.replace(_scanned_copy(path), target)
    return target


class _PageOcr(_FakeOcr):
    """요청 순서가 아니라 **보낸 이미지**로 쪽을 골라 답한다 — MCP 가 쪽을 겹쳐 보낸다."""

    def __init__(self, by_png: dict, dpi: int, **kwargs) -> None:
        super().__init__([], dpi, **kwargs)
        owner = self

        class _Pages(list):
            def pop(self, index=0):
                return by_png.get(owner.requests[-1]["file"], [])

        self.pages = _Pages([None])


def _load_mcp_ocr() -> dict:
    namespace: dict = {}
    with open(os.path.join(MCP_DIR, "genon_ocr.py"), encoding="utf-8") as fh:
        exec(compile(fh.read(), "genon_ocr.py", "exec"), namespace)  # noqa: S102 - 등록 방식과 같다
    return namespace


def _deferred_markers(root: str, target: str, **kwargs) -> tuple:
    records = dp.DocumentProcessor()._process(
        target, save_images=False, ocr_defer=True, nfs_root=root, **kwargs
    )[0]
    joined = "\n\n".join(record["text"] for record in records)
    return joined, re.findall(r"\[\[GENON_SCAN page=(\d+) image=([^\]\n]+)\]\]", joined)


def case_deferred(rep: Report) -> None:
    import asyncio

    ocr = _load_mcp_ocr()
    saved_env = {key: os.environ.get(key) for key in ("NFS_ROOT", "OCR_ENDPOINT")}
    try:
        for columns in (1, 2, 3):
            tag = f"OCR 미룸 {columns}단"
            rng = random.Random(7)
            flow = Flow(columns=columns)
            flow.wide_text("문서 제목입니다")
            for number in range(1, 31):
                flow.paragraph(f"제{number}조(규정 {number}) " + _sentences(rng, rng.randint(3, 5)), indent=False)
                flow.paragraph("① " + _sentences(rng, 2), indent=False)
            path = flow.save()
            root = tempfile.mkdtemp()
            try:
                source = pymupdf.open(path)
                lines = [_page_line_items(page) for page in source]
                source.close()
                want = [_norm(text) for text in _texts(dp.parse_pdf(path)[0])]
                target = _deferred_copy(path, root)
                _, marks = _deferred_markers(root, target)
                rep.expect(
                    [int(page) for page, _ in marks] == list(range(1, len(lines) + 1))
                    and all(image == f"up/doc/scan-p{int(page):03d}.png" for page, image in marks),
                    f"[{tag}] 스캔 쪽마다 표식 하나 · NFS 루트 기준 상대경로", str(marks[:2]),
                )
                by_png = {}
                for page, image in marks:
                    with open(os.path.join(root, image), "rb") as fh:
                        by_png[base64.b64encode(fh.read()).decode("ascii")] = lines[int(page) - 1]
                server = _PageOcr(by_png, dp._PDF_OCR_DPI)
                os.environ["NFS_ROOT"], os.environ["OCR_ENDPOINT"] = root, server.endpoint
                try:
                    result = json.loads(asyncio.run(ocr["ocr_scan_pages"]([image for _, image in marks])))
                finally:
                    server.close()
                got = [
                    _norm(text) for page in result.get("pages") or []
                    for text in page["text"].split("\n\n") if text
                ]
                rep.expect(result.get("ok") and got == want,
                           f"[{tag}] MCP 가 텍스트 레이어 판과 같은 문단을 낸다", f"{len(got)} / {len(want)}")
                rep.expect(not any(_norm(_HEADER) in text for text in got),
                           f"[{tag}] 쪽마다 되풀이되는 머리말은 뺀다")
            finally:
                os.remove(path)
                shutil.rmtree(root, ignore_errors=True)

        # 청크 겹침이 표식을 자르지 않는다 — 스캔 쪽과 텍스트 쪽이 섞여 표식이 청크 경계에 걸린다.
        rng = random.Random(11)
        flow = Flow(columns=1)
        for number in range(1, 31):
            flow.paragraph(f"제{number}조(규정 {number}) " + _sentences(rng, rng.randint(3, 5)), indent=False)
        path = flow.save()
        root = tempfile.mkdtemp()
        try:
            target = os.path.join(root, "up", "doc.pdf")
            os.makedirs(os.path.dirname(target))
            os.replace(_scanned_copy(path, keep_text_pages=1), target)
            joined, marks = _deferred_markers(root, target)
            # 청크 겹침이 표식을 자르거나 되풀이하지 않는다 — 표식 바로 뒤 문단이 상한을 넘겨
            # 새 청크가 열리는 자리, 즉 겹침 꼬리가 표식에 걸치는 자리를 직접 만든다.
            marker = dp._SCAN_MARKER.format(page=2, image="up/doc/scan-p002.png")
            blocks = [
                dp.Block(kind="paragraph", text=_sentences(rng, 6), section=0),
                dp.Block(kind="paragraph", text=marker, section=0),
                dp.Block(kind="paragraph", text=_sentences(rng, 6), section=0),
            ]
            chunks = dp.chunk_blocks(blocks, dp.ChunkOptions(max_chars=len(blocks[0].text) + 60,
                                                             overlap_chars=len(marker) + 20))
            pieces = "".join(chunk.text for chunk in chunks)
            rep.expect(len(chunks) >= 2 and pieces.count("GENON_SCAN") == 1 and pieces.count(marker) == 1,
                       "[OCR 미룸] 청크 겹침이 표식을 자르거나 되풀이하지 않는다",
                       f"청크 {len(chunks)} · 표식 {pieces.count('GENON_SCAN')}")
            try:
                dp.DocumentProcessor()._process(
                    target, save_images=False, ocr_defer=True, nfs_root=os.path.join(root, "other")
                )
                raised = ""
            except dp.PreprocessError as exc:
                raised = str(exc)
            rep.expect("NFS 루트" in raised, "[OCR 미룸] 원본이 NFS 루트 밖이면 세운다", raised)
            saved_root = os.environ.pop("NFS_ROOT", None)
            try:
                dp.DocumentProcessor()._process(target, save_images=False, ocr_defer=True)
                raised = ""
            except dp.PreprocessError as exc:
                raised = str(exc)
            finally:
                if saved_root is not None:
                    os.environ["NFS_ROOT"] = saved_root
            rep.expect("NFS 루트" in raised, "[OCR 미룸] NFS 루트를 모르면 세운다", raised)

            images = [image for _, image in marks]
            os.environ["NFS_ROOT"] = root
            server = _PageOcr({}, dp._PDF_OCR_DPI, status=500)
            os.environ["OCR_ENDPOINT"] = server.endpoint
            try:
                failed = json.loads(asyncio.run(ocr["ocr_scan_pages"](images)))
            finally:
                server.close()
            rep.expect(failed == {"ok": False, "error_type": "OCR_SERVER_ERROR"},
                       "[OCR 미룸] OCR 서버 실패는 빈 글이 아니라 ok=false 다", str(failed))
            missing = json.loads(asyncio.run(ocr["ocr_scan_pages"](["up/doc/scan-p999.png"])))
            outside = json.loads(asyncio.run(ocr["ocr_scan_pages"](["../etc/passwd.png"])))
            rep.expect(missing.get("error_type") == "IMAGE_NOT_FOUND"
                       and outside.get("error_type") == "PATH_OUTSIDE_ROOT",
                       "[OCR 미룸] 지워진 원본 · 루트 밖 경로를 갈라 거절한다",
                       f"{missing} / {outside}")

            _case_deferred_step(rep, joined, images)
        finally:
            os.remove(path)
            shutil.rmtree(root, ignore_errors=True)
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _case_deferred_step(rep: Report, joined: str, images: list) -> None:
    """스텝 사본 하나(번역 스텝 1)로 표식 치환과 실패 처리를 본다 — 넷이 같은 코드인지는
    `check_deploy_contract` 의 사본 일치 판정이 본다."""
    import asyncio
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "translate_detect_step", os.path.join(WORKFLOW_DIR, "sfr018_translate_01_detect.py")
    )
    step = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(step)
    calls: list = []

    def install(reply):
        async def fake(env_name, tool, arguments, *, read_timeout=15.0):
            calls.append((env_name, tool, list(arguments["image_paths"])))
            return reply(arguments["image_paths"])
        step._mcp_call = fake

    install(lambda paths: ({"ok": True, "pages": [
        {"image_path": path, "text": f"쪽글{path[-7:-4]}"} for path in paths
    ]}, None))
    text, error = asyncio.run(step._ocr_scanned_pages(joined, {}))
    rep.expect(error is None and "GENON_SCAN" not in text
               and all(f"쪽글{image[-7:-4]}" in text for image in images)
               and calls == [("OCR_MCP_ID", "ocr_scan_pages", images)],
               "[OCR 미룸] 스텝이 연속한 쪽을 한 번에 보내고 표식을 OCR 글로 바꾼다", str(calls[:1]))

    calls.clear()
    marked = "[[GENON_SCAN page=2 image=a/scan-p002.png]]\n\n본문\n\n[[GENON_SCAN page=4 image=a/scan-p004.png]]"
    asyncio.run(step._ocr_scanned_pages(marked, {}))
    rep.expect([paths for _, _, paths in calls] == [["a/scan-p002.png"], ["a/scan-p004.png"]],
               "[OCR 미룸] 사이에 텍스트 쪽이 끼면 나눠 보낸다", str(calls))

    for label, reply, code in (
        ("원본 지워짐", lambda p: ({"ok": False, "error_type": "IMAGE_NOT_FOUND"}, None), "00020003"),
        ("OCR 실패", lambda p: ({"ok": False, "error_type": "OCR_SERVER_ERROR"}, None), "00020002"),
        ("통신 실패", lambda p: (None, ("transport", "ConnectError", None)), "00020001"),
        ("쪽 누락", lambda p: ({"ok": True, "pages": []}, None), "00020002"),
    ):
        install(reply)
        text, error = asyncio.run(step._ocr_scanned_pages(marked, {}))
        rep.expect(error is not None and error["error_code"].endswith(code) and text == marked,
                   f"[OCR 미룸] 스텝: {label} → 요청을 세운다", str(error))


def _hwp_cell(text, row, col, row_span=1, col_span=1, header=False):
    from docling_core.types.doc import TableCell
    return TableCell(
        text=text, row_span=row_span, col_span=col_span, column_header=header,
        start_row_offset_idx=row, end_row_offset_idx=row + row_span,
        start_col_offset_idx=col, end_col_offset_idx=col + col_span,
    )


def _hwp_doc(with_pages: bool = True, duplicate_covered: bool = False):
    """조문 두 개 + 병합 표 + 목록 항목. `duplicate_covered` 면 덮인 자리에도 같은 칸을 싣는다."""
    from docling_core.types.doc import BoundingBox, DoclingDocument, ProvenanceItem, Size, TableData

    doc = DoclingDocument(name="t")
    if with_pages:
        doc.add_page(page_no=1, size=Size(width=595, height=842))
        doc.add_page(page_no=2, size=Size(width=595, height=842))

    def prov(page):
        if not with_pages:
            return None
        return ProvenanceItem(page_no=page, bbox=BoundingBox(l=0, t=0, r=1, b=1), charspan=(0, 1))

    doc.add_text(label="text", text="제1조(목적) 이 규정은 정보자산 반출입 절차를 정한다.", prov=prov(1))
    doc.add_text(label="text", text="① 반출은 사전 승인을 받아야 한다.", prov=prov(1))
    merged = "반출 자산 정보(관리 번호 · 품명 · 수량을 모두 적는다)"
    cells = [
        _hwp_cell("구분", 0, 0, row_span=2, header=True),
        _hwp_cell(merged, 0, 1, col_span=3, header=True),
        _hwp_cell("번호", 1, 1), _hwp_cell("품명", 1, 2), _hwp_cell("수량", 1, 3),
        _hwp_cell("노트북", 2, 0), _hwp_cell("A-1", 2, 1), _hwp_cell("업무용", 2, 2), _hwp_cell("1", 2, 3),
    ]
    if duplicate_covered:
        cells += [_hwp_cell(merged, 0, 2, col_span=2), _hwp_cell(merged, 0, 3), _hwp_cell("구분", 1, 0)]
    table = doc.add_table(data=TableData(num_rows=3, num_cols=4, table_cells=cells), prov=prov(1))
    # 표 칸 내용이 표의 자식 항목으로 따로 실리는 백엔드 모양
    doc.add_text(label="text", text="업무용", parent=table, prov=prov(1))
    doc.add_text(label="text", text="제2조(승인) 승인권자는 경영지원실장으로 한다.", prov=prov(2))
    group = doc.add_list_group()
    doc.add_list_item(text="반출 사유를 적는다.", marker="1.", parent=group, prov=prov(2))
    return doc


def case_hwp(rep: Report) -> None:
    try:
        import docling_core  # noqa: F401
    except ImportError:
        print("[SKIP] docling_core 없음 — hwp 점검을 건너뛴다")
        return
    import asyncio

    original = dp._hwp_convert
    path = os.path.join(tempfile.mkdtemp(), "신청서.hwp")
    with open(path, "wb") as fh:
        fh.write(b"\xd0\xcf\x11\xe0")
    processor = dp.DocumentProcessor()
    merged = "반출 자산 정보(관리 번호 · 품명 · 수량을 모두 적는다)"

    def run(**kwargs):
        return asyncio.run(processor(None, path, **kwargs))

    def runs(**kwargs) -> bool:
        """폴백 판정용 — 세워지면 False(점검이 죽지 않고 FAIL 로 센다)."""
        try:
            return bool(run(**kwargs))
        except dp.PreprocessError:
            return False

    def install(results):
        calls = []

        def fake(file_path, backend):
            calls.append(backend)
            result = results[backend]
            if isinstance(result, BaseException):
                raise result
            return result
        dp._hwp_convert = fake
        return calls

    try:
        for duplicate in (False, True):
            tag = "[hwp 덮인 자리 중복]" if duplicate else "[hwp]"
            install({dp._HWP_SDK: _hwp_doc(duplicate_covered=duplicate)})
            records = run()
            text = "\n".join(r["text"] for r in records)
            rep.expect(text.count(merged) == 1, f"{tag} 가로 병합 칸 글자가 한 번만 실린다",
                       str(text.count(merged)))
            rep.expect(len(re.findall(r">구분<", text)) == 1, f"{tag} 세로 병합 칸 글자가 한 번만 실린다")
            table = next(r["text"] for r in records if r.get("source_kind") == "table")
            rows = re.findall(r"<tr>.*?</tr>", table)
            widths = [len(re.findall(r"<t[hd]", row)) for row in rows]
            rep.expect('colspan="3"' in table and 'rowspan="2"' in table and widths == [2, 3, 4],
                       f"{tag} 병합이 span 으로 살고 행마다 칸 수가 격자와 맞다", str(widths))
        rep.expect(text.count("업무용") == 1, "[hwp] 표 칸 안 항목이 문단으로 또 실리지 않는다",
                   str(text.count("업무용")))
        first = [r for r in records if "제1조" in r["text"]]
        rep.expect(bool(first) and all("제2조(승인) 승인권자" not in r["text"] for r in first),
                   "[hwp] 조 경계에서 청크가 끊긴다")
        second = [r for r in records if "반출 사유" in r["text"]]
        rep.expect(bool(second) and "1. 반출 사유를 적는다." in second[0]["text"]
                   and second[0].get("outline_path", [None])[0] == "제2조(승인)",
                   "[hwp] 목록 번호가 되붙고 조 줄기를 물려받는다",
                   json.dumps(second[:1], ensure_ascii=False))
        rep.expect(records[0]["page_basis"] == "page" and records[0]["i_page"] == 1
                   and second[0]["i_page"] == 2 and records[0]["n_page"] == 2
                   and "i_section" not in records[0],
                   "[hwp] 쪽 필드가 docling 쪽 번호를 따른다")

        install({dp._HWP_SDK: _hwp_doc(with_pages=False)})
        records = run()
        rep.expect(all(r["page_basis"] == "document" and r["i_page"] == 1 and r["n_page"] == 1
                       for r in records), "[hwp] 쪽 정보가 없으면 문서 하나로 싣는다")

        from docling_core.types.doc import DoclingDocument
        calls = install({dp._HWP_SDK: RuntimeError("sdk"), dp._HWP_LEGACY: _hwp_doc()})
        rep.expect(runs() and calls == [dp._HWP_SDK, dp._HWP_LEGACY],
                   "[hwp] SDK 실패 → 레거시 백엔드로 읽는다", str(calls))
        calls = install({dp._HWP_SDK: DoclingDocument(name="빈"), dp._HWP_LEGACY: _hwp_doc()})
        rep.expect(runs() and calls == [dp._HWP_SDK, dp._HWP_LEGACY],
                   "[hwp] SDK 결과가 비면 레거시 백엔드로 읽는다", str(calls))
        for label, legacy in (("레거시도 실패", RuntimeError("legacy")),
                              ("레거시도 빈 결과", DoclingDocument(name="빈"))):
            install({dp._HWP_SDK: RuntimeError("sdk"), dp._HWP_LEGACY: legacy})
            try:
                records = run()
                ok = False
            except dp.PreprocessError:
                ok, records = True, []
            except Exception as exc:
                ok, records = False, [repr(exc)]
            rep.expect(ok, f"[hwp] {label}면 빈 결과가 아니라 문서를 세운다",
                       str(records)[:200])

        dp._hwp_convert = original
        try:
            run()
            ok, message = False, ""
        except dp.PreprocessError as exc:
            ok, message = True, str(exc)
        rep.expect(ok and "hwp 리더" in message, "[hwp] 리더(GenOS docling)가 없으면 원인을 말하고 세운다",
                   message)
    finally:
        dp._hwp_convert = original


def case_sample(rep: Report) -> None:
    if not os.path.exists(_SAMPLE_01):
        print(f"[SKIP] 실물 없음: {_SAMPLE_01}")
        return
    blocks = dp.parse_pdf(_SAMPLE_01)[0]
    texts = [_norm(b.text) for b in blocks]
    rep.expect(any("내용올담고있다.공공기관에서" in t for t in texts),
               "[01.pdf] 단 경계에서 꺾인 `…담고 있` / `다. 공공기관…` 이 한 문단이다")
    rep.expect(not any("地理學" in t for t in texts), "[01.pdf] 머리말(地理學論叢)이 본문에 없다")
    rep.expect(not any(re.fullmatch(r"-?\d{1,3}-?", t) for t in texts), "[01.pdf] 쪽번호 블록이 없다")
    intro = [t for t in texts if t.startswith("본연구는국가혁신체계")]
    rep.expect(len(intro) == 1 and "변화된대학이란" in intro[0],
               "[01.pdf] 좌 · 우 단이 섞이지 않는다 (들어가는 말 첫 문단)")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rep = Report()
    case_statute(rep)
    _columns_case(rep, 2, "2단", with_table=True)
    _columns_case(rep, 3, "3단", with_table=False)
    case_scanned(rep)
    case_deferred(rep)
    case_hwp(rep)
    case_sample(rep)
    print()
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
