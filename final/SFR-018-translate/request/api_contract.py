"""번역 HTTP 계약 — 요청 스키마·응답 모양.

라우트·배선은 `main.py` 에 남고 계약은 이 파일에 있다.

## 왜 요청과 응답을 한 파일에 뒀나 (006 은 둘로 갈랐는데)

006 은 값→**파일**(hwpx 조립·PDF 변환·헤더 10종)이 따로 무거워 `api_download.py` 가
자기 몫을 한다. 번역은 **문서를 만들지 않는다**(요구사항 §3) — 응답은 JSON 이고
`markdown_payload` 한 함수뿐이라, 나누면 파일만 늘고 경계는 안 생긴다.

md 내려받기도 이 판단 안에 있다. 그 경로가 하는 일은 **요청 스키마 하나와 인코딩
한 줄**이고, 인코딩·파일명 규약은 이미 `translation_pipeline/common/md_output.py`
에 따로 있다.

## 여기 있는 것이 지키는 계약

- **응답 모양은 `markdown_payload` 한 벌이다.** 경로마다 필드를 고르면 화면이 경로마다
  다른 것을 읽어 같은 기능이 두 벌로 갈린다.
- **오류 응답은 `{error_code, msg}`** (3.9.5절)이고 같은 코드를 로그에도 남긴다 —
  채팅 연계 시 사용자에게는 `msg` 만 가므로, 로그에 코드가 없으면 어느 요청이었는지
  나중에 맞춰볼 수 없다.
- **사용자 노출 문구는 고정 안내문만** (3.8절). 예외 원문은 `error_type` 으로 로그에만.
"""

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from translation_pipeline.common.error_codes import ERR_INPUT, ERR_INTERNAL
from translation_pipeline.common.logging_utils import log_error, log_warning


# ─────────────────────────────────────────────────────────────
# 요청 스키마
# ─────────────────────────────────────────────────────────────
class TranslateMarkdownRequest(BaseModel):
    markdown: str = Field(..., min_length=1, description="전처리기가 변환한 마크다운/HTML 본문")
    target_lang: str = Field(..., min_length=1, max_length=32)
    source_lang: str = Field("", max_length=32)
    register: str = Field("", max_length=32)
    # 내려받을 파일 이름에 쓴다. 결과를 만들 때 파일까지 굳혀 올리므로 제목이 이
    # 요청에 있어야 한다.
    title: str = Field("", max_length=200, description="파일명에 쓸 제목")
    # false 면 결과 md 를 올리지 않는다 — 캔버스 스텝은 안내 판정 뒤 `POST /upload` 로 올린다.
    upload: bool = Field(True, description="결과 md 를 올리고 download_url 을 낼지")


class TranslateStreamRequest(BaseModel):
    """`POST /translate/stream`.

    본문은 `TranslateMarkdownRequest` 와 같다(제목만 없다 — 파일은 finalize 가 굳힌다).
    같은 모양으로 두는 것이 요점이다: 프론트가 스트리밍을 쓸지 말지를 **엔드포인트만
    바꿔서** 정할 수 있어야 하고, 필드가 갈리면 그 전환이 코드 변경이 된다.
    """

    markdown: str = Field(..., min_length=1, description="전처리기가 변환한 마크다운/HTML 본문")
    target_lang: str = Field(..., min_length=1, max_length=32)
    source_lang: str = Field("", max_length=32)
    register: str = Field("", max_length=32)


class TranslateFinalizeRequest(BaseModel):
    """`POST /translate/finalize` — 흘려보낸 뒤 **하이라이트 재료**를 받아 가는 요청.

    ## 왜 본문을 되돌려 받나 (상태를 두지 않는다)

    스트리밍이 끝나면 서빙은 그 결과를 들고 있지 않다. 세션에 넣어 두면 이 무상태 단위에
    상태가 생기고(Redis 의존 + TTL + 정리), 얻는 것은 요청 크기뿐이다. **용어 매칭은
    결정적**이라 같은 두 텍스트에서 같은 답이 나온다 — 그래서 프론트가 방금 받은 것을
    그대로 되돌려 보낸다.

    `translated_text` 는 **`done` 프레임이 준 문자열을 그대로** 보내는 것이 맞다. 프론트가
    델타를 이어 붙인 값과 서빙의 정본이 한 글자라도 다르면 좌표(`spans`)가 밀리고, 그
    어긋남은 **하이라이트가 한 칸 밀린 화면**으로만 드러난다.
    """

    original_text: str = Field(..., min_length=1, description="번역 전 원문 (스트리밍에 보낸 것)")
    translated_text: str = Field(..., min_length=1, description="`done` 프레임의 translated_text")
    target_lang: str = Field(..., min_length=1, max_length=32)
    source_lang: str = Field("", max_length=32)
    register: str = Field("", max_length=32)
    title: str = Field("", max_length=200, description="내려받기 파일명에 쓸 제목")
    # false 면 결과 md 를 올리지 않는다 — 캔버스 스텝은 안내 판정 뒤 `POST /upload` 로 올린다.
    upload: bool = Field(True, description="결과 md 를 올리고 download_url 을 낼지")


class UploadRequest(BaseModel):
    """`POST /upload` — 번역 정본에 안내문을 얹어 md 로 올린다.

    상태를 두지 않는 것은 `/download` 와 같다. 안내 판정은 스텝이 하고(숫자 가드 MCP 가
    서빙 뒤에 돈다), 파일 안 모양은 `md_output.with_disclaimer` 가 정한다.
    """

    text: str = Field("", description="올릴 본문 (번역 정본 — `<mark>` 사본이 아니다)")
    title: str = Field("", max_length=200, description="파일명에 쓸 제목")
    disclaimer: str = Field("", max_length=4000, description="파일 맨 위에 얹을 안내문")


class InputCheckRequest(BaseModel):
    """`POST /input/check` — 판단할 원문. 앞부분만 쓰므로 길이 상한을 따로 두지 않는다."""

    text: str = Field("", description="판단할 원문")


class DownloadRequest(BaseModel):
    """md 내려받기.

    **본문을 요청으로 받는다 — 세션에 저장하지 않는다.** 번역은 상태가 없는 단위이고
    (Redis 를 쓰지 않는다), 저장을 새로 붙이면 "화면의 번역문과 파일이 다를 수 있는"
    경로가 생긴다. 화면이 들고 있는 것을 그대로 보내면 그 어긋남이 원리적으로 없다.

    `text` 와 `markdown` 을 **둘 다 받는다** — 화면이 방금 받은 필드(`markdown`)를 그대로
    되돌려 보내도, 본문을 `text` 로 보내도 같은 파일이 내려간다.
    """

    text: str = Field("", description="내려받을 번역문 (또는 markdown 필드)")
    markdown: str = Field("", description="text 의 별칭 — 마크다운 경로 응답 필드 이름")
    title: str = Field("", max_length=200, description="파일명에 쓸 제목")

    def body(self) -> str:
        return self.text or self.markdown


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


def markdown_payload(artifacts, download_url: str = "") -> dict:
    """마크다운 경로 응답."""
    return {
        "markdown": artifacts.markdown,
        # 미리 굳혀 올린 md 링크. 올리지 못했으면 `None` — 결과는 그대로 나가고
        # 화면이 "파일로 받을 수 없다" 를 말할 수 있어야 한다.
        "download_url": download_url or None,
        # 화면 전용 사본 — 사전 용어에 `<mark>`(형광). **내려받기는 `markdown` 을 되돌려 보낸다**
        # (태그가 파일에 실리면 사용자가 파일에서 지워야 한다).
        "markdown_highlighted": artifacts.markdown_highlighted or artifacts.markdown,
        "source_markdown": artifacts.source_markdown,
        # 원문 사본 — 화면이 좌우로 놓고 비교하므로 **양쪽에** 칠한다. 사전이 안 걸린
        # 문서에서는 `source_markdown` 과 같다.
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
