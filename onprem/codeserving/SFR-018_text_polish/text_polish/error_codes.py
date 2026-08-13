"""글다듬이(Text Polish) 오류 코드 중앙 관리.

GenOS 엔지니어 개발가이드 v1.02 3.9절 반영.
- 3.9.2절: 00020001 / 00020002 / 00020003 세 개의 공통 코드만 조합해서 쓰고,
  임의로 새 숫자 코드를 만들지 않는다. 원인 구분은 error_type / user_msg로 한다.
- 응답에는 error_code, msg 만 담고 내부 예외 원문(str(exc))은 절대 포함하지 않는다
  (3.8절, 3.9.6절).

## 영역코드는 03 이다 (2026-08-13 정정)

이 파일은 오랫동안 `_AREA_CODE = "02"` 였고 "워크플로우 Python 단계이므로" 라고 적혀
있었다. **그 전제가 2026-08-11 영역 재배치로 없어졌다** — 글다듬이는 워크플로우(02)에서
코드 서빙(03)으로 옮겨졌고, 워크플로우 쪽 몫은
`onprem/workflow/sfr018_polish_0{1,2}.py` 두 스텝이 각자 `_AREA = "02"` 오류표를 들고
가져갔다. 즉 **02 를 내는 주체가 따로 생겼는데 서빙도 계속 02 를 내고 있었다.**

3.9.1 은 영역코드로 "어디서 난 오류인가"를 가른다. 서빙과 스텝이 같은 02 를 쓰면 로그에서
그 둘을 구분할 수 없다 — 번역·FAQ 서빙은 둘 다 03 이라 이 단위만 어긋나 있었다.

## `http_status` 를 코드가 들고 있는다 (2026-08-13)

그전에는 `_error_response(ERR_INPUT_EMPTY, 400)` 처럼 **호출부가 상태코드를 손으로**
넘겼다. 같은 오류가 자리마다 다른 상태로 나갈 수 있는 형태이고, 실제로 `ERR_INPUT_EMPTY`
가 400 과 422 두 곳에서 쓰이고 있었다. 번역·FAQ 단위처럼 코드에 붙여 한 곳에서 정한다.
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
    code=f"{_AREA_CODE}-00020001",
    error_type="POLISH_UPSTREAM_TIMEOUT",
    retryable=True,
    user_msg="문장 다듬기 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    http_status=504,
)

# 00020002 — 통신은 됐지만 응답이 실행 실패를 나타냄 (빈 응답 등)
ERR_UPSTREAM_EXECUTION = ErrorCode(
    code=f"{_AREA_CODE}-00020002",
    error_type="POLISH_UPSTREAM_EXECUTION_FAILED",
    retryable=True,
    user_msg="문장 다듬기 결과를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    http_status=502,
)

# 00020003 — 그 외 전부 (입력 없음, 상한 초과, 톤 값 오류, 내부 처리 실패)
ERR_INPUT_EMPTY = ErrorCode(
    code=f"{_AREA_CODE}-00020003",
    error_type="POLISH_INPUT_EMPTY",
    retryable=False,
    user_msg="다듬을 문서나 텍스트를 입력해 주세요.",
    http_status=400,
)

# 상한 초과. **`ERR_INPUT_EMPTY` 를 재활용하지 않는다** (2026-08-13 분리).
# 그전에는 20만 자를 붙여 넣은 사용자가 "다듬을 문서나 텍스트를 입력해 주세요" 를 받았다 —
# 무엇을 하라는 건지 알 수 없는 안내였고, 로그의 error_type 도 `POLISH_INPUT_EMPTY` 라
# 운영에서 "빈 입력이 왜 이렇게 많나" 로 보였다. 두 사건은 사용자가 할 일이 반대다.
ERR_INPUT_TOO_LONG = ErrorCode(
    code=f"{_AREA_CODE}-00020003",
    error_type="POLISH_INPUT_TOO_LONG",
    retryable=False,
    user_msg="문서가 너무 깁니다. 나누어 요청해 주세요.",
    http_status=422,
)

ERR_INTERNAL = ErrorCode(
    code=f"{_AREA_CODE}-00020003",
    error_type="POLISH_INTERNAL_UNCLASSIFIED",
    retryable=False,
    user_msg="요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    http_status=500,
)
