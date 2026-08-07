"""FAQ 내보내기 — hwpx / pdf / xlsx (요구사항 §2).

세 형식의 성질이 다르다:

| 형식 | 방식 | 가용 조건 |
|---|---|---|
| xlsx | `openpyxl` 로 표를 새로 만든다 | pip 설치만 (폐쇄망에서 항상 가능) |
| pdf  | 마크다운 → HTML → `weasyprint` | 이미지에 weasyprint + 한글 폰트 |
| hwpx | **FAQ 템플릿 반복 블록 복제** | 관리자가 템플릿을 볼륨에 등록 |

hwpx 를 백지에서 만들지 않는 이유는 `hwpx_export.py` 머리말에 적었다.

**"수단 없음"과 "변환 실패"를 구분해 올린다** — 전자는 재시도해도 소용없고(다른 형식으로
받으면 된다), 후자는 재시도 가치가 있다. SFR-006 PDF 규약과 같다.
"""

from .errors import ExportError, ExporterUnavailable

__all__ = ["ExportError", "ExporterUnavailable"]
