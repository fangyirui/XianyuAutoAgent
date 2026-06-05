from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.api.deps import get_current_user
from common.core import settings
import aiohttp

router = APIRouter(prefix="/ws", tags=["websocket"], dependencies=[Depends(get_current_user)])


class SendMessageBody(BaseModel):
    text: str


async def _call_ws_service(method: str, path: str, json_body: dict = None) -> dict:
    url = f"{settings.WEBSOCKET_SERVICE_URL}{path}"
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, json=json_body) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=resp.status, detail="WebSocket service error")
            return await resp.json()


@router.get("/status")
async def ws_status():
    return await _call_ws_service("GET", "/api/health/status")


@router.post("/reconnect")
async def ws_reconnect():
    return await _call_ws_service("POST", "/api/control/reconnect")


@router.post("/manual-mode/{chat_id}")
async def toggle_manual_mode(chat_id: str):
    return await _call_ws_service("POST", f"/api/control/manual-mode/{chat_id}")


@router.post("/send-message/{chat_id}")
async def send_message(chat_id: str, body: SendMessageBody):
    return await _call_ws_service(
        "POST", f"/api/control/send-message/{chat_id}", json_body={"text": body.text}
    )
