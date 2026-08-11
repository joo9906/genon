"""내려받기 형식 — 무엇을 만들 수 있고, 어떻게 만드는가.

`main.py` 에서 갈라져 나왔다 (2026-08-11). 세 가지가 한 덩어리로 묶여 있어야 갈리지
않는다: **형식 목록**(`FORMATS`), **지금 만들 수 있는지**(`available_formats`),
**실제 생성**(`build_bytes`). 셋이 흩어지면 `/config` 가 켜준 버튼을 `/download` 가
501 로 거절하는 상태가 생긴다.

## 가용성은 프로세스당 한 번만 본다

xlsx 는 openpyxl(순수 파이썬)만 있으면 되고, pdf 는 weasyprint 또는 전처리기 변환기,
hwpx 는 **관리자 템플릿 등록**이 조건이다. 전부 이미지 빌드·설정 시점에 정해지므로
요청마다 다시 볼 이유가 없다 — 환경이 바뀌면 pod 을 재시작한다.
캐시 자체는 `main.py` 의 lifespan 이 채운다(기동 로그에 함께 남겨야 해서다).

## pdf 는 두 경로가 있고 순서에 이유가 있다

hwpx 템플릿이 있으면 **사내 서식 그대로**(hwpx→pdf), 없으면 마크다운 렌더링.
앞쪽을 먼저 시도하는 이유는 배포된 문서의 서식이 사내 양식과 같아야 하기 때문이고,
변환기가 없으면 뒤쪽으로 떨어진다.

## 없는 형식은 가짜로 만들지 않는다

hwpx 템플릿이 없으면 **501** 이다 (006 PDF 규약과 같다). 백지에서 hwpx 를 조립하면
`header.xml` 의 `charPr`/`itemCnt` 한 글자 차이로 한/글이 문서를 못 여는데, 확인할
한/글이 없다. 열리지 않는 파일을 주는 것보다 못 만든다고 말하는 편이 낫다.
"""

from datetime import datetime, timezone

from .exporters import hwpx_export, pdf_export, xlsx_export
from .exporters.errors import ExportError
from .formatting import rows_to_markdown

# 형식 → (media type, 확장자)
FORMATS = {
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
    "hwpx": ("application/octet-stream", "hwpx"),
}


def available_formats() -> list:
    """지금 이 컨테이너가 만들 수 있는 형식.

    셋 다 확인해서 알린다 — UI 가 못 만드는 형식의 버튼을 켜두면 사용자는 눌러 보고서야
    501 을 받는다.
    """
    formats = []
    try:
        import openpyxl  # noqa: F401 - 가용성 확인만 (실제 사용은 지연 import)

        formats.append("xlsx")
    except ImportError:
        pass
    if pdf_export.markdown_available() or (
        hwpx_export.available() and pdf_export.document_converter_available()
    ):
        formats.append("pdf")
    if hwpx_export.available():
        formats.append("hwpx")
    return formats


def build_bytes(fmt: str, items: list, title: str) -> bytes:
    """형식별 생성 — **동기 함수**다. 호출부가 `asyncio.to_thread` 로 감싼다.

    pdf 는 두 경로가 있다: hwpx 템플릿이 있으면 사내 서식 그대로(hwpx→pdf),
    없으면 마크다운 렌더링. 앞쪽을 먼저 시도하는 이유는 배포한 문서의 서식이
    사내 양식과 같아야 하기 때문이고, 변환기가 없으면 뒤쪽으로 떨어진다.
    """
    created_on = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    if fmt == "xlsx":
        return xlsx_export.build_faq_xlsx(items, sheet_title=title or "FAQ")
    if fmt == "hwpx":
        return hwpx_export.build_faq_hwpx(items, title=title, created_on=created_on)
    if fmt == "pdf":
        if hwpx_export.available() and pdf_export.document_converter_available():
            hwpx_bytes = hwpx_export.build_faq_hwpx(items, title=title, created_on=created_on)
            return pdf_export.hwpx_to_pdf(hwpx_bytes)
        return pdf_export.markdown_to_pdf(rows_to_markdown(items), title=title)
    raise ExportError("지원하지 않는 형식입니다.")
