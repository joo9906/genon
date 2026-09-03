"""hwpx 자동 번호·글머리표가 왜 안 붙는지 가려낸다. **점검이 아니라 진단 도구다.**

    python onprem/test/diagnose_hwpx_markers.py <문서.hwpx>

`_Markers` 는 값이 없을 때 예외를 던지지 않고 **빈 표시**를 돌려준다 — 그래서 "번호가
안 붙는다" 는 증상 하나에 원인이 여러 갈래이고, 로그에는 어느 쪽도 남지 않는다.
이 스크립트는 그 갈래를 문서에서 직접 읽어 가른다.

**문서 내용을 짧은 발췌로 출력한다.** 폐쇄망 안에서 눈으로 보는 용도이고, 출력을 로그나
저장소에 남기지 않는다(§3.8).
"""

import pathlib
import re
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from preprocessor import final_preprocessor as P  # noqa: E402

EXCERPT = 44


def main(path: str) -> int:
    raw = pathlib.Path(path).read_bytes()

    print("=" * 72)
    print("1) ZIP 항목 — header.xml 이 없으면 표시가 전부 빠진다(로그도 안 남는다)")
    print("=" * 72)
    with zipfile.ZipFile(pathlib.Path(path)) as archive:
        names = archive.namelist()
    header_like = [n for n in names if "header" in n.lower()]
    print(f"  header 계열 항목: {header_like or '**없음**'}")
    print(f"  기대하는 이름   : {P._HEADER_ENTRY}")
    header = P._read_entry(raw, P._HEADER_ENTRY)
    print(f"  읽은 바이트     : {len(header)}")
    if not header:
        print("  >>> 원인 확정: header.xml 을 못 읽었다. 위 '기대하는 이름' 과 실제")
        print("      항목 이름을 대조할 것(대소문자·경로 차이).")
        return 1

    print()
    print("=" * 72)
    print("2) 머리 정의 — 네임스페이스·번호 정의·문단 모양")
    print("=" * 72)
    root = P._parse_xml(header)
    tags = {re.sub(r"\{([^}]*)\}.*", r"\1", e.tag) for e in root.iter() if isinstance(e.tag, str)}
    print(f"  네임스페이스    : {sorted(tags)}")
    print(f"  코드가 찾는 것  : {P.HH_NS}")
    if P.HH_NS not in tags:
        print("  >>> 원인 확정: 머리 네임스페이스가 다르다. HH_NS 를 맞춰야 한다.")
        return 1

    markers = P._Markers(header)
    print(f"  hh:numbering    : {list(markers._numbering) or '**없음**'}")
    for num_id, levels in markers._numbering.items():
        shown = {lvl: (tpl or "**빈 문자열**", fmt) for lvl, (tpl, fmt, _s) in sorted(levels.items())}
        print(f"      id={num_id}: {shown}")
    print(f"  hh:bullet       : {markers._bullets or '**없음**'}")
    headed = {k: v for k, v in markers._para_pr.items() if v[0] != "NONE"}
    print(f"  hh:paraPr 총    : {len(markers._para_pr)}개, 그중 heading != NONE: {len(headed)}개")
    for pr_id, value in sorted(headed.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        num_id, levels = markers._resolve(markers._numbering, value[1], "diagnose")
        how = "id" if value[1] == num_id else ("인덱스" if levels is not None else "**못 찾음**")
        print(f"      paraPrIDRef={pr_id}: type={value[0]} idRef={value[1]} level={value[2]}"
              f"  → 정의 {num_id} ({how})")
    if not headed:
        print("  >>> 이 문서의 문단 모양에는 번호·글머리표 정의가 하나도 없다.")
        print("      = 개요 번호를 쓰지 않는 문서다. 번호가 본문 글자일 가능성이 높다(4 를 볼 것).")

    print()
    print("=" * 72)
    print("3) 본문 문단 — 문단마다 무슨 표시가 계산되는가")
    print("=" * 72)
    # **표·상자 안 문단까지 본다.** 본문 최상위만 훑으면 표 안 목록이 안 보이는데,
    # 목록은 표 안에 있는 일이 흔하다. 번호는 누적 상태라 여기 표시 값은 참고용이다 —
    # 이 절이 답하는 것은 "이 문단 모양이 번호를 받는가" 다.
    fresh = P._Markers(header)
    seen: dict = {}
    rows = []
    for _name, xml_bytes in P._iter_section_xml(raw):
        section = P._parse_xml(xml_bytes)
        for para in list(section.iter(P._PARA)):
            nested = P._nearest_para(para) is not None
            marker = fresh.advance(para)
            text = P._own_text(para)
            ref = para.get("paraPrIDRef")
            kind = fresh._para_pr.get(ref, ("NONE", "", 0))[0]
            key = (ref, para.get("styleIDRef"), kind, bool(marker))
            seen[key] = seen.get(key, 0) + 1
            if text:
                rows.append((ref, para.get("styleIDRef"), kind, marker, nested, text[:EXCERPT]))

    print(f"  {'paraPrIDRef':>12} {'styleIDRef':>10} {'heading':>8} {'표시':>6}  건수")
    for (ref, style, kind, has), count in sorted(seen.items(), key=lambda kv: -kv[1]):
        print(f"  {str(ref):>12} {str(style):>10} {kind:>8} {'있음' if has else '없음':>6}  {count}")

    print()
    print("  글자가 있는 문단 앞 40개 (안=표·상자 안 문단):")
    for ref, style, kind, marker, nested, text in rows[:40]:
        where = "안" if nested else "  "
        print(f"    {where} paraPr={str(ref):>4} style={str(style):>4} {kind:>7}"
              f" 표시={marker!r:>8} | {text}")

    print()
    print("  문단 모양별로 **표시가 나오는지만** 따로 확인한다(누적 상태 영향 제거):")
    for ref in sorted({r for r, *_rest in rows}, key=lambda v: int(v) if str(v).isdigit() else -1):
        probe = P._Markers(header)
        holder = P._parse_xml(
            f'<hp:p xmlns:hp="{P.HP_NS}" paraPrIDRef="{ref}"/>'.encode()
        )
        print(f"      paraPrIDRef={str(ref):>4} → {probe.advance(holder)!r}")

    print()
    print("=" * 72)
    print("4) 번호가 **본문 글자**인가 — 그렇다면 `_Markers` 는 애초에 관계가 없다")
    print("=" * 72)
    literal = [
        (r, t) for r, _s, _k, _m, _n, t in rows
        if re.match(r"^\s*(\d{1,2}[.)]|[가-하][.)])\s", t)
    ]
    print(f"  본문 글자가 이미 번호로 시작하는 문단: {len(literal)}건")
    for ref, text in literal[:10]:
        print(f"      paraPr={str(ref):>4} | {text}")

    raw_numbers = 0
    for _name, xml_bytes in P._iter_section_xml(raw):
        raw_numbers += len(re.findall(rb">\s*\d{1,2}\.\s", xml_bytes))
    print(f"  XML 안에서 `>N. ` 모양이 보이는 횟수: {raw_numbers}")
    if raw_numbers and not literal:
        print("  >>> 번호가 XML 에는 있는데 파싱 결과에는 없다 — `_Markers` 가 아니라")
        print("      텍스트 추출(`_own_text`)이나 문단 선택 쪽 문제다.")

    print()
    print("=" * 72)
    print("5) 복원한 표시가 **최종 적재 레코드까지** 살아 오는가")
    print("=" * 72)
    document = P.parse(raw)
    blocks = P.annotate_outline(document.blocks)
    chunks = P.chunk_blocks(blocks)
    records = P.to_records(chunks)
    expect = [m for _r, _s, _k, m, _n, _t in rows if m]
    print(f"  블록 {len(document.blocks)} → 청크 {len(chunks)} → 레코드 {len(records)}")
    print(f"  파싱 단계에서 표시가 붙은 문단: {len(expect)}건")
    if expect:
        body = chr(10).join(str(r.get("text", "")) for r in records)
        missing = [m for m in dict.fromkeys(expect) if m.strip() not in body]
        print(f"  그중 최종 레코드 본문에서 **사라진** 표시: {missing or '없음'}")
        if missing:
            print("  >>> `_Markers` 는 돌았고 그 뒤(청킹·머리말·조문 위계)에서 빠졌다.")
    else:
        print("  >>> 파싱 단계에서 이미 표시가 하나도 안 붙었다. 위 2·3 을 볼 것 —")
        print("      청킹 쪽은 볼 필요가 없다.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
