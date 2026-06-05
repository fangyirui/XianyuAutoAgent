import asyncio
from typing import List

# 会话消息实时事件的进程内发布/订阅。
# 与 log_buffer 同构，但不保留历史缓冲——历史消息走 DB（getMessages/getConversations），
# 这里只负责把"新落库的一条消息"作为增量事件实时推给所有 SSE 订阅者。
# websocket 服务单进程单事件循环：消息落库处与 SSE 推送处在同一 loop，故内存队列即可，无需 Redis。

_subscribers: List[asyncio.Queue] = []


def publish(event: dict):
    """把一条会话事件投递给所有订阅者。永不抛异常——调用方在落库后调用，
    推送失败绝不能影响主流程。队列满则丢弃该订阅者的这条（SSE 会在重连时由前端拉历史补齐）。"""
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue):
    try:
        _subscribers.remove(q)
    except ValueError:
        pass
