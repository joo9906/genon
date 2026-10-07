# =====================================================================================
# genon_template_draft — 템플릿 채우기(SFR-006) 초안 찍어 보기 MCP 도구 (area 01)
#
# **이 파일 하나가 등록 단위다.** GenOS MCP 는 소스 파일 한 개를 받아 실행하며,
# `mcp` 객체를 런타임이 전역으로 주입한다. 모든 최상위 심볼에 `TD` 접두어를 붙였다.
#
# ## 무엇을 하나
#
# 006 서빙의 다운로드 경로 `POST /generate` 를 불러 **지금까지 모인 값으로 hwpx 초안**을
# 만들고, 받은 파일을 GenOS CDN(MinIO)에 올려 **다운로드 링크**(`download_url`)를 돌려준다.
# MCP 결과는 JSON 문자열이라 바이너리를 그대로 실을 수 없다. 업로드는 서빙의
# `file_store.py` 와 같은 주소·폼(`file` + `hostname`)이다.
#
# **`session_id` 를 주면 그 세션은 끝난다** — `/generate` 는 다운로드 버튼용이라 생성 성공이
# 곧 세션 종료다. 대화를 이어 가며 찍어 보려면 `session_id` 없이 `template_id` + `values`
# 로 부른다(세션을 건드리지 않는다).
#
# ## 왜 채우기를 여기서 하지 않나
#
# hwpx 채우기(슬롯 · 서식 · 반복 묶음 · 본문 블록)는 006 서빙의 `document.build` 한 벌이
# 정본이다. 여기서 다시 구현하면 hwpx 파싱 사본이 하나 더 늘고(이미 5벌이다), 다운로드 파일과
# 초안이 다른 규칙으로 만들어질 수 있다. 그래서 이 파일은 **부르기만 한다** —
# MCP 파일은 stdlib 만 쓰는 규약이라 lxml 도 없다.
#
# ## 부르는 길
#
# 워크플로우 스텝과 같은 게이트웨이 경로다:
# `{GENOS_URL}/api/gateway/code_serving/{TEMPLATE_FILL_SERVING_ID}/generate`,
# `Authorization: Bearer {GENOS_TOKEN}`. `GENOS_URL` 이 이미 `/api/gateway` 로 끝나면
# 중복시키지 않는다(루트 CLAUDE.md 의 URL 조립 규약). 채운 항목·미입력 항목은 응답 헤더
# (`X-Written-Fields` · `X-Missing-Fields` · `X-Body-Blocks`, URL 인코딩)로 온다.
#
# CDN 업로드는 게이트웨이 경로가 없어 K8s 서비스 주소를 직접 부른다(가이드 11.5.8 의 예외 —
# `file_store.py` 머리말). 주소는 `GENOS_CDN_UPLOAD_URL` · `GENOS_CDN_HOSTNAME` 환경변수다.
#
# **설치가 필요한 패키지를 쓰지 않는다.** stdlib 만으로 돈다 (`urllib`).
# =====================================================================================

import json
import logging
import os
import uuid
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ── 로깅 ─────────────────────────────────────────
# 3.8절 기록 허용 필드. 항목 값·세션 id 는 로그에 남기지 않는다.
TDALLOWED_FIELDS = frozenset(
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

_TDlog = logging.getLogger("genon_template_draft")


def _TDsetup_logging() -> None:
    """이 파일 전용 **stderr** 핸들러. stdout 은 MCP 전송 채널이 될 수 있다(README §0)."""
    if _TDlog.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    _TDlog.addHandler(handler)
    _TDlog.setLevel(logging.INFO)
    _TDlog.propagate = False


_TDsetup_logging()


def _TDprepare(message: str, event: str, fields: dict) -> tuple:
    extra: dict = {"event": event}
    dropped = []
    for key, value in fields.items():
        if key == "event" or key not in TDALLOWED_FIELDS:
            dropped.append(key)
            continue
        if value is not None:
            extra[key] = value
    if dropped:
        message = f"{message} [dropped_fields={','.join(sorted(dropped))}]"
    return message, extra


def tdlog_info(message: str, *, event: str, **fields) -> None:
    text, extra = _TDprepare(message, event, fields)
    _TDlog.info(text, extra=extra)


def tdlog_warning(message: str, *, event: str, **fields) -> None:
    text, extra = _TDprepare(message, event, fields)
    _TDlog.warning(text, extra=extra)


# ── mcp shim ─────────────────────────────────────
try:
    mcp  # noqa: F821 - 런타임이 주입한다
except NameError:
    class _TDLocalMCP:
        def tool(self, *args, **kwargs):
            def _decorator(fn):
                return fn
            return _decorator

    mcp = _TDLocalMCP()


# ── 설정 ─────────────────────────────────────────
_TDDEFAULT_TIMEOUT = 60.0      # 초 — 조립. 템플릿은 1~2쪽이라 넉넉하다
_TDDEFAULT_UPLOAD_URL = "http://llmops-cdn-api-service:8080/minio/upload/temp"
_TDDEFAULT_HOSTNAME = "https://genos.genon.ai"
_TDMAX_VALUES = 500            # 직접 넘기는 값 개수 상한 (서빙 쪽 상한과 별개로 먼저 막는다)


class TDDraftError(Exception):
    """도구 실패. `error_type` 은 호출부가 분기에 쓰는 고정 코드다."""

    def __init__(self, error_type: str, upstream_status=None) -> None:
        super().__init__(error_type)
        self.error_type = error_type
        self.upstream_status = upstream_status


def _TDtimeout() -> float:
    raw = (os.environ.get("TEMPLATE_DRAFT_TIMEOUT") or "").strip()
    try:
        value = float(raw) if raw else _TDDEFAULT_TIMEOUT
    except ValueError:
        return _TDDEFAULT_TIMEOUT
    return value if value > 0 else _TDDEFAULT_TIMEOUT


def _TDgenerate_url() -> str:
    """`/generate` 주소. URL 은 이 함수 한 곳에서만 만든다."""
    base = (os.environ.get("GENOS_URL") or "").strip().rstrip("/")
    if not base:
        raise TDDraftError("GENOS_URL_MISSING")
    serving_id = (os.environ.get("TEMPLATE_FILL_SERVING_ID") or "").strip()
    if not serving_id:
        raise TDDraftError("TEMPLATE_FILL_SERVING_ID_MISSING")
    gateway = base if base.endswith("/api/gateway") else f"{base}/api/gateway"
    return f"{gateway}/code_serving/{serving_id}/generate"


def _TDflag(value) -> bool:
    """GenOS 는 빈 값을 `""` 로 준다 — 불리언도 문자열로 올 수 있다."""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("true", "1", "yes", "y")


def _TDvalues(raw) -> dict:
    """값은 객체 또는 JSON 객체 문자열로 받는다. 빈 값은 '없음' 이다."""
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TDDraftError("VALUES_NOT_JSON") from exc
    if not isinstance(raw, dict):
        raise TDDraftError("VALUES_NOT_OBJECT")
    if len(raw) > _TDMAX_VALUES:
        raise TDDraftError("TOO_MANY_VALUES")
    return {str(k): "" if v is None else str(v) for k, v in raw.items()}


def _TDpost(url: str, payload: dict) -> tuple:
    """`(본문 바이트, 응답 헤더)` 를 돌려준다. 성공 응답은 hwpx 바이너리다."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {(os.environ.get('GENOS_TOKEN') or '').strip()}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_TDtimeout()) as response:
            return response.read(), response.headers
    except urllib.error.HTTPError as exc:
        # 서빙이 낸 오류 코드를 그대로 돌려준다 — 404(세션·템플릿 없음)와 5xx 는 할 일이 다르다.
        detail = {}
        try:
            detail = json.loads(exc.read() or b"{}")
        except (ValueError, OSError):
            detail = {}
        code = detail.get("error_code") if isinstance(detail, dict) else None
        raise TDDraftError(str(code or "SERVING_ERROR"), upstream_status=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TDDraftError("SERVING_TRANSPORT_FAILED") from exc


def _TDupload(data: bytes, filename: str) -> str:
    """CDN 에 올리고 presigned URL 을 돌려준다. **실패하면 빈 문자열** — 사유는 로그로만 남긴다."""
    url = (os.environ.get("GENOS_CDN_UPLOAD_URL") or _TDDEFAULT_UPLOAD_URL).strip()
    hostname = (os.environ.get("GENOS_CDN_HOSTNAME") or _TDDEFAULT_HOSTNAME).strip()
    boundary = uuid.uuid4().hex
    quoted = urllib.parse.quote(filename)
    body = b"".join(
        (
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="hostname"\r\n\r\n',
            hostname.encode("utf-8"),
            f"\r\n--{boundary}\r\n".encode(),
            # 한글 파일명은 RFC 5987 로 함께 싣는다 — `filename` 에는 ASCII 만 둔다.
            f'Content-Disposition: form-data; name="file"; filename="{quoted}"; '
            f"filename*=UTF-8''{quoted}\r\n".encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            data,
            f"\r\n--{boundary}--\r\n".encode(),
        )
    )
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TDtimeout()) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # 상태코드만 남긴다 — 본문에 내부 경로가 실릴 수 있다 (3.8절).
        tdlog_warning("초안 업로드 실패", event="template_draft_upload_failed",
                      upstream_status=exc.code, error_type=type(exc).__name__)
        return ""
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        tdlog_warning("초안 업로드 실패", event="template_draft_upload_failed",
                      error_type=type(exc).__name__)
        return ""
    body_data = payload.get("data") if isinstance(payload, dict) else None
    link = str(body_data.get("presigned_url") or "").strip() if isinstance(body_data, dict) else ""
    if not link:
        tdlog_warning("업로드 응답에 presigned_url 이 없다", event="template_draft_upload_failed",
                      error_type="NO_PRESIGNED_URL")
    return link


def _TDheader_list(headers, name: str) -> list:
    raw = urllib.parse.unquote(headers.get(name) or "")
    return [item for item in raw.split(",") if item]


def _TDfilename(headers) -> str:
    """`Content-Disposition: attachment; filename*=UTF-8''<인코딩된 이름>` 에서 이름을 꺼낸다."""
    disposition = headers.get("Content-Disposition") or ""
    _, _, encoded = disposition.partition("filename*=UTF-8''")
    return urllib.parse.unquote(encoded.strip().strip('"'))


def _td_run(arguments: dict) -> str:
    started = time.monotonic()
    session_id = str(arguments.get("session_id") or "").strip()
    template_id = str(arguments.get("template_id") or "").strip()
    try:
        values = _TDvalues(arguments.get("values"))
        if not session_id and not template_id:
            raise TDDraftError("SESSION_OR_TEMPLATE_REQUIRED")
        payload: dict = {}
        if session_id:
            payload["session_id"] = session_id
        if template_id:
            payload["template_id"] = template_id
        if values:
            payload["values"] = values
        filename = str(arguments.get("filename") or "").strip()
        if filename:
            payload["filename"] = filename
        raw, headers = _TDpost(_TDgenerate_url(), payload)
        if not raw.startswith(b"PK"):
            # hwpx 는 ZIP 이다. 프록시 오류 페이지 등이 200 으로 오면 여기서 걸린다.
            raise TDDraftError("SERVING_INVALID_RESPONSE")
    except TDDraftError as exc:
        tdlog_warning(
            "초안을 만들지 못했다",
            event="template_draft_failed",
            resource_id=template_id or None,
            error_type=exc.error_type,
            upstream_status=exc.upstream_status,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        result = {"ok": False, "error_type": exc.error_type}
        if exc.upstream_status is not None:
            result["upstream_status"] = exc.upstream_status
        return json.dumps(result, ensure_ascii=False)

    filename = _TDfilename(headers) or f"{template_id or '초안'}.hwpx"
    link = _TDupload(raw, filename)
    written = _TDheader_list(headers, "X-Written-Fields")
    missing = _TDheader_list(headers, "X-Missing-Fields")
    try:
        body_blocks = int(headers.get("X-Body-Blocks") or 0)
    except ValueError:
        body_blocks = 0
    tdlog_info(
        "초안 생성",
        event="template_draft_done",
        resource_id=template_id or None,
        item_count=len(written),
        status=f"missing={len(missing)} linked={int(bool(link))} session_ended={int(bool(session_id))}",
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return json.dumps(
        {
            "ok": True,
            "template_id": template_id or None,
            "filename": filename,
            # 올리지 못했으면 `null` — 사유는 로그(`template_draft_upload_failed`)에 있다.
            "download_url": link or None,
            "fields_written": written,
            "fields_missing": missing,
            "ready_for_download": not missing,
            "body_blocks": body_blocks,
            "size_bytes": len(raw),
            # `/generate` 는 세션 id 를 받으면 생성 성공과 함께 세션을 끝낸다.
            "session_ended": bool(session_id),
        },
        ensure_ascii=False,
    )


@mcp.tool()
async def template_fill_draft(
    session_id: str = "",
    template_id: str = "",
    values: dict | str | None = None,
    filename: str = "",
) -> str:
    """[언제 쓰나] 템플릿 채우기 내용으로 hwpx 초안을 찍어 볼 때.

    다운로드 버튼과 같은 `/generate` 를 부른다. **`session_id` 를 주면 그 대화 세션은 끝난다**
    — 대화를 이어 가야 하면 `session_id` 없이 `template_id` + `values` 로 부른다.
    미입력 항목이 남아 있어도 만든다(빈 자리는 비워 둔다).

    Args:
        session_id: 템플릿 채우기 대화의 세션 id. 주면 그 세션에 모인 값·본문 추가 내용을 쓰고,
            생성이 끝나면 세션이 종료된다.
        template_id: 템플릿 이름. 세션이 기억하는 템플릿 대신 쓰거나, 세션 없이 찍을 때 준다.
        values: `{항목명: 값}` (JSON 객체 문자열도 받는다). 세션 값 위에 덮어쓴다 — 세션 없이
            값만으로 찍어 볼 수도 있다. 반복 묶음은 `본문 2`·`내용 2-1` 처럼 번호 이름으로 준다.
        filename: 내려받을 파일 이름 (기본 `<템플릿>_초안.hwpx`).

    Returns:
        JSON 문자열 `{"ok", "template_id", "filename", "download_url", "fields_written",
        "fields_missing", "ready_for_download", "body_blocks", "size_bytes", "session_ended"}`.
        `download_url` 이 `null` 이면 초안은 만들었지만 CDN 에 올리지 못한 것이다.
        실패면 `{"ok": false, "error_type"}` — `SESSION_OR_TEMPLATE_REQUIRED` ·
        `VALUES_NOT_JSON` · `VALUES_NOT_OBJECT` · `TOO_MANY_VALUES` · `GENOS_URL_MISSING` ·
        `TEMPLATE_FILL_SERVING_ID_MISSING` · `SERVING_TRANSPORT_FAILED` ·
        `SERVING_INVALID_RESPONSE` · 서빙 오류 코드(`ERR-03-…`, `upstream_status` 동반).
    """
    return _td_run(
        {
            "session_id": session_id,
            "template_id": template_id,
            "values": values,
            "filename": filename,
        }
    )
