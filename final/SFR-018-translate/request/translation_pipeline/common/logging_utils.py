"""공용 로깅 유틸 — 가이드 3.7/3.8/3.10 (GENOS_RULES §C) 준수 계층.

배포 단위마다 같은 계약의 사본을 둔다 (단위 간 import 금지).

- `print()` 금지. 모든 로그는 표준 logger 로만 나간다 (3.10절).
- 형식은 GenOS 런타임 로거와 같고 stdout 으로 낸다. 허용 필드는 줄 끝에
  `| event=… trace_id=…` 로 붙는다.
- **기록 허용 필드 화이트리스트만 통과시킨다** (3.8절).
- 값은 반드시 `extra` 필드로 넘기고 **메시지 문자열에 f-string 으로 끼워 넣지 않는다.**
  문자열에 섞인 값은 걸러낼 방법이 없어 화이트리스트가 무력해진다
  (문서 원문·질문·LLM 응답 전문·시크릿이 새는 실제 경로가 여기다).
- 허용 목록 밖 필드는 **이름만** 메시지 끝에 남기고 값은 버린다. 조용히 지우면
  호출부가 기록됐다고 착각한다 (실패 침묵 처리 금지 컨벤션).
"""

import logging
import os
import sys

# 3.8절 기록 허용 필드. 이 목록을 늘리려면 가이드 근거가 있어야 한다.
ALLOWED_FIELDS = (
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
)

_LOGGER_NAME = "translation_pipeline"
_log = logging.getLogger(_LOGGER_NAME)

# GenOS 런타임 로거(`common/logger.py`)와 같은 형식이다. 그 형식은 `extra` 를 찍지 않으므로
# 허용 필드는 포매터가 줄 끝에 `| event=… trace_id=…` 로 붙인다 — 붙이지 않으면 필드가
# 로그 화면에서 사라져 `trace_id` 로 요청을 묶을 수 없다.
_FORMAT = "%(levelname)s: %(asctime)s|[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S %Z"


class _FieldFormatter(logging.Formatter):
    def formatMessage(self, record: logging.LogRecord) -> str:
        line = super().formatMessage(record)
        pairs = [
            f"{key}={' '.join(str(getattr(record, key)).split())}"
            for key in ALLOWED_FIELDS
            if getattr(record, key, None) is not None
        ]
        return f"{line} | {' '.join(pairs)}" if pairs else line


def _level(name) -> int:
    level = logging.getLevelName(str(name or "INFO").strip().upper())
    return level if isinstance(level, int) else logging.INFO


if not _log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(_FieldFormatter(_FORMAT, _DATEFMT))
    _log.addHandler(_handler)
    # 루트로 올리지 않는다 — 런타임 루트 핸들러가 같은 줄을 한 번 더 찍는다.
    _log.propagate = False
_log.setLevel(_level(os.environ.get("LOG_LEVEL")))


def configure_logging(level: str = "INFO") -> None:
    """코드 서빙 진입점에서 한 번 호출한다. **이 단위의 로거 레벨만** 정한다.

    루트 로거는 건드리지 않는다. 루트를 INFO 로 내리면 httpx 가 요청마다 내부 URL 을
    INFO 로 남긴다(3.8절 기록 금지 항목). 단위 안의 모듈 로거
    (`logging.getLogger(__name__)`)는 이 로거의 자식이라 같은 핸들러·레벨을 탄다.
    """
    _log.setLevel(_level(level))


def _prepare(message: str, event: str, fields: dict) -> tuple[str, dict]:
    extra: dict = {"event": event}
    dropped = []
    for key, value in fields.items():
        if key == "event" or key not in ALLOWED_FIELDS:
            # 값은 남기지 않고 필드명만 — 호출부 실수를 드러내되 내용은 새지 않게
            dropped.append(key)
            continue
        if value is not None:
            extra[key] = value
    if dropped:
        message = f"{message} [dropped_fields={','.join(sorted(dropped))}]"
    return message, extra


# ─────────────────────────────────────────────────────────────
# 디버그 에코
# ─────────────────────────────────────────────────────────────
# 3.8절 화이트리스트가 값을 버리기 때문에(이름만 남는다) 로그만으로는 무엇이 왜
# 실패했는지 알 수 없다. 버려지는 값까지 보고 싶을 때를 위해 표준 로그와 별도로
# 한 줄을 더 뿜는다.
#
# - 표준 로그와 섞이지 않게 **stderr** 로 쓴다. 플랫폼은 stdout·stderr 를 둘 다 수집한다.
# - **`GENON_DEBUG=1` 일 때만 낸다(기본 꺼짐).** 허용 필드 밖 값이 남으므로 운영에서
#   켜 두지 않는다.
# - 값은 `_DEBUG_MAX_VALUE` 로 자른다. 문서 원문·프롬프트가 통째로 실리면 이 에코 자체가
#   유출 경로가 된다(3.8절). 자르는 것으로 충분하지 않은 값은 애초에 넘기지 않는다.
_DEBUG_MAX_VALUE = 300


def debug_enabled() -> bool:
    return (os.environ.get("GENON_DEBUG") or "").strip().lower() in {"1", "true", "on"}


def debug_echo(message: str, *, event: str = "", **fields) -> None:
    """화이트리스트를 지나지 않은 값까지 stderr 로 한 줄 뿜는다."""
    if not debug_enabled():
        return
    parts = [f"event={event}"] if event else []
    for key, value in fields.items():
        text = str(value)
        if len(text) > _DEBUG_MAX_VALUE:
            text = f"{text[:_DEBUG_MAX_VALUE]}…(+{len(text) - _DEBUG_MAX_VALUE}자)"
        parts.append(f"{key}={text}")
    sys.stderr.write(f"[DEBUG {_LOGGER_NAME}] {message} | {' '.join(parts)}\n")
    sys.stderr.flush()


def log_info(message: str, *, event: str, **fields) -> None:
    text, extra = _prepare(message, event, fields)
    _log.info(text, extra=extra, stacklevel=2)


def log_warning(message: str, *, event: str, **fields) -> None:
    debug_echo(f"WARNING {message}", event=event, **fields)
    text, extra = _prepare(message, event, fields)
    _log.warning(text, extra=extra, stacklevel=2)


def log_error(message: str, *, event: str, **fields) -> None:
    debug_echo(f"ERROR {message}", event=event, **fields)
    text, extra = _prepare(message, event, fields)
    _log.error(text, extra=extra, stacklevel=2)
