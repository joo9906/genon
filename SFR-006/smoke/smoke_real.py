"""실제 현장 템플릿(data/파워.hwpx) 스팟체크 — 서식 명세 오인·줄맞춤 보존 확인."""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture import bootstrap, template_bytes  # noqa: E402

TEMPLATE_DIR = bootstrap("tf_real_")

from template_fill.hwpx_fields import fill_template, scan_fields  # noqa: E402
from template_fill.hwpx_markdown import render_markdown  # noqa: E402
from template_fill.hwpx_style import (  # noqa: E402
    apply_styles,
    collect_style_specs,
    parse_style_spec,
)

src, _source = template_bytes()

print("== 1) 항목 스캔 ==")
specs = scan_fields(src)
for s in specs:
    print(f"  {s.name!r:10} source={s.source} filled={s.filled}")
assert [s.name for s in specs] == ["제 목", "본문", "배포일", "담당자", "주요 내용"], [s.name for s in specs]

print("\n== 2) 서식 명세 (값 안내는 서식이 아니다) ==")
styles = collect_style_specs(src)
for name, spec in styles.items():
    print(f"  {name!r:10} {spec}")
assert styles["제 목"].font == "HY헤드라인M" and styles["제 목"].size_pt == 16, styles["제 목"]
assert styles["본문"].font == "맑은 고딕" and styles["본문"].size_pt == 11, styles["본문"]
assert styles["주요 내용"].font == "휴먼 명조" and styles["주요 내용"].size_pt == 15, styles["주요 내용"]
assert "배포일" not in styles, "날짜 형식 안내를 글꼴로 오인했다"
assert "담당자" not in styles, "값 자리표시어({소속})를 글꼴로 오인했다"

print("\n== 3) 채우기 — 콜론 줄맞춤 보존 ==")
values = {
    "제 목": "2026년 상반기 실적 보고",
    "본문": "상반기 매출은 전년 대비 12% 증가했다.",
    "배포일": "2026. 8. 5. (수)",
    "담당자": "경영지원실 왕주영",
    "주요 내용": "신규 계약 3건 체결, 이탈률 2%p 개선.",
}
result = fill_template(src, values)
print("  written:", result.written_fields)
print("  missing:", result.missing_fields)
filled_md = render_markdown(result.hwpx_bytes).markdown
print(filled_md)
assert "제 목 : 2026년 상반기 실적 보고" in filled_md, "콜론 앞 공백(줄맞춤)이 사라졌다"
assert "본문 : 상반기 매출은" in filled_md, filled_md
assert "주요 내용: 신규 계약" in filled_md, "원래 공백 없던 라벨에 공백이 생겼다"
assert "{" not in filled_md, "서식 명세/자리표시어 표기가 남았다"
assert not result.missing_fields

print("\n== 4) 서식 적용 ==")
styled = apply_styles(result.hwpx_bytes, styles, scope="paragraph")
print("  applied:", styled.applied_fields, "unmatched:", styled.unmatched_specs,
      "new charPr:", styled.added_char_prs, "stripped:", styled.stripped_annotations)
assert sorted(styled.applied_fields) == ["본문", "제 목", "주요 내용"], styled.applied_fields

print("\n== 5) 라운드트립 재스캔 ==")
rescan = scan_fields(styled.hwpx_bytes)
for s in rescan:
    print(f"  {s.name!r:10} filled={s.filled} value={s.current_value!r}")
assert all(s.filled for s in rescan), [s.name for s in rescan if not s.filled]

print("\n== 6) 부분 초안 (일부만 채움) ==")
partial = fill_template(src, {"제 목": "중간 보고"})
partial_md = render_markdown(partial.hwpx_bytes).markdown
print(partial_md)
assert "제 목 : 중간 보고" in partial_md
assert "배포일 :" in partial_md and "{" not in partial_md, "미입력 라벨은 남고 안내 표기는 지워야 한다"
assert sorted(partial.missing_fields) == ["담당자", "배포일", "본문", "주요 내용"], partial.missing_fields

print("\n== 7) 근거 없는 {…} 판정 표 ==")
for text, label in (
    ("{소속} {성명}", "담당자"),
    ("{YYYY.MM.DD. (요일)}", "배포일"),
    ("{제목, HY헤드라인M, 16pt}", "제 목"),
    ("{본문, 맑은 고딕, 11pt}", "본문"),
    ("{함초롬돋움 16pt 굵게}", "제목"),
    ("{볼드체, 고딕, 16pt}", "제목"),
    ("{사내전용서체, 12pt}", "비고"),
    ("{글꼴}", "비고"),
):
    print(f"  {text:26} label={label!r:8} -> {parse_style_spec(text, label=label)}")

shutil.rmtree(TEMPLATE_DIR, ignore_errors=True)
print("\nALL OK")
