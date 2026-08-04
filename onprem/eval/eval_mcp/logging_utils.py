"""평가 MCP 로깅 유틸 — 가이드 3.7/3.8/3.10 (GENOS_RULES §C) 준수 계층.

세 배포 단위(`template_fill`/`text_polish`/`translation_pipeline`)의 logging_utils 와
같은 계약이다. 배포 단위 간 import 금지 규칙 때문에 사본으로 둔다.

- **기록 허용 필드 화이트리스트만** 통과시키고, 값은 `extra` 로만 넘긴다.
  평가 입력에는 문서 원문·사용자 질문·LLM 응답 전문이 그대로 들어오므로
  (그게 평가 대상이다) 로그 경로가 특히 위험하다. 지표 값·건수만 남긴다.
- **stdio MCP 는 stdout 을 전송 채널로 쓴다.** 로그가 stdout 으로 나가면 프로토콜이
  깨지므로 핸들러를 stderr 로 고정한다 (§C: JS stdio MCP `console.log` 금지와 같은 이유).
- 평가지표 영역 계약: 오류는 객체로 반환하지 않고 **로그를 남긴 뒤 예외를 던진다**
  (CLAUDE.md §1, GENOS_RULES A.4). 그 경로는 error_codes.fail() 하나로 통일한다.
"""

import logging
import sys

# 3.8절 기록 허용 필드
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

_log = logging.getLogger("genon_eval")


def configure_stderr_logging(level: str = "INFO") -> None:
    """stdout 오염 없이 로그를 내보내도록 stderr 핸들러를 붙인다.

    stdio 전송에서 stdout 은 JSON-RPC 프레임 전용이다. 서버 진입점에서 한 번 호출한다.
    """
    if _log.handlers:
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    _log.addHandler(handler)
    _log.setLevel(getattr(logging, level.upper(), logging.INFO))
    _log.propagate = False  # 루트 핸들러가 stdout 이어도 새지 않게


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
