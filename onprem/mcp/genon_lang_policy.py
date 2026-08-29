# =====================================================================================
# genon_lang_policy — 언어·문체·톤 정책 MCP 도구 (area 01)
#
# **이 파일 하나가 등록 단위다.** GenOS MCP 는 소스 파일 한 개를 받아 실행하며,
# `mcp` 객체를 런타임이 전역으로 주입한다. 그래서 패키지로 쪼갤 수 없다.
#
# **모든 최상위 심볼에 `LP` 접두어를 붙였다.** 한 서버에 다른 도구 파일이 함께 로드될 수
# 있어서다 — `ToolError`·`HANDLERS` 같은 흔한 이름을 그대로 두면 나중에 로드된 쪽이
# 앞엣것을 덮어쓰고, 그 실패는 "도구가 이상한 결과를 낸다" 로만 드러난다.
#
# LLM 을 부르지 않는다. 여기 있는 판정은 **거부 판정**(지원하지 않는 번역 방향)과
# **정책 강제**(문서유형이 톤을 덮어쓰는 경우)라서, 모델에 맡기면 같은 입력에 다른 답이
# 나온다. 스크립트 기반으로 결정적으로 판정한다.
#
# **설치가 필요한 패키지를 쓰지 않는다.** stdlib 만으로 돈다 — 그래서 부팅 시 설치 절차가
# 없다. `pydantic` 하나를 **선택적으로**(try/except) 가져다 쓰는데, MCP 런타임(FastMCP)이
# 도구 스키마를 만들 때 이미 쓰는 패키지라 따로 설치할 것이 아니고, 없으면 선택지 없이
# 그냥 돈다 (아래 "선택지를 도구 스키마에 싣는다" 절).
# =====================================================================================

import json
import logging
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Annotated

# ── languages.py ─────────────────────────────
LPKOREAN = "ko"


# ── 로깅 ───────────────────────────────────────────
# **`print()` 를 쓰지 않는다** (GENOS_RULES §C, 가이드 3.10). MCP 는 stdout 이 전송 채널이
# 될 수 있고(stdio 방식), 그러면 로그 한 줄이 프로토콜을 깨뜨린다 — `eval/` 이 stderr 전용
# 로깅을 쓰는 이유와 같다. 값(문서 원문·경로·시크릿)은 메시지에 넣지 않고 예외 **타입**만
# 남긴다(3.8절).
_LPlog = logging.getLogger("genon_lang_policy")


def _LPsetup_logging() -> None:
    """이 파일 전용 **stderr** 핸들러를 붙인다 (2026-08-14).

    두 가지를 동시에 지키려는 것이다:

    - **`print()` 를 쓰지 않는다** (GENOS_RULES §C). MCP 는 stdout 이 전송 채널이 될 수
      있고(stdio 방식), 그러면 로그 한 줄이 프로토콜을 깨뜨린다 — `eval/` 이 stderr 전용
      로깅을 쓰는 이유와 같다.
    - **그렇다고 조용해지지도 않는다.** 로깅 설정이 없는 프로세스에서 `logger.info` 는
      **아무 데도 안 나온다**(기본 최후 핸들러가 WARNING 부터다). 그냥 logger 로 바꾸기만
      하면 부팅·적재 메시지가 소리 없이 사라진다 — 그건 print 보다 나쁘다.

    핸들러가 이미 있으면 아무것도 하지 않는다(런타임이 설정했다면 그쪽을 존중한다).
    """
    if _LPlog.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    _LPlog.addHandler(handler)
    _LPlog.setLevel(logging.INFO)
    # 루트로 올리지 않는다 — 루트에 stdout 핸들러가 붙어 있으면 그리로 새어 나간다.
    _LPlog.propagate = False


_LPsetup_logging()


@dataclass(frozen=True)
class LPLanguage:
    code: str
    label: str          # 프롬프트에 넣는 이름 (영문 — LLM 지시문이 영어다)
    korean_label: str   # 사용자 노출용
    # 사내 용어사전이 있는 언어인가 (2026-08-14 요구 확정 — 한국어·영어만).
    # 나머지 넷은 LLM 만으로 번역한다. **번역 단위 `languages.py` 와 같은 표여야 한다** —
    # 갈리면 화면 안내(이쪽)와 실제 적용(그쪽)이 다르고, 준수율은 늘 1.0 이라 정상처럼 보인다.
    glossary_supported: bool = False


LPSUPPORTED_LANGUAGES = (
    LPLanguage(code="ko", label="Korean", korean_label="한국어", glossary_supported=True),
    LPLanguage(code="en", label="English", korean_label="영어", glossary_supported=True),
    LPLanguage(code="zh", label="Chinese", korean_label="중국어"),
    LPLanguage(code="th", label="Thai", korean_label="태국어"),
    LPLanguage(code="vi", label="Vietnamese", korean_label="베트남어"),
    LPLanguage(code="ru", label="Russian", korean_label="러시아어"),
)

_LPBY_CODE = {language.code: language for language in LPSUPPORTED_LANGUAGES}

# 흔한 별칭 → 코드. 화면·워크플로우 변수가 어떤 표기로 오든 한 곳에서 흡수한다.
_LPlanguages_ALIASES = {
    "korean": "ko", "kor": "ko", "ko-kr": "ko", "한국어": "ko", "국문": "ko",
    "english": "en", "eng": "en", "en-us": "en", "영어": "en", "영문": "en",
    "chinese": "zh", "zh-cn": "zh", "zh-hans": "zh", "cn": "zh", "중국어": "zh",
    "thai": "th", "th-th": "th", "태국어": "th",
    "vietnamese": "vi", "vi-vn": "vi", "베트남어": "vi",
    "russian": "ru", "ru-ru": "ru", "러시아어": "ru", "노어": "ru",
}


class LPLanguageNotSupported(ValueError):
    """지원하지 않는 언어 코드/번역 방향.

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다
    (main.py 가 그대로 API 응답 msg 로 쓴다).
    """


def lplanguages_supported_payload() -> list:
    """`GET /languages` 응답용 — 화면이 선택지를 하드코딩하지 않게 한다."""
    return [
        {
            "code": language.code,
            "label": language.korean_label,
            "en_label": language.label,
            "glossary_supported": language.glossary_supported,
        }
        for language in LPSUPPORTED_LANGUAGES
    ]


def lpglossary_languages() -> list:
    """용어사전이 적용되는 언어 코드 목록 (`["ko", "en"]`)."""
    return [language.code for language in LPSUPPORTED_LANGUAGES if language.glossary_supported]


def lpglossary_applies(source_code: str, target_code: str) -> bool:
    """이 번역 방향에 용어사전을 쓸 것인가 — 번역 단위 `languages.glossary_applies` 사본.

    대상만 보면 `ru→ko` 가 통과하는데 색인은 영어 원문 용어를 들고 있어 러시아어 본문에
    맞을 리가 없다. 원문 미감지는 막지 않는다(조회가 빈손으로 끝날 뿐이다).
    """
    target = _LPBY_CODE.get((target_code or "").strip().lower())
    if target is None or not target.glossary_supported:
        return False
    source = _LPBY_CODE.get((source_code or "").strip().lower())
    if source is None:
        return True
    return source.glossary_supported


def lpresolve(code: str) -> LPLanguage:
    """언어 코드/별칭을 Language 로 바꾼다.

    Raises:
        LanguageNotSupported: 지원 목록에 없음.
    """
    normalized = (code or "").strip().lower().replace("_", "-")
    normalized = _LPlanguages_ALIASES.get(normalized, normalized)
    language = _LPBY_CODE.get(normalized)
    if language is None:
        raise LPLanguageNotSupported(
            "지원하지 않는 언어입니다. 한국어·영어·중국어·태국어·베트남어·러시아어 중에서 골라 주세요."
        )
    return language


# ── 스크립트 기반 감지 ────────────────────────────────────────

# 베트남어를 영어와 가르는 문자. 라틴 확장 성조 부호가 붙은 글자들이다.
# (nfd 정규화 후 결합 부호로 보는 방법도 있지만, 사전 조합 문자가 대부분이라
#  이쪽이 오탐이 적다.)
_LPVIETNAMESE_CHARS = set(
    "ăâđêôơưĂÂĐÊÔƠƯ"
    "áàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩị"
    "óòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
)


def _LPscript_of(char: str) -> str:
    """한 글자가 어느 언어 후보에 속하는지. 판정 불가면 빈 문자열."""
    if char in _LPVIETNAMESE_CHARS:
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
_LPABSENT_SHARE = 0.10


def lpscript_shares(text: str, *, sample_chars: int = 4000) -> dict:
    """`{언어 코드: 표본 내 문자 비율}`. 판정된 글자가 없으면 빈 dict.

    분모는 **스크립트로 판정된 글자**다 — 숫자·공백·문장부호는 넣지 않는다(어느 언어에도
    속하지 않아 모든 비율을 일률적으로 떨어뜨린다).

    베트남어는 라틴 문자 위에 얹히므로 성조 부호가 하나라도 있으면 라틴 표를 베트남어로
    본다 ('en' 과 'vi' 가 같은 글자를 공유해 단순 최빈값으로는 갈리지 않는다).
    """
    counts: dict = {}
    for char in (text or "")[:sample_chars]:
        script = _LPscript_of(char)
        if script:
            counts[script] = counts.get(script, 0) + 1
    if not counts:
        return {}
    if counts.get("vi"):
        counts["vi"] = counts.pop("vi") + counts.pop("en", 0)
    total = sum(counts.values())
    return {code: count / total for code, count in counts.items()}


def lpdetect_detail(text: str, *, sample_chars: int = 4000) -> tuple:
    """`(최빈 언어 코드, 그 비율)`. 판정 불가면 `("", 0.0)`."""
    shares = lpscript_shares(text, sample_chars=sample_chars)
    if not shares:
        return "", 0.0
    return max(shares.items(), key=lambda item: item[1])


def lpdetect(text: str, *, sample_chars: int = 4000) -> str:
    """가장 많이 등장한 스크립트의 언어 코드. 판정 불가면 빈 문자열.

    긴 문서 전체를 세지 않고 앞부분 표본만 본다 — 언어는 문서 안에서 바뀌지 않고,
    수십만 자를 세는 비용이 판정 정확도를 올려주지 않는다.
    """
    return lpdetect_detail(text, sample_chars=sample_chars)[0]


@dataclass(frozen=True)
class LPDirectionVerdict:
    """방향 판정 결과 — **무엇으로 정했는지까지** 담는다.

    예전에는 `(source, target)` 튜플이었다. 그러면 "원문 언어를 어디서 얻었나"
    (사용자 선언인가 감지인가, 둘이 어긋나지는 않았나)가 경계를 넘지 못한다 —
    호출부는 결과만 보고 그 사실을 복원할 수 없다.
    """

    source: object          # LPLanguage | None (감지 불가 + 대상이 한국어)
    target: object          # LPLanguage
    detected: str = ""      # 문서에서 감지한 최빈 언어 ("" = 판정 불가)
    declared: bool = False  # 호출부가 원문 언어를 명시했는가
    mismatch: bool = False  # 선언과 감지가 다른가 (사실 보고 — 거부 여부와 별개)
    declared_share: float = 0.0  # 선언한 언어의 문자가 표본에서 차지하는 몫


def lpresolve_direction(target_lang: str, source_lang: str, sample_text: str) -> "LPDirectionVerdict":
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
        LPDirectionVerdict. `source` 는 감지 실패 + 대상이 한국어일 때만 None 이다.

    Raises:
        LPLanguageNotSupported: 지원 밖 언어, 같은 언어 쌍, 한국어 축 없음,
            또는 **선언과 문서가 달라 축이 깨지는 경우**.
    """
    target = lpresolve(target_lang)

    declared = lpresolve(source_lang) if (source_lang or "").strip() else None
    shares = lpscript_shares(sample_text)
    detected_code = max(shares.items(), key=lambda item: item[1])[0] if shares else ""
    declared_share = shares.get(declared.code, 0.0) if declared else 0.0

    source = declared or (_LPBY_CODE[detected_code] if detected_code else None)
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
        if target.code != LPKOREAN:
            raise LPLanguageNotSupported(
                "원문 언어를 선택해 주세요. 문서에서 언어를 알아내지 못했고, "
                "한국어가 아닌 언어로 번역하려면 원문이 한국어인지 확인되어야 합니다."
            )
        return LPDirectionVerdict(None, target, detected_code, bool(declared), mismatch, declared_share)

    if source.code == target.code:
        raise LPLanguageNotSupported("원문과 같은 언어로는 번역할 수 없습니다.")
    if LPKOREAN not in (source.code, target.code):
        raise LPLanguageNotSupported(
            "한국어가 포함된 번역만 지원합니다. 원문 또는 번역 대상 중 하나는 한국어여야 합니다."
        )

    # 교차검증 — 선언만 보면 통과하는데 **문서 기준으로는 축이 없다.**
    # 값(문서 원문)은 담지 않는다. 감지된 언어 이름만 밝힌다 (3.8절).
    if (mismatch and declared_share < _LPABSENT_SHARE
            and LPKOREAN not in (detected_code, target.code)):
        raise LPLanguageNotSupported(
            f"선택하신 원문 언어와 문서의 언어가 다릅니다. 문서는 "
            f"{_LPBY_CODE[detected_code].korean_label}로 보이며, 한국어가 포함된 번역만 "
            "지원합니다. 원문 언어를 확인해 주세요."
        )

    return LPDirectionVerdict(source, target, detected_code, bool(declared), mismatch, declared_share)


# ── registers.py ─────────────────────────────
LPDEFAULT_REGISTER = "written"


@dataclass(frozen=True)
class LPRegister:
    key: str
    label: str          # 프롬프트용 (영문)
    korean_label: str   # 사용자 노출용
    instruction: str


LPREGISTERS = {
    "written": LPRegister(
        key="written",
        label="Formal written style",
        korean_label="문어체",
        instruction=(
            "Use formal written register suitable for official documents and reports. "
            "Prefer complete sentences, standard terminology and impersonal phrasing. "
            "Avoid contractions, slang and conversational fillers. "
            "When translating into Korean, use the '~하다/~한다' declarative or '~합니다' "
            "formal ending consistently across the whole document."
        ),
    ),
    "spoken": LPRegister(
        key="spoken",
        label="Conversational spoken style",
        korean_label="구어체",
        instruction=(
            "Use natural conversational register suitable for chat, guidance and spoken delivery. "
            "Prefer short sentences and everyday wording, while staying polite and professional. "
            "When translating into Korean, use the '~해요/~예요' polite conversational ending "
            "consistently across the whole document."
        ),
    ),
}

# 화면·워크플로우 변수 표기 흡수 (언어 별칭과 같은 이유 — 표기 정규화는 한 곳에서)
_LPregisters_ALIASES = {
    "문어체": "written", "formal": "written", "document": "written", "written": "written",
    "구어체": "spoken", "casual": "spoken", "conversational": "spoken", "spoken": "spoken",
}


def lpresolve_register(value: str) -> tuple:
    """(Register, fell_back) 을 돌려준다.

    fell_back 이 True 면 알 수 없는 값이 와서 기본값을 쓴 것이다. 호출부는 이 사실을
    응답·로그에 노출한다 (사용자가 고른 문체가 조용히 무시되지 않게).
    """
    normalized = (value or "").strip().lower()
    if not normalized:
        return LPREGISTERS[LPDEFAULT_REGISTER], False
    key = _LPregisters_ALIASES.get(normalized)
    if key is None:
        return LPREGISTERS[LPDEFAULT_REGISTER], True
    return LPREGISTERS[key], False


def lpregisters_supported_payload() -> list:
    """`GET /languages` 응답에 함께 실어 화면이 선택지를 하드코딩하지 않게 한다.

    **식별자 필드는 `code` 다** (2026-08-14 통일). 예전에는 이 목록만 `key` 였다 —
    같은 응답 안의 언어 목록은 `code` 이고 글다듬이 `/policies` 의 문서유형·톤도
    `code` 라서, 프론트가 드롭다운을 그릴 때 **목록마다 다른 키를 읽어야** 했다.
    선택지 목록은 전부 `{code, label}` 한 모양으로 맞춘다.
    """
    return [
        {"code": register.key, "label": register.korean_label}
        for register in LPREGISTERS.values()
    ]


# ── tone_presets.py ─────────────────────────────
# ── 톤 정의 ───────────────────────────────────────────────

LPDEFAULT_TONE = "polite"


@dataclass(frozen=True)
class LPTonePreset:
    label: str
    instruction: str


LPTONE_PRESETS: dict[str, LPTonePreset] = {
    "polite": LPTonePreset(
        label="정중함",
        instruction=(
            "격식 있는 존댓말('~습니다/~합니다')로 다듬는다. "
            "명령형·반말·구어체 표현을 정중한 문어체로 바꾸고, "
            "상대를 존중하는 완곡한 표현을 사용한다."
        ),
    ),
    "friendly": LPTonePreset(
        label="친절함",
        instruction=(
            "부드럽고 친근한 존댓말로 다듬는다. 딱딱한 한자어와 관공서식 표현은 "
            "쉬운 일상어로 풀어 쓰되 정보 누락은 없어야 한다. "
            "안내·권유 표현('~해 주시면 됩니다', '~하실 수 있습니다')을 활용한다."
        ),
    ),
    "report": LPTonePreset(
        label="간결 및 보고체",
        instruction=(
            "간결한 보고체('~함', '~임', '~됨' 개조식 종결)로 다듬는다. "
            "중복 수식어와 부연 설명을 제거하고 핵심 정보 위주로 압축하되, "
            "수치·날짜·고유명사 등 사실 정보는 절대 생략하지 않는다."
        ),
    ),
}


def lpis_valid_tone(value: str | None) -> bool:
    return bool(value) and value in LPTONE_PRESETS


# ── 문서유형 정책 ─────────────────────────────────────────


@dataclass(frozen=True)
class LPDocTypePolicy:
    label: str
    # forced_tone이 있으면 톤 고정 — 사용자가 다른 톤을 요청해도 이 톤으로 강제
    forced_tone: str | None = None
    # forced_tone 이 없을 때 사용자가 고를 수 있는 톤. **빈 튜플이면 제한 없음**이다
    # (2026-08-18). 예전 기본값은 내장 3종을 적어 둔 닫힌 목록이었는데, 관리자가
    # 프롬프트 라이브러리에 톤을 추가해도 **자유 선택군에서 못 고르는** 상태가 됐다 —
    # 화면 목록에는 뜨는데 고르면 기본 톤으로 되돌아간다(오류 없이).
    allowed_tones: tuple[str, ...] = ()
    # 문서유형별 추가 지시문 (선택)
    extra_instruction: str = ""


LPDEFAULT_DOC_TYPE = "email"

# forced_tone 값은 관리자가 운영 정책에 맞게 조정하는 부분이다.
# (아래는 초안 기본값 — 실제 강제 톤은 관리자 확정 후 매니페스트/환경설정에서 주입)
LPDOC_TYPE_POLICIES: dict[str, LPDocTypePolicy] = {
    # ── 자유 선택군 ──
    "email": LPDocTypePolicy(
        label="메일",
        extra_instruction="수신자에게 보내는 이메일 형식(인사-본문-맺음말 흐름)을 유지한다.",
    ),
    "post": LPDocTypePolicy(
        label="게시글",
        extra_instruction="사내/대외 게시글로 읽기 쉽도록 문단 구분을 유지한다.",
    ),
    "press_release": LPDocTypePolicy(
        label="보도자료",
        extra_instruction="보도자료 관례(핵심 사실 우선, 객관적 서술)를 따른다.",
    ),
    "official_doc": LPDocTypePolicy(
        label="공문",
        extra_instruction="공문서 형식(항목 번호, 붙임 표기 등 구조)을 훼손하지 않는다.",
    ),
    # ── 톤 고정군 (관리자 지정 톤만 사용) ──
    "debt_reason": LPDocTypePolicy(
        label="채무 및 연체발생 사유",
        forced_tone="report",
        extra_instruction="사실관계 중심으로 서술하고 주관적 평가·추측 표현을 제거한다.",
    ),
    "reviewer_opinion": LPDocTypePolicy(
        label="심사역 의견",
        forced_tone="report",
        extra_instruction="심사 판단 근거가 드러나도록 논리 순서를 유지한다.",
    ),
    "asset_opinion": LPDocTypePolicy(
        label="재산 의견",
        forced_tone="report",
        extra_instruction="금액·자산 내역 등 수치는 원문 그대로 유지한다.",
    ),
    "customer_notice": LPDocTypePolicy(
        label="고객발송문구",
        forced_tone="polite",
        extra_instruction="법적 고지 문구·필수 안내 항목은 임의로 삭제하거나 완화하지 않는다.",
    ),
}


# ── 관리자 정책 — GenOS 프롬프트 라이브러리 (2026-08-18) ──────────────
#
# 위 표는 **기본값**이고, 관리자가 `도구 > 프롬프트 라이브러리` 에 등록한 톤·문서유형이
# 그 위에 얹힌다 (가이드 §10.5). **글다듬이 코드서빙 `policy_store.py` 와 같은 판정이어야
# 한다** — 화면 드롭다운은 그쪽이 그리고 강제 톤 판정은 이쪽이 하므로, 갈리면 사용자가
# 화면에서 고른 톤을 워크플로우가 "알 수 없는 톤" 으로 되돌린다. 오류는 안 난다.
# `check_tone_policy.py` 가 두 벌을 대조한다.
#
# **`httpx` 를 쓸 수 없다.** MCP 파일은 `requirements.txt` 가 없다 — `urllib` 로 짠다
# (`genon_glossary` 와 같은 이유).
#
# **기동 훅이 없으므로 첫 도구 호출에서 받는다.** import 에서 받으면 admin-api 가 느릴 때
# 등록이 왜 안 되는지 드러나지 않는다.
_LPPOLICY_TTL_SECONDS = 60.0
_LPPOLICY_FETCH_TIMEOUT = 5.0
_LPMAX_CODE_CHARS = 40
_LPMAX_LABEL_CHARS = 40
_LPMAX_INSTRUCTION_CHARS = 2000
_LPMAX_POLICY_ITEMS = 50

_LPPOLICY_CACHE: dict = {}
_LPPOLICY_AT: float = 0.0


def _LPempty_policy(reason: str) -> dict:
    return {"tones": {}, "doc_types": {}, "source": "builtin", "reason": reason, "rejected": {}}


def _LPclean(value, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def lpparse_policy_document(raw: str) -> dict:
    """프롬프트 본문(JSON)을 검증된 정책 dict 로. **예외를 던지지 않는다.**

    관리자가 JSON 을 잘못 쓰는 것은 흔하고, 그때 톤 판정이 통째로 멈추면 안 된다 —
    내장 기본값으로 돌면서 사유를 남긴다. 불량 항목은 **사유별 건수**만 센다 (3.8절).
    """
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return _LPempty_policy("invalid_json")
    if not isinstance(document, dict):
        return _LPempty_policy("invalid_shape")

    rejected: dict = {}

    def _reject(why: str) -> None:
        rejected[why] = rejected.get(why, 0) + 1

    tones: dict = {}
    for item in (document.get("tones") or [])[:_LPMAX_POLICY_ITEMS]:
        if not isinstance(item, dict):
            _reject("tone_not_object")
            continue
        code = _LPclean(item.get("code"), _LPMAX_CODE_CHARS)
        if not code:
            _reject("tone_code_missing")
            continue
        if item.get("disabled") is True:
            tones[code] = {"disabled": True}
            continue
        instruction = _LPclean(item.get("instruction"), _LPMAX_INSTRUCTION_CHARS)
        if not instruction:
            _reject("tone_instruction_missing")
            continue
        tones[code] = {
            "label": _LPclean(item.get("label"), _LPMAX_LABEL_CHARS) or code,
            "instruction": instruction,
            "disabled": False,
        }

    doc_types: dict = {}
    for item in (document.get("doc_types") or [])[:_LPMAX_POLICY_ITEMS]:
        if not isinstance(item, dict):
            _reject("doc_type_not_object")
            continue
        code = _LPclean(item.get("code"), _LPMAX_CODE_CHARS)
        if not code:
            _reject("doc_type_code_missing")
            continue
        if item.get("disabled") is True:
            doc_types[code] = {"disabled": True}
            continue
        allowed = item.get("allowed_tones")
        doc_types[code] = {
            "label": _LPclean(item.get("label"), _LPMAX_LABEL_CHARS) or code,
            "extra_instruction": _LPclean(item.get("extra_instruction"), _LPMAX_INSTRUCTION_CHARS),
            "forced_tone": _LPclean(item.get("forced_tone"), _LPMAX_CODE_CHARS),
            "allowed_tones": tuple(
                _LPclean(t, _LPMAX_CODE_CHARS) for t in allowed if _LPclean(t, _LPMAX_CODE_CHARS)
            ) if isinstance(allowed, list) else (),
            "disabled": False,
        }

    return {
        "tones": tones,
        "doc_types": doc_types,
        "source": "prompt_library",
        "reason": "ok",
        "rejected": rejected,
    }


def _LPfetch_policy() -> dict:
    base = os.environ.get("GENOS_ADMIN_API_URL", "").strip().rstrip("/")
    prompt_id = os.environ.get("LANG_POLICY_PROMPT_ID", "").strip()
    if not (base and prompt_id):
        return _LPempty_policy("not_configured")

    url = f"{base}/prompt/template/{prompt_id}"
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=_LPPOLICY_FETCH_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 상태코드만 남긴다 (3.8절). 404 는 ID 오기입, 5xx 는 admin-api 장애 —
        # 관리자가 할 일이 다르다.
        return _LPempty_policy(f"fetch_failed_{exc.code}")
    except Exception:  # noqa: BLE001 - 연결 실패·타임아웃·JSON 파싱까지
        return _LPempty_policy("fetch_failed")

    # 가이드 §10.5 응답 계약: `{"code": 0, "data": "<본문>"}`
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return _LPempty_policy("api_error")
    body = payload.get("data")
    if not isinstance(body, str) or not body.strip():
        return _LPempty_policy("empty_body")
    return lpparse_policy_document(body)


def lppolicy(*, force: bool = False) -> dict:
    """관리자 정책 (TTL 캐시). 첫 도구 호출에서 받는다."""
    global _LPPOLICY_CACHE, _LPPOLICY_AT
    now = time.monotonic()
    if not force and _LPPOLICY_CACHE and (now - _LPPOLICY_AT) < _LPPOLICY_TTL_SECONDS:
        return _LPPOLICY_CACHE

    result = _LPfetch_policy()
    _LPPOLICY_CACHE, _LPPOLICY_AT = result, now
    if result["source"] == "prompt_library":
        _LPlog.info("관리자 정책 적재", extra={
            "event": "policy_loaded",
            "item_count": len(result["tones"]) + len(result["doc_types"]),
            "status": f"rejected={sum(result['rejected'].values())}",
        })
    elif result["reason"] != "not_configured":
        _LPlog.warning("관리자 정책을 읽지 못해 내장 기본값으로 동작한다",
                       extra={"event": "policy_load_failed", "status": result["reason"]})
    return result


def lpclear_policy_cache() -> None:
    """점검용 — 캐시를 비운다."""
    global _LPPOLICY_CACHE, _LPPOLICY_AT
    _LPPOLICY_CACHE, _LPPOLICY_AT = {}, 0.0


def lpmerged_tones() -> dict:
    """`{code: LPTonePreset}` — 내장 + 관리자. 감춘 항목은 빠진다."""
    merged = dict(LPTONE_PRESETS)
    for code, item in (lppolicy().get("tones") or {}).items():
        if item.get("disabled"):
            merged.pop(code, None)
            continue
        merged[code] = LPTonePreset(label=item["label"], instruction=item["instruction"])
    return merged


def lpmerged_doc_types() -> dict:
    """`{code: LPDocTypePolicy}` — 내장 + 관리자. 감춘 항목은 빠진다."""
    merged = dict(LPDOC_TYPE_POLICIES)
    for code, item in (lppolicy().get("doc_types") or {}).items():
        if item.get("disabled"):
            merged.pop(code, None)
            continue
        base = merged.get(code)
        allowed = item.get("allowed_tones") or (base.allowed_tones if base else ())
        merged[code] = LPDocTypePolicy(
            label=item["label"],
            forced_tone=item.get("forced_tone") or None,
            allowed_tones=tuple(allowed),
            extra_instruction=item.get("extra_instruction", ""),
        )
    return merged


def lpnormalize_doc_type(value: str | None) -> str:
    """문서유형 코드를 확정한다. **관리자가 추가한 유형도 인정한다.**"""
    doc_types = lpmerged_doc_types()
    key = (value or LPDEFAULT_DOC_TYPE).strip()
    if key in doc_types:
        return key
    return LPDEFAULT_DOC_TYPE if LPDEFAULT_DOC_TYPE in doc_types else next(iter(doc_types))


def _LPtone_allowed(tone: str, policy: LPDocTypePolicy) -> bool:
    """이 문서유형에서 그 톤을 고를 수 있는가. **빈 목록은 제한 없음**이다."""
    return not policy.allowed_tones or tone in policy.allowed_tones


def lpresolve_tone(doc_type_raw: str | None, tone_raw: str | None) -> tuple[str, str, bool]:
    """문서유형 정책에 따라 실제 적용할 톤을 결정한다.

    Returns:
        (doc_type_key, tone_key, tone_overridden)
        tone_overridden: 사용자가 요청한 톤이 정책에 의해 다른 톤으로 대체됐는지 여부.
                         True면 응답에 안내 문구를 붙여 사용자에게 알린다.
    """
    tones = lpmerged_tones()
    doc_type = lpnormalize_doc_type(doc_type_raw)
    policy = lpmerged_doc_types()[doc_type]
    requested = (tone_raw or "").strip()
    valid = bool(requested) and requested in tones

    if policy.forced_tone and policy.forced_tone in tones:
        overridden = valid and requested != policy.forced_tone
        return doc_type, policy.forced_tone, overridden

    if valid and _LPtone_allowed(requested, policy):
        return doc_type, requested, False

    # 미지정/허용 외 톤 → 허용 목록의 첫 톤. **관리자가 지운 톤을 가리킬 수 있으므로**
    # 존재 확인을 거친다 — 없으면 기본 톤, 그것도 없으면 남은 첫 톤이다.
    for candidate in tuple(policy.allowed_tones) + (LPDEFAULT_TONE,) + tuple(tones):
        if candidate in tones:
            return doc_type, candidate, valid
    raise LPToolError("NO_TONE_AVAILABLE")


# ── tools.py ─────────────────────────────
class LPToolError(ValueError):
    def __init__(self, error_type: str):
        super().__init__(error_type)
        self.error_type = error_type


# 감지 표본 상한. 문자 체계 판정에 문서 전체가 필요하지 않고, 게이트웨이로 문서 원문을
# 통째로 흘리는 것도 피한다 (3.8절 취지).
_LPMAX_SAMPLE_CHARS = 8000


def _LPtext_arg(arguments: dict, name: str, *, required: bool = True) -> str:
    value = arguments.get(name)
    if value is None:
        if required:
            raise LPToolError(f"MISSING_ARG_{name.upper()}")
        return ""
    if not isinstance(value, str):
        raise LPToolError(f"INVALID_TYPE_{name.upper()}")
    return value


def _LPdetect_language(arguments: dict) -> dict:
    sample = _LPtext_arg(arguments, "sample")[:_LPMAX_SAMPLE_CHARS]
    code, ratio = lpdetect_detail(sample)
    return {
        "ok": True,
        "lang": code or "",
        "detected": bool(code),
        # 최빈 언어가 표본에서 차지하는 몫. 낮으면 여러 문자 체계가 섞인 문서다 —
        # `validate_direction` 이 이 값들로 선언값을 교차검증하므로 함께 낸다.
        "ratio": round(ratio, 3),
    }


def _LPvalidate_direction(arguments: dict) -> dict:
    """번역 방향이 한국어 축을 지나는지 검증한다 (요구사항 §6).

    **거부는 오류가 아니라 판정 결과다.** `allowed=false` 로 내려야 워크플로우가
    "재시도 무의미" 로 다루고 사용자에게 고정 안내문을 보여줄 수 있다.
    """
    sample = _LPtext_arg(arguments, "sample")[:_LPMAX_SAMPLE_CHARS]
    target_lang = _LPtext_arg(arguments, "target_lang")
    source_lang = _LPtext_arg(arguments, "source_lang", required=False)

    try:
        verdict = lpresolve_direction(target_lang, source_lang, sample)
    except LPLanguageNotSupported as exc:
        # 메시지는 이 파일 안에서 작성한 고정 한국어 안내문이다 (3.8절 계약).
        return {
            "ok": True,
            "allowed": False,
            "reason": str(exc),
            "source_lang": "",
            "target_lang": target_lang,
            "detected": False,
        }

    source = verdict.source
    return {
        "ok": True,
        "allowed": True,
        "reason": "",
        "source_lang": source.code if source else "",
        "target_lang": verdict.target.code,
        # 감지 불가인데 여기까지 왔다면 대상이 한국어라는 뜻이다(축이 이미 성립).
        # 대상이 비한국어면 위에서 `allowed=false` 로 갈라졌다.
        "detected": source is not None,
        "korean_axis": LPKOREAN in ((source.code if source else ""), verdict.target.code),
        # **원문 언어를 무엇으로 정했는지** — 사용자 선언인가 감지인가, 둘이 어긋나지는
        # 않았나. 이 셋이 없으면 호출부는 결과만 보고 그 사실을 복원할 수 없다.
        # `source_mismatch=true` 는 **통과한** 충돌이다 (대상이 한국어라 축이 성립하는
        # 경우). 축이 깨지는 충돌은 위에서 `allowed=false` 로 갈라진다.
        "source_declared": verdict.declared,
        "detected_lang": verdict.detected,
        "source_mismatch": verdict.mismatch,
        "declared_share": round(verdict.declared_share, 3),
        # 이 방향에 용어사전이 붙는가. 거부 판정이 아니라 **안내**다 — 워크플로우가
        # 로그·응답에 실어 "왜 이 언어만 용어가 안 지켜지나" 를 답할 수 있게 한다.
        "glossary_applies": lpglossary_applies(source.code if source else "", verdict.target.code),
    }


def _LPlist_languages(_arguments: dict) -> dict:
    return {
        "ok": True,
        "languages": list(lplanguages_supported_payload()),
        "glossary_languages": lpglossary_languages(),
    }


def _LPlist_registers(_arguments: dict) -> dict:
    return {"ok": True, "registers": list(lpregisters_supported_payload())}


def _LPresolve_register(arguments: dict) -> dict:
    """문체 값을 정규화하고 **기본값으로 떨어졌는지**를 함께 낸다.

    2026-08-11 에 두 가지를 고쳤다. 둘 다 단일 파일로 합치며 실제 응답을 찍어 보고 나서야
    드러났다 — 이 도구가 HTTP 계약 점검에 걸리지 않는 자리에 있었다:

    1. **`getattr(code, "code", str(code))` 가 항상 `str(code)` 로 떨어졌다.**
       `LPRegister` 의 필드는 `key` 이고 `code` 는 없다. 그래서 응답에 파이썬 repr 이
       통째로 실렸다 — 영문 지시문까지 포함해서. 호출부가 쓸 수 있는 값이 아니었고,
       내부 문자열이 그대로 새는 것이기도 하다 (3.8절).
    2. **`fell_back` 을 계산해 놓고 버렸다.** `lpresolve_register` 가 튜플 둘째로
       "알 수 없는 값이 와서 기본값을 썼다" 를 알려주는데 응답에 싣지 않았다.
       그러면 사용자가 고른 문체가 **조용히 무시된다** — 이 서빙이 없애려는 바로 그
       실패 형태다(`resolve_tone` 의 `tone_overridden` 과 같은 취지).
    """
    value = _LPtext_arg(arguments, "register", required=False)
    resolved = lpresolve_register(value)
    # `lpresolve_register` 는 `(LPRegister, fell_back)` 튜플을 돌려준다. JSON 으로는
    # 이름 붙은 형태여야 호출부가 위치에 의존하지 않는다 (§I).
    if isinstance(resolved, tuple):
        register, fell_back = resolved[0], bool(resolved[1])
    else:
        register, fell_back = resolved, False
    return {
        "ok": True,
        "register": register.key,
        "label": register.korean_label,
        "fell_back": fell_back,
    }


def _LPresolve_tone(arguments: dict) -> dict:
    """문서유형·톤을 확정하고 **정책상 강제되었는지**를 함께 낸다.

    `tone_overridden` 이 워크플로우 분기의 근거다 — 사용자가 고른 톤이 문서유형 정책에
    밀렸다는 사실을 알려주지 않으면, 결과만 보고는 왜 다른 톤이 나왔는지 알 수 없다.
    """
    doc_type_raw = _LPtext_arg(arguments, "doc_type", required=False)
    tone_raw = _LPtext_arg(arguments, "tone", required=False)

    doc_type_key, tone_key, overridden = lpresolve_tone(doc_type_raw, tone_raw)
    # **내장 표가 아니라 병합 표에서 꺼낸다.** 내장 표를 읽으면 관리자가 추가한
    # 문서유형·톤에서만 KeyError 로 죽는다 — 정확히 그 기능을 쓰는 사람에게만 터진다.
    policy = lpmerged_doc_types()[doc_type_key]
    tone = lpmerged_tones()[tone_key]

    notice = ""
    if overridden:
        notice = f"※ '{policy.label}' 문서는 정책상 '{tone.label}' 톤이 적용됩니다."

    return {
        "ok": True,
        "doc_type": doc_type_key,
        "doc_type_label": policy.label,
        "tone": tone_key,
        "tone_label": tone.label,
        "tone_overridden": overridden,
        "notice": notice,
        # 관리자 정책을 읽었는지 — 화면(`GET /policies`)과 이 판정이 같은 표를 보는지
        # 확인할 수 있어야 한다. 조회 실패와 "아직 등록 안 함" 이 둘 다 내장 목록으로
        # 보이면 관리자는 자기가 넣은 톤이 왜 무시되는지 알 수 없다.
        "policy_source": lppolicy().get("source", "builtin"),
        "policy_reason": lppolicy().get("reason", "not_configured"),
    }

# ── 도구 카탈로그는 손으로 적지 않는다 (2026-08-14) ──────────────────
# 예전에는 `LPTOOL_SPECS` 에 JSON-Schema 를 손으로 적어 뒀다 — `/mcp/list` 를 우리가
# 구현하던 시절의 잔재다. 지금은 `@mcp.tool()` 이 시그니처·타입힌트·독스트링에서
# 카탈로그를 만들므로 그 목록은 **아무 데서도 읽히지 않았고**, 고쳐도 노출되는
# 스키마가 바뀌지 않는다 — 고친 사람은 바뀐 줄 안다. 그래서 지웠다.
# 도구 설명을 고칠 곳은 각 `@mcp.tool()` 함수의 독스트링이다.

_LPHANDLERS = {
    "detect_language": _LPdetect_language,
    "validate_direction": _LPvalidate_direction,
    "list_languages": _LPlist_languages,
    "list_registers": _LPlist_registers,
    "resolve_register": _LPresolve_register,
    "resolve_tone": _LPresolve_tone,
}


def lpcall_tool(name: str, arguments: dict) -> dict:
    handler = _LPHANDLERS.get(name)
    if handler is None:
        raise LPToolError("UNKNOWN_TOOL")
    return handler(arguments)


# =====================================================================================
# 로컬 단독 실행 대비: 런타임이 주입하는 전역 `mcp` 가 없으면 최소 shim 을 쓴다.
# =====================================================================================
try:
    mcp  # noqa: F821
except NameError:
    class _LPLocalMCP:
        def tool(self, *args, **kwargs):
            def _decorator(fn):
                return fn
            return _decorator

    mcp = _LPLocalMCP()
    _LPlog.info("로컬 테스트용 shim 사용", extra={"event": "mcp_shim_used"})


def _lp_run(name: str, arguments: dict) -> str:
    """도구 본문을 부르고 JSON 문자열로 돌려준다.

    **입력 오류를 예외로 올리지 않는다** — MCP 도구가 예외로 죽으면 호출부(워크플로우
    스텝)에 오는 것은 전송 실패와 구분되지 않는 형태다. `ok=false` + `error_type` 으로
    내려야 스텝이 "재시도 무의미" 로 다루고 사용자에게 고정 안내문을 보여줄 수 있다.
    """
    try:
        result = lpcall_tool(name, arguments)
        if isinstance(result, dict) and "ok" not in result:
            result = {"ok": True, **result}
    except LPToolError as exc:
        result = {"ok": False, "error_type": exc.error_type}
    except Exception as exc:  # noqa: BLE001 - 최종 방어선. 원문은 응답에 싣지 않는다 (3.8절)
        _LPlog.warning("도구 실행 실패", extra={"event": "mcp_tool_failed", "error_type": type(exc).__name__})
        result = {"ok": False, "error_type": "TOOL_EXECUTION_FAILED"}
    return json.dumps(result, ensure_ascii=False)


# =====================================================================================
# 선택지를 **도구 스키마에 싣는다** (2026-08-18)
#
# 그전에는 도구 인자가 전부 맨 `str` 이었다. 그러면 **선택지가 계약 어디에도 없다** —
# 노출되는 스키마에는 "문자열" 이라고만 적히고, 어떤 값이 유효한지는 `list_languages`·
# `list_registers` 를 따로 불러야 알 수 있다. 그래서 호출부(캔버스 화면·워크플로우 변수·
# 도구를 고르는 LLM)가 **자기 목록을 들고 있게 되고**, 언어나 톤이 늘거나 빠질 때 한쪽만
# 고친다. 그 상태는 예외를 내지 않는다 — 빈 드롭다운이나 "지원하지 않는 언어입니다" 로만
# 드러나고, 사용자에게는 백엔드가 막은 것처럼 보인다.
#
# 위 표(`LPSUPPORTED_LANGUAGES`·`LPREGISTERS`·`LPDOC_TYPE_POLICIES`·`LPTONE_PRESETS`)에서
# `enum` 을 **만들어서** 얹는다. 표가 유일한 출처이므로 사본이 생기지 않는다 —
# 손으로 적으면 이 파일 안에서 표와 스키마가 갈린다.
#
# **`Literal[...]` 로 하지 않은 이유가 두 가지다.** Literal 이면 스키마에 enum 이 실리는
# 대신 지원 밖 값이 **도구 본문에 닿기 전에** 타입 검증에서 죽는다:
#
# 1. **별칭이 죽는다.** `lpresolve`·`lpresolve_register` 는 `"한국어"`·`"korean"`·
#    `"문어체"`·`"formal"` 을 일부러 흡수한다(화면·워크플로우 변수 표기가 제각각이라
#    한 곳에서 정규화하려는 것이다). Literal 은 그 값들을 전부 거부한다.
# 2. **거부가 판정이 아니라 오류가 된다.** `validate_direction` 은 "거부는 오류가 아니라
#    판정 결과" (`allowed=false` + 고정 한국어 안내문)를 계약으로 삼는다. 타입 검증에서
#    죽으면 호출부에 오는 것은 전송 실패와 구분되지 않는 형태다. `resolve_tone` 의
#    `tone_overridden`·`resolve_register` 의 `fell_back` 도 같이 사라진다 — 그 값들이
#    "사용자가 고른 값이 조용히 무시되지 않게" 하려고 있는 것이다.
#
# 그래서 **스키마에는 선택지를 싣되 판정은 본문이 한다.** 호출부는 무엇을 고를 수 있는지
# 알게 되고(강제), 그래도 다른 값이 오면 지금까지의 안내가 그대로 나간다(그물).
#
# 빈 문자열(`""`)은 **항상 선택지에 넣는다.** GenOS 는 값이 없을 때 `None` 이 아니라 `""`
# 를 주입하므로, 빼 두면 스키마를 엄격히 검증하는 호출부가 "미지정" 을 못 보낸다.
# =====================================================================================
try:  # pydantic 은 MCP 런타임(FastMCP)이 스키마를 만들 때 이미 쓰는 패키지다.
    from pydantic import Field as _LPPydanticField
except Exception:  # noqa: BLE001 - 없으면 선택지 없이(맨 str) 동작한다. 판정은 그대로다.
    _LPPydanticField = None


def _LPchoice_arg(description: str, choices: list) -> object:
    """`(코드, 라벨)` 목록에서 **선택지가 실린 인자 주석**을 만든다.

    Args:
        description: 인자 설명 앞머리.
        choices: `[(code, label), …]`. 표에서 만들어 넘긴다 — 손으로 적지 않는다.

    Returns:
        `Annotated[str, Field(...)]`. pydantic 이 없으면 그냥 `str` 로 떨어진다
        (스키마에 선택지가 안 실릴 뿐, 도구는 그대로 돈다).
    """
    values = [code for code, _ in choices] + [""]
    listed = ", ".join(f"{code}({label})" for code, label in choices)
    text = f"{description} 선택지: {listed}. (미지정은 빈 문자열)"
    if _LPPydanticField is None:
        return str
    return Annotated[str, _LPPydanticField(description=text, json_schema_extra={"enum": values})]


_LPLANGUAGE_CHOICES = [(lang.code, lang.korean_label) for lang in LPSUPPORTED_LANGUAGES]
_LPREGISTER_CHOICES = [(reg.key, reg.korean_label) for reg in LPREGISTERS.values()]
_LPDOC_TYPE_CHOICES = [(key, policy.label) for key, policy in LPDOC_TYPE_POLICIES.items()]
_LPTONE_CHOICES = [(key, preset.label) for key, preset in LPTONE_PRESETS.items()]

_LPTargetLangArg = _LPchoice_arg("번역 대상 언어 코드.", _LPLANGUAGE_CHOICES)
_LPSourceLangArg = _LPchoice_arg("원문 언어 코드. 비우면 표본으로 감지한다.", _LPLANGUAGE_CHOICES)
_LPRegisterArg = _LPchoice_arg("문체.", _LPREGISTER_CHOICES)
_LPDocTypeArg = _LPchoice_arg("문서유형(기본 제공). 관리자가 추가한 코드도 받는다.", _LPDOC_TYPE_CHOICES)
# **enum 은 내장 톤·문서유형뿐이다.** 관리자가 프롬프트 라이브러리에 추가한 항목은
# 등록 시점에 존재하지 않아 스키마에 실을 수 없다 — 본문은 그 값도 받는다.
# 화면이 그리는 **최신 선택지의 정본은 글다듬이 `GET /policies`** 다.
_LPToneArg = _LPchoice_arg(
    "톤(기본 제공). 관리자가 추가한 톤 코드도 받는다. 문서유형 정책이 톤을 고정하면 대체된다.",
    _LPTONE_CHOICES,
)


# =====================================================================================
# MCP Tools
#
# GenOS 는 값이 없을 때 None 이 아니라 **빈 문자열("")** 을 주입한다. 그래서 선택 인자는
# 전부 `str = ""` 로 받고, "안 넘김" 과 "빈 값" 을 본문에서 같게 다룬다.
# =====================================================================================

@mcp.tool()
async def detect_language(sample: str = "") -> str:
    """[언제 쓰나] 문서·발화가 무슨 언어인지 알아야 할 때. LLM 을 쓰지 않아 항상 같은 답이 나온다.

    표본 텍스트의 언어를 **문자 체계로** 감지한다.

    Args:
        sample: 감지할 표본 텍스트.

    Returns:
        JSON 문자열 `{"ok": true, "lang": "ko"|"en"|…, "detected": bool}`.
        **감지 불가는 빈 문자열이고 오류가 아니다** — 숫자·기호뿐인 문서에서 번역을
        막으면 안 되기 때문이다. 그 경우 방향 검증만 건너뛴다.
    """
    return _lp_run("detect_language", {"sample": sample})


@mcp.tool()
async def validate_direction(
    sample: str = "",
    target_lang: _LPTargetLangArg = "",
    source_lang: _LPSourceLangArg = "",
) -> str:
    """[언제 쓰나] 번역을 시작하기 **전에** 지원 범위인지 확인할 때. 거부 사유까지 함께 준다.

    번역 방향(원본→대상)이 지원 범위인지 검증한다. 지원 언어는 6개(한국어·영어·중국어·
    태국어·베트남어·러시아어)이고 **원본이나 대상 중 하나는 반드시 한국어**여야 한다
    (요구사항 §6). `en→ru` 같은 비한국어 쌍은 거부된다.

    Args:
        sample: 원문 표본 (원본 언어 감지용).
        target_lang: 번역 대상 언어 코드.
        source_lang: 원본 언어 코드. 비우면 표본으로 감지한다.

    Returns:
        JSON 문자열 `{"ok": true, "allowed": bool, ...}`.
        **거부는 오류가 아니라 판정 결과**(`allowed=false`)다 — 그래야 호출부가
        "재시도 무의미" 로 다루고 사용자에게 고정 안내문을 보여줄 수 있다.
    """
    return _lp_run("validate_direction", {
        "sample": sample, "target_lang": target_lang, "source_lang": source_lang,
    })


@mcp.tool()
async def list_languages() -> str:
    """[언제 쓰나] UI 가 언어 선택지를 만들 때.

    Returns:
        JSON 문자열. 지원 번역 언어 목록.
    """
    return _lp_run("list_languages", {})


@mcp.tool()
async def list_registers() -> str:
    """[언제 쓰나] UI 가 문체 선택지를 만들 때.

    Returns:
        JSON 문자열. 지원 문체(문어체/구어체) 목록.
    """
    return _lp_run("list_registers", {})


@mcp.tool()
async def resolve_register(register: _LPRegisterArg = "") -> str:
    """[언제 쓰나] 사용자가 고른 문체 값을 정규화할 때.

    Args:
        register: 문체 값. 비거나 알 수 없는 값은 기본 문체로 떨어진다.

    Returns:
        JSON 문자열.
    """
    return _lp_run("resolve_register", {"register": register})


@mcp.tool()
async def resolve_tone(doc_type: _LPDocTypeArg = "", tone: _LPToneArg = "") -> str:
    """[언제 쓰나] 글다듬이에서 문서유형·톤을 확정할 때. 정책 강제 여부까지 판정한다.

    Args:
        doc_type: 문서유형 값. 비우면 기본값.
        tone: 사용자가 고른 톤. 비우면 기본값.

    Returns:
        JSON 문자열 `{"ok": true, "tone", "tone_label", "tone_overridden", "notice"}`.
        **문서유형이 톤을 강제하는 경우** `tone_overridden=true` 와 사용자 안내문을 함께
        낸다 — 사용자가 고른 톤이 조용히 무시되면 왜 문체가 다른지 알 수 없다.
    """
    return _lp_run("resolve_tone", {"doc_type": doc_type, "tone": tone})
