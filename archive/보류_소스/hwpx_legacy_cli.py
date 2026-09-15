"""hwpx 템플릿 조작 검증 도구 (로컬 단독 실행, GenOS 연동 없음).

lxml 로 hwpx(ZIP+XML) 템플릿을 실제로 조작할 수 있는지 확인하는 용도.
프로토타입 스크립트와 같은 두 가지 조작을 수행한다.

  ① 고정 토큰 치환 : 모든 <hp:t> 텍스트의 {{token}} 을 값으로 치환
  ② 반복 블록 복제 : {{main}} 문단(□) / {{detail}} 문단(◦) / 그 뒤 spacer
                     문단을 contents 배열 개수만큼 deepcopy 삽입 후 원본 제거

사용법
  python hwpx_template_tool.py inspect  template.hwpx
      → 문단 구조 덤프 (paraPrIDRef, 텍스트, 토큰 위치) — 템플릿 파악용

  python hwpx_template_tool.py scan     template.hwpx
      → 템플릿에 존재하는 {{token}} 목록 출력

  python hwpx_template_tool.py fill     template.hwpx values.json -o out.hwpx
      → 값을 채운 hwpx 생성 + 잔존 토큰 검사

values.json 예시
  {
    "title": "생성형 AI 구축 사업 추진",
    "department1_name": "지원부서",
    "manager1": "김XX 부장(02-750-1092)",
    "number": "1",
    "distribution_date": "2026.05.15.(금)",
    "contents": [
      {"main": "사업 개요", "detail": "생성형 AI 플랫폼 구축"},
      {"main": "추진 일정", "detail": "2026년 하반기 착수"},
      {"main": "기대 효과"}
    ]
  }

프로토타입 대비 수정 사항
  - `if element.getparent():` → `is not None` (lxml 은 자식 없는 element 를
    False 로 평가하므로 truthiness 비교는 오동작)
  - □/◦ 기호 텍스트 매칭 → {{main}}/{{detail}} 토큰 포함 여부로 문단 탐색
    (기호가 바뀌어도 동작, xpath [0] IndexError 방지)
  - XML 선언 유지, mimetype 무압축(STORED) 규약 유지
  - 값 치환은 t.text 대입 → lxml 이 escape 자동 처리 (<, &, > 안전)
"""

import argparse
import io
import json
import re
import sys
import zipfile
from copy import deepcopy

from lxml import etree

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
NS = {"hp": HP_NS}
TOKEN_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
MAIN_TOKEN = "{{main}}"
DETAIL_TOKEN = "{{detail}}"
NEWLINE_REPLACEMENT = " "  # <hp:t> 안의 \n 은 문단이 되지 않으므로 치환


# ─────────────────────────────────────────────────────────────────────────────
# 조작 엔진
# ─────────────────────────────────────────────────────────────────────────────
def normalize(value) -> str:
    text = str(value if value is not None else "")
    return text.replace("\r\n", "\n").replace("\n", NEWLINE_REPLACEMENT)


def fill_scalar_tokens(root, values: dict) -> None:
    """모든 hp:t 텍스트에서 {{token}} 치환. 값이 없는 토큰은 건드리지 않는다."""
    for t in root.iter(f"{{{HP_NS}}}t"):
        if not t.text or "{{" not in t.text:
            continue
        new_text = t.text
        for name in set(TOKEN_RE.findall(new_text)):
            val = values.get(name)
            if val is None or isinstance(val, (list, dict)):
                continue
            new_text = new_text.replace("{{" + name + "}}", normalize(val))
        t.text = new_text  # lxml 이 escape 자동 처리


def expand_repeat_block(root, contents: list) -> None:
    """{{main}}/{{detail}}/spacer 문단을 contents 개수만큼 복제 삽입."""
    mains = root.xpath(
        f'.//hp:p[hp:run/hp:t[contains(text(), "{MAIN_TOKEN}")]]', namespaces=NS
    )
    if not mains:
        if contents:
            raise SystemExit(
                "오류: contents 가 주어졌지만 템플릿에 {{main}} 문단이 없습니다."
            )
        return
    square_tpl = mains[0]

    circles = root.xpath(
        f'.//hp:p[hp:run/hp:t[contains(text(), "{DETAIL_TOKEN}")]]', namespaces=NS
    )
    circle_tpl = circles[0] if circles else None
    spacer_tpl = circle_tpl.getnext() if circle_tpl is not None \
        else square_tpl.getnext()

    parent = square_tpl.getparent()
    idx = parent.index(square_tpl)


    for item in contents:
        if not isinstance(item, dict) or not str(item.get("main", "")).strip():
            continue

        square_p = deepcopy(square_tpl)
        for t in square_p.iter(f"{{{HP_NS}}}t"):
            if t.text and MAIN_TOKEN in t.text:
                t.text = t.text.replace(MAIN_TOKEN, normalize(item["main"]))
        parent.insert(idx, square_p)
        idx += 1

        detail = str(item.get("detail", "")).strip()
        if detail and circle_tpl is not None:
            circle_p = deepcopy(circle_tpl)
            for t in circle_p.iter(f"{{{HP_NS}}}t"):
                if t.text and DETAIL_TOKEN in t.text:
                    t.text = t.text.replace(DETAIL_TOKEN, normalize(detail))
            parent.insert(idx, circle_p)
            idx += 1

        if spacer_tpl is not None:
            parent.insert(idx, deepcopy(spacer_tpl))
            idx += 1

    # 템플릿 문단 제거 — lxml truthiness 함정 회피: 반드시 `is not None`
    for tpl in (square_tpl, circle_tpl, spacer_tpl):
        if tpl is not None and tpl.getparent() is not None:
            tpl.getparent().remove(tpl)


def transform_xml(xml_bytes: bytes, values: dict, contents: list) -> bytes:
    root = etree.fromstring(xml_bytes)
    if MAIN_TOKEN.encode() in xml_bytes:
        expand_repeat_block(root, contents)
    fill_scalar_tokens(root, values)
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)


def generate(template_path: str, values: dict) -> bytes:
    """hwpx(ZIP) 안의 Contents/*.xml 을 변환해 새 hwpx 바이트를 만든다."""
    contents = values.get("contents")
    contents = contents if isinstance(contents, list) else []
    scalars = {k: v for k, v in values.items() if not isinstance(v, (list, dict))}

    buf = io.BytesIO()
    with zipfile.ZipFile(template_path, "r") as src, \
            zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename.startswith("Contents/") and item.filename.endswith(".xml"):
                data = transform_xml(data, scalars, contents)
            compress = zipfile.ZIP_STORED if item.filename == "mimetype" \
                else zipfile.ZIP_DEFLATED  # mimetype 무압축 규약
            dst.writestr(item.filename, data, compress_type=compress)
    return buf.getvalue()


def scan_tokens(source) -> set:
    """hwpx(경로 또는 bytes)에서 {{token}} 집합을 스캔."""
    src = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    tokens = set()
    with zipfile.ZipFile(src, "r") as zf:
        for name in zf.namelist():
            if name.startswith("Contents/") and name.endswith(".xml"):
                tokens.update(TOKEN_RE.findall(
                    zf.read(name).decode("utf-8", errors="replace")))
    return tokens


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def cmd_inspect(args):
    """섹션별 문단 구조 덤프 — 템플릿에서 어떤 문단이 어떤 스타일인지 파악."""
    with zipfile.ZipFile(args.template) as zf:
        for name in sorted(zf.namelist()):
            if not (name.startswith("Contents/section") and name.endswith(".xml")):
                continue
            print(f"\n===== {name} =====")
            root = etree.fromstring(zf.read(name))
            for i, p in enumerate(root.iter(f"{{{HP_NS}}}p")):
                texts = [t.text or "" for t in p.iter(f"{{{HP_NS}}}t")]
                joined = "".join(texts).strip()
                mark = ""
                if MAIN_TOKEN in joined:
                    mark = "  ← 반복 블록 main"
                elif DETAIL_TOKEN in joined:
                    mark = "  ← 반복 블록 detail"
                elif not joined:
                    mark = "  (빈 문단 — spacer 후보)"
                print(f"[{i:3d}] paraPr={p.get('paraPrIDRef', '-'):>3} "
                      f"| {joined[:60]!r}{mark}")


def cmd_scan(args):
    tokens = scan_tokens(args.template)
    if not tokens:
        sys.exit("{{token}} 을 찾지 못했습니다. 한글에서 토큰을 한 번에 "
                 "타이핑했는지(서식으로 run 이 쪼개지지 않았는지) 확인하세요.")
    repeat = tokens & {"main", "detail"}
    print(f"발견 토큰 {len(tokens)}개: {sorted(tokens)}")
    if repeat:
        print(f"반복 블록 토큰: {sorted(repeat)} → values.json 의 contents 배열로 채움")


def cmd_fill(args):
    with open(args.values, encoding="utf-8") as f:
        values = json.load(f)

    out_bytes = generate(args.template, values)
    out_path = args.output or "filled_output.hwpx"
    with open(out_path, "wb") as f:
        f.write(out_bytes)
    print(f"생성 완료: {out_path}")

    remain = scan_tokens(out_bytes)
    if remain:
        print(f"⚠ 치환되지 않은 토큰 잔존: {sorted(remain)}")
        print("  → values.json 키 누락이거나, 한글 편집기가 토큰을 여러 run 으로 "
              "쪼갠 경우입니다 (inspect 로 해당 문단을 확인하세요).")
    else:
        print("모든 토큰 치환 완료. 한글 뷰어로 열어 서식/반복 문단을 확인하세요.")


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, extra in (
        ("inspect", cmd_inspect, False),
        ("scan", cmd_scan, False),
        ("fill", cmd_fill, True),
    ):
        s = sub.add_parser(name)
        s.add_argument("template")
        if extra:
            s.add_argument("values")
            s.add_argument("-o", "--output")
        s.set_defaults(fn=fn)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
