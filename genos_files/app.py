"""Internal MCP 상담사 서비스를 위한 FastAPI 런타임 호환 진입점."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request

from service import service as customer_service


app: FastAPI = FastAPI(title="Samsung-Card Customer Agent")


@app.get("")
@app.get("/health")
async def health() -> dict[str, str]:
    """배포 헬스체크용 서비스 상태를 반환한다."""
    return {"status": "ok"}


@app.post("/json")
@app.post("/chat")
async def chat_json(request: Request) -> Any:
    """채팅 payload를 받아 service.service로 위임한다."""
    payload = await request.json()
    config: dict = {}

    if isinstance(payload, dict):
        config = {
            "accessToken": payload.get("Authorization", "")
        }
        _access_token = config["accessToken"]
        print(f"[app.chat_json] request.accessToken: {_access_token}")

    return await customer_service(config, payload if isinstance(payload, dict) else {})
