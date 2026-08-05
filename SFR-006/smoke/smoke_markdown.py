"""hwpx → 마크다운 변환 스모크. 합성 픽스처(표 병합 포함) + 실제 템플릿."""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture import HP, bootstrap, pack, para, run, template_bytes  # noqa: E402

TEMPLATE_DIR = bootstrap("tf_markdown_")

from template_fill.hwpx_fields import fill_template, scan_fields  # noqa: E402
from template_fill.hwpx_markdown import render_markdown  # noqa: E402


def tc(text, row, col, col_span=1, row_span=1):
    return (
        f'<hp:tc><hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
        f'<hp:cellSpan colSpan="{col_span}" rowSpan="{row_span}"/>'
        f"<hp:subList>{para(run(text))}</hp:subList></hp:tc>"
    )


# 표: 3열. (0,0) 가로 2칸 병합 / (1,0) 세로 2칸 병합 / 파이프 포함 셀 / 두 문단 셀
TABLE = (
    '<hp:tbl rowCnt="3" colCnt="3">'
    f"<hp:tr>{tc('구분 (병합)', 0, 0, col_span=2)}{tc('비고', 0, 2)}</hp:tr>"
    f"<hp:tr>{tc('세로병합', 1, 0, row_span=2)}{tc('a|b 파이프', 1, 1)}"
    '<hp:tc><hp:cellAddr colAddr="2" rowAddr="1"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
    f"<hp:subList>{para(run('첫 문단'))}{para(run('둘째 문단'))}</hp:subList></hp:tc></hp:tr>"
    f"<hp:tr>{tc('담당자: {고딕, 11pt}', 2, 1)}{tc('', 2, 2)}</hp:tr>"
    "</hp:tbl>"
)

# 좌표 없는 표(합성/구버전) — 순서대로 채워지는지
TABLE_NO_ADDR = (
    "<hp:tbl>"
    "<hp:tr><hp:tc><hp:subList>" + para(run("이름")) + "</hp:subList></hp:tc>"
    "<hp:tc><hp:subList>" + para(run("연락처")) + "</hp:subList></hp:tc></hp:tr>"
    "<hp:tr><hp:tc><hp:subList>" + para(run("왕주영")) + "</hp:subList></hp:tc>"
    "<hp:tc><hp:subList>" + para(run("010-0000-0000")) + "</hp:subList></hp:tc></hp:tr>"
    "</hp:tbl>"
)

SECTION0 = f"""<?xml version="1.0" encoding="UTF-8"?>
<hp:sec xmlns:hp="{HP}">
  {para(run("제 목") + run(" : ") + run("{제목, HY헤드라인M, 16pt}"))}
  {para(run(""))}
  {para(run("본문: {본문, 맑은 고딕, 11pt}"))}
  {para('<hp:run charPrIDRef="0"><hp:ctrl><hp:header><hp:subList>'
        + para(run("머리말은 본문이 아니다"))
        + '</hp:subList></hp:header></hp:ctrl></hp:run>')}
  {para('<hp:run charPrIDRef="0">' + TABLE + '</hp:run>')}
  {para(run("표 아래 문장입니다."))}
  {para('<hp:run charPrIDRef="0">' + TABLE_NO_ADDR + '</hp:run>')}
</hp:sec>
"""

SECTION1 = f"""<?xml version="1.0" encoding="UTF-8"?>
<hp:sec xmlns:hp="{HP}">
  {para(run("두 번째 섹션 문단"))}
</hp:sec>
"""


# 일부러 역순으로 넣는다 — 엔트리 순서가 아니라 섹션 번호로 정렬해야 한다
src = pack(
    {
        "Contents/section1.xml": SECTION1,
        "Contents/section0.xml": SECTION0,
    }
)

print("== 1) 원본 템플릿 마크다운 ==")
result = render_markdown(src)
print(result.markdown)
print(f"\n  paragraphs={result.paragraph_count} tables={result.table_count} truncated={result.truncated}")

md = result.markdown
assert "머리말은 본문이 아니다" not in md, "머리말이 본문에 섞였다"
assert md.index("제 목") < md.index("본문:") < md.index("구분 (병합)") < md.index("표 아래 문장") < md.index("두 번째 섹션 문단"), md
assert "| 구분 (병합) |   | 비고 |" in md, "가로 병합 자리에 빈 칸이 들어가야 한다"
assert "|---|---|---|" in md
assert "a\\|b 파이프" in md, "셀 안 파이프는 이스케이프해야 한다"
assert "첫 문단<br>둘째 문단" in md, "셀 안 여러 문단은 <br> 로"
# 빈 문단·표 소유 문단·머리말은 세지 않는다 → 텍스트 있는 본문 문단 4개
assert result.table_count == 2 and result.paragraph_count == 4, result

lines = [l for l in md.splitlines() if l.startswith("|")]
widths = {l.count("|") for l in lines if "---" not in l}
print("  표 줄 파이프 개수:", widths)

print("\n== 2) 채운 결과 마크다운 (미리보기 경로) ==")
specs = scan_fields(src)
print("  항목:", [(s.name, s.source) for s in specs])
filled = fill_template(
    src,
    {"제 목": "2026년 상반기 실적 보고", "본문": "매출이 전년 대비 12% 증가했다.", "담당자": "왕주영"},
)
print("  written:", filled.written_fields, "missing:", filled.missing_fields)
md2 = render_markdown(filled.hwpx_bytes).markdown
print(md2)
# 라벨 표기는 원문 그대로 유지된다 (`제 목 : ` 의 콜론 앞 공백 보존)
assert "제 목 : 2026년 상반기 실적 보고" in md2, md2
assert "{" not in md2, "서식 명세 표기가 미리보기에 남았다"
assert "담당자: 왕주영" in md2, "표 안 라벨이 채워져야 한다"

print("\n== 3) 상한 초과 ==")
capped = render_markdown(src, max_chars=40)
assert capped.truncated and capped.markdown.endswith("…(이후 생략)"), capped
print("  ", capped.markdown.replace("\n", " ⏎ "))

print("\n== 4) 실제 템플릿 (data/파워.hwpx) ==")
real, _source = template_bytes()
real_md = render_markdown(real)
print(real_md.markdown)
print(f"\n  paragraphs={real_md.paragraph_count} tables={real_md.table_count}")

print("\n== 5) 손상 입력 ==")
from template_fill.hwpx_fields import TemplateError

try:
    render_markdown(b"not a zip")
except TemplateError as exc:
    print("  TemplateError:", exc)
else:
    raise AssertionError("손상 입력에서 TemplateError 가 나야 한다")

shutil.rmtree(TEMPLATE_DIR, ignore_errors=True)
print("\nALL OK")
