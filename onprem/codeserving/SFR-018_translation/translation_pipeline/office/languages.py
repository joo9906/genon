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

호출부가 `source_lang` 을 명시해도 **감지는 항상 돌린다** (2026-08-18). 감지는 폴백이 아니라
**교차검증**이다 — 자세한 근거는 `resolve_direction` 머리말.

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
  응답(`source_lang`, `source_lang_detected`, `source_lang_mismatch`)에 실어 호출부가
  확인할 수 있게 한다. **거부는 최빈값이 아니라 "선언한 언어가 문서에 사실상 없다"
  (10% 미만)로 판정하므로** 이 한계가 정당한 요청을 막지는 않는다 — 한자가 섞인
  한국어 문서에도 한글은 남아 있다.
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


# 선언한 원문 언어가 문서에 **사실상 없다** 고 볼 문자 비율 (2026-08-18).
#
# 감지 결과를 선언값과 대조해 **거부의 근거로 쓰기** 때문에 문턱이 필요하다. 처음에는
# "감지 언어가 표본의 60% 를 넘으면 확실" 로 뒀는데, 그러면
# `본 사업 KPI 는 ROI, TCO, SLA 로 관리한다` 같은 **멀쩡한 한국어 문장이 거부됐다**
# (라틴 문자가 62%). 그건 우회할 방법이 없는 오차단이다.
#
# 그래서 최빈값이 아니라 **선언한 언어의 문자가 표본에 있는가**를 본다. 이게 실제로
# 물어야 할 질문이다 — §6 이 요구하는 것은 "한국어가 한쪽에 있는가" 이고, 영어 문서에
# 한글은 0% 인 반면 영문 용어가 많은 한국어 문서도 한글은 20% 밑으로 잘 안 내려간다.
_ABSENT_SHARE = 0.10


def script_shares(text: str, *, sample_chars: int = 4000) -> dict:
    """`{언어 코드: 표본 내 문자 비율}`. 판정된 글자가 없으면 빈 dict.

    분모는 **스크립트로 판정된 글자**다 — 숫자·공백·문장부호는 넣지 않는다(어느 언어에도
    속하지 않아 모든 비율을 일률적으로 떨어뜨린다).

    베트남어는 라틴 문자 위에 얹히므로 성조 부호가 하나라도 있으면 라틴 표를 베트남어로
    본다 ('en' 과 'vi' 가 같은 글자를 공유해 단순 최빈값으로는 갈리지 않는다).
    """
    counts: dict = {}
    for char in (text or "")[:sample_chars]:
        script = _script_of(char)
        if script:
            counts[script] = counts.get(script, 0) + 1
    if not counts:
        return {}
    if counts.get("vi"):
        counts["vi"] = counts.pop("vi") + counts.pop("en", 0)
    total = sum(counts.values())
    return {code: count / total for code, count in counts.items()}


def detect_detail(text: str, *, sample_chars: int = 4000) -> tuple:
    """`(최빈 언어 코드, 그 비율)`. 판정 불가면 `("", 0.0)`."""
    shares = script_shares(text, sample_chars=sample_chars)
    if not shares:
        return "", 0.0
    return max(shares.items(), key=lambda item: item[1])


def detect(text: str, *, sample_chars: int = 4000) -> str:
    """가장 많이 등장한 스크립트의 언어 코드. 판정 불가면 빈 문자열.

    긴 문서 전체를 세지 않고 앞부분 표본만 본다 — 언어는 문서 안에서 바뀌지 않고,
    수십만 자를 세는 비용이 판정 정확도를 올려주지 않는다.
    """
    return detect_detail(text, sample_chars=sample_chars)[0]


@dataclass(frozen=True)
class DirectionVerdict:
    """방향 판정 결과 — **무엇으로 정했는지까지** 담는다.

    예전에는 `(source, target)` 튜플이었다. 그러면 "원문 언어를 어디서 얻었나"
    (사용자 선언인가 감지인가, 둘이 어긋나지는 않았나)가 경계를 넘지 못한다 —
    호출부는 결과만 보고 그 사실을 복원할 수 없다.
    """

    source: object          # Language | None (감지 불가 + 대상이 한국어)
    target: object          # Language
    detected: str = ""      # 문서에서 감지한 최빈 언어 ("" = 판정 불가)
    declared: bool = False  # 호출부가 원문 언어를 명시했는가
    mismatch: bool = False  # 선언과 감지가 다른가 (사실 보고 — 거부 여부와 별개)
    declared_share: float = 0.0  # 선언한 언어의 문자가 표본에서 차지하는 몫


def resolve_direction(target_lang: str, source_lang: str, sample_text: str) -> "DirectionVerdict":
    """원문·대상을 정하고 한국어 축을 검증한다 (요구사항 §6).

    ## 감지는 폴백이 아니라 **교차검증**이다 (2026-08-18 변경)

    그전에는 `source_lang` 이 오면 감지를 **아예 건너뛰었다.** 그래서 사용자가
    "한국어 → 러시아어" 를 고르고 **영어 문서**를 올리면 실제 방향은 `en→ru` 인데
    선언을 믿어 그대로 통과했다 — §6 이 막으려던 바로 그 쌍이고, 검증 대상 밖 경로가
    조용히 쓰인다. 원문 언어는 화면에서 고르는 값이라 틀리게 고를 수 있고, 그 실수를
    잡아낼 수단이 감지뿐이다.

    이제 **항상 감지한다.** 다만 정본은 여전히 선언값이다 — 감지가 사용자의 선택을
    조용히 덮으면 이 파일이 없애려는 바로 그 실패 형태가 된다(`fell_back`·
    `tone_overridden` 과 같은 취지). 감지는 **거부의 근거**로만 쓰고, 그것도 두 조건이
    함께 설 때만 쓴다:

    1. **선언한 언어가 문서에 사실상 없다** (`declared_share < 10%`). 최빈값으로
       판정하지 않는다 — `본 사업 KPI 는 ROI, TCO, SLA 로 관리한다` 는 라틴 문자가
       62% 라 최빈값으로는 영어가 되지만, **한국어 문서가 맞다.**
    2. **그 결과 §6 이 깨진다** (감지 언어·대상 어느 쪽에도 한국어가 없다).

    | 선언 | 문서 | 대상 | 결과 |
    |---|---|---|---|
    | ko | 영어(한글 0%) | ru | **거부** — 실제로는 `en→ru` 다 |
    | th | 한국어(태국 문자 0%) | ko | 통과 — 대상이 한국어라 축이 성립 (`mismatch=True`) |
    | ko | 한국어+영문용어(한글 33%) | ru | 통과 — 선언한 언어가 문서에 있다 |
    | ko | 한국어 | ru | 통과 (충돌 없음) |

    선언과 대상이 **같은 언어**인 경우(`ko`→`ko`)는 문서가 무엇이든 그 전에 거부된다 —
    충돌 판정까지 가지 않는다.

    Args:
        target_lang: 사용자가 고른 대상 언어 (필수).
        source_lang: 사용자가 고른 원문 언어. 비어 있으면 감지값을 쓴다.
        sample_text: 감지용 표본 (번역 대상 본문 앞부분).

    Returns:
        DirectionVerdict. `source` 는 감지 실패 + 대상이 한국어일 때만 None 이다.

    Raises:
        LanguageNotSupported: 지원 밖 언어, 같은 언어 쌍, 한국어 축 없음,
            또는 **선언과 문서가 달라 축이 깨지는 경우**.
    """
    target = resolve(target_lang)

    declared = resolve(source_lang) if (source_lang or "").strip() else None
    shares = script_shares(sample_text)
    detected_code = max(shares.items(), key=lambda item: item[1])[0] if shares else ""
    declared_share = shares.get(declared.code, 0.0) if declared else 0.0

    source = declared or (_BY_CODE[detected_code] if detected_code else None)
    mismatch = bool(declared and detected_code and declared.code != detected_code)

    if source is None:
        # 감지 불가(숫자·기호뿐인 문서)이고 선언도 없을 때.
        #
        # **대상이 한국어면 통과**시킨다 — 축이 이미 성립하므로 원문이 무엇이든 규칙을
        # 어기지 않는다. 표만 있는 문서를 "언어를 못 알아봤다" 는 이유로 막지 않는다.
        #
        # **대상이 한국어가 아니면 거부한다** (2026-08-14). 이때는 원문이 한국어라는 것을
        # 아무도 확인해 주지 않아 **한국어 축을 증명할 수 없다** — 그대로 두면 사실상
        # `en→ru` 를 허용하는 뒷문이 된다(검증 대상 밖 경로가 조용히 쓰인다).
        # 화면은 원문 언어도 선택지로 갖고 있으므로 명시하면 그만이다.
        if target.code != KOREAN:
            raise LanguageNotSupported(
                "원문 언어를 선택해 주세요. 문서에서 언어를 알아내지 못했고, "
                "한국어가 아닌 언어로 번역하려면 원문이 한국어인지 확인되어야 합니다."
            )
        return DirectionVerdict(None, target, detected_code, bool(declared), mismatch, declared_share)

    if source.code == target.code:
        raise LanguageNotSupported("원문과 같은 언어로는 번역할 수 없습니다.")
    if KOREAN not in (source.code, target.code):
        raise LanguageNotSupported(
            "한국어가 포함된 번역만 지원합니다. 원문 또는 번역 대상 중 하나는 한국어여야 합니다."
        )

    # 교차검증 — 선언만 보면 통과하는데 **문서 기준으로는 축이 없다.**
    # 값(문서 원문)은 담지 않는다. 감지된 언어 이름만 밝힌다 (3.8절).
    if (mismatch and declared_share < _ABSENT_SHARE
            and KOREAN not in (detected_code, target.code)):
        raise LanguageNotSupported(
            f"선택하신 원문 언어와 문서의 언어가 다릅니다. 문서는 "
            f"{_BY_CODE[detected_code].korean_label}로 보이며, 한국어가 포함된 번역만 "
            "지원합니다. 원문 언어를 확인해 주세요."
        )

    return DirectionVerdict(source, target, detected_code, bool(declared), mismatch, declared_share)
