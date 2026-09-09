"""Office 문서 번역 코드 서빙 진입점 (area 03).

엔드포인트
- GET  /health              : 헬스체크 (가이드 필수)
- GET  ""                   : 루트 — 게이트웨이가 경로 없이 베이스를 때리는 경우 대비
- GET  /languages           : 지원 언어·문체 목록 (화면이 선택지를 하드코딩하지 않게)
- GET  /glossary            : 용어사전 적재 상태
- POST /glossary/reload     : 용어사전 재적재 (관리자)
- POST /translate           : 문서에서 추출한 노드 목록 번역
- POST /translate/markdown  : 전처리기(docx/pdf→마크다운/HTML) 산출물 번역
- POST /translate/hwpx      : **hwpx 업로드 직접 파싱 후 번역** (전처리기 미경유)
- POST /download            : 번역문을 **txt 파일**로 내려주기 (2026-08-12 신규)

요구사항 반영
- 대상 언어 6개 + 문어체/구어체 선택, **한국어 축 쌍만** 허용 (languages.py).
- 원본과 번역본을 함께 돌려준다 (`source_markdown` / `pairs`) — UI 대조 표시용.
- 용어사전 하이라이트 데이터(`glossary.term_map`, `glossary.hits`)를 함께 싣는다.
- **문서 출력(hwpx/pdf)은 하지 않는다**(요구사항 §3). 나가는 파일은 **txt 하나**다
  (2026-08-12 — 사용자가 결과를 메모장에서 편집한다).

규약
- 입력 크기 상한(nodes 개수/총 문자수/업로드 바이트)으로 초대형 요청의 LLM 예산·메모리
  잠식을 막는다.
- `TranslationRequestError` 는 pipeline 에서 만든 고정 안내문만 담는다(외부 예외 미노출).
  그 외 모든 예외는 `ERR_INTERNAL.user_msg` 고정 문구만 노출한다(3.8절).
- 0.0.0.0:$PORT bind, 오류 응답 `{error_code, msg}` 형식(3.9.5절).
"""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

from api_contract import (
    DownloadRequest,
    TranslateFinalizeRequest,
    TranslateMarkdownRequest,
    TranslateRequest,
    TranslateStreamRequest,
    input_error_response as _input_error_response,
    internal_error_response as _internal_error_response,
    markdown_payload as _markdown_payload,
    nodes_payload as _nodes_payload,
    read_upload_capped as _read_upload_capped,
)
from config import Config
from translation_pipeline.common import file_store, prompt_library, glossary_store, txt_output
from translation_pipeline.common.error_codes import ERR_INPUT
from translation_pipeline.common.logging_utils import (
    configure_logging,
    log_info,
    log_warning,
)
from translation_pipeline.office.hwpx_text import HwpxParseError, to_markdown
from translation_pipeline.office.languages import (
    glossary_languages,
    supported_payload as supported_languages,
)
from translation_pipeline.office.pipeline import (
    TranslationRequestError,
    run_markdown_translation_job,
    run_translation_job,
)
from translation_pipeline.office import stream_pipeline
from translation_pipeline.office.registers import supported_payload as supported_registers

configure_logging(os.getenv("LOG_LEVEL", "INFO"))

async def _load_glossary() -> dict:
    """용어사전 적재 한 곳 — 기동과 `/glossary/reload` 가 같은 경로를 탄다.

    두 자리에서 각각 인자를 조립하면 한쪽만 고쳤을 때 **기동은 되는데 재적재만 다른
    드라이브를 보는** 상태가 된다. 조용히 틀리는 종류라 함수 하나로 묶었다.
    """
    return await glossary_store.load_from_admin_api(
        Config.glossary_api_url(),
        Config.glossary_drive_id(),
        Config.glossary_workspace_id(),
        Config.glossary_token(),
    )


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """용어사전 적재 + 관리자 토큰 부재 경고.

    적재 실패는 기동을 막지 않는다 — 용어사전은 품질 장치이고, 없다고 번역을 못 하는
    것은 아니다. 대신 상태를 `GET /glossary` 와 번역 응답에 노출한다.

    적재는 **admin-api 호출**이라 async 그대로 부른다 (2026-08-14 — 파일 시절에는
    blocking I/O 라 `to_thread` 로 넘겼다).

    `@app.on_event("startup")` 에서 옮겨왔다 (2026-08-11) — 그쪽은 deprecated 이고,
    requirements 에 FastAPI 상한이 없어 제거 시점을 통제할 수 없다.
    """
    await _load_glossary()
    if not Config.ADMIN_TOKEN:
        log_warning(
            "TRANSLATE_ADMIN_TOKEN 미설정 — 용어사전 재적재가 인증 없이 열려 있다",
            event="admin_token_missing",
            resource_id="glossary_admin",
            status="unprotected",
        )
    yield


app = FastAPI(title="office-translation-service", lifespan=_lifespan)



@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/")
@app.get("")
async def root() -> dict:
    """게이트웨이가 서빙 베이스를 경로 없이 때리는 배포가 있다 (운영 app.py 대조 결과).

    거기서 404 가 나면 배선이 잘못된 것처럼 보이므로 최소 정보를 돌려준다.

    **`""` 와 `"/"` 를 둘 다 등록해야 한다** (2026-08-11 수정) — `@app.get("")` 만으로는
    아무 경로에도 닿지 않는다. 근거는 006 `main.py` 의 같은 라우트 참고.
    """
    return {"service": "office-translation-service", "status": "ok"}


@app.get("/languages")
async def languages() -> dict:
    """지원 언어·문체 목록. **프론트는 이 응답만 보고 선택지를 그린다.**

    화면이 언어 목록을 따로 들고 있으면 언어를 늘리거나 용어사전 적용 범위가 바뀔 때
    한쪽만 고치게 되고, 그 상태는 예외를 내지 않고 **잘못된 안내**로만 드러난다.

    함께 알리는 제약 둘 — 어느 쪽도 화면이 추측할 수 없다:

    - `korean_axis_required`: 원문·대상 중 하나는 한국어여야 한다. 6×6 조합을 보여준 뒤
      400 을 받게 두지 않는다.
    - `glossary_languages` + 각 언어의 `glossary_supported`: 용어사전은 한국어·영어에만
      있다. 나머지 넷은 LLM 만으로 번역되며, 그 사실을 화면이 미리 말할 수 있어야
      "왜 이 언어만 용어가 안 지켜지나" 가 되지 않는다.
    """
    return {
        "languages": supported_languages(),
        "registers": supported_registers(),
        "korean_axis_required": True,
        "glossary_languages": glossary_languages(),
    }


@app.get("/glossary")
async def glossary_status() -> dict:
    return glossary_store.status()


@app.post("/glossary/reload")
async def glossary_reload(x_admin_token: str = Header("")):
    """용어사전을 **admin-api 에서 다시 받는다** (용어 등록·재인덱싱 후 재배포 없이 반영).

    관리 화면의 변경은 승인 결재를 거쳐 반영되므로, 승인이 끝난 뒤 이 경로를 한 번
    부르면 된다.

    **반환 타입 주석을 일부러 붙이지 않는다.** FastAPI 는 `Response` 서브클래스가 아닌
    반환 주석을 `response_model` 로 삼는데, `JSONResponse | dict` 같은 Union 은 응답
    모델을 만들지 못해 라우트 등록 단계에서 앱이 죽는다. 성공/오류로 형이 갈리는
    라우트는 이 저장소 세 단위 모두 주석 없이 둔다 (가이드 §I 타입힌트 권고보다
    기동 실패를 피하는 쪽이 우선이다).
    """
    if Config.ADMIN_TOKEN and x_admin_token != Config.ADMIN_TOKEN:
        return JSONResponse(
            status_code=403,
            content={"error_code": ERR_INPUT.code, "msg": "용어사전 재적재 권한이 없습니다."},
        )
    return await _load_glossary()


@app.post("/translate")
async def translate(body: TranslateRequest):
    """Office 문서에서 추출한 노드 목록을 번역한다.

    Returns:
        pairs: 노드별 원문/번역 쌍 (unit_id 포함 — 하이라이트 상세와 연결된다)
        text: 번역 결과를 이어붙인 전체 텍스트
        translation_error: 실패 시 사유 분류 문자열 (성공 시 빈 문자열)
        stats / glossary / numeric_warnings / options: 아래 마크다운 경로와 같은 의미
    """
    started = time.monotonic()
    if len(body.nodes) > Config.MAX_NODES:
        return _input_error_response(f"nodes 개수가 상한({Config.MAX_NODES}건)을 초과했습니다.")
    total_chars = sum(len(str(n.get("text", ""))) for n in body.nodes)
    if total_chars > Config.MAX_TOTAL_CHARS:
        return _input_error_response(
            f"총 텍스트 길이가 상한({Config.MAX_TOTAL_CHARS}자)을 초과했습니다."
        )

    try:
        artifacts = await run_translation_job(
            nodes=body.nodes,
            target_lang=body.target_lang,
            source_lang=body.source_lang,
            register=body.register,
        )
    except TranslationRequestError as exc:
        # 계약: 이 예외의 메시지는 pipeline.py 에서 우리가 만든 고정 안내문만 담는다.
        return _input_error_response(str(exc))
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
        return _internal_error_response("translate_internal_error", exc)

    log_info(
        "노드 번역 완료",
        event="translate_completed",
        item_count=len(artifacts.pairs),
        status=artifacts.translation_error or "ok",
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return _nodes_payload(artifacts)


async def _upload_result(markdown: str, title: str) -> str:
    """번역 정본을 txt 로 굳혀 올리고 링크를 돌려준다. 실패하면 빈 문자열.

    두 라우트(`/translate/markdown`·`/translate/hwpx`)가 같은 규칙을 쓰도록 한 곳에
    둔다 — 각자 조립하면 파일명 기본값이나 인코딩이 갈린다.
    """
    stem = txt_output.safe_stem(title, "번역결과")
    return await file_store.upload_bytes(
        txt_output.to_bytes(markdown),
        txt_output.download_filename(stem),
        txt_output.MEDIA_TYPE,
    )


@app.post("/translate/markdown")
async def translate_markdown(body: TranslateMarkdownRequest):
    """전처리기(docx/pdf → 마크다운/HTML) 산출물을 구조 보존 방식으로 번역한다.

    표 파이프·HTML 태그·제목·목록·코드펜스는 코드가 스켈레톤으로 보존하고 텍스트
    내용만 LLM 에 보낸다. 응답 markdown 의 구조는 입력과 항상 동일하다.

    Returns:
        markdown: 번역된 마크다운/HTML (구조 원본 동일)
        source_markdown: 원본 (UI 좌우 대조용 — 화면이 따로 들고 있지 않게)
        pairs: 유닛별 원문/번역 쌍 (검수·하이라이트용)
        translation_error: 실패 시 사유 분류 문자열 (성공 시 빈 문자열)
        stats: 유닛 수·폴백 발생률·중복 제거 건수 (018 fallback 지표의 원천)
        glossary: 용어사전 준수율 + 하이라이트 데이터(term_map / hits)
        numeric_warnings: 숫자 보존 검사에 걸린 유닛
        options: 실제로 적용된 언어·문체 (감지값·기본값 대체 여부 포함)
    """
    started = time.monotonic()
    if len(body.markdown) > Config.MAX_TOTAL_CHARS:
        return _input_error_response(
            f"총 텍스트 길이가 상한({Config.MAX_TOTAL_CHARS}자)을 초과했습니다."
        )

    try:
        artifacts = await run_markdown_translation_job(
            markdown=body.markdown,
            target_lang=body.target_lang,
            source_lang=body.source_lang,
            register=body.register,
        )
    except TranslationRequestError as exc:
        return _input_error_response(str(exc))
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
        return _internal_error_response("translate_markdown_internal_error", exc)

    log_info(
        "마크다운 번역 완료",
        event="translate_markdown_completed",
        item_count=len(artifacts.pairs),
        status=artifacts.translation_error or "ok",
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return _markdown_payload(artifacts, await _upload_result(artifacts.markdown, body.title))


@app.post("/translate/hwpx")
async def translate_hwpx(
    document: UploadFile = File(..., description="번역할 hwpx 파일"),
    target_lang: str = Form(...),
    source_lang: str = Form(""),
    register: str = Form(""),
    title: str = Form(""),
):
    """업로드한 hwpx 를 **직접 파싱**해 번역한다 (전처리기를 거치지 않는다).

    hwpx 를 전처리기에 태우면 표 안의 수치가 깨진다(요구사항 §5). 그래서 여기서는
    `hwpx_text.to_markdown` 이 원본 XML 의 `cellAddr` 좌표로 표 격자를 직접 만들고,
    그 마크다운이 `/translate/markdown` 과 **같은 스켈레톤 분해 경로**를 탄다.

    문서 출력은 하지 않는다 — 번역된 마크다운과 원본 마크다운만 돌려준다.
    """
    started = time.monotonic()
    raw = await _read_upload_capped(document, Config.MAX_UPLOAD_BYTES)
    if raw is None:
        return _input_error_response(
            f"파일 크기가 상한({Config.MAX_UPLOAD_BYTES // (1024 * 1024)}MB)을 초과했습니다."
        )
    if not raw:
        return _input_error_response("업로드된 파일이 비어 있습니다.")

    try:
        # zip 해제 + XML 파싱은 CPU/blocking 작업이라 이벤트 루프에서 직접 돌리지 않는다.
        #
        # **상한을 파서에 넘기지 않는다** (2026-08-31). `to_markdown` 의 `max_chars` 는
        # 넘는 만큼을 **조용히 잘라 버린다** — `HwpxDocument` 에 그 사실을 담는 필드가
        # 없어 응답에도 로그에도 흔적이 남지 않았다. 사용자는 뒷부분이 빠진 번역문을
        # 받고, 원문이 화면에 그대로 있으니 "왜 뒤가 안 됐나" 를 물을 자리도 없다.
        # 길이 판정은 아래에서 다른 세 경로와 **같은 방식**(초과는 오류)으로 한다.
        parsed = await asyncio.to_thread(to_markdown, raw)
    except HwpxParseError as exc:
        # 계약: 이 예외의 메시지는 hwpx_text.py 의 고정 안내문이다
        return _input_error_response(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _internal_error_response("translate_hwpx_parse_error", exc)

    if not parsed.markdown.strip():
        return _input_error_response("문서에서 번역할 텍스트를 찾지 못했습니다.")

    if len(parsed.markdown) > Config.MAX_TOTAL_CHARS:
        # 자르지 않고 세운다 — 나머지 세 경로(`/translate/nodes`·`/markdown`·`/download`)와
        # 같은 규약이다. 여기만 조용히 잘리면 같은 문서를 어느 경로로 넣었는지에 따라
        # 결과가 달라지고, 그 차이가 사용자에게 보이지 않는다.
        return _input_error_response(
            f"총 텍스트 길이가 상한({Config.MAX_TOTAL_CHARS}자)을 초과했습니다."
        )

    log_info(
        "hwpx 직접 파싱 완료",
        event="hwpx_parsed",
        item_count=parsed.paragraph_count,
        status=f"tables={parsed.table_count}",
    )

    try:
        artifacts = await run_markdown_translation_job(
            markdown=parsed.markdown,
            target_lang=target_lang,
            source_lang=source_lang,
            register=register,
        )
    except TranslationRequestError as exc:
        return _input_error_response(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _internal_error_response("translate_hwpx_internal_error", exc)

    log_info(
        "hwpx 번역 완료",
        event="translate_hwpx_completed",
        item_count=len(artifacts.pairs),
        status=artifacts.translation_error or "ok",
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    payload = _markdown_payload(artifacts, await _upload_result(artifacts.markdown, title))
    payload["source"] = {
        "paragraph_count": parsed.paragraph_count,
        "table_count": parsed.table_count,
    }
    return payload


@app.post("/download")
async def download(body: DownloadRequest):
    """번역문을 txt 파일로 내려준다 (2026-08-12 신규).

    ## 본문을 손대지 않는다

    받은 문자열을 **그대로** 파일로 만든다. 마크다운 표·HTML 표·머리글 기호를 평문으로
    풀지 않는다 — 그 구조는 **원본 문서에서 온 것**이고(전처리기 산출물), 번역의 계약은
    "구조는 입력과 동일" 이다. 여기서 표를 풀면 우리가 지키기로 한 그 구조를 마지막
    단계에서 우리 손으로 깨뜨리는 셈이 된다. 표를 사람이 읽을 형태로 바꾸는 일은
    사용자가 메모장에서 한다.

    (FAQ 는 반대다 — 거기서는 `**Q1.**`·`> 근거:` 를 **우리가** 붙인 장식이라 파일에서는
    떼어낸다. 기준은 "그 기호를 누가 넣었나" 다.)

    ## 상태를 두지 않는다

    세션 저장 없이 요청 본문을 받는다. 근거는 `api_contract.DownloadRequest` 머리말에 있다.
    """
    text = body.body()
    if not text.strip():
        return _input_error_response("내려받을 번역문이 없습니다.")
    if len(text) > Config.MAX_TOTAL_CHARS:
        return _input_error_response(
            f"총 텍스트 길이가 상한({Config.MAX_TOTAL_CHARS}자)을 초과했습니다."
        )

    stem = txt_output.safe_stem(body.title, "번역결과")
    data = txt_output.to_bytes(text)
    log_info(
        "번역문 txt 생성",
        event="download_completed",
        item_count=len(text.splitlines()),
        status=f"bytes={len(data)}",
    )
    return Response(
        content=data,
        media_type=txt_output.MEDIA_TYPE,
        headers=txt_output.headers(stem),
    )


if __name__ == "__main__":
    # 가이드 6.2: Python 코드 서빙은 저장소 루트의 main.py 가 있으면 그 파일을 먼저 실행한다.
    # 이 블록이 없으면 자동 실행 경로에서 모듈만 로드되고 서버가 뜨지 않는다.
    # 시작 (Run) 커맨드를 따로 등록하면 그쪽이 우선한다.
    # PORT 는 GenOS 가 주입하며 기본값 8080 이다 (가이드 6.3).
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


@app.get("/prompts")
async def prompts() -> dict:
    """프롬프트를 **어디서 받았는지** (2026-09-03).

    관리자가 프롬프트 라이브러리에서 문구를 고쳤는데 반영이 안 될 때 답할 자리다. 이 값이
    없으면 "ID 를 안 넣었다"(`configured: false`)와 "넣었는데 못 읽었다"
    (`reason: fetch_failed_404`)가 **똑같이 옛 문구로** 보인다.

    **본문은 담지 않는다** — 담으면 이 경로가 지시문 유출 경로가 된다 (3.8절).
    """
    return {"prompts": await asyncio.to_thread(prompt_library.status)}


@app.post("/prompts/reload")
async def prompts_reload(x_admin_token: str = Header("")):
    """**관리자** — 프롬프트 라이브러리를 즉시 다시 읽는다 (TTL 을 기다리지 않는다).

    **반환 타입 주석을 붙이지 않는다** — 성공/오류로 형이 갈리는 라우트는 이 저장소
    세 단위 모두 주석 없이 둔다(Union 반환 주석이면 앱이 기동 단계에서 죽는다).
    """
    if Config.ADMIN_TOKEN and x_admin_token != Config.ADMIN_TOKEN:
        return JSONResponse(
            status_code=403,
            content={"error_code": ERR_INPUT.code, "msg": "프롬프트 재적재 권한이 없습니다."},
        )
    return {"prompts": await asyncio.to_thread(prompt_library.reload)}


# ═══════════════════════════════════════════════════════════════════════════
# 스트리밍 번역 — **`not/` 판본에만 있는 두 라우트**
# ═══════════════════════════════════════════════════════════════════════════
# ```
# POST /translate/stream    (SSE)   번역문이 문서 순서대로 흐른다
#       … delta … delta … done{translated_text, options, …}
# POST /translate/finalize  (JSON)  {original_text, translated_text, glossary, …}
#                                    프론트가 이걸 받아 **바뀐 낱말만** 칠한다
# ```
#
# **정본 경로(`POST /translate/markdown`)를 지운 것이 아니다.** 그쪽은 스켈레톤 분해로
# 구조 보존을 **코드가 보장**하고, 이쪽은 흘릴 것이 있어야 해서 그 보장을 감지로 바꾼다
# (`stream_pipeline` 머리말). 표가 많은 문서는 정본 경로가 맞다.
_SSE_MEDIA_TYPE = "text/event-stream"


def _sse(frame: dict) -> str:
    """SSE 프레임 한 줄. `ensure_ascii=False` 라야 한글이 그대로 간다."""
    return f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"


@app.post("/translate/stream")
async def translate_stream(body: TranslateStreamRequest):
    """번역문을 만들어지는 대로 SSE 로 흘리고, 마지막에 `done` 프레임을 준다.

    **반환 타입 주석을 붙이지 않는다** — 성공은 `StreamingResponse`, 오류는
    `JSONResponse` 다. Union 을 적으면 FastAPI 가 그것을 `response_model` 로 삼아
    **라우트 등록 단계에서 앱이 죽는다**(공통 규약).

    ## 흘리기 전 실패는 SSE 가 아니라 평범한 오류다

    SSE 는 200 으로 시작하므로, 한 글자도 흘리기 전에 실패한 것까지 SSE 로 내면 호출부가
    상태코드로 성공/실패를 가릴 수 없다. 입력 상한·언어 축 거부(§6)는 여기서 걸린다.
    """
    if len(body.markdown) > Config.MAX_TOTAL_CHARS:
        return _input_error_response(
            f"총 텍스트 길이가 상한({Config.MAX_TOTAL_CHARS}자)을 초과했습니다."
        )

    try:
        # **정본과 같은 판정을 지난다** — 원문 언어 교차검증(§6 축 거부)·문체 폴백.
        # 여기서 세우지 않으면 스트리밍 경로만 그 집행을 건너뛰는 뒷문이 된다.
        options = stream_pipeline.resolve_options(
            target_lang=body.target_lang,
            source_lang=body.source_lang,
            register=body.register,
            sample_text=body.markdown,
        )
    except TranslationRequestError as exc:
        return _input_error_response(str(exc))
    except Exception as exc:  # noqa: BLE001 - 최종 방어선
        return _internal_error_response("translate_stream_options_error", exc)

    started = time.monotonic()
    # 흘릴 글을 큐에 넣고, 아래 제너레이터가 꺼내 SSE 로 내보낸다. 번역과 전송을 큐로
    # 가르는 이유: `translate_document_stream` 은 `on_text` 를 **직렬화해서** 부르는데
    # (조각들이 함께 돈다), 제너레이터 안에서 직접 부를 수는 없다.
    queue: asyncio.Queue = asyncio.Queue()
    _DONE = object()

    async def _on_text(text: str) -> None:
        await queue.put(text)

    async def _work() -> None:
        # **폴백 사실을 따로 든다.** `outcome` 을 비스트리밍 결과로 덮으면 그 객체의
        # `stream_unsupported` 는 거짓이라 "되돌아갔다" 는 사실이 사라진다.
        fell_back = False
        try:
            outcome = await stream_pipeline.translate_document_stream(
                body.markdown, options, _on_text
            )
            # **스트리밍을 안 받는 배포면 비스트리밍으로 되돌아간다.** 한 글자도 안
            # 흘렸을 때만 — 흘린 뒤에 다시 하면 화면에 같은 문서가 겹친다.
            if outcome.stream_unsupported and outcome.streamed_chars == 0:
                fell_back = True
                log_warning(
                    "스트리밍을 쓸 수 없어 비스트리밍으로 번역한다",
                    event="translate_stream_fallback",
                    resource_id="llm_gateway",
                    error_type=outcome.error_type,
                )
                outcome = await stream_pipeline.translate_document_plain(
                    body.markdown, options
                )
                if outcome.ok:
                    # 폴백 결과는 한 덩어리로 흘린다 — 프론트는 delta 만 알면 된다.
                    await queue.put(outcome.text)

            # **전량 실패는 이 단위의 기존 규약대로 `translation_error` 로 낸다**
            # (`/translate/markdown` 과 같다). 그때 흘린 것은 0 이다 — 실패 조각의 원문은
            # 최종 판정 뒤에만 풀리고, 전량 실패면 풀지 않기 때문이다.
            translation_error = ""
            if not outcome.ok:
                translation_error = (
                    "config_missing" if outcome.config_missing
                    else "transport" if outcome.is_transport_error
                    else "execution"
                )

            log_info(
                "번역 스트리밍 완료",
                event="translate_stream_completed",
                item_count=outcome.chunk_count,
                status=(
                    f"failed={outcome.failed_chunk_count}"
                    f",streamed={outcome.streamed_chars}"
                    f",fallback={int(fell_back)}"
                    f",diverged={int(outcome.stream_diverged)}"
                    f",{translation_error or 'ok'}"
                ),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            await queue.put(
                {
                    "type": "done",
                    # **정본을 함께 싣는다.** 프론트가 델타를 이어 붙인 값과 한 글자라도
                    # 다르면 finalize 의 좌표가 밀리고, 그 어긋남은 **하이라이트가 한 칸
                    # 밀린 화면**으로만 드러난다. 이 값을 그대로 finalize 로 보낸다.
                    "translated_text": outcome.text,
                    "options": stream_pipeline.options_payload(options),
                    "chunk_count": outcome.chunk_count,
                    "failed_chunk_count": outcome.failed_chunk_count,
                    "translation_error": translation_error,
                    # 스트리밍 고유 사실 둘. **화면에 나간 글과 정본이 어긋난 경우**를
                    # 조용히 넘기지 않는다.
                    "stream_diverged": outcome.stream_diverged,
                    "stream_fallback": fell_back,
                    # 다음에 부를 곳을 응답이 직접 말한다 — 프론트가 경로를 베껴 두면
                    # 이름을 바꿀 때 한쪽만 고쳐진다.
                    "finalize_endpoint": "/translate/finalize",
                }
            )
        except Exception as exc:  # noqa: BLE001 - 최종 방어선
            # 흘리기가 이미 시작됐을 수 있어 SSE 프레임으로 낸다. 예외 원문은 싣지
            # 않는다 (3.8절) — 로그만 남긴다.
            log_warning(
                "번역 스트리밍 중 내부 오류",
                event="translate_stream_internal_error",
                error_type=type(exc).__name__,
            )
            await queue.put(
                {
                    "type": "error",
                    "error_code": ERR_INPUT.code,
                    "msg": "번역 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
                }
            )
        finally:
            await queue.put(_DONE)

    async def _frames():
        task = asyncio.ensure_future(_work())
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                if isinstance(item, str):
                    yield _sse({"type": "delta", "text": item})
                else:
                    yield _sse(item)
        finally:
            # 클라이언트가 끊으면 제너레이터가 닫힌다. 번역을 그대로 두면 그 요청이
            # LLM 을 계속 부르며 살아 있다 — 취소하고 정리한다.
            if not task.done():
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    return StreamingResponse(
        _frames(),
        media_type=_SSE_MEDIA_TYPE,
        headers={
            # 중간 프록시가 모아서 보내면 스트리밍이 사라진다 — 그 상태는 "한방에 나온다"
            # 로만 보이고 오류가 없다.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/translate/finalize")
async def translate_finalize(body: TranslateFinalizeRequest):
    """흘려보낸 번역을 **JSON 으로 마무리한다** — 하이라이트 재료 + 내려받기 링크.

    Returns:
        original_text: 받은 원문 그대로 (프론트가 좌측에 그리는 값)
        translated_text: 받은 번역문 그대로 (우측)
        glossary: `term_map` / `hits[].spans`(원문 좌표) / `hits[].target_spans`(번역문
            좌표) / `compliance`. **적용된 용어만 좌표가 있다** — 요구사항 §2 가 묻는
            것이 "어떤 단어가 사전의 어떤 단어를 참고했나" 라, 참고하지 않은 자리는 칠할
            관계가 없다(미준수는 `term_map_unapplied` 가 맡는 검수용 값이다).
        structure: 구조 지문 대조 결과. 스트리밍 경로는 스켈레톤을 쓰지 않아 구조 보존이
            프롬프트에 달려 있다 — **못 막는 대신 숨기지 않는다.**
        download_url: 번역 정본 txt 링크 (업로드 실패 시 빈 문자열 — fail-open)
        options: 실제로 적용된 언어·문체

    **LLM 을 부르지 않는다.** 여기서 하는 일은 결정적 대조뿐이라 빠르고, 같은 입력이면
    몇 번을 불러도 같은 답이다(프론트가 재시도해도 안전하다).
    """
    started = time.monotonic()
    if len(body.original_text) > Config.MAX_TOTAL_CHARS or (
        len(body.translated_text) > Config.MAX_TOTAL_CHARS
    ):
        # 되돌아오는 본문이 곧 요청 크기다 — 스트리밍 입구와 같은 상한을 건다.
        return _input_error_response(
            f"총 텍스트 길이가 상한({Config.MAX_TOTAL_CHARS}자)을 초과했습니다."
        )

    try:
        options = stream_pipeline.resolve_options(
            target_lang=body.target_lang,
            source_lang=body.source_lang,
            register=body.register,
            sample_text=body.original_text,
        )
        glossary = stream_pipeline.build_document_glossary(
            body.original_text, body.translated_text, options
        )
        structure = stream_pipeline.structure_diff(
            body.original_text, body.translated_text
        )
    except TranslationRequestError as exc:
        return _input_error_response(str(exc))
    except Exception as exc:  # noqa: BLE001 - 최종 방어선
        return _internal_error_response("translate_finalize_internal_error", exc)

    log_info(
        "번역 마무리 완료",
        event="translate_finalize_completed",
        item_count=glossary["matched_count"],
        status=(
            f"applied={glossary['applied_count']}"
            f",compliance={glossary['compliance']}"
            f",structure_issues={len(structure['issues'])}"
        ),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return {
        "original_text": body.original_text,
        "translated_text": body.translated_text,
        "glossary": glossary,
        "structure": structure,
        # 업로드 실패는 번역이 실패한 것과 다른 사건이라 링크만 비운다 (fail-open).
        "download_url": await _upload_result(body.translated_text, body.title),
        "options": stream_pipeline.options_payload(options),
    }
