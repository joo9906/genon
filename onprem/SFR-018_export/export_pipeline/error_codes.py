"""SFR-018 내보내기 오류 코드 중앙 관리.

GenOS 엔지니어 개발가이드 v1.02 3.9절 반영.
- 3.9.2절: 공통 코드는 00020001(통신 실패) / 00020002(실행 실패) / 00020003(그 외)
  세 개만 조합한다. 원인 구분은 error_type / user_msg 로 한다.
- 이 단위는 코드 서빙 하나뿐이므로 영역코드는 **03** 고정이다.
- 3.9.6절: 코드 서빙은 예외를 던지지 않고 오류 **객체**를 반환한다.
- 3.8절: user_msg 에 내부 예외 원문·문서 내용을 절대 담지 않는다.
"""

from dataclasses import dataclass

_SERVING = "03"  # 코드 서빙


@dataclass(frozen=True)
class ErrorCode:
    code: str
    error_type: str
    retryable: bool
    user_msg: str
    http_status: int = 500


ERR_INPUT = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="EXPORT_INPUT",
    retryable=False,
    user_msg="요청 형식이 올바르지 않습니다.",
    http_status=400,
)

ERR_FILE_EMPTY = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="EXPORT_FILE_EMPTY",
    retryable=False,
    user_msg="업로드한 파일이 비어 있습니다.",
    http_status=400,
)

ERR_FILE_TOO_LARGE = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="EXPORT_FILE_TOO_LARGE",
    retryable=False,
    user_msg="파일이 너무 큽니다. 20MB 이하 문서만 처리할 수 있습니다.",
    http_status=400,
)

ERR_UNSUPPORTED_FORMAT = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="EXPORT_UNSUPPORTED_FORMAT",
    retryable=False,
    user_msg="지원하지 않는 문서 형식입니다. hwpx, docx, pdf 파일을 올려 주세요.",
    http_status=400,
)

# hwpx 되쓰기는 원본이 hwpx 일 때만 성립한다. docx·pdf 는 되쓸 원본이 없다.
ERR_HWPX_ONLY = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="EXPORT_HWPX_ONLY",
    retryable=False,
    user_msg=(
        "hwpx 파일로 받으려면 원본도 hwpx 여야 합니다. "
        "docx·pdf 원본은 PDF 로 받아 주세요."
    ),
    http_status=400,
)

ERR_DOCUMENT_INVALID = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="EXPORT_DOCUMENT_INVALID",
    retryable=False,
    user_msg="문서를 해석하지 못했습니다. 파일이 손상되지 않았는지 확인해 주세요.",
    http_status=400,
)

# 대화에 쓴 원본과 다른 파일을 올린 경우. 그대로 되쓰면 엉뚱한 문단이 바뀐다.
ERR_FINGERPRINT_MISMATCH = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="EXPORT_FINGERPRINT_MISMATCH",
    retryable=False,
    user_msg="다듬기에 사용한 원본과 다른 파일입니다. 같은 문서를 올려 주세요.",
    http_status=400,
)

ERR_SESSION_NOT_FOUND = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="EXPORT_SESSION_NOT_FOUND",
    retryable=False,
    user_msg="세션 정보를 찾을 수 없습니다. 대화를 먼저 진행해 주세요.",
    http_status=404,
)

ERR_SESSION_SAVE = ErrorCode(
    code=f"{_SERVING}-00020002",
    error_type="EXPORT_SESSION_SAVE_FAILED",
    retryable=True,
    user_msg="작업 상태를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    http_status=500,
)

ERR_TOO_MANY_PARAGRAPHS = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="EXPORT_TOO_MANY_PARAGRAPHS",
    retryable=False,
    user_msg="문서가 너무 깁니다. 문서를 나누어 처리해 주세요.",
    http_status=400,
)

# 전처리기 변환기(rhwp/LibreOffice/PDF SDK)가 이 컨테이너에 없는 경우.
# 조용히 빈 PDF 를 주지 않고 원인을 알린다.
ERR_PDF_CONVERTER_MISSING = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="EXPORT_PDF_CONVERTER_MISSING",
    retryable=False,
    user_msg="이 환경에서는 PDF 변환을 사용할 수 없습니다. 관리자에게 문의해 주세요.",
    http_status=503,
)

ERR_PDF_CONVERSION_FAILED = ErrorCode(
    code=f"{_SERVING}-00020002",
    error_type="EXPORT_PDF_CONVERSION_FAILED",
    retryable=True,
    user_msg="PDF 변환에 실패했습니다. 잠시 후 다시 시도해 주세요.",
    http_status=500,
)

ERR_INTERNAL = ErrorCode(
    code=f"{_SERVING}-00020002",
    error_type="EXPORT_INTERNAL",
    retryable=True,
    user_msg="파일을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.",
    http_status=500,
)


def to_payload(error: ErrorCode) -> dict:
    """3.9.6절 오류 객체. 예외 원문·내부 경로는 담지 않는다."""
    return {
        "error": {
            "error_code": error.code,
            "msg": error.user_msg,
            "retryable": error.retryable,
        }
    }
