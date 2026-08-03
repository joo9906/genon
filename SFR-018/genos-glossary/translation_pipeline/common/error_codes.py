"""오류 코드 중앙 관리.

GenOS 엔지니어 개발가이드 v1.02 3.9절 반영.
error_code는 {영역 코드}-{공통 오류 코드} 형식이며, 이 프로젝트는 코드 서빙
(영역 코드 03) 하나만 다루므로 여기 상수만 참조하면 된다.

각 모듈은 문자열을 직접 쓰지 않고 이 파일의 상수를 import해서 쓴다.
    from translation_pipeline.common.error_codes import ERR_INPUT, ERR_UPSTREAM_TIMEOUT

새 오류 유형이 필요해지면 이 파일에만 추가한다 (3.9.2절: 임의로 새 공통코드를
만들지 않고, 정해진 00020001/00020002/00020003만 조합해서 쓴다).
"""

from dataclasses import dataclass

_AREA_CODE = "03"  # 코드 서빙 (3.9.1절)


@dataclass(frozen=True)
class ErrorCode:
    code: str          # "{영역코드}-{공통코드}" — API 응답/로그에 그대로 사용
    error_type: str     # 내부 분류용 (3.9.6절) — 로그 grep, 통계용. 사용자에게 노출 안 함
    http_status: int    # 3.9.3절 기준 권장 상태코드
    user_msg: str        # 사용자 안내 문구 기본값


# 00020001 — 외부 API와 통신 자체가 실패 (연결 실패/timeout/502·503·504)
ERR_UPSTREAM_TIMEOUT = ErrorCode(
    code=f"{_AREA_CODE}-00020001",
    error_type="LLM_UPSTREAM_TIMEOUT",
    http_status=504,
    user_msg="외부 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
)

# 00020002 — 통신은 됐지만 응답 본문이 실행 실패를 나타냄
ERR_UPSTREAM_EXECUTION = ErrorCode(
    code=f"{_AREA_CODE}-00020002",
    error_type="LLM_UPSTREAM_EXECUTION_FAILED",
    http_status=502,
    user_msg="외부 서비스가 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
)

# 00020003 — 통신 오류가 아닌 나머지 전부 (입력 검증, 파싱, 내부 처리 실패 등)
# 3.9.2절: 입력 오류·인증 오류·리소스 없음 등에 별도 숫자코드를 새로 만들지 않고
# 전부 00020003으로 처리하며, error_type과 msg로 원인을 구분한다.
ERR_INPUT = ErrorCode(
    code=f"{_AREA_CODE}-00020003",
    error_type="TRANSLATION_INPUT_INVALID",
    http_status=400,
    user_msg="입력값을 확인해 주세요.",
)

ERR_RESPONSE_PARSE = ErrorCode(
    code=f"{_AREA_CODE}-00020003",
    error_type="LLM_RESPONSE_PARSE_FAILED",
    http_status=500,
    user_msg="요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
)

ERR_INTERNAL = ErrorCode(
    code=f"{_AREA_CODE}-00020003",
    error_type="INTERNAL_UNCLASSIFIED",
    http_status=500,
    user_msg="요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
)

# ------------------------------------------------------------------
# 용어사전(Weaviate/임베딩) 관련 — 기존 00020001/00020002 숫자코드를 재사용하고
# error_type만 분리한다 (3.9.2절). 이 오류들은 fail-open 정책상 HTTP 응답으로
# 사용자에게 나가지 않고, 내부 로그(log_warning) 식별용으로만 쓰인다.
# ------------------------------------------------------------------
ERR_GLOSSARY_UPSTREAM = ErrorCode(
    code=f"{_AREA_CODE}-00020001",
    error_type="GLOSSARY_UPSTREAM_TIMEOUT",
    http_status=504,
    user_msg="용어사전 조회가 지연되고 있습니다.",
)

ERR_GLOSSARY_EXECUTION = ErrorCode(
    code=f"{_AREA_CODE}-00020002",
    error_type="GLOSSARY_UPSTREAM_EXECUTION_FAILED",
    http_status=502,
    user_msg="용어사전 조회를 처리하지 못했습니다.",
)
