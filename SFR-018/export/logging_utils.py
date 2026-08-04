"""공용 로깅 유틸 — 가이드 3.7/3.8/3.10 (GENOS_RULES §C) 준수 계층.

`text_polish/logging_utils.py` 와 **같은 계약의 사본**이다 (배포 단위 간 import 금지).

- `print()` 금지. 모든 로그는 표준 logger 로만 나간다 (3.10절).
- **기록 허용 필드 화이트리스트만** 통과시키고, 값은 `extra` 로만 넘긴다 (3.8절).
  내보내기 경로에는 문서 원문이 그대로 들어오므로(그게 변환 대상이다) 로그가 특히
  위험하다 — 문단 수·건수 같은 집계값만 남긴다.
- 허용 목록 밖 필드는 **이름만** 남기고 값은 버린다 (호출부 실수를 드러내되 내용은 안 새게).
"""

import logging

# 3.8절 기록 허용 필드. 이 목록을 늘리려면 가이드 근거가 있어야 한다.
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

_log = logging.getLogger("sfr018_export")


def configure_logging(level: str = "INFO") -> None:
    """코드 서빙 진입점에서 한 번 호출한다.

    핸들러가 이미 있으면 basicConfig 는 아무것도 하지 않으므로 중복 호출이 안전하다.
    """
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))


def _prepare(message: str, event: str, fields: dict) -> tuple[str, dict]:
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
