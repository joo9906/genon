"""요청 스키마와 입력 검증 — "들어온 HTTP 요청을 믿을 수 있는 값으로 바꾸는" 층.

`main.py` 에서 갈라져 나왔다 (2026-08-11). 진입 파일이 배선만 남도록 **요청을 값으로
바꾸는 일**을 여기로 모았다. 여기서 나가는 값은 전부 검증·정규화가 끝난 것이고,
아래 계층(`document`·`session_view`·`template_store`)은 HTTP 를 모른다.

## 이 층의 규율

- **거절은 전부 `ApiError`** 로 올린다. `(값, 오류)` 튜플을 쓰지 않는다 — `if error: return`
  을 한 번 빠뜨리면 검증되지 않은 값이 조용히 아래로 내려간다.
- **안내문은 이 파일 안에서 쓴 고정 한국어 문구만** 담는다 (3.8절). 예외 원문을 그대로
  넣으면 내부 경로·스택이 사용자 화면으로 샌다.
- **상한은 전부 `Config`** 에서 읽는다. 여기에 숫자를 박으면 배포별로 못 바꾼다.
"""

import json

from fastapi import UploadFile
from pydantic import BaseModel, Field

from .api_errors import ApiError
from .config import Config
from .error_codes import ERR_API_ADMIN_FORBIDDEN, ERR_API_INPUT

# 다운로드 형식은 **hwpx 하나뿐이다** (2026-08-14 요구 변경 — pdf 를 걷어냈다).
# 목록과 검사를 남겨 두는 이유: 옛 클라이언트가 `format=pdf` 로 부르면 **400 으로
# 거절해야** 한다. 조용히 hwpx 를 내려주면 화면은 PDF 를 받았다고 믿는데 파일은
# hwpx 인 상태가 되고, 그 어긋남은 아무 기록도 남기지 않는다.
# (FAQ 가 옛 형식 이름 xlsx/pdf/hwpx 를 400 으로 거절하는 것과 같은 판단이다.)
DOCUMENT_FORMATS = ("hwpx",)


# ─────────────────────────────────────────────────────────────
# 요청 스키마
# ─────────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    template_id: str | None = Field(None, max_length=256)
    session_id: str | None = Field(None, max_length=256)
    # 세션 없이 값 직접 지정도 허용 (테스트/단발 호출). 세션 값 위에 덮어쓴다.
    values: dict[str, str] | None = None
    filename: str | None = Field(None, max_length=128)
    # hwpx 만 받는다. 생략이 기본이고, 다른 값은 400 이다(위 `DOCUMENT_FORMATS` 주석).
    format: str | None = Field(None, max_length=8)
    # 템플릿 항목 밖에 이어 쓸 본문. 생략하면 **세션에 쌓인 것**을 쓴다.
    blocks: list | None = None


class ValuePatchRequest(BaseModel):
    session_id: str = Field(..., max_length=256)
    template_id: str | None = Field(None, max_length=256)
    values: dict[str, str] = Field(default_factory=dict)
    # 응답에 채운 결과 마크다운을 포함할지 (연속 편집이면 끄는 편이 가볍다)
    preview: bool = True


class ValueDeleteRequest(BaseModel):
    session_id: str = Field(..., max_length=256)
    template_id: str | None = Field(None, max_length=256)
    fields: list[str] = Field(default_factory=list)
    preview: bool = True


class BlockPutRequest(BaseModel):
    session_id: str = Field(..., max_length=256)
    template_id: str | None = Field(None, max_length=256)
    # 전체 목록을 그대로 받는다 (부분 갱신이 아니다) — 이유는 PUT /blocks docstring 참고
    blocks: list = Field(default_factory=list)
    preview: bool = True


# ─────────────────────────────────────────────────────────────
# 검증·정규화
# ─────────────────────────────────────────────────────────────
def require_admin(token: str | None) -> None:
    """관리자 토큰 검사. 토큰이 설정돼 있지 않으면 검사하지 않는다(기동 시 경고를 남긴다)."""
    if not Config.ADMIN_TOKEN:
        return
    if (token or "").strip() != Config.ADMIN_TOKEN:
        raise ApiError(ERR_API_ADMIN_FORBIDDEN)


def resolve_format(raw: str | None) -> str:
    fmt = (raw or "hwpx").strip().lower()
    if fmt not in DOCUMENT_FORMATS:
        raise ApiError(ERR_API_INPUT, "지금은 hwpx 로만 내려받을 수 있습니다.")
    return fmt


def normalize_values(raw: dict) -> dict:
    return {str(k): str(v)[: Config.MAX_VALUE_CHARS] for k, v in (raw or {}).items()}


def check_value_count(values) -> None:
    if values and len(values) > Config.MAX_FIELDS:
        raise ApiError(
            ERR_API_INPUT, f"values 개수가 상한({Config.MAX_FIELDS}건)을 초과했습니다."
        )


def parse_json_form(raw: str, field_name: str, expected: type):
    """multipart 폼으로 온 JSON 문자열을 파싱한다 (형식이 다르면 400)."""
    shape = "객체" if expected is dict else "배열"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(ERR_API_INPUT, f"{field_name} 는 JSON {shape}이어야 합니다.") from exc
    if not isinstance(parsed, expected):
        raise ApiError(ERR_API_INPUT, f"{field_name} 는 JSON {shape}이어야 합니다.")
    return parsed


# 업로드를 나눠 읽는 단위. 상한 판정을 위한 것이므로 값 자체에 의미는 없다 —
# 너무 작으면 왕복이 늘고, 너무 크면 상한을 넘긴 뒤에야 멈춘다.
_UPLOAD_CHUNK_BYTES = 1024 * 1024


async def read_upload(template: UploadFile) -> bytes:
    """업로드 파일을 읽고 형식·크기를 검증한다 (등록·즉석 생성 공용).

    **상한 검사를 다 읽기 전에 한다** (2026-08-11). 예전에는 `await template.read()` 로
    전량을 받은 **뒤** 크기를 봤다. `UploadFile` 이 디스크로 spool 하므로 OOM 은 아니지만,
    상한이 20MB 여도 1GB 짜리를 보내면 **1GB 를 다 받아 디스크에 쓴 뒤** 거절했다 —
    상한이 거부 조건일 뿐 자원 한도로는 작동하지 않았다는 뜻이다.

    청크로 읽으며 누적 크기가 상한을 넘는 즉시 멈춘다. 넘긴 요청이 쓰는 디스크는
    상한 + 청크 하나로 묶인다.
    """
    name = (template.filename or "").strip()
    if not name.lower().endswith(".hwpx"):
        raise ApiError(ERR_API_INPUT, "hwpx 파일만 업로드할 수 있습니다.")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await template.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        # 전량을 메모리에서 XML 파싱하므로 상한이 필요하다
        if total > Config.MAX_UPLOAD_BYTES:
            raise ApiError(
                ERR_API_INPUT,
                f"파일 크기가 상한({Config.MAX_UPLOAD_BYTES // (1024 * 1024)}MB)을 초과했습니다.",
            )
        chunks.append(chunk)
    if not total:
        raise ApiError(ERR_API_INPUT, "업로드한 파일이 비어 있습니다.")
    return b"".join(chunks)
