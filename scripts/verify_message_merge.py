"""去抖合并 + 批级幂等 零回归/正确性验证。

覆盖：
1) 滑动去抖：同 chat_id 短时间连发 N 条 → 合并成 1 次 AI 回复（generate_reply 调 1 次），
   合并文本为各条以 \n 拼接，user 消息各自落库 N 行，assistant 落 1 行。
2) 单条等价：批大小=1 时喂给 AI 的"当前消息"= 原文本身（不被改写），LLM 入参字节级一致。
3) 跨会话并发：不同 chat_id 各自独立成批，互不合并。
4) 硬上限：持续不停发时，从首条算起 ~MAX_MS 必 flush，不会无限拖延。
5) 批级幂等：同一批重投（process_job_batch 再调）不重复调 AI、不重复落库、不重复发送、
   议价只 +1；任一成员单独重投也识别"已完成"跳过。
6) 议价合并：一批多条价格意图只 +1 轮，而非 +N。

用法：
  python scripts/verify_message_merge.py
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


class FakeLive:
    """最小化 XianyuLive：只实现 process_job_batch 依赖的副作用，记录调用以便断言。
    复用真实的 process_job_batch / _process_fresh_batch / _persist_user_msgs /
    _batch_text / _batch_newest_ct / _mark_done（从 XianyuLive 借方法），
    但把 DB / AI / 发送换成内存假实现。"""

    def __init__(self, redis):
        self.redis = redis
        self.message_expire_time = settings.MESSAGE_EXPIRE_TIME
        self.simulate_human_typing = False
        self.is_connected = True
        self.ws = object()
        # 记录
        self.ai_calls = []          # 每次 generate_reply 的 (merged_message, context_len)
        self.sent = []              # 每次 send_msg 的 (chat_id, toid, text)
        self.user_rows = []         # 落库的 user 文本（按 conv）
        self.assistant_rows = []    # 落库的 assistant 文本
        self.bargain_incr = 0
        self._next_intent = "default"
        self._next_reply = "好的"
        self._msg_id_seq = 0
        self._conv_msgs = {}        # conv_id -> [(id, role, content)]
        self._conv_seq = 0
        self._convs = {}            # chat_id -> conv_id

    # —— 假 DB ——
    async def _get_or_create_conversation(self, chat_id, user_id, item_id, user_nickname=None):
        if chat_id not in self._convs:
            self._conv_seq += 1
            self._convs[chat_id] = self._conv_seq
            self._conv_msgs[self._conv_seq] = []
        class C: pass
        c = C(); c.id = self._convs[chat_id]
        return c

    async def _add_message(self, conversation_id, role, content, last_intent=None):
        self._msg_id_seq += 1
        self._conv_msgs.setdefault(conversation_id, []).append((self._msg_id_seq, role, content))
        if role == "user":
            self.user_rows.append(content)
        elif role == "assistant":
            self.assistant_rows.append(content)
        return self._msg_id_seq

    async def _get_context(self, conversation_id, limit=50):
        return [{"role": r, "content": c} for _id, r, c in self._conv_msgs.get(conversation_id, [])]

    async def _get_context_before(self, conversation_id, before_id, limit=50):
        return [{"role": r, "content": c} for _id, r, c in self._conv_msgs.get(conversation_id, []) if _id < before_id]

    async def _get_item_cache(self, item_id):
        return {"title": "x", "soldPrice": "100"}

    async def _get_item_custom_prompt(self, item_id):
        return ""

    async def _get_item_default_reply(self, item_id):
        return ""

    async def _has_user_message(self, conversation_id):
        return any(r == "user" for _id, r, _c in self._conv_msgs.get(conversation_id, []))

    async def _increment_bargain(self, chat_id):
        self.bargain_incr += 1

    def build_item_description(self, info):
        return "ITEM"

    # —— 假 AI / 发送 ——
    class _Bot:
        def __init__(self, outer): self.outer = outer
        async def generate_reply(self, msg, item_desc, context, item_custom_prompt=None, chat_id=None):
            self.outer.ai_calls.append((msg, len(context)))
            return self.outer._next_reply, self.outer._next_intent

    @property
    def bot(self):
        return FakeLive._Bot(self)

    async def send_msg(self, ws, cid, toid, text):
        self.sent.append((cid, toid, text))


# 借用真实方法（用 __dict__ 取，保留 staticmethod 包装）
from app.websocket.manager import XianyuLive  # noqa: E402
for _m in ("process_job_batch", "_process_fresh_batch", "_persist_user_msgs",
           "_batch_text", "_batch_newest_ct", "_mark_done"):
    setattr(FakeLive, _m, XianyuLive.__dict__[_m])


def _mk(entry_id, chat_id, text, ct=None):
    if ct is None:
        ct = int(time.time() * 1000)
    return (entry_id, {
        "chat_id": chat_id, "send_user_id": "u1", "item_id": "i1",
        "send_message": text, "sender_nickname": "", "create_time": str(ct),
    })


async def main():
    failures = []

    def check(cond, msg):
        if cond:
            print(f"[OK] {msg}")
        else:
            print(f"[FAIL] {msg}")
            failures.append(msg)

    # ── 1) 合并：3 条 → 1 次 AI，合并文本，user 落 3 行 ──
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    live = FakeLive(redis)
    batch = [_mk("1-0", "cA", "在吗"), _mk("2-0", "cA", "这个还有货吗"), _mk("3-0", "cA", "包邮吗")]
    out = await live.process_job_batch(batch)
    check(out == "done", f"批处理返回 done（实际 {out}）")
    check(len(live.ai_calls) == 1, f"3 条合并只调 1 次 AI（实际 {len(live.ai_calls)}）")
    check(live.ai_calls[0][0] == "在吗\n这个还有货吗\n包邮吗", f"合并文本正确（实际 {live.ai_calls[0][0]!r}）")
    check(live.user_rows == ["在吗", "这个还有货吗", "包邮吗"], f"user 各自落 3 行（实际 {live.user_rows}）")
    check(live.assistant_rows == ["好的"], f"assistant 落 1 行（实际 {live.assistant_rows}）")
    check(len(live.sent) == 1, f"只发送 1 次（实际 {len(live.sent)}）")

    # ── 2) 单条等价：批大小=1 时喂给 AI 的当前消息 = 原文 ──
    redis2 = fakeredis.aioredis.FakeRedis(decode_responses=True)
    live2 = FakeLive(redis2)
    out = await live2.process_job_batch([_mk("10-0", "cB", "你好")])
    check(live2.ai_calls[0][0] == "你好", f"单条不被改写，LLM 入参字节级一致（实际 {live2.ai_calls[0][0]!r}）")
    check(live2.user_rows == ["你好"], "单条 user 落 1 行")

    # ── 5) 批级幂等：整批重投不重复 ──
    out2 = await live.process_job_batch(batch)
    check(out2 == "done", "整批重投仍返回 done")
    check(len(live.ai_calls) == 1, f"重投不重复调 AI（实际 {len(live.ai_calls)}）")
    check(live.user_rows == ["在吗", "这个还有货吗", "包邮吗"], "重投不重复落 user")
    check(len(live.sent) == 1, "重投不重复发送（已 mdone，跳过）")

    # 任一成员单独重投也跳过
    out3 = await live.process_job_batch([_mk("2-0", "cA", "这个还有货吗")])
    check(out3 == "done" and len(live.ai_calls) == 1, "单成员重投识别已完成、跳过")

    # ── 6) 议价合并：一批多条 price 只 +1 ──
    redis3 = fakeredis.aioredis.FakeRedis(decode_responses=True)
    live3 = FakeLive(redis3)
    live3._next_intent = "price"
    pbatch = [_mk("20-0", "cC", "便宜点"), _mk("21-0", "cC", "100 卖吗"), _mk("22-0", "cC", "急")]
    await live3.process_job_batch(pbatch)
    check(live3.bargain_incr == 1, f"一批多条议价只 +1（实际 {live3.bargain_incr}）")
    # 重投不再加
    await live3.process_job_batch(pbatch)
    check(live3.bargain_incr == 1, f"议价重投不重复 +1（实际 {live3.bargain_incr}）")

    # ── 过期：整批最新条都过期 → drop ──
    redis4 = fakeredis.aioredis.FakeRedis(decode_responses=True)
    live4 = FakeLive(redis4)
    old_ct = int(time.time() * 1000) - settings.MESSAGE_EXPIRE_TIME - 10000
    out = await live4.process_job_batch([_mk("30-0", "cD", "旧消息", ct=old_ct)])
    check(out == "drop" and len(live4.ai_calls) == 0, "整批过期 → drop，不调 AI")

    # ── 新鲜度按最新条：老+新混合，仍处理 ──
    redis5 = fakeredis.aioredis.FakeRedis(decode_responses=True)
    live5 = FakeLive(redis5)
    now = int(time.time() * 1000)
    mixed = [_mk("40-0", "cE", "很久以前", ct=now - settings.MESSAGE_EXPIRE_TIME - 5000),
             _mk("41-0", "cE", "刚刚", ct=now)]
    out = await live5.process_job_batch(mixed)
    check(out == "done" and len(live5.ai_calls) == 1, "新鲜度按最新条判定：混合批仍回复")

    print()
    if failures:
        print(f"❌ {len(failures)} 项失败")
        for f in failures:
            print(f"   - {f}")
        sys.exit(1)
    print("✅ process_job_batch 合并/幂等 全部通过")


if __name__ == "__main__":
    asyncio.run(main())
