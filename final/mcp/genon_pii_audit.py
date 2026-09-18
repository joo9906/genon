# =====================================================================================
# genon_pii_audit — 생성 문서 PII 노출 건수 감사 MCP 도구 (area 01)
#
# **이 파일 하나가 등록 단위다.** GenOS MCP 는 소스 파일 한 개를 받아 실행하며,
# `mcp` 객체를 런타임이 전역으로 주입한다. 그래서 패키지로 쪼갤 수 없다.
#
# **모든 최상위 심볼에 `PA` 접두어를 붙였다.** 한 서버에 다른 도구 파일이 함께 로드될 수
# 있어서다 — 겹치는 이름은 나중에 로드된 쪽이 앞엣것을 덮고, 그 실패는 "도구가 이상한
# 값을 낸다" 로만 드러난다. **도구 함수 이름만 예외**다(LLM 에 노출되는 계약이라 못 붙인다).
#
# ## 이 도구의 몫 — **집계만** 한다, 언제 도는지는 정하지 않는다
#
# 야간·주간처럼 **주기적으로 사람이 직접 돌리는** 감사용이다. 그래서 스케줄러도, 저장소도,
# 배치 트리거도 여기 없다 — 결과 텍스트 묶음을 받아 **미마스킹 개인정보 건수를 세어
# 돌려주는 것**이 전부다. 주기는 운영이 정한다.
#
# 기능 응답 경로(코드서빙 payload)에는 **붙이지 않는다.** 매 응답마다 도는 판정이 아니고,
# 응답에 실으면 그 값이 화면 계약이 되어 나중에 바꿀 때 발이 묶인다.
#
# ## 왜 LLM 을 쓰지 않나
#
# 셋 다 이 도구를 못 쓰게 만드는 이유다:
#
# 1. **감사 대상을 모델에 보내게 된다.** 미마스킹 개인정보를 찾겠다고 그 텍스트를 LLM
#    호출에 실으면 **감사 자체가 유출 경로**가 된다. 우리가 세려던 사고를 우리가 낸다.
# 2. **같은 문서에 같은 답이 안 나온다.** 주 단위 추세를 보는 값인데 판정이 흔들리면
#    건수가 늘었는지 모델이 달라졌는지 구분할 수 없다.
# 3. **허용치가 0 이라 오탐 비용이 크다.** 상시 빨간불이면 사람이 지표를 끈다 —
#    오탐은 결국 미탐으로 간다. 검증식(체크섬)이 있는 유형은 그걸로 거른다.
#
# GenOS 가드레일(#315 민감정보 마스킹)과는 **경쟁이 아니라 짝**이다. 마스킹은 적재
# 전처리기가 하고, 이 도구는 **그 층이 빠졌다는 사실을 산출물 쪽에서** 잡는다.
#
# ## 왜 필요한가 — 마스킹은 우리 층이 아니고, 빠져도 소리가 안 난다
#
# 마스킹 모듈은 **사이트 설치본에 없을 수 있고**(2026-09-02 에 실제로 그 import 가 없어
# pdf 적재가 막혔다) 설정이 꺼져 있을 수도 있다. 어느 쪽이든 적재는 정상으로 보이고,
# 검색도 되며, 네 기능이 그 텍스트를 **최종 답변에 원문 그대로** 싣는다. 오류가 없으니
# 로그에도 안 남는다 — 사용자가 화면에서 주민등록번호를 발견할 때까지 아무도 모른다.
#
# ## 판정부는 `onprem/eval/eval_mcp/pii_metrics.py` 의 **사본**이다
#
# 배포 단위 간 import 금지라 사본이고, 표 격자·톤 프리셋과 같은 성격의 **의도된 중복**이다.
# 갈리면 같은 문서가 감사 도구와 평가지표에서 **다른 건수**로 나오고 그 어긋남은 오류로
# 드러나지 않는다 — `onprem/test/check_mcp_tools.py` 가 두 구현에 같은 입력을 태워
# 대조한다. 검출 규칙을 고치면 **두 곳을 같이 고친다.**
#
# 비표준 패키지를 쓰지 않는다 (stdlib 만). 그래서 부팅 시 설치 절차가 없다.
# =====================================================================================

import json
import logging
import os
import re
import sys
from typing import Annotated

# ── 로깅 ───────────────────────────────────────────
# **`print()` 를 쓰지 않는다** (GENOS_RULES §C, 가이드 3.10). MCP 는 stdout 이 전송 채널이
# 될 수 있고(stdio 방식), 그러면 로그 한 줄이 프로토콜을 깨뜨린다.
# **값(검출된 개인정보·문서 원문)은 로그에 넣지 않는다** (3.8절) — 건수와 유형 이름만.
_PAlog = logging.getLogger("genon_pii_audit")


def _PAsetup_logging() -> None:
    """이 파일 전용 **stderr** 핸들러를 붙인다.

    로깅 설정이 없는 프로세스에서 `logger.info` 는 **아무 데도 안 나온다**(기본 최후
    핸들러가 WARNING 부터다). 그냥 logger 로 바꾸기만 하면 감사 요약이 소리 없이
    사라진다 — 그건 print 보다 나쁘다.
    """
    if _PAlog.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    _PAlog.addHandler(handler)
    _PAlog.setLevel(logging.INFO)
    # 루트로 올리지 않는다 — 루트에 stdout 핸들러가 붙어 있으면 그리로 새어 나간다.
    _PAlog.propagate = False


_PAsetup_logging()


class PAToolError(Exception):
    """호출자 입력 문제. 예외 원문이 아니라 **코드**만 응답에 싣는다 (3.8절)."""

    def __init__(self, error_type: str):
        super().__init__(error_type)
        self.error_type = error_type


# =====================================================================================
# 검출 규칙 — `eval_mcp/pii_metrics.py` 의 사본 (위 머리말)
# =====================================================================================

# 표시용 `<mark>` 는 먼저 벗긴다. 글다듬이·번역의 최종 텍스트에는 하이라이트 태그가
# 섞여 있고, 바뀐 낱말이 번호 가운데를 가르면(`010-<mark>1234</mark>-5678`) 검출기가
# 못 본다 — **미탐 쪽으로 틀리는 경로**라 반드시 벗기고 센다.
# **`<mark>` 만** 벗긴다. `<table>` 은 원문에서 온 구조다.
_PADISPLAY_TAG_RE = re.compile(r"</?mark\s*>", re.IGNORECASE)

# 마스킹 문자 — 운영에서 실제로 쓰는 것들. `X`/`x` 는 넣지 않는다(영문 단어의 x 를
# 마스킹으로 세면 `masked_count` 가 부풀어 진단이 흐려진다).
_PAMASK_CHARS = "*●#✻"

# 숫자·하이픈으로 이뤄진 토큰 안에 마스킹 문자가 2개 이상 있는 것 = 마스킹된 식별자.
# `010-****-5678` · `******-*******` · `1234-****-****-5678` 를 잡는다.
_PAMASKED_RE = re.compile(
    r"(?<![0-9A-Za-z])(?=[0-9\-]*[" + _PAMASK_CHARS + r"]{2,})"
    r"[0-9\-" + _PAMASK_CHARS + r"]{4,}"
    r"(?![0-9A-Za-z])"
)


def _PAdigits(text: str) -> list:
    return [int(ch) for ch in text if ch.isdigit()]


def _PAvalid_rrn(token: str) -> bool:
    """주민등록번호/외국인등록번호 검증식 + 월·일 상식 검사.

    이 검사가 없으면 `210101-1234567` 같은 **지어낸 예시 번호**가 전부 유출로 잡혀
    리포트가 오탐으로 덮인다.
    """
    nums = _PAdigits(token)
    if len(nums) != 13:
        return False
    month, day = nums[2] * 10 + nums[3], nums[4] * 10 + nums[5]
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return False
    weights = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
    total = sum(n * w for n, w in zip(nums[:12], weights))
    return (11 - total % 11) % 10 == nums[12]


def _PAvalid_biz(token: str) -> bool:
    """사업자등록번호 검증식 (가중치 1,3,7,1,3,7,1,3,5 + 9번째 자리 보정)."""
    nums = _PAdigits(token)
    if len(nums) != 10:
        return False
    weights = (1, 3, 7, 1, 3, 7, 1, 3, 5)
    total = sum(n * w for n, w in zip(nums[:9], weights))
    total += (nums[8] * 5) // 10
    return (10 - total % 10) % 10 == nums[9]


def _PAvalid_card(token: str) -> bool:
    """신용카드 Luhn 검사.

    16자리 숫자열은 계좌번호·문서번호로도 흔하다. Luhn 을 걸지 않으면 그 전부가
    카드번호로 잡힌다 (통계표가 든 문서에서 특히).
    """
    nums = _PAdigits(token)
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
# 사람 이름에는 검증식(체크섬)이 없다 — 그래서 이 검출기는 위 셋과 성격이 다르다.
# `check` 자리에 들어가는 것은 수학적 검증이 아니라 **성씨 사전 재확인**이다.
#
# **처음에는 문맥 요건 없이(성씨+1~2음절이면 전부) 만들었는데, 실측에서 정밀도가
# 감당이 안 됐다.** `연락처`(연+락처)·`예시`(예+시)처럼 극히 흔한 한자어가 성씨
# 글자로 시작하는 경우가 널려 있어, 감사 리포트가 상시 빨간불이 될 정도로
# 오탐이 났다(이 파일 자체가 "오탐은 결국 미탐으로 간다" 고 적어 둔 그 실패다).
# **그래서 직함·존칭이 바로 뒤에 붙을 때만 잡는다** — `_PA_NAME_CONTEXT` 가 없으면
# 애초에 정규식이 매치하지 않는다. 대가는 **직함·존칭 없이 본문에만 나오는
# 이름은 놓친다**(예: "이 문제는 김민준이 해결했다") — 재현율을 정밀도와 맞바꿨다.
#
# **오탐·미탐이 둘 다 남는다** — 성씨 사전에 없는 성씨는 놓치고(미탐), 직함
# 자체의 앞 음절이 성씨 글자와 겹치면(`선생님`→선생+님, `박사님`→박사+님) 그
# 직함 단어 자체를 이름으로 오인할 수 있어 `_PA_NAME_NOT_A_GIVEN` 으로 그
# 자리만 따로 막았다 — **완전한 목록이 아니고, 그것이 알려진 한계다.** 형태소·
# NER 모델 없이는 이보다 정확히 가릴 수 없다(폐쇄망 설치 가능 여부는 미확인).
#
# 그래서 `PANOT_DETECTED` 에서 `name` 을 뺐다 — "전혀 못 본다" 에서 "직함·존칭이
# 붙은 것만 본다" 로 바뀐 것이다. 값은 여전히 응답에 싣지 않는다(3.8절), 자리만 낸다.
_PA_SURNAMES_2 = (
    "남궁", "황보", "제갈", "선우", "서문", "사공", "독고", "동방",
)

_PA_SURNAMES_1 = (
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
# **`글자` 다음에 오는 것만 확인한다** — 뒤에 조사가 더 붙어도(`대리에게`·`님께서`)
# 상관없다. 순서는 무관하다(`|` 대안 중 하나만 맞으면 된다).
_PA_NAME_CONTEXT = (
    "선생님", "고객님", "사장님", "회장님", "대표님",
    "부장님", "과장님", "차장님", "팀장님", "실장님", "이사님", "원장님",
    "님", "씨", "군", "양",
    "대리", "과장", "차장", "부장", "팀장", "실장", "이사", "대표",
    "사원", "주임", "교수", "박사", "원장", "전무", "상무", "회장",
    "본부장", "지점장", "센터장", "국장",
)

# 직함 단어 자체가 (성씨 글자 + 1~2음절) 모양이면 그 직함을 이름으로 오인한다
# (`선생님`→선(성씨)+생, `박사님`→박(성씨)+사, `이사님`→이(성씨)+사). **문맥
# 요건만으로는 못 막는다** — 직함 뒤에 또 다른 존칭·직함이 오는 흔한 경우라서다.
# 그래서 매치된 토큰이 직함 목록 자체(또는 `-님` 을 뗀 어간)와 같으면 버린다.
_PA_NAME_NOT_A_GIVEN = frozenset(_PA_NAME_CONTEXT) | frozenset(
    word[:-1] for word in _PA_NAME_CONTEXT if word.endswith("님") and len(word) > 1
)

# 성씨 다음 1~2 음절이 이 값과 같으면 잡지 않는다 — 성씨 + 흔한 낱말이 이름처럼
# 보이는 가장 흔한 사례들이다. **완전한 목록이 아니다.**
_PA_NAME_GIVEN_STOPWORDS = frozenset({
    "것", "번", "제", "후", "때", "리", "래", "곳", "점",
    "안", "밖", "속", "앞", "뒤", "든", "터", "지", "께",
    "지만", "러분", "든지", "부터", "까지", "처럼", "마다", "라도", "조차", "마저",
})

_PA_NAME_SURNAME_ALT = "|".join(
    sorted(_PA_SURNAMES_2 + _PA_SURNAMES_1, key=len, reverse=True)
)
_PA_NAME_CONTEXT_ALT = "|".join(sorted(_PA_NAME_CONTEXT, key=len, reverse=True))
_PA_NAME_RE = re.compile(
    rf"(?<![가-힣])(?:{_PA_NAME_SURNAME_ALT})[가-힣]{{1,2}}"
    rf"(?= ?(?:{_PA_NAME_CONTEXT_ALT}))"
)


def _PAvalid_name(token: str) -> bool:
    """성씨 사전에 다시 대조하고, 직함 자체나 흔한 낱말이 아닌지 본다.

    체크섬이 아니라 **재확인**이다 — `check` 는 `match.group(0)` 만 받으므로
    정규식이 성씨를 1글자로 골랐는지 2글자(복성)로 골랐는지 여기서 다시 가른다.
    복성이 더 기니 먼저 본다.
    """
    if token[:2] in _PA_SURNAMES_2 and len(token) - 2 in (1, 2):
        given = token[2:]
    elif token[:1] in _PA_SURNAMES_1 and len(token) - 1 in (1, 2):
        given = token[1:]
    else:
        return False
    if given in _PA_NAME_GIVEN_STOPWORDS:
        return False
    return token not in _PA_NAME_NOT_A_GIVEN


# 검출기 표 — (유형, 정규식, 검증 함수 또는 None). **표 순서가 곧 겹침 우선순위**다.
#
# **`(?<!\d)`/`(?!\d)` 로 감싸는 것이 중요하다.** 없으면 더 긴 숫자열의 일부가 걸려
# 한 자리 어긋난 좌표를 낸다 (계좌번호 안에서 카드번호를 찾는 식).
PADETECTORS: tuple = (
    ("rrn", re.compile(r"(?<![0-9])\d{6}\s?-\s?[1-8]\d{6}(?![0-9])"), _PAvalid_rrn),
    ("biz", re.compile(r"(?<![0-9])\d{3}-\d{2}-\d{5}(?![0-9])"), _PAvalid_biz),
    ("card", re.compile(r"(?<![0-9])(?:\d{4}[- ]){3}\d{4}(?![0-9])"), _PAvalid_card),
    (
        "phone",
        re.compile(
            r"(?<![0-9])(?:01[016789]|0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4]))"
            r"\s?-\s?\d{3,4}\s?-\s?\d{4}(?![0-9])"
        ),
        None,
    ),
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), None),
    ("driver_license", re.compile(r"(?<![0-9])\d{2}-\d{2}-\d{6}-\d{2}(?![0-9])"), None),
    ("passport", re.compile(r"(?<![0-9A-Za-z])[MSRODmsrod]\d{8}(?![0-9A-Za-z])"), None),
    ("name", _PA_NAME_RE, _PAvalid_name),
)

PADETECTOR_NAMES: tuple = tuple(name for name, _re, _check in PADETECTORS)

# `leak_count == 0` 을 "개인정보 없음" 으로 읽지 못하게 **안 보는 유형**도 함께 낸다.
# **`name` 은 2026-09-17 에 뺐다** — 완전 미탐에서 휴리스틱 검출로 바뀌었다(위 절).
PANOT_DETECTED: tuple = (
    {"category": "address", "reason": "주소는 일반 문장과 형태가 겹쳐 오탐이 미탐을 부른다."},
    {
        "category": "account",
        "reason": "계좌번호는 은행마다 자리수가 다르고 체크섬이 없어 일반 숫자열과 구분되지 않는다.",
    },
)


def PAscan_text(text: str) -> dict:
    """한 텍스트의 미마스킹 PII 를 찾는다. **값은 담지 않고 자리만** 낸다 (3.8절)."""
    body = _PADISPLAY_TAG_RE.sub("", text or "")
    found: list = []
    taken: list = []  # 이미 잡힌 구간 — 겹치는 검출을 두 번 세지 않는다

    for name, pattern, check in PADETECTORS:
        for match in pattern.finditer(body):
            if check is not None and not check(match.group(0)):
                continue
            start, end = match.span()
            # 겹침 배제: 카드번호로 잡힌 자리를 전화번호가 다시 잡는 식의 이중 계수를
            # 막는다. 앞선 검출기(체크섬이 있는 쪽)가 우선한다.
            if any(start < prev_end and prev_start < end for prev_start, prev_end in taken):
                continue
            taken.append((start, end))
            found.append({"category": name, "start": start, "end": end})

    found.sort(key=lambda item: item["start"])ㄴ
    return {
        "leak_count": len(found),
        "locations": found,
        "masked_count": len(_PAMASKED_RE.findall(body)),
    }


# =====================================================================================
# 감사 집계
# =====================================================================================

# 문서에서 본문을 찾을 키. 네 기능의 최종 산출 이름을 그대로 받는다 — 호출자가 응답을
# 옮겨 담으며 키를 바꾸지 않아도 되게 한다.
_PATEXT_KEYS = ("text", "answer", "result", "polished_text", "translated_text", "content")
_PAID_KEYS = ("id", "document_id", "doc_id", "session_id")


def _PAdocument_body(entry, index: int) -> tuple:
    """`(식별자, 본문, 사유)`. 본문 키가 하나도 없으면 사유를 돌려준다.

    **본문을 못 찾은 문서를 "유출 0건" 으로 세지 않는다.** 그렇게 세면 키 이름을
    한 번 잘못 준 감사가 **전건 통과**로 나오고, 그 상태는 오류도 경고도 없이
    "이번 주도 깨끗합니다" 로만 보인다 — 이 도구가 잡으려는 것과 정확히 같은 형태다.
    """
    if isinstance(entry, str):
        return index, entry, None
    if not isinstance(entry, dict):
        return index, "", "문서는 문자열이거나 객체여야 합니다."
    ident = index
    for key in _PAID_KEYS:
        if entry.get(key) is not None:
            ident = entry[key]
            break
    for key in _PATEXT_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return ident, value, None
    # 키는 있는데 빈 문자열인 것과, 키 자체가 없는 것을 가른다 — 앞은 "빈 산출물"
    # 이라 셀 것이 없는 정상이고, 뒤는 호출자가 잘못 넘긴 것이다.
    if any(key in entry for key in _PATEXT_KEYS):
        return ident, "", None
    return ident, "", "본문 키가 없습니다. " + "/".join(_PATEXT_KEYS) + " 중 하나가 필요합니다."


def _PAcoerce_documents(documents) -> list:
    """캔버스 변수로 온 JSON 문자열도 받는다.

    워크플로우 변수는 문자열로 오는 일이 흔하다. 문자열이면 JSON 으로 읽어 보고,
    실패하면 **문서 한 건의 본문**으로 본다 — 통째로 거부하면 "텍스트 하나만 훑어
    보려던" 호출이 이유 없이 막힌다.
    """
    if isinstance(documents, list):
        return documents
    if isinstance(documents, dict):
        return [documents]
    if isinstance(documents, str):
        stripped = documents.strip()
        if not stripped:
            raise PAToolError("EMPTY_DOCUMENTS")
        if stripped[0] in "[{":
            try:
                parsed = json.loads(stripped)
            except ValueError:
                return [documents]
            return parsed if isinstance(parsed, list) else [parsed]
        return [documents]
    raise PAToolError("BAD_DOCUMENTS")


def PAaudit(documents) -> dict:
    """결과 문서 묶음의 **미마스킹 개인정보 절대 건수**를 집계한다.

    Returns:
        `leak_count` 가 감사 값이고 **0 이어야 한다.** 나머지는 진단용이다.
        유출이 있는 문서만 `documents_with_leaks` 에 넣되 **상한을 두지 않는다** —
        상한을 두면 그 뒤의 유출이 리포트에서 사라지는데, 감사에서 그건 미탐과 같다.
    """
    rows = _PAcoerce_documents(documents)
    if not rows:
        raise PAToolError("EMPTY_DOCUMENTS")

    leaking: list = []
    unreadable: list = []
    by_category: dict = {}
    total = masked_total = scanned = 0

    for index, entry in enumerate(rows):
        ident, body, reason = _PAdocument_body(entry, index)
        if reason is not None:
            unreadable.append({"id": ident, "reason": reason})
            continue
        scanned += 1
        result = PAscan_text(body)
        masked_total += result["masked_count"]
        total += result["leak_count"]
        if not result["leak_count"]:
            continue
        for hit in result["locations"]:
            by_category[hit["category"]] = by_category.get(hit["category"], 0) + 1
        leaking.append(
            {
                "id": ident,
                "leak_count": result["leak_count"],
                # 값은 담지 않는다 (3.8절). 호출자는 자기가 넣은 텍스트를 갖고 있으므로
                # 이 좌표로 찾을 수 있고, 우리는 그 값을 옮기지 않는다.
                "locations": result["locations"],
            }
        )

    payload = {
        "ok": True,
        "documents": len(rows),
        "scanned": scanned,
        # 본문을 못 읽은 문서는 **분모에서 빼고 드러낸다.** 통과로도 유출로도 세지 않는다.
        "unreadable": unreadable,
        "leak_count": total,
        "documents_with_leaks": leaking,
        "leaking_document_count": len(leaking),
        "by_category": dict(sorted(by_category.items())),
        # `leak=0 · masked=0` 은 "개인정보가 없던 문서" 와 "아무것도 안 돌았다" 가
        # 구분되지 않는다. 그 둘을 가르라고 함께 낸다.
        "masked_count": masked_total,
        "detectors": list(PADETECTOR_NAMES),
        "not_detected": [dict(item) for item in PANOT_DETECTED],
    }

    if total:
        _PAlog.warning(
            "생성 문서에 마스킹되지 않은 개인정보가 있다",
            extra={
                "event": "pii_audit_leak_detected",
                "item_count": total,
                "status": " ".join(f"{k}={v}" for k, v in payload["by_category"].items()),
            },
        )
    else:
        _PAlog.info(
            "미마스킹 개인정보 없음",
            extra={"event": "pii_audit_clean", "item_count": scanned, "status": f"masked={masked_total}"},
        )
    if unreadable:
        _PAlog.warning(
            "본문을 읽지 못한 문서가 있어 감사 대상에서 빠졌다",
            extra={"event": "pii_audit_unreadable", "item_count": len(unreadable)},
        )
    return payload


# =====================================================================================
# 도구 본문 — 얇은 어댑터
# =====================================================================================

def _PAtool_audit(arguments: dict) -> dict:
    return PAaudit(arguments.get("documents"))


def _PAtool_scan(arguments: dict) -> dict:
    text = arguments.get("text")
    if not isinstance(text, str) or not text.strip():
        raise PAToolError("EMPTY_TEXT")
    result = PAscan_text(text)
    return {
        "ok": True,
        "leak_count": result["leak_count"],
        "locations": result["locations"],
        "masked_count": result["masked_count"],
        "detectors": list(PADETECTOR_NAMES),
        "not_detected": [dict(item) for item in PANOT_DETECTED],
    }


def _PAtool_detectors(arguments: dict) -> dict:
    return {
        "ok": True,
        "detectors": [
            {"category": name, "checksum": check is not None}
            for name, _pattern, check in PADETECTORS
        ],
        "not_detected": [dict(item) for item in PANOT_DETECTED],
    }


_PAHANDLERS = {
    "pii_audit": _PAtool_audit,
    "pii_scan_text": _PAtool_scan,
    "pii_detectors": _PAtool_detectors,
}


def PAcall_tool(name: str, arguments: dict) -> dict:
    handler = _PAHANDLERS.get(name)
    if handler is None:
        raise PAToolError("UNKNOWN_TOOL")
    return handler(arguments)


# =====================================================================================
# 로컬 단독 실행 대비: 런타임이 주입하는 전역 `mcp` 가 없으면 최소 shim 을 쓴다.
# =====================================================================================
try:
    mcp  # noqa: F821
except NameError:
    class _PALocalMCP:
        def tool(self, *args, **kwargs):
            def _decorator(fn):
                return fn
            return _decorator

    mcp = _PALocalMCP()
    _PAlog.info("로컬 테스트용 shim 사용", extra={"event": "mcp_shim_used"})


# ─────────────────────────────────────────────────────────────
# 디버그 에코 — **테스트 기간 한정** (2026-09-07)
# ─────────────────────────────────────────────────────────────
# 로그에는 3.8절대로 예외 **클래스명만** 남는다. 도구가 왜 죽었는지(어느 인자에서,
# 무슨 메시지로)는 어디에도 안 남아 원인 추적이 안 된다. 그 동안만 stderr 로 한 줄 더
# 뿜는다 — `print` 가 아니라 **`sys.stderr.write`** 다: stdout 은 MCP 의 전송 채널이라
# 한 줄만 섞여도 프로토콜이 깨진다(`check_deploy_contract` 가 그것을 본다).
# `GENON_DEBUG=0` 으로 끈다. 걷어낼 때는 이 블록과 `_padebug_echo` 호출만 지운다.
_PADEBUG_MAX_VALUE = 300


def _padebug_echo(message: str, *, event: str = "", **fields) -> None:
    if (os.environ.get("GENON_DEBUG") or "1").strip().lower() in {"0", "false", "off"}:
        return
    parts = [f"event={event}"] if event else []
    for key, value in fields.items():
        text = str(value)
        if len(text) > _PADEBUG_MAX_VALUE:
            text = f"{text[:_PADEBUG_MAX_VALUE]}…(+{len(text) - _PADEBUG_MAX_VALUE}자)"
        parts.append(f"{key}={text}")
    sys.stderr.write(f"[DEBUG {_PAlog.name}] {message} | {' '.join(parts)}\n")
    sys.stderr.flush()


def _pa_run(name: str, arguments: dict) -> str:
    """도구 본문을 부르고 JSON 문자열로 돌려준다.

    **입력 오류를 예외로 올리지 않는다** — MCP 도구가 예외로 죽으면 호출부에 오는 것은
    전송 실패와 구분되지 않는다. `ok=false` + `error_type` 으로 내려야 호출자가
    "재시도 무의미" 로 다룰 수 있다.
    """
    _padebug_echo(
        "도구 호출",
        event="mcp_tool_called",
        tool=name,
        arg_keys=",".join(sorted(arguments or {})),
    )
    try:
        result = PAcall_tool(name, arguments)
    except PAToolError as exc:
        _padebug_echo(
            "도구 입력 오류", event="mcp_tool_error", tool=name,
            error_type=exc.error_type, exc=repr(exc),
        )
        result = {"ok": False, "error_type": exc.error_type}
    except Exception as exc:  # noqa: BLE001 - 최종 방어선. 원문은 응답에 싣지 않는다 (3.8절)
        _padebug_echo(
            "도구 실행 실패", event="mcp_tool_failed", tool=name, exc=repr(exc)
        )
        _PAlog.warning("도구 실행 실패", extra={"event": "mcp_tool_failed", "error_type": type(exc).__name__})
        result = {"ok": False, "error_type": "TOOL_EXECUTION_FAILED"}
    return json.dumps(result, ensure_ascii=False)


# =====================================================================================
# MCP Tools
#
# GenOS 는 값이 없을 때 None 이 아니라 **빈 문자열("")** 을 주입한다. 그래서 문서 인자를
# `list` 로 선언하지 않는다 — `list` 로만 선언하면 MCP 가 본문 전에 타입 검증을 하다가
# `""` 에서 검증 에러를 내고, 그 실패는 전송 실패와 구분되지 않는다.
# =====================================================================================

try:  # pydantic 은 MCP 런타임(FastMCP)이 스키마를 만들 때 이미 쓰는 패키지다.
    from pydantic import Field as _PAPydanticField
except Exception:  # noqa: BLE001 - 없으면 설명 없이(맨 타입) 동작한다. 판정은 그대로다.
    _PAPydanticField = None


def _PAdocuments_arg() -> object:
    """문서 묶음 인자 주석 — **받아들이는 모양을 스키마 설명에 싣는다.**

    선택지(enum)를 만들 수 있는 인자가 아니라 설명만 붙인다. 본문 키 목록이 스키마에
    없으면 호출자가 자기 키 이름을 지어내고, 그러면 `unreadable` 로만 드러난다 —
    미리 알려 주는 편이 낫다.
    """
    text = (
        "감사할 결과 문서 묶음. 문자열 목록 또는 {id, text} 객체 목록"
        "(JSON 문자열도 받는다). 본문 키는 " + "/".join(_PATEXT_KEYS) + " 중 하나."
    )
    if _PAPydanticField is None:
        return object
    return Annotated[object, _PAPydanticField(description=text)]


_PADocumentsArg = _PAdocuments_arg()


@mcp.tool()
async def pii_audit(documents: _PADocumentsArg = "") -> str:
    """[언제 쓰나] 야간·주간처럼 **주기적으로** 생성 문서를 모아 개인정보 유출을 감사할 때.
    → 기능 응답마다 부르는 도구가 아니다. 모아 둔 결과 텍스트를 한 번에 넣는다.

    생성 문서(글다듬이·번역·FAQ·템플릿 채우기의 최종 산출물)에 **마스킹되지 않은
    개인정보가 몇 건 남아 있는지**를 절대 건수로 센다. 마스킹은 적재 전처리기의 몫인데
    그 층이 빠져도 오류가 나지 않으므로, 산출물 쪽에서 세는 것이 이 도구의 몫이다.

    **검출된 값은 응답에 담지 않는다** — 유형과 자리(start/end)만 낸다.

    Args:
        documents: 문자열 목록 또는 `[{"id": …, "text": …}]`. JSON 문자열도 받는다.

    Returns:
        JSON 문자열. `leak_count` 가 감사 값이고 **0 이어야 한다**.
        `by_category`(어느 유형이 샜나) · `documents_with_leaks`(어느 문서·어디인가) ·
        `masked_count`(마스킹이 돌기는 했나) · `detectors`/`not_detected`(무엇을 봤고
        무엇은 안 봤나) · `unreadable`(본문을 못 읽어 감사에서 빠진 문서).
    """
    return _pa_run("pii_audit", {"documents": documents})


@mcp.tool()
async def pii_scan_text(text: str = "") -> str:
    """[언제 쓰나] 문서 **한 건**을 즉석에서 확인할 때 (감사 결과를 눈으로 좇을 때).
    → 묶음 감사는 `pii_audit` 을 쓴다.

    Args: 
        text: 검사할 결과 텍스트.

    Returns:
        JSON 문자열 `{"ok": true, "leak_count": n, "locations": [{category,start,end}], …}`.
        **값은 담기지 않는다** (3.8절).
    """
    return _pa_run("pii_scan_text", {"text": text})


@mcp.tool()
async def pii_detectors() -> str:
    """[언제 쓰나] 감사 결과가 0건일 때 **그것이 무슨 뜻인지** 확인할 때.

    `leak_count == 0` 은 "개인정보가 없다" 가 아니라 "여기 적힌 유형이 없다" 는 뜻이다.
    검출하는 유형과 **검출하지 않는 유형(그 이유까지)** 을 함께 돌려준다.

    Returns:
        JSON 문자열 `{"ok": true, "detectors": [{category, checksum}], "not_detected": […]}`.
        `checksum: true` 인 유형은 검증식으로 오탐을 거른다.
    """
    return _pa_run("pii_detectors", {})
