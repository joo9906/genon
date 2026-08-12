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
"""

# 메모장이 인코딩을 확정할 수 있게 붙인다 (위 머리말 참고).
_BOM = b"\xef\xbb\xbf"

MEDIA_TYPE = "text/plain; charset=utf-8"
EXTENSION = "txt"

# 파일명에 쓸 수 없거나 쓰면 곤란한 것: 윈도우 금지 문자 + 경로 구분자.
_FORBIDDEN_CHARS = '\\/:*?"<>|'
_MAX_STEM_CHARS = 80


def to_bytes(text: str) -> bytes:
    """본문 문자열 → 내려줄 바이트. 줄바꿈을 CRLF 로 통일하고 BOM 을 붙인다.

    입력에 이미 CRLF 가 섞여 있어도 `\\r\\r\\n` 이 되지 않게 **먼저 LF 로 접었다가** 펴낸다.
    """
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
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
