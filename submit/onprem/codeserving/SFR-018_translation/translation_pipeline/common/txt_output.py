"""내려받는 .txt 의 인코딩·줄바꿈·파일명 규약 (2026-08-12 신규).

SFR-018 세 기능(번역·글다듬이·FAQ)의 **유일한 산출 형식이 txt** 로 통일되면서 생겼다.
그전에는 FAQ 만 파일을 냈고 형식이 hwpx/pdf/xlsx 세 가지였다 — 그쪽은 전부 걷어냈다
(`git show archive/sfr018-doc-export` 에 남아 있다).

## 왜 세 단위에 같은 파일이 있나

배포 단위 간 import 금지(onprem 규칙)라 사본이다. 표 격자 규칙·톤 프리셋과 같은 성격의
**의도된 중복**이고, 갈렸는지는 `onprem/test/check_unit_endpoints.py` 가 세 단위의 응답
**바이트를 직접 대조**해 본다(정적 diff 가 아니라 동작으로 본다).

## BOM + CRLF — "메모장에서 열린다"가 이 파일의 목적이다

사용자는 이 파일을 받아 **윈도우 메모장**에서 편집한다. 그래서 둘을 붙인다:

- **CRLF**: 1809 이전 메모장은 LF 만 있는 파일의 줄바꿈을 렌더하지 못해 **전체가 한 줄로**
  붙어 보인다. 폐쇄망 사내 PC 의 윈도우 빌드를 우리가 통제할 수 없으므로 CRLF 로 낸다.
- **UTF-8 BOM**: BOM 이 없으면 옛 메모장은 파일을 ANSI(=cp949)로 읽어 **한글이 깨진다.**
  BOM 이 있으면 어느 버전이든 UTF-8 로 확정한다.

**환경변수로 끄지 않는다.** 스위치를 두면 "어떤 PC 에서는 깨진다"가 되고, 그 상태는
로그에 아무 흔적도 남기지 않는다 — 재현 불가한 제보만 남는다.

## 파일명은 값으로 만들되 헤더에 값을 그대로 싣지 않는다

제목은 사용자·문서에서 온 문자열이다. 경로 구분자·제어문자를 지우고
(`safe_stem`) RFC 5987 로 인코딩해서(`content_disposition`) 헤더에 넣는다 —
따옴표나 개행이 섞인 제목으로 응답 헤더가 갈라지지 않게 한다.

## 줄 **중간**의 강조 기호만 뗀다 (2026-08-14 추가)

메모장에는 마크다운 렌더러가 없어서 `**단어**` 가 별표 그대로 보인다. 그래서 파일에서는
인라인 강조를 뗀다 — **글자는 남기고 기호만** 지운다.

떼지 않는 것이 더 중요하다:

- **줄머리 기호**(`#` `-` `>` `1.`)와 **표의 `|`**, 표 구분선은 **구조**다. 지우면 문서
  모양이 통째로 무너지고, 그건 사용자가 메모장에서 되살릴 수 없다.
- **줄 전체를 감싼 강조**(`**2026년 실적**` 한 줄)는 남긴다. 그건 제목으로 쓴 것이라
  기호가 곧 위계 표시다 — 인라인 강조와 목적이 다르다.
- **코드펜스(``` ) 블록 안**은 손대지 않는다. 거기서 `*`·`_` 는 코드의 일부다.

화면(마크다운)에는 적용하지 않는다 — 렌더러가 굵게 보여주므로 뗄 이유가 없고, 떼면
원문이 강조한 단어를 잃는다. **적용 지점은 이 파일 하나**(`to_bytes`)이고, 그래서 세
단위가 같은 규칙을 쓴다.
"""

import re

# 메모장이 인코딩을 확정할 수 있게 붙인다 (위 머리말 참고).
_BOM = b"\xef\xbb\xbf"

MEDIA_TYPE = "text/plain; charset=utf-8"
EXTENSION = "txt"

# 파일명에 쓸 수 없거나 쓰면 곤란한 것: 윈도우 금지 문자 + 경로 구분자.
_FORBIDDEN_CHARS = '\\/:*?"<>|'
_MAX_STEM_CHARS = 80

# 줄머리의 구조 기호 — 여기까지는 건드리지 않고, **그 뒤부터** 강조를 뗀다.
# (`- **항목**: 값` 에서 `- ` 는 목록 기호이고 `**항목**` 이 인라인 강조다.)
_LEADING_RE = re.compile(r"^[ \t]*(?:(?:[#>]+|[-*+]|\d+[.)])[ \t]+|[#>]+|\|)*")
_FENCE_RE = re.compile(r"^[ \t]*(?:```|~~~)")

# 짝을 이루고 **안쪽이 공백으로 시작·끝나지 않는** 강조만 뗀다.
# `_` 는 앞뒤가 단어 문자가 아닐 때만 본다 — `snake_case` 를 강조로 오인하면 식별자가 깨진다.
_INLINE_RULES = (
    re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*"),
    re.compile(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)"),
    re.compile(r"(?<![\w*])\*(?=[^\s*])([^*]+?)(?<=[^\s*])\*(?![\w*])"),
    re.compile(r"(?<![\w_])_(?=[^\s_])([^_]+?)(?<=[^\s_])_(?![\w_])"),
    re.compile(r"`([^`]+)`"),
)

# 줄 전체가 하나의 강조로 감싸여 있으면 제목으로 쓴 것이라 남긴다.
_WHOLE_LINE_RE = re.compile(r"^(?:\*\*(?=\S).*(?<=\S)\*\*|__(?=\S).*(?<=\S)__)$")


def strip_inline_marks(text: str) -> str:
    """줄 **중간**의 마크다운 강조 기호를 뗀다 (규칙은 머리말 참고).

    표 셀 안의 강조도 뗀다 — 셀 안 `**단어**` 역시 인라인이다. `|` 는 이 정규식들이
    건드리지 않으므로 격자는 그대로다.
    """
    lines = (text or "").split("\n")
    out = []
    in_fence = False
    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue

        head = _LEADING_RE.match(line).group(0)
        body = line[len(head):]
        if _WHOLE_LINE_RE.match(body.strip()):
            out.append(line)
            continue
        for rule in _INLINE_RULES:
            body = rule.sub(r"\1", body)
        out.append(head + body)
    return "\n".join(out)


def to_bytes(text: str) -> bytes:
    """본문 문자열 → 내려줄 바이트. 인라인 강조를 떼고, CRLF 로 통일하고, BOM 을 붙인다.

    입력에 이미 CRLF 가 섞여 있어도 `\\r\\r\\n` 이 되지 않게 **먼저 LF 로 접었다가** 펴낸다.
    **강조 제거를 여기서 하는 이유**: 세 단위의 호출부가 각자 부르면 한 곳이 빠져도
    아무도 모른다. 파일을 만드는 유일한 길목이 여기다.
    """
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = strip_inline_marks(normalized)
    return _BOM + normalized.replace("\n", "\r\n").encode("utf-8")


def safe_stem(title: str, default: str) -> str:
    """제목 → 파일명 본체. 비면 `default` 를 쓴다.

    제어문자·경로 구분자를 지우고 공백을 한 칸으로 접는다. 확장자는 붙이지 않는다 —
    호출부가 `EXTENSION` 과 조립한다.
    """
    cleaned = []
    for ch in (title or ""):
        if ch in _FORBIDDEN_CHARS or ord(ch) < 32:
            continue
        cleaned.append(ch)
    stem = " ".join("".join(cleaned).split())[:_MAX_STEM_CHARS].strip(" .")
    return stem or default


def download_filename(stem: str) -> str:
    """업로드에 쓸 파일명 — `stem.txt` (2026-08-28 신규).

    `content_disposition` 은 헤더용이라 RFC 5987 인코딩이 섞여 업로드 폼에 쓸 수 없다.
    파일명 조립을 호출부가 각자 하면 세 단위의 확장자가 갈릴 수 있어 여기에 둔다.
    """
    return f"{stem}.{EXTENSION}"


def content_disposition(stem: str) -> str:
    """`Content-Disposition` 헤더 값. 한글 파일명이므로 RFC 5987 만 쓴다.

    `filename=` 을 함께 주지 않는 이유: ASCII 로 접을 수 없는 제목을 억지로 옮겨 적으면
    브라우저에 따라 그쪽을 골라 깨진 이름으로 저장된다. `filename*` 은 현행 브라우저가
    전부 이해한다.
    """
    import urllib.parse

    quoted = urllib.parse.quote(f"{stem}.{EXTENSION}")
    return f"attachment; filename*=UTF-8''{quoted}"


def headers(stem: str, **extra: str) -> dict:
    """`Response(headers=...)` 에 그대로 넣는 헤더 묶음."""
    merged = {"Content-Disposition": content_disposition(stem)}
    merged.update({key: str(value) for key, value in extra.items()})
    return merged
