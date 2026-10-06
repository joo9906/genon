"""SFR-018 FAQ 오류 코드 중앙 관리.

가이드 3.9절
- 3.9.2절: 공통 코드는 00020001(통신 실패) / 00020002(실행 실패) / 00020003(그 외)
  세 개만 조합한다. 원인 구분은 error_type / user_msg 로 한다.
- 이 패키지는 코드 서빙(영역코드 03)만 정의한다 — `main.py` 가 HTTP 오류 응답으로 낸다.
  워크플로우 스텝(영역코드 02, `final/workflow/sfr018_faq_0*.py`)은 파일 하나가 등록
  단위라 이 패키지를 import 하지 못하므로 자기 오류표를 스텝 파일 안에 따로 둔다.
- 3.8절: user_msg 에 내부 예외 원문·문서 내용을 절대 담지 않는다.
- **코드 문자열은 `ERR-` 로 시작한다** (요구사항): `ERR-<영역>-<공통코드>`.
  로그·응답에서 오류 코드를 눈으로 바로 가려내기 위한 접두어이고, 분류 판정은
  **뒤 8자리**로 한다 (`code.endswith("00020003")`).
"""

from dataclasses import dataclass

_SERVING = "03"


@dataclass(frozen=True)
class ErrorCode:
    code: str
    error_type: str
    retryable: bool
    user_msg: str
    http_status: int = 500


# ── 코드 서빙(03) — main.py ──────────────────────────────────

ERR_API_INPUT = ErrorCode(
    code=f"ERR-{_SERVING}-00020003",
    error_type="FAQ_API_INPUT",
    retryable=False,
    user_msg="요청 형식이 올바르지 않습니다.",
    http_status=400,
)

ERR_API_SESSION_NOT_FOUND = ErrorCode(
    code=f"ERR-{_SERVING}-00020003",
    error_type="FAQ_API_SESSION_NOT_FOUND",
    retryable=False,
    user_msg="FAQ 정보를 찾을 수 없습니다. FAQ 를 먼저 생성해 주세요.",
    http_status=404,
)

ERR_API_UPSTREAM_TIMEOUT = ErrorCode(
    code=f"ERR-{_SERVING}-00020001",
    error_type="FAQ_API_UPSTREAM_TIMEOUT",
    retryable=True,
    user_msg="외부 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    http_status=504,
)

ERR_API_UPSTREAM_EXECUTION = ErrorCode(
    code=f"ERR-{_SERVING}-00020002",
    error_type="FAQ_API_UPSTREAM_EXECUTION_FAILED",
    retryable=True,
    user_msg="FAQ 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.",
    http_status=502,
)

# 통신·실행은 됐는데 **근거를 확인할 수 있는 항목이 하나도 없는** 경우
# (`generator.FAILURE_NO_GROUNDED`). 빈 목록을 성공으로 내려보내면 "FAQ 가 0개인 문서"
# 처럼 보인다.
#
# 실행 실패(502)와 가르는 이유: 두 사건은 사용자가 할 일이 다르다: 실행 실패는 "잠시 후 다시", 근거 미확보는 "이 문서로는
# 근거 있는 FAQ 가 안 나온다"(문서를 바꾸거나 개수를 줄이는 쪽이 맞다). 502 로 뭉뚱그리면
# 그 구분이 사라지고 기각 사유를 아무리 세어도 화면까지 오지 않는다.
ERR_API_NO_GROUNDED = ErrorCode(
    code=f"ERR-{_SERVING}-00020002",
    error_type="FAQ_API_NO_GROUNDED_ITEMS",
    retryable=True,
    user_msg="문서에서 근거를 확인할 수 있는 FAQ 를 만들지 못했습니다. 다시 시도해 주세요.",
    # 422 — 요청 형식은 맞지만 그 내용으로는 처리할 수 없다. 워크플로우 스텝이 이
    # 상태코드를 근거 미확보로 읽는다.
    http_status=422,
)

# 프롬프트 템플릿을 못 찾았다 (`generator.FAILURE_PROMPT`).
#
# **재시도로 풀리지 않는다.** 프롬프트(`final/SFR-018-faq/prompt/`)를 안 넣은 배포 실수라
# 몇 번을 불러도 같은 자리에서 실패한다. LLM 실패와 error_type 을 갈라야 로그에서
# 배포 구성 문제로 드러난다.
ERR_API_PROMPT_UNAVAILABLE = ErrorCode(
    code=f"ERR-{_SERVING}-00020003",
    error_type="FAQ_API_PROMPT_UNAVAILABLE",
    retryable=False,
    user_msg="요청을 처리하지 못했습니다. 관리자에게 문의해 주세요.",
    http_status=500,
)

# Gateway 설정(`GENOS_URL`/`LLM_SERVING_ID`) 부재 (`generator.FAILURE_CONFIG`).
#
# 프롬프트 부재와 **같은 성격**이다 — 환경을 안 채운 배포 실수라 재시도가 무의미하다.
# `LlmResult.is_transport_error` 가 False 여도 실행 실패(502)로 뭉치지 않는다.
ERR_API_CONFIG_UNAVAILABLE = ErrorCode(
    code=f"ERR-{_SERVING}-00020003",
    error_type="FAQ_API_CONFIG_UNAVAILABLE",
    retryable=False,
    user_msg="서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
    http_status=500,
)

ERR_API_INTERNAL = ErrorCode(
    code=f"ERR-{_SERVING}-00020003",
    error_type="FAQ_API_INTERNAL",
    retryable=False,
    user_msg="요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    http_status=500,
)

ERR_API_ADMIN_FORBIDDEN = ErrorCode(
    code=f"ERR-{_SERVING}-00020003",
    error_type="FAQ_API_ADMIN_FORBIDDEN",
    retryable=False,
    user_msg="권한이 없습니다.",
    http_status=403,
)
