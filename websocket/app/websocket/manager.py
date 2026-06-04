import json
import time
import asyncio
import base64
import random
import websockets
from loguru import logger
from datetime import datetime
from sqlalchemy import select, update, func
from common.core import settings
from common.db import AsyncSessionLocal, redis_client
from common.models import Conversation, Message, ItemCache
from common.utils import generate_mid, generate_uuid, generate_device_id, trans_cookies
from ..services.xianyu import XianyuApis, TokenManager
from ..services.xianyu.message_handler import (
    is_sync_package, is_chat_message, is_typing_status,
    is_bracket_system_message, decrypt_sync_data,
)
from ..services.agent import XianyuReplyBot
from .message_queue import enqueue


class XianyuLive:
    def __init__(self):
        cookies_str = settings.COOKIES_STR
        self.cookies_str = cookies_str
        self.cookies = trans_cookies(cookies_str)
        self.myid = self.cookies["unb"]
        self.device_id = generate_device_id(self.myid)

        self.apis = XianyuApis(cookies_str)
        self.token_mgr = TokenManager(self.apis, self.device_id)
        self.bot = XianyuReplyBot()
        self.redis = redis_client

        self.ws = None
        self.heartbeat_interval = settings.HEARTBEAT_INTERVAL
        self.heartbeat_timeout = settings.HEARTBEAT_TIMEOUT
        self.last_heartbeat_time = 0.0
        self.last_heartbeat_response = 0.0
        self.connection_restart_flag = False

        self.manual_mode_conversations: set = set()
        self.manual_mode_timestamps: dict = {}
        self.manual_mode_timeout = settings.MANUAL_MODE_TIMEOUT
        self.message_expire_time = settings.MESSAGE_EXPIRE_TIME
        self.toggle_keywords = settings.TOGGLE_KEYWORDS
        self.simulate_human_typing = settings.SIMULATE_HUMAN_TYPING
        self.skip_keywords = [k.strip() for k in settings.SKIP_KEYWORDS.split(",") if k.strip()]
        self._stopped = False

    @property
    def is_connected(self) -> bool:
        return self.ws is not None and self.ws.open

    async def stop(self):
        self._stopped = True
        self.connection_restart_flag = True
        if self.ws:
            await self.ws.close()

    def is_manual_mode(self, chat_id: str) -> bool:
        if chat_id not in self.manual_mode_conversations:
            return False
        if time.time() - self.manual_mode_timestamps.get(chat_id, 0) > self.manual_mode_timeout:
            self.manual_mode_conversations.discard(chat_id)
            self.manual_mode_timestamps.pop(chat_id, None)
            return False
        return True

    def toggle_manual_mode(self, chat_id: str) -> str:
        if self.is_manual_mode(chat_id):
            self.manual_mode_conversations.discard(chat_id)
            self.manual_mode_timestamps.pop(chat_id, None)
            return "auto"
        self.manual_mode_conversations.add(chat_id)
        self.manual_mode_timestamps[chat_id] = time.time()
        return "manual"

    async def _get_or_create_conversation(self, chat_id: str, user_id: str, item_id: str, user_nickname: str = None):
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Conversation).where(Conversation.chat_id == chat_id))
            conv = result.scalar_one_or_none()
            if not conv:
                conv = Conversation(chat_id=chat_id, user_id=user_id, item_id=item_id, user_nickname=user_nickname)
                db.add(conv)
                await db.commit()
                await db.refresh(conv)
            elif user_nickname and not conv.user_nickname:
                conv.user_nickname = user_nickname
                await db.commit()
                await db.refresh(conv)
            return conv

    async def _add_message(self, conversation_id: int, role: str, content: str, last_intent: str = None):
        async with AsyncSessionLocal() as db:
            msg = Message(conversation_id=conversation_id, role=role, content=content)
            db.add(msg)
            # 同步刷新会话行：让 updated_at 反映"最后一条消息时间"（列表按它倒序排序）。
            # last_intent 仅在调用方显式传入时写回（assistant 落库时），其余消息不动该列。
            values = {"updated_at": func.now()}
            if last_intent is not None:
                values["last_intent"] = last_intent
            await db.execute(
                update(Conversation).where(Conversation.id == conversation_id).values(**values)
            )
            await db.commit()
            await db.refresh(msg)
            return msg.id

    async def _get_context(self, conversation_id: int, limit: int = 50) -> list:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at).limit(limit)
            )
            return [{"role": m.role, "content": m.content} for m in result.scalars().all()]

    async def _get_context_before(self, conversation_id: int, before_id: int, limit: int = 50) -> list:
        """取 id < before_id 的历史。用于重投时重建"当前消息落库前"的上下文，
        使重试的 LLM 入参与首次尝试一致（不让当前消息出现在自己的历史里）。"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id, Message.id < before_id)
                .order_by(Message.created_at).limit(limit)
            )
            return [{"role": m.role, "content": m.content} for m in result.scalars().all()]

    async def _get_item_cache(self, item_id: str) -> dict | None:
        """只在缓存含完整 itemDO（带 soldPrice）时返回；只有列表数据时返回 None 以触发详情补全。"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ItemCache).where(ItemCache.item_id == item_id))
            row = result.scalar_one_or_none()
            if row and row.raw_json and "soldPrice" in row.raw_json:
                return row.raw_json
            return None

    async def _get_item_custom_prompt(self, item_id: str) -> str:
        """读取商品级额外 AI 提示词；不存在或空返回空串。"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ItemCache.custom_prompt).where(ItemCache.item_id == item_id)
            )
            row = result.first()
            return (row[0] or "") if row else ""

    async def _get_item_default_reply(self, item_id: str) -> str:
        """读取商品级默认回复；仅在开关启用且文本非空时返回。否则返回空串
        （等价于'未启用'），调用方据此判断是否短路 AI 流程。"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ItemCache.default_reply, ItemCache.default_reply_enabled).where(
                    ItemCache.item_id == item_id
                )
            )
            row = result.first()
            if not row:
                return ""
            enabled = bool(row[1])
            text = (row[0] or "").strip() if row[0] else ""
            return text if (enabled and text) else ""

    async def _has_user_message(self, conversation_id: int) -> bool:
        """会话是否已有买家（role='user'）消息。用于判定本条是否为会话首条买家消息。"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Message.id)
                .where(Message.conversation_id == conversation_id, Message.role == "user")
                .limit(1)
            )
            return result.first() is not None

    async def _is_my_item(self, item_id: str) -> bool:
        """item_cache 表里是否存在归属于当前卖家的此商品。"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ItemCache.id).where(
                    ItemCache.item_id == item_id,
                    ItemCache.seller_id == str(self.myid),
                )
            )
            return result.scalar_one_or_none() is not None

    async def _save_item_cache(self, item_id: str, data: dict):
        """写入/更新 itemDO 详情；seller_id 一律使用当前账号 unb。"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ItemCache).where(ItemCache.item_id == item_id))
            row = result.scalar_one_or_none()
            try:
                price = float(data.get("soldPrice", 0))
            except (ValueError, TypeError):
                price = 0.0
            now = datetime.now()
            if row:
                row.raw_json = data
                row.title = data.get("title", "") or row.title
                if price > 0:
                    row.price = price
                row.description = data.get("desc", "") or row.description
                row.seller_id = str(self.myid)
                row.fetched_at = now
                # NOTE: 不要写 row.custom_prompt —— 用户在管理后台手工配置的提示词必须保留
            else:
                db.add(ItemCache(
                    item_id=item_id, raw_json=data,
                    title=data.get("title", ""),
                    price=price,
                    description=data.get("desc", ""),
                    seller_id=str(self.myid),
                    fetched_at=now,
                ))
            await db.commit()

    async def _batch_save_items_from_list(self, items: list) -> int:
        """把商品列表接口返回的 cardData 批量保存到 item_cache。"""
        if not items:
            return 0
        saved = 0
        now = datetime.now()
        async with AsyncSessionLocal() as db:
            for it in items:
                item_id = str(it.get("id", ""))
                if not item_id or item_id.startswith("auto_"):
                    continue
                title = it.get("title", "") or ""
                price_str = (it.get("priceInfo") or {}).get("price", "0")
                try:
                    price = float(price_str)
                except (ValueError, TypeError):
                    price = 0.0

                result = await db.execute(select(ItemCache).where(ItemCache.item_id == item_id))
                row = result.scalar_one_or_none()
                if row:
                    if title:
                        row.title = title
                    if price > 0:
                        row.price = price
                    row.seller_id = str(self.myid)
                    if not row.raw_json or "soldPrice" not in row.raw_json:
                        row.raw_json = it
                    row.fetched_at = now
                    # NOTE: 不要写 row.custom_prompt —— 用户在管理后台手工配置的提示词必须保留
                else:
                    db.add(ItemCache(
                        item_id=item_id,
                        raw_json=it,
                        title=title,
                        price=price,
                        description="",
                        seller_id=str(self.myid),
                        fetched_at=now,
                    ))
                saved += 1
            await db.commit()
        return saved

    async def sync_my_items(self) -> int:
        """通过 mtop.idle.web.xyh.item.list 拉取卖家所有商品，并补全详情（含 desc）。"""
        logger.info(f"开始同步商品列表 | seller={self.myid}")
        try:
            items = await self.apis.get_all_items(self.myid, page_size=20)
        except Exception as e:
            logger.error(f"同步商品列表失败: {e}")
            return 0
        saved = await self._batch_save_items_from_list(items)
        logger.info(f"商品基础信息同步完成 | seller={self.myid}, 拉取={len(items)}条, 保存={saved}条")

        item_ids = [str(it.get("id", "")) for it in items if it.get("id") and not str(it.get("id", "")).startswith("auto_")]
        need_detail = await self._find_items_missing_detail(item_ids)
        if need_detail:
            logger.info(f"开始补全 {len(need_detail)} 件商品的详情")
            await self._fetch_missing_details(need_detail)
            logger.info(f"商品详情补全完成 | 总数={len(need_detail)}")
        return saved

    async def _find_items_missing_detail(self, item_ids: list) -> list:
        """筛出 item_cache 中 raw_json 不含 soldPrice 的商品ID。"""
        if not item_ids:
            return []
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ItemCache.item_id, ItemCache.raw_json).where(ItemCache.item_id.in_(item_ids))
            )
            missing = []
            for item_id, raw_json in result.all():
                if not raw_json or "soldPrice" not in raw_json:
                    missing.append(item_id)
            return missing

    async def _fetch_missing_details(self, item_ids: list):
        """并发补全商品详情，限流 3，单条间隔 0.5s。"""
        semaphore = asyncio.Semaphore(3)

        async def fetch_one(item_id: str):
            async with semaphore:
                try:
                    api_result = await self.apis.get_item_info(item_id)
                    if "data" in api_result and "itemDO" in api_result["data"]:
                        await self._save_item_cache(item_id, api_result["data"]["itemDO"])
                        logger.info(f"✅ 详情已补全 | item_id={item_id}")
                    else:
                        logger.warning(f"❌ 详情获取失败 | item_id={item_id}, keys={list(api_result.keys()) if isinstance(api_result, dict) else type(api_result).__name__}")
                except Exception as e:
                    logger.error(f"补全详情异常 | item_id={item_id}: {e}")
                await asyncio.sleep(0.5)

        await asyncio.gather(*[fetch_one(item_id) for item_id in item_ids], return_exceptions=True)

    async def _increment_bargain(self, chat_id: str):
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Conversation).where(Conversation.chat_id == chat_id))
            conv = result.scalar_one_or_none()
            if conv:
                conv.bargain_count += 1
                await db.commit()

    async def send_msg(self, ws, cid: str, toid: str, text: str):
        payload = {"contentType": 1, "text": {"text": text}}
        text_b64 = base64.b64encode(json.dumps(payload).encode()).decode()
        msg = {
            "lwp": "/r/MessageSend/sendByReceiverScope",
            "headers": {"mid": generate_mid()},
            "body": [
                {
                    "uuid": generate_uuid(), "cid": f"{cid}@goofish", "conversationType": 1,
                    "content": {"contentType": 101, "custom": {"type": 1, "data": text_b64}},
                    "redPointPolicy": 0, "extension": {"extJson": "{}"},
                    "ctx": {"appVersion": "1.0", "platform": "web"}, "mtags": {}, "msgReadStatusSetting": 1,
                },
                {"actualReceivers": [f"{toid}@goofish", f"{self.myid}@goofish"]},
            ],
        }
        await ws.send(json.dumps(msg))

    def build_item_description(self, item_info: dict) -> str:
        clean_skus = []
        for sku in item_info.get("skuList", []):
            specs = [p["valueText"] for p in sku.get("propertyList", []) if p.get("valueText")]
            clean_skus.append({
                "spec": " ".join(specs) or "默认规格",
                "price": round(float(sku.get("price", 0)) / 100, 2),
                "stock": sku.get("quantity", 0),
            })
        valid_prices = [s["price"] for s in clean_skus if s["price"] > 0]
        if valid_prices:
            mn, mx = min(valid_prices), max(valid_prices)
            price_display = f"¥{mn}" if mn == mx else f"¥{mn} - ¥{mx}"
        else:
            price_display = f"¥{round(float(item_info.get('soldPrice', 0)), 2)}"
        summary = {
            "title": item_info.get("title", ""), "desc": item_info.get("desc", ""),
            "price_range": price_display, "total_stock": item_info.get("quantity", 0),
            "sku_details": clean_skus,
        }
        return json.dumps(summary, ensure_ascii=False)

    async def handle_message(self, message_data: dict, ws):
        if not is_sync_package(message_data):
            return
        sync_data = message_data["body"]["syncPushPackage"]["data"][0]
        message = decrypt_sync_data(sync_data)
        if not message:
            return
        if is_typing_status(message) or not is_chat_message(message):
            logger.debug(f"非聊天消息，跳过 | typing={is_typing_status(message)}, chat={is_chat_message(message)}")
            return

        create_time = int(message["1"]["5"])
        age_ms = time.time() * 1000 - create_time
        if age_ms > self.message_expire_time:
            logger.debug(f"消息过期，age={age_ms:.0f}ms > {self.message_expire_time}ms")
            return

        send_user_id = message["1"]["10"]["senderUserId"]
        send_message = message["1"]["10"]["reminderContent"]
        url_info = message["1"]["10"]["reminderUrl"]
        sender_nickname = message["1"]["10"].get("reminderTitle") or message["1"]["10"].get("senderNick") or ""
        item_id = url_info.split("itemId=")[1].split("&")[0] if "itemId=" in url_info else None
        chat_id = message["1"]["2"].split("@")[0]

        if not item_id:
            logger.debug(f"无item_id，跳过 | chat_id={chat_id}, url_info={url_info}")
            return

        if send_user_id == self.myid:
            if send_message.strip() in self.toggle_keywords:
                mode = self.toggle_manual_mode(chat_id)
                logger.info(f"{'🔴 已接管' if mode == 'manual' else '🟢 已恢复'} 会话 {chat_id}")
                return
            # 仅当会话已存在（买家先发过）时追加；否则不凭空创建脏会话（user_id/nickname 无从知道）。
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Conversation).where(Conversation.chat_id == chat_id))
                conv = result.scalar_one_or_none()
            if conv:
                await self._add_message(conv.id, "assistant", send_message)
                logger.debug(f"自己发送的消息已记录 | chat_id={chat_id}")
            else:
                logger.debug(f"卖家先发起，会话尚未存在，跳过记录 | chat_id={chat_id}, item_id={item_id}")
            return

        logger.info(f"收到用户消息 | 会话: {chat_id}, 用户: {send_user_id}, 商品: {item_id}, 内容: {send_message}")

        matched_kw = next((kw for kw in self.skip_keywords if kw in send_message), None)
        if matched_kw:
            logger.info(f"命中跳过关键词「{matched_kw}」，不记录、不回复 | chat_id={chat_id}")
            return

        if self.is_manual_mode(chat_id):
            conv = await self._get_or_create_conversation(chat_id, send_user_id, item_id, sender_nickname)
            await self._add_message(conv.id, "user", send_message)
            logger.info(f"人工接管中，仅记录 | chat_id={chat_id}")
            return

        if is_bracket_system_message(send_message):
            # 闲鱼客户端的 [xxx] 事件（如 [发来一个商品]/[买家拍下了商品]）：仅入库，不触发 AI 回复。
            # 归属校验前置：foreign item（自己以买家身份在别人店里）的事件丢弃，避免凭空建脏会话。
            if not await self._is_my_item(item_id):
                logger.debug(f"foreign item 的系统方括号消息，跳过: {send_message} | item_id={item_id}")
                return
            conv = await self._get_or_create_conversation(chat_id, send_user_id, item_id, sender_nickname)
            await self._add_message(conv.id, "system", send_message)
            logger.debug(f"系统方括号消息已记录: {send_message}")
            return

        # 归属校验：商品不在当前卖家的商品库里，说明这是别人的商品（自己以买家身份的会话），跳过自动回复。
        if not await self._is_my_item(item_id):
            logger.info(f"商品 {item_id} 不属于当前卖家 {self.myid}，跳过自动回复 | chat_id={chat_id}")
            return

        # 入队：后续"默认回复 / 取详情 / AI 生成 / 发送"全部交给消息队列 worker 可靠消费
        # （成功才 XACK，失败留 PEL 自动重投），避免 AI 报错 / 发送报错导致买家消息无人回复。
        # 此处仅保留无副作用的入口门控；产生回复的逻辑统一在 process_job 中执行。
        await enqueue(self.redis, {
            "chat_id": chat_id,
            "send_user_id": send_user_id,
            "item_id": item_id,
            "send_message": send_message,
            "sender_nickname": sender_nickname or "",
            "create_time": create_time,
        })
        logger.info(f"消息已入队待处理 | chat_id={chat_id}, item_id={item_id}")

    async def process_job(self, entry_id: str, fields: dict) -> str:
        """消费一条队列消息：默认回复门控 / 取详情 / AI 生成 / 发送。

        返回值约定（consumer 据此决定 XACK 还是留 PEL）：
          done    成功发送（或 '-' 无需回复）→ XACK
          skip    已完成过（重投 / ack 丢失）→ XACK
          drop    过期，不再回复 → XACK
          retry   可重试失败（AI 报错 / 详情API失败 / 发送失败 / WS 未连）→ 不 XACK，留 PEL

        幂等：用 mq:committed:{id} / mq:done:{id} 两个标记保证重投不重复调用 AI、不重复落库；
        一旦回复文本提交（committed），发送失败的重投只重发已提交文本，不再生成、不污染上下文。
        """
        done_key = f"mq:done:{entry_id}"
        committed_key = f"mq:committed:{entry_id}"
        ttl = settings.MQ_DEDUP_TTL

        chat_id = fields.get("chat_id", "")
        send_user_id = fields.get("send_user_id", "")
        item_id = fields.get("item_id", "")
        send_message = fields.get("send_message", "")
        # 与原 handle_message 一致：空昵称传 "" 而非 None（_get_or_create_conversation 同等对待，
        # 但建会话时 user_nickname 列保持 "" 而非 NULL，保证与改动前字节一致）
        sender_nickname = fields.get("sender_nickname", "")

        # 已完整发送过（重投 / ack 丢失）→ 跳过，避免重复回复
        if await self.redis.exists(done_key):
            logger.debug(f"消息已完成，跳过重投 | id={entry_id}")
            return "skip"

        # 新鲜度复检：过期消息不再回复（与 handle_message 入队前的过期门同一语义）
        try:
            create_time = int(fields.get("create_time", "0"))
        except (ValueError, TypeError):
            create_time = 0
        if create_time > 0 and (time.time() * 1000 - create_time) > self.message_expire_time:
            logger.info(f"队列消息已过期，丢弃不回复 | id={entry_id}, chat_id={chat_id}")
            return "drop"

        # ── 重发路径：上次已生成并落库、仅发送失败（或发送后崩溃未及 ack）──
        committed = await self.redis.get(committed_key)
        if committed:
            try:
                data = json.loads(committed)
            except Exception:
                data = None
            if data:
                if not self.is_connected:
                    logger.warning(f"重发但 WS 未连接，待重连后重试 | id={entry_id}")
                    return "retry"
                try:
                    await self.send_msg(self.ws, data["chat_id"], data["toid"], data["reply"])
                except Exception as e:
                    logger.warning(f"重发失败，留 PEL | id={entry_id}: {e}")
                    return "retry"
                await self.redis.setex(done_key, ttl, "1")
                logger.info(f"重发成功 | id={entry_id}, chat_id={data['chat_id']}")
                return "done"

        return await self._process_fresh(
            entry_id, done_key, committed_key, ttl,
            chat_id, send_user_id, item_id, send_message, sender_nickname,
        )

    async def _process_fresh(
        self, entry_id, done_key, committed_key, ttl,
        chat_id, send_user_id, item_id, send_message, sender_nickname,
    ) -> str:
        """首次处理（未 committed）：逻辑逐行搬自原 handle_message 内联段，
        默认配置下 LLM 入参与发送字节级不变。差异仅在于：发送前先把已生成的回复
        写入 committed_key，使"发送失败重投"只重发不再生成。"""
        # 商品级默认回复门控：启用且文本非空时，仅对会话首条买家消息短路 AI 直接发固定文本，
        # 之后该会话穿透到正常 AI 流程。默认（disabled 或文本为空）下返回空串，主流程字节级不变。
        default_reply = await self._get_item_default_reply(item_id)
        if default_reply:
            conv = await self._get_or_create_conversation(chat_id, send_user_id, item_id, sender_nickname)
            if not await self._has_user_message(conv.id):
                await self._add_message(conv.id, "user", send_message)
                await self._add_message(conv.id, "assistant", default_reply)
                logger.info(f"使用商品默认回复(首条) | chat_id={chat_id}, item_id={item_id}, reply={default_reply}")
                await self.redis.setex(
                    committed_key, ttl,
                    json.dumps({"chat_id": chat_id, "toid": send_user_id, "reply": default_reply}),
                )
                if not self.is_connected:
                    logger.warning(f"WS 未连接，默认回复待重连后发送 | id={entry_id}")
                    return "retry"
                try:
                    await self.send_msg(self.ws, chat_id, send_user_id, default_reply)
                except Exception as e:
                    logger.warning(f"默认回复发送失败，留 PEL | id={entry_id}: {e}")
                    return "retry"
                await self.redis.setex(done_key, ttl, "1")
                return "done"

        item_info = await self._get_item_cache(item_id)
        if not item_info:
            logger.info(f"商品详情未命中，调用详情API补全 | item_id={item_id}")
            try:
                api_result = await self.apis.get_item_info(item_id)
            except Exception as e:
                logger.warning(f"详情API异常，留 PEL 重试 | item_id={item_id}: {e}")
                return "retry"
            if "data" in api_result and "itemDO" in api_result["data"]:
                item_info = api_result["data"]["itemDO"]
                await self._save_item_cache(item_id, item_info)
                logger.info(f"商品详情已缓存 | item_id={item_id}, title={item_info.get('title', '')}")
            else:
                logger.warning(f"获取商品详情失败 | item_id={item_id}, response_keys={list(api_result.keys())}")
                return "retry"

        conv = await self._get_or_create_conversation(chat_id, send_user_id, item_id, sender_nickname)
        item_desc = f"当前商品的信息如下：{self.build_item_description(item_info)}"
        item_custom_prompt = await self._get_item_custom_prompt(item_id)

        # 留痕 user 消息 —— 仅一次。重投（上次 AI 失败、未 commit）时复用同一行，
        # 并据其 id 重建"落库前"的上下文，保证重试与首次的 LLM 入参字节级一致。
        usermsg_key = f"mq:usermsg:{entry_id}"
        prior = await self.redis.get(usermsg_key)
        if prior:
            user_msg_id = int(prior)
            context = await self._get_context_before(conv.id, user_msg_id)
        else:
            context = await self._get_context(conv.id)
            user_msg_id = await self._add_message(conv.id, "user", send_message)
            await self.redis.setex(usermsg_key, ttl, str(user_msg_id))
        logger.info(f"开始生成AI回复 | chat_id={chat_id}, 上下文条数={len(context)}, 商品额外提示词长度={len(item_custom_prompt)}")
        try:
            bot_reply, intent = await self.bot.generate_reply(
                send_message, item_desc, context, item_custom_prompt=item_custom_prompt, chat_id=chat_id,
            )
        except Exception as e:
            logger.error(f"AI生成回复异常，user 消息已留痕，留 PEL 重试 | chat_id={chat_id}, err={e}")
            return "retry"

        if bot_reply == "-":
            logger.info(f"AI返回'-'，不回复 | chat_id={chat_id}")
            await self.redis.setex(done_key, ttl, "1")
            return "done"

        # 提交：递增议价、落库 assistant、写 committed —— 这些副作用只发生一次。
        # 写 committed 之后即便发送失败，重投也只走"重发路径"，不再生成、不再落库、不再递增。
        # 议价计数单独用 NX 标记守护：即便在 add_message/commit 之间发生 DB 失败导致整体重投，
        # 也不会把同一条消息的议价轮次重复累加（会影响 PriceAgent 的 temperature）。
        if intent == "price":
            if await self.redis.set(f"mq:incr:{entry_id}", "1", nx=True, ex=ttl):
                await self._increment_bargain(chat_id)
        await self._add_message(conv.id, "assistant", bot_reply, last_intent=intent)
        await self.redis.setex(
            committed_key, ttl,
            json.dumps({"chat_id": chat_id, "toid": send_user_id, "reply": bot_reply}),
        )
        logger.info(f"AI回复完成 | chat_id={chat_id}, 意图={intent}, 回复: {bot_reply}")

        if self.simulate_human_typing:
            delay = min(random.uniform(0, 1) + len(bot_reply) * random.uniform(0.1, 0.3), 10.0)
            logger.debug(f"模拟打字延迟 {delay:.1f}s")
            await asyncio.sleep(delay)

        if not self.is_connected:
            logger.warning(f"WS 未连接，回复待重连后发送 | id={entry_id}")
            return "retry"
        try:
            await self.send_msg(self.ws, chat_id, send_user_id, bot_reply)
        except Exception as e:
            logger.warning(f"发送失败，留 PEL 重发 | id={entry_id}: {e}")
            return "retry"
        await self.redis.setex(done_key, ttl, "1")
        return "done"

    async def heartbeat_loop(self, ws):
        while True:
            try:
                current_time = time.time()
                if current_time - self.last_heartbeat_time >= self.heartbeat_interval:
                    heartbeat_msg = {"lwp": "/!", "headers": {"mid": generate_mid()}}
                    await ws.send(json.dumps(heartbeat_msg))
                    self.last_heartbeat_time = time.time()

                if (current_time - self.last_heartbeat_response) > (self.heartbeat_interval + self.heartbeat_timeout):
                    logger.warning("心跳响应超时，可能连接已断开")
                    break

                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"心跳循环出错: {e}")
                break

    async def run(self):
        while not self._stopped:
            try:
                self.connection_restart_flag = False
                if self.token_mgr.needs_refresh():
                    logger.info("Token需要刷新...")
                    await self.token_mgr.refresh()
                    logger.info("Token刷新完成")
                if not self.token_mgr.current_token:
                    remaining = int(self.apis.risk_control_until - time.time())
                    if remaining > 0:
                        wait = min(remaining + 5, 120)
                        logger.error(f"风控冷却中，剩余 {remaining}s，本轮等待 {wait}s 后再检查")
                        await asyncio.sleep(wait)
                    else:
                        logger.error("无法获取Token，等待重试...")
                        await asyncio.sleep(30)
                    continue

                headers = {
                    "Cookie": self.cookies_str,
                    "Host": "wss-goofish.dingtalk.com",
                    "Connection": "Upgrade",
                    "Pragma": "no-cache",
                    "Cache-Control": "no-cache",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                    "Origin": "https://www.goofish.com",
                    "Accept-Encoding": "gzip, deflate, br, zstd",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                }
                logger.info("正在连接WebSocket...")
                async with websockets.connect("wss://wss-goofish.dingtalk.com/", extra_headers=headers) as ws:
                    self.ws = ws

                    # 注册
                    reg_msg = {
                        "lwp": "/reg",
                        "headers": {
                            "cache-header": "app-key token ua wv",
                            "app-key": "444e9908a51d1cb236a27862abc769c9",
                            "token": self.token_mgr.current_token,
                            "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 DingTalk(2.1.5) OS(Windows/10) Browser(Chrome/133.0.0.0) DingWeb/2.1.5 IMPaaS DingWeb/2.1.5",
                            "dt": "j",
                            "wv": "im:3,au:3,sy:6",
                            "sync": "0,0;0;0;",
                            "did": self.device_id,
                            "mid": generate_mid(),
                        },
                    }
                    await ws.send(json.dumps(reg_msg))
                    await asyncio.sleep(1)

                    # 发送 ackDiff（与原版一致）
                    ack_diff_msg = {
                        "lwp": "/r/SyncStatus/ackDiff",
                        "headers": {"mid": generate_mid()},
                        "body": [{
                            "pipeline": "sync",
                            "tooLong2Tag": "PNM,1",
                            "channel": "sync",
                            "topic": "sync",
                            "highPts": 0,
                            "pts": int(time.time() * 1000) * 1000,
                            "seq": 0,
                            "timestamp": int(time.time() * 1000),
                        }],
                    }
                    await ws.send(json.dumps(ack_diff_msg))
                    logger.info(f"WebSocket连接注册完成 | myid={self.myid}, device_id={self.device_id}")

                    # 初始化心跳时间
                    self.last_heartbeat_time = time.time()
                    self.last_heartbeat_response = time.time()

                    # 启动心跳任务
                    hb_task = asyncio.create_task(self.heartbeat_loop(ws))

                    async for raw in ws:
                        try:
                            if self.connection_restart_flag:
                                logger.info("检测到连接重启标志，准备重新建立连接...")
                                break

                            data = json.loads(raw)

                            # 处理心跳响应
                            if (
                                isinstance(data, dict)
                                and "code" in data
                                and data["code"] == 200
                                and "headers" in data
                                and "mid" in data["headers"]
                            ):
                                self.last_heartbeat_response = time.time()
                                logger.debug("收到心跳响应")
                                continue

                            # 发送通用ACK响应
                            if "headers" in data and "mid" in data.get("headers", {}):
                                ack = {
                                    "code": 200,
                                    "headers": {
                                        "mid": data["headers"]["mid"],
                                        "sid": data["headers"].get("sid", ""),
                                    }
                                }
                                for key in ("app-key", "ua", "dt"):
                                    if key in data["headers"]:
                                        ack["headers"][key] = data["headers"][key]
                                await ws.send(json.dumps(ack))

                            # 处理消息
                            logger.debug(f"收到WebSocket消息 | lwp={data.get('lwp', 'N/A')}, keys={list(data.keys())}")
                            await self.handle_message(data, ws)

                        except json.JSONDecodeError:
                            logger.error("消息JSON解析失败")
                        except Exception as e:
                            logger.error(f"处理消息时发生错误: {e}")
                            logger.debug(f"原始消息: {raw}")

                    hb_task.cancel()
                    try:
                        await hb_task
                    except asyncio.CancelledError:
                        pass

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket连接关闭: code={e.code}, reason={e.reason}")
            except Exception as e:
                logger.error(f"连接错误: {e}", exc_info=True)
            finally:
                self.ws = None
                if self.connection_restart_flag:
                    logger.info("主动重启连接，立即重连...")
                else:
                    logger.info("等待5秒后重连...")
                    await asyncio.sleep(5)
