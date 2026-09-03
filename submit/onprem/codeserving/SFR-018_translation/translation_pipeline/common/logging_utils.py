"""공용 로깅 유틸 — 가이드 3.7/3.8/3.10 (GENOS_RULES §C) 준수 계층.

- `print()` 금지. 모든 로그는 표준 logger 로만 나간다 (3.10절).
- **기록 허용 필드 화이트리스트만 통과시킨다** (3.8절):
  `event, trace_id, request_id, resource_id, status, duration_ms, item_count,
  upstream_status, error_code, error_type`
- 값은 반드시 `extra` 필드로 넘기고 **메시지 문자열에 f-string 으로 끼워 넣지 않는다.**
  문자열 안에 섞인 값은 걸러낼 방법이 없어 화이트리스트가 무력해지기 때문이다
  (문서 원문·사용자 질문·LLM 응답 전문·시크릿이 새는 실제 경로가 여기다).
- 허용 목록 밖 필드는 **이름만** 메시지 끝에 남기고 값은 버린다. 조용히 지우면
  호출부가 기록됐다고 착각한다 (실패 침묵 처리 금지 컨벤션).
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

_log = logging.getLogger("translation_pipeline")


def configure_logging(level: str = "INFO") -> None:
    """코드 서빙 진입점에서 한 번 호출한다 (워크플로우 영역은 GenOS 가 이미 설정한다).

    핸들러가 이미 있으면 basicConfig 는 아무것도 하지 않으므로 중복 호출이 안전하다.
    stdout 으로 직접 쓰는 print 는 금지(3.10절)이고, 여기서도 쓰지 않는다.
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
        # 값은 남기지 않고 필드명만 — 호출부 실수를 드러내되 내용은 새지 않게
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
