"""반복 블록 테스트 — 합성 픽스처만 사용한다.

이식 과정에서 고친 원본 CLI(`hwpx.py`) 결함에 대한 회귀 테스트를 포함한다:
간격 문단 오검출로 실제 내용이 삭제되던 것, run 이 쪼개진 토큰이 안 채워지던 것,
한글 토큰이 안 채워지던 것.
"""

import io
import unittest
import zipfile

from lxml import etree

from template_fill.hwpx_fields import HP_NS, TemplateError
from template_fill.hwpx_repeat import fill_with_repeat

_PARA = f"{{{HP_NS}}}p"
_TEXT = f"{{{HP_NS}}}t"


def _para(runs: list, para_pr: str = "0") -> str:
    inner = "".join(f"<hp:run><hp:t>{text}</hp:t></hp:run>" for text in runs)
    return f'<hp:p paraPrIDRef="{para_pr}">{inner}</hp:p>'


def _template(body: str) -> bytes:
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<hp:sec xmlns:hp="{HP_NS}">{body}</hp:sec>'
    ).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", b"application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/manifest.xml", b"<manifest/>")
        zf.writestr("Contents/section0.xml", section)
    return buffer.getvalue()


def _texts(hwpx_bytes: bytes) -> list:
    """결과 문단 텍스트 목록 (빈 문단 제외).

    문단 하나당 텍스트 하나로 모으되, 표 셀처럼 문단이 겹치는 픽스처는 쓰지 않으므로
    `hp:p` 순회로 충분하다.
    """
    with zipfile.ZipFile(io.BytesIO(hwpx_bytes)) as zf:
        root = etree.fromstring(zf.read("Contents/section0.xml"))
    collected = []
    for para in root.iter(_PARA):
        text = "".join((node.text or "") for node in para.iter(_TEXT))
        if text.strip():
            collected.append(text)
    return collected


class FillWithRepeatTest(unittest.TestCase):
    def test_문단을_블록_수만큼_복제한다(self):
        template = _template(_para(["{{제목}}"]) + _para(["{{main}}"]))
        result = fill_with_repeat(template, ["첫째", "둘째", "셋째"], {"제목": "보고서"})
        self.assertEqual(result.block_count, 3)
        self.assertEqual(_texts(result.hwpx_bytes), ["보고서", "첫째", "둘째", "셋째"])

    def test_템플릿_문단은_결과에_남지_않는다(self):
        result = fill_with_repeat(_template(_para(["{{main}}"])), ["본문"])
        self.assertEqual(_texts(result.hwpx_bytes), ["본문"])
        self.assertEqual(result.leftover_tokens, [])

    def test_항목_설명_2단_구조(self):
        template = _template(_para(["□ {{main}}"]) + _para(["◦ {{detail}}"]))
        result = fill_with_repeat(
            template,
            [
                {"main": "추진 배경", "detail": "관련 법령이 개정되었다."},
                {"main": "기대 효과", "detail": "처리 기간이 단축된다."},
            ],
        )
        self.assertEqual(result.block_count, 2)
        self.assertEqual(
            _texts(result.hwpx_bytes),
            ["□ 추진 배경", "◦ 관련 법령이 개정되었다.", "□ 기대 효과", "◦ 처리 기간이 단축된다."],
        )

    def test_detail_이_없는_블록은_설명_문단을_만들지_않는다(self):
        template = _template(_para(["□ {{main}}"]) + _para(["◦ {{detail}}"]))
        result = fill_with_repeat(template, [{"main": "제목만 있음"}])
        self.assertEqual(_texts(result.hwpx_bytes), ["□ 제목만 있음"])

    def test_빈_문단만_간격용으로_인정한다(self):
        # 원본 CLI 회귀: getnext() 를 무조건 간격용으로 보고 삭제해 실제 내용을 잃었다
        template = _template(_para(["{{main}}"]) + _para(["맺음말은 지워지면 안 된다"]))
        result = fill_with_repeat(template, ["본문 하나", "본문 둘"])
        self.assertEqual(
            _texts(result.hwpx_bytes), ["본문 하나", "본문 둘", "맺음말은 지워지면 안 된다"]
        )

    def test_간격용_빈_문단은_블록마다_복제된다(self):
        template = _template(_para(["{{main}}"]) + _para([" "]))
        result = fill_with_repeat(template, ["가", "나"])
        self.assertEqual(_texts(result.hwpx_bytes), ["가", "나"])
        with zipfile.ZipFile(io.BytesIO(result.hwpx_bytes)) as zf:
            root = etree.fromstring(zf.read("Contents/section0.xml"))
        # 본문 2개 + 간격 2개
        self.assertEqual(len(list(root.iter(_PARA))), 4)

    def test_run_이_쪼개진_토큰도_치환한다(self):
        # 원본 CLI 회귀: hp:t 하나에 토큰이 온전해야만 치환됐다
        result = fill_with_repeat(_template(_para(["{{ma", "in}}"])), ["쪼개진 토큰도 채운다"])
        self.assertEqual(_texts(result.hwpx_bytes), ["쪼개진 토큰도 채운다"])

    def test_한글_토큰을_채운다(self):
        # 원본 CLI 회귀: ASCII 전용 TOKEN_RE 가 {{부서}} 를 못 잡았다
        template = _template(_para(["{{부서}} 귀중"]) + _para(["{{main}}"]))
        result = fill_with_repeat(template, ["본문"], {"부서": "경영지원실"})
        self.assertEqual(_texts(result.hwpx_bytes), ["경영지원실 귀중", "본문"])

    def test_값이_없어_남은_토큰을_보고한다(self):
        template = _template(_para(["{{제목}}"]) + _para(["{{main}}"]))
        result = fill_with_repeat(template, ["본문"])  # 제목 값을 주지 않았다
        self.assertEqual(result.leftover_tokens, ["제목"])

    def test_본문이_빈_블록은_건너뛰고_보고한다(self):
        result = fill_with_repeat(_template(_para(["{{main}}"])), ["있음", "   ", ""])
        self.assertEqual(result.block_count, 1)
        self.assertEqual(result.skipped_blocks, 2)

    def test_본문_문단_표시가_없으면_안내_예외(self):
        with self.assertRaises(TemplateError):
            fill_with_repeat(_template(_para(["표시가 없는 템플릿"])), ["본문"])

    def test_블록이_없으면_표시가_없어도_통과한다(self):
        result = fill_with_repeat(_template(_para(["표시가 없는 템플릿"])), [])
        self.assertEqual(result.block_count, 0)
        self.assertEqual(_texts(result.hwpx_bytes), ["표시가 없는 템플릿"])

    def test_블록_형식이_틀리면_안내_예외(self):
        with self.assertRaises(TemplateError):
            fill_with_repeat(_template(_para(["{{main}}"])), [123])

    def test_템플릿이_hwpx_가_아니면_안내_예외(self):
        with self.assertRaises(TemplateError):
            fill_with_repeat(b"not a zip", ["본문"])

    def test_mimetype_은_무압축으로_남는다(self):
        result = fill_with_repeat(_template(_para(["{{main}}"])), ["본문"])
        with zipfile.ZipFile(io.BytesIO(result.hwpx_bytes)) as zf:
            self.assertEqual(zf.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)

    def test_문단_서식이_보존된다(self):
        # deepcopy 이므로 paraPrIDRef 가 복제 문단마다 유지돼야 한다
        result = fill_with_repeat(_template(_para(["{{main}}"], para_pr="7")), ["가", "나"])
        with zipfile.ZipFile(io.BytesIO(result.hwpx_bytes)) as zf:
            xml = zf.read("Contents/section0.xml").decode("utf-8")
        self.assertEqual(xml.count('paraPrIDRef="7"'), 2)

    def test_줄바꿈은_공백으로_정규화된다(self):
        result = fill_with_repeat(_template(_para(["{{main}}"])), ["첫 줄\n둘째 줄"])
        self.assertEqual(_texts(result.hwpx_bytes), ["첫 줄 둘째 줄"])


if __name__ == "__main__":
    unittest.main()
