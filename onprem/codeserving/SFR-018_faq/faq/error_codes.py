"""SFR-018 FAQ 오류 코드 중앙 관리.

가이드 3.9절
- 3.9.2절: 공통 코드는 00020001(통신 실패) / 00020002(실행 실패) / 00020003(그 외)
  세 개만 조합한다. 원인 구분은 error_type / user_msg 로 한다.
- 이 패키지는 두 영역에 걸친다 (SFR-006 과 같은 구성):
  * `run_chat.py` (워크플로우 Python 단계) → 영역코드 02, `data["error"]` 객체로 반환
  * `main.py` (코드 서빙)                 → 영역코드 03, HTTP 오류 응답으로 반환
- 3.8절: user_msg 에 내부 예외 원문·문서 내용을 절대 담지 않는다.
"""

from dataclasses import dataclass

_WORKFLOW = "02"
_SERVING = "03"


@dataclass(frozen=True)
class ErrorCode:
    code: str
    error_type: str
    retryable: bool
    user_msg: str
    http_status: int = 500


# ── 워크플로우(02) — run_chat.py ─────────────────────────────

ERR_CHAT_NO_INPUT = ErrorCode(
    code=f"{_WORKFLOW}-00020003",
    error_type="FAQ_NO_INPUT",
    retryable=False,
    user_msg="업로드된 문서를 찾을 수 없습니다. 문서를 첨부한 뒤 다시 시도해 주세요.",
)

ERR_CHAT_DOC_INVALID = ErrorCode(
    code=f"{_WORKFLOW}-00020003",
    error_type="FAQ_DOCUMENT_INVALID",
    retryable=False,
    user_msg="문서를 해석하지 못했습니다. hwpx·pdf·docx 파일인지 확인해 주세요.",
)

ERR_CHAT_COUNT_ZERO = ErrorCode(
    code=f"{_WORKFLOW}-00020003",
    error_type="FAQ_COUNT_ZERO",
    retryable=False,
    user_msg="생성할 FAQ 개수가 0으로 지정되어 있습니다. 1개 이상으로 골라 주세요.",
)

ERR_CHAT_UPSTREAM_TIMEOUT = ErrorCode(
    code=f"{_WORKFLOW}-00020001",
    error_type="FAQ_UPSTREAM_TIMEOUT",
    retryable=True,
    user_msg="응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
)

ERR_CHAT_UPSTREAM_EXECUTION = ErrorCode(
    code=f"{_WORKFLOW}-00020002",
    error_type="FAQ_UPSTREAM_EXECUTION_FAILED",
    retryable=True,
    user_msg="FAQ 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.",
)

# 스키마·근거 검증을 통과한 항목이 하나도 없는 경우. 통신은 됐지만 쓸 결과가 없다.
# 빈 목록을 성공으로 내려보내면 "FAQ 가 0개인 문서"처럼 보인다 (실패 침묵 처리 금지).
ERR_CHAT_NO_GROUNDED_ITEMS = ErrorCode(
    code=f"{_WORKFLOW}-00020002",
    error_type="FAQ_NO_GROUNDED_ITEMS",
    retryable=True,
    user_msg="문서에서 근거를 확인할 수 있는 FAQ 를 만들지 못했습니다. 다시 시도해 주세요.",
)

ERR_CHAT_INTERNAL = ErrorCode(
    code=f"{_WORKFLOW}-00020003",
    error_type="FAQ_INTERNAL_UNCLASSIFIED",
    retryable=False,
    user_msg="요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
)


# ── 코드 서빙(03) — main.py ──────────────────────────────────

ERR_API_INPUT = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="FAQ_API_INPUT",
    retryable=False,
    user_msg="요청 형식이 올바르지 않습니다.",
    http_status=400,
)

ERR_API_SESSION_NOT_FOUND = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="FAQ_API_SESSION_NOT_FOUND",
    retryable=False,
    user_msg="FAQ 정보를 찾을 수 없습니다. FAQ 를 먼저 생성해 주세요.",
    http_status=404,
)

ERR_API_UPSTREAM_TIMEOUT = ErrorCode(
    code=f"{_SERVING}-00020001",
    error_type="FAQ_API_UPSTREAM_TIMEOUT",
    retryable=True,
    user_msg="외부 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    http_status=504,
)

ERR_API_UPSTREAM_EXECUTION = ErrorCode(
    code=f"{_SERVING}-00020002",
    error_type="FAQ_API_UPSTREAM_EXECUTION_FAILED",
    retryable=True,
    user_msg="FAQ 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.",
    http_status=502,
)

ERR_API_INTERNAL = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="FAQ_API_INTERNAL",
    retryable=False,
    user_msg="요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    http_status=500,
)

ERR_API_ADMIN_FORBIDDEN = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="FAQ_API_ADMIN_FORBIDDEN",
    retryable=False,
    user_msg="권한이 없습니다.",
    http_status=403,
)

# 내보내기 형식별 가용성. **"수단 없음"과 "변환 실패"를 다른 코드로 구분한다** —
# 전자는 재시도해도 소용없고(다른 형식으로 받으면 된다), 후자는 재시도 가치가 있다
# (SFR-006 PDF 규약과 같다).
ERR_API_EXPORT_UNAVAILABLE = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="FAQ_API_EXPORT_UNAVAILABLE",
    retryable=False,
    user_msg="이 환경에서는 요청하신 형식으로 내려받을 수 없습니다. 다른 형식을 골라 주세요.",
    http_status=501,
)

ERR_API_EXPORT_FAILED = ErrorCode(
    code=f"{_SERVING}-00020002",
    error_type="FAQ_API_EXPORT_FAILED",
    retryable=True,
    user_msg="파일 생성에 실패했습니다. 잠시 후 다시 시도하거나 다른 형식을 골라 주세요.",
    http_status=500,
)
