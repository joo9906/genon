# =====================================================================================
# genon_lang_policy — 언어·문체·톤 정책 MCP 도구 (area 01)
#
# **이 파일 하나가 등록 단위다.** GenOS MCP 는 소스 파일 한 개를 받아 실행하며,
# `mcp` 객체를 런타임이 전역으로 주입한다. 그래서 패키지로 쪼갤 수 없다.
#
# **모든 최상위 심볼에 `LP` 접두어를 붙였다.** 한 서버에 다른 도구 파일이 함께 로드될 수
# 있어서다 — `ToolError`·`TOOL_SPECS` 같은 흔한 이름을 그대로 두면 나중에 로드된 쪽이
# 앞엣것을 덮어쓰고, 그 실패는 "도구가 이상한 결과를 낸다" 로만 드러난다.
#
# LLM 을 부르지 않는다. 여기 있는 판정은 **거부 판정**(지원하지 않는 번역 방향)과
# **정책 강제**(문서유형이 톤을 덮어쓰는 경우)라서, 모델에 맡기면 같은 입력에 다른 답이
# 나온다. 스크립트 기반으로 결정적으로 판정한다.
#
# 비표준 패키지를 쓰지 않는다 (stdlib 만). 그래서 부팅 시 설치 절차가 없다.
# =====================================================================================

import json
import unicodedata
from dataclasses import dataclass, field

# ── languages.py ─────────────────────────────
LPKOREAN = "ko"


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


def lpdetect(text: str, *, sample_chars: int = 4000) -> str:
    """가장 많이 등장한 스크립트의 언어 코드. 판정 불가면 빈 문자열.

    긴 문서 전체를 세지 않고 앞부분 표본만 본다 — 언어는 문서 안에서 바뀌지 않고,
    수십만 자를 세는 비용이 판정 정확도를 올려주지 않는다.

    베트남어는 라틴 문자 위에 얹히므로, 성조 부호가 하나라도 있으면 라틴 표를
    베트남어로 본다 ('en' 과 'vi' 가 같은 글자를 공유해 단순 최빈값으로는 갈리지 않는다).
    """
    counts: dict = {}
    for char in (text or "")[:sample_chars]:
        script = _LPscript_of(char)
        if script:
            counts[script] = counts.get(script, 0) + 1
    if not counts:
        return ""
    if counts.get("vi"):
        counts["vi"] = counts.pop("vi") + counts.pop("en", 0)
    return max(counts.items(), key=lambda item: item[1])[0]


def lpresolve_direction(target_lang: str, source_lang: str, sample_text: str) -> tuple:
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
    target = lpresolve(target_lang)

    source = None
    if (source_lang or "").strip():
        source = lpresolve(source_lang)
    else:
        detected = lpdetect(sample_text)
        if detected:
            source = _LPBY_CODE[detected]

    if source is None:
        # 감지 불가(숫자·기호뿐인 문서)는 거부하지 않는다 — 방향 검증만 건너뛴다.
        return None, target

    if source.code == target.code:
        raise LPLanguageNotSupported("원문과 같은 언어로는 번역할 수 없습니다.")
    if LPKOREAN not in (source.code, target.code):
        raise LPLanguageNotSupported(
            "한국어가 포함된 번역만 지원합니다. 원문 또는 번역 대상 중 하나는 한국어여야 합니다."
        )
    return source, target


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
    """`GET /languages` 응답에 함께 실어 화면이 선택지를 하드코딩하지 않게 한다."""
    return [
        {"key": register.key, "label": register.korean_label}
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
    # forced_tone이 없을 때 사용자가 선택 가능한 톤 목록
    allowed_tones: tuple[str, ...] = field(default=("polite", "friendly", "report"))
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


def lpnormalize_doc_type(value: str | None) -> str:
    key = (value or LPDEFAULT_DOC_TYPE).strip()
    return key if key in LPDOC_TYPE_POLICIES else LPDEFAULT_DOC_TYPE


def lpresolve_tone(doc_type_raw: str | None, tone_raw: str | None) -> tuple[str, str, bool]:
    """문서유형 정책에 따라 실제 적용할 톤을 결정한다.

    Returns:
        (doc_type_key, tone_key, tone_overridden)
        tone_overridden: 사용자가 요청한 톤이 정책에 의해 다른 톤으로 대체됐는지 여부.
                         True면 응답에 안내 문구를 붙여 사용자에게 알린다.
    """
    doc_type = lpnormalize_doc_type(doc_type_raw)
    policy = LPDOC_TYPE_POLICIES[doc_type]
    requested = (tone_raw or "").strip()

    if policy.forced_tone:
        overridden = lpis_valid_tone(requested) and requested != policy.forced_tone
        return doc_type, policy.forced_tone, overridden

    if lpis_valid_tone(requested) and requested in policy.allowed_tones:
        return doc_type, requested, False

    # 미지정/허용 외 톤 → 허용 목록의 첫 톤(또는 기본 톤)으로 안전하게 대체
    fallback = policy.allowed_tones[0] if policy.allowed_tones else LPDEFAULT_TONE
    return doc_type, fallback, lpis_valid_tone(requested)


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
    code = lpdetect(sample)
    return {"ok": True, "lang": code or "", "detected": bool(code)}


def _LPvalidate_direction(arguments: dict) -> dict:
    """번역 방향이 한국어 축을 지나는지 검증한다 (요구사항 §6).

    **거부는 오류가 아니라 판정 결과다.** `allowed=false` 로 내려야 워크플로우가
    "재시도 무의미" 로 다루고 사용자에게 고정 안내문을 보여줄 수 있다.
    """
    sample = _LPtext_arg(arguments, "sample")[:_LPMAX_SAMPLE_CHARS]
    target_lang = _LPtext_arg(arguments, "target_lang")
    source_lang = _LPtext_arg(arguments, "source_lang", required=False)

    try:
        source, target = lpresolve_direction(target_lang, source_lang, sample)
    except LPLanguageNotSupported as exc:
        # 메시지는 `languages.py` 안에서 작성한 고정 한국어 안내문이다 (3.8절 계약).
        return {
            "ok": True,
            "allowed": False,
            "reason": str(exc),
            "source_lang": "",
            "target_lang": target_lang,
            "detected": False,
        }

    return {
        "ok": True,
        "allowed": True,
        "reason": "",
        "source_lang": source.code if source else "",
        "target_lang": target.code,
        # 감지 불가(숫자·기호뿐)는 거부가 아니다 — 방향 검증만 건너뛴 상태다.
        "detected": source is not None,
        "korean_axis": LPKOREAN in ((source.code if source else ""), target.code),
        # 이 방향에 용어사전이 붙는가. 거부 판정이 아니라 **안내**다 — 워크플로우가
        # 로그·응답에 실어 "왜 이 언어만 용어가 안 지켜지나" 를 답할 수 있게 한다.
        "glossary_applies": lpglossary_applies(source.code if source else "", target.code),
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
    policy = LPDOC_TYPE_POLICIES[doc_type_key]
    tone = LPTONE_PRESETS[tone_key]

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
    }


LPTOOL_SPECS = [
    {
        "name": "detect_language",
        "description": (
            "표본 텍스트의 언어를 문자 체계로 감지한다. LLM 을 쓰지 않으므로 같은 입력에 "
            "항상 같은 결과가 나온다. 감지 불가는 빈 문자열이다(오류가 아니다)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"sample": {"type": "string", "description": "감지할 표본 텍스트"}},
            "required": ["sample"],
        },
    },
    {
        "name": "validate_direction",
        "description": (
            "번역 방향(원본→대상)이 지원 범위인지 검증한다. 지원 언어 6개이며 "
            "원본이나 대상 중 하나는 반드시 한국어여야 한다. 거부는 오류가 아니라 "
            "`allowed=false` 판정으로 돌려준다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sample": {"type": "string", "description": "원문 표본 (원본 언어 감지용)"},
                "target_lang": {"type": "string", "description": "번역 대상 언어 코드"},
                "source_lang": {"type": "string", "description": "원본 언어 코드. 비우면 표본으로 감지한다"},
            },
            "required": ["sample", "target_lang"],
        },
    },
    {
        "name": "list_languages",
        "description": "지원하는 번역 언어 목록을 낸다.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_registers",
        "description": "지원하는 문체(문어체/구어체) 목록을 낸다.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "resolve_register",
        "description": "문체 값을 정규화한다. 알 수 없는 값은 기본 문체로 떨어진다.",
        "inputSchema": {
            "type": "object",
            "properties": {"register": {"type": "string", "description": "문체 값"}},
        },
    },
    {
        "name": "resolve_tone",
        "description": (
            "문서유형과 톤을 확정한다. 문서유형 정책이 톤을 강제하는 경우 "
            "`tone_overridden=true` 와 사용자 안내문을 함께 낸다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "doc_type": {"type": "string", "description": "문서유형 값. 비우면 기본값"},
                "tone": {"type": "string", "description": "사용자가 고른 톤. 비우면 기본값"},
            },
        },
    },
]

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
    print("[BOOT] 로컬 테스트용 shim 사용")


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
        print(f"[ERROR] {name} 실패: {type(exc).__name__}")
        result = {"ok": False, "error_type": "TOOL_EXECUTION_FAILED"}
    return json.dumps(result, ensure_ascii=False)


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
async def validate_direction(sample: str = "", target_lang: str = "", source_lang: str = "") -> str:
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
async def resolve_register(register: str = "") -> str:
    """[언제 쓰나] 사용자가 고른 문체 값을 정규화할 때.

    Args:
        register: 문체 값. 비거나 알 수 없는 값은 기본 문체로 떨어진다.

    Returns:
        JSON 문자열.
    """
    return _lp_run("resolve_register", {"register": register})


@mcp.tool()
async def resolve_tone(doc_type: str = "", tone: str = "") -> str:
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
