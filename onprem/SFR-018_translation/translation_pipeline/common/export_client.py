"""내보내기 코드 서빙 호출 클라이언트 (번역 → SFR-018_export).

원본 hwpx 업로드는 클라이언트가 내보내기 서비스 `/prepare` 로 하고, 번역은 `session_id`
로 문단을 가져와 번역한 뒤 결과를 돌려준다. 전처리기 마크다운을 쓰지 않는 이유는 그것이
원본 hwpx 문단과 1:1 이 아니어서 되쓰기 좌표로 쓸 수 없기 때문이다.

`text_polish/export_client.py` 와 같은 계약의 사본이다 (배포 단위 간 import 금지).

가이드 준수:
- 10장: 다른 배포 단위는 **Gateway 경유**로 호출한다. K8s service DNS 직접 호출 금지.
- 3.6절: timeout 명시. 재시도는 하지 않는다 (실패 시 기존 경로로 degrade).
- 3.8절: 문단 내용을 로그에 남기지 않는다.
"""

import os

import httpx

from translation_pipeline.common.logging_utils import log_info, log_warning

_TIMEOUT = float(os.environ.get("EXPORT_CLIENT_TIMEOUT", "10"))


def _base_url() -> str:
    """내보내기 서비스 베이스 URL. 기본은 Gateway 표준 경로."""
    override = (os.environ.get("EXPORT_BASE_URL") or "").strip().rstrip("/")
    if override:
        return override
    genos_url = (os.environ.get("GENOS_URL") or "").strip().rstrip("/")
    serving_id = (os.environ.get("EXPORT_SERVING_ID") or "").strip()
    if not genos_url or not serving_id:
        return ""
    return f"{genos_url}/api/gateway/code_serving/{serving_id}"


def _headers() -> dict:
    token = (os.environ.get("GENOS_TOKEN") or "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def configured() -> bool:
    return bool(_base_url())


async def fetch_paragraphs(session_id: str, trace_id: str = "") -> dict:
    """세션에 준비된 원본 문단 배열을 가져온다. 실패 시 found: False 로 degrade."""
    base = _base_url()
    empty = {"found": False, "source_kind": "", "paragraphs": []}
    if not base:
        return empty
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                f"{base}/paragraphs", params={"session_id": session_id}, headers=_headers()
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        log_warning(
            "내보내기 문단 조회 실패",
            event="export_fetch_failed",
            resource_id="export",
            error_type=type(exc).__name__,
            trace_id=trace_id or None,
        )
        return empty
    except ValueError as exc:
        log_warning(
            "내보내기 문단 응답 형식 오류",
            event="export_fetch_bad_payload",
            resource_id="export",
            error_type=type(exc).__name__,
            trace_id=trace_id or None,
        )
        return empty

    if not isinstance(payload, dict) or not isinstance(payload.get("paragraphs"), list):
        log_warning(
            "내보내기 문단 응답 스키마 불일치",
            event="export_fetch_schema_mismatch",
            resource_id="export",
            trace_id=trace_id or None,
        )
        return empty
    return {
        "found": bool(payload.get("found")),
        "source_kind": str(payload.get("source_kind") or ""),
        "paragraphs": payload["paragraphs"],
    }


async def push_results(session_id: str, results: dict, trace_id: str = "") -> bool:
    """번역한 문단을 세션에 저장한다. 화면에 보여준 값과 같은 값을 보낸다."""
    base = _base_url()
    if not base or not results:
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{base}/results",
                json={
                    "session_id": session_id,
                    "results": {str(k): v for k, v in results.items()},
                },
                headers=_headers(),
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        log_warning(
            "내보내기 결과 저장 실패",
            event="export_push_failed",
            resource_id="export",
            error_type=type(exc).__name__,
            trace_id=trace_id or None,
        )
        return False
    log_info(
        "내보내기 결과 저장 완료",
        event="export_push_completed",
        resource_id="export",
        item_count=len(results),
        trace_id=trace_id or None,
    )
    return True
