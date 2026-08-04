"""PDF 생성 — 전처리기 변환기에 위임한다.

**PDF 렌더러를 직접 만들지 않는다.** 전처리기가 이미 변환기를 들고 있고
(`pdf_sdk` / `rhwp` / `libreoffice`), `genos-project/CLAUDE.md` 도 HWPX→PDF 변환은
다른 담당자 소관이라고 못박고 있다. 우리는 호출만 한다.

경로가 두 개이고 성질이 다르다:

- **문서 → PDF** (`hwpx_to_pdf`): `genon.preprocessor.converters.hwp_to_pdf` 위임.
  외부 변환기(사내 PDF SDK / rhwp / LibreOffice)가 필요하다. hwpx 되쓰기 결과를
  **원본 서식 그대로** PDF 로 만드는 경로다.
- **마크다운 → PDF** (`markdown_to_pdf`): markdown → HTML → weasyprint.
  전처리기 `convert_md_to_pdf` 와 같은 방식. 원본 서식이 아니라 마크다운 렌더링
  서식이 된다. docx·pdf 원본과 FAQ 가 이 경로를 쓴다.

두 경로 모두 **동기 blocking 작업**(임시 파일·외부 프로세스)이므로 호출부가
`asyncio.to_thread` 로 감싼다 (가이드 6.9 — async 핸들러에서 blocking 직접 실행 금지).

변환기가 없으면 조용히 빈 PDF 를 주지 않고 `PdfConverterUnavailable` 로 알린다.
"""

import os
import tempfile

from export_pipeline.logging_utils import log_info, log_warning


class PdfConverterUnavailable(RuntimeError):
    """이 컨테이너에 PDF 변환기가 없음.

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다.
    """


class PdfConversionError(RuntimeError):
    """변환기는 있는데 변환이 실패함.

    계약: 위와 같다. 외부 도구의 오류 원문을 담지 않는다 (3.8절).
    """


def _load_document_converter():
    """전처리기의 문서→PDF 변환 함수를 가져온다 (지연 import).

    모듈 import 시점에 실패하면 컨테이너가 뜨지 않으므로 호출 시점에 확인한다.
    """
    try:
        from genon.preprocessor.converters.hwp_to_pdf import convert_hwp_to_pdf
    except ImportError as exc:
        raise PdfConverterUnavailable(
            "이 환경에서는 문서 PDF 변환을 사용할 수 없습니다."
        ) from exc
    return convert_hwp_to_pdf


def _load_markdown_renderer():
    """마크다운→PDF 렌더러를 가져온다 (지연 import).

    weasyprint 는 pip 로 설치되지만 시스템 라이브러리(pango/cairo)에 의존하므로
    이미지에 따라 없을 수 있다 — 전처리기도 ImportError 를 감싸 처리한다.
    """
    try:
        from markdown import markdown
        from weasyprint import HTML
    except ImportError as exc:
        raise PdfConverterUnavailable(
            "이 환경에서는 마크다운 PDF 변환을 사용할 수 없습니다."
        ) from exc
    return markdown, HTML


def document_converter_available() -> bool:
    """문서→PDF 변환기 가용성 (전처리기 availability 모듈 기준)."""
    try:
        from genon.preprocessor.converters.hwp_to_pdf.availability import (
            libreoffice_available,
            pdf_sdk_available,
            rhwp_available,
        )
    except ImportError:
        return False
    return bool(pdf_sdk_available() or rhwp_available() or libreoffice_available())


def hwpx_to_pdf(hwpx_bytes: bytes, *, stem: str = "document") -> bytes:
    """hwpx 바이트를 PDF 바이트로 변환한다 (원본 서식 유지 경로).

    전처리기와 같은 백엔드 우선순위를 쓴다: hwpx 는 pdf_sdk → rhwp → libreoffice.

    Raises:
        PdfConverterUnavailable: 변환기가 이 컨테이너에 없음.
        PdfConversionError: 변환 실패.
    """
    convert = _load_document_converter()
    with tempfile.TemporaryDirectory() as work_dir:
        source_path = os.path.join(work_dir, f"{stem}.hwpx")
        with open(source_path, "wb") as handle:
            handle.write(hwpx_bytes)
        try:
            produced = convert(source_path, order=["pdf_sdk", "rhwp", "libreoffice"])
        except Exception as exc:  # 외부 변환기 예외는 종류를 예측할 수 없다
            log_warning(
                "hwpx PDF 변환 실패",
                event="pdf_convert_failed",
                resource_id="hwp_to_pdf",
                error_type=type(exc).__name__,
            )
            raise PdfConversionError("PDF 변환에 실패했습니다.") from exc
        if not produced or not os.path.exists(produced):
            # 변환기가 None 을 돌려주는 경로가 있다 — 빈 파일을 내보내지 않는다
            log_warning("hwpx PDF 변환 결과 없음", event="pdf_convert_empty", resource_id="hwp_to_pdf")
            raise PdfConversionError("PDF 변환에 실패했습니다.")
        with open(produced, "rb") as handle:
            data = handle.read()
    log_info("hwpx PDF 변환 완료", event="pdf_converted", resource_id="hwp_to_pdf")
    return data


def markdown_to_pdf(markdown_text: str, *, title: str = "") -> bytes:
    """마크다운을 PDF 바이트로 변환한다 (마크다운 렌더링 서식).

    전처리기 `convert_md_to_pdf` 와 같은 방식이다. 표를 살리려면 markdown 의
    tables 확장이 필요하므로 명시적으로 켠다.

    Raises:
        PdfConverterUnavailable: markdown/weasyprint 가 없음.
        PdfConversionError: 렌더링 실패.
    """
    if not (markdown_text or "").strip():
        raise PdfConversionError("PDF 로 만들 내용이 없습니다.")
    render_markdown, HTML = _load_markdown_renderer()
    body = render_markdown(markdown_text, extensions=["tables", "fenced_code"])
    heading = f"<h1>{title}</h1>" if title.strip() else ""
    # 한글 폰트는 이미지에 설치된 것을 쓴다 — 폰트 파일을 저장소에 넣지 않는다
    document = (
        "<html><head><meta charset='utf-8'><style>"
        "body{font-family:'Noto Sans CJK KR','Malgun Gothic',sans-serif;line-height:1.6}"
        "table{border-collapse:collapse}td,th{border:1px solid #999;padding:4px 8px}"
        "</style></head><body>" + heading + body + "</body></html>"
    )
    try:
        data = HTML(string=document).write_pdf()
    except Exception as exc:
        log_warning(
            "마크다운 PDF 변환 실패",
            event="pdf_markdown_failed",
            resource_id="weasyprint",
            error_type=type(exc).__name__,
        )
        raise PdfConversionError("PDF 변환에 실패했습니다.") from exc
    if not data:
        raise PdfConversionError("PDF 변환에 실패했습니다.")
    log_info("마크다운 PDF 변환 완료", event="pdf_markdown_converted", resource_id="weasyprint")
    return data
