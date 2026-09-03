"""onprem/preprocessor — hwpx 전용 GenOS 전처리기(area 05)의 파싱·청킹·`DocumentProcessor`.

실행: `cd SFR-018 && python -m unittest discover -s tests -t .`

**등록 단위는 `onprem/preprocessor/final_preprocessor.py` 한 파일이다** — 다른 파일을
import 하지 않는다(MCP 와 같은 파일 단위 등록). 여기서는 로컬 패키지 임포트 편의를
위해 `onprem/preprocessor/__init__.py` 가 재노출한 이름으로 같은 코드를 태운다.

## 무엇을 지키나

가장 중요한 것은 **표를 쪼갤 때 행이 새지 않는 것**이다. 한 행이 사라져도 남은 표는
문법적으로 멀쩡해서 눈으로는 안 보인다 — 검색 결과에 그 행만 영영 안 나올 뿐이다.

`DocumentProcessorTest` 는 `docs/GENOS_RULES.md` §F 가 요구하는 필수 케이스
(정상/빈 파일/손상 파일/미지원 확장자/파라미터 경계)를 지킨다.
"""

import asyncio
import io
import os
import re
import sys
import tempfile
import unittest
import zipfile

from . import onprem_path  # noqa: F401

# preprocessor 는 배포 단위가 아니라 onprem 바로 아래 패키지다.
sys.path.insert(0, onprem_path.ONPREM)

from preprocessor import final_preprocessor as hwpx_preprocessor  # noqa: E402
from preprocessor import (  # noqa: E402
    ChunkOptions,
    HwpxDocumentProcessor as DocumentProcessor,
    HwpxParseError,
    annotate_outline,
    chunk_blocks,
    parse,
    to_records,
)

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = "http://www.hancom.co.kr/hwpml/2011/head"

# sentinel 값은 **운영 코드에서 가져온다** — 손으로 적으면 상수를
# 고쳐도 그물이 옛 값을 계속 지킨다.
ID_NONE = hwpx_preprocessor._ID_NONE


def _para(text: str) -> str:
    return f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"


def _cell(row: int, col: int, body: str, *, row_span: int = 1, col_span: int = 1) -> str:
    return (
        f'<hp:tc><hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
        f'<hp:cellSpan colSpan="{col_span}" rowSpan="{row_span}"/>'
        f"<hp:subList>{body}</hp:subList></hp:tc>"
    )


def _pack(*bodies: str, header: str = "") -> bytes:
    """섹션 XML 을 인자 개수만큼 담은 hwpx 바이트.

    `header` 는 `Contents/header.xml`(문단 모양·번호 매기기 정의). **비워 두는 것이
    기본**이라, 그 항목이 없는 문서에서도 파싱이 그대로 도는지가 함께 검증된다.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        if header:
            zf.writestr("Contents/header.xml", header.encode("utf-8"))
        for index, body in enumerate(bodies):
            section = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<hs:sec xmlns:hp="{HP}" xmlns:hs="{HS}">{body}</hs:sec>'
            )
            zf.writestr(f"Contents/section{index}.xml", section.encode("utf-8"))
    return buf.getvalue()


def _blocks(*lines: str) -> list:
    """문단 목록 → 파싱된(위계 없는) 블록 목록."""
    return parse(_pack("".join(_para(t) for t in lines))).blocks


def _statute(*lines: str) -> list:
    """문단 목록 → 사다리를 **명시적으로 켠** 블록 목록.

    `auto` 를 쓰지 않는 이유: 사다리 자체를 보는 테스트가 auto 문턱(조 2개)에 걸려
    함께 죽으면, 규칙이 틀린 것인지 판정이 안 켜진 것인지 구분되지 않는다.
    auto 판정은 `OutlineModeTest` 가 따로 본다.
    """
    return annotate_outline(_blocks(*lines), "statute")


def _long_table(rows: int) -> str:
    body = "".join(
        f'<hp:tr>{_cell(i, 0, _para(f"항목{i}"))}'
        f'{_cell(i, 1, _para(f"{i * 100}"))}'
        f'{_cell(i, 2, _para("비고 문구입니다"))}</hp:tr>'
        for i in range(rows)
    )
    return f"<hp:p><hp:run><hp:tbl>{body}</hp:tbl></hp:run></hp:p>"


def _table_body(chunk) -> list:
    """표 청크에서 머리말(`제목 (표 2/10)`)을 뗀 본문 줄 목록.

    머리말은 봉투에 메타데이터가 안 실려서 본문에 넣은 것이라(→ `TablePrefixTest`),
    표 구조를 보는 테스트는 그 줄을 빼고 봐야 한다.
    """
    lines = chunk.text.splitlines()
    if lines and not lines[0].startswith("<table"):
        return lines[1:]
    return lines


def _merged_table() -> str:
    body = (
        f'<hp:tr>{_cell(0, 0, _para("구분"), row_span=2)}'
        f'{_cell(0, 1, _para("실적"), col_span=2)}</hp:tr>'
        f'<hp:tr>{_cell(1, 1, _para("상반기"))}{_cell(1, 2, _para("하반기"))}</hp:tr>'
    )
    return f"<hp:p><hp:run><hp:tbl>{body}</hp:tbl></hp:run></hp:p>"


class ParseTest(unittest.TestCase):
    def test_blocks_keep_document_order(self):
        data = _pack(_para("머리말") + _long_table(3) + _para("맺음말"))
        document = parse(data)
        self.assertEqual(
            [(b.kind, b.text[:3]) for b in document.blocks],
            [("paragraph", "머리말"), ("table", "<ta"), ("paragraph", "맺음말")],
        )

    def test_tables_are_always_html(self):
        """마크다운 표는 **행 경계가 개행뿐**이라, 검색 결과 조립에서 개행이 뭉개지면
        표가 아니게 된다(실물 확인). 병합이 없는 표도 HTML 로 낸다."""
        document = parse(_pack(_long_table(2) + _merged_table()))
        for block in document.blocks:
            self.assertTrue(block.text.startswith("<table><tbody>"), block.text[:40])
            self.assertNotIn("|---", block.text)

    def test_first_row_is_marked_as_the_header(self):
        """마크다운 구분선이 하던 일 — 없으면 조각마다 반복되는 머리행이 데이터로 읽힌다."""
        document = parse(_pack(_long_table(2)))
        rows = document.blocks[0].text.splitlines()
        self.assertIn("<th>항목0</th>", rows[1])
        self.assertIn("<td>항목1</td>", rows[2])

    def test_counts(self):
        document = parse(_pack(_para("가") + _long_table(2) + _para("나")))
        self.assertEqual(document.paragraph_count, 2)
        self.assertEqual(document.table_count, 1)
        self.assertEqual(document.section_count, 1)

    def test_to_markdown_matches_deployed_shape(self):
        """블록 사이 빈 줄 — 배포된 세 사본이 내던 문자열과 같은 모양."""
        document = parse(_pack(_para("가") + _para("나")))
        self.assertEqual(document.to_markdown(), "가\n\n나")


class BoxedTableTest(unittest.TestCase):
    """칸이 하나뿐인 표는 **표가 아니라 제목·강조 상자다.**

    hwpx 는 제목상자를 1칸 표로 만드는 일이 흔한데, 그대로 표로 내면 본문 행이 0개인
    퇴화된 표(머리행 하나에 본문 0행)가 된다 — 글자는 남지만 표가 아닌 것이 표로 검색되고
    표 골격이 노이즈로 임베딩된다. 실물(기술협상서)에서 확인한 모양이다.
    """

    def _box(self, body: str) -> str:
        return f"<hp:p><hp:run><hp:tbl><hp:tr>{_cell(0, 0, body)}</hp:tr></hp:tbl></hp:run></hp:p>"

    def test_single_cell_table_becomes_a_paragraph(self):
        document = parse(_pack(self._box(_para("『무슨무슨』 사업 기술협상서"))))
        self.assertEqual([b.kind for b in document.blocks], ["paragraph"])
        self.assertEqual(document.blocks[0].text, "『무슨무슨』 사업 기술협상서")

    def test_box_joins_its_paragraphs_with_real_newlines(self):
        """`<br>` 은 표 칸 안의 줄바꿈이라, 표를 벗어나면 글자로 보인다."""
        document = parse(_pack(self._box(_para("첫 줄") + _para("둘째 줄"))))
        self.assertEqual(document.blocks[0].text, "첫 줄\n둘째 줄")

    def test_empty_box_is_dropped(self):
        """빈 상자를 표로 내면 글자 없는 청크가 생긴다."""
        document = parse(_pack(_para("본문") + self._box(_para(""))))
        self.assertEqual([b.text for b in document.blocks], ["본문"])

    def test_box_with_a_nested_table_stays_a_table(self):
        """문단으로 펴면 안쪽 표를 통째로 잃는다."""
        # 중첩 표도 hwpx 에서는 문단(hp:p) 안에 놓인다 — 그 모양대로 세워야 소유 판정
        # (`_owning_box`)이 실제와 같은 길을 탄다.
        inner_rows = f'<hp:tr>{_cell(0, 0, _para("가"))}{_cell(0, 1, _para("나"))}</hp:tr>'
        inner = f"<hp:p><hp:run><hp:tbl>{inner_rows}</hp:tbl></hp:run></hp:p>"
        document = parse(_pack(self._box(_para("설명") + inner)))
        self.assertEqual([b.kind for b in document.blocks], ["table"])
        self.assertIn("나", document.blocks[0].text)

    def test_real_table_is_untouched(self):
        """칸이 둘 이상이면 그대로 표다 — 1행짜리라도."""
        row = f"<hp:tr>{_cell(0, 0, _para('가'))}{_cell(0, 1, _para('나'))}</hp:tr>"
        document = parse(_pack(f"<hp:p><hp:run><hp:tbl>{row}</hp:tbl></hp:run></hp:p>"))
        self.assertEqual([b.kind for b in document.blocks], ["table"])

    def test_box_participates_in_outline_detection(self):
        """조문이 상자 안에 있어도 위계로 읽혀야 한다 — 표로 두면 지나쳐 간다."""
        body = self._box(_para("제5조(목적) 목적을 정한다.")) + _para("제6조(범위) 범위를 정한다.")
        blocks = annotate_outline(parse(_pack(body)).blocks)
        self.assertEqual([b.outline_level for b in blocks], [5, 5])


class TableChunkingTest(unittest.TestCase):
    """표를 쪼갤 때의 계약. **행이 새면 안 된다.**"""

    def test_small_table_is_one_chunk(self):
        document = parse(_pack(_long_table(3)))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=2000))
        self.assertEqual(len(chunks), 1)
        self.assertIsNone(chunks[0].table_part)

    def test_split_loses_no_rows(self):
        """모든 데이터 행이 정확히 한 번씩 남아야 한다."""
        document = parse(_pack(_long_table(12)))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=300))
        self.assertGreater(len(chunks), 1, "쪼개지지 않았다면 이 테스트가 무의미하다")

        joined = "\n".join(c.text for c in chunks)
        # 0번은 머리행이라 조각마다 반복되는 것이 정상이다 (그게 이 분할의 요점이다).
        for index in range(1, 12):
            self.assertEqual(
                joined.count(f"<td>항목{index}</td>"), 1,
                f"항목{index} 행이 {joined.count(f'<td>항목{index}</td>')}번 나온다 (1번이어야 한다)",
            )
        # 머리행은 조각 수만큼 나와야 한다 — 한 번만 나오면 반복이 안 된 것이다
        self.assertEqual(joined.count("<th>항목0</th>"), len(chunks))

    def test_split_repeats_header(self):
        """조각마다 머리행이 있어야 **혼자서도 해석 가능**하다."""
        document = parse(_pack(_long_table(12)))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=300))
        for chunk in chunks:
            lines = _table_body(chunk)
            self.assertEqual(lines[0], "<table><tbody>")
            self.assertIn("<th>", lines[1], f"머리행이 없다: {lines[:2]}")
            self.assertEqual(lines[-1], "</tbody></table>")

    def test_split_chunks_report_their_part(self):
        """쪼갰다는 사실을 숨기지 않는다 — 조각만 보고 '표가 이게 전부' 로 읽으면 안 된다."""
        document = parse(_pack(_long_table(12)))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=300))
        total = len(chunks)
        self.assertEqual(
            [c.table_part for c in chunks],
            [(i, total) for i in range(total)],
        )

    def test_merged_table_split_keeps_rows_and_header(self):
        rows = "".join(
            f'<hp:tr>{_cell(i, 0, _para(f"행{i}"), row_span=(2 if i == 0 else 1))}'
            f'{_cell(i, 1, _para(f"값{i} 설명이 붙은 긴 셀 내용"))}</hp:tr>'
            for i in range(10)
        )
        document = parse(_pack(f"<hp:p><hp:run><hp:tbl>{rows}</hp:tbl></hp:run></hp:p>"))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=300))
        self.assertGreater(len(chunks), 1)
        joined = "\n".join(c.text for c in chunks)
        for index in range(1, 10):  # 0번은 머리행이라 조각마다 반복된다
            self.assertEqual(joined.count(f"<td>행{index}</td>"), 1)
        self.assertIn("rowspan=", joined, "병합 선언이 보존돼야 한다")
        for chunk in chunks:
            body = "\n".join(_table_body(chunk))
            self.assertTrue(body.startswith("<table><tbody>"))
            self.assertTrue(body.endswith("</tbody></table>"))
            self.assertIn("행0", body, "머리행이 조각마다 반복돼야 한다")

    def test_table_never_merges_with_paragraph(self):
        """표를 문단 꼬리에 붙이면 검색 결과가 읽기 어려워진다."""
        document = parse(_pack(_para("짧은 머리말") + _long_table(2)))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=2000))
        self.assertEqual([c.kind for c in chunks], ["paragraph", "table"])


class WideRowTest(unittest.TestCase):
    """행 **하나**가 상한을 넘을 때. 행 단위로만 쪼개던 때는 여기서 상한을 넘긴 채
    임베딩으로 갔고(실물 1,929자), 컨텍스트가 짧으면 뒤쪽이 조용히 잘렸다."""

    LINES = 12

    def _table(self) -> str:
        # 셀 안 여러 문단이 곧 `<br>` 다 (`_cell_text`) — 문자열로 `<br>` 를 넣으면
        # 그건 XML 태그라 파싱이 죽는다.
        long_cell = "".join(
            f"<hp:p><hp:run><hp:t>▪{i}번 항목에 대한 상세 의견입니다</hp:t></hp:run></hp:p>"
            for i in range(self.LINES)
        )
        rows = (
            f'<hp:tr>{_cell(0, 0, _para("순번"))}{_cell(0, 1, _para("협상대상자 의견"))}'
            f'{_cell(0, 2, _para("수용여부"))}</hp:tr>'
            f'<hp:tr>{_cell(1, 0, _para("7"))}{_cell(1, 1, long_cell)}'
            f'{_cell(1, 2, _para("수용"))}</hp:tr>'
        )
        return f"<hp:p><hp:run><hp:tbl>{rows}</hp:tbl></hp:run></hp:p>"

    def _chunks(self, max_chars: int = 300):
        return chunk_blocks(parse(_pack(self._table())).blocks, ChunkOptions(max_chars=max_chars))

    def test_no_chunk_exceeds_the_limit(self):
        for chunk in self._chunks():
            self.assertLessEqual(
                len(chunk.text), 300, f"머리말까지 넣어 상한을 지켜야 한다: {chunk.text[:60]}"
            )

    def test_every_line_survives_exactly_once(self):
        """표 안에서 겹치면 같은 수치가 두 번 나와 합계가 틀린다 — 무손실이자 무중복."""
        joined = "\n".join(c.text for c in self._chunks())
        for index in range(self.LINES):
            self.assertEqual(joined.count(f"▪{index}번 항목에 대한 상세 의견입니다"), 1)

    def test_short_cells_repeat_so_the_piece_reads_alone(self):
        chunks = self._chunks()
        self.assertGreater(len(chunks), 1, "쪼개지지 않았다면 이 테스트가 무의미하다")
        for chunk in chunks:
            row = _table_body(chunk)[2]
            self.assertIn("<td>7</td>", row, f"순번이 빠졌다: {row}")
            self.assertIn("<td>수용</td>", row, f"수용여부가 빠졌다: {row}")

    def test_column_count_never_changes(self):
        for chunk in self._chunks():
            widths = {
                len(re.findall(r"<t[dh]\b", line))
                for line in _table_body(chunk)
                if line.startswith("<tr>")
            }
            self.assertEqual(widths, {3}, f"열 수가 흔들렸다: {widths}")

    def test_empty_long_cell_is_marked_not_blank(self):
        """조각에 안 실린 긴 칸은 생략 표시를 남긴다 — 빈칸이면 '값 없음' 으로 읽힌다.

        긴 칸이 **둘 이상**일 때 생기는 자리다(실물의 `의견 등` + `협상대상자 의견`).
        """
        long_cell = "".join(
            f"<hp:p><hp:run><hp:t>{{}}{i}번 항목에 대한 상세 의견입니다</hp:t></hp:run></hp:p>"
            for i in range(self.LINES)
        )
        rows = (
            f'<hp:tr>{_cell(0, 0, _para("순번"))}{_cell(0, 1, _para("의견 등"))}'
            f'{_cell(0, 2, _para("협상대상자 의견"))}</hp:tr>'
            f'<hp:tr>{_cell(1, 0, _para("7"))}{_cell(1, 1, long_cell.format(*"▪" * self.LINES))}'
            f'{_cell(1, 2, long_cell.format(*"◦" * self.LINES))}</hp:tr>'
        )
        table = f"<hp:p><hp:run><hp:tbl>{rows}</hp:tbl></hp:run></hp:p>"
        chunks = chunk_blocks(parse(_pack(table)).blocks, ChunkOptions(max_chars=300))
        body_rows = [_table_body(c)[2] for c in chunks]
        self.assertIn("<td>…</td>", body_rows[0], f"뒤 칸 자리가 비어 있다: {body_rows[0]}")
        self.assertIn("<td>…</td>", body_rows[-1], f"앞 칸 자리가 비어 있다: {body_rows[-1]}")

    def test_merged_row_is_not_split_inside_cells(self):
        """병합은 "이 칸이 몇 행·몇 열을 덮는다" 는 선언이라, 조각마다 되풀이하면
        **없던 격자를 지어낸다.** 그런 행은 상한을 넘겨도 그대로 둔다."""
        long_cell = "".join(
            f"<hp:p><hp:run><hp:t>▪{i}번 항목에 대한 상세 의견입니다</hp:t></hp:run></hp:p>"
            for i in range(self.LINES)
        )
        rows = (
            f'<hp:tr>{_cell(0, 0, _para("순번"))}{_cell(0, 1, _para("의견"))}'
            f'{_cell(0, 2, _para("비고"))}</hp:tr>'
            f'<hp:tr>{_cell(1, 0, _para("7"), col_span=2)}{_cell(1, 2, long_cell)}</hp:tr>'
        )
        table = f"<hp:p><hp:run><hp:tbl>{rows}</hp:tbl></hp:run></hp:p>"
        chunks = chunk_blocks(parse(_pack(table)).blocks, ChunkOptions(max_chars=300))
        joined = "\n".join(c.text for c in chunks)
        self.assertNotIn("…", joined, "병합이 걸린 행을 셀 안에서 쪼갰다")
        self.assertEqual(joined.count('colspan="2"'), 1, "병합 선언이 복제됐다")

    def test_nested_table_row_is_not_split_inside_cells(self):
        """안쪽 표가 조각 사이에서 갈린다."""
        inner_rows = f'<hp:tr>{_cell(0, 0, _para("가"))}{_cell(0, 1, _para("나"))}</hp:tr>'
        inner = f"<hp:p><hp:run><hp:tbl>{inner_rows}</hp:tbl></hp:run></hp:p>"
        long_cell = "".join(
            f"<hp:p><hp:run><hp:t>▪{i}번 항목에 대한 상세 의견입니다</hp:t></hp:run></hp:p>"
            for i in range(self.LINES)
        )
        rows = (
            f'<hp:tr>{_cell(0, 0, _para("순번"))}{_cell(0, 1, _para("의견"))}</hp:tr>'
            f'<hp:tr>{_cell(1, 0, _para("7") + inner)}{_cell(1, 1, long_cell)}</hp:tr>'
        )
        table = f"<hp:p><hp:run><hp:tbl>{rows}</hp:tbl></hp:run></hp:p>"
        chunks = chunk_blocks(parse(_pack(table)).blocks, ChunkOptions(max_chars=300))
        joined = "\n".join(c.text for c in chunks)
        self.assertNotIn("…", joined, "중첩 표가 든 행을 셀 안에서 쪼갰다")
        # 안쪽 표도 첫 행을 머리행으로 본다 — 한 번만, 온전히 남아야 한다.
        self.assertEqual(
            joined.count("<tr><th>가</th><th>나</th></tr>"), 1, "안쪽 표가 갈렸거나 복제됐다"
        )

    def test_untouched_when_rows_already_fit(self):
        document = parse(_pack(_long_table(12)))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=300))
        for chunk in chunks:
            self.assertNotIn("…", chunk.text, "쪼갤 필요가 없는 행을 건드렸다")


class TablePrefixTest(unittest.TestCase):
    """표 조각의 머리말. **레코드 메타데이터가 아니라 본문에 들어가야 한다** —
    검색 결과 봉투(`<doc file_name=… security_level=…>`)에는 `i_table_part` 가 실리지
    않아, 3번째 조각이 '3번 항목부터 시작하는 표' 로 보였다(실물 확인)."""

    def test_split_pieces_say_which_piece_they_are(self):
        document = parse(_pack(_long_table(12)))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=300))
        total = len(chunks)
        for index, chunk in enumerate(chunks):
            self.assertTrue(
                chunk.text.startswith(f"(표 {index + 1}/{total})"),
                f"조각 표시가 없다: {chunk.text[:40]}",
            )

    def test_preceding_short_paragraph_becomes_the_title(self):
        document = parse(_pack(_para("협상 의견 표") + _long_table(12)))
        chunks = [c for c in chunk_blocks(document.blocks, ChunkOptions(max_chars=300))
                  if c.kind == "table"]
        for chunk in chunks:
            self.assertEqual(chunk.table_title, "협상 의견 표")
            self.assertTrue(chunk.text.startswith("협상 의견 표 (표 "))

    def test_body_paragraph_is_not_a_title(self):
        """본문을 제목으로 삼으면 조각마다 반복돼 임베딩이 표에서 멀어진다."""
        body = "가" * 200
        document = parse(_pack(_para(body) + _long_table(12)))
        chunks = [c for c in chunk_blocks(document.blocks, ChunkOptions(max_chars=300))
                  if c.kind == "table"]
        self.assertTrue(all(c.table_title == "" for c in chunks))

    def test_title_does_not_leak_to_the_next_table(self):
        document = parse(
            _pack(_para("첫 표 제목") + _long_table(2) + _long_table(2))
        )
        tables = [c for c in chunk_blocks(document.blocks, ChunkOptions(max_chars=2000))
                  if c.kind == "table"]
        self.assertEqual([c.table_title for c in tables], ["첫 표 제목", ""])

    def test_unsplit_table_keeps_its_title_and_has_no_part_marker(self):
        document = parse(_pack(_para("작은 표") + _long_table(2)))
        table = [c for c in chunk_blocks(document.blocks, ChunkOptions(max_chars=2000))
                 if c.kind == "table"][0]
        self.assertTrue(table.text.startswith("작은 표\n<table"))
        self.assertNotIn("(표 ", table.text)

    def test_statute_document_does_not_get_two_prefixes(self):
        blocks = annotate_outline(
            parse(_pack(_para("제5조(목적)") + _long_table(12))).blocks, "statute"
        )
        chunks = [c for c in chunk_blocks(blocks, ChunkOptions(max_chars=300))
                  if c.kind == "table"]
        for chunk in chunks:
            self.assertTrue(chunk.text.startswith("제5조(목적)\n\n(표 "), chunk.text[:40])
            self.assertEqual(chunk.text.count("제5조(목적)"), 1)


class AnchoredObjectOrderTest(unittest.TestCase):
    """한 문단에 표·상자가 **둘 이상** 매달릴 때. XML 순서가 곧 화면 순서는 아니다 —
    실물에서 제목상자가 본문 표 **뒤로** 밀려 표 조각 어디에도 제목이 없었다."""

    @staticmethod
    def _pos(*, treat_as_char: str, vert_offset: str, vert_rel_to: str = "PARA") -> str:
        return (
            f'<hp:pos treatAsChar="{treat_as_char}" vertRelTo="{vert_rel_to}"'
            f' vertOffset="{vert_offset}" horzOffset="0"/>'
        )

    def _anchor(self, table_pos: str, box_pos: str) -> list:
        box = (
            f"<hp:tbl>{box_pos}<hp:tr>{_cell(0, 0, _para('문서 제목'))}</hp:tr></hp:tbl>"
        )
        table = (
            f"<hp:tbl>{table_pos}"
            f'<hp:tr>{_cell(0, 0, _para("머리"))}{_cell(0, 1, _para("값"))}</hp:tr>'
            f'<hp:tr>{_cell(1, 0, _para("행"))}{_cell(1, 1, _para("1"))}</hp:tr></hp:tbl>'
        )
        # XML 에는 본문 표를 **먼저** 둔다 — 실물이 그랬다.
        return parse(_pack(f"<hp:p><hp:run>{table}{box}</hp:run></hp:p>")).blocks

    def test_inline_box_comes_before_the_floating_table(self):
        blocks = self._anchor(
            self._pos(treat_as_char="0", vert_offset="5940"),   # 본문 표: 문단에서 아래로
            self._pos(treat_as_char="1", vert_offset="0"),      # 제목상자: 글자처럼
        )
        self.assertEqual([b.kind for b in blocks], ["paragraph", "table"])
        self.assertEqual(blocks[0].text, "문서 제목")

    def test_title_reaches_the_table_chunks(self):
        blocks = self._anchor(
            self._pos(treat_as_char="0", vert_offset="5940"),
            self._pos(treat_as_char="1", vert_offset="0"),
        )
        table = [c for c in chunk_blocks(blocks, ChunkOptions(max_chars=2000))
                 if c.kind == "table"][0]
        self.assertEqual(table.table_title, "문서 제목")

    def test_document_order_is_kept_when_offsets_are_not_comparable(self):
        """기준이 다르면(문단 vs 페이지) 오프셋 크기를 비교할 수 없다 — 순서를 지어내지 않는다."""
        blocks = self._anchor(
            self._pos(treat_as_char="0", vert_offset="5940"),
            self._pos(treat_as_char="0", vert_offset="0", vert_rel_to="PAGE"),
        )
        self.assertEqual([b.kind for b in blocks], ["table", "paragraph"])


class ParagraphChunkingTest(unittest.TestCase):
    def test_paragraphs_are_packed_up_to_limit(self):
        body = "".join(_para(f"문단 {i} 입니다.") for i in range(20))
        document = parse(_pack(body))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=120, overlap_chars=0))
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk.text), 120 + 20)  # 경계 문단 하나만큼 여유

    def test_long_paragraph_is_split_at_sentences(self):
        sentence = "본 사업은 2026년에 완료하였습니다. "
        document = parse(_pack(_para(sentence * 30)))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=200, overlap_chars=0))
        self.assertGreater(len(chunks), 1)
        # 문장 중간에서 잘리면 조각이 '본 사업은' 같은 토막으로 끝난다
        for chunk in chunks[:-1]:
            self.assertTrue(chunk.text.rstrip().endswith("다."), chunk.text[-30:])

    def test_tiny_paragraph_merges_into_previous(self):
        document = parse(_pack(_para("충분히 긴 첫 문단입니다. " * 3) + _para("짧음")))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=2000))
        self.assertEqual(len(chunks), 1)
        self.assertIn("짧음", chunks[0].text)


class OutlineDetectionTest(unittest.TestCase):
    """조문 위계 판정 (`annotate_outline`).

    가장 중요한 것은 **인용을 제목으로 오인하지 않는 것**이다. `제5조에 따라` 를 제목으로
    읽으면 그 자리에서 청크가 끊겨, 앞 조의 마지막 항이 뒤 조의 것처럼 검색된다 —
    조각을 눈으로 봐도 멀쩡해 보이므로 드러나지 않는다.
    """

    def test_levels_follow_the_statute_ladder(self):
        blocks = _statute(
            "제1편 총칙",
            "제2장 통칙",
            "제3절 적용",
            "제4관 특례",
            "제5조(목적) 이 규칙의 목적을 정한다.",
            "① 첫째 항이다.",
            "1. 첫째 호이다",
            "가. 첫째 목이다",
            "본문 문단이다.",
        )
        self.assertEqual([b.outline_level for b in blocks], [1, 2, 3, 4, 5, 6, 7, 8, 0])

    def test_citation_is_not_a_heading(self):
        """조사가 붙으면 제목이 아니라 본문 인용이다."""
        blocks = _statute(
            "제5조(목적) 목적을 정한다.",
            "제6조(범위) 범위를 정한다.",
            "제5조에 따라 신청서를 제출한다.",
            "제2장에서 정한 바에 따른다.",
        )
        self.assertEqual([b.outline_level for b in blocks], [5, 5, 0, 0])

    def test_sub_article_is_one_article(self):
        """가지조문(`제5조의2`)은 제5조와 **다른 조**이고, 레벨은 같다."""
        blocks = _statute("제5조(목적) 목적.", "제5조의2(특례) 특례를 정한다.")
        self.assertEqual([b.outline_level for b in blocks], [5, 5])
        self.assertNotEqual(blocks[0].outline_path, blocks[1].outline_path)

    def test_supplementary_provision_is_a_chapter(self):
        blocks = _statute("제5조(목적) 목적.", "제6조(범위) 범위.", "부칙", "이 규칙은 공포한 날부터 시행한다.")
        self.assertEqual(blocks[2].outline_level, 2)
        self.assertEqual(blocks[3].outline_path, ("부칙",))

    def test_path_stops_at_article(self):
        """항·호·목은 제목이 아니라 조문 **내용**이다 — 줄기에 쌓이면 머리말이 본문을
        통째로 되풀이한다."""
        blocks = _statute(
            "제2장 통칙",
            "제5조(목적) 목적을 정한다.",
            "① 첫째 항이다.",
            "1. 첫째 호이다",
        )
        for block in blocks[1:]:
            self.assertEqual(block.outline_path, ("제2장 통칙", "제5조(목적)"), block.text)

    def test_label_prefers_parenthetical_title(self):
        """조문 제목은 본문과 한 문단에 붙어 온다 — 이름표는 괄호까지만."""
        blocks = _statute(
            "제5조(적용범위) 이 규칙은 회사에 근무하는 전 직원에게 적용한다.",
            "제6조(예외) 예외를 정한다.",
        )
        self.assertEqual(blocks[0].outline_path, ("제5조(적용범위)",))

    def test_date_paragraph_is_not_a_clause(self):
        """`2026. 8. 13.` 이 1호로 잡히면 시행일 문단이 조문 구조에 끼어든다."""
        blocks = _statute("제5조(목적) 목적.", "제6조(범위) 범위.", "2026. 8. 13. 기준으로 한다.")
        self.assertEqual(blocks[2].outline_level, 0)

    def test_table_inherits_the_article(self):
        """표만 검색돼 나왔을 때 어느 조의 표인지 알아야 한다."""
        body = _para("제5조(목적) 목적.") + _para("제6조(별표) 다음 표와 같다.") + _long_table(3)
        blocks = annotate_outline(parse(_pack(body)).blocks)
        table = next(b for b in blocks if b.is_table)
        self.assertEqual(table.outline_path, ("제6조(별표)",))
        self.assertEqual(table.outline_level, 0, "표 자체는 제목이 아니다")


class OutlineModeTest(unittest.TestCase):
    """**언제 사다리를 적용할 것인가.** 같은 `1.` 이 법령에서는 호이고 공문서에서는
    최상위 항목이라, 일반 문서에 사다리를 걸면 목록이 전부 제목으로 승격돼 지금보다
    나빠진다. `auto` 는 조 표기를 세어 본 뒤에만 켠다.
    """

    ORDINARY = ("1. 사업 개요", "가. 배경입니다.", "① 첫째", "2026. 8. 13. 기준")

    def test_auto_stays_off_for_ordinary_document(self):
        blocks = annotate_outline(_blocks(*self.ORDINARY))
        self.assertEqual([b.outline_level for b in blocks], [0, 0, 0, 0])
        self.assertEqual([b.outline_path for b in blocks], [(), (), (), ()])

    def test_auto_needs_more_than_one_article(self):
        """조문을 한 번 인용한 일반 문서를 조문 문서로 오인하지 않는다."""
        blocks = annotate_outline(_blocks("제5조(목적) 목적.", "1. 첫째", "가. 둘째"))
        self.assertEqual([b.outline_level for b in blocks], [0, 0, 0])

    def test_auto_turns_on_from_two_articles(self):
        blocks = annotate_outline(_blocks("제5조(목적) 목적.", "제6조(범위) 범위.", "1. 첫째"))
        self.assertEqual([b.outline_level for b in blocks], [5, 5, 7])

    def test_statute_mode_forces_the_ladder(self):
        """`auto` 가 못 켠 문서도 등록 화면에서 명시하면 켜진다."""
        blocks = annotate_outline(_blocks(*self.ORDINARY), "statute")
        self.assertEqual([b.outline_level for b in blocks], [7, 8, 6, 0])

    def test_off_mode_leaves_blocks_bare(self):
        blocks = annotate_outline(_blocks("제5조(목적) 목적.", "제6조(범위) 범위."), "off")
        self.assertEqual([b.outline_level for b in blocks], [0, 0])
        self.assertEqual([b.outline_path for b in blocks], [(), ()])

    def test_invalid_mode_falls_back_to_auto(self):
        """등록 화면 오타가 재적재를 막으면 안 된다."""
        blocks = annotate_outline(
            _blocks("제5조(목적) 목적.", "제6조(범위) 범위."), "STATUTE-ish"
        )
        self.assertEqual([b.outline_level for b in blocks], [5, 5])


class DocumentOutlineTest(unittest.TestCase):
    """**공문서 사다리** (`outline_mode="document"`). 법령 사다리와 레벨이 정면으로
    어긋나므로(법령의 `1.` 은 호, 공문서의 `1.` 은 최상위) 별도 표이고, `auto` 는
    이 모드를 절대 고르지 않는다.

    오탐의 대가가 법령 쪽보다 크다 — 법령에서 `1.` 은 레벨 7 이라 청크 경계도 제목
    줄기도 안 건드리는데, 여기서는 최상위라 오탐 하나가 곧 잘못된 청크 경계다.
    """

    def _levels(self, *lines):
        return [b.outline_level for b in annotate_outline(_blocks(*lines), "document")]

    def _paths(self, *lines):
        return [b.outline_path for b in annotate_outline(_blocks(*lines), "document")]

    def test_number_and_hangul_make_two_levels(self):
        self.assertEqual(
            self._levels("1. 지원 대상", "가. 신청 자격", "내용이다.", "2. 지원 내용", "가. 항목"),
            [1, 2, 0, 1, 2],
        )

    def test_path_nests_under_the_parent(self):
        paths = self._paths(
            "1. 지원 대상", "가. 신청 자격", "내용이다.", "2. 지원 내용", "가. 항목"
        )
        self.assertEqual(paths[1], ("1. 지원 대상", "가. 신청 자격"))
        self.assertEqual(paths[2], ("1. 지원 대상", "가. 신청 자격"))
        self.assertEqual(paths[3], ("2. 지원 내용",))

    def test_levels_are_renumbered_from_the_observed_top(self):
        """최상위가 `Ⅰ.` 인 문서와 `1.` 인 문서가 같은 레벨을 가져야
        청크 경계·머리말 깊이를 고정 숫자로 둘 수 있다."""
        self.assertEqual(
            self._levels("Ⅰ. 총칙", "1. 목적", "본문이다.", "2. 범위", "Ⅱ. 운영", "1. 절차"),
            [1, 2, 0, 2, 1, 2],
        )

    def test_fullwidth_and_missing_space_are_matched(self):
        """실물 공문서에 전각 마침표와 공백 없는 표기가 흔하다."""
        self.assertEqual(
            self._levels("1．지원대상", "2.기타사항", "본문 문장이다."), [1, 1, 0]
        )

    def test_numbered_sentence_is_not_a_heading(self):
        """길고 종결어미로 끝나면 제목이 아니라 번호 붙은 본문이다."""
        self.assertEqual(
            self._levels(
                "1. 본 사업은 노후 설비를 교체하기 위하여 추진하는 것이다.",
                "2. 예산은 총 30억원 규모로 편성하였으며 단계적으로 집행한다.",
            ),
            [0, 0],
        )

    def test_single_occurrence_is_not_a_ladder_step(self):
        """한 번만 나오는 표기는 본문 인용일 수 있다 — 사다리에 넣지 않는다."""
        self.assertEqual(
            self._levels("1. 지원 대상", "2. 지원 내용", "1) 부속 항목", "내용이다."),
            [1, 1, 0, 0],
        )

    def test_ladder_step_must_start_at_one(self):
        """3번부터 시작하는 표기는 목록이 아니다."""
        self.assertEqual(
            self._levels("3. 어떤 항목", "4. 다른 항목", "내용이다."), [0, 0, 0]
        )

    def test_auto_never_selects_the_document_ladder(self):
        """**회귀 방지 핵심.** auto 가 이 사다리를 고르면 법령 문서의 호·목이
        최상위 제목으로 승격돼 조문이 통째로 흩어진다."""
        lines = ("1. 지원 대상", "가. 신청 자격", "2. 지원 내용", "가. 항목")
        self.assertEqual(self._levels(*lines), [1, 2, 1, 2])
        blocks = annotate_outline(_blocks(*lines))
        self.assertEqual([b.outline_level for b in blocks], [0, 0, 0, 0])

    def test_no_usable_ladder_leaves_blocks_bare(self):
        blocks = annotate_outline(_blocks("본문이다.", "또 다른 본문이다."), "document")
        self.assertEqual([b.outline_level for b in blocks], [0, 0])
        self.assertEqual([b.outline_path for b in blocks], [(), ()])

    def test_chunks_break_at_the_top_two_levels(self):
        lines = ("1. 지원 대상", "가. 자격", "내용 하나다.", "나. 서류", "2. 지원 내용", "내용 둘이다.")
        options = ChunkOptions(
            max_chars=2000, outline_break_level=hwpx_preprocessor._DOC_BREAK_LEVEL
        )
        chunks = chunk_blocks(annotate_outline(_blocks(*lines), "document"), options)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(chunks[0].text.startswith("1. 지원 대상"))
        self.assertIn("나. 서류", chunks[1].text)
        self.assertTrue(chunks[2].text.startswith("2. 지원 내용"))

    def test_statute_documents_are_unaffected(self):
        """레벨 상수를 모드별로 가른 변경이 법령 경로를 흔들지 않는다."""
        blocks = _statute("제5조(목적) 목적.", "① 항이다.", "1. 호다.", "가. 목이다.")
        self.assertEqual([b.outline_level for b in blocks], [5, 6, 7, 8])
        self.assertEqual(blocks[3].outline_path, ("제5조(목적)",))


class OutlineChunkingTest(unittest.TestCase):
    """**조가 검색 단위다.** 한 조가 여러 청크로 흩어지면 "제5조가 무엇을 정하는가" 에
    답할 수 없고, 두 조가 한 청크에 붙으면 검색이 엉뚱한 조를 근거로 든다.
    """

    def _chunks(self, lines, **kwargs):
        options = ChunkOptions(max_chars=kwargs.pop("max_chars", 2000), **kwargs)
        return chunk_blocks(_statute(*lines), options)

    def test_articles_never_share_a_chunk(self):
        """길이로는 한 청크에 들어가도 조가 다르면 갈린다."""
        chunks = self._chunks(
            ["제5조(목적) 목적을 정한다.", "① 첫째 항.", "제6조(범위) 범위를 정한다.", "② 둘째 항."]
        )
        self.assertEqual(len(chunks), 2)
        self.assertIn("제5조", chunks[0].text)
        self.assertNotIn("제6조", chunks[0].text)
        self.assertIn("제6조", chunks[1].text)

    def test_clauses_do_not_break_the_article(self):
        """항·호·목에서 끊으면 조문 하나가 문장 조각으로 부서진다."""
        chunks = self._chunks(
            ["제5조(목적) 목적.", "① 첫째 항.", "1. 첫째 호", "가. 첫째 목", "② 둘째 항."]
        )
        self.assertEqual(len(chunks), 1)
        for marker in ("① 첫째 항.", "1. 첫째 호", "가. 첫째 목", "② 둘째 항."):
            self.assertIn(marker, chunks[0].text)

    def test_long_article_splits_at_clause_boundaries(self):
        """상한을 넘으면 그때만 갈리고, 경계는 항 머리에 떨어진다."""
        lines = ["제5조(목적) 목적을 정한다."]
        lines += [f"{chr(0x2460 + i)} 제{i}항의 내용을 길게 적은 문장입니다." for i in range(8)]
        chunks = self._chunks(lines, max_chars=120, overlap_chars=0)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertEqual(chunk.outline_path, ("제5조(목적)",), "쪼개져도 같은 조다")
        # 조각 머리가 항 기호(또는 조 제목)로 시작해야 문장 중간에서 잘리지 않은 것이다
        for chunk in chunks[1:]:
            body = chunk.text.split("\n\n", 1)[-1]
            self.assertRegex(body, r"^[①-⑳]", body[:40])

    def test_chunk_carries_its_outline_as_a_prefix(self):
        """조각은 **혼자서도 해석 가능**해야 한다 — 표 조각에 머리행을 반복하는 것과
        같은 이유이고, 임베딩되는 문자열에 들어가야 검색에 걸린다."""
        chunks = self._chunks(["제2장 통칙", "제5조(목적) 목적.", "① 첫째 항.", "제6조(범위) 범위."])
        self.assertTrue(chunks[-1].text.startswith("제2장 통칙\n\n"), chunks[-1].text[:40])

    def test_prefix_is_not_duplicated(self):
        """조 제목으로 시작하는 청크에 자기 이름이 두 번 실리면 안 된다."""
        chunks = self._chunks(["제5조(목적) 목적.", "제6조(범위) 범위."])
        self.assertEqual(chunks[0].text.count("제5조"), 1, chunks[0].text)

    def test_heading_only_paragraph_is_dropped_without_losing_text(self):
        """`제2장 통칙` 여섯 글자는 혼자 검색돼도 아무것도 답하지 못한다. 다만 글자는
        다음 청크의 머리말로 살아남아야 한다."""
        chunks = self._chunks(["제2장 통칙", "제5조(목적) 목적.", "제6조(범위) 범위."])
        self.assertNotIn("제2장 통칙", [c.text for c in chunks])
        self.assertTrue(all("제2장 통칙" in c.text for c in chunks))

    def test_tiny_article_is_not_absorbed_by_the_previous_one(self):
        """짧다는 이유로 앞 조에 붙이면 방금 끊은 조 경계가 되돌려진다."""
        chunks = self._chunks(["제5조(목적) " + "목적을 정한다. " * 8, "제6조(범위) 짧음."])
        self.assertEqual(len(chunks), 2)
        self.assertNotIn("제6조", chunks[0].text)

    def test_prefix_can_be_turned_off(self):
        chunks = self._chunks(["제2장 통칙", "제5조(목적) 목적.", "제6조(범위) 범위."], outline_prefix=False)
        self.assertFalse(chunks[-1].text.startswith("제2장 통칙"))
        self.assertEqual(chunks[-1].outline_path, ("제2장 통칙", "제6조(범위)"), "메타는 남는다")

    def test_ordinary_document_chunking_is_unchanged(self):
        """위계가 없는 문서는 옛 동작 그대로 — 길이 기준으로만 묶인다."""
        body = "".join(_para(f"문단 {i} 입니다.") for i in range(20))
        blocks = parse(_pack(body)).blocks
        options = ChunkOptions(max_chars=120, overlap_chars=0)
        self.assertEqual(
            [c.text for c in chunk_blocks(blocks, options)],
            [c.text for c in chunk_blocks(annotate_outline(blocks), options)],
        )


class VectorRecordTest(unittest.TestCase):
    def test_fields_match_genos_schema(self):
        document = parse(_pack(_para("가") + _long_table(2)))
        records = to_records(
            chunk_blocks(document.blocks),
            file_name="예산.hwpx",
            section_count=document.section_count,
        )
        required = {
            "text", "n_char", "n_word", "n_line",
            "i_page", "e_page", "n_page",
            "i_chunk_on_page", "n_chunk_of_page",
            "i_chunk_on_doc", "n_chunk_of_doc",
            "reg_date", "chunk_bboxes", "media_files",
        }
        self.assertTrue(required.issubset(records[0]), required - set(records[0]))

    def test_page_fields_are_filled_so_the_ui_can_group(self):
        """**비워 두면 GenOS 적재 결과 화면에 이 문서가 안 뜬다** (2026-09-03).

        페이지 자리에는 구역이 들어가고 그 사실을 `page_basis` 가 말한다. 0 이나 `None`
        으로 두면 화면이 청크를 묶지 못한다 — 오류가 아니라 **빈 목록**이라 아무 데도
        안 드러난다.
        """
        document = parse(_pack(_para("가")))
        record = to_records(chunk_blocks(document.blocks), section_count=1)[0]
        self.assertEqual(record["i_page"], 1, "1-based 여야 벤더 pdf 경로와 같은 기준이다")
        self.assertEqual(record["e_page"], 1)
        self.assertEqual(record["n_page"], 1)
        self.assertEqual(record["i_chunk_on_page"], 0, "벤더는 0 부터 센다")
        self.assertEqual(record["n_chunk_of_page"], 1)
        self.assertEqual(record["page_basis"], "section", "숫자의 출처를 말하지 않는다")
        # 벤더가 좌표·미디어를 못 찾았을 때 내는 값과 같아야 한다 (`None` 이 아니다).
        self.assertEqual(record["chunk_bboxes"], "[]")
        self.assertEqual(record["media_files"], "")

    def test_pages_follow_sections_not_a_single_page(self):
        """구역이 여럿이면 페이지도 여럿이다 — 전부 1페이지로 뭉개면 묶음이 사라진다."""
        document = parse(_pack(_para("가"), _para("나"), _para("다")))
        records = to_records(
            chunk_blocks(document.blocks), section_count=document.section_count
        )
        self.assertEqual(
            [r["i_page"] for r in records], [r["i_section"] + 1 for r in records]
        )
        self.assertTrue(all(r["n_page"] == document.section_count for r in records))
        self.assertTrue(all(r["i_page"] <= r["n_page"] for r in records),
                        "페이지 밖을 가리키는 레코드가 있다")

    def test_chunk_index_is_assigned_here(self):
        document = parse(_pack("".join(_para(f"문단 {i} 입니다.") for i in range(10))))
        records = to_records(chunk_blocks(document.blocks, ChunkOptions(max_chars=80)))
        self.assertEqual([r["i_chunk_on_doc"] for r in records], list(range(len(records))))
        self.assertTrue(all(r["n_chunk_of_doc"] == len(records) for r in records))

    def test_extra_fields_are_merged(self):
        document = parse(_pack(_para("가")))
        records = to_records(chunk_blocks(document.blocks), extra={"security_level": "C"})
        self.assertEqual(records[0]["security_level"], "C")

    def test_outline_is_exposed_separately_from_the_text(self):
        """머리말은 임베딩되라고 본문에 붙이고, 이 둘은 출처 표시·조 단위 필터용이다."""
        chunks = chunk_blocks(_statute("제2장 통칙", "제5조(목적) 목적.", "제6조(범위) 범위."))
        record = to_records(chunks)[-1]
        self.assertEqual(record["outline_path"], ["제2장 통칙", "제6조(범위)"])
        self.assertEqual(record["outline_title"], "제6조(범위)")

    def test_ordinary_document_has_no_outline_fields(self):
        """위계가 없으면 키 자체를 만들지 않는다 — 빈 값으로 채우면 조문 문서처럼 읽힌다."""
        record = to_records(chunk_blocks(parse(_pack(_para("가"))).blocks))[0]
        self.assertNotIn("outline_path", record)
        self.assertNotIn("outline_title", record)

    def test_table_part_is_zero_based_and_named_like_the_other_indexes(self):
        """레코드는 `i_table_part`(0-based) + `n_table_part` 다 — `i_page`/`n_page` 규약.

        옛 이름 `table_part` 로는 UI 가 `표 {값}/{총}` 을 그대로 찍어 **첫 조각이
        "표 0/16" 이 되고 "16/16" 은 영영 안 나온다.** 본문 머리말만 1-based 이고,
        그 어긋남은 본문·레코드 어느 쪽도 틀린 티가 안 난다.
        """
        document = parse(_pack(_long_table(12)))
        records = to_records(chunk_blocks(document.blocks, ChunkOptions(max_chars=300)))
        total = len(records)
        self.assertGreater(total, 1, "표가 쪼개지지 않아 이 테스트가 아무것도 안 본다")
        for index, record in enumerate(records):
            self.assertNotIn("table_part", record, "옛 이름이 남아 있다")
            self.assertEqual(record["i_table_part"], index)
            self.assertEqual(record["n_table_part"], total)
            # 본문은 사람이 읽는 자리라 1-based. 두 값이 같은 조각을 가리켜야 한다.
            self.assertTrue(
                record["text"].startswith(f"(표 {record['i_table_part'] + 1}/{total})"),
                record["text"][:40],
            )

    def test_unsplit_table_has_no_part_fields(self):
        """안 쪼갠 표에 1/1 을 달면 "쪼개진 표" 로 읽힌다 — 키 자체를 만들지 않는다."""
        record = to_records(chunk_blocks(parse(_pack(_long_table(2))).blocks))[0]
        self.assertNotIn("i_table_part", record)
        self.assertNotIn("n_table_part", record)

    def test_section_is_taken_from_each_chunks_own_blocks(self):
        """표 뒤에서 새로 시작하는 청크가 **앞 청크의 섹션 번호를 물려받으면 안 된다.**

        옛 코드는 버퍼가 빌 때 `not chunks and not buffer_section` 일 때만 섹션을 잡았다.
        길이 초과로 끊길 때는 따로 갱신하므로 드러나지 않지만, **표를 만나 끊긴 뒤에는
        조건이 거짓이라 값이 앞 섹션에 얼어붙는다** — 검색 결과 출처가 틀린 섹션을
        가리키고, 그 어긋남은 화면에 정상으로 보인다.
        """
        first = _para("섹션0 문단입니다.") + _long_table(2)
        second = "".join(_para(f"섹션1 문단 {i} 입니다.") for i in range(3))
        document = parse(_pack(first, second))
        self.assertEqual(document.section_count, 2)

        records = to_records(
            chunk_blocks(document.blocks, ChunkOptions(max_chars=2000)),
            section_count=document.section_count,
        )
        for record in records:
            expected = 1 if record["text"].startswith("섹션1") else 0
            self.assertEqual(record["i_section"], expected, record["text"][:40])
        self.assertEqual({r["i_section"] for r in records}, {0, 1})

    def test_chunk_never_spans_two_sections(self):
        """구역이 바뀌면 끊는다. 걸치면 `i_section` 이 둘 중 하나만 가리켜 출처가 틀린다.

        예전에는 구역 경계에 표가 있어 **우연히** 끊겼을 뿐이라 드러나지 않았다 —
        1칸 표를 문단으로 내기 시작하면서 그 우연이 사라졌다.
        """
        document = parse(_pack(_para("섹션0 끝 문단."), _para("섹션1 첫 문단.")))
        records = to_records(
            chunk_blocks(document.blocks, ChunkOptions(max_chars=2000)),
            section_count=document.section_count,
        )
        self.assertEqual(len(records), 2, [r["text"] for r in records])
        self.assertEqual([r["i_section"] for r in records], [0, 1])


class DocumentProcessorTest(unittest.TestCase):
    """`docs/GENOS_RULES.md` §F 필수 케이스: 정상/빈 파일/손상 파일/미지원 확장자/파라미터 경계.

    GenOS 가 실제로 호출하는 모양(`DocumentProcessor()` 무인자 생성 → 파일 경로로 호출)을
    그대로 태운다 — `parse()`/`to_records()` 를 직접 부르는 위 테스트들과 달리 파일
    I/O·확장자 검사·예외 계약까지 확인한다.
    """

    def _write(self, data: bytes, suffix: str = ".hwpx") -> str:
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        self.addCleanup(os.remove, path)
        return path

    def _run(self, path: str, **kwargs):
        processor = DocumentProcessor()
        return asyncio.run(processor(None, path, **kwargs))

    def test_normal_file_returns_records_with_text(self):
        path = self._write(_pack(_para("가") + _long_table(2) + _para("나")))
        records = self._run(path, file_name="예산.hwpx")
        self.assertGreater(len(records), 0)
        for record in records:
            self.assertTrue(record["text"])
        self.assertEqual(records[0]["file_name"], "예산.hwpx")

    def test_empty_file_raises_explicit_error_not_empty_list(self):
        path = self._write(b"")
        with self.assertRaises(HwpxParseError):
            self._run(path)

    def test_corrupted_file_raises(self):
        path = self._write(b"this is not a zip file")
        with self.assertRaises(HwpxParseError):
            self._run(path)

    def test_unsupported_extension_raises(self):
        path = self._write(_pack(_para("가")), suffix=".docx")
        with self.assertRaises(HwpxParseError):
            self._run(path)

    def test_textless_document_raises_not_empty_list(self):
        """유효한 zip/XML 이지만 본문이 전혀 없으면 빈 목록이 아니라 명시적 오류."""
        path = self._write(_pack(""))
        with self.assertRaises(HwpxParseError):
            self._run(path)

    def test_invalid_chunk_size_falls_back_to_default(self):
        """등록 화면 파라미터 입력 실수(문자열/빈 값)가 재적재를 막지 않는다."""
        path = self._write(_pack(_para("가")))
        records = self._run(path, chunk_size="not-a-number")
        self.assertGreater(len(records), 0)

    def test_statute_document_is_chunked_by_article_end_to_end(self):
        """GenOS 가 부르는 모양 그대로 — 조문 문서는 별도 설정 없이 조 단위로 갈린다."""
        path = self._write(
            _pack(
                _para("제2장 통칙")
                + _para("제5조(목적) 이 규칙의 목적을 정한다.")
                + _para("① 첫째 항이다.")
                + _para("제6조(적용범위) 전 직원에게 적용한다.")
            )
        )
        records = self._run(path)
        self.assertEqual([r["outline_title"] for r in records], ["제5조(목적)", "제6조(적용범위)"])
        self.assertTrue(all(r["text"].startswith("제2장 통칙") for r in records))

    def test_outline_mode_off_restores_length_only_chunking(self):
        path = self._write(
            _pack(_para("제5조(목적) 목적을 정한다.") + _para("제6조(적용범위) 전 직원에게 적용한다."))
        )
        records = self._run(path, outline_mode="off")
        self.assertEqual(len(records), 1, "위계를 끄면 길이 기준으로 한 청크에 들어간다")
        self.assertNotIn("outline_path", records[0])

    def test_invalid_outline_mode_falls_back_to_default(self):
        """등록 화면 파라미터 오타가 재적재를 막지 않는다."""
        path = self._write(
            _pack(_para("제5조(목적) 목적을 정한다.") + _para("제6조(적용범위) 전 직원에게 적용한다."))
        )
        records = self._run(path, outline_mode="   STATUTE  ")
        self.assertEqual(len(records), 2, "공백·대문자는 정규화되어 statute 로 읽힌다")

    def test_overlap_not_smaller_than_chunk_size_does_not_hang(self):
        """overlap_chars >= max_chars 면 문자 분할 예외 경로가 무한 루프에 빠질 수 있다 —
        `ChunkOptions.__post_init__` 이 막는다. 경계값 파라미터 테스트."""
        sentence = "본 사업은 2026년에 완료하였습니다. "
        path = self._write(_pack(_para(sentence * 50)))
        records = self._run(path, chunk_size=50, chunk_overlap=50)
        self.assertGreater(len(records), 0)


class NothingIsDuplicatedTest(unittest.TestCase):
    """**같은 글자를 두 번 싣지도 않는다** — 위 `NothingIsDroppedTest` 의 짝이다.

    셀 안 글상자·각주를 되살리려고 `_cell_parts` 에 상자 갈래를 넣으면서 생긴 자리다.
    표(`hp:tbl`)는 상자가 아니라서, 중첩 표의 셀에서 위로 올라가면 표를 지나쳐 **바깥
    셀이 소유자로 잡힌다.** 그래서 바깥 셀이 중첩 표를 표로 한 번 내고 그 표의 셀들을
    상자로 또 펴, 같은 값이 두 번 실렸다. 표 격자는 멀쩡해서 눈으로는 정상처럼 보인다.
    """

    def _nested_cell_table(self) -> bytes:
        inner_rows = f'<hp:tr>{_cell(0, 0, _para("소분류"))}{_cell(0, 1, _para("값"))}</hp:tr>'
        inner = f"<hp:p><hp:run><hp:tbl>{inner_rows}</hp:tbl></hp:run></hp:p>"
        rows = f'<hp:tr>{_cell(0, 0, _para("구분"))}{_cell(0, 1, _para("세부") + inner)}</hp:tr>'
        return _pack(f"<hp:p><hp:run><hp:tbl>{rows}</hp:tbl></hp:run></hp:p>")

    def test_nested_table_cells_are_not_emitted_twice(self):
        text = parse(self._nested_cell_table()).blocks[0].text
        self.assertEqual(text.count("소분류"), 1, text)
        self.assertEqual(text.count("값"), 1, text)

    def test_nested_table_stays_a_table(self):
        """중복을 없애면서 중첩 표를 통째로 잃지 않았는지 함께 본다."""
        text = parse(self._nested_cell_table()).blocks[0].text
        self.assertEqual(text.count("<table>"), 2, text)
        self.assertIn("<th>세부<table>", text)

    def test_box_inside_a_cell_is_still_flattened_once(self):
        """셀 안 글상자는 셀 글자로 펴진다 — 그 갈래를 죽이지 않았는지 본다."""
        box = f'<hp:p><hp:run><hp:drawText><hp:subList>{_para("메모")}</hp:subList>'
        box += "</hp:drawText></hp:run></hp:p>"
        rows = f'<hp:tr>{_cell(0, 0, _para("구분"))}{_cell(0, 1, _para("세부") + box)}</hp:tr>'
        text = parse(_pack(f"<hp:p><hp:run><hp:tbl>{rows}</hp:tbl></hp:run></hp:p>")).blocks[0].text
        self.assertEqual(text.count("메모"), 1, text)


class NothingIsDroppedTest(unittest.TestCase):
    """**문서에 보이는 글자는 하나도 버리지 않는다.**

    여기 모인 것은 전부 "예외를 던지지 않고 조용히 사라지던" 손실이다. 표가 깨지는
    것과 달리 **없어진 자리에 아무 흔적이 안 남아**, 그 문장을 물어봤을 때 검색이
    아무것도 못 찾을 때까지 드러나지 않는다. 그래서 손실마다 판정을 하나씩 세운다.
    """

    def _box(self, tag: str, body: str) -> str:
        """상자 하나. **문단으로 감싸지 않는다** — 감싸는 자리는 호출부마다 다르다
        (도형은 `hp:rect` 안, 각주·머리말은 `hp:ctrl` 안)."""
        return f"<hp:{tag}><hp:subList>{body}</hp:subList></hp:{tag}>"

    def test_text_after_a_tab_survives(self):
        """`hp:t` 는 혼합 내용이다 — 탭 **뒤** 글자는 자식의 `tail` 에 있다."""
        body = "<hp:p><hp:run><hp:t>가.<hp:tab/>지원 대상</hp:t></hp:run></hp:p>"
        self.assertEqual([b.text for b in parse(_pack(body)).blocks], ["가. 지원 대상"])

    def test_line_break_does_not_glue_words_together(self):
        """강제 줄바꿈을 그냥 버리면 `첫 줄둘째 줄` 이 된다."""
        body = "<hp:p><hp:run><hp:t>첫 줄<hp:lineBreak/>둘째 줄</hp:t></hp:run></hp:p>"
        self.assertEqual([b.text for b in parse(_pack(body)).blocks], ["첫 줄 둘째 줄"])

    def test_typographic_spaces_and_hyphen_survive(self):
        body = (
            "<hp:p><hp:run><hp:t>제1장<hp:nbSpace/>총칙"
            "<hp:fwSpace/>2026<hp:hyphen/>08</hp:t></hp:run></hp:p>"
        )
        self.assertEqual(
            [b.text for b in parse(_pack(body)).blocks], ["제1장 총칙\u30002026-08"]
        )

    def test_text_box_is_a_paragraph_not_a_hole(self):
        """글상자·도형 안 글은 본문과 같은 글이다 — 라벨 없이 문단으로 낸다."""
        inner = self._box("drawText", _para("추진 배경 및 필요성"))
        body = f"<hp:p><hp:run><hp:rect>{inner}</hp:rect></hp:run></hp:p>"
        self.assertEqual(
            [b.text for b in parse(_pack(body)).blocks], ["추진 배경 및 필요성"]
        )

    def test_footnote_is_kept_with_a_label(self):
        """각주는 본문 흐름 밖이라 라벨을 붙인다 — 없으면 본문 문장으로 읽힌다."""
        note = self._box("footNote", _para("근거: 정보통신망법 제3조"))
        body = f"<hp:p><hp:run><hp:t>본문 문장</hp:t><hp:ctrl>{note}</hp:ctrl></hp:run></hp:p>"
        self.assertEqual(
            [b.text for b in parse(_pack(body)).blocks],
            ["본문 문장", "[각주] 근거: 정보통신망법 제3조"],
        )

    def test_page_header_and_footer_are_kept(self):
        """머리말·꼬리말은 섹션당 한 번 정의된다 — 페이지마다 반복되지 않는다."""
        header = self._box("header", _para("대외비"))
        footer = self._box("footer", _para("신용회복위원회"))
        body = f"<hp:p><hp:run><hp:ctrl>{header}{footer}</hp:ctrl></hp:run></hp:p>"
        self.assertEqual(
            [b.text for b in parse(_pack(body)).blocks],
            ["[머리말] 대외비", "[꼬리말] 신용회복위원회"],
        )

    def test_hidden_comment_and_memo_are_kept(self):
        hidden = self._box("hiddenComment", _para("검토 필요"))
        memo = self._box("memo", _para("2차 회의 반영"))
        body = f"<hp:p><hp:run><hp:ctrl>{hidden}{memo}</hp:ctrl></hp:run></hp:p>"
        self.assertEqual(
            [b.text for b in parse(_pack(body)).blocks],
            ["[숨은 설명] 검토 필요", "[메모] 2차 회의 반영"],
        )

    def test_equation_text_is_kept(self):
        """수식은 `hp:t` 가 아니라 `hp:script` 에 있다 — 한 문단의 뜻이 걸린다."""
        body = (
            "<hp:p><hp:run><hp:t>산출식: </hp:t>"
            "<hp:equation><hp:script>ROI = (P - C) / C</hp:script></hp:equation>"
            "</hp:run></hp:p>"
        )
        self.assertEqual(
            [b.text for b in parse(_pack(body)).blocks], ["산출식: ROI = (P - C) / C"]
        )

    def test_table_caption_comes_before_the_table(self):
        """캡션은 표의 제목이다 — 앞에 두면 `_table_title_of` 가 조각마다 이고 간다."""
        caption = f"<hp:caption><hp:subList>{_para('[표 1] 사업 개요')}</hp:subList></hp:caption>"
        row = f"<hp:tr>{_cell(0, 0, _para('가'))}{_cell(0, 1, _para('나'))}</hp:tr>"
        body = f"<hp:p><hp:run><hp:tbl>{caption}{row}</hp:tbl></hp:run></hp:p>"
        blocks = parse(_pack(body)).blocks
        self.assertEqual([b.kind for b in blocks], ["paragraph", "table"])
        self.assertEqual(blocks[0].text, "[표 1] 사업 개요")

    def test_caption_is_not_emitted_twice(self):
        """캡션은 표에 달린 것이라, 문단이 따로 또 내면 같은 글자가 두 번 실린다."""
        caption = f"<hp:caption><hp:subList>{_para('[표 1] 개요')}</hp:subList></hp:caption>"
        row = f"<hp:tr>{_cell(0, 0, _para('가'))}{_cell(0, 1, _para('나'))}</hp:tr>"
        body = f"<hp:p><hp:run><hp:tbl>{caption}{row}</hp:tbl></hp:run></hp:p>"
        texts = [b.text for b in parse(_pack(body)).blocks]
        self.assertEqual(texts.count("[표 1] 개요"), 1)

    def test_text_box_inside_a_cell_stays_in_that_cell(self):
        """셀 안 글상자를 셀 밖으로 내면 그 글이 어느 칸의 것인지 사라진다."""
        inner = self._box("drawText", _para("단서 조항"))
        body = f"<hp:p><hp:run><hp:t>본칙</hp:t><hp:rect>{inner}</hp:rect></hp:run></hp:p>"
        row = f"<hp:tr>{_cell(0, 0, body)}{_cell(0, 1, _para('나'))}</hp:tr>"
        blocks = parse(_pack(f"<hp:p><hp:run><hp:tbl>{row}</hp:tbl></hp:run></hp:p>")).blocks
        self.assertEqual([b.kind for b in blocks], ["table"])
        self.assertIn("본칙<br>단서 조항", blocks[0].text)

    def test_footnote_inside_a_cell_keeps_its_label(self):
        note = self._box("footNote", _para("각주 하나"))
        body = f"<hp:p><hp:run><hp:t>본칙</hp:t><hp:ctrl>{note}</hp:ctrl></hp:run></hp:p>"
        row = f"<hp:tr>{_cell(0, 0, body)}{_cell(0, 1, _para('나'))}</hp:tr>"
        blocks = parse(_pack(f"<hp:p><hp:run><hp:tbl>{row}</hp:tbl></hp:run></hp:p>")).blocks
        self.assertIn("[각주] 각주 하나", blocks[0].text)

    def test_table_inside_a_text_box_stays_a_table(self):
        """글상자 안 표를 글자로 펴면 그 수치가 무엇의 값인지 사라진다."""
        row = f"<hp:tr>{_cell(0, 0, _para('항목'))}{_cell(0, 1, _para('120'))}</hp:tr>"
        nested = f"<hp:p><hp:run><hp:tbl>{row}</hp:tbl></hp:run></hp:p>"
        inner = self._box("drawText", _para("요약") + nested)
        body = f"<hp:p><hp:run><hp:rect>{inner}</hp:rect></hp:run></hp:p>"
        blocks = parse(_pack(body)).blocks
        self.assertEqual([b.kind for b in blocks], ["paragraph", "table"])
        self.assertIn("<th>120</th>", blocks[1].text)

    def test_box_text_joins_the_outline_ladder(self):
        """글상자 안 조문도 위계로 읽혀야 한다 — 버리던 시절에는 아예 못 봤다."""
        inner = self._box("drawText", _para("제5조(목적) 목적을 정한다."))
        body = f"<hp:p><hp:run><hp:rect>{inner}</hp:rect></hp:run></hp:p>"
        body += _para("제6조(범위) 범위를 정한다.")
        blocks = annotate_outline(parse(_pack(body)).blocks)
        self.assertEqual([b.outline_level for b in blocks], [5, 5])


class AutoNumberTest(unittest.TestCase):
    """자동 번호·글머리표 — **문서에 보이는데 본문 XML 에는 없는 글자.**

    개요 번호(`1.`·`가.`)와 글머리표(`-`)는 문단 텍스트가 아니라 `Contents/header.xml`
    의 정의를 문단 모양이 가리켜 만들어진다. 복원하지 않으면 목록이라는 사실과 항목의
    층위가 함께 사라진다 — 남은 문장들은 멀쩡해 보여서 무엇이 빠졌는지 알 수 없다.
    """

    BULLET_HEADER = (
        f'<hh:head xmlns:hh="{HH}"><hh:refList>'
        '<hh:bullets><hh:bullet id="2" char="-"/></hh:bullets>'
        '<hh:paraProperties>'
        '<hh:paraPr id="7"><hh:heading type="BULLET" idRef="2" level="0"/></hh:paraPr>'
        '</hh:paraProperties></hh:refList></hh:head>'
    )

    NUMBER_HEADER = (
        f'<hh:head xmlns:hh="{HH}"><hh:refList>'
        '<hh:numberings><hh:numbering id="1">'
        '<hh:paraHead level="1" start="1" numFormat="DIGIT">^1.</hh:paraHead>'
        '<hh:paraHead level="2" start="1" numFormat="HANGUL_SYLLABLE">^2.</hh:paraHead>'
        '<hh:paraHead level="3" start="1" numFormat="DIGIT">(^3)</hh:paraHead>'
        '<hh:paraHead level="4" start="1" numFormat="CIRCLED_DIGIT"/>'
        '</hh:numbering></hh:numberings>'
        '<hh:paraProperties>'
        '<hh:paraPr id="10"><hh:heading type="OUTLINE" idRef="1" level="0"/></hh:paraPr>'
        '<hh:paraPr id="11"><hh:heading type="OUTLINE" idRef="1" level="1"/></hh:paraPr>'
        '<hh:paraPr id="12"><hh:heading type="OUTLINE" idRef="1" level="2"/></hh:paraPr>'
        '<hh:paraPr id="13"><hh:heading type="OUTLINE" idRef="1" level="3"/></hh:paraPr>'
        '<hh:paraPr id="99"><hh:heading type="NONE" idRef="0" level="0"/></hh:paraPr>'
        '</hh:paraProperties></hh:refList></hh:head>'
    )

    # `heading/@level + 1` 이 정의에 **없는** 헤더. 정의된 단계를 순서대로 늘어놓고
    # `@level` 을 인덱스로 봐야 번호가 나온다 — 안 하면 번호가 통째로 빠진다.
    OFFSET_HEADER = (
        f'<hh:head xmlns:hh="{HH}"><hh:refList>'
        '<hh:numberings><hh:numbering id="1">'
        '<hh:paraHead level="3" start="1" numFormat="DIGIT">[^3]</hh:paraHead>'
        '<hh:paraHead level="4" start="1" numFormat="HANGUL_SYLLABLE">[^4]</hh:paraHead>'
        '</hh:numbering></hh:numberings>'
        '<hh:paraProperties>'
        '<hh:paraPr id="10"><hh:heading type="OUTLINE" idRef="1" level="0"/></hh:paraPr>'
        '<hh:paraPr id="11"><hh:heading type="OUTLINE" idRef="1" level="1"/></hh:paraPr>'
        '</hh:paraProperties></hh:refList></hh:head>'
    )

    # 단계 정의가 **하나뿐인** 헤더. 그 아래 단계를 가리키는 문단은 "번호는 그려지는데
    # 서식을 모르는" 상태다 — 비워 두면 목록이라는 사실과 층위가 통째로 사라진다.
    SPARSE_HEADER = (
        f'<hh:head xmlns:hh="{HH}"><hh:refList>'
        '<hh:numberings><hh:numbering id="1">'
        '<hh:paraHead level="1" start="1" numFormat="DIGIT">^1.</hh:paraHead>'
        '</hh:numbering></hh:numberings>'
        '<hh:paraProperties>'
        '<hh:paraPr id="10"><hh:heading type="OUTLINE" idRef="1" level="0"/></hh:paraPr>'
        '<hh:paraPr id="11"><hh:heading type="OUTLINE" idRef="1" level="1"/></hh:paraPr>'
        '</hh:paraProperties></hh:refList></hh:head>'
    )

    # 표시 문자열이 줄바꿈·들여쓰기와 함께 저장된 헤더(보기 좋게 저장된 문서).
    PRETTY_HEADER = NUMBER_HEADER.replace(
        'numFormat="DIGIT">^1.</hh:paraHead>',
        'numFormat="DIGIT">' + chr(10) + '        ^1.' + chr(10) + '      </hh:paraHead>',
    )

    def _with(self, header, *pairs) -> list:
        body = "".join(
            f'<hp:p paraPrIDRef="{ref}"><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>'
            for ref, text in pairs
        )
        return [b.text for b in parse(_pack(body, header=header)).blocks]

    def test_offset_level_definition_falls_back_to_position(self):
        """`@level + 1` 이 정의에 없으면 정의 순서로 맞춘다."""
        self.assertEqual(
            self._with(self.OFFSET_HEADER, ("10", "개요"), ("11", "하위")),
            ["[1] 개요", "[가] 하위"],
        )

    def test_undefined_level_falls_back_to_a_number(self):
        """정의에 없는 단계에서 빈 문자열을 돌려주면 번호가 조용히 사라진다."""
        self.assertEqual(
            self._with(self.SPARSE_HEADER, ("10", "개요"), ("11", "하위")),
            ["1. 개요", "1. 하위"],
        )

    def test_pretty_printed_template_is_stripped(self):
        """헤더가 들여쓰기와 함께 저장돼 있으면 번호 앞에 개행이 붙는다."""
        self.assertEqual(self._with(self.PRETTY_HEADER, ("10", "개요")), ["1. 개요"])

    def _numbered(self, *pairs) -> list:
        body = "".join(
            f'<hp:p paraPrIDRef="{ref}"><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>'
            for ref, text in pairs
        )
        return [b.text for b in parse(_pack(body, header=self.NUMBER_HEADER)).blocks]

    def test_bullet_character_is_restored(self):
        body = (
            '<hp:p paraPrIDRef="7"><hp:run><hp:t>문서를 업로드한다</hp:t></hp:run></hp:p>'
            '<hp:p paraPrIDRef="7"><hp:run><hp:t>보안을 해제한다</hp:t></hp:run></hp:p>'
        )
        document = parse(_pack(body, header=self.BULLET_HEADER))
        self.assertEqual(
            [b.text for b in document.blocks], ["- 문서를 업로드한다", "- 보안을 해제한다"]
        )

    def test_numbers_count_up_and_deeper_levels_restart(self):
        self.assertEqual(
            self._numbered(
                ("10", "총칙"),
                ("11", "목적"),
                ("12", "세부"),
                ("12", "세부2"),
                ("11", "범위"),
                ("10", "본칙"),
            ),
            ["1. 총칙", "가. 목적", "(1) 세부", "(2) 세부2", "나. 범위", "2. 본칙"],
        )

    def test_paragraphs_without_a_heading_get_nothing(self):
        self.assertEqual(self._numbered(("99", "보통 문단")), ["보통 문단"])

    def test_level_without_a_display_string_adds_nothing(self):
        """복원할 수 없는 단계는 **비워 둔다** — 틀린 번호를 붙이는 것보다 낫다."""
        self.assertEqual(self._numbered(("13", "네 번째 단계")), ["네 번째 단계"])

    def test_empty_paragraph_still_consumes_a_number(self):
        """빈 문단을 건너뛰면 그 뒤 번호가 전부 하나씩 밀린다."""
        body = (
            '<hp:p paraPrIDRef="10"><hp:run><hp:t>첫째</hp:t></hp:run></hp:p>'
            '<hp:p paraPrIDRef="10"><hp:run><hp:t></hp:t></hp:run></hp:p>'
            '<hp:p paraPrIDRef="10"><hp:run><hp:t>셋째</hp:t></hp:run></hp:p>'
        )
        document = parse(_pack(body, header=self.NUMBER_HEADER))
        self.assertEqual([b.text for b in document.blocks], ["1. 첫째", "3. 셋째"])

    def test_numbering_reaches_paragraphs_inside_cells(self):
        cell = _cell(0, 0, '<hp:p paraPrIDRef="10"><hp:run><hp:t>셀 항목</hp:t></hp:run></hp:p>')
        row = f"<hp:tr>{cell}{_cell(0, 1, _para('나'))}</hp:tr>"
        body = f"<hp:p><hp:run><hp:tbl>{row}</hp:tbl></hp:run></hp:p>"
        document = parse(_pack(body, header=self.NUMBER_HEADER))
        self.assertIn("1. 셀 항목", document.blocks[0].text)

    def test_document_without_header_xml_still_parses(self):
        """`Contents/header.xml` 이 없는 문서에서도 파싱은 그대로 돌아야 한다."""
        body = '<hp:p paraPrIDRef="10"><hp:run><hp:t>번호 정의가 없다</hp:t></hp:run></hp:p>'
        self.assertEqual([b.text for b in parse(_pack(body)).blocks], ["번호 정의가 없다"])

    def test_broken_header_xml_does_not_block_the_body(self):
        """머리 정의를 못 읽는 것으로 본문 적재를 막지 않는다 — 번호만 빠진다."""
        body = '<hp:p paraPrIDRef="10"><hp:run><hp:t>본문은 살아야 한다</hp:t></hp:run></hp:p>'
        document = parse(_pack(body, header="<hh:head>닫히지 않은"))
        self.assertEqual([b.text for b in document.blocks], ["본문은 살아야 한다"])

    # 실물 한/글이 내는 모양 — `hh:numbering/@id` 는 **1 부터**인데 헤딩은 `idRef="0"`
    # 을 쓴다. 위 `NUMBER_HEADER` 는 손으로 지은 것이라 둘이 맞아 있어서(id=1 ↔ idRef=1)
    # **id 로만 찾는 옛 코드도 통과했다** — 실물에서는 번호가 전부 사라지는데 그물에는
    # 걸리지 않았다. 그래서 실물 모양을 따로 둔다. 저장소 hwpx 4벌이 전부 이 모양이다.
    REAL_NUMBER_HEADER = NUMBER_HEADER.replace('idRef="1"', 'idRef="0"')

    REAL_BULLET_HEADER = (
        f'<hh:head xmlns:hh="{HH}"><hh:refList>'
        '<hh:bullets><hh:bullet id="1" char="●"/></hh:bullets>'
        '<hh:paraProperties>'
        '<hh:paraPr id="7"><hh:heading type="BULLET" idRef="0" level="0"/></hh:paraPr>'
        '</hh:paraProperties></hh:refList></hh:head>'
    )

    # `@char` 가 없는 글머리표(이미지 글머리표). 화면에는 그려지는데 글자를 모른다.
    IMAGE_BULLET_HEADER = REAL_BULLET_HEADER.replace(' char="●"', "")

    # `4294967295` = 한/글이 "없음" 을 뜻하는 sentinel. 인덱스로 읽으면 안 된다.
    SENTINEL_HEADER = NUMBER_HEADER.replace('idRef="1"', f'idRef="{ID_NONE}"')

    # 문단 모양은 번호를 쓴다고 하는데 번호 정의가 없는 문서.
    NO_DEFINITION_HEADER = (
        f'<hh:head xmlns:hh="{HH}"><hh:refList><hh:paraProperties>'
        '<hh:paraPr id="10"><hh:heading type="OUTLINE" idRef="0" level="0"/></hh:paraPr>'
        '</hh:paraProperties></hh:refList></hh:head>'
    )

    def _with(self, header: str, *pairs) -> list:
        body = "".join(
            f'<hp:p paraPrIDRef="{ref}"><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>'
            for ref, text in pairs
        )
        return [b.text for b in parse(_pack(body, header=header)).blocks]

    def test_real_documents_reference_numbering_by_index(self):
        """실물은 `idRef="0"` 인데 `@id` 는 1 부터다 — id 로만 찾으면 번호가 통째로 빠진다."""
        self.assertEqual(
            self._with(
                self.REAL_NUMBER_HEADER,
                ("10", "총칙"),
                ("11", "목적"),
                ("11", "범위"),
                ("10", "본칙"),
            ),
            ["1. 총칙", "가. 목적", "나. 범위", "2. 본칙"],
        )

    def test_real_documents_reference_bullets_by_index(self):
        """글머리표도 같은 off-by-one 이다 — 실물 표본이 없어 모양만 맞춰 지킨다."""
        self.assertEqual(
            self._with(self.REAL_BULLET_HEADER, ("7", "문서를 업로드한다")),
            ["● 문서를 업로드한다"],
        )

    def test_bullet_without_a_character_still_marks_the_item(self):
        """이미지 글머리표는 **그려지는데 글자만 모른다** — 비우면 목록이라는 사실이 사라진다."""
        self.assertEqual(
            self._with(self.IMAGE_BULLET_HEADER, ("7", "문서를 업로드한다")),
            ["- 문서를 업로드한다"],
        )

    def test_numbering_without_a_definition_falls_back_to_digits(self):
        """정의를 못 찾으면 숫자로 낸다 — 표시 문자열이 **빈** 단계와 다른 경우다.

        빈 단계는 한/글도 아무것도 그리지 않아 비우는 것이 원문에 맞고
        (`test_level_without_a_display_string_adds_nothing`), 이쪽은 무언가 그려지는데
        무엇인지 모르는 것이라 비우면 그 자리가 통째로 사라진다.
        """
        self.assertEqual(
            self._with(self.NO_DEFINITION_HEADER, ("10", "첫째"), ("10", "둘째")),
            ["1. 첫째", "2. 둘째"],
        )

    def test_none_sentinel_is_not_read_as_an_index(self):
        """`4294967295` 는 "정의 없음" 이다 — 인덱스로 읽으면 안 그리는 자리에 번호가 생긴다."""
        self.assertEqual(self._with(self.SENTINEL_HEADER, ("10", "번호 없음")), ["번호 없음"])

    def test_two_refs_to_one_definition_share_the_counter(self):
        """id 와 인덱스로 같은 정의에 닿은 두 문단 모양은 **한 목록**이다.

        원본 `idRef` 로 카운터를 들면 `1. 1. 2.` 가 나온다 — 번호가 있는데 틀린 상태라
        빠진 것보다 알아채기 어렵다.
        """
        header = self.NUMBER_HEADER.replace(
            '<hh:paraPr id="99">',
            '<hh:paraPr id="20"><hh:heading type="OUTLINE" idRef="0" level="0"/></hh:paraPr>'
            '<hh:paraPr id="99">',
        )
        self.assertEqual(
            self._with(header, ("10", "하나"), ("20", "둘"), ("10", "셋")),
            ["1. 하나", "2. 둘", "3. 셋"],
        )

    def test_restored_numbers_feed_the_outline_ladder(self):
        """번호를 잃으면 호(`1.`)가 본문 문단으로 떨어진다 — 청크 경계가 달라진다."""
        body = (
            _para("제5조(목적) 목적을 정한다.")
            + '<hp:p paraPrIDRef="10"><hp:run><hp:t>적용 대상</hp:t></hp:run></hp:p>'
        )
        blocks = annotate_outline(parse(_pack(body, header=self.NUMBER_HEADER)).blocks, "statute")
        self.assertEqual([b.outline_level for b in blocks], [5, 7])


if __name__ == "__main__":
    unittest.main()
