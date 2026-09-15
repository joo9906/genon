"""결과 파일을 GenOS MinIO 에 올리고 **다운로드 링크**를 받는다 (2026-08-28 신규).

## 왜 파일 본문을 응답에 싣지 않게 됐나

그전에는 화면이 정본 텍스트를 들고 있다가 내려받기 버튼에서 `POST /download` 로
**되돌려 보냈다.** 그래서 payload 에 태그 없는 정본이 한 벌 더 실렸고, 표시용 사본과
정본이 같은 응답에 섞여 "어느 것이 파일이 되는 값인가" 를 주석으로 설명해야 했다.

지금은 결과를 만들 때 **여기서 파일로 굳혀 올리고 링크만 싣는다.** 정본은 이 모듈
안에서만 쓰이고 밖으로 나가지 않는다.

## 실패해도 결과를 버리지 않는다 (fail-open)

업로드 실패는 다듬기·번역이 실패한 것과 다른 사건이다. 결과는 그대로 내보내고
`download_url` 을 `None` 으로 둬서 **화면이 "파일로 받을 수 없다" 를 말할 수 있게** 한다.
예외를 올리면 잘 만들어진 결과가 통째로 버려진다.

## 참고 코드를 그대로 옮기지 않은 세 가지

운영 MCP 예제(`generate_word_report_general_version`)가 이 서비스를 쓰는데, 그 코드를
배포 단위에 그대로 옮기면 안 된다:

1. **동기 `urllib` → `httpx.AsyncClient`.** async 라우트에서 동기 HTTP 를 부르면 그
   워커의 이벤트 루프가 업로드 내내 멈춘다 (가이드 3.4).
2. **예외 원문을 반환하지 않는다.** 예제는 `f"오류 발생: {e}"` 를 돌려주는데, 그 문자열에
   내부 URL 과 스택이 실린다 (3.8절 위반). 여기서는 사유를 **분류값**으로만 남긴다.
3. **임시 파일을 만들지 않는다.** 우리 산출물은 메모리 위의 바이트라 디스크를 거칠
   이유가 없다. 예제는 `delete=False` 로 만들고 예외 경로에서 지우지 않아 파일이 남는다.

## 호스트를 코드에 적지 않는다

`GENOS_CDN_UPLOAD_URL` 은 K8s 서비스 DNS 를 직접 가리킨다. 가이드 11.5.8 이 금지하는
것은 **LLM·MCP·코드서빙** 호출이고 CDN 업로드는 게이트웨이 경로가 없어 예외이지만,
그렇더라도 주소는 환경변수로 둔다 (§3.7 — 배포마다 달라지는 값).
"""

import os

import httpx

from translation_pipeline.common.logging_utils import log_info, log_warning

_DEFAULT_UPLOAD_URL = "http://llmops-cdn-api-service:8080/minio/upload/temp"
_DEFAULT_HOSTNAME = "https://genos.genon.ai"

# 업로드는 결과 전달의 곁가지다. 오래 붙들면 다 만든 결과가 늦게 나간다.
_CONNECT_TIMEOUT = 3.0
_READ_TIMEOUT = 20.0


def upload_url() -> str:
    return (os.environ.get("GENOS_CDN_UPLOAD_URL", "") or _DEFAULT_UPLOAD_URL).strip()


def public_hostname() -> str:
    """presigned URL 에 박히는 외부 호스트. 업로드 폼의 `hostname` 필드로 넘어간다."""
    return (os.environ.get("GENOS_CDN_HOSTNAME", "") or _DEFAULT_HOSTNAME).strip()


async def upload_bytes(data: bytes, filename: str, media_type: str) -> str:
    """파일 한 개를 올리고 presigned URL 을 돌려준다. **실패하면 빈 문자열.**

    Returns:
        다운로드 링크. 올리지 못했으면 `""` — 호출부는 이 값을 `download_url` 로
        그대로 싣고(빈 값이면 `None`), 결과 자체는 정상으로 내보낸다.
    """
    url = upload_url()
    if not url or not data:
        log_warning(
            "결과 파일을 올리지 못했다 — 링크 없이 결과만 전달",
            event="file_upload_skipped",
            status="not_configured" if not url else "empty_body",
        )
        return ""

    timeout = httpx.Timeout(connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=10.0, pool=3.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                data={"hostname": public_hostname()},
                files={"file": (filename, data, media_type)},
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        # 상태코드만 남긴다 — 본문에 내부 경로가 실릴 수 있다 (3.8절).
        log_warning(
            "결과 파일 업로드 실패 — 링크 없이 결과만 전달",
            event="file_upload_failed",
            upstream_status=exc.response.status_code,
            error_type=type(exc).__name__,
            status="degraded",
        )
        return ""
    except Exception as exc:  # noqa: BLE001 — 업로드 실패가 결과를 버리게 두지 않는다
        log_warning(
            "결과 파일 업로드 실패 — 링크 없이 결과만 전달",
            event="file_upload_failed",
            error_type=type(exc).__name__,
            status="degraded",
        )
        return ""

    link = ""
    if isinstance(payload, dict):
        body = payload.get("data")
        if isinstance(body, dict):
            link = str(body.get("presigned_url") or "").strip()
    if not link:
        # 200 인데 링크가 없는 경우 — 응답 모양이 바뀌면 조용히 빈 링크가 나간다.
        # 그 사실을 사건으로 남겨야 "왜 다운로드가 안 되나" 를 답할 수 있다.
        log_warning(
            "업로드 응답에 presigned_url 이 없다 — 링크 없이 결과만 전달",
            event="file_upload_no_url",
            status="degraded",
        )
        return ""

    log_info(
        "결과 파일 업로드 완료",
        event="file_upload_completed",
        status=f"bytes={len(data)}",
    )
    return link
