"""`ApiError` → HTTP 응답 변환 (코드 서빙 03 전용).

## 예외 하나로 모은 이유 (예전에는 튜플이었다)

헬퍼들은 원래 `(값, 오류응답)` 튜플을 돌려주고, 호출부마다 이렇게 받았다:

    context, error = await _load_editing_context(...)
    if error is not None:
        return error

엔드포인트가 12개인데 이런 헬퍼가 8개라, 같은 3줄이 열다섯 군데 반복됐다. 문제는 길이가
아니라 **빠뜨려도 조용하다는 것**이다. `if error` 를 한 번 빠뜨리면 `None` 인 값을 그대로
들고 진행해 엉뚱한 자리에서 터진다 — 사용자에게는 500 으로 보이고, 로그에는 진짜 원인
(템플릿 없음)이 남지 않는다.

`ApiError` 를 던지면 그 실수가 불가능해진다. 처리하지 않으면 핸들러까지 올라가 **원래
의도한 오류 코드 그대로** 응답이 된다. 오류를 무시하는 경로가 언어 차원에서 사라진다.

`ApiError` 자체는 **`error_codes.py` 에 있다** — 워크플로우(02)도 던지는데, 이 파일은
fastapi 를 import 하므로 그쪽이 끌어오면 안 된다 (이유는 `error_codes.ApiError` docstring).
"""

from fastapi import Request
from fastapi.responses import JSONResponse

from .error_codes import ApiError, ErrorCode
from .logging_utils import log_error, log_warning


def error_response(err: ErrorCode, msg: str | None = None) -> JSONResponse:
    """`{error_code, msg}` 형식의 오류 응답 (가이드 3.9.5).

    채팅 연계 시 `msg` 만 전달될 수 있으므로 **같은 코드를 내부 로그에도** 남긴다 —
    사용자 화면에 코드가 안 보여도 운영에서 추적할 수 있어야 한다.

    **레벨은 상태코드로 가른다** (2026-08-14). 그전에는 전부 `WARNING` 이었다 —
    잘못된 입력(4xx, 사용자가 고칠 일)과 내부 오류(5xx, 우리가 고칠 일)가 같은 레벨로
    섞였고, **운영이 `level >= ERROR` 로 내부 오류를 거르면 이 단위만 안 보였다.**
    018 세 단위는 내부 오류를 `log_error` 로 남긴다 — 같은 사건은 같은 레벨이어야 한다.
    """
    emit = log_error if err.http_status >= 500 else log_warning
    emit(
        "코드 서빙 오류 응답",
        event="api_error",
        error_code=err.code,
        error_type=err.error_type,
        status=str(err.http_status),
    )
    return JSONResponse(
        status_code=err.http_status,
        content={"error_code": err.code, "msg": msg or err.user_msg},
    )


def install(app) -> None:
    """앱에 `ApiError` 핸들러를 건다. `main.py` 가 기동 시 한 번 부른다."""

    @app.exception_handler(ApiError)
    async def _handle(_request: Request, exc: ApiError) -> JSONResponse:  # noqa: ANN202
        return error_response(exc.code, exc.msg)
