from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.responses import StreamingResponse
from app.api.deps import get_current_user
from app.core.security import decode_token
from common.core import settings
import aiohttp

router = APIRouter(prefix="/logs/runtime", tags=["runtime-logs"])


def _verify_token_param(token: str = Query(None)):
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return payload["sub"]


@router.get("/history", dependencies=[Depends(get_current_user)])
async def runtime_logs_history(limit: int = 500, before_id: int | None = None):
    url = f"{settings.WEBSOCKET_SERVICE_URL}/api/logs/history?limit={limit}"
    if before_id is not None:
        url += f"&before_id={before_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()


@router.get("/stream", dependencies=[Depends(_verify_token_param)])
async def runtime_logs_stream():
    url = f"{settings.WEBSOCKET_SERVICE_URL}/api/logs/stream"

    # SSE 是永不结束的长流，aiohttp 默认 total=300s 会按时砍断（不看有无数据流动），
    # 导致代理层每 5 分钟断一次。total=None 取消总超时，仅保留连接超时。
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=10)

    async def proxy_stream():
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                async for line in resp.content:
                    yield line

    return StreamingResponse(proxy_stream(), media_type="text/event-stream")
