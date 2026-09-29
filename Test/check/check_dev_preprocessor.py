"""`final/preprocessor/dev_preprocessor.py` pdf 경로 점검 — 단 순서 · 문단 복원 · 머리말.

`python Test/check/check_dev_preprocessor.py`

## 무엇을 보는가

pdf 는 줄 좌표만 있고 문단이 없다. 그래서 **원문 문단을 알고 있는 pdf 를 여기서 만들어**
(PyMuPDF 내장 한글 글꼴) 다시 읽었을 때 문단이 하나씩, 원래 순서대로 나오는지 본다.
글자를 글자 단위로 꺾어 조판하므로 줄 끝이 단을 거의 채운다(양쪽 맞춤과 같은 모양).

1. **1단 조문** — 조/항/호 표기가 문단을 열고, 쪽을 넘는 조문이 한 문단으로 이어진다.
   `…있` / `다. …` 로 꺾인 줄은 목 표기(`다.`)가 아니라 이음이다. 조 경계에서 청크가 끊긴다.
2. **2단** — 전폭 제목 · 초록이 단보다 먼저, 좌 · 우 단이 섞이지 않고, 단 · 쪽을 넘는
   문단이 이어진다. 가운데 전폭 표는 표 블록으로 제자리에 선다.
3. **3단** — 같은 판정을 단 셋으로.
4. **실물 `Test/data/preprocessor/01.pdf`**(2단 OCR 논문) — **있을 때만** 탄다. 없으면
   건수가 줄어 `run_all` 의 EXPECTED 가 잡는다.

머리말 · 쪽번호는 세 합성 문서 모두 쪽마다 찍혀 있고 본문에 남으면 FAIL 이다.
스캔 쪽의 그림 속 OCR 글자 조각은 보지 않는다(보류된 범위다).
"""

from __future__ import annotations

import logging
import os
import random
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import PDF_SAMPLES_DIR, PREPROC_DIR  # noqa: E402

sys.path.insert(0, PREPROC_DIR)
logging.disable(logging.CRITICAL)

import pymupdf  # noqa: E402

import dev_preprocessor as dp  # noqa: E402

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
    case_sample(rep)
    print()
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
