"""글다듬이(Text Polish) 오류 코드 중앙 관리.

GenOS 엔지니어 개발가이드 v1.02 3.9절 반영.
- 워크플로우 Python 단계이므로 영역 코드는 02 를 사용한다 (부록 A 기준).
- 3.9.2절: 00020001 / 00020002 / 00020003 세 개의 공통 코드만 조합해서 쓰고,
  임의로 새 숫자 코드를 만들지 않는다. 원인 구분은 error_type / user_msg로 한다.
- data["error"] 에는 error_code, msg, retryable 만 담고 내부 예외 원문(str(exc))은
  절대 포함하지 않는다 (3.8절, 3.9.6절).
"""

from dataclasses import dataclass

_AREA_CODE = "02"  # 워크플로우 Python 단계


@dataclass(frozen=True)
class ErrorCode:
    code: str
    error_type: str
    retryable: bool
    user_msg: str


# 00020001 — 외부 호출 자체가 실패 (Gateway 연결 실패 / timeout)
ERR_UPSTREAM_TIMEOUT = ErrorCode(
    code=f"{_AREA_CODE}-00020001",
    error_type="POLISH_UPSTREAM_TIMEOUT",
    retryable=True,
    user_msg="문장 다듬기 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
)

# 00020002 — 통신은 됐지만 응답이 실행 실패를 나타냄 (빈 응답 등)
ERR_UPSTREAM_EXECUTION = ErrorCode(
    code=f"{_AREA_CODE}-00020002",
    error_type="POLISH_UPSTREAM_EXECUTION_FAILED",
    retryable=True,
    user_msg="문장 다듬기 결과를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
)

# 00020003 — 그 외 전부 (입력 없음, 톤 값 오류, 내부 처리 실패)
ERR_INPUT_EMPTY = ErrorCode(
    code=f"{_AREA_CODE}-00020003",
    error_type="POLISH_INPUT_EMPTY",
    retryable=False,
    user_msg="다듬을 문서나 텍스트를 입력해 주세요.",
)

ERR_INTERNAL = ErrorCode(
    code=f"{_AREA_CODE}-00020003",
    error_type="POLISH_INTERNAL_UNCLASSIFIED",
    retryable=False,
    user_msg="요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
)
