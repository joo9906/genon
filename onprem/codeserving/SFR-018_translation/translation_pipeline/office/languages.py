"""지원 언어 정의 + 한국어 축 검증 + 결정적 언어 감지.

## 지원 범위 (요구사항)

한국어 · 영어 · 중국어 · 태국어 · 베트남어 · 러시아어 6개.
번역 방향은 **한국어를 반드시 한쪽에 두는 쌍만** 지원한다 —
`ko→en`, `ru→ko` 는 되고 `en→ru` 는 받지 않는다. 사내 문서 흐름이 한국어를 중심으로
돌기 때문이고, 비한국어 쌍은 품질 검증 대상 밖이라 열어두면 검증 안 된 경로가
운영에서 조용히 쓰인다.

## 언어 감지를 LLM 에 맡기지 않는 이유

방향 검증(한국어 축)은 **거부 판정**이다. LLM 이 흔들리면 정상 요청이 400 이 되거나
지원 밖 쌍이 통과한다. 문자 스크립트 판정은 결정적이고, 이 6개 언어는 스크립트가
겹치지 않는다(라틴 계열인 영어·베트남어만 성조 부호로 갈린다).

호출부가 `source_lang` 을 명시하면 감지하지 않는다 — 감지는 폴백이다.

## 한계 (알고 쓰는 것)

- 한자만으로 이루어진 짧은 한국어 문서는 `zh` 로 감지될 수 있다. 그래서 감지 결과를
  응답(`source_lang`, `source_lang_detected`)에 실어 호출부가 확인할 수 있게 한다.
- 숫자·기호뿐인 입력은 감지 불가(`""`)다. 이 경우 방향 검증을 건너뛰고 번역을 진행한다
  — 감지 실패를 거부 사유로 쓰면 표만 있는 문서가 통째로 막힌다.
"""

import unicodedata
from dataclasses import dataclass

KOREAN = "ko"


@dataclass(frozen=True)
class Language:
    code: str
    label: str          # 프롬프트에 넣는 이름 (영문 — LLM 지시문이 영어다)
    korean_label: str   # 사용자 노출용


SUPPORTED_LANGUAGES = (
    Language(code="ko", label="Korean", korean_label="한국어"),
    Language(code="en", label="English", korean_label="영어"),
    Language(code="zh", label="Chinese", korean_label="중국어"),
    Language(code="th", label="Thai", korean_label="태국어"),
    Language(code="vi", label="Vietnamese", korean_label="베트남어"),
    Language(code="ru", label="Russian", korean_label="러시아어"),
)

_BY_CODE = {language.code: language for language in SUPPORTED_LANGUAGES}

# 흔한 별칭 → 코드. 화면·워크플로우 변수가 어떤 표기로 오든 한 곳에서 흡수한다.
_ALIASES = {
    "korean": "ko", "kor": "ko", "ko-kr": "ko", "한국어": "ko", "국문": "ko",
    "english": "en", "eng": "en", "en-us": "en", "영어": "en", "영문": "en",
    "chinese": "zh", "zh-cn": "zh", "zh-hans": "zh", "cn": "zh", "중국어": "zh",
    "thai": "th", "th-th": "th", "태국어": "th",
    "vietnamese": "vi", "vi-vn": "vi", "베트남어": "vi",
    "russian": "ru", "ru-ru": "ru", "러시아어": "ru", "노어": "ru",
}


class LanguageNotSupported(ValueError):
    """지원하지 않는 언어 코드/번역 방향.

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다
    (main.py 가 그대로 API 응답 msg 로 쓴다).
    """


def supported_payload() -> list:
    """`GET /languages` 응답용 — 화면이 선택지를 하드코딩하지 않게 한다."""
    return [
        {"code": language.code, "label": language.korean_label, "en_label": language.label}
        for language in SUPPORTED_LANGUAGES
    ]


def resolve(code: str) -> Language:
    """언어 코드/별칭을 Language 로 바꾼다.

    Raises:
        LanguageNotSupported: 지원 목록에 없음.
    """
    normalized = (code or "").strip().lower().replace("_", "-")
    normalized = _ALIASES.get(normalized, normalized)
    language = _BY_CODE.get(normalized)
    if language is None:
        raise LanguageNotSupported(
            "지원하지 않는 언어입니다. 한국어·영어·중국어·태국어·베트남어·러시아어 중에서 골라 주세요."
        )
    return language


# ── 스크립트 기반 감지 ────────────────────────────────────────

# 베트남어를 영어와 가르는 문자. 라틴 확장 성조 부호가 붙은 글자들이다.
# (nfd 정규화 후 결합 부호로 보는 방법도 있지만, 사전 조합 문자가 대부분이라
#  이쪽이 오탐이 적다.)
_VIETNAMESE_CHARS = set(
    "ăâđêôơưĂÂĐÊÔƠƯ"
    "áàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩị"
    "óòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
)


def _script_of(char: str) -> str:
    """한 글자가 어느 언어 후보에 속하는지. 판정 불가면 빈 문자열."""
    if char in _VIETNAMESE_CHARS:
        return "vi"
    code_point = ord(char)
    if 0xAC00 <= code_point <= 0xD7A3 or 0x1100 <= code_point <= 0x11FF or 0x3130 <= code_point <= 0x318F:
        return "ko"
    if 0x0E00 <= code_point <= 0x0E7F:
        return "th"
    if 0x0400 <= code_point <= 0x04FF or 0x0500 <= code_point <= 0x052F:
        return "ru"
    if 0x4E00 <= code_point <= 0x9FFF or 0x3400 <= code_point <= 0x4DBF or 0xF900 <= code_point <= 0xFAFF:
        return "zh"
    if char.isalpha() and unicodedata.name(char, "").startswith("LATIN"):
        return "en"
    return ""


def detect(text: str, *, sample_chars: int = 4000) -> str:
    """가장 많이 등장한 스크립트의 언어 코드. 판정 불가면 빈 문자열.

    긴 문서 전체를 세지 않고 앞부분 표본만 본다 — 언어는 문서 안에서 바뀌지 않고,
    수십만 자를 세는 비용이 판정 정확도를 올려주지 않는다.

    베트남어는 라틴 문자 위에 얹히므로, 성조 부호가 하나라도 있으면 라틴 표를
    베트남어로 본다 ('en' 과 'vi' 가 같은 글자를 공유해 단순 최빈값으로는 갈리지 않는다).
    """
    counts: dict = {}
    for char in (text or "")[:sample_chars]:
        script = _script_of(char)
        if script:
            counts[script] = counts.get(script, 0) + 1
    if not counts:
        return ""
    if counts.get("vi"):
        counts["vi"] = counts.pop("vi") + counts.pop("en", 0)
    return max(counts.items(), key=lambda item: item[1])[0]


def resolve_direction(target_lang: str, source_lang: str, sample_text: str) -> tuple:
    """(source Language | None, target Language) 를 정하고 한국어 축을 검증한다.

    Args:
        target_lang: 사용자가 고른 대상 언어 (필수).
        source_lang: 호출부가 명시한 원문 언어. 비어 있으면 sample_text 로 감지한다.
        sample_text: 감지용 표본 (번역 대상 본문 앞부분).

    Returns:
        (source, target). source 는 감지 실패 시 None 이다.

    Raises:
        LanguageNotSupported: 지원 밖 언어이거나, 양쪽 다 한국어가 아닌 쌍.
    """
    target = resolve(target_lang)

    source = None
    if (source_lang or "").strip():
        source = resolve(source_lang)
    else:
        detected = detect(sample_text)
        if detected:
            source = _BY_CODE[detected]

    if source is None:
        # 감지 불가(숫자·기호뿐인 문서)는 거부하지 않는다 — 방향 검증만 건너뛴다.
        return None, target

    if source.code == target.code:
        raise LanguageNotSupported("원문과 같은 언어로는 번역할 수 없습니다.")
    if KOREAN not in (source.code, target.code):
        raise LanguageNotSupported(
            "한국어가 포함된 번역만 지원합니다. 원문 또는 번역 대상 중 하나는 한국어여야 합니다."
        )
    return source, target
