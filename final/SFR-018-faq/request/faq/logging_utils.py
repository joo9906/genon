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
import os
import sys

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

_LOGGER_NAME = "faq"
_log = logging.getLogger(_LOGGER_NAME)


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


# ─────────────────────────────────────────────────────────────
# 디버그 에코 — **테스트 기간 한정** (2026-09-07)
# ─────────────────────────────────────────────────────────────
# 3.8절 화이트리스트가 값을 버리기 때문에(이름만 남는다) 로그만으로는 **무엇이 왜
# 실패했는지 알 수 없다.** 원인을 찾는 동안에는 버려지는 값까지 보고 싶으니, 표준
# 로그와 **별도로** 한 줄을 더 뿜는다. 로그 경로는 그대로다 — 걷어낼 때 이 블록과
# `debug_echo` 호출만 지우면 원래 규약으로 돌아온다.
#
# - **stdout 이 아니라 stderr 로 쓴다.** stdout 은 MCP·스트리밍의 전송 채널이라 섞이면
#   프로토콜이 깨진다 (3.10절이 print 를 금지하는 실제 이유이고, `check_deploy_contract`
#   가 그것을 본다).
# - `GENON_DEBUG=0` 이면 조용해진다. **기본은 켜짐** — 지금은 원인 추적이 목적이다.
# - 값은 `_DEBUG_MAX_VALUE` 로 자른다. 문서 원문·프롬프트가 통째로 실리면 이 에코 자체가
#   유출 경로가 된다(3.8절). 자르는 것으로 충분하지 않은 값은 애초에 넘기지 않는다.
_DEBUG_MAX_VALUE = 300


def debug_enabled() -> bool:
    return (os.environ.get("GENON_DEBUG") or "1").strip().lower() not in {"0", "false", "off"}


def debug_echo(message: str, *, event: str = "", **fields) -> None:
    """화이트리스트를 지나지 않은 값까지 stderr 로 한 줄 뿜는다 (테스트 기간 한정)."""
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
    _log.info(text, extra=extra)


def log_warning(message: str, *, event: str, **fields) -> None:
    debug_echo(f"WARNING {message}", event=event, **fields)
    text, extra = _prepare(message, event, fields)
    _log.warning(text, extra=extra)


def log_error(message: str, *, event: str, **fields) -> None:
    debug_echo(f"ERROR {message}", event=event, **fields)
    text, extra = _prepare(message, event, fields)
    _log.error(text, extra=extra)
