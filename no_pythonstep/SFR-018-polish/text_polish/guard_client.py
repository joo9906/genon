"""결정적 점검 — MCP `genon_text_guard` 의 구조·사실 대조를 부른다.

`POST /chat` 은 워크플로우 스텝 2 가 하던 점검을 이 서빙에서 직접 한다. 판정 코드를 이
단위에 복사하지 않고 **같은 MCP 를 부른다** — 사본을 두면 번역·FAQ 와 같은 질문에 다른
답이 나오고, 그 어긋남은 오류로 드러나지 않는다.

- `markdown_structure_issues`: 표·제목·코드펜스 훼손
- `fact_issues`: 숫자·날짜 누락·변경

**되돌리지 않고 경고만 낸다.** 점검 호출이 실패해도 결과는 그대로 나가고(fail-open),
침묵하지 않도록 `text_guard_call_failed` 로 남긴다. `TEXT_GUARD_MCP_ID` 가 비어 있으면
부르지 않고 `text_guard_unconfigured` 를 남긴다.
"""

import asyncio
import json
import os

import httpx

from .config import Config
from .logging_utils import log_warning

GUARD_TOOLS = ("markdown_structure_issues", "fact_issues")

_CONNECT_TIMEOUT = 3.0
_READ_TIMEOUT = 15.0
_MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _mcp_url(serving_id: str) -> str:
    """`/api/gateway` prefix 는 `llm._chat_url` 과 같은 규칙으로 붙인다."""
    base = Config.genos_url()
    prefix = "" if base.endswith("/api/gateway") else "/api/gateway"
    return f"{base}{prefix}/mcp/{serving_id}/mcp"


def _decode_body(response):
    """MCP 는 JSON 한 덩어리 또는 SSE 프레임으로 답한다. 둘 다 JSON-RPC 객체로 되돌린다."""
    ctype = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype != "text/event-stream":
        return response.json()
    text = (response.text or "").replace("\r\n", "\n")
    for block in text.split("\n\n"):
        data = "\n".join(
            line.split(":", 1)[1].strip() for line in block.splitlines() if line.startswith("data:")
        ).strip()
        if not data:
            continue
        try:
            frame = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(frame, dict) and ("result" in frame or "error" in frame):
            return frame
    raise ValueError("no JSON-RPC frame")


async def _call(client: httpx.AsyncClient, url: str, tool: str, source: str, revised: str):
    """도구 1회 호출 → `issues` 목록. 실패하면 `None` (로그는 호출부가 남긴다)."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": {"source": source, "revised": revised}},
    }
    response = await client.post(url, json=payload)
    if response.status_code >= 400:
        return None, ("HTTPStatusError", response.status_code)
    try:
        body = _decode_body(response)
    except ValueError:
        return None, ("InvalidJson", response.status_code)
    if not isinstance(body, dict) or body.get("error"):
        return None, ("MCP_TOOL_ERROR", None)
    contents = (body.get("result") or {}).get("content") or []
    text = "".join(
        str(item.get("text") or "")
        for item in contents
        if isinstance(item, dict) and item.get("type") == "text"
    )
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None, ("InvalidJson", None)
    if not isinstance(parsed, dict):
        return None, ("InvalidJson", None)
    return [str(issue) for issue in (parsed.get("issues") or [])], None


async def check(source: str, revised: str) -> dict:
    """`{도구 이름: issues 목록}`. 부르지 못한 도구는 빈 목록이다."""
    results = {tool: [] for tool in GUARD_TOOLS}
    serving_id = (os.environ.get("TEXT_GUARD_MCP_ID") or "").strip()
    try:
        # `genos_token()` 은 값이 없으면 예외다 — 점검 설정 부재가 다듬은 결과를 막지 않게 한다
        token = Config.genos_token() if serving_id and Config.genos_url() else ""
    except RuntimeError:
        token = ""
    if not token:
        log_warning(
            "결정적 점검 서빙이 설정되지 않아 점검 없이 전달한다",
            event="text_guard_unconfigured",
            resource_id="genon_text_guard",
            status="degraded",
        )
        return results

    url = _mcp_url(serving_id)
    headers = {**_MCP_HEADERS, "Authorization": f"Bearer {token}"}
    timeout = httpx.Timeout(
        connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=5.0, pool=_CONNECT_TIMEOUT
    )
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        outcomes = await asyncio.gather(
            *(_call(client, url, tool, source, revised) for tool in GUARD_TOOLS),
            return_exceptions=True,
        )
    for tool, outcome in zip(GUARD_TOOLS, outcomes):
        if isinstance(outcome, BaseException):
            failure = (type(outcome).__name__, None)
            issues = None
        else:
            issues, failure = outcome
        if issues is None:
            log_warning(
                "결정적 점검 호출 실패 — 결과는 그대로 전달",
                event="text_guard_call_failed",
                resource_id=tool,
                error_type=failure[0],
                upstream_status=failure[1],
                status="degraded",
            )
            continue
        results[tool] = issues
    return results
