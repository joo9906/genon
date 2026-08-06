"""`Structure` 도구 — 마크다운/HTML 지문 대조와 hwpx XML 무결성.

담당 지표 (README):
- 018 글다듬이: `markdown_guard` 지문 대조 통과율
- 018 번역: 재조립 실패·세그먼트 수 불일치 fallback 발생률
- 006 채움·판정 정확성: 라운드트립(채움 → 재스캔 판정 일치), 미입력 필드 안내문 유지
- 006 문서 무결성: 필드 값 제외 영역의 텍스트 동일성, 개체(표·이미지) 수 일치

hwpx 지문은 이 패키지가 직접 lxml 로 계산한다. 운영 코드(`template_fill`)를
import 하지 않는 이유: onprem 배포 단위는 서로 import 하지 않는다는 규칙이 있고,
평가기가 피평가 코드의 파서를 공유하면 파서 버그를 함께 놓치기 때문이다.
"""

import re
import zipfile
from collections import Counter
from pathlib import Path

from lxml import etree

from .error_codes import (
    ERR_EMPTY_ITEMS,
    ERR_FILE_NOT_FOUND,
    ERR_HWPX_INVALID,
    fail,
)
from .logging_utils import log_info, log_warning
from .normalize import normalize, split_sentences

# ── 마크다운/HTML 지문 (전처리기 산출물 두 유형 모두) ────────────
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_HEADING_RE = re.compile(r"^(#{1,6})\s")
_TABLE_SEP_RE = re.compile(r"^\s*\|?(\s*:?-+:?\s*\|)+\s*:?-*:?\s*\|?\s*$")
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")
_HTML_TABLE_REGION_RE = re.compile(r"<table\b.*?</table\s*>", re.IGNORECASE | re.DOTALL)
_HTML_TR_RE = re.compile(r"<tr\b", re.IGNORECASE)
_HTML_CELL_RE = re.compile(r"<t[dh]\b", re.IGNORECASE)

# ── hwpx (OWPML) ─────────────────────────────────────────────
HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_FIELD_BEGIN = f"{{{HP_NS}}}fieldBegin"
_FIELD_END = f"{{{HP_NS}}}fieldEnd"
_TEXT = f"{{{HP_NS}}}t"
_PARA = f"{{{HP_NS}}}p"
_STRING_PARAM = f"{{{HP_NS}}}stringParam"
_SECTION_RE = re.compile(r"^Contents/section\d+\.xml$", re.IGNORECASE)
# ── 슬롯 (`{'제목', 16pt, 고딕, 볼드}`) — 006 템플릿의 채울 자리 ──
# 운영 코드와 같은 규칙을 이 패키지가 따로 구현한다 (파서 공유 금지 — 모듈 docstring).
# 따옴표 안 첫 인자가 항목명이고, **중괄호 밖 텍스트가 문서 골격**이다.
SLOT_FIELD_TYPE = "SLOT"
_QUOTES = "'‘’\"“”"
_SLOT_RE = re.compile(
    r"\{\s*(?P<open>['‘\"“])(?P<name>[^" + _QUOTES + r"{}]*)(?P<close>['’\"”])"
    r"(?P<rest>[^{}]*)\}"
)
_QUOTE_PAIRS = {"'": "'’", "‘": "'’", '"': '"”', "“": '"”'}
_TOKEN_RE = re.compile(r"\{\{\s*([^{}\r\n]+?)\s*\}\}")
# 개수 일치를 특히 눈에 띄게 보고할 개체 태그 (표·이미지·수식 등)
OBJECT_TAGS = ("tbl", "pic", "container", "equation", "ole", "line", "rect", "chart")
# 글자를 담는 요소 — 슬롯에 서식을 걸면 개수가 정당하게 달라진다 (hwpx_integrity 참고).
_TEXT_CARRIER_TAGS = ("run", "t", "linesegarray", "lineseg")


def fingerprint(text: str) -> dict:
    """구조 지문 — 표 행별 열 수, 구분 행 수, 제목 레벨 순서, 코드펜스 수, HTML 표."""
    html_tables = [
        [len(_HTML_TR_RE.findall(region)), len(_HTML_CELL_RE.findall(region))]
        for region in _HTML_TABLE_REGION_RE.findall(text or "")
    ]
    body = _HTML_TABLE_REGION_RE.sub("", text or "")

    headings, table_rows = [], []
    separator_rows = fences = 0
    in_code = False
    for line in body.splitlines():
        if _FENCE_RE.match(line):
            fences += 1
            in_code = not in_code
            continue
        if in_code:
            continue
        heading = _HEADING_RE.match(line.strip())
        if heading:
            headings.append(len(heading.group(1)))
            continue
        if line.lstrip().startswith("|"):
            if _TABLE_SEP_RE.match(line):
                separator_rows += 1
            else:
                table_rows.append(len(_UNESCAPED_PIPE_RE.findall(line)) - 1)
    return {
        "headings": headings,
        "table_rows": table_rows,
        "separator_rows": separator_rows,
        "fences": fences,
        "html_tables": html_tables,
    }


def fingerprint_diff(original: str, result: str) -> dict:
    """지문을 비교해 훼손 항목을 낸다. 운영 코드 markdown_guard 와 같은 판정 기준."""
    before, after = fingerprint(original), fingerprint(result)
    issues = []
    if before["table_rows"] != after["table_rows"] or before["separator_rows"] != after["separator_rows"]:
        issues.append("markdown_table")
    if before["html_tables"] != after["html_tables"]:
        issues.append("html_table")
    if before["headings"] != after["headings"]:
        issues.append("heading")
    if before["fences"] != after["fences"]:
        issues.append("code_fence")
    return {"passed": not issues, "issues": issues, "before": before, "after": after}


def structure_pass_rate(pairs: list) -> dict:
    """(원문, 결과) 쌍 묶음의 지문 대조 통과율 + 훼손 유형별 건수."""
    if not pairs:
        fail(ERR_EMPTY_ITEMS, event="polish_pairs_empty")

    issue_counts: Counter = Counter()
    failures = []
    for index, pair in enumerate(pairs):
        diff = fingerprint_diff(str(pair.get("original", "")), str(pair.get("result", "")))
        if not diff["passed"]:
            issue_counts.update(diff["issues"])
            failures.append({"index": index, "id": pair.get("id"), "issues": diff["issues"]})

    total = len(pairs)
    return {
        "items": total,
        "passed": total - len(failures),
        "pass_rate": round((total - len(failures)) / total, 4),
        "issue_counts": dict(issue_counts),
        "failures": failures,
    }


def translation_fallback_rate(records: list) -> dict:
    """번역 실행 기록에서 fallback(원문 유지) 발생률과 세그먼트 수 불일치율.

    번역은 스켈레톤 분리·재조립으로 구조를 코드가 보장하므로, 남는 위험은
    "재조립 실패 → 원문 폴백"뿐이다. 그래서 이 지표가 0 에 수렴해야 한다.

    records: [{"id":..., "segments_in": n, "segments_out": m, "fallback": bool}]
    """
    if not records:
        fail(ERR_EMPTY_ITEMS, event="translation_records_empty")

    fallbacks, mismatches = [], []
    for index, record in enumerate(records):
        ident = record.get("id", index)
        if record.get("fallback"):
            fallbacks.append(ident)
        sin, sout = record.get("segments_in"), record.get("segments_out")
        if sin is not None and sout is not None and int(sin) != int(sout):
            mismatches.append({"id": ident, "segments_in": int(sin), "segments_out": int(sout)})

    total = len(records)
    return {
        "items": total,
        "fallback_count": len(fallbacks),
        "fallback_rate": round(len(fallbacks) / total, 4),
        "segment_mismatch_count": len(mismatches),
        "segment_mismatch_rate": round(len(mismatches) / total, 4),
        "fallback_ids": fallbacks,
        "segment_mismatches": mismatches,
        "target": "두 비율 모두 0 이어야 한다",
    }


# ─────────────────────────────────────────────────────────────
# hwpx 스캔 — 006 지표의 공통 입력
# ─────────────────────────────────────────────────────────────
def _read_sections(path: str) -> dict:
    file_path = Path(path)
    if not file_path.is_file():
        fail(ERR_FILE_NOT_FOUND, event="hwpx_file_not_found")
    try:
        with zipfile.ZipFile(file_path) as archive:
            names = archive.namelist()
            sections = {
                name: archive.read(name) for name in sorted(names) if _SECTION_RE.match(name)
            }
    except (zipfile.BadZipFile, OSError) as exc:
        fail(ERR_HWPX_INVALID, event="hwpx_parse_failed", from_exc=exc)
    if not sections:
        fail(ERR_HWPX_INVALID, event="hwpx_parse_failed")
    return {"sections": sections, "entries": sorted(names)}


def _guide_text(begin_elem) -> str:
    for param in begin_elem.iter(_STRING_PARAM):
        return (param.text or "").strip()
    return ""


def _nearest_para(node):
    """이 텍스트 노드를 직접 담고 있는 문단 (표 셀 안의 하위 문단까지 구분)."""
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _PARA:
            return parent
        parent = parent.getparent()
    return None


def _split_slots(text: str) -> tuple:
    """문단 텍스트 → (골격 조각, 항목명). 슬롯이 없으면 ([원문], []).

    `제 목 : {'제 목', 16pt}` → (["제 목 : ", ""], ["제 목"]).
    조각은 **중괄호 밖 텍스트 그대로**이고 항목보다 정확히 하나 많다. 조각을 이어 붙인
    것이 문서 골격이고, 조각 사이가 값이 들어갈 자리다.

    레거시 `{{token}}` 자리는 슬롯으로 보지 않는다 (같은 길이 공백으로 가려 offset 유지).
    """
    masked = _TOKEN_RE.sub(lambda m: " " * len(m.group(0)), text) if "{{" in text else text
    parts, names = [], []
    cursor = 0
    for match in _SLOT_RE.finditer(masked):
        if match.group("close") not in _QUOTE_PAIRS[match.group("open")]:
            continue
        name = match.group("name").strip()
        if not name:
            continue
        parts.append(text[cursor:match.start()])
        names.append(name)
        cursor = match.end()
    parts.append(text[cursor:])
    return parts, names


def _extract_values(parts: list, filled_text: str):
    """골격 조각으로 채워진 문단에서 값을 되짚는다. 골격이 어긋나면 None.

    골격을 그대로 박아 넣은 정규식으로 값 자리만 최소 일치시킨다 — 값에 어떤 글자가
    들어오든(공백·콜론 포함) 골격이 유지되기만 하면 값을 정확히 떼어낸다.

    라벨 방식일 때는 `제목: 값` 을 콜론으로 되짚었고, 그래서 문장에 콜론이 있으면
    항목으로 오인했다. 지금은 골격 자체를 대조하므로 그 추측이 필요 없다.

    `None` 은 "채운 문서가 템플릿 골격을 벗어났다"는 뜻이다 — 무결성 지표가 그것을
    텍스트 불일치로 보고한다 (조용히 넘기지 않는다).
    """
    pattern = "(.*?)".join(re.escape(part) for part in parts)
    match = re.fullmatch(pattern, filled_text, re.DOTALL)
    return list(match.groups()) if match else None


def _group_by_paragraph(chunks: list) -> list:
    """[(문단, 조각)] → [(문단, 문단 텍스트)] — 등장 순서를 유지한다."""
    grouped: list = []
    for para, chunk in chunks:
        if grouped and grouped[-1][0] is para:
            grouped[-1][1].append(chunk)
        else:
            grouped.append((para, [chunk]))
    return [(para, "".join(parts)) for para, parts in grouped]


def scan_hwpx(path: str) -> dict:
    """hwpx 를 스캔해 필드 목록 · 필드 외 텍스트 · 태그 수를 낸다.

    두 방식을 함께 본다 (운영 코드와 같은 계약):
    - 누름틀: fieldBegin/fieldEnd 짝을 문서 순서 스택으로 맞춘다 (문단/필드 id 는
      전부 중복돼 신뢰할 수 없다 — 규칙 문서 §3.2).
    - 슬롯: 본문에 텍스트로 적힌 `{'제목', 16pt}`. 중괄호 밖은 문서 골격, 안은 값 자리다.

    **슬롯 값은 이 함수가 낼 수 없다.** 채운 문서에는 `{…}` 가 남지 않으므로, 한 파일만
    보고는 어디까지가 골격이고 어디부터가 값인지 알 수 없다. 전/후 문단을 맞춰 값을
    되짚는 일은 `_align` 이 한다 — 그래서 `paragraphs` 를 함께 낸다.
    """
    loaded = _read_sections(path)
    fields, outside_text, paragraphs = [], [], []
    tag_counts: Counter = Counter()

    for section_name, xml_bytes in loaded["sections"].items():
        try:
            root = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError as exc:
            fail(ERR_HWPX_INVALID, event="hwpx_parse_failed", from_exc=exc)

        stack = []
        # 문단 단위로 라벨 항목을 판정해야 하므로 필드 밖 텍스트를 문단과 함께 모은다.
        # (lxml 프록시는 참조를 놓으면 회수되고 id 가 재사용되므로 요소를 직접 들고 있는다)
        outside_chunks: list = []
        field_paras: list = []
        for elem in root.iter():
            tag = etree.QName(elem).localname if isinstance(elem.tag, str) else None
            if tag:
                tag_counts[tag] += 1

            if elem.tag == _FIELD_BEGIN:
                field_paras.append(_nearest_para(elem))
                stack.append(
                    {
                        "name": (elem.get("name") or "").strip(),
                        "guide": _guide_text(elem),
                        "field_type": (elem.get("type") or "").strip(),
                        "section": section_name,
                        "text": "",
                    }
                )
            elif elem.tag == _FIELD_END:
                if stack:
                    fields.append(stack.pop())
            elif elem.tag == _TEXT:
                chunk = elem.text or ""
                if stack:
                    for open_field in stack:  # 중첩 필드는 모든 열린 필드에 귀속
                        open_field["text"] += chunk
                else:
                    outside_chunks.append((_nearest_para(elem), chunk))

        # 누름틀이 있는 문단은 슬롯 판정에서 제외한다. 문단마다 목록을 훑으면
        # (문단 수 × 필드 수) 비교가 되므로 id 집합으로 한 번에 만든다 —
        # field_paras 리스트를 계속 들고 있어야 프록시가 살아 있어 id 가 유효하다.
        field_para_ids = {id(p) for p in field_paras if p is not None}
        for order, (para, text) in enumerate(_group_by_paragraph(outside_chunks)):
            outside_text.append(text)
            if para is None or id(para) in field_para_ids:
                paragraphs.append({"key": [section_name, order], "text": text, "slots": []})
                continue
            _, names = _split_slots(text)
            paragraphs.append({"key": [section_name, order], "text": text, "slots": names})
            for name in names:
                # 값은 여기서 알 수 없다 — 채운 문서에는 `{…}` 가 없기 때문이다.
                # 전/후 문단을 같은 자리끼리 맞춰야 값이 나온다 (`_align`).
                fields.append(
                    {
                        "name": name,
                        "guide": name,
                        "field_type": SLOT_FIELD_TYPE,
                        "section": section_name,
                        "text": "",
                    }
                )

        if stack:
            # begin/end 짝이 맞지 않는 문서 = 파서 또는 템플릿 이상. 버리지 않고 알린다.
            log_warning(
                "hwpx 누름틀 begin/end 짝이 맞지 않는다",
                event="hwpx_unclosed_fields",
                resource_id=section_name,
                item_count=len(stack),
            )
        fields.extend(reversed(stack))

    for item in fields:
        text = item["text"].strip()
        item["filled"] = bool(text) and text != item["guide"].strip()
        item["is_guide_state"] = not item["filled"]

    # 필드 값·문서 텍스트는 로그에 남기지 않는다 (3.8절) — 개수만 남긴다
    log_info(
        "hwpx 스캔 완료",
        event="hwpx_scanned",
        item_count=len(fields),
        status=f"sections={len(loaded['sections'])} filled={sum(1 for f in fields if f['filled'])}",
    )

    return {
        "path": str(path),
        "entries": loaded["entries"],
        "fields": fields,
        # 누름틀 밖 텍스트 원문. 슬롯 값이 섞여 있으므로 **골격 비교에는 쓰지 않는다** —
        # 골격은 전/후 문단을 맞춰 값을 빼낸 `_align` 결과를 쓴다.
        "outside_text": "".join(outside_text),
        "paragraphs": paragraphs,
        "tag_counts": dict(tag_counts),
    }


def _align(before: dict, after: dict) -> dict:
    """전/후 문단을 **같은 자리끼리** 맞춰 골격과 값을 뽑는다.

    이 대조가 필요한 이유: 채운 문서에는 `{…}` 가 남지 않는다. 그래서 "무엇이 값이고
    무엇이 골격인가" 를 채운 문서만 보고는 알 수 없다. 템플릿의 골격 조각을 자로 삼아
    값을 되짚어야 한다.

    문단 자리는 (섹션, 텍스트를 가진 문단의 등장 순번) 으로 짚는다 — 채우기·서식은 문단을
    더하거나 빼지 않고, 본문 블록은 뒤에만 붙는다. 자리가 어긋나면 골격 대조가 실패해
    `broken` 으로 보고된다 (조용히 다른 문단과 비교하지 않는다).
    """
    after_map = {tuple(item["key"]): item["text"] for item in after["paragraphs"]}
    skeleton_before, skeleton_after, broken = [], [], []
    values: dict = {}
    seen = set()

    for item in before["paragraphs"]:
        key = tuple(item["key"])
        seen.add(key)
        filled = after_map.get(key)
        if not item["slots"]:
            skeleton_before.append(item["text"])
            skeleton_after.append(item["text"] if filled is None else filled)
            continue
        parts, names = _split_slots(item["text"])
        skeleton_before.append("".join(parts))
        extracted = None if filled is None else _extract_values(parts, filled)
        if extracted is None:
            broken.append(list(item["key"]))
            skeleton_after.append(filled or "")
            continue
        skeleton_after.append("".join(parts))
        for name, value in zip(names, extracted):
            values.setdefault(name, []).append(value)

    # 채운 문서에만 있는 문단(본문 블록)도 골격 비교에 넣는다 — 내용이 늘어난 사실을
    # 무결성 지표가 알아야 한다.
    for item in after["paragraphs"]:
        if tuple(item["key"]) not in seen:
            skeleton_after.append(item["text"])

    return {
        "skeleton_before": "".join(skeleton_before),
        "skeleton_after": "".join(skeleton_after),
        "values": values,
        "broken_paragraphs": broken,
    }


def _field_map(scan: dict) -> dict:
    """이름 기준 병합 — 같은 이름이 여러 번 나오면 모두 채워졌을 때만 filled."""
    merged: dict = {}
    for item in scan["fields"]:
        slot = merged.setdefault(
            item["name"], {"guide": item["guide"], "occurrences": 0, "filled": True, "values": []}
        )
        slot["occurrences"] += 1
        slot["filled"] = slot["filled"] and item["filled"]
        if item["filled"]:
            slot["values"].append(item["text"].strip())
    return merged


def hwpx_roundtrip(before_path: str, after_path: str, written_values: dict | None = None) -> dict:
    """채움 → 재스캔 라운드트립 판정 일치 + 미입력 필드 안내문 유지 검증.

    - `agreement_rate`: 기대 판정(값을 준 필드=채워짐, 안 준 필드=부족)과
      재스캔 판정이 일치하는 비율. README 계약상 100% 를 유지해야 한다.
    - `guide_state_kept`: 값이 없는 필드가 안내문 상태로 남았는지(부분 초안 계약).
    - `value_mismatch`: 기록한 값과 재스캔한 값이 정규화 후 다른 필드.
    """
    before_scan, after_scan = scan_hwpx(before_path), scan_hwpx(after_path)
    before, after = _field_map(before_scan), _field_map(after_scan)
    # 슬롯 값은 문단 골격 대조로 얻는다 — 채운 문서에는 `{…}` 표기가 없다.
    for name, extracted in _align(before_scan, after_scan)["values"].items():
        written_texts = [value.strip() for value in extracted if value.strip()]
        after[name] = {
            "guide": name,
            "occurrences": len(extracted),
            # 자리가 여럿이면 **전부** 채워졌을 때만 채워진 것으로 본다 (_field_map 과 같은 규칙)
            "filled": bool(written_texts) and len(written_texts) == len(extracted),
            "values": written_texts,
        }
    values = {str(k): str(v) for k, v in (written_values or {}).items()}

    rows, disagreements, guide_broken, value_mismatch = [], [], [], []
    for name in sorted(set(before) | set(after)):
        expected_filled = name in values or (name in before and before[name]["filled"])
        actual = after.get(name)
        actual_filled = bool(actual and actual["filled"])
        agree = expected_filled == actual_filled
        rows.append(
            {
                "field": name,
                "expected_filled": expected_filled,
                "actual_filled": actual_filled,
                "agree": agree,
            }
        )
        if not agree:
            disagreements.append(name)
        if not expected_filled and actual and actual["filled"]:
            guide_broken.append(name)
        if name in values and actual and actual["values"]:
            if normalize(actual["values"][0]) != normalize(values[name]):
                value_mismatch.append(
                    {"field": name, "written": values[name], "rescanned": actual["values"][0]}
                )

    total = len(rows)
    if not total:
        fail(ERR_EMPTY_ITEMS, event="hwpx_roundtrip_no_fields")
    return {
        "fields": total,
        "agreement_rate": round((total - len(disagreements)) / total, 4),
        "disagreements": disagreements,
        "guide_state_kept": not guide_broken,
        "guide_state_broken_fields": guide_broken,
        "value_mismatch": value_mismatch,
        "per_field": rows,
    }


def hwpx_integrity(before_path: str, after_path: str) -> dict:
    """문서 무결성 — 값 자리를 뺀 골격의 텍스트 동일성 + 개체 수 일치.

    채우기는 값 자리의 글자만 바꾸므로 **골격은 글자 단위로 같아야** 한다. 다르면
    파서/필러가 문서를 건드린 것이다. 슬롯 문법에서는 골격이 곧 "중괄호 밖 텍스트" 라
    이 비교가 이전보다 정확하다 — 라벨 방식에서는 콜론 뒤를 값으로 추측해야 했다.

    태그 수는 **개체 기준으로만** 본다. 슬롯에 서식을 걸면 run 이 갈라지므로 글자를
    담는 요소 수가 달라지는 것이 정상이다 (`_TEXT_CARRIER_TAGS`).
    """
    before, after = scan_hwpx(before_path), scan_hwpx(after_path)
    aligned = _align(before, after)
    # 골격은 **중괄호 밖 텍스트**다. 채운 문서에서 값 자리를 되짚어 뺀 뒤 비교한다 —
    # 원문(outside_text)을 그대로 비교하면 채워 넣은 값이 전부 골격 훼손으로 잡힌다.
    text_before = normalize(aligned["skeleton_before"])
    text_after = normalize(aligned["skeleton_after"])

    tags = set(before["tag_counts"]) | set(after["tag_counts"])
    tag_diff = {
        tag: {"before": before["tag_counts"].get(tag, 0), "after": after["tag_counts"].get(tag, 0)}
        for tag in sorted(tags)
        if before["tag_counts"].get(tag, 0) != after["tag_counts"].get(tag, 0)
    }
    # 글자를 담는 요소는 개수가 달라지는 것이 **정상**이다. 슬롯에 서식을 걸려면 그 자리를
    # 전용 run 으로 떼어내야 하고(`{'제목', 16pt}` → run 둘), 여러 `hp:t` 로 쪼개진 자리는
    # 하나로 합쳐진다. 그래서 이 태그들은 보고만 하고 합불에는 넣지 않는다.
    # 대신 표·그림 같은 **개체**와 문단 수는 그대로여야 한다 (아래 objects·p).
    structural_diff = {tag: delta for tag, delta in tag_diff.items() if tag not in _TEXT_CARRIER_TAGS}
    objects = {
        tag: {"before": before["tag_counts"].get(tag, 0), "after": after["tag_counts"].get(tag, 0)}
        for tag in OBJECT_TAGS
    }

    return {
        "outside_text_identical": text_before == text_after,
        "text_length_delta": len(text_after) - len(text_before),
        "tag_count_diff": tag_diff,
        "structural_tag_diff": structural_diff,
        "skeleton_broken_paragraphs": aligned["broken_paragraphs"],
        "object_counts": objects,
        "object_counts_match": all(v["before"] == v["after"] for v in objects.values()),
        "zip_entries_identical": before["entries"] == after["entries"],
        "passed": (
            text_before == text_after
            and not structural_diff
            and not aligned["broken_paragraphs"]
            and before["entries"] == after["entries"]
        ),
    }


def ending_consistency(text: str) -> dict:
    """문서 초반·후반의 종결어미 일관성 (`Text` 규칙 검사, 018 톤 지표).

    종결 유형: 합니다체(~습니다/~합니다), 해요체(~요), 해라체/평서(~다),
    개조식(~함/~임/~됨). 초반 절반과 후반 절반의 우세 유형이 다르면 불일치로 본다.
    """
    sentences = split_sentences(text)
    if not sentences:
        fail(ERR_EMPTY_ITEMS, event="ending_no_sentences")

    def classify(sentence: str) -> str:
        body = sentence.rstrip(" .!?…")
        if body.endswith(("습니다", "합니다", "십니다", "입니다")):
            return "hapnida"
        if body.endswith(("어요", "에요", "예요", "아요", "해요", "세요", "요")):
            return "haeyo"
        if body.endswith(("함", "임", "됨", "음", "짐", "옴")):
            return "gaejosik"
        if body.endswith("다"):
            return "da"
        return "other"

    labels = [classify(s) for s in sentences]
    half = max(1, len(labels) // 2)
    front, back = Counter(labels[:half]), Counter(labels[half:])

    def dominant(counter: Counter) -> str:
        ranked = [(k, v) for k, v in counter.items() if k != "other"]
        return max(ranked, key=lambda kv: kv[1])[0] if ranked else "other"

    front_top, back_top = dominant(front), dominant(back)
    return {
        "sentences": len(sentences),
        "front_dominant": front_top,
        "back_dominant": back_top,
        "consistent": front_top == back_top,
        "distribution": dict(Counter(labels)),
    }
