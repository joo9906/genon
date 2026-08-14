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

## 용어사전은 **한국어·영어에만** 적용한다 (2026-08-14 요구 확정)

`glossary_supported` 가 그 사실을 언어 정의에 담는다. 중국어·태국어·베트남어·러시아어는
사내 용어사전이 없으므로 **LLM 만으로 번역**한다.

정책을 여기 두는 이유는 **화면과 실행이 같은 표를 봐야** 하기 때문이다. 프론트는
`GET /languages` 로 선택지를 받아 그리고, 실행부(`glossary_report`)는 같은 함수로 게이트한다.
어느 한쪽에 하드코딩하면 "화면에는 용어사전 적용이라고 떴는데 실제로는 안 걸린 상태" 가
되고, 그 어긋남은 준수율이 늘 1.0 으로 나와 **정상처럼 보인다**.

**쌍으로 판정한다** (`glossary_applies`). 대상 언어만 보면 `ru→ko` 가 통과하는데, 그때
색인은 영어 원문 용어를 들고 있어 러시아어 본문에 맞을 리가 없다 — 걸리지도 않을 조회를
돌리고 "준수율 1.0" 을 내는 셈이다. 원문 언어를 감지하지 못했으면 막지 않는다(조회가
빈손으로 끝날 뿐이고, 감지 실패를 이유로 기능을 끄면 표만 있는 문서에서 사전이 사라진다).

## 한계 (알고 쓰는 것)

- 한자만으로 이루어진 짧은 한국어 문서는 `zh` 로 감지될 수 있다. 그래서 감지 결과를
  응답(`source_lang`, `source_lang_detected`)에 실어 호출부가 확인할 수 있게 한다.
- 숫자·기호뿐인 입력은 감지 불가(`""`)다. 이때는 **대상 언어로 갈린다**(2026-08-14):
  대상이 한국어면 축이 이미 성립하므로 통과시키고(표만 있는 문서를 막지 않는다),
  대상이 비한국어면 **원문 언어를 명시하라고 거부한다** — 원문이 한국어라는 것을 아무도
  확인해 주지 않는 상태로 통과시키면 `en→ru` 를 허용하는 뒷문이 된다.
"""

import unicodedata
from dataclasses import dataclass

KOREAN = "ko"


@dataclass(frozen=True)
class Language:
    code: str
    label: str          # 프롬프트에 넣는 이름 (영문 — LLM 지시문이 영어다)
    korean_label: str   # 사용자 노출용
    # 사내 용어사전이 있는 언어인가. 없으면 LLM 만으로 번역한다 (위 머리말 참고).
    glossary_supported: bool = False


SUPPORTED_LANGUAGES = (
    Language(code="ko", label="Korean", korean_label="한국어", glossary_supported=True),
    Language(code="en", label="English", korean_label="영어", glossary_supported=True),
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
    """`GET /languages` 응답용 — 화면이 선택지를 하드코딩하지 않게 한다.

    `glossary_supported` 를 함께 낸다. 화면이 "용어사전 적용" 배지를 이 값으로 그리면
    실행부와 같은 표를 보게 된다 — 프론트가 언어 목록을 따로 들고 있으면 언어를 늘릴 때
    한쪽만 고치게 되고, 그 상태는 오류가 아니라 **잘못된 안내**로만 드러난다.
    """
    return [
        {
            "code": language.code,
            "label": language.korean_label,
            "en_label": language.label,
            "glossary_supported": language.glossary_supported,
        }
        for language in SUPPORTED_LANGUAGES
    ]


def glossary_languages() -> list:
    """용어사전이 적용되는 언어 코드 목록 (`["ko", "en"]`)."""
    return [language.code for language in SUPPORTED_LANGUAGES if language.glossary_supported]


def glossary_applies(source_code: str, target_code: str) -> bool:
    """이 번역 방향에 용어사전을 쓸 것인가.

    쌍으로 판정하는 이유와 원문 미감지를 막지 않는 이유는 이 파일 머리말에 있다.
    **코드는 이미 해석된 값**(`TranslationOptions.source_code`/`target_code`)을 받는다 —
    별칭 해석을 여기서 또 하면 같은 요청 안에서 판정이 갈릴 수 있다.
    """
    target = _BY_CODE.get((target_code or "").strip().lower())
    if target is None or not target.glossary_supported:
        return False
    source = _BY_CODE.get((source_code or "").strip().lower())
    if source is None:
        return True      # 감지 실패 — 조회는 빈손으로 끝난다. 막을 이유가 없다.
    return source.glossary_supported


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
        # 감지 불가(숫자·기호뿐인 문서)일 때.
        #
        # **대상이 한국어면 통과**시킨다 — 축이 이미 성립하므로 원문이 무엇이든 규칙을
        # 어기지 않는다. 표만 있는 문서를 "언어를 못 알아봤다" 는 이유로 막지 않는다.
        #
        # **대상이 한국어가 아니면 거부한다** (2026-08-14). 이때는 원문이 한국어라는 것을
        # 아무도 확인해 주지 않아 **한국어 축을 증명할 수 없다** — 그대로 두면 사실상
        # `en→ru` 를 허용하는 뒷문이 된다(검증 대상 밖 경로가 조용히 쓰인다).
        # 화면은 원문 언어도 선택지로 갖고 있으므로 명시하면 그만이고, 안내문이 그것을
        # 요구한다. 감지에 실패한 사실을 사용자에게 떠넘기지 않는다.
        if target.code != KOREAN:
            raise LanguageNotSupported(
                "원문 언어를 선택해 주세요. 문서에서 언어를 알아내지 못했고, "
                "한국어가 아닌 언어로 번역하려면 원문이 한국어인지 확인되어야 합니다."
            )
        return None, target

    if source.code == target.code:
        raise LanguageNotSupported("원문과 같은 언어로는 번역할 수 없습니다.")
    if KOREAN not in (source.code, target.code):
        raise LanguageNotSupported(
            "한국어가 포함된 번역만 지원합니다. 원문 또는 번역 대상 중 하나는 한국어여야 합니다."
        )
    return source, target
