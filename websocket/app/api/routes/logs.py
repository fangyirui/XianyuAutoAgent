import asyncio
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from ...core import log_buffer

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/history")
async def logs_history(limit: int = 200):
    return log_buffer.get_history(limit)


@router.get("/stream")
async def logs_stream():
    q = log_buffer.subscribe()

    async def event_generator():
        try:
            while True:
                entry = await asyncio.wait_for(q.get(), timeout=30)
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"
        except asyncio.CancelledError:
            return
        finally:
            log_buffer.unsubscribe(q)

    async def stream():
        while True:
            async for chunk in event_generator():
                yield chunk

    return StreamingResponse(stream(), media_type="text/event-stream")
