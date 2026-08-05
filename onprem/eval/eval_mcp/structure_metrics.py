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
# ── 라벨 항목 (`제목: {고딕, 16pt}`) — 006 현장 템플릿의 실제 방식 ──
# 운영 코드와 같은 규칙을 이 패키지가 따로 구현한다 (파서 공유 금지 — 모듈 docstring).
LABEL_FIELD_TYPE = "LABEL"
_LABEL_MAX_CHARS = 20
_LABEL_MAX_WORDS = 3
_LABEL_LINE_RE = re.compile(r"^\s*([^\s:：][^:：]*?)\s*[:：]\s*(.*)$", re.DOTALL)
_SPEC_BLOCK_RE = re.compile(r"\{[^{}]*\}")
_LABEL_FORBIDDEN = ".!?\t\r\n"
# 개수 일치를 특히 눈에 띄게 보고할 개체 태그 (표·이미지·수식 등)
OBJECT_TAGS = ("tbl", "pic", "container", "equation", "ole", "line", "rect", "chart")


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


def _is_label_name(label: str) -> bool:
    if not label or len(label) > _LABEL_MAX_CHARS:
        return False
    if any(ch in label for ch in _LABEL_FORBIDDEN):
        return False
    return len(label.split()) <= _LABEL_MAX_WORDS


def _split_label_line(text: str):
    """`제목: 값` → ("제목", "값"). 라벨 항목이 아니면 None.

    서식 명세 표기 `{…}` 는 값에서 뺀다 — 채우기 단계가 산출물에서 지우는 대상이라
    채움 전/후 비교에서 텍스트 차이로 잡히면 안 된다.
    """
    if not text.strip() or "{{" in text:
        return None
    match = _LABEL_LINE_RE.match(text)
    if not match:
        return None
    label = match.group(1).strip()
    if not _is_label_name(label):
        return None
    return label, _SPEC_BLOCK_RE.sub("", match.group(2)).strip()


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
    - 라벨 항목: 본문에 텍스트로 적힌 `제목: {고딕, 16pt}` 문단. 항목명은 문서 골격,
      콜론 뒤는 값으로 나눠 센다. 이렇게 나누지 않으면 무결성 지표가 "채워 넣은 값"을
      골격 훼손으로 오판한다.
    """
    loaded = _read_sections(path)
    fields, outside_text = [], []
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

        for para, text in _group_by_paragraph(outside_chunks):
            parsed = None
            if para is not None and not any(p is para for p in field_paras):
                parsed = _split_label_line(text)
            if parsed is None:
                outside_text.append(text)
                continue
            label, value = parsed
            # 항목명 + 콜론은 문서 골격이라 무결성 비교 대상, 콜론 뒤 값은 필드다
            outside_text.append(f"{label}:")
            fields.append(
                {
                    "name": label,
                    "guide": "",
                    "field_type": LABEL_FIELD_TYPE,
                    "section": section_name,
                    "text": value,
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
        "outside_text": "".join(outside_text),
        "tag_counts": dict(tag_counts),
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
    before, after = _field_map(scan_hwpx(before_path)), _field_map(scan_hwpx(after_path))
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
    """문서 무결성 — 필드 값 제외 영역의 텍스트 동일성 + 개체 수 일치.

    누름틀 치환은 필드 run 의 텍스트만 바꾸므로, 필드 밖 텍스트와 모든 XML
    태그 수는 **바이트 단위로 같아야** 한다. 다르면 파서/필러가 문서를 건드린 것이다.
    """
    before, after = scan_hwpx(before_path), scan_hwpx(after_path)
    text_before, text_after = normalize(before["outside_text"]), normalize(after["outside_text"])

    tags = set(before["tag_counts"]) | set(after["tag_counts"])
    tag_diff = {
        tag: {"before": before["tag_counts"].get(tag, 0), "after": after["tag_counts"].get(tag, 0)}
        for tag in sorted(tags)
        if before["tag_counts"].get(tag, 0) != after["tag_counts"].get(tag, 0)
    }
    objects = {
        tag: {"before": before["tag_counts"].get(tag, 0), "after": after["tag_counts"].get(tag, 0)}
        for tag in OBJECT_TAGS
    }

    return {
        "outside_text_identical": text_before == text_after,
        "text_length_delta": len(text_after) - len(text_before),
        "tag_count_diff": tag_diff,
        "object_counts": objects,
        "object_counts_match": all(v["before"] == v["after"] for v in objects.values()),
        "zip_entries_identical": before["entries"] == after["entries"],
        "passed": text_before == text_after and not tag_diff and before["entries"] == after["entries"],
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
