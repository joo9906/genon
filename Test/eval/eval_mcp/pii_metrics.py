"""PII 마스킹 누락 검출 — **최종 답변 텍스트**에 남은 미마스킹 개인정보의 절대 건수.

## 왜 필요한가 — 마스킹은 우리 층이 아니고, 빠져도 소리가 안 난다

민감정보 마스킹(#315)은 적재 전처리기(첨부용 `guardrail` 모듈)가 한다. 그런데 그
모듈은 **사이트 설치본에 없을 수 있고**(2026-09-02 실제로 그 import 가 없어 pdf 적재가
막혔다), 설정(`guardrail.masking_enabled`)이 꺼져 있을 수도 있다. 어느 쪽이든:

- 적재는 **정상으로 보인다.** 문서는 들어가고 검색도 된다.
- 네 기능은 그 텍스트를 그대로 읽어 **최종 답변에 원문 그대로 실어 내보낸다.**
- 오류가 없으므로 **아무 로그에도 남지 않는다.** 사용자가 화면에서 주민등록번호를
  발견할 때까지 아무도 모른다.

즉 이 지표는 **다른 층의 가드레일이 누락됐다는 사실을 우리 쪽 출구에서 잡는** 것이다.

## 왜 비율이 아니라 **절대 건수** 인가

허용치가 0이기 때문이다. 비율로 재면 200문장 문서에서 1건이 0.5% 라 "거의 완벽" 으로
보이고 임계(`< 0.05`)를 통과한다 — **한 건도 나가면 안 되는 값에 비율 기준을 걸면
기준이 사고를 승인한다.** `leak_count == 0` 하나가 합불이다.

## `leak_count == 0` 은 "PII 가 없다" 가 아니다

**여기 있는 유형만** 본다(`DETECTORS`). 주소·계좌번호는 검출하지 않는다 — 주소는
일반 문장과 형태가 겹쳐 오탐이 미탐을 부르고, 계좌번호는 은행마다 자리수가 달라
체크섬이 없어 **일반 숫자열과 구분되지 않는다.** 없는 검출기를 통과로 보이게 하지
않으려고 응답에 `detectors` 를 함께 낸다.

**이름은 2026-09-17 부터 성씨 사전 + 직함/존칭 문맥으로 본다** (`_valid_name`) —
체크섬이 아니라 성씨 목록 재확인이다. 문맥 요건 없이 만들었다가 실측에서 정밀도가
감당이 안 돼(`연락처`·`예시` 같은 흔한 한자어가 전부 이름으로 잡혔다) **직함·존칭이
바로 뒤에 붙을 때만**(`김민준 대리`·`홍길동 님`) 잡도록 좁혔다 — 직함·존칭 없이
본문에만 나오는 이름은 놓친다(재현율을 정밀도와 맞바꿨다). 형태소·NER 모델
없이는 이보다 정확히 가릴 수 없다.

그리고 `masked_count` 를 같이 센다. **`leak_count=0` + `masked_count=0` 은 두 가지 뜻**
이라 그 둘을 가르지 못하면 지표가 무의미해진다:

- 문서에 애초에 개인정보가 없었다 (정상)
- 마스킹도 검출도 아무것도 돌지 않았다 (확인 필요)

## 값을 응답에 담지 않는다 (3.8절)

검출된 PII 원문을 리포트에 실으면 **평가 리포트가 유출 경로가 된다.** 자리
(`start`/`end`)와 유형만 낸다 — 호출자는 자기가 넣은 텍스트를 갖고 있으므로 그
좌표로 찾을 수 있고, 우리는 값을 옮기지 않는다.

## 오탐을 체크섬으로 줄인다

주민등록번호·사업자등록번호·카드번호는 **검증식이 정의된 번호**다. 자리수만 맞는
숫자열(날짜 조합·문서번호·통계표의 수치)이 걸리면 가드레일이 상시 빨간불이 되고,
그러면 사람이 임계를 올리거나 지표를 끈다 — 오탐은 미탐으로 가는 길이다.
검증식이 없는 유형(전화·이메일·여권·면허)은 형태가 충분히 특이한 것만 넣었다.
"""

import re

from .error_codes import ERR_EMPTY_ITEMS, fail
from .logging_utils import log_info, log_warning
from .normalize import strip_display_tags

# 마스킹 문자 — 운영에서 실제로 쓰는 것들. `X`/`x` 는 숫자 자리에 붙어야만 마스킹으로
# 본다(영문 단어의 x 를 마스킹으로 세면 `masked_count` 가 부풀어 진단이 흐려진다).
_MASK_CHARS = "*●#✻"

# 숫자·하이픈으로 이뤄진 토큰 안에 마스킹 문자가 2개 이상 있는 것 = 마스킹된 식별자.
# `010-****-5678` · `******-*******` · `1234-****-****-5678` 를 잡는다.
_MASKED_RE = re.compile(
    r"(?<![0-9A-Za-z])(?=[0-9\-]*[" + _MASK_CHARS + r"]{2,})"
    r"[0-9\-" + _MASK_CHARS + r"]{4,}"
    r"(?![0-9A-Za-z])"
)


def _digits(text: str) -> list:
    return [int(ch) for ch in text if ch.isdigit()]


def _valid_rrn(token: str) -> bool:
    """주민등록번호/외국인등록번호 검증식 + 월·일 상식 검사.

    가중치 2,3,4,5,6,7,8,9,2,3,4,5 로 앞 12자리를 더해 `(11 - 합%11) % 10` 이 13번째
    자리와 같아야 한다. 이 검사가 없으면 `210101-1234567` 같은 **지어낸 예시 번호**가
    전부 유출로 잡혀 리포트가 오탐으로 덮인다.
    """
    nums = _digits(token)
    if len(nums) != 13:
        return False
    month, day = nums[2] * 10 + nums[3], nums[4] * 10 + nums[5]
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return False
    weights = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
    total = sum(n * w for n, w in zip(nums[:12], weights))
    return (11 - total % 11) % 10 == nums[12]


def _valid_biz(token: str) -> bool:
    """사업자등록번호 검증식 (가중치 1,3,7,1,3,7,1,3,5 + 9번째 자리 보정)."""
    nums = _digits(token)
    if len(nums) != 10:
        return False
    weights = (1, 3, 7, 1, 3, 7, 1, 3, 5)
    total = sum(n * w for n, w in zip(nums[:9], weights))
    total += (nums[8] * 5) // 10
    return (10 - total % 10) % 10 == nums[9]


def _valid_card(token: str) -> bool:
    """신용카드 Luhn 검사.

    16자리 숫자열은 계좌번호·문서번호로도 흔하다. Luhn 을 걸지 않으면 그 전부가
    카드번호로 잡힌다 (통계표가 든 문서에서 특히).
    """
    nums = _digits(token)
    if not 13 <= len(nums) <= 19:
        return False
    total = 0
    for i, n in enumerate(reversed(nums)):
        if i % 2:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


# ── 이름 검출 — 체크섬이 아니라 **성씨 사전 + 직함/존칭 문맥** (2026-09-17) ──────
#
# `genon_pii_audit.py` 의 사본이다 — 성씨 목록·정규식·문맥 목록까지 **글자 하나
# 안 갈리게** 유지한다. 이 판정부가 갈리면 감사 도구와 이 지표가 같은 문서에
# 다른 건수를 낸다(사본 대조는 `check_mcp_tools._check_pii_copy` 가 본다).
#
# **처음에는 문맥 요건 없이(성씨+1~2음절이면 전부) 만들었는데, 실측에서 정밀도가
# 감당이 안 됐다.** `연락처`(연+락처)·`예시`(예+시)처럼 극히 흔한 한자어가 성씨
# 글자로 시작하는 경우가 널려 있어 오탐이 났다. **그래서 직함·존칭이 바로
# 뒤에 붙을 때만 잡는다** — 대가는 직함·존칭 없이 본문에만 나오는 이름은
# 놓친다는 것이다(재현율을 정밀도와 맞바꿨다).
_SURNAMES_2 = (
    "남궁", "황보", "제갈", "선우", "서문", "사공", "독고", "동방",
)

_SURNAMES_1 = (
    "김", "이", "박", "최", "정", "강", "조", "윤", "장", "임",
    "한", "오", "신", "서", "권", "황", "안", "송", "전", "홍",
    "유", "고", "문", "양", "손", "배", "백", "허", "남", "심",
    "노", "하", "곽", "성", "차", "주", "우", "구", "민", "나",
    "진", "지", "엄", "채", "원", "천", "방", "공", "현", "함",
    "변", "염", "여", "추", "도", "소", "석", "선", "설", "마",
    "길", "연", "위", "표", "명", "기", "반", "왕", "금", "옥",
    "육", "인", "맹", "제", "모", "탁", "국", "편", "용", "예",
    "봉", "사", "화", "부", "가", "복", "동", "두", "목", "형",
    "계", "피", "감", "음", "태", "경", "어", "좌",
)

# 이 뒤에 (공백 하나 있어도 되고 붙어도 되는) 직함·존칭이 와야만 잡는다.
_NAME_CONTEXT = (
    "선생님", "고객님", "사장님", "회장님", "대표님",
    "부장님", "과장님", "차장님", "팀장님", "실장님", "이사님", "원장님",
    "님", "씨", "군", "양",
    "대리", "과장", "차장", "부장", "팀장", "실장", "이사", "대표",
    "사원", "주임", "교수", "박사", "원장", "전무", "상무", "회장",
    "본부장", "지점장", "센터장", "국장",
)

# 직함 단어 자체가 (성씨 글자 + 1~2음절) 모양이면 그 직함을 이름으로 오인한다
# (`선생님`→선(성씨)+생, `박사님`→박(성씨)+사, `이사님`→이(성씨)+사). 매치된
# 토큰이 직함 목록 자체(또는 `-님` 을 뗀 어간)와 같으면 버린다.
_NAME_NOT_A_GIVEN = frozenset(_NAME_CONTEXT) | frozenset(
    word[:-1] for word in _NAME_CONTEXT if word.endswith("님") and len(word) > 1
)

# 성씨 다음 1~2 음절이 이 값과 같으면 잡지 않는다 — 성씨 + 흔한 낱말이 이름처럼
# 보이는 가장 흔한 사례들이다. **완전한 목록이 아니다.**
_NAME_GIVEN_STOPWORDS = frozenset({
    "것", "번", "제", "후", "때", "리", "래", "곳", "점",
    "안", "밖", "속", "앞", "뒤", "든", "터", "지", "께",
    "지만", "러분", "든지", "부터", "까지", "처럼", "마다", "라도", "조차", "마저",
})

_NAME_SURNAME_ALT = "|".join(sorted(_SURNAMES_2 + _SURNAMES_1, key=len, reverse=True))
_NAME_CONTEXT_ALT = "|".join(sorted(_NAME_CONTEXT, key=len, reverse=True))
_NAME_RE = re.compile(
    rf"(?<![가-힣])(?:{_NAME_SURNAME_ALT})[가-힣]{{1,2}}(?= ?(?:{_NAME_CONTEXT_ALT}))"
)


def _valid_name(token: str) -> bool:
    """성씨 사전에 다시 대조하고, 직함 자체나 흔한 낱말이 아닌지 본다.

    체크섬이 아니라 **재확인**이다 — `check` 는 `match.group(0)` 만 받으므로
    정규식이 성씨를 1글자로 골랐는지 2글자(복성)로 골랐는지 여기서 다시 가른다.
    복성이 더 기니 먼저 본다.
    """
    if token[:2] in _SURNAMES_2 and len(token) - 2 in (1, 2):
        given = token[2:]
    elif token[:1] in _SURNAMES_1 and len(token) - 1 in (1, 2):
        given = token[1:]
    else:
        return False
    if given in _NAME_GIVEN_STOPWORDS:
        return False
    return token not in _NAME_NOT_A_GIVEN


# 검출기 표 — (유형, 정규식, 검증 함수 또는 None).
#
# **`(?<!\d)`/`(?!\d)` 로 감싸는 것이 중요하다.** 없으면 더 긴 숫자열의 일부가 걸려
# 한 자리 어긋난 좌표를 낸다 (계좌번호 안에서 카드번호를 찾는 식).
DETECTORS: tuple = (
    (
        "rrn",  # 주민등록번호·외국인등록번호 (뒷자리 1~8)
        re.compile(r"(?<![0-9])\d{6}\s?-\s?[1-8]\d{6}(?![0-9])"),
        _valid_rrn,
    ),
    (
        "biz",  # 사업자등록번호
        re.compile(r"(?<![0-9])\d{3}-\d{2}-\d{5}(?![0-9])"),
        _valid_biz,
    ),
    (
        "card",  # 신용·체크카드
        re.compile(r"(?<![0-9])(?:\d{4}[- ]){3}\d{4}(?![0-9])"),
        _valid_card,
    ),
    (
        "phone",  # 휴대전화 + 유선 지역번호
        re.compile(
            r"(?<![0-9])(?:01[016789]|0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4]))"
            r"\s?-\s?\d{3,4}\s?-\s?\d{4}(?![0-9])"
        ),
        None,
    ),
    (
        "email",
        re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
        None,
    ),
    (
        "driver_license",  # 운전면허 (지역 2 - 연도 2 - 일련 6 - 확인 2)
        re.compile(r"(?<![0-9])\d{2}-\d{2}-\d{6}-\d{2}(?![0-9])"),
        None,
    ),
    (
        "passport",  # 여권번호 (M/S/R/O/D + 8자리)
        re.compile(r"(?<![0-9A-Za-z])[MSRODmsrod]\d{8}(?![0-9A-Za-z])"),
        None,
    ),
    ("name", _NAME_RE, _valid_name),
)

DETECTOR_NAMES: tuple = tuple(name for name, _re, _check in DETECTORS)


def scan_text(text: str) -> dict:
    """한 텍스트의 미마스킹 PII 를 찾는다. **값은 담지 않고 자리만** 낸다.

    `<mark>` 를 먼저 벗긴다 — 글다듬이·번역의 최종 텍스트에는 표시용 태그가 섞여 있고,
    바뀐 낱말이 번호 가운데를 가르면(`010-<mark>1234</mark>-5678`) 검출기가 못 본다.
    **미탐 쪽으로 틀리는 경로**라 반드시 벗기고 센다.
    """
    body = strip_display_tags(text or "")
    found: list = []
    taken: list = []  # 이미 잡힌 구간 — 겹치는 검출을 두 번 세지 않는다

    for name, pattern, check in DETECTORS:
        for match in pattern.finditer(body):
            token = match.group(0)
            if check is not None and not check(token):
                continue
            start, end = match.span()
            # 겹침 배제: 카드번호로 잡힌 자리를 전화번호가 다시 잡는 식의 이중 계수를
            # 막는다. 앞선 검출기(체크섬이 있는 쪽)가 우선한다 — 표 순서가 곧 우선순위다.
            if any(start < prev_end and prev_start < end for prev_start, prev_end in taken):
                continue
            taken.append((start, end))
            found.append({"category": name, "start": start, "end": end})

    found.sort(key=lambda item: item["start"])
    return {
        "leak_count": len(found),
        "locations": found,
        "masked_count": len(_MASKED_RE.findall(body)),
    }


def pii_leak_count(texts: list) -> dict:
    """최종 답변 텍스트들의 **미마스킹 PII 절대 건수**.

    Args:
        texts: 문자열 목록, 또는 `{"id": …, "text": …}` 목록. 네 기능의 최종 답변
            (006 `text` · 글다듬이 `polished_text` · 번역 `translated_text` ·
            FAQ 항목을 이어붙인 텍스트)을 그대로 넣는다.

    Returns:
        `leak_count` 가 합불 값이고 **0 이어야 한다**. 나머지는 진단용이다 —
        `by_category`(어느 유형이 샜나), `masked_count`(마스킹이 돌기는 했나),
        `detectors`(무엇을 봤나 = 무엇은 안 봤나), `items`(항목별 내역).
    """
    if not texts:
        fail(ERR_EMPTY_ITEMS, event="pii_no_texts")

    items: list = []
    by_category: dict = {}
    total = masked_total = 0

    for index, entry in enumerate(texts):
        if isinstance(entry, dict):
            ident = entry.get("id", index)
            body = str(entry.get("text") or "")
        else:
            ident, body = index, str(entry or "")
        result = scan_text(body)
        for hit in result["locations"]:
            by_category[hit["category"]] = by_category.get(hit["category"], 0) + 1
        total += result["leak_count"]
        masked_total += result["masked_count"]
        items.append(
            {
                "id": ident,
                "leak_count": result["leak_count"],
                "masked_count": result["masked_count"],
                "locations": result["locations"],
            }
        )

    payload = {
        "texts": len(items),
        "leak_count": total,
        "by_category": dict(sorted(by_category.items())),
        "masked_count": masked_total,
        # 검출 범위를 응답에 싣는다 — 목록에 없는 유형(이름·주소·계좌번호)은 재지 않으므로
        # `leak_count=0` 을 "개인정보 없음" 으로 읽으면 안 된다.
        "detectors": list(DETECTOR_NAMES),
        "items": items,
    }

    # 값은 남기지 않는다 (3.8절) — 건수와 유형 이름만.
    if total:
        log_warning(
            "최종 답변에 마스킹되지 않은 개인정보가 있다",
            event="pii_leak_detected",
            item_count=total,
            status=" ".join(f"{k}={v}" for k, v in payload["by_category"].items()),
        )
    else:
        log_info(
            "미마스킹 개인정보 없음",
            event="pii_scan_clean",
            item_count=len(items),
            status=f"masked={masked_total}",
        )
    return payload
