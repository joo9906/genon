# =====================================================================================
# genon_ocr — 스캔 쪽 이미지 OCR + 읽는 순서 · 문단 복원 MCP 도구 (area 01)
#
# **이 파일 하나가 등록 단위다.** GenOS MCP 는 소스 파일 한 개를 받아 실행하며,
# `mcp` 객체를 런타임이 전역으로 주입한다. 모든 최상위 심볼에 `OC` 접두어를 붙였다.
#
# ## 어디서 부르나
#
# 첨부 전처리기(`high_preprocessor.py`, `ocr_defer=True`)는 스캔 pdf 쪽을 OCR 하지 않고
# 쪽 이미지를 NFS 에 저장한 뒤 그 자리에 표식(`[[GENON_SCAN page=N image=상대경로]]`)을
# 남긴다. 워크플로우 스텝 1 이 표식을 찾아 이 도구를 부르고, 받은 글로 표식을 바꾼다.
# 이미지는 **경로로 받는다** — 쪽 하나가 수 MB 라 base64 로 게이트웨이를 건너지 않는다.
# 경로는 NFS 루트(`NFS_ROOT`) 기준 상대경로다. 전처리기와 이 서버가 같은 NFS 를 다른
# 자리에 마운트할 수 있어서다.
#
# ## OCR 서버
#
# 지능형 전처리기 · `high_preprocessor` 가 부르는 Paddle OCR 서빙과 같은 요청 · 응답이다
# (`{"file": base64 PNG, "fileType": 1}` → `result.ocrResults[0].prunedResult` 의
# `rec_texts` · `rec_scores` · `rec_boxes`). 실패는 `ok=false` 로 돌려준다 — 스텝이
# 요청을 세운다. 그 쪽만 빈 채 넘기면 본문 일부가 결과에서 조용히 빠진다.
#
# ## 읽는 순서 · 문단
#
# OCR 이 주는 것은 글 상자 목록이라 그대로 이으면 다단이 섞이고 줄마다 문단이 끊긴다.
# 여기서 줄 → 단(거터) → 문단 순으로 다시 묶는다. `high_preprocessor` 의 pdf 문단 복원과
# **같은 규칙을 따르지만 사본은 아니다** — 그쪽은 문서 전체(문서 거터 · 글자 크기 · 그림
# 영역)를 보고, 여기는 한 호출로 받은 쪽들의 상자 좌표만 본다. 한쪽 판정을 고치면 다른
# 쪽도 그 사례에서 같은 답을 내는지 확인한다.
#
# - 쪽 위 · 아래 띠에 되풀이되는 머리말 · 꼬리말과 쪽번호는 뺀다 — 한 문서의 쪽을 함께
#   받아야(3쪽 이상) 머리말을 본문과 가를 수 있다.
# - 쪽을 넘는 문단은 앞 쪽 글에 붙인다(`occarry_over`). 표식이 쪽마다 따로라 그대로 두면
#   쪽 경계마다 문장이 반으로 갈린다.
#
# - 줄 머리 표기(`제5조` · `①` · `1.` · `가.` · 글머리표)는 언제나 새 문단을 연다 — 조/항/호
#   가 문단 머리로 남아야 다음 단계가 위계를 읽는다.
# - 줄 머리 `다.` 는 어미일 수도 있다. 앞 줄이 한글로 끝나고 문장이 안 끝났는데 단을 거의
#   채웠으면 이음으로 본다.
# - 문단 안의 줄은 공백으로 잇는다. 줄 끝이 낱말 경계인지 좌표로 알 수 없고, 붙이는 쪽이
#   검색에 더 해롭다.
#
# **설치가 필요한 패키지를 쓰지 않는다.** stdlib 만으로 돈다 (OCR 호출은 `urllib`).
# =====================================================================================

import base64
import difflib
import json
import logging
import os
import re
import statistics
import struct
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

# ── 로깅 ─────────────────────────────────────────
# 3.8절 기록 허용 필드. 인식한 글은 로그에 남기지 않는다.
OCALLOWED_FIELDS = frozenset(
    {
        "event",
        "trace_id",
        "request_id",
        "resource_id",
        "status",
        "duration_ms",
        "item_count",
        "upstream_status",
        "error_code",
        "error_type",
    }
)

_OClog = logging.getLogger("genon_ocr")


def _OCsetup_logging() -> None:
    """이 파일 전용 **stderr** 핸들러. stdout 은 MCP 전송 채널이 될 수 있다(README §0)."""
    if _OClog.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    _OClog.addHandler(handler)
    _OClog.setLevel(logging.INFO)
    _OClog.propagate = False


_OCsetup_logging()


def _OCprepare(message: str, event: str, fields: dict) -> tuple:
    extra: dict = {"event": event}
    dropped = []
    for key, value in fields.items():
        if key == "event" or key not in OCALLOWED_FIELDS:
            dropped.append(key)
            continue
        if value is not None:
            extra[key] = value
    if dropped:
        message = f"{message} [dropped_fields={','.join(sorted(dropped))}]"
    return message, extra


def oclog_info(message: str, *, event: str, **fields) -> None:
    text, extra = _OCprepare(message, event, fields)
    _OClog.info(text, extra=extra)


def oclog_warning(message: str, *, event: str, **fields) -> None:
    text, extra = _OCprepare(message, event, fields)
    _OClog.warning(text, extra=extra)


# ── mcp shim ─────────────────────────────────────
try:
    mcp  # noqa: F821 - 런타임이 주입한다
except NameError:
    class _OCLocalMCP:
        def tool(self, *args, **kwargs):
            def _decorator(fn):
                return fn
            return _decorator

    mcp = _OCLocalMCP()


# ── 설정 ─────────────────────────────────────────
_OCDEFAULT_ENDPOINT = "http://192.168.73.172:48080/ocr"   # 지능형 전처리기 기본값과 같다
_OCDEFAULT_TIMEOUT = 60.0          # 초 — 쪽 하나 요청
_OCDEFAULT_MIN_SCORE = 0.3         # 인식 점수가 이보다 낮은 상자는 버린다(지능형 `text_score` 기본값)
_OCMAX_IMAGE_BYTES = 40 * 1024 * 1024
_OCMAX_PAGES = 16                  # 한 호출에 받는 쪽 수 — 넘으면 스텝이 나눠 부른다
_OCCONCURRENCY = 4                 # OCR 서버에 동시에 보내는 쪽 수
_OCPNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class OCToolError(ValueError):
    """도구가 `ok=false` 로 돌려줄 실패. `error_type` 은 호출부가 갈라 읽는 고정 값이다."""

    def __init__(self, error_type: str) -> None:
        super().__init__(error_type)
        self.error_type = error_type


def _OCnfs_root() -> str:
    root = (os.environ.get("NFS_ROOT") or "").strip()
    if not root:
        raise OCToolError("NFS_ROOT_MISSING")
    return os.path.realpath(root)


def ocresolve_image(image_path: str) -> str:
    """NFS 루트 기준 상대경로 → 실제 경로. 루트 밖을 가리키면 거절한다."""
    relative = str(image_path or "").strip().lstrip("/\\")
    if not relative:
        raise OCToolError("MISSING_ARG_IMAGE_PATH")
    if not relative.lower().endswith(".png"):
        raise OCToolError("UNSUPPORTED_IMAGE")
    root = _OCnfs_root()
    path = os.path.realpath(os.path.join(root, relative))
    if os.path.commonpath([root, path]) != root:
        raise OCToolError("PATH_OUTSIDE_ROOT")
    if not os.path.isfile(path):
        # 원본은 NFS 보관 정책(한 달)으로 지워진다 — 오래된 대화를 다시 돌리면 여기로 온다.
        raise OCToolError("IMAGE_NOT_FOUND")
    return path


def ocread_png(path: str) -> tuple:
    """(PNG 바이트, 폭, 높이). 크기는 IHDR 에서 읽는다."""
    if os.path.getsize(path) > _OCMAX_IMAGE_BYTES:
        raise OCToolError("IMAGE_TOO_LARGE")
    with open(path, "rb") as fh:
        data = fh.read()
    if not data.startswith(_OCPNG_SIGNATURE) or len(data) < 24:
        raise OCToolError("UNSUPPORTED_IMAGE")
    width, height = struct.unpack(">II", data[16:24])
    return data, width, height


def ocrequest(png: bytes) -> dict:
    """OCR 서버 호출 한 번. 통신 실패와 서버 · 응답 실패를 가른다."""
    endpoint = (os.environ.get("OCR_ENDPOINT") or _OCDEFAULT_ENDPOINT).strip()
    try:
        timeout = float(os.environ.get("OCR_TIMEOUT") or _OCDEFAULT_TIMEOUT)
    except ValueError:
        timeout = _OCDEFAULT_TIMEOUT
    body = json.dumps(
        {"file": base64.b64encode(png).decode("ascii"), "fileType": 1, "visualize": False}
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        oclog_warning("ocr server http error", event="ocr_http_error", upstream_status=exc.code)
        raise OCToolError("OCR_SERVER_ERROR") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OCToolError("OCR_TRANSPORT_FAILED") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OCToolError("OCR_INVALID_RESPONSE") from exc


def ocfields(response: dict) -> list:
    """응답 → `[(글, 점수, (x0, y0, x1, y1) 픽셀)]`. 서버가 오류를 알렸으면 예외."""
    if not isinstance(response, dict):
        raise OCToolError("OCR_INVALID_RESPONSE")
    if response.get("errorCode") not in (0, None):
        raise OCToolError("OCR_SERVER_ERROR")
    results = (response.get("result") or {}).get("ocrResults") or []
    if not results:
        return []
    pruned = results[0].get("prunedResult") or {}
    texts = pruned.get("rec_texts") or []
    scores = pruned.get("rec_scores") or []
    boxes = pruned.get("rec_boxes") or []
    return list(zip(texts, scores, boxes))


# =====================================================================================
# 읽는 순서 · 문단 복원
# =====================================================================================

_OCROW_OVERLAP = 0.5               # 세로로 이만큼 겹치면 같은 줄이다
_OCJOIN_GAP = 1.0                  # 같은 줄 조각 사이가 줄 높이의 이 배 이하면 한 줄로 잇는다
_OCNARROW_RATIO = 0.6              # 본문 폭의 이만큼 못 미치는 줄만 거터 판정에 쓴다
_OCGUTTER_SEARCH = 0.15            # 본문 양끝 이 비율 안에서는 거터를 찾지 않는다
_OCGUTTER_MIN = 0.5                # 거터 최소 폭 — 줄 높이의 배수
_OCGUTTER_NOISE = 0.05             # 거터를 가로지르는 좁은 줄을 이 비율까지 잡음으로 본다
_OCMIN_COLUMN_LINES = 3
_OCHEADER_BAND = 0.12              # 머리말 후보 띠 — 쪽 위 이 비율 (`high_preprocessor` 와 같다)
_OCFOOTER_BAND = 0.10              # 꼬리말 후보 띠 — 쪽 아래 이 비율
_OCRUNNING_SIMILARITY = 0.6
_OCRUNNING_MIN_PAGES = 3
_OCRUNNING_PAGE_RATIO = 0.25
_OCGAP_FACTOR = 1.6
_OCSHORT_LINE = 0.3
_OCSHORT_SENTENCE = 0.08
_OCFULL_LINE = 0.1                 # 단 오른쪽 끝에서 이만큼 안에 끝나면 단을 채운 줄이다
_OCINDENT = 0.8                    # 줄 높이의 이 배 넘게 들여 쓰면 새 문단이다

_OCSENTENCE_END_RE = re.compile(r"[.!?。:;][\"'”’」』)\]]*$")
_OCHYPHEN_RE = re.compile(r"[A-Za-z]-$")
_OCPAGE_NO_RE = re.compile(r"^[-–—\s]*\d{1,4}\s*(?:/\s*\d{1,4})?[-–—\s]*$")
_OCMARKER_RE = re.compile(
    r"^(?:제\s*\d+\s*[편장절관조]"
    r"|부\s*칙"
    r"|[①-⑳]"
    r"|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ][.．]"
    r"|\d{1,2}[.．)）](?=\s|[가-힣A-Za-z])"
    r"|[가나다라마바사아자차카타파하][.．)）](?=\s|[가-힣A-Za-z])"
    r"|[(（]\d{1,2}[)）]"
    r"|[•·∙◦○●□■▪▫◆◇▶►※*\-–—]\s)"
)
_OCENDING_MARKER_RE = re.compile(r"^[가나다라마바사아자차카타파하][.．]")


@dataclass(frozen=True)
class OCLine:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def height(self) -> float:
        return max(1.0, self.y1 - self.y0)


def ocrows(items: list) -> list:
    """상자 → 세로로 겹치는 것끼리 묶은 줄 후보."""
    rows: list = []
    for item in sorted(items, key=lambda it: ((it.y0 + it.y1) / 2, it.x0)):
        for row in reversed(rows[-3:]):
            top = min(member.y0 for member in row)
            bottom = max(member.y1 for member in row)
            overlap = min(bottom, item.y1) - max(top, item.y0)
            if overlap > _OCROW_OVERLAP * min(bottom - top, item.height):
                row.append(item)
                break
        else:
            rows.append([item])
    return rows


def ocmerge_row(row: list, height: float) -> list:
    """한 줄 후보 안에서 가까이 붙은 조각끼리 한 줄로. 단 사이처럼 멀면 따로 둔다."""
    merged: list = []
    for item in sorted(row, key=lambda it: it.x0):
        if merged and item.x0 - merged[-1].x1 <= _OCJOIN_GAP * height:
            last = merged[-1]
            merged[-1] = OCLine(
                last.x0, min(last.y0, item.y0), max(last.x1, item.x1), max(last.y1, item.y1),
                f"{last.text} {item.text}",
            )
        else:
            merged.append(item)
    return merged


def ocgutters(lines: list, height: float) -> list:
    """단 사이 빈 세로띠 `[(시작, 끝)]`. 좁은 줄이 덮지 않는 자리 중 양쪽에 줄이 넉넉한 곳."""
    if len(lines) < 2 * _OCMIN_COLUMN_LINES:
        return []
    left = min(line.x0 for line in lines)
    right = max(line.x1 for line in lines)
    width = right - left
    if width <= 0:
        return []
    narrow = [line for line in lines if line.x1 - line.x0 < _OCNARROW_RATIO * width]
    if len(narrow) < 2 * _OCMIN_COLUMN_LINES:
        return []
    size = int(width) + 1
    cover = [0] * size
    for line in narrow:
        for x in range(max(0, int(line.x0 - left)), min(size, int(line.x1 - left) + 1)):
            cover[x] += 1
    noise = int(_OCGUTTER_NOISE * len(narrow))
    lo = int(_OCGUTTER_SEARCH * width)
    hi = int((1 - _OCGUTTER_SEARCH) * width)
    gutters: list = []
    start = None
    for x in range(lo, hi + 1):
        free = x < hi and cover[x] <= noise
        if free and start is None:
            start = x
        elif not free and start is not None:
            if x - start >= max(4.0, _OCGUTTER_MIN * height):
                g0, g1 = left + start, left + x
                before = sum(1 for line in narrow if line.x1 <= g0 + 1)
                after = sum(1 for line in narrow if line.x0 >= g1 - 1)
                if before >= _OCMIN_COLUMN_LINES and after >= _OCMIN_COLUMN_LINES:
                    gutters.append((g0, g1))
            start = None
    return gutters


def occolumn_of(line: OCLine, gutters: list) -> int:
    """단 번호. 거터를 가로지르면 -1(전폭)."""
    for g0, g1 in gutters:
        if line.x0 < g0 - 1 and line.x1 > g1 + 1:
            return -1
    center = (line.x0 + line.x1) / 2
    return sum(1 for g0, _ in gutters if center > g0)


def ocorder(lines: list, gutters: list) -> list:
    """읽는 순서의 `[(group, column, 줄)]`. 전폭 줄이 띠를 가르고, 띠 안은 단 순서대로 읽는다."""
    ordered: list = []
    band: list = []
    group = [0]

    def flush() -> None:
        for column in range(len(gutters) + 1):
            members = [line for line in band if occolumn_of(line, gutters) == column]
            if members:
                group[0] += 1
                ordered.extend(
                    (group[0], column, line) for line in sorted(members, key=lambda l: l.y0)
                )
        band.clear()

    for line in sorted(lines, key=lambda l: (l.y0, l.x0)):
        if gutters and occolumn_of(line, gutters) == -1:
            flush()
            group[0] += 1
            ordered.append((group[0], -1, line))
        else:
            band.append(line)
    flush()
    return ordered


def ocparagraphs(ordered: list, height: float) -> tuple:
    """읽는 순서의 줄 → (문단 글 목록, 마지막 문단이 다음 쪽으로 이어지는가).

    단 폭은 **단 하나 전체**(쪽 위아래 모든 띠)의 줄로 잰다 — 한두 줄짜리 띠는 자기 줄 폭이
    곧 단 폭이라 "짧게 끝난 줄" 을 판정할 수 없다. 전폭 줄은 쪽 전체 폭으로 잰다.
    줄 간격은 같은 group(띠 하나의 단 하나) 안에서만 잰다.
    """
    lines = [line for _, _, line in ordered]
    page_edge = (min(line.x0 for line in lines), max(line.x1 for line in lines))
    columns: dict = {}
    groups: dict = {}
    for group, column, line in ordered:
        columns.setdefault(column, []).append(line)
        groups.setdefault(group, []).append(line)
    edges = {
        column: page_edge if column == -1
        else (min(line.x0 for line in members), max(line.x1 for line in members))
        for column, members in columns.items()
    }
    gaps = {}
    for group, members in groups.items():
        positive = [b.y0 - a.y1 for a, b in zip(members, members[1:]) if b.y0 - a.y1 > 0]
        gaps[group] = statistics.median(positive) if positive else None

    paragraphs: list = []
    parts: list = []
    previous = None
    for group, column, line in ordered:
        if previous is not None:
            prev_group, prev_column, prev_line = previous
            if ocbreaks(prev_line, line, edges[prev_column], edges[column],
                        gaps[group] if prev_group == group else None,
                        prev_group == group, height):
                paragraphs.append(ocjoin(parts))
                parts = []
        parts.append(line.text)
        previous = (group, column, line)
    if parts:
        paragraphs.append(ocjoin(parts))
    _, last_column, last = previous
    left, right = edges[last_column]
    open_tail = (
        last.x1 >= right - _OCFULL_LINE * max(1.0, right - left)
        and not _OCSENTENCE_END_RE.search(last.text)
    )
    return paragraphs, open_tail


def ocbreaks(previous: OCLine, line: OCLine, prev_edge: tuple, edge: tuple, gap,
             same_group: bool, height: float) -> bool:
    """`previous` 다음에 `line` 이 새 문단을 여는가."""
    left, right = prev_edge
    width = max(1.0, right - left)
    full = previous.x1 >= right - _OCFULL_LINE * width
    ended = bool(_OCSENTENCE_END_RE.search(previous.text))
    if _OCMARKER_RE.match(line.text):
        ending = (
            _OCENDING_MARKER_RE.match(line.text)
            and re.search(r"[가-힣]$", previous.text)
            and not ended
            and full
        )
        if not ending:
            return True
    if previous.x1 < right - _OCSHORT_LINE * width:
        return True
    if ended and previous.x1 < right - _OCSHORT_SENTENCE * width:
        return True
    if not same_group:
        # 단 · 띠가 바뀌는 자리 — 앞 줄이 단을 채우고 문장이 안 끝났을 때만 잇는다.
        return ended or not full
    if gap is not None and line.y0 - previous.y1 > _OCGAP_FACTOR * gap + 1.0:
        return True
    return line.x0 - edge[0] > _OCINDENT * height


def ocjoin(parts: list) -> str:
    text = parts[0]
    for part in parts[1:]:
        if _OCHYPHEN_RE.search(text) and part[:1].islower():
            text = text[:-1] + part
        else:
            text = f"{text} {part}"
    return text


def ocpage_lines(fields: list, min_score: float) -> tuple:
    """OCR 상자 → (줄 목록, 줄 높이 중앙값, 버린 상자 수)."""
    items: list = []
    dropped = 0
    for text, score, box in fields:
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        try:
            ok = bool(text) and float(score or 0.0) >= min_score and len(box) == 4
        except (TypeError, ValueError):
            ok = False
        if not ok:
            dropped += 1
            continue
        x0, y0, x1, y1 = (float(value) for value in box)
        items.append(OCLine(x0, y0, x1, y1, text))
    if not items:
        return [], 0.0, dropped
    height = statistics.median(item.height for item in items)
    lines = [line for row in ocrows(items) for line in ocmerge_row(row, height)]
    return lines, height, dropped


def ocrunning_key(text: str) -> str:
    return re.sub(r"[\d\s]+", "", text)


def ocin_margin(line: OCLine, page_height: float) -> bool:
    return line.y1 <= _OCHEADER_BAND * page_height or line.y0 >= (1 - _OCFOOTER_BAND) * page_height


def ocrunning_keys(pages: list) -> list:
    """여러 쪽 위 · 아래 띠에 되풀이되는 줄의 키. 쪽 하나만 보면 머리말을 본문과 가를 수 없다."""
    if len(pages) < _OCRUNNING_MIN_PAGES:
        return []
    candidates: list = []
    for lines, page_height in pages:
        keys = {ocrunning_key(line.text) for line in lines if ocin_margin(line, page_height)}
        candidates.append({key for key in keys if len(key) >= 2})
    need = max(_OCRUNNING_MIN_PAGES, int(_OCRUNNING_PAGE_RATIO * len(pages) + 0.999))
    running: list = []
    for keys in candidates:
        for key in keys:
            if any(ocsimilar(key, known) for known in running):
                continue
            count = sum(1 for other in candidates if any(ocsimilar(key, item) for item in other))
            if count >= need:
                running.append(key)
    return running


def ocsimilar(left: str, right: str) -> bool:
    if left == right:
        return True
    return difflib.SequenceMatcher(None, left, right).ratio() >= _OCRUNNING_SIMILARITY


def ocbody_lines(lines: list, page_height: float, running: list) -> list:
    """쪽번호 · 되풀이 머리말을 뺀 본문 줄."""
    body = []
    for line in lines:
        if ocin_margin(line, page_height):
            if _OCPAGE_NO_RE.match(line.text):
                continue
            key = ocrunning_key(line.text)
            if any(ocsimilar(key, known) for known in running):
                continue
        body.append(line)
    return body


@dataclass
class OCPage:
    paragraphs: list
    column_count: int
    open_tail: bool = False


def oclayout(lines: list, height: float) -> OCPage:
    """본문 줄 → 쪽 하나의 문단."""
    if not lines:
        return OCPage([], 0)
    gutters = ocgutters(lines, height)
    paragraphs, open_tail = ocparagraphs(ocorder(lines, gutters), height)
    return OCPage(paragraphs, len(gutters) + 1, open_tail)


def occarry_over(pages: list) -> None:
    """쪽을 넘어 이어지는 문단을 앞 쪽으로 붙인다(제자리 수정).

    앞 쪽 마지막 줄이 단을 채우고 문장이 안 끝났고, 다음 쪽 첫 줄이 조/항/호 · 글머리 표기가
    아니면 한 문단이다(줄 머리 `다.` 는 어미일 수 있어 `ocbreaks` 와 같이 본다). 받은 쪽 목록은 **연속한 쪽**이어야 한다 — 사이에 텍스트 쪽이 끼면
    호출부가 나눠 부른다. 쪽 글은 표식 자리마다 따로 들어가므로 옮겨 붙여야 이어진다.
    """
    for previous, page in zip(pages, pages[1:]):
        if not (previous.open_tail and previous.paragraphs and page.paragraphs):
            continue
        head = page.paragraphs[0]
        ending = _OCENDING_MARKER_RE.match(head) and re.search(r"[가-힣]$", previous.paragraphs[-1])
        if _OCMARKER_RE.match(head) and not ending:
            continue
        previous.paragraphs[-1] = ocjoin([previous.paragraphs[-1], head])
        page.paragraphs.pop(0)


# =====================================================================================
# 도구
# =====================================================================================

def ocparse_paths(image_paths) -> list:
    if isinstance(image_paths, str):
        raw = image_paths.strip()
        if not raw:
            raise OCToolError("MISSING_ARG_IMAGE_PATHS")
        if raw.startswith("["):
            try:
                image_paths = json.loads(raw)
            except json.JSONDecodeError:
                raise OCToolError("INVALID_TYPE_IMAGE_PATHS") from None
        else:
            image_paths = [raw]
    if not isinstance(image_paths, list) or not all(isinstance(p, str) for p in image_paths):
        raise OCToolError("INVALID_TYPE_IMAGE_PATHS")
    if not image_paths:
        raise OCToolError("MISSING_ARG_IMAGE_PATHS")
    if len(image_paths) > _OCMAX_PAGES:
        raise OCToolError("TOO_MANY_IMAGES")
    return image_paths


def ocscan_pages(image_paths, min_score) -> dict:
    paths = ocparse_paths(image_paths)
    if min_score is None or min_score == "":
        threshold = _OCDEFAULT_MIN_SCORE
    else:
        try:
            threshold = float(min_score)
        except (TypeError, ValueError):
            raise OCToolError("INVALID_TYPE_MIN_SCORE") from None
    # 경로 · 파일을 먼저 다 확인한다 — OCR 을 몇 쪽 돌린 뒤에 없는 파일로 멈추면 그 호출이 헛돈다.
    images = [ocread_png(ocresolve_image(path)) for path in paths]
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=min(_OCCONCURRENCY, len(images))) as pool:
        responses = list(pool.map(lambda image: ocrequest(image[0]), images))
    pages = []
    dropped = 0
    for response, (_png, _width, page_height) in zip(responses, images):
        lines, height, lost = ocpage_lines(ocfields(response), threshold)
        dropped += lost
        pages.append((lines, height, float(page_height)))
    running = ocrunning_keys([(lines, page_height) for lines, _, page_height in pages])
    layouts = [
        oclayout(ocbody_lines(lines, page_height, running), height)
        for lines, height, page_height in pages
    ]
    occarry_over(layouts)
    results = [
        {
            "image_path": path,
            "text": "\n\n".join(layout.paragraphs),
            "paragraph_count": len(layout.paragraphs),
            "column_count": layout.column_count,
        }
        for path, layout in zip(paths, layouts)
    ]
    oclog_info(
        "scan pages recognized",
        event="ocr_scan_pages",
        item_count=len(results),
        duration_ms=int((time.monotonic() - start) * 1000),
    )
    return {
        "ok": True,
        "pages": results,
        "page_count": len(results),
        "dropped_count": dropped,
        "running_count": len(running),
    }


def _oc_run(arguments: dict) -> str:
    try:
        result = ocscan_pages(arguments.get("image_paths"), arguments.get("min_score"))
    except OCToolError as exc:
        oclog_warning("scan pages failed", event="ocr_scan_failed", error_type=exc.error_type)
        result = {"ok": False, "error_type": exc.error_type}
    except Exception as exc:  # noqa: BLE001 - 최종 방어선. 원문은 응답에 싣지 않는다 (3.8절)
        oclog_warning("scan pages failed", event="ocr_scan_failed", error_type=type(exc).__name__)
        result = {"ok": False, "error_type": "TOOL_EXECUTION_FAILED"}
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def ocr_scan_pages(image_paths: list | str = "", min_score: float | str | None = None) -> str:
    """[언제 쓰나] 첨부 원문에 스캔 쪽 표식(`[[GENON_SCAN page=N image=…]]`)이 있을 때.

    표식의 `image` 경로(NFS 루트 기준 상대경로, PNG)들을 OCR 해 쪽마다 **읽는 순서대로 묶은
    문단**을 낸다. 다단은 단 순서로 읽고, 조/항/호 표기는 문단 머리로 남긴다. 한 문서의
    쪽을 **함께** 넘겨야 쪽마다 되풀이되는 머리말 · 꼬리말을 뺄 수 있다(3쪽 이상).

    Args:
        image_paths: 표식의 `image=` 값 목록 — **한 문서의 연속한 쪽**을 쪽 순서로 (최대 16개).
            쪽을 넘는 문단은 앞 쪽 글에 붙여 낸다. JSON 배열 문자열도 받는다.
        min_score: 이보다 인식 점수가 낮은 상자는 버린다 (기본 0.3).

    Returns:
        JSON 문자열 `{"ok", "pages": [{"image_path", "text", "paragraph_count",
        "column_count"}], "page_count", "dropped_count", "running_count"}`.
        실패면 `{"ok": false, "error_type"}` — `IMAGE_NOT_FOUND`(원본이 지워졌다) ·
        `OCR_TRANSPORT_FAILED` · `OCR_SERVER_ERROR` · `OCR_INVALID_RESPONSE` ·
        `NFS_ROOT_MISSING` · `PATH_OUTSIDE_ROOT` · `UNSUPPORTED_IMAGE` · `TOO_MANY_IMAGES`.
        **한 쪽이라도 실패하면 전체가 실패다.** 실패를 빈 글로 바꾸지 말 것 — 그 쪽 본문이
        조용히 빠진다.
    """
    return _oc_run({"image_paths": image_paths, "min_score": min_score})
