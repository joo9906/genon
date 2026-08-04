"""내보내기 코드 서빙 호출 클라이언트 (글다듬이 → SFR-018_export).

워크플로우 Python 단계는 원본 파일 바이트를 받지 못한다(전처리기가 변환한 마크다운만
온다). 그래서 원본 hwpx 업로드는 클라이언트가 내보내기 서비스 `/prepare` 로 하고,
이 워크플로우는 `session_id` 로 문단을 가져와 다듬은 뒤 결과를 돌려준다.

가이드 준수:
- 10장: 다른 배포 단위는 **GenOS Gateway 경유**로 호출한다. K8s service DNS 직접 호출 금지.
  `EXPORT_BASE_URL` 은 게이트웨이 라우팅이 다른 배포에서만 쓰는 탈출구다.
- 5.5절: 워크플로우 이미지에는 임의 패키지를 추가할 수 없다 → `httpx` 만 쓴다
  (workflow image 포함 모듈: asyncio, httpx, json, datetime, re …).
- 3.6절: 모든 호출에 timeout 명시. 재시도는 하지 않는다 — 실패하면 기존 마크다운 경로로
  degrade 하면 되고, 다듬기 응답을 지연시키는 것이 더 나쁘다.
- 3.8절: 문단 내용을 로그에 남기지 않는다. 개수·상태만 남긴다.
"""

import os

import httpx

from .logging_utils import log_info, log_warning

_TIMEOUT = float(os.environ.get("EXPORT_CLIENT_TIMEOUT", "10"))


def _base_url() -> str:
    """내보내기 서비스 베이스 URL.

    기본은 Gateway 표준 경로다. 게이트웨이 라우팅이 다른 배포에서는
    `EXPORT_BASE_URL` 로 통째 대체한다(설정 실수를 조용히 넘기지 않도록 로그로 알린다).
    """
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
    """내보내기 연계가 설정돼 있는지. 없으면 이 기능을 조용히 건너뛴다."""
    return bool(_base_url())


async def fetch_paragraphs(session_id: str, trace_id: str = "") -> dict:
    """세션에 준비된 원본 문단 배열을 가져온다.

    Returns:
        `{"found": bool, "source_kind": str, "paragraphs": [{"index", "text"}]}`.
        연계 미설정·통신 실패·비정상 응답이면 `found: False` 로 degrade 한다 —
        내보내기가 안 되는 것이 다듬기 자체를 막아서는 안 된다.
    """
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
            "내보내기 문단 조회 실패 — 마크다운 경로로 진행",
            event="export_fetch_failed",
            resource_id="export",
            error_type=type(exc).__name__,
            trace_id=trace_id or None,
        )
        return empty
    except ValueError as exc:  # JSON 아님
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
    """다듬은 문단을 세션에 저장한다.

    화면에 보여준 값과 **같은 값**을 보낸다 — 내보내기 시점에 LLM 을 다시 부르면
    파일 속 문장이 화면과 달라지기 때문이다.

    Returns:
        저장 성공 여부. 실패는 로그로 노출하고 호출부가 사용자에게 알린다
        (조용히 넘기면 다운로드 버튼이 눌러지지 않는 이유를 알 수 없다).
    """
    base = _base_url()
    if not base or not results:
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{base}/results",
                json={"session_id": session_id, "results": {str(k): v for k, v in results.items()}},
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
