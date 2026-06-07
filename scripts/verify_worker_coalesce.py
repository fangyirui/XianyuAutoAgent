"""消费端出队再合并 正确性/零回归验证。

场景：买家在上一条 AI 回复**生成期间**才发下一条（慢 AI），后续消息已 flush 进分片队列
排队。worker 处理完一批后应非阻塞排干队列、按 chat_id 合并，使"回复期间到达"的同会话
多条并成一次 AI 调用——这是 reader 侧滑动去抖（只看到达间隔）够不到的场景。

覆盖：
1) 慢 AI 期间同会话连到 2 批 → worker 出队时合并，总共只调 2 次 AI（第1批 + 合并后的第2+3）。
2) 跨会话不误合并：同一分片里混入不同 chat_id 的批，按 chat_id 分组各自独立处理。
3) 零回归：队列里只有一批（无竞争）→ 排干立即 Empty，单批单独处理，与改动前一致。
4) 关闭开关：MQ_DEBOUNCE_WINDOW_MS=0 → 不排干，逐批处理。

用法：
  python scripts/verify_worker_coalesce.py
"""
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "websocket"))

import fakeredis.aioredis  # noqa: E402
from common.core import settings  # noqa: E402
from app.websocket import message_queue as mq  # noqa: E402
from app.websocket.message_queue import MessageQueueConsumer, _shard  # noqa: E402


class FakeLive:
    """记录 process_job_batch 每次调用收到的 batch（合并后的成员），不碰真实 AI/DB。"""

    def __init__(self, redis):
        self.redis = redis
        self.batches = []          # 每次 process_job_batch 收到的 ids 列表
        self.gate = None           # 可选 asyncio.Event：set 前阻塞，模拟慢 AI

    async def process_job_batch(self, batch):
        ids = [eid for eid, _ in batch]
        self.batches.append(ids)
        if self.gate is not None and not self.gate.is_set():
            await self.gate.wait()
        return "done"


def _b(entry_id, chat_id, text="x"):
    """构造一个单成员批 [(entry_id, fields)]（与 _emit_batch 投进队列的形状一致）。"""
    return [(entry_id, {
        "chat_id": chat_id, "send_user_id": "u1", "item_id": "i1",
        "send_message": text, "sender_nickname": "", "create_time": str(int(time.time() * 1000)),
    })]


async def _new_consumer(window_ms=2000):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    live = FakeLive(redis)
    # 固定窗口与单分片，使所有 chat_id 落同一 worker，便于复现竞争
    settings.MQ_DEBOUNCE_WINDOW_MS = window_ms
    settings.MQ_WORKER_COUNT = 1
    settings.MQ_INLINE_RETRY = 0
    c = MessageQueueConsumer(live, redis)
    c._loop = asyncio.get_running_loop()
    return c, live


async def main():
    failures = []

    def check(cond, msg):
        print(f"[{'OK' if cond else 'FAIL'}] {msg}")
        if not cond:
            failures.append(msg)

    # ── 1) 慢 AI 期间同会话连到 2 批 → 出队合并 ──
    c, live = await _new_consumer(window_ms=2000)
    live.gate = asyncio.Event()             # 第1批将阻塞在此，模拟慢 AI
    worker = asyncio.create_task(c._worker(0))

    c.queues[0].put_nowait(_b("1-0", "cA"))  # 第1批：worker 取走后阻塞在 gate
    await asyncio.sleep(0.05)                # 让 worker 真正进入 process_job_batch 并卡住
    # 回复"生成期间"后续到达：直接投进同一分片队列排队
    c.queues[0].put_nowait(_b("2-0", "cA"))
    c.queues[0].put_nowait(_b("3-0", "cA"))
    await asyncio.sleep(0.05)
    live.gate.set()                          # 放行：worker 完成第1批，出队时应排干并合并 2+3
    await asyncio.sleep(0.1)

    check(live.batches[0] == ["1-0"], f"第1批单独处理（实际 {live.batches[0]}）")
    check(len(live.batches) == 2, f"2+3 合并为一次处理，共 2 次调用（实际 {len(live.batches)} 次）")
    check(len(live.batches) == 2 and live.batches[1] == ["2-0", "3-0"],
          f"第2次调用含合并后的 2、3（实际 {live.batches[1] if len(live.batches) > 1 else 'N/A'}）")
    c._stopped = True
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass

    # ── 2) 跨会话不误合并：同分片混入不同 chat_id ──
    c2, live2 = await _new_consumer(window_ms=2000)
    live2.gate = asyncio.Event()
    worker2 = asyncio.create_task(c2._worker(0))
    c2.queues[0].put_nowait(_b("10-0", "cA"))   # 第1批卡住
    await asyncio.sleep(0.05)
    # 期间到达：cA 再一条 + cB 一条（不同会话），都排在同一分片队列
    c2.queues[0].put_nowait(_b("11-0", "cA"))
    c2.queues[0].put_nowait(_b("12-0", "cB"))
    await asyncio.sleep(0.05)
    live2.gate.set()
    await asyncio.sleep(0.1)
    # 排干后按 chat_id 分组：cA 的 11 单独、cB 的 12 单独 → 不能合成一批
    after_first = live2.batches[1:]
    check(["11-0"] in after_first and ["12-0"] in after_first,
          f"跨会话各自独立处理，不合并（实际 {after_first}）")
    check(all(set(b) <= {"11-0"} or set(b) <= {"12-0"} for b in after_first),
          f"没有任何一批混入不同 chat_id（实际 {after_first}）")
    c2._stopped = True
    worker2.cancel()
    try:
        await worker2
    except asyncio.CancelledError:
        pass

    # ── 3) 零回归：无竞争（队列只一批）→ 单批单独处理 ──
    c3, live3 = await _new_consumer(window_ms=2000)
    worker3 = asyncio.create_task(c3._worker(0))
    c3.queues[0].put_nowait(_b("20-0", "cA"))
    await asyncio.sleep(0.05)
    c3.queues[0].put_nowait(_b("21-0", "cA"))   # 上一批早已处理完，这批出队时队列已空
    await asyncio.sleep(0.05)
    check(live3.batches == [["20-0"], ["21-0"]],
          f"无竞争时逐批单独处理，字节级一致（实际 {live3.batches}）")
    c3._stopped = True
    worker3.cancel()
    try:
        await worker3
    except asyncio.CancelledError:
        pass

    # ── 4) 关闭开关：window=0 不排干 ──
    c4, live4 = await _new_consumer(window_ms=0)
    live4.gate = asyncio.Event()
    worker4 = asyncio.create_task(c4._worker(0))
    c4.queues[0].put_nowait(_b("30-0", "cA"))
    await asyncio.sleep(0.05)
    c4.queues[0].put_nowait(_b("31-0", "cA"))
    c4.queues[0].put_nowait(_b("32-0", "cA"))
    await asyncio.sleep(0.05)
    live4.gate.set()
    await asyncio.sleep(0.1)
    check(live4.batches == [["30-0"], ["31-0"], ["32-0"]],
          f"window=0 关闭合并，逐批处理（实际 {live4.batches}）")
    c4._stopped = True
    worker4.cancel()
    try:
        await worker4
    except asyncio.CancelledError:
        pass

    print()
    if failures:
        print(f"❌ {len(failures)} 项失败")
        for f in failures:
            print(f"   - {f}")
        sys.exit(1)
    print("✅ 消费端出队合并 全部通过")


if __name__ == "__main__":
    asyncio.run(main())
