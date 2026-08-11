"""FAQ HTTP 계약 — 요청 스키마·업로드 읽기·오류 응답.

`main.py` 에서 갈라져 나왔다 (2026-08-11). 진입 파일에는 라우트와 배선만 남는다.
형식별 파일 생성은 옆의 `download_formats.py` 가 맡는다.

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

from fastapi import UploadFile
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
    format: str = Field(..., description="hwpx | pdf | xlsx")
    session_id: str = Field("", max_length=128)
    # 세션 없이 화면이 들고 있는 항목을 그대로 보낼 수도 있다 (재생성 방지)
    items: list[dict] | None = None
    title: str = Field("", max_length=200)


# ─────────────────────────────────────────────────────────────
# 업로드
# ─────────────────────────────────────────────────────────────
# 업로드를 나눠 읽는 단위. 상한 판정을 위한 것이므로 값 자체에 의미는 없다.
_UPLOAD_CHUNK_BYTES = 1024 * 1024


async def read_upload_capped(document: UploadFile, max_bytes: int) -> bytes | None:
    """상한을 넘기면 **읽기를 멈추고** `None` 을 돌려준다 (2026-08-11).

    예전에는 `await document.read()` 로 전량을 받은 **뒤** 크기를 봤다. `UploadFile` 이
    디스크로 spool 하므로 OOM 은 아니지만, 상한이 20MB 여도 1GB 짜리를 보내면 1GB 를
    다 받아 디스크에 쓴 뒤 거절했다 — 상한이 자원 한도로 작동하지 않았다.

    빈 파일은 `b""` 로 돌아온다. 호출부가 `None`(상한 초과)과 falsy(빈 파일)를
    **다른 안내문**으로 가르므로 두 경우를 섞지 않는다.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await document.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


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
