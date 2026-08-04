"""hwpx 되쓰기 코어 테스트 — 합성 픽스처만 사용한다 (실제 hwpx 샘플 불필요).

검증 대상은 "문서를 깨지 않는가"다:
- 문단 index 가 문서 순서(표 셀 포함, 중복 없이)와 일치하는가
- 되쓰기 후 대상 밖 ZIP 엔트리가 바이트 동일한가
- 부분 서식 통일·원문 동일·미지 index 를 침묵하지 않고 보고하는가
"""

import io
import unittest
import zipfile

from export.hwpx_rewrite import (
    HwpxExportError,
    extract_paragraphs,
    fingerprint,
    rewrite_paragraphs,
)

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def _para(runs: list, char_pr: str = "0") -> str:
    """문단 하나. runs 의 각 원소가 hp:run/hp:t 하나 (부분 서식 재현용)."""
    inner = "".join(
        f'<hp:run charPrIDRef="{char_pr}"><hp:t>{text}</hp:t></hp:run>' for text in runs
    )
    return f'<hp:p paraPrIDRef="0">{inner}</hp:p>'


def _section(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<hp:sec xmlns:hp="{HP}">{body}</hp:sec>'
    ).encode("utf-8")


def _build_hwpx(sections: dict, extra: dict | None = None) -> bytes:
    """합성 hwpx. mimetype 은 무압축, 그 밖 엔트리는 되쓰기 대상이 아니어야 한다."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", b"application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/manifest.xml", b"<manifest/>")
        # header.xml 은 Contents/ 아래지만 서식 정의라 되쓰기 대상이 아니다
        zf.writestr(
            "Contents/header.xml",
            '<hh:head xmlns:hh="x"><hh:t>건드리면 안 됨</hh:t></hh:head>'.encode("utf-8"),
        )
        for name, data in sections.items():
            zf.writestr(name, data)
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buffer.getvalue()


# 표 셀 안 문단 + 부분 서식 문단 + 빈 문단을 모두 담은 픽스처
_TABLE = (
    '<hp:p paraPrIDRef="0"><hp:run><hp:tbl><hp:tr>'
    f'<hp:tc><hp:subList>{_para(["셀 하나"])}</hp:subList></hp:tc>'
    f'<hp:tc><hp:subList>{_para(["셀 둘"])}</hp:subList></hp:tc>'
    "</hp:tr></hp:tbl></hp:run></hp:p>"
)
_BODY = (
    _para(["보고서 제목"])
    + _para(["안녕하세요 ", "중요한", " 사항입니다"])  # 부분 서식 (run 3개)
    + _para(["   "])  # 빈 문단 — index 를 받지 않아야 한다
    + _TABLE
    + _para(["맺음말"])
)


def _sample() -> bytes:
    return _build_hwpx({"Contents/section0.xml": _section(_BODY)})


class ExtractParagraphsTest(unittest.TestCase):
    def test_문단을_문서_순서로_중복없이_추출한다(self):
        result = extract_paragraphs(_sample())
        texts = [p["text"] for p in result["paragraphs"]]
        # 표 셀 문단이 겉 문단과 중복되지 않고, 빈 문단은 빠진다
        self.assertEqual(
            texts,
            ["보고서 제목", "안녕하세요 중요한 사항입니다", "셀 하나", "셀 둘", "맺음말"],
        )
        self.assertEqual(result["paragraph_count"], 5)
        self.assertEqual([p["index"] for p in result["paragraphs"]], [0, 1, 2, 3, 4])

    def test_섹션은_문자열이_아니라_번호_순서로_읽는다(self):
        # 문자열 정렬이면 section10 이 section2 앞에 와서 index 가 밀린다
        sections = {
            "Contents/section0.xml": _section(_para(["첫째"])),
            "Contents/section2.xml": _section(_para(["둘째"])),
            "Contents/section10.xml": _section(_para(["셋째"])),
        }
        result = extract_paragraphs(_build_hwpx(sections))
        self.assertEqual([p["text"] for p in result["paragraphs"]], ["첫째", "둘째", "셋째"])

    def test_hwpx_가_아니면_안내_예외(self):
        with self.assertRaises(HwpxExportError):
            extract_paragraphs(b"not a zip")

    def test_본문_섹션이_없으면_안내_예외(self):
        with self.assertRaises(HwpxExportError):
            extract_paragraphs(_build_hwpx({}))


class RewriteParagraphsTest(unittest.TestCase):
    def test_지정한_문단만_바뀐다(self):
        sample = _sample()
        result = rewrite_paragraphs(sample, [{"index": 0, "text": "새 제목"}])
        after = extract_paragraphs(result.hwpx_bytes)
        self.assertEqual(after["paragraphs"][0]["text"], "새 제목")
        self.assertEqual(after["paragraphs"][4]["text"], "맺음말")
        self.assertEqual(result.rewritten_indexes, [0])

    def test_표_셀_문단도_되쓴다(self):
        result = rewrite_paragraphs(_sample(), {2: "바뀐 셀"})
        after = extract_paragraphs(result.hwpx_bytes)
        self.assertEqual(after["paragraphs"][2]["text"], "바뀐 셀")
        # 표 구조(행·셀 수)가 유지돼야 한다
        self.assertEqual(after["paragraph_count"], 5)

    def test_부분_서식_통일을_보고한다(self):
        result = rewrite_paragraphs(_sample(), {1: "Hello, this is important."})
        self.assertEqual(result.style_simplified_indexes, [1])
        after = extract_paragraphs(result.hwpx_bytes)
        # 첫 run 에 전체가 들어가고 나머지 run 텍스트는 비워진다
        self.assertEqual(after["paragraphs"][1]["text"], "Hello, this is important.")

    def test_단일_run_문단은_서식_손실이_없다(self):
        result = rewrite_paragraphs(_sample(), {0: "새 제목"})
        self.assertEqual(result.style_simplified_indexes, [])

    def test_원문과_같은_값은_건드리지_않는다(self):
        # 굳이 쓰면 부분 서식만 잃는다 — 글다듬이가 그대로 둔 문단이 여기 해당
        result = rewrite_paragraphs(_sample(), {1: "안녕하세요 중요한 사항입니다"})
        self.assertEqual(result.unchanged_indexes, [1])
        self.assertEqual(result.rewritten_indexes, [])
        self.assertEqual(result.style_simplified_indexes, [])

    def test_원본에_없는_index_는_보고한다(self):
        result = rewrite_paragraphs(_sample(), {99: "어디에도 없음"})
        self.assertEqual(result.unknown_indexes, [99])
        self.assertEqual(result.rewritten_indexes, [])

    def test_되쓰기_대상_밖_엔트리는_바이트_동일하다(self):
        sample = _sample()
        result = rewrite_paragraphs(sample, {0: "새 제목"})
        with zipfile.ZipFile(io.BytesIO(sample)) as before, zipfile.ZipFile(
            io.BytesIO(result.hwpx_bytes)
        ) as after:
            self.assertEqual(before.namelist(), after.namelist())
            for name in before.namelist():
                if name == "Contents/section0.xml":
                    continue
                self.assertEqual(before.read(name), after.read(name), name)

    def test_mimetype_은_무압축으로_남는다(self):
        result = rewrite_paragraphs(_sample(), {0: "새 제목"})
        with zipfile.ZipFile(io.BytesIO(result.hwpx_bytes)) as zf:
            self.assertEqual(zf.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)

    def test_지문이_다르면_쓰지_않고_실패한다(self):
        # 원본이 바뀌면 index 가 밀려 엉뚱한 문단에 값이 들어간다
        other = _build_hwpx({"Contents/section0.xml": _section(_para(["다른 문서"]))})
        with self.assertRaises(HwpxExportError):
            rewrite_paragraphs(_sample(), {0: "새 제목"}, expected_fingerprint=fingerprint(other))

    def test_지문이_같으면_통과한다(self):
        sample = _sample()
        result = rewrite_paragraphs(
            sample, {0: "새 제목"}, expected_fingerprint=fingerprint(sample)
        )
        self.assertEqual(result.rewritten_indexes, [0])

    def test_세그먼트_형식이_틀리면_안내_예외(self):
        with self.assertRaises(HwpxExportError):
            rewrite_paragraphs(_sample(), [{"idx": 0, "text": "잘못된 키"}])
        with self.assertRaises(HwpxExportError):
            rewrite_paragraphs(_sample(), {"영": "정수가 아닌 index"})

    def test_줄바꿈은_공백으로_정규화된다(self):
        # <hp:t> 안의 \n 은 문단 분리가 아니라서 그대로 넣으면 깨져 보인다
        result = rewrite_paragraphs(_sample(), {0: "제목\n둘째 줄"})
        after = extract_paragraphs(result.hwpx_bytes)
        self.assertEqual(after["paragraphs"][0]["text"], "제목 둘째 줄")


if __name__ == "__main__":
    unittest.main()
