"""내보내기 예외 — 두 종류만 둔다.

세 내보내기 모듈이 같은 예외를 던져야 `main.py` 가 형식별로 분기하지 않는다.

계약: 두 예외의 메시지는 **던지는 모듈 안에서 작성한 고정 한국어 안내문**만 담는다.
외부 도구(weasyprint, 한/글 변환기)의 오류 원문을 담지 않는다 (3.8절).
"""

from ..config import Config


class ExporterUnavailable(RuntimeError):
    """이 컨테이너/설정에서 그 형식으로 만들 수단이 없다 (501, 재시도 무의미)."""


class ExportError(RuntimeError):
    """수단은 있는데 생성이 실패했다 (500, 재시도 가치 있음)."""


def ensure_exportable_items(items: list) -> None:
    """형식과 무관한 항목 가드 — 빈 목록과 배포 상한 초과.

    형식별 모듈이 각자 검사하면 같은 안내문이 여러 벌 생기고, `FAQ_MAX_COUNT` 를
    올렸을 때 한 형식만 빠뜨리기 쉽다. 가드와 그 문구를 여기 함께 둔다
    (위 계약대로 이 모듈 안에서 작성한 고정 안내문이다).

    Raises:
        ExportError: 항목이 없거나 상한을 넘음.
    """
    if not items:
        raise ExportError("내보낼 FAQ 항목이 없습니다.")
    if len(items) > Config.MAX_FAQ_COUNT:
        raise ExportError("FAQ 항목이 너무 많습니다. 나누어 내보내 주세요.")
