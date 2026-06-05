from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.responses import StreamingResponse
from app.core.security import decode_token
from common.core import settings
import aiohttp

router = APIRouter(prefix="/logs", tags=["conversation-stream"])


def _verify_token_param(token: str = Query(None)):
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return payload["sub"]


@router.get("/conversations/stream", dependencies=[Depends(_verify_token_param)])
async def conversations_stream():
    """代理到 websocket 服务的会话消息实时增量流。
    EventSource 无法带 Authorization 头，故走 query-param token 鉴权（同运行时日志流）。"""
    url = f"{settings.WEBSOCKET_SERVICE_URL}/api/logs/conversations/stream"

    # SSE 是永不结束的长流，aiohttp 默认 total=300s 会按时砍断（不看有无数据流动），
    # 导致代理层每 5 分钟断一次。total=None 取消总超时，仅保留连接超时。
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=10)

    async def proxy_stream():
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                async for line in resp.content:
                    yield line

    return StreamingResponse(proxy_stream(), media_type="text/event-stream")
