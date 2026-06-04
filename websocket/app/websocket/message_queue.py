"""Redis Stream 可靠消息队列。

买家消息经 handle_message 全部门控后入 Stream，由本进程内的 consumer 消费：
取详情 → AI 生成 → 发送，**成功才 XACK**；失败留在 PEL，由 reclaimer 在空闲超阈
后重投，超过最大投递次数或消息已过时效则进死信流。彻底解决 AI 报错 / 发送报错
导致"买家消息没人回"的问题。

为什么放同进程：发送依赖活的 ws 连接（只存在于 websocket 进程），所以 consumer
不能是独立容器。副作用反而是好事——重连期间发送失败不 XACK，重连后自动补发。

并发与顺序：1 个 reader 阻塞读流，按 crc32(chat_id) % N 投到 N 个内存分片队列；
N 个 worker 各自串行排干自己的分片。同一 chat_id 恒定落同一分片 → 每会话严格 FIFO；
不同 chat_id 落不同分片 → 跨会话并发。
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
    consumer——process_job 每次都经 live.bot 取当前 bot。
    """

    def __init__(self, live, redis):
        self.live = live
        self.redis = redis
        self.n = max(1, settings.MQ_WORKER_COUNT)
        self.consumer_name = f"c-{int(time.time())}"
        self.queues = [asyncio.Queue() for _ in range(self.n)]
        self._tasks: list[asyncio.Task] = []
        # reader 把 entry_id 放进分片队列后登记于此；reclaimer 跳过仍在途的消息，杜绝重复发送
        self._inflight: set[str] = set()
        self._stopped = False

    async def start(self):
        await ensure_group(self.redis)
        self._tasks.append(asyncio.create_task(self._reader()))
        for i in range(self.n):
            self._tasks.append(asyncio.create_task(self._worker(i)))
        self._tasks.append(asyncio.create_task(self._reclaimer()))
        logger.info(f"消息队列消费者已启动 | workers={self.n}, consumer={self.consumer_name}")

    async def stop(self):
        self._stopped = True
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("消息队列消费者已停止")

    def _dispatch(self, entry_id: str, fields: dict):
        """投到对应分片队列并登记在途。"""
        self._inflight.add(entry_id)
        idx = _shard(fields.get("chat_id", ""), self.n)
        self.queues[idx].put_nowait((entry_id, fields))

    async def _reader(self):
        """阻塞读新消息（'>'），只分发不处理，保证读循环不被 AI 阻塞。

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
                        self._dispatch(entry_id, fields)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"队列 reader 异常，1s 后重试: {e}")
                await asyncio.sleep(1)

    async def _worker(self, idx: int):
        """串行排干分片队列。同 chat_id 恒落同一分片 → 会话内严格 FIFO。"""
        q = self.queues[idx]
        while not self._stopped:
            try:
                entry_id, fields = await q.get()
            except asyncio.CancelledError:
                raise
            try:
                await self._handle(entry_id, fields)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception(f"worker[{idx}] 处理异常（留 PEL 待重投）| id={entry_id}: {e}")
            finally:
                self._inflight.discard(entry_id)
                q.task_done()

    async def _handle(self, entry_id: str, fields: dict):
        """处理单条：调用 live.process_job；成功 / 不可重试 → XACK，可重试失败 → 留 PEL。

        worker 内联快重试先兜瞬时抖动（网络抖动、偶发 429）；仍失败才落到 PEL 交
        reclaimer 做跨崩溃的耐久重试，避免每次小故障都等 reclaim 周期。
        """
        attempts = settings.MQ_INLINE_RETRY + 1
        for n in range(attempts):
            outcome = await self.live.process_job(entry_id, fields)
            if outcome != "retry":
                # done / skip / expired / drop —— 均视为已终结，确认掉
                await self._ack(entry_id)
                return
            if n < attempts - 1:
                backoff = settings.MQ_INLINE_RETRY_BASE_MS * (2 ** n) / 1000.0
                logger.warning(f"内联重试 {n + 1}/{attempts - 1}，{backoff:.1f}s 后 | id={entry_id}")
                await asyncio.sleep(backoff)
        # 内联重试耗尽：不 XACK，留在 PEL 等 reclaimer
        logger.warning(f"内联重试耗尽，留 PEL 待 reclaim | id={entry_id}")

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
                    self._dispatch(entry_id, fields)
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



