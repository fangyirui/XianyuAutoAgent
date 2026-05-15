import asyncio
from collections import deque
from datetime import datetime
from typing import List

_buffer: deque = deque(maxlen=500)
_subscribers: List[asyncio.Queue] = []


def sink(message):
    record = message.record
    entry = {
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


def get_history(limit: int = 200) -> List[dict]:
    items = list(_buffer)
    return items[-limit:]


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue):
    try:
        _subscribers.remove(q)
    except ValueError:
        pass
