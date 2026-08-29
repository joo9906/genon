"""번역 HTTP 계약 — 요청 스키마·업로드 읽기·응답 모양.

`main.py` 에서 갈라져 나왔다 (2026-08-11). 진입 파일에는 라우트와 배선만 남는다.

## 왜 요청과 응답을 한 파일에 뒀나 (006 은 둘로 갈랐는데)

006 은 값→**파일**(hwpx 조립·PDF 변환·헤더 10종)이 따로 무거워 `api_download.py` 가
자기 몫을 한다. 번역은 **문서를 만들지 않는다**(요구사항 §3) — 응답은 JSON 이고
`markdown_payload` 한 함수뿐이라, 나누면 파일만 늘고 경계는 안 생긴다.

txt 내려받기가 붙은 뒤에도(2026-08-12) 이 판단은 그대로다. 그 경로가 하는 일은
**요청 스키마 하나와 인코딩 한 줄**이고, 인코딩·파일명 규약은 이미
`translation_pipeline/common/txt_output.py` 에 따로 있다.

## 여기 있는 것이 지키는 계약

- **세 진입점이 같은 응답 모양을 쓴다.** `/translate/markdown`·`/translate/hwpx` 와
  전처리기 경로가 각자 필드를 고르면, 화면이 경로마다 다른 것을 읽어 같은 기능이
  두 벌로 갈린다. `markdown_payload` 가 그 한 벌이다.
- **오류 응답은 `{error_code, msg}`** (3.9.5절)이고 같은 코드를 로그에도 남긴다 —
  채팅 연계 시 사용자에게는 `msg` 만 가므로, 로그에 코드가 없으면 어느 요청이었는지
  나중에 맞춰볼 수 없다.
- **사용자 노출 문구는 고정 안내문만** (3.8절). 예외 원문은 `error_type` 으로 로그에만.
"""

from fastapi import UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from translation_pipeline.common.error_codes import ERR_INPUT, ERR_INTERNAL
from translation_pipeline.common.logging_utils import log_error, log_warning


# ─────────────────────────────────────────────────────────────
# 요청 스키마
# ─────────────────────────────────────────────────────────────
class TranslateRequest(BaseModel):
    nodes: list[dict] = Field(..., description="문서에서 추출한 노드 목록")
    target_lang: str = Field(..., min_length=1, max_length=32)
    # 비우면 원문에서 감지한다 (languages.detect — 결정적 스크립트 판정)
    source_lang: str = Field("", max_length=32)
    # 문어체(written) / 구어체(spoken). 비우면 문어체.
    register: str = Field("", max_length=32)


class TranslateMarkdownRequest(BaseModel):
    markdown: str = Field(..., min_length=1, description="전처리기가 변환한 마크다운/HTML 본문")
    target_lang: str = Field(..., min_length=1, max_length=32)
    source_lang: str = Field("", max_length=32)
    register: str = Field("", max_length=32)
    # 내려받을 파일 이름에 쓴다 (2026-08-28). 결과를 만들 때 파일까지 굳혀 올리므로
    # 제목이 이 요청에 있어야 한다 — 예전에는 `POST /download` 가 따로 받았다.
    title: str = Field("", max_length=200, description="파일명에 쓸 제목")


class DownloadRequest(BaseModel):
    """txt 내려받기 (2026-08-12 신규 — SFR-018 산출물이 txt 로 통일됐다).

    **본문을 요청으로 받는다 — 세션에 저장하지 않는다.** 번역은 상태가 없는 단위이고
    (Redis 를 쓰지 않는다), 저장을 새로 붙이면 "화면의 번역문과 파일이 다를 수 있는"
    경로가 생긴다. 화면이 들고 있는 것을 그대로 보내면 그 어긋남이 원리적으로 없다.

    `text` 와 `markdown` 을 **둘 다 받는 이유**: 번역 응답 필드 이름이 경로마다 다르다
    (`/translate` 는 `text`, `/translate/markdown`·`/translate/hwpx` 는 `markdown`).
    화면이 방금 받은 필드를 그대로 되돌려 보낼 수 있어야 이름을 옮겨 적는 층이 생기지
    않는다 — 그 층에서 빈 문자열을 보내면 빈 파일이 내려간다.
    """

    text: str = Field("", description="내려받을 번역문 (또는 markdown 필드)")
    markdown: str = Field("", description="text 의 별칭 — 마크다운 경로 응답 필드 이름")
    title: str = Field("", max_length=200, description="파일명에 쓸 제목")

    def body(self) -> str:
        return self.text or self.markdown


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
# 응답
# ─────────────────────────────────────────────────────────────
def input_error_response(msg: str) -> JSONResponse:
    # 3.9.5절: 채팅 연계 시 msg 만 전달될 수 있으니 내부 로그에도 같은 코드를 남긴다
    log_warning(
        "번역 입력 오류 응답",
        event="api_input_error",
        error_code=ERR_INPUT.code,
        error_type=ERR_INPUT.error_type,
        status=str(ERR_INPUT.http_status),
    )
    return JSONResponse(
        status_code=ERR_INPUT.http_status,
        content={"error_code": ERR_INPUT.code, "msg": msg},
    )


def internal_error_response(event: str, exc: Exception) -> JSONResponse:
    log_error(
        "번역 처리 중 내부 오류",
        event=event,
        error_code=ERR_INTERNAL.code,
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=ERR_INTERNAL.http_status,
        content={"error_code": ERR_INTERNAL.code, "msg": ERR_INTERNAL.user_msg},
    )


def nodes_payload(artifacts) -> dict:
    """노드 경로(`POST /translate`) 응답.

    라우트에서 손으로 조립하던 것을 여기로 옮겼다(2026-08-14). 조립기가 한 곳에 있어야
    필드를 늘릴 때 **세 진입점이 같이 움직인다** — 이 파일 머리말이 계약으로 적어 둔 것이
    정작 이 경로에서만 지켜지지 않고 있었다.

    마크다운 경로와 다른 것은 본문 필드뿐이다: 여기는 `text`(번역문을 이어붙인 것),
    그쪽은 `markdown`(구조 보존) + `markdown_highlighted`(표시용 사본).
    노드 경로에는 원본 구조가 없어 하이라이트 사본을 만들 자리가 없다 —
    하이라이트가 필요하면 `glossary.hits[].target_spans` 와 `pairs` 를 쓴다.
    """
    return {
        "pairs": artifacts.pairs,
        "text": artifacts.text,
        "translation_error": artifacts.translation_error,
        "stats": artifacts.stats.as_payload(),
        "glossary": artifacts.glossary,
        "numeric_warnings": artifacts.numeric_warnings,
        "options": artifacts.options,
    }


def markdown_payload(artifacts, download_url: str = "") -> dict:
    """마크다운 경로 응답 — 세 진입점이 같은 형태를 쓴다.

    화면이 경로마다 다른 필드를 읽게 되면(업로드 번역 vs 전처리기 번역) 같은 기능이
    두 벌로 갈린다.
    """
    return {
        "markdown": artifacts.markdown,
        # 미리 굳혀 올린 txt 링크 (2026-08-28). 올리지 못했으면 `None` — 결과는 그대로
        # 나가고 화면이 "파일로 받을 수 없다" 를 말할 수 있어야 한다.
        "download_url": download_url or None,
        # 화면 전용 사본 — 사전 용어에 `<mark>`(형광). **내려받기는 `markdown` 을 되돌려 보낸다**
        # (태그가 파일에 실리면 사용자가 메모장에서 지워야 한다).
        "markdown_highlighted": artifacts.markdown_highlighted or artifacts.markdown,
        "source_markdown": artifacts.source_markdown,
        # 원문 사본 (2026-08-28) — 화면이 좌우로 놓고 비교하므로 **양쪽에** 칠한다.
        # 사전이 안 걸린 문서에서는 `source_markdown` 과 같다.
        "source_markdown_highlighted": (
            artifacts.source_markdown_highlighted or artifacts.source_markdown
        ),
        "pairs": artifacts.pairs,
        "translation_error": artifacts.translation_error,
        "stats": artifacts.stats.as_payload(),
        "glossary": artifacts.glossary,
        "numeric_warnings": artifacts.numeric_warnings,
        "options": artifacts.options,
    }
