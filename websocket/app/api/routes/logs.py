import asyncio
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from ...core import log_buffer, conv_events

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/history")
async def logs_history(limit: int = 500, before_id: int | None = None):
    return log_buffer.get_history(limit, before_id)


@router.get("/stream")
async def logs_stream():
    q = log_buffer.subscribe()

    async def stream():
        try:
            while True:
                try:
                    entry = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            return
        finally:
            log_buffer.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/conversations/stream")
async def conversations_stream():
    """会话消息实时增量流：每当有新消息落库（买家/AI/人工/系统）即推一条事件。
    前端据 conversation_id 决定追加到当前对话框 / 更新列表 / 拉新会话。"""
    q = conv_events.subscribe()

    async def stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            return
        finally:
            conv_events.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream")
