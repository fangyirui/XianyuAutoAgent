import asyncio
from collections import deque
from datetime import datetime
from typing import List, Optional

_buffer: deque = deque(maxlen=5000)
_subscribers: List[asyncio.Queue] = []
_seq = 0  # 全局自增序号，作为日志游标（进程内单调递增；重启清零，与缓冲一同重置）


def sink(message):
    global _seq
    record = message.record
    _seq += 1
    entry = {
        "id": _seq,
        "time": record["time"].strftime("%Y-%m-%d %H:%M:%S"),
        "level": record["level"].name,
        "message": record["message"],
        "module": record["module"],
    }
    _buffer.append(entry)
    for q in list(_subscribers):
        try:
            q.put_nowait(entry)
        except asyncio.QueueFull:
            pass


def get_history(limit: int = 500, before_id: Optional[int] = None) -> dict:
    """返回最近一页日志（按 id 升序）。before_id 时只取更早的，用于向上翻页。
    has_more 表示在本页之外是否还有更早的日志（受环形缓冲上限 5000 约束）。"""
    items = list(_buffer)
    if before_id is not None:
        items = [e for e in items if e["id"] < before_id]
    has_more = len(items) > limit
    return {"items": items[-limit:], "has_more": has_more}


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue):
    try:
        _subscribers.remove(q)
    except ValueError:
        pass
