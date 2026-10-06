"""SFR-006 오류 코드 중앙 관리.

GenOS 엔지니어 개발가이드 v1.02 3.9절 반영.
- 3.9.2절: 공통 코드는 00020001(통신 실패) / 00020002(실행 실패) / 00020003(그 외)
  세 개만 조합한다. 원인 구분은 error_type / user_msg 로 한다.
- 이 패키지는 두 영역의 코드를 낸다:
  * chat_api.py(`/chat/*`, 워크플로우 스텝이 부른다) → 영역코드 02. 스텝이 응답을
    data["error"] 객체로 옮긴다
  * main.py(화면·다운로드가 부른다)                → 영역코드 03, HTTP 오류 응답
- 3.8절: user_msg 에 내부 예외 원문/문서 내용을 절대 담지 않는다.
- **코드 문자열은 `ERR-` 로 시작한다**: `ERR-<영역>-<공통코드>`.
  로그·응답에서 오류 코드를 눈으로 바로 가려내기 위한 접두어이고, 분류 판정은
  **뒤 8자리**로 한다 (`code.endswith("00020003")`) — 접두어는 그 판정과 무관하다.
"""

from dataclasses import dataclass

_WORKFLOW = "02"  # 워크플로우 Python 단계
_SERVING = "03"   # 코드 서빙


@dataclass(frozen=True)
class ErrorCode:
    code: str
    error_type: str
    retryable: bool
    user_msg: str
    http_status: int = 500


class ApiError(Exception):
    """사용자에게 그대로 보여줄 수 있는 오류. 진입 계층이 응답으로 바꾼다.

    **이 예외가 여기(의존성 0인 파일)에 있는 이유**: HTTP 를 모르는 조립·인프라
    계층(`chat_state`·`session_view`·`template_store`)도 던진다. HTTP 변환을 담당하는
    `api_errors.py` 에 두면 그 계층이 예외 하나 때문에 fastapi 에 묶인다.

    계약:
    - `code` 는 이 파일의 상수만 쓴다 (문자열 하드코딩 금지 — §5).
    - `msg` 는 **호출부가 작성한 고정 한국어 안내문**이거나 도메인 예외(`TemplateError` 등)가
      자기 파일 안에서 만든 문구다. 예외 원문·문서 내용·LLM 응답을 담지 않는다 (3.8절).
    - 생략하면 `ErrorCode.user_msg` 가 쓰인다.
    - HTTP 상태는 `ErrorCode.http_status` 가 정한다.
    """

    def __init__(self, code: ErrorCode, msg: str | None = None) -> None:
        super().__init__(msg or code.user_msg)
        self.code = code
        self.msg = msg or code.user_msg


# ── 워크플로우(02) — chat_api.py `/chat/*` ───────────────────

ERR_CHAT_UPSTREAM_TIMEOUT = ErrorCode(
    code=f"ERR-{_WORKFLOW}-00020001",
    error_type="TEMPLATE_FILL_UPSTREAM_TIMEOUT",
    retryable=True,
    user_msg="응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
)

ERR_CHAT_UPSTREAM_EXECUTION = ErrorCode(
    code=f"ERR-{_WORKFLOW}-00020002",
    error_type="TEMPLATE_FILL_UPSTREAM_EXECUTION_FAILED",
    retryable=True,
    user_msg="입력 내용을 분석하지 못했습니다. 잠시 후 다시 시도해 주세요.",
)

ERR_CHAT_TEMPLATE_NOT_FOUND = ErrorCode(
    code=f"ERR-{_WORKFLOW}-00020003",
    error_type="TEMPLATE_FILL_TEMPLATE_NOT_FOUND",
    retryable=False,
    user_msg="템플릿을 찾을 수 없습니다. 관리자에게 템플릿 등록 여부를 확인해 주세요.",
)

ERR_CHAT_TEMPLATE_INVALID = ErrorCode(
    code=f"ERR-{_WORKFLOW}-00020003",
    error_type="TEMPLATE_FILL_TEMPLATE_INVALID",
    retryable=False,
    user_msg="템플릿 파일을 해석하지 못했습니다. hwpx 형식인지 확인해 주세요.",
)

ERR_CHAT_NO_FIELDS = ErrorCode(
    code=f"ERR-{_WORKFLOW}-00020003",
    error_type="TEMPLATE_FILL_NO_FIELDS",
    retryable=False,
    user_msg="템플릿에서 채울 수 있는 항목(슬롯·누름틀)을 찾지 못했습니다.",
)

ERR_CHAT_INTERNAL = ErrorCode(
    code=f"ERR-{_WORKFLOW}-00020003",
    error_type="TEMPLATE_FILL_INTERNAL_UNCLASSIFIED",
    retryable=False,
    user_msg="요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
)

# Gateway 설정(`GENOS_URL`/`LLM_SERVING_ID`) 부재.
#
# `llm.py` 는 이 경우 `LlmResult(error_type="CONFIG_MISSING")` 를 돌려준다.
# `is_transport_error` 가 False 라 따로 가르지 않으면 `ERR_CHAT_UPSTREAM_EXECUTION`
# (00020002, retryable=True)에 뭉친다. **환경변수를 안 넣은 배포 실수**라 몇 번을 다시
# 눌러도 같은 자리에서 실패하므로 "잠시 후 다시 시도" 를 내면 안 되고, 로그의 error_type
# 도 LLM 실패와 달라야 원인이 드러난다. 018 세 단위와 같은 판단이다.
ERR_CHAT_CONFIG_MISSING = ErrorCode(
    code=f"ERR-{_WORKFLOW}-00020003",
    error_type="TEMPLATE_FILL_CONFIG_MISSING",
    retryable=False,
    user_msg="서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
)


# ── 코드 서빙(03) — main.py ──────────────────────────────────

ERR_API_INPUT = ErrorCode(
    code=f"ERR-{_SERVING}-00020003",
    error_type="TEMPLATE_FILL_API_INPUT",
    retryable=False,
    user_msg="요청 형식이 올바르지 않습니다.",
    http_status=400,
)

ERR_API_TEMPLATE_NOT_FOUND = ErrorCode(
    code=f"ERR-{_SERVING}-00020003",
    error_type="TEMPLATE_FILL_API_TEMPLATE_NOT_FOUND",
    retryable=False,
    user_msg="템플릿을 찾을 수 없습니다.",
    http_status=404,
)

ERR_API_SESSION_NOT_FOUND = ErrorCode(
    code=f"ERR-{_SERVING}-00020003",
    error_type="TEMPLATE_FILL_API_SESSION_NOT_FOUND",
    retryable=False,
    user_msg="세션 정보를 찾을 수 없습니다. 대화를 먼저 진행해 주세요.",
    http_status=404,
)

ERR_API_INTERNAL = ErrorCode(
    code=f"ERR-{_SERVING}-00020002",
    error_type="TEMPLATE_FILL_API_INTERNAL",
    retryable=True,
    user_msg="문서 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.",
    http_status=500,
)

ERR_API_ADMIN_FORBIDDEN = ErrorCode(
    code=f"ERR-{_SERVING}-00020003",
    error_type="TEMPLATE_FILL_API_ADMIN_FORBIDDEN",
    retryable=False,
    user_msg="템플릿 등록·삭제 권한이 없습니다.",
    http_status=403,
)

ERR_API_TEMPLATE_EXISTS = ErrorCode(
    code=f"ERR-{_SERVING}-00020003",
    error_type="TEMPLATE_FILL_API_TEMPLATE_EXISTS",
    retryable=False,
    user_msg="같은 이름의 템플릿이 이미 있습니다. 덮어쓰려면 overwrite 를 지정해 주세요.",
    http_status=409,
)
