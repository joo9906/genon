"""문서 조립 → 다운로드 응답 — "검증된 값을 파일로 바꾸는" 층.

`main.py` 에서 갈라져 나왔다 (2026-08-11). `api_requests.py` 가 요청을 값으로 바꾸고,
여기서 그 값을 문서로 바꾼다. `main.py` 에는 그 둘을 잇는 배선만 남는다.

## 경계

- **조립 순서(서식 → 채우기 → 블록)는 여기에 없다.** `document.build` 한 곳에만 있다.
  예전에 코드서빙·미리보기·점검 스크립트가 각자 순서를 적고 있었고, 점검이 자기가 검증할
  순서를 스스로 복제해 무의미했다.
- **`document.build` 는 HTTP 를 모른다.** 도메인 예외(`TemplateError`)를 `ApiError` 로
  바꾸는 것이 이 파일의 일이고, 그 경계가 여기다.
- **blocking 작업은 전부 `asyncio.to_thread`** (6.9절). zip 해제·XML 파싱이 전부 여기를
  지난다 — 이벤트 루프에서 직접 돌리면 헬스체크가 멈춘다.
- **산출 형식은 이 판본에서 txt 하나다.** 정본은 hwpx 를 낸다(2026-08-14 요구 변경 —
  PDF 변환 `pdf_convert.py` 를 걷어냈다. 그 경로가 `genon.preprocessor` 를 요구했고
  pip 로 붙일 수 없어 **기본 이미지 변경 절차**(11.5.6)에 묶여 있었다. 코드는
  `archive/sfr006-pdf` 브랜치). **`not/` 판본은 `lxml` 이 없어 hwpx 를 되쓸 수 없으므로**
  018 세 단위와 같은 txt 규약으로 낸다 — 아래 `download_response` 주석.
  두 판본 모두 환경에 아무것도 요구하지 않는다.
"""

import asyncio
import urllib.parse

from fastapi.responses import Response

from . import document, session_view, txt_output
from .api_errors import ApiError
from .config import Config
from .error_codes import ERR_API_INPUT, ERR_API_INTERNAL
from .field_judge import normalize_blocks
from .hwpx_blocks import block_style_names
from .hwpx_fields import TemplateError
from .logging_utils import log_warning


async def resolve_blocks(template_id: str, template_bytes: bytes, raw_blocks) -> list:
    """문서 생성 직전에 본문 블록을 검증한다 (`/generate`, `/generate/upload` 공용).

    서식 화이트리스트의 출처가 두 경로에서 다르다 — 등록 템플릿은 색인(캐시)에서,
    업로드 파일은 그 자리에서 파싱해 얻는다. 블록이 없으면 둘 다 하지 않는다
    (블록을 안 쓰는 호출에 파싱·Redis 왕복을 얹지 않는다).
    """
    if not Config.BODY_BLOCKS or not raw_blocks:
        return []
    if template_id:
        _, index = await session_view.load_index(template_id)
        styles = list(index.block_styles)
    else:
        try:
            styles = await asyncio.to_thread(block_style_names, template_bytes)
        except TemplateError as exc:
            raise ApiError(ERR_API_INPUT, str(exc)) from exc

    blocks, rejected = normalize_blocks(raw_blocks, styles)
    if rejected:
        log_warning(
            "본문 블록 일부를 기각했다",
            event="generate_blocks_rejected",
            resource_id=template_id or "upload",
            item_count=len(rejected),
        )
    return blocks


async def build(template_bytes: bytes, values: dict, blocks: list, label: str):
    """조립 파이프라인을 스레드에서 돌리고 실패를 HTTP 오류로 바꾼다.

    파이프라인 자체(`document.build`)는 HTTP 를 모른다 — 여기가 그 경계다.
    """
    try:
        return await asyncio.to_thread(
            document.build, template_bytes, values, blocks, label=label
        )
    except TemplateError as exc:
        # 계약: TemplateError 메시지는 도메인 모듈이 만든 고정 안내문만 담는다
        raise ApiError(ERR_API_INPUT, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 원문은 로그 메타에만
        log_warning(
            "hwpx 생성 중 내부 오류",
            event="generate_internal_error",
            resource_id=label,
            error_code=ERR_API_INTERNAL.code,
            error_type=type(exc).__name__,
        )
        raise ApiError(ERR_API_INTERNAL) from exc


def download_response(built, filename_base: str, template_bytes: bytes) -> Response:
    """**txt** 본문 + 부분 초안/블록 정보를 헤더로 함께 내려준다 (`not/` 판본).

    > 정본은 여기서 `built.hwpx_bytes` 를 그대로 내려준다. 이 판본은 `lxml` 없이 hwpx 를
    > 되쓸 수 없어(`hwpx_fields` 의 `serialize_part` 자리 주석) **txt 를 낸다.**
    > 그래서 `template_bytes` 를 하나 더 받는다 — 자동 번호·글머리표 정의가 있는
    > `Contents/header.xml` 이 거기 있고, 채우기는 그 파트를 건드리지 않는다.

    본문은 **미리보기와 같은 렌더러**를 지난다(`document.to_text`). 파일 전용 조립을
    따로 두면 "화면에는 보이는데 파일에는 없는" 상태가 되살아난다.

    `X-Document-Format` 은 이제 `txt` 다. **값을 바꾼다는 것이 요점이다** — `hwpx` 로
    두면 화면이 확장자를 `.hwpx` 로 붙여, 열리지 않는 파일을 사용자가 받는다.

    `X-Styled-Fields` 는 **언제나 빈 값**이다(서식 단계가 없다). 헤더를 빼지 않는 이유는
    정본과 응답 모양을 맞춰 화면이 두 벌이 되지 않게 하려는 것이고, 값이 비어 있다는
    사실 자체가 "서식이 안 걸렸다"는 정확한 신호다.
    """
    text = document.to_text(template_bytes, built)
    filename = (filename_base or "초안").strip()
    # 옛 확장자로 들어와도 떼어낸다 — 세션·화면에 `초안.hwpx` 같은 이름이 남아 있으면
    # `초안.hwpx.txt` 가 된다.
    for suffix in (".hwpx", ".txt"):
        filename = filename.removesuffix(suffix)
    quoted = urllib.parse.quote(f"{filename}.{txt_output.EXTENSION}")  # 한글 파일명 → RFC 5987
    return Response(
        content=txt_output.to_bytes(text),
        media_type=txt_output.MEDIA_TYPE,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quoted,
            # 부분 초안 여부를 파일과 함께 전달 — 누락을 침묵 처리하지 않는다
            "X-Missing-Fields": urllib.parse.quote(",".join(built.missing_fields)),
            "X-Written-Fields": urllib.parse.quote(",".join(built.written_fields)),
            "X-Styled-Fields": urllib.parse.quote(",".join(built.styled_fields)),
            "X-Body-Blocks": str(built.appended_blocks),
            "X-Document-Format": txt_output.EXTENSION,
        },
    )
