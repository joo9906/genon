"""공용 로깅 유틸 — 가이드 3.7/3.8/3.10 (GENOS_RULES §C) 준수 계층.

배포 단위마다 같은 계약의 사본을 둔다 (단위 간 import 금지).

- `print()` 금지. 모든 로그는 표준 logger 로만 나간다 (3.10절).
  초안(`archive/FAQ.py`)은 `print()` 로 GENOS_URL 을 찍고 있었다 — 그 경로를 없앤다.
- **기록 허용 필드 화이트리스트만 통과시킨다** (3.8절).
- 값은 반드시 `extra` 필드로 넘기고 **메시지 문자열에 f-string 으로 끼워 넣지 않는다.**
  문자열에 섞인 값은 걸러낼 방법이 없어 화이트리스트가 무력해진다
  (문서 원문·질문·LLM 응답 전문·시크릿이 새는 실제 경로가 여기다).
- 허용 목록 밖 필드는 **이름만** 메시지 끝에 남기고 값은 버린다. 조용히 지우면
  호출부가 기록됐다고 착각한다.
"""

import logging

ALLOWED_FIELDS = frozenset(
    {
        "event",
        "trace_id",
        "request_id",
        "resource_id",
        "status",
        "duration_ms",
        "item_count",
        "upstream_status",
        "error_code",
        "error_type",
    }
)

_log = logging.getLogger("faq")


def configure_logging(level: str = "INFO") -> None:
    """코드 서빙 진입점에서 한 번 호출한다 (워크플로우 영역은 GenOS 가 이미 설정한다)."""
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))


def _prepare(message: str, event: str, fields: dict) -> tuple:
    extra: dict = {"event": event}
    dropped = []
    for key, value in fields.items():
        if key == "event" or key not in ALLOWED_FIELDS:
            dropped.append(key)
            continue
        if value is not None:
            extra[key] = value
    if dropped:
        message = f"{message} [dropped_fields={','.join(sorted(dropped))}]"
    return message, extra


def log_info(message: str, *, event: str, **fields) -> None:
    text, extra = _prepare(message, event, fields)
    _log.info(text, extra=extra)


def log_warning(message: str, *, event: str, **fields) -> None:
    text, extra = _prepare(message, event, fields)
    _log.warning(text, extra=extra)


def log_error(message: str, *, event: str, **fields) -> None:
    text, extra = _prepare(message, event, fields)
    _log.error(text, extra=extra)
