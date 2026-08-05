"""SFR-006 오류 코드 중앙 관리.

GenOS 엔지니어 개발가이드 v1.02 3.9절 반영.
- 3.9.2절: 공통 코드는 00020001(통신 실패) / 00020002(실행 실패) / 00020003(그 외)
  세 개만 조합한다. 원인 구분은 error_type / user_msg 로 한다.
- 이 패키지는 두 영역에 걸친다:
  * run_chat.py (워크플로우 Python 단계) → 영역코드 02, data["error"] 객체로 반환
  * main.py (코드 서빙)                → 영역코드 03, HTTP 오류 응답으로 반환
- 3.8절: user_msg 에 내부 예외 원문/문서 내용을 절대 담지 않는다.
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


# ── 워크플로우(02) — run_chat.py ─────────────────────────────

ERR_CHAT_UPSTREAM_TIMEOUT = ErrorCode(
    code=f"{_WORKFLOW}-00020001",
    error_type="TEMPLATE_FILL_UPSTREAM_TIMEOUT",
    retryable=True,
    user_msg="응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
)

ERR_CHAT_UPSTREAM_EXECUTION = ErrorCode(
    code=f"{_WORKFLOW}-00020002",
    error_type="TEMPLATE_FILL_UPSTREAM_EXECUTION_FAILED",
    retryable=True,
    user_msg="입력 내용을 분석하지 못했습니다. 잠시 후 다시 시도해 주세요.",
)

ERR_CHAT_TEMPLATE_NOT_FOUND = ErrorCode(
    code=f"{_WORKFLOW}-00020003",
    error_type="TEMPLATE_FILL_TEMPLATE_NOT_FOUND",
    retryable=False,
    user_msg="템플릿을 찾을 수 없습니다. 관리자에게 템플릿 등록 여부를 확인해 주세요.",
)

ERR_CHAT_TEMPLATE_INVALID = ErrorCode(
    code=f"{_WORKFLOW}-00020003",
    error_type="TEMPLATE_FILL_TEMPLATE_INVALID",
    retryable=False,
    user_msg="템플릿 파일을 해석하지 못했습니다. hwpx 형식인지 확인해 주세요.",
)

ERR_CHAT_NO_FIELDS = ErrorCode(
    code=f"{_WORKFLOW}-00020003",
    error_type="TEMPLATE_FILL_NO_FIELDS",
    retryable=False,
    user_msg="템플릿에서 채울 수 있는 누름틀 필드를 찾지 못했습니다.",
)

ERR_CHAT_INTERNAL = ErrorCode(
    code=f"{_WORKFLOW}-00020003",
    error_type="TEMPLATE_FILL_INTERNAL_UNCLASSIFIED",
    retryable=False,
    user_msg="요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
)


# ── 코드 서빙(03) — main.py ──────────────────────────────────

ERR_API_INPUT = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="TEMPLATE_FILL_API_INPUT",
    retryable=False,
    user_msg="요청 형식이 올바르지 않습니다.",
    http_status=400,
)

ERR_API_TEMPLATE_NOT_FOUND = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="TEMPLATE_FILL_API_TEMPLATE_NOT_FOUND",
    retryable=False,
    user_msg="템플릿을 찾을 수 없습니다.",
    http_status=404,
)

ERR_API_SESSION_NOT_FOUND = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="TEMPLATE_FILL_API_SESSION_NOT_FOUND",
    retryable=False,
    user_msg="세션 정보를 찾을 수 없습니다. 대화를 먼저 진행해 주세요.",
    http_status=404,
)

ERR_API_INTERNAL = ErrorCode(
    code=f"{_SERVING}-00020002",
    error_type="TEMPLATE_FILL_API_INTERNAL",
    retryable=True,
    user_msg="문서 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.",
    http_status=500,
)

ERR_API_ADMIN_FORBIDDEN = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="TEMPLATE_FILL_API_ADMIN_FORBIDDEN",
    retryable=False,
    user_msg="템플릿 등록·삭제 권한이 없습니다.",
    http_status=403,
)

ERR_API_TEMPLATE_EXISTS = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="TEMPLATE_FILL_API_TEMPLATE_EXISTS",
    retryable=False,
    user_msg="같은 이름의 템플릿이 이미 있습니다. 덮어쓰려면 overwrite 를 지정해 주세요.",
    http_status=409,
)

# PDF 변환기는 이미지 빌드 옵션(INSTALL_LIBREOFFICE/INSTALL_RHWP, PDF SDK 포함 여부)에
# 따라 아예 없을 수 있다. "변환 수단이 없음"과 "변환 실패"는 대응이 달라 코드를 나눈다 —
# 전자는 재시도해도 소용없고(hwpx 로 받으면 된다), 후자는 재시도 가치가 있다.
ERR_API_PDF_UNAVAILABLE = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="TEMPLATE_FILL_API_PDF_UNAVAILABLE",
    retryable=False,
    user_msg="이 환경에서는 PDF 변환을 지원하지 않습니다. hwpx 로 내려받아 주세요.",
    http_status=501,
)

ERR_API_PDF_FAILED = ErrorCode(
    code=f"{_SERVING}-00020002",
    error_type="TEMPLATE_FILL_API_PDF_FAILED",
    retryable=True,
    user_msg="PDF 변환에 실패했습니다. 잠시 후 다시 시도하거나 hwpx 로 내려받아 주세요.",
    http_status=500,
)
