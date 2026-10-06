"""글다듬이(Text Polish) 오류 코드 중앙 관리.

GenOS 엔지니어 개발가이드 v1.02 3.9절 반영.
- 3.9.2절: 00020001 / 00020002 / 00020003 세 개의 공통 코드만 조합해서 쓰고,
  임의로 새 숫자 코드를 만들지 않는다. 원인 구분은 error_type / user_msg로 한다.
- 응답에는 error_code, msg 만 담고 내부 예외 원문(str(exc))은 절대 포함하지 않는다
  (3.8절, 3.9.6절).

## 영역코드는 03 이다

3.9.1 은 영역코드로 "어디서 난 오류인가" 를 가른다. 이 단위는 코드 서빙(03)이고,
워크플로우 스텝(`final/workflow/sfr018_polish_0{1,2}_*.py`)은 각자 02 오류표를 든다 —
둘이 같은 영역코드를 쓰면 로그에서 서빙 오류와 스텝 오류를 구분할 수 없다.
번역·FAQ 서빙도 03 이다.

## `http_status` 를 코드가 들고 있는다

호출부가 상태코드를 손으로 넘기면 같은 오류가 자리마다 다른 상태로 나갈 수 있다.
번역·FAQ 단위처럼 코드에 붙여 한 곳에서 정한다.

## 코드 문자열은 `ERR-` 로 시작한다

`ERR-<영역>-<공통코드>`. 로그·응답에서 오류 코드를 눈으로 바로 가려내기 위한 접두어이고,
분류 판정은 **뒤 8자리**로 한다 (`code.endswith("00020003")`).
"""

from dataclasses import dataclass

_AREA_CODE = "03"  # 코드 서빙 (3.9.1절)


@dataclass(frozen=True)
class ErrorCode:
    code: str
    error_type: str
    retryable: bool
    user_msg: str
    http_status: int = 500


# 00020001 — 외부 호출 자체가 실패 (Gateway 연결 실패 / timeout)
ERR_UPSTREAM_TIMEOUT = ErrorCode(
    code=f"ERR-{_AREA_CODE}-00020001",
    error_type="POLISH_UPSTREAM_TIMEOUT",
    retryable=True,
    user_msg="문장 다듬기 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    http_status=504,
)

# 00020002 — 통신은 됐지만 응답이 실행 실패를 나타냄 (빈 응답 등)
ERR_UPSTREAM_EXECUTION = ErrorCode(
    code=f"ERR-{_AREA_CODE}-00020002",
    error_type="POLISH_UPSTREAM_EXECUTION_FAILED",
    retryable=True,
    user_msg="문장 다듬기 결과를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    http_status=502,
)

# 00020003 — 그 외 전부 (입력 없음, 상한 초과, 톤 값 오류, 내부 처리 실패)
ERR_INPUT_EMPTY = ErrorCode(
    code=f"ERR-{_AREA_CODE}-00020003",
    error_type="POLISH_INPUT_EMPTY",
    retryable=False,
    user_msg="다듬을 문서나 텍스트를 입력해 주세요.",
    http_status=400,
)

# 상한 초과. **`ERR_INPUT_EMPTY` 를 재활용하지 않는다** — 두 사건은 사용자가 할 일이
# 반대이고, 같은 error_type 으로 남기면 운영에서 "빈 입력이 왜 이렇게 많나" 로 보인다.
ERR_INPUT_TOO_LONG = ErrorCode(
    code=f"ERR-{_AREA_CODE}-00020003",
    error_type="POLISH_INPUT_TOO_LONG",
    retryable=False,
    user_msg="문서가 너무 깁니다. 나누어 요청해 주세요.",
    http_status=422,
)

ERR_INTERNAL = ErrorCode(
    code=f"ERR-{_AREA_CODE}-00020003",
    error_type="POLISH_INTERNAL_UNCLASSIFIED",
    retryable=False,
    user_msg="요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    http_status=500,
)

# Gateway 설정(`GENOS_URL`/`LLM_SERVING_ID`) 부재. **재시도로 풀리지 않는다.**
#
# `ERR_INTERNAL`("잠시 후 다시 시도해 주세요")로 내보내면 사용자는 같은 자리에서 계속
# 실패하고, 로그에서도 **환경변수를 안 넣은 배포 실수라는 사실이 드러나지 않는다.**
# `llm.py` 가 `CONFIG_MISSING` 을 `LlmResult` 로 돌려주고 라우트가 이 코드로 옮긴다.
# FAQ 의 프롬프트 부재(`ERR_API_PROMPT_UNAVAILABLE`)·번역의 설정 부재와 같은 판단이다.
ERR_CONFIG_MISSING = ErrorCode(
    code=f"ERR-{_AREA_CODE}-00020003",
    error_type="POLISH_CONFIG_MISSING",
    retryable=False,
    user_msg="서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
    http_status=500,
)
