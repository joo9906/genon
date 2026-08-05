"""hwpx → PDF 변환. 전처리기의 변환기를 **호출만** 한다.

전처리기(`genos_files/intelligence_processor.py` 사본으로 확인)는 `.hwpx` 를 1급
입력으로 지원하고 HWP/HWPX 전용 백엔드 `rhwp` 를 LibreOffice 보다 우선한다:

    from genon.preprocessor.converters.hwp_to_pdf import convert_hwp_to_pdf
    convert_hwp_to_pdf(file_path, order=["pdf_sdk", "rhwp", "libreoffice"])

**전처리기 코드는 수정하지 않는다** — 이 모듈은 호출 규약만 맞춘다. 대체 구현이나
모의 변환 경로는 두지 않는다 (`onprem/` 은 mock/noop 경로를 두지 않는 규칙이고,
가짜 PDF 를 만들 수 있게 열어 두면 그게 운영에 흘러갈 위험이 실익보다 크다).

그 함수의 성질 때문에 감싸야 하는 것이 네 가지다:

1. 그 패키지는 이 저장소에 없다 (전처리기 이미지에 들어 있다). import 실패는
   "이 환경은 PDF 미지원" 이라는 상태이므로 오류를 구분해 알린다 —
   **코드서빙 이미지에 전처리기 패키지가 포함돼야 PDF 가 동작한다.**
2. 변환 백엔드가 0개일 수 있다 (빌드에서 INSTALL_LIBREOFFICE/INSTALL_RHWP 를 끄거나
   PDF SDK 미포함). 그때는 시도 자체가 무의미하므로 미리 판별한다.
3. **실패해도 예외를 던지지 않고 None 을 반환한다.** 그대로 흘리면 빈 응답이 나가므로
   여기서 예외로 바꾼다 (실패를 침묵 처리하지 않는다 — 저장소 컨벤션).
4. 경로 기반 API 다. 우리 파이프라인은 메모리 바이트로 끝나므로 임시파일을 경유한다.
   변환은 외부 프로세스를 도는 blocking 작업이라 `asyncio.to_thread` 로 뺀다
   (이벤트 루프 차단 금지).

주의: `attach_processor._get_pdf_path()` 는 쓰지 않는다. `CONVERTIBLE_EXTENSIONS` 에
`.hwp` 만 있어서 `"보고서.hwpx".replace(".hwp", ".pdf")` → `보고서.pdfx` 가 된다.
출력 경로는 변환기가 돌려주는 값을 그대로 쓴다.
"""

import asyncio
import os
import tempfile

from .logging_utils import log_info, log_warning

# 전처리기 호출 순서 — HWP/HWPX 는 rhwp 가 LibreOffice 보다 정확하다 (전처리기와 동일)
_CONVERT_ORDER = ["pdf_sdk", "rhwp", "libreoffice"]
# 변환기에 넘길 임시 파일명은 ASCII 고정으로 둔다. 외부 변환기(LibreOffice 등)가
# 한글·공백 경로에서 흔들리는 것을 피하고, 사용자에게 보이는 파일명은 어차피
# Content-Disposition 이 정한다.
_TEMP_STEM = "document"
_PDF_MAGIC = b"%PDF-"

# 가용성은 이미지 빌드 시점에 결정되고 런타임에 바뀌지 않는다. 매 요청 probe 하면
# (which/subprocess 호출) 목록·상태 조회가 그만큼 느려지므로 프로세스당 1회만 본다.
# 환경이 바뀌면 pod 재시작이 필요하다.
_AVAILABLE: "bool | None" = None


class PdfUnavailableError(RuntimeError):
    """이 환경에 PDF 변환 수단이 없다 (미지원 — 재시도 무의미).

    계약: 메시지는 이 파일에서 만든 고정 한국어 안내문만 담는다.
    """


class PdfConvertError(RuntimeError):
    """변환을 시도했지만 실패했다 (재시도 가치 있음).

    계약: 메시지는 이 파일에서 만든 고정 한국어 안내문만 담는다.
    """


_UNAVAILABLE_MSG = "이 환경에서는 PDF 변환을 지원하지 않습니다."
_FAILED_MSG = "PDF 변환에 실패했습니다."


def _load_converter():
    """전처리기 변환 함수를 가져온다. 없으면 PdfUnavailableError."""
    try:
        from genon.preprocessor.converters.hwp_to_pdf import convert_hwp_to_pdf
    except ImportError as exc:
        raise PdfUnavailableError(_UNAVAILABLE_MSG) from exc
    return convert_hwp_to_pdf


def _backend_available() -> bool:
    """변환 백엔드가 하나라도 있는가.

    가용성 모듈 자체를 import 할 수 없으면(단일 파일 배포 등) 판단을 보류하고
    True 를 돌려준다 — 전처리기 `_has_any_pdf_converter()` 와 같은 규약이다.
    판단 불가를 미지원으로 단정하면 되는 환경에서도 PDF 를 막게 된다.
    """
    try:
        from genon.preprocessor.converters.hwp_to_pdf.availability import (
            libreoffice_available,
            pdf_sdk_available,
            rhwp_available,
        )
    except ImportError:
        return True
    try:
        return bool(pdf_sdk_available() or rhwp_available() or libreoffice_available())
    except Exception as exc:  # noqa: BLE001 - probe 실패가 기능을 막지 않게
        log_warning(
            "PDF 변환기 가용성 확인 실패 — 가용으로 가정",
            event="pdf_probe_failed",
            error_type=type(exc).__name__,
        )
        return True


def available() -> bool:
    """PDF 다운로드를 제공할 수 있는 환경인가 (UI 버튼 노출 판단용)."""
    global _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    try:
        _load_converter()
    except PdfUnavailableError:
        log_warning(
            "전처리기 PDF 변환 모듈이 없어 PDF 를 제공하지 않는다",
            event="pdf_module_missing",
            status="unavailable",
        )
        _AVAILABLE = False
        return _AVAILABLE
    _AVAILABLE = _backend_available()
    if not _AVAILABLE:
        log_warning(
            "PDF 변환 백엔드가 하나도 없어 PDF 를 제공하지 않는다",
            event="pdf_backend_missing",
            status="unavailable",
        )
    return _AVAILABLE


def reset_availability_cache() -> None:
    """가용성 캐시 초기화 (기동 순서 때문에 첫 판정이 이르게 굳은 경우용)."""
    global _AVAILABLE
    _AVAILABLE = None


async def to_pdf(hwpx_bytes: bytes) -> bytes:
    """채운 hwpx 바이트를 PDF 바이트로 바꾼다.

    Raises:
        PdfUnavailableError: 변환 수단이 없는 환경 (재시도 무의미).
        PdfConvertError: 변환 시도 실패 또는 결과물이 PDF 가 아님.
    """
    convert = _load_converter()
    if not _backend_available():
        raise PdfUnavailableError(_UNAVAILABLE_MSG)

    def _run() -> bytes:
        with tempfile.TemporaryDirectory(prefix="template_fill_pdf_") as workdir:
            src_path = os.path.join(workdir, f"{_TEMP_STEM}.hwpx")
            with open(src_path, "wb") as handle:
                handle.write(hwpx_bytes)
            out_path = convert(src_path, order=_CONVERT_ORDER)
            if not out_path or not os.path.exists(out_path):
                # 변환기는 실패해도 None 을 돌려준다 — 여기서 오류로 승격한다
                raise PdfConvertError(_FAILED_MSG)
            with open(out_path, "rb") as handle:
                data = handle.read()
            if not data.startswith(_PDF_MAGIC):
                # 확장자만 pdf 인 산출물을 그대로 내려보내지 않는다
                raise PdfConvertError(_FAILED_MSG)
            return data

    try:
        pdf_bytes = await asyncio.to_thread(_run)
    except (PdfUnavailableError, PdfConvertError):
        raise
    except Exception as exc:  # noqa: BLE001 - 변환기 내부 예외는 분류만 남긴다
        log_warning(
            "PDF 변환 중 예외",
            event="pdf_convert_error",
            error_type=type(exc).__name__,
        )
        raise PdfConvertError(_FAILED_MSG) from exc

    log_info("PDF 변환 완료", event="pdf_converted", item_count=len(pdf_bytes))
    return pdf_bytes
