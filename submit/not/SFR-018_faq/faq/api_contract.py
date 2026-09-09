"""FAQ HTTP 계약 — 요청 스키마·업로드 읽기·오류 응답.

`main.py` 에서 갈라져 나왔다 (2026-08-11). 진입 파일에는 라우트와 배선만 남는다.
파일 본문 조립은 `formatting.rows_to_plain_text`, 인코딩·파일명은 `txt_output.py` 가 맡는다
(2026-08-12 전까지는 형식별 생성기를 고르는 `download_formats.py` 가 그 자리였다).

## 오류 응답 본문을 만드는 자리는 여기 하나다

`json_error` 가 `{error_code, msg}` 를 조립하는 **유일한 함수**다 (3.9.5절). 형식을 두 곳에서
만들면 한쪽만 바뀌어 호출자가 필드를 못 찾는다.

**로그는 여기서 한꺼번에 남기지 않는다.** 사건의 성격이 달라서다 — 입력 오류는 warning
(사용자가 고칠 수 있다), 내부 오류는 error(우리가 고쳐야 한다). 그래서 `error_response`
와 `internal_error` 로 갈라 두고, 응답 본문만 `json_error` 를 공유한다.

## 예외 원문은 응답에 싣지 않는다

`internal_error` 는 예외를 받지만 `error_type`(클래스 이름)만 로그에 남기고 응답에는
고정 안내문을 낸다 (3.8절). 스택이나 경로가 화면으로 새면 폐쇄망 내부 구조가 노출된다.
"""

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .error_codes import ERR_API_INTERNAL
from .logging_utils import log_error, log_warning


# ─────────────────────────────────────────────────────────────
# 요청 스키마
# ─────────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    markdown: str = Field(..., min_length=1, description="전처리기가 변환한 문서 본문")
    count: int = Field(0, ge=0, le=1000)  # 0 이면 기본 개수. 상한 검증은 generator 가 한다
    session_id: str = Field("", max_length=128)
    title: str = Field("", max_length=200)


class DownloadRequest(BaseModel):
    # 2026-08-12: 형식이 txt 하나가 되어 **필수에서 선택으로 바꿨다.** 화면이 형식을 고르지
    # 않아도 되지만, 옛 이름(hwpx/pdf/xlsx)으로 오는 요청은 라우트가 거절한다 —
    # 조용히 txt 를 내려주면 화면과 파일이 어긋난 채로 아무 기록도 남지 않는다.
    format: str = Field("txt", max_length=16, description="txt (비워도 txt)")
    session_id: str = Field("", max_length=128)
    # 세션 없이 화면이 들고 있는 항목을 그대로 보낼 수도 있다 (재생성 방지)
    items: list[dict] | None = None
    title: str = Field("", max_length=200)


# ─────────────────────────────────────────────────────────────
# 업로드 — **이 판본에는 없다** (2026-09-08)
# ─────────────────────────────────────────────────────────────
# `read_upload_capped(document, max_bytes)` 가 여기 있었다. 호출부가 `POST /generate/upload`
# 하나였고 그 라우트를 뺐으므로 **아무도 안 부르는 사본**이 된다 — 남겨 두면 `UploadFile`
# import 가 따라 남고, 나중에 이 판본을 정본과 대조할 때 "업로드가 되는 줄" 알게 된다.
# 정본(`onprem/`)에는 그대로 있다.


# ─────────────────────────────────────────────────────────────
# 오류 응답
# ─────────────────────────────────────────────────────────────
def json_error(error_code, msg: str = "") -> JSONResponse:
    """`{error_code, msg}` 응답 본문을 만드는 유일한 자리 (3.9.5절).

    형식을 두 곳에서 조립하면 한쪽만 바뀌어 호출자가 필드를 못 찾는 일이 생긴다.
    로그는 사건의 성격이 달라 호출부가 각자 남긴다 (입력 오류=warning, 내부 오류=error).
    """
    return JSONResponse(
        status_code=error_code.http_status,
        content={"error_code": error_code.code, "msg": msg or error_code.user_msg},
    )


def error_response(error_code, msg: str = "") -> JSONResponse:
    log_warning(
        "FAQ API 오류 응답",
        event="api_error",
        error_code=error_code.code,
        error_type=error_code.error_type,
        status=str(error_code.http_status),
    )
    return json_error(error_code, msg)


def internal_error(event: str, exc: Exception) -> JSONResponse:
    # 예외 원문은 응답에 싣지 않는다 — 고정 안내문만 나간다 (3.8절)
    log_error(
        "FAQ 처리 중 내부 오류",
        event=event,
        error_code=ERR_API_INTERNAL.code,
        error_type=type(exc).__name__,
    )
    return json_error(ERR_API_INTERNAL)
