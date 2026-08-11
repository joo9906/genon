"""onprem/preprocessor — 파싱·청킹·VDB 레코드.

실행: `cd SFR-018 && python -m unittest discover -s tests -t .`

이 패키지는 **아직 어디에도 배선돼 있지 않다** (나중 RAG 적재용). 그래서 회귀 테스트가
더 필요하다 — 쓰이지 않는 코드는 조용히 썩고, 붙이는 시점에는 이미 왜 이렇게 만들었는지
아무도 기억하지 못한다.

## 무엇을 지키나

가장 중요한 것은 **표를 쪼갤 때 행이 새지 않는 것**이다. 한 행이 사라져도 남은 표는
문법적으로 멀쩡해서 눈으로는 안 보인다 — 검색 결과에 그 행만 영영 안 나올 뿐이다.
"""

import io
import os
import sys
import unittest
import zipfile

from . import onprem_path  # noqa: F401

# preprocessor 는 배포 단위가 아니라 onprem 바로 아래 패키지다.
sys.path.insert(0, onprem_path.ONPREM)

from preprocessor import (  # noqa: E402
    ChunkOptions,
    chunk_blocks,
    parse,
    to_records,
)

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"


def _para(text: str) -> str:
    return f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"


def _cell(row: int, col: int, body: str, *, row_span: int = 1, col_span: int = 1) -> str:
    return (
        f'<hp:tc><hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
        f'<hp:cellSpan colSpan="{col_span}" rowSpan="{row_span}"/>'
        f"<hp:subList>{body}</hp:subList></hp:tc>"
    )


def _pack(body: str) -> bytes:
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<hs:sec xmlns:hp="{HP}" xmlns:hs="{HS}">{body}</hs:sec>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("Contents/section0.xml", section.encode("utf-8"))
    return buf.getvalue()


def _long_markdown_table(rows: int) -> str:
    body = "".join(
        f'<hp:tr>{_cell(i, 0, _para(f"항목{i}"))}'
        f'{_cell(i, 1, _para(f"{i * 100}"))}'
        f'{_cell(i, 2, _para("비고 문구입니다"))}</hp:tr>'
        for i in range(rows)
    )
    return f"<hp:p><hp:run><hp:tbl>{body}</hp:tbl></hp:run></hp:p>"


def _merged_table() -> str:
    body = (
        f'<hp:tr>{_cell(0, 0, _para("구분"), row_span=2)}'
        f'{_cell(0, 1, _para("실적"), col_span=2)}</hp:tr>'
        f'<hp:tr>{_cell(1, 1, _para("상반기"))}{_cell(1, 2, _para("하반기"))}</hp:tr>'
    )
    return f"<hp:p><hp:run><hp:tbl>{body}</hp:tbl></hp:run></hp:p>"


class ParseTest(unittest.TestCase):
    def test_blocks_keep_document_order(self):
        data = _pack(_para("머리말") + _long_markdown_table(3) + _para("맺음말"))
        document = parse(data)
        self.assertEqual(
            [(b.kind, b.text[:3]) for b in document.blocks],
            [("paragraph", "머리말"), ("table", "| 항"), ("paragraph", "맺음말")],
        )

    def test_table_format_is_recorded(self):
        document = parse(_pack(_long_markdown_table(2) + _merged_table()))
        self.assertEqual([b.table_format for b in document.blocks], ["markdown", "html"])

    def test_counts(self):
        document = parse(_pack(_para("가") + _long_markdown_table(2) + _para("나")))
        self.assertEqual(document.paragraph_count, 2)
        self.assertEqual(document.table_count, 1)
        self.assertEqual(document.section_count, 1)

    def test_to_markdown_matches_deployed_shape(self):
        """블록 사이 빈 줄 — 배포된 세 사본이 내던 문자열과 같은 모양."""
        document = parse(_pack(_para("가") + _para("나")))
        self.assertEqual(document.to_markdown(), "가\n\n나")


class TableChunkingTest(unittest.TestCase):
    """표를 쪼갤 때의 계약. **행이 새면 안 된다.**"""

    def test_small_table_is_one_chunk(self):
        document = parse(_pack(_long_markdown_table(3)))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=2000))
        self.assertEqual(len(chunks), 1)
        self.assertIsNone(chunks[0].table_part)

    def test_markdown_split_loses_no_rows(self):
        """모든 데이터 행이 정확히 한 번씩 남아야 한다."""
        document = parse(_pack(_long_markdown_table(12)))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=300))
        self.assertGreater(len(chunks), 1, "쪼개지지 않았다면 이 테스트가 무의미하다")

        joined = "\n".join(c.text for c in chunks)
        # 0번은 머리행이라 조각마다 반복되는 것이 정상이다 (그게 이 분할의 요점이다).
        for index in range(1, 12):
            self.assertEqual(
                joined.count(f"| 항목{index} |"), 1,
                f"항목{index} 행이 {joined.count(f'| 항목{index} |')}번 나온다 (1번이어야 한다)",
            )
        # 머리행은 조각 수만큼 나와야 한다 — 한 번만 나오면 반복이 안 된 것이다
        self.assertEqual(joined.count("| 항목0 |"), len(chunks))

    def test_markdown_split_repeats_header(self):
        """조각마다 머리행이 있어야 **혼자서도 해석 가능**하다."""
        document = parse(_pack(_long_markdown_table(12)))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=300))
        for chunk in chunks:
            lines = chunk.text.splitlines()
            self.assertTrue(lines[1].startswith("|---"), f"구분선이 없다: {lines[:2]}")

    def test_split_chunks_report_their_part(self):
        """쪼갰다는 사실을 숨기지 않는다 — 조각만 보고 '표가 이게 전부' 로 읽으면 안 된다."""
        document = parse(_pack(_long_markdown_table(12)))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=300))
        total = len(chunks)
        self.assertEqual(
            [c.table_part for c in chunks],
            [(i, total) for i in range(total)],
        )

    def test_html_split_keeps_rows_and_header(self):
        rows = "".join(
            f'<hp:tr>{_cell(i, 0, _para(f"행{i}"), row_span=(2 if i == 0 else 1))}'
            f'{_cell(i, 1, _para(f"값{i} 설명이 붙은 긴 셀 내용"))}</hp:tr>'
            for i in range(10)
        )
        document = parse(_pack(f"<hp:p><hp:run><hp:tbl>{rows}</hp:tbl></hp:run></hp:p>"))
        self.assertEqual(document.blocks[0].table_format, "html")

        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=300))
        self.assertGreater(len(chunks), 1)
        joined = "\n".join(c.text for c in chunks)
        for index in range(1, 10):  # 0번은 머리행이라 조각마다 반복된다
            self.assertEqual(joined.count(f"<td>행{index}</td>"), 1)
        for chunk in chunks:
            self.assertTrue(chunk.text.startswith("<table><tbody>"))
            self.assertTrue(chunk.text.endswith("</tbody></table>"))
            self.assertIn("행0", chunk.text, "머리행이 조각마다 반복돼야 한다")

    def test_table_never_merges_with_paragraph(self):
        """표를 문단 꼬리에 붙이면 검색 결과가 읽기 어려워진다."""
        document = parse(_pack(_para("짧은 머리말") + _long_markdown_table(2)))
        chunks = chunk_blocks(document.blocks, ChunkOptions(max_chars=2000))
        self.assertEqual([c.kind for c in chunks], ["paragraph", "table"])


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


class VectorRecordTest(unittest.TestCase):
    def test_fields_match_genos_schema(self):
        document = parse(_pack(_para("가") + _long_markdown_table(2)))
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

    def test_page_fields_are_none_not_zero(self):
        """hwpx 는 흐름 문서라 페이지를 모른다. **0 으로 채우면 1페이지처럼 읽힌다.**"""
        document = parse(_pack(_para("가")))
        record = to_records(chunk_blocks(document.blocks))[0]
        for field in ("i_page", "e_page", "n_page", "chunk_bboxes"):
            self.assertIsNone(record[field], field)

    def test_chunk_index_is_assigned_here(self):
        document = parse(_pack("".join(_para(f"문단 {i} 입니다.") for i in range(10))))
        records = to_records(chunk_blocks(document.blocks, ChunkOptions(max_chars=80)))
        self.assertEqual([r["i_chunk_on_doc"] for r in records], list(range(len(records))))
        self.assertTrue(all(r["n_chunk_of_doc"] == len(records) for r in records))

    def test_extra_fields_are_merged(self):
        document = parse(_pack(_para("가")))
        records = to_records(chunk_blocks(document.blocks), extra={"security_level": "C"})
        self.assertEqual(records[0]["security_level"], "C")


if __name__ == "__main__":
    unittest.main()
