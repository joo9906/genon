"""FAQ → PDF.

`archive/sfr018-export` 태그의 `export_pipeline/pdf_export.py` 중 **마크다운 경로만**
가져왔다. 그쪽에는 문서→PDF(전처리기 `hwp_to_pdf` 위임) 경로도 있었지만, 그건 원본
서식을 살려 되쓴 hwpx 를 변환하는 용도였다. FAQ 는 원본 문서가 없으므로 해당 없다.

두 경로가 남는다:
- **마크다운 → PDF** (`markdown_to_pdf`): markdown → HTML → weasyprint.
  전처리기 `convert_md_to_pdf` 와 같은 방식. 기본 경로다.
- **hwpx → PDF** (`hwpx_to_pdf`): FAQ 템플릿으로 만든 hwpx 를 전처리기 변환기에
  넘긴다. **템플릿이 등록돼 있을 때만** 쓴다 — 그래야 사내 서식 그대로 나온다.

**PDF 렌더러를 직접 만들지 않는다.** `genos-project/CLAUDE.md` 가 HWPX→PDF 변환은
다른 담당자 소관이라고 못박고 있고, 전처리기가 이미 변환기를 들고 있다.

두 경로 모두 **동기 blocking 작업**(임시 파일·외부 프로세스)이므로 호출부가
`asyncio.to_thread` 로 감싼다 (async 핸들러에서 blocking 직접 실행 금지).

변환기가 없으면 조용히 빈 PDF 를 주지 않고 `ExporterUnavailable` 로 알린다.
"""

import os
import tempfile

from ..logging_utils import log_info, log_warning
from .errors import ExportError, ExporterUnavailable


def _load_markdown_renderer():
    """마크다운→PDF 렌더러를 가져온다 (지연 import).

    weasyprint 는 pip 로 설치되지만 시스템 라이브러리(pango/cairo)에 의존하므로
    이미지에 따라 없을 수 있다 — 전처리기도 ImportError 를 감싸 처리한다.
    모듈 로드 시점에 import 하면 그런 이미지에서 컨테이너가 아예 뜨지 않는다.
    """
    try:
        from markdown import markdown
        from weasyprint import HTML
    except ImportError as exc:
        raise ExporterUnavailable("이 환경에서는 PDF 내보내기를 사용할 수 없습니다.") from exc
    return markdown, HTML


def markdown_available() -> bool:
    """`GET /formats` 가 UI 에 알려줄 가용성. 예외 없이 참/거짓만."""
    try:
        _load_markdown_renderer()
    except ExporterUnavailable:
        return False
    return True


def document_converter_available() -> bool:
    """hwpx→PDF 변환기 가용성 (전처리기 availability 모듈 기준)."""
    try:
        from genon.preprocessor.converters.hwp_to_pdf.availability import (
            libreoffice_available,
            pdf_sdk_available,
            rhwp_available,
        )
    except ImportError:
        return False
    return bool(pdf_sdk_available() or rhwp_available() or libreoffice_available())


def markdown_to_pdf(markdown_text: str, *, title: str = "") -> bytes:
    """마크다운을 PDF 바이트로 변환한다 (마크다운 렌더링 서식).

    표를 살리려면 markdown 의 tables 확장이 필요하므로 명시적으로 켠다.

    Raises:
        ExporterUnavailable: markdown/weasyprint 가 없음.
        ExportError: 렌더링 실패 또는 내용 없음.
    """
    if not (markdown_text or "").strip():
        raise ExportError("PDF 로 만들 내용이 없습니다.")
    render_markdown, HTML = _load_markdown_renderer()
    body = render_markdown(markdown_text, extensions=["tables", "fenced_code"])
    heading = f"<h1>{title}</h1>" if (title or "").strip() else ""
    # 한글 폰트는 이미지에 설치된 것을 쓴다 — 폰트 파일을 저장소에 넣지 않는다
    document = (
        "<html><head><meta charset='utf-8'><style>"
        "body{font-family:'Noto Sans CJK KR','Malgun Gothic',sans-serif;line-height:1.6}"
        "blockquote{color:#555;border-left:3px solid #bbb;margin:0.4em 0;padding-left:0.8em}"
        "table{border-collapse:collapse}td,th{border:1px solid #999;padding:4px 8px}"
        "</style></head><body>" + heading + body + "</body></html>"
    )
    try:
        data = HTML(string=document).write_pdf()
    except Exception as exc:  # noqa: BLE001 - 외부 렌더러 예외 종류를 예측할 수 없다
        log_warning(
            "마크다운 PDF 변환 실패",
            event="pdf_markdown_failed",
            resource_id="weasyprint",
            error_type=type(exc).__name__,
        )
        raise ExportError("PDF 변환에 실패했습니다.") from exc
    if not data:
        raise ExportError("PDF 변환에 실패했습니다.")
    log_info("마크다운 PDF 변환 완료", event="pdf_markdown_converted", resource_id="weasyprint")
    return data


def hwpx_to_pdf(hwpx_bytes: bytes, *, stem: str = "faq") -> bytes:
    """hwpx 바이트를 PDF 로 변환한다 (사내 서식 유지 경로).

    전처리기와 같은 백엔드 우선순위를 쓴다: `pdf_sdk → rhwp → libreoffice`
    (`rhwp` 가 HWP/HWPX 전용이라 LibreOffice 보다 정확하다).

    임시 파일명은 ASCII 고정이다 — 외부 변환기가 한글·공백 경로에서 흔들리는 것을
    피한다. 사용자에게 보이는 파일명은 `Content-Disposition` 이 정한다.

    Raises:
        ExporterUnavailable: 변환기가 이 컨테이너에 없음.
        ExportError: 변환 실패.
    """
    try:
        from genon.preprocessor.converters.hwp_to_pdf import convert_hwp_to_pdf
    except ImportError as exc:
        raise ExporterUnavailable("이 환경에서는 문서 PDF 변환을 사용할 수 없습니다.") from exc

    with tempfile.TemporaryDirectory() as work_dir:
        source_path = os.path.join(work_dir, f"{stem}.hwpx")
        with open(source_path, "wb") as handle:
            handle.write(hwpx_bytes)
        try:
            produced = convert_hwp_to_pdf(source_path, order=["pdf_sdk", "rhwp", "libreoffice"])
        except Exception as exc:  # noqa: BLE001 - 외부 변환기 예외를 예측할 수 없다
            log_warning(
                "hwpx PDF 변환 실패",
                event="pdf_convert_failed",
                resource_id="hwp_to_pdf",
                error_type=type(exc).__name__,
            )
            raise ExportError("PDF 변환에 실패했습니다.") from exc
        if not produced or not os.path.exists(produced):
            # 변환기가 예외 없이 None 을 돌려주는 경로가 있다 — 빈 파일을 내보내지 않는다
            log_warning(
                "hwpx PDF 변환 결과 없음",
                event="pdf_convert_empty",
                resource_id="hwp_to_pdf",
            )
            raise ExportError("PDF 변환에 실패했습니다.")
        with open(produced, "rb") as handle:
            data = handle.read()

    if not data.startswith(b"%PDF-"):
        # 결과물이 PDF 가 아니면 내려보내지 않는다 (SFR-006 pdf_convert 와 같은 검사)
        raise ExportError("PDF 변환에 실패했습니다.")
    log_info("hwpx PDF 변환 완료", event="pdf_converted", resource_id="hwp_to_pdf")
    return data
