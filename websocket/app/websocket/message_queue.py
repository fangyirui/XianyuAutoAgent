"""Redis Stream 可靠消息队列。

买家消息经 handle_message 全部门控后入 Stream，由本进程内的 consumer 消费：
取详情 → AI 生成 → 发送，**成功才 XACK**；失败留在 PEL，由 reclaimer 在空闲超阈
后重投，超过最大投递次数或消息已过时效则进死信流。彻底解决 AI 报错 / 发送报错
导致"买家消息没人回"的问题。

为什么放同进程：发送依赖活的 ws 连接（只存在于 websocket 进程），所以 consumer
不能是独立容器。副作用反而是好事——重连期间发送失败不 XACK，重连后自动补发。

并发与顺序：1 个 reader 阻塞读流，按 chat_id 进去抖缓冲（滑动窗口，见下），flush 后
按 crc32(chat_id) % N 把整批投到 N 个内存分片队列；N 个 worker 各自串行排干自己的分片。
同一 chat_id 恒定落同一分片 → 每会话严格 FIFO；不同 chat_id 落不同分片 → 跨会话并发。

去抖合并：买家短时间连发多条时，reader 不立即处理，而是按 chat_id 缓冲——每来一条把该
会话的 flush 推迟 MQ_DEBOUNCE_WINDOW_MS（滑动窗口），停顿超过窗口就把整批合并成一次
AI 回复（首条算起最多压 MQ_DEBOUNCE_MAX_MS 硬上限）。合并后一批共享一次 AI 调用、一条
assistant 回复、一次发送；幂等标记按 batch 主键（首条 entry_id）建，批内每个 entry_id
都映射到该主键，保证任一成员被 reclaim 重投都能识别"整批已处理"。窗口设 0 关闭合并。

出队再合并（补足 reader 侧去抖够不到的场景）：reader 侧只按"到达间隔"合并，但买家也可能
在上一条 AI 回复**生成期间**（慢调用，数十秒）才发下一条——此时 worker 正忙，后续消息已
flush 进分片队列排队。worker 处理完一批后，**非阻塞排干此刻队列里已就绪的其余批**，按
chat_id 分组合并再处理：同会话的多批并成一次 AI 调用，跨会话各自独立。不引入额外等待
（只取已就绪的），无竞争时排干立即 Empty → 与逐批处理字节级一致；窗口设 0 时一并关闭。
"""

import asyncio
import time
import zlib
from loguru import logger
from common.core import settings

STREAM = "stream:messages"
GROUP = "cg:messages"
DEAD_STREAM = "stream:messages:dead"
STREAM_MAXLEN = 10000   # 流近似上限：正常消费下远不会触达，仅防异常堆积撑爆内存
DEAD_MAXLEN = 1000


def _shard(chat_id: str, n: int) -> int:
    """稳定哈希分片：同 chat_id 恒定落同一 worker。不用内置 hash()（字符串哈希按进程随机化）。"""
    if not chat_id or n <= 1:
        return 0
    return zlib.crc32(chat_id.encode("utf-8")) % n


async def ensure_group(redis):
    """幂等创建消费组（含 MKSTREAM）。已存在则忽略 BUSYGROUP。"""
    try:
        await redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        logger.info(f"创建消费组 {GROUP} @ {STREAM}")
    except Exception as e:
        if "BUSYGROUP" in str(e):
            return
        raise


async def enqueue(redis, fields: dict) -> str:
    """把一条待处理消息写入流。值统一转字符串（Stream 仅接受字符串/字节）。"""
    data = {k: ("" if v is None else str(v)) for k, v in fields.items()}
    return await redis.xadd(STREAM, data, maxlen=STREAM_MAXLEN, approximate=True)


class MessageQueueConsumer:
    """流消费者：1 reader + N 分片 worker + 1 reclaimer。

    持有对 XianyuLive 实例的引用（而非 bot），这样 soft_reload 换 bot 后无需重建
    consumer——process_job_batch 每次都经 live.bot 取当前 bot。
    """

    def __init__(self, live, redis):
        self.live = live
        self.redis = redis
        self.n = max(1, settings.MQ_WORKER_COUNT)
        self.consumer_name = f"c-{int(time.time())}"
        self.queues = [asyncio.Queue() for _ in range(self.n)]
        self._tasks: list[asyncio.Task] = []
        # reader/reclaimer 把 entry_id 收进缓冲或分片队列后登记于此；reclaimer 跳过仍在途的
        # 消息（含正在去抖缓冲中的），杜绝重复发送。缓冲最多压 MQ_DEBOUNCE_MAX_MS（远小于
        # reclaim 空闲阈值），故缓冲期不会被误判卡死。
        self._inflight: set[str] = set()
        self._stopped = False
        # ── 去抖合并缓冲（按 chat_id）──
        # _buffers[chat_id] = [(entry_id, fields), ...] 累积的待合并消息；
        # _timers[chat_id]  = 该会话的 flush 定时器句柄（滑动窗口，每来一条重置）；
        # _first_seen[chat_id] = 本批首条进入缓冲的时刻（loop 时钟），用于 MAX 硬上限。
        self.window_ms = max(0, settings.MQ_DEBOUNCE_WINDOW_MS)
        self.max_ms = max(self.window_ms, settings.MQ_DEBOUNCE_MAX_MS)
        self._buffers: dict[str, list] = {}
        self._timers: dict[str, asyncio.TimerHandle] = {}
        self._first_seen: dict[str, float] = {}
        self._loop = None

    async def start(self):
        await ensure_group(self.redis)
        self._loop = asyncio.get_running_loop()
        self._tasks.append(asyncio.create_task(self._reader()))
        for i in range(self.n):
            self._tasks.append(asyncio.create_task(self._worker(i)))
        self._tasks.append(asyncio.create_task(self._reclaimer()))
        logger.info(
            f"消息队列消费者已启动 | workers={self.n}, consumer={self.consumer_name}, "
            f"debounce={self.window_ms}ms(max {self.max_ms}ms)"
        )

    async def stop(self):
        self._stopped = True
        # 取消所有待触发的去抖定时器：缓冲里未 flush 的消息不 XACK，留 PEL 由重启后的
        # reader（新消费者）经 reclaimer 接管重投，不丢消息。
        for t in self._timers.values():
            t.cancel()
        self._timers.clear()
        self._buffers.clear()
        self._first_seen.clear()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("消息队列消费者已停止")

    def _admit(self, entry_id: str, fields: dict):
        """收一条新消息：登记在途，并按 chat_id 进去抖缓冲（滑动窗口，受硬上限约束）。
        window<=0 时不缓冲，立即作为单条 batch 派发（与改动前逐条处理等价）。"""
        self._inflight.add(entry_id)
        if self.window_ms <= 0:
            self._emit_batch([(entry_id, fields)])
            return
        chat_id = fields.get("chat_id", "")
        self._buffers.setdefault(chat_id, []).append((entry_id, fields))
        now = self._loop.time()
        self._first_seen.setdefault(chat_id, now)
        # 滑动窗口：每来一条把 flush 推迟 window_ms；但整体不超过从首条算起的硬上限 max_ms，
        # 防"买家一直打字永不回复"。临近上限时 delay 收敛到 0，下一条即触发 flush。
        remaining_to_max = self.max_ms / 1000.0 - (now - self._first_seen[chat_id])
        delay = min(self.window_ms / 1000.0, max(0.0, remaining_to_max))
        old = self._timers.get(chat_id)
        if old:
            old.cancel()
        self._timers[chat_id] = self._loop.call_later(delay, self._flush, chat_id)

    def _flush(self, chat_id: str):
        """去抖定时器回调（sync）：把该会话缓冲的整批消息派发到其分片 worker。"""
        self._timers.pop(chat_id, None)
        self._first_seen.pop(chat_id, None)
        batch = self._buffers.pop(chat_id, None)
        if batch:
            self._emit_batch(batch)

    def _emit_batch(self, batch: list):
        """把一批 (entry_id, fields) 投到 chat_id 所属分片队列；登记全部在途。
        批内顺序 = 到达顺序（= stream id 升序）→ 会话内严格 FIFO。"""
        for entry_id, _ in batch:
            self._inflight.add(entry_id)
        chat_id = batch[0][1].get("chat_id", "")
        idx = _shard(chat_id, self.n)
        self.queues[idx].put_nowait(batch)

    async def _reader(self):
        """阻塞读新消息（'>'），只收进去抖缓冲不处理，保证读循环不被 AI 阻塞。

        本消费者用一次性名字（c-<ts>），不复用，故自身 PEL 恒空——无需历史回放。
        进程崩溃残留在旧消费者 PEL 中的消息由 reclaimer 通过 XCLAIM 接管重投，
        与本 reader 解耦，职责单一。
        """
        while not self._stopped:
            try:
                resp = await self.redis.xreadgroup(
                    GROUP, self.consumer_name,
                    {STREAM: ">"},
                    count=64,
                    block=settings.MQ_READ_BLOCK_MS,
                )
                if not resp:
                    # 真 redis 下空返回意味着已 block 满 MQ_READ_BLOCK_MS；让出事件循环即可。
                    # 但若后端（或某些客户端）对空流立即返回，这里的小睡可防止读循环空转抢占
                    # 事件循环、饿死 worker。生产路径有消息时不会走到此分支，无额外延迟。
                    await asyncio.sleep(0.05)
                    continue
                for _stream, entries in resp:
                    for entry_id, fields in entries:
                        self._admit(entry_id, fields)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"队列 reader 异常，1s 后重试: {e}")
                await asyncio.sleep(1)

    async def _worker(self, idx: int):
        """串行排干分片队列（每个元素是一整批合并消息）。
        同 chat_id 恒落同一分片 → 会话内严格 FIFO。

        出队再合并：worker 取到队首批后，**非阻塞排干此刻队列里已就绪的其余批**，按
        chat_id 合并后再逐组处理。这补足了 reader 侧滑动去抖够不到的场景——worker 忙于
        上一会话的慢 AI 调用时，同会话后续消息已 flush 进本队列等待，出队时一并取走、并成
        一次 AI 调用。与到达间隔无关：只要"回复期间到达"就合并。

        无竞争时（队列里仅一批）排干立即 Empty，分组只有一个 chat_id 的一批 → 与逐批处理
        字节级一致；MQ_DEBOUNCE_WINDOW_MS=0（显式关闭合并）时跳过排干，退回纯逐批。"""
        q = self.queues[idx]
        coalesce = self.window_ms > 0
        while not self._stopped:
            try:
                first = await q.get()
            except asyncio.CancelledError:
                raise
            drained = [first]
            if coalesce:
                # 非阻塞排干当前队列：只取此刻已就绪的，不等待新到达（不引入额外延迟）。
                while True:
                    try:
                        drained.append(q.get_nowait())
                    except asyncio.QueueEmpty:
                        break
            # 按 chat_id 分组（dict 保持首次出现顺序）；同 chat_id 多批按出队顺序(=到达顺序)拼接。
            # 不同 chat_id 各自独立成组、独立处理，绝不跨会话合并。
            groups: dict[str, list] = {}
            for b in drained:
                cid = b[0][1].get("chat_id", "")
                groups.setdefault(cid, []).extend(b)
            try:
                for cid, merged in groups.items():
                    ids = [eid for eid, _ in merged]
                    try:
                        await self._handle_batch(merged)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.exception(f"worker[{idx}] 批处理异常（留 PEL 待重投）| ids={ids}: {e}")
                    finally:
                        for entry_id in ids:
                            self._inflight.discard(entry_id)
            finally:
                for _ in drained:
                    q.task_done()

    async def _handle_batch(self, batch: list):
        """处理一整批：调用 live.process_job_batch；成功 / 不可重试 → 整批 XACK，
        可重试失败 → 整批留 PEL（下次 reclaim 整批重投，幂等标记保证不重复 AI/落库/发送）。

        worker 内联快重试先兜瞬时抖动（网络抖动、偶发 429）；仍失败才落到 PEL 交
        reclaimer 做跨崩溃的耐久重试，避免每次小故障都等 reclaim 周期。
        """
        ids = [eid for eid, _ in batch]
        attempts = settings.MQ_INLINE_RETRY + 1
        for n in range(attempts):
            outcome = await self.live.process_job_batch(batch)
            if outcome != "retry":
                # done / drop —— 均视为已终结，整批确认掉
                for entry_id in ids:
                    await self._ack(entry_id)
                return
            if n < attempts - 1:
                backoff = settings.MQ_INLINE_RETRY_BASE_MS * (2 ** n) / 1000.0
                logger.warning(f"批内联重试 {n + 1}/{attempts - 1}，{backoff:.1f}s 后 | ids={ids}")
                await asyncio.sleep(backoff)
        # 内联重试耗尽：不 XACK，整批留在 PEL 等 reclaimer
        logger.warning(f"批内联重试耗尽，留 PEL 待 reclaim | ids={ids}")

    async def _ack(self, entry_id: str):
        try:
            await self.redis.xack(STREAM, GROUP, entry_id)
        except Exception as e:
            logger.warning(f"XACK 失败 | id={entry_id}: {e}")

    async def _to_dead(self, entry_id: str, fields: dict, reason: str):
        """进死信流并确认，不阻塞后续消息。"""
        try:
            payload = dict(fields)
            payload["_dead_reason"] = reason
            payload["_dead_at"] = str(int(time.time()))
            await self.redis.xadd(DEAD_STREAM, payload, maxlen=DEAD_MAXLEN, approximate=True)
        except Exception as e:
            logger.error(f"写死信流失败 | id={entry_id}: {e}")
        await self._ack(entry_id)
        logger.error(f"☠️ 消息进死信 | id={entry_id}, reason={reason}, chat={fields.get('chat_id')}")

    async def _reclaimer(self):
        """周期扫描 PEL：空闲超阈值的消息，超投递上限/过时效 → 死信，否则 XCLAIM 重投。
        跳过仍在 _inflight 的消息（worker 正在慢处理，不是卡死），杜绝重复发送。"""
        interval = settings.MQ_RECLAIM_INTERVAL
        idle_ms = settings.MQ_RECLAIM_IDLE_MS
        max_deliv = settings.MQ_MAX_DELIVERIES
        while not self._stopped:
            try:
                await asyncio.sleep(interval)
                pending = await self.redis.xpending_range(
                    STREAM, GROUP, min="-", max="+", count=128,
                )
                for p in pending or []:
                    entry_id = p["message_id"]
                    if entry_id in self._inflight:
                        continue
                    if p["time_since_delivered"] < idle_ms:
                        continue
                    # 认领回本消费者（即便仍归原 consumer 名），拿到字段
                    claimed = await self.redis.xclaim(
                        STREAM, GROUP, self.consumer_name, min_idle_time=idle_ms,
                        message_ids=[entry_id],
                    )
                    if not claimed:
                        continue
                    _id, fields = claimed[0]
                    if fields is None:
                        # 原始 entry 已被 XDEL / trim，无法重投，直接确认清除
                        await self._ack(entry_id)
                        continue
                    if p["times_delivered"] >= max_deliv:
                        await self._to_dead(entry_id, fields, f"max_deliveries({max_deliv})")
                        continue
                    if self._is_expired(fields):
                        await self._to_dead(entry_id, fields, "expired")
                        continue
                    logger.info(f"♻️ reclaim 重投 | id={entry_id}, deliv={p['times_delivered']}")
                    # 经去抖缓冲重投：同一失败批的成员会被先后 reclaim 并自然重新合并成批，
                    # 与首次合并的成员集尽量一致；幂等标记保证不重复 AI/落库/发送。
                    self._admit(entry_id, fields)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"reclaimer 异常: {e}")

    def _is_expired(self, fields: dict) -> bool:
        try:
            create_time = int(fields.get("create_time", "0"))
        except (ValueError, TypeError):
            return False
        if create_time <= 0:
            return False
        return (time.time() * 1000 - create_time) > settings.MESSAGE_EXPIRE_TIME



