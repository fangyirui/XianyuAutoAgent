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
from common.models import Conversation, Message, ItemCache, Seller
from common.utils import generate_mid, generate_uuid, generate_device_id, trans_cookies
from ..services.xianyu import XianyuApis, TokenManager
from ..services.xianyu.message_handler import (
    is_sync_package, is_chat_message, is_typing_status,
    is_bracket_system_message, decrypt_sync_data,
)
from ..services.agent import XianyuReplyBot
from .message_queue import enqueue
from ..core import conv_events


# 商品默认回复内的分隔符占位符：写死，不走配置。发送时按它切割成多条消息逐条发出。
# 文本中不含该占位符时，发送逻辑退化为单条原文发送（与改动前字节级一致）。
REPLY_SPLIT_DELIMITER = "{$分隔符}"


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
        # 最近一次已落库的 cookie 串：避免每次刷新都写库，仅在真正变化时持久化
        self._persisted_cookie_str = cookies_str

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
            # 实时增量推送：落库成功后把这条消息广播给 SSE 订阅者（前端对话页实时刷新）。
            # 严格事后副作用——整段 try 包裹，推送失败绝不影响落库与主流程。
            try:
                conv_events.publish({
                    "conversation_id": conversation_id,
                    "message": {
                        "id": msg.id,
                        "role": role,
                        "content": content,
                        "created_at": msg.created_at.isoformat() if msg.created_at else None,
                    },
                })
            except Exception as e:
                logger.debug(f"会话事件推送失败（不影响落库）| conv_id={conversation_id}: {e}")
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

    @staticmethod
    def _split_reply(text: str) -> list:
        """按写死的分隔符占位符把回复切成多段，去掉空白段。
        不含占位符时返回 [text] —— 上层据此退化为单条发送，字节级与改动前一致。"""
        if REPLY_SPLIT_DELIMITER not in text:
            return [text]
        return [seg.strip() for seg in text.split(REPLY_SPLIT_DELIMITER) if seg.strip()]

    async def send_msg_multi(self, ws, cid: str, toid: str, text: str):
        """发送回复：若文本含分隔符占位符则切成多条按序逐条发出，否则单条发送。
        多条之间留少量随机停顿，更接近真人连发。"""
        segments = self._split_reply(text)
        for i, seg in enumerate(segments):
            if i > 0:
                await asyncio.sleep(random.uniform(0.5, 1.2))
            await self.send_msg(ws, cid, toid, seg)

    async def manual_send(self, chat_id: str, text: str) -> dict:
        """从控制台人工发送一条消息给买家。

        行为与卖家在闲鱼 App 内手动回复完全一致：仅发送 + 落库 role='assistant'
        （见 handle_message 中 send_user_id == self.myid 分支），不触碰人工接管
        （manual_mode）或任何其它会话状态字段。会话必须已存在（买家先发过），
        否则拿不到买家 user_id（toid）。"""
        text = (text or "").strip()
        if not text:
            return {"status": "error", "detail": "empty_text"}
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Conversation).where(Conversation.chat_id == chat_id))
            conv = result.scalar_one_or_none()
        if not conv:
            return {"status": "error", "detail": "conversation_not_found"}
        if not self.is_connected:
            return {"status": "error", "detail": "ws_not_connected"}
        try:
            await self.send_msg(self.ws, chat_id, conv.user_id, text)
        except Exception as e:
            logger.warning(f"人工发送失败 | chat_id={chat_id}: {e}")
            return {"status": "error", "detail": "send_failed"}
        await self._add_message(conv.id, "assistant", text)
        logger.info(f"✉️ 人工发送 | chat_id={chat_id}, 内容: {text}")
        return {"status": "ok", "chat_id": chat_id}

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
        lines = [
            f"商品标题：{item_info.get('title', '')}",
            f"商品描述：{item_info.get('desc', '')}",
            f"商品价格：{price_display}",
        ]
        if clean_skus:
            sku_text = "；".join(
                f"{s['spec']}（{s['price']}元/库存{s['stock']}）" for s in clean_skus
            )
            lines.append(f"商品规格：{sku_text}")
        return "\n".join(lines)

    async def handle_message(self, message_data: dict, ws):
        if not is_sync_package(message_data):
            return
        # syncPushPackage.data 是数组：闲鱼会把多条变更打包进同一个推送包（注册后回放
        # 离线消息、买家连发、积压等）。此前只取 data[0]，data[1:] 被静默丢弃——既不入队、
        # 不重试、不记日志，可靠队列对其毫无保护。这里逐条处理，杜绝"消息被吞且无痕迹"。
        data_list = message_data["body"]["syncPushPackage"]["data"]
        if len(data_list) > 1:
            logger.warning(f"同步包内含 {len(data_list)} 条数据，逐条处理")
        for sync_data in data_list:
            try:
                await self._handle_one_sync(sync_data, ws)
            except Exception as e:
                logger.error(f"处理单条同步数据出错（跳过该条，不影响同包其余）: {e}")

    async def _handle_one_sync(self, sync_data: dict, ws):
        """处理同步包内的单条数据：解密 + 全部 intake 门控 + 入队。
        从 handle_message 拆出，使一个推送包内的多条消息都能被逐条处理。"""
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
        # 此处仅保留无副作用的入口门控；产生回复的逻辑统一在 process_job_batch 中执行。
        await enqueue(self.redis, {
            "chat_id": chat_id,
            "send_user_id": send_user_id,
            "item_id": item_id,
            "send_message": send_message,
            "sender_nickname": sender_nickname or "",
            "create_time": create_time,
        })
        logger.info(f"消息已入队待处理 | chat_id={chat_id}, item_id={item_id}")

    @staticmethod
    def _batch_text(batch: list) -> str:
        """合并一批买家消息为单条"当前消息"喂给 AI。批大小=1 时即原文本身，
        保证单条消息的 LLM 入参与改动前字节级一致。"""
        return "\n".join(f.get("send_message", "") for _, f in batch)

    @staticmethod
    def _batch_newest_ct(batch: list) -> int:
        """批内最新一条的 create_time（毫秒）。新鲜度按最新条判定——缓冲期再长，
        只要最后一条仍在时效内就回复，不因合并等待把整批判过期。"""
        cts = []
        for _, f in batch:
            try:
                cts.append(int(f.get("create_time", "0")))
            except (ValueError, TypeError):
                pass
        return max(cts) if cts else 0

    async def _mark_done(self, ids: list, ttl: int):
        """标记批内每条消息均已并入一次已发送的回复。按成员粒度打标，使任一成员
        被 reclaim 重投时都能识别"已处理"，杜绝拆批重投导致的重复回复。"""
        for entry_id in ids:
            await self.redis.setex(f"mq:mdone:{entry_id}", ttl, "1")

    async def process_job_batch(self, batch: list) -> str:
        """消费一整批（同一 chat_id 去抖合并后的若干条）买家消息，合并成一次 AI 回复。

        返回值约定（consumer 据此决定整批 XACK 还是整批留 PEL）：
          done    成功发送（或 '-' 无需回复 / 全部已处理）→ 整批 XACK
          drop    整批过期，不再回复 → 整批 XACK
          retry   可重试失败（AI 报错 / 详情API失败 / 发送失败 / WS 未连）→ 整批留 PEL

        幂等以 batch_key（批内最小 entry_id）为主键：mq:bcommit / mq:umsg / mq:bincr
        各只发生一次；mq:mdone:{每个成员} 在成功发送后逐条打标。一旦回复文本提交
        （bcommit），发送失败的重投只重发已提交文本，不再生成、不污染上下文。"""
        batch = sorted(batch, key=lambda x: x[0])  # 按 stream id 升序 = 到达顺序
        ids = [e for e, _ in batch]
        batch_key = ids[0]
        ttl = settings.MQ_DEDUP_TTL
        committed_key = f"mq:bcommit:{batch_key}"

        first = batch[0][1]
        chat_id = first.get("chat_id", "")
        send_user_id = first.get("send_user_id", "")
        item_id = first.get("item_id", "")
        # 与原 handle_message 一致：空昵称传 "" 而非 None
        sender_nickname = first.get("sender_nickname", "")

        # 全部成员已并入过某次已发送回复（重投 / ack 丢失）→ 跳过，避免重复回复
        all_done = True
        for entry_id in ids:
            if not await self.redis.exists(f"mq:mdone:{entry_id}"):
                all_done = False
                break
        if all_done:
            logger.debug(f"批全部已完成，跳过重投 | ids={ids}")
            return "done"

        # 新鲜度复检：按最新一条判定，整批过期才丢弃
        newest_ct = self._batch_newest_ct(batch)
        if newest_ct > 0 and (time.time() * 1000 - newest_ct) > self.message_expire_time:
            logger.info(f"队列批已过期，丢弃不回复 | ids={ids}, chat_id={chat_id}")
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
                    logger.warning(f"重发但 WS 未连接，待重连后重试 | ids={ids}")
                    return "retry"
                try:
                    await self.send_msg_multi(self.ws, data["chat_id"], data["toid"], data["reply"])
                except Exception as e:
                    logger.warning(f"批重发失败，留 PEL | ids={ids}: {e}")
                    return "retry"
                await self._mark_done(ids, ttl)
                logger.info(f"批重发成功 | ids={ids}, chat_id={data['chat_id']}")
                return "done"

        return await self._process_fresh_batch(
            batch, ids, batch_key, committed_key, ttl,
            chat_id, send_user_id, item_id, sender_nickname,
        )


    async def _process_fresh_batch(
        self, batch, ids, batch_key, committed_key, ttl,
        chat_id, send_user_id, item_id, sender_nickname,
    ) -> str:
        """首次处理一批（未 committed）：把批内多条买家消息合并成一次 AI 回复。
        批大小=1 时逐行等价于改动前的单条路径，默认配置下 LLM 入参与发送字节级不变。

        与单条版差异：user 消息按成员各自落库（保真历史），但喂给 AI 的"当前消息"
        是合并文本；幂等标记按 batch_key（首条 entry_id）建，成功后逐条打 mdone。"""
        merged_message = self._batch_text(batch)
        # 商品级默认回复门控：启用且文本非空时，仅对会话首条买家消息短路 AI 直接发固定文本。
        # 合并语义下：整批的多条 user 消息都各自落库，再发一次默认回复。
        default_reply = await self._get_item_default_reply(item_id)
        if default_reply:
            conv = await self._get_or_create_conversation(chat_id, send_user_id, item_id, sender_nickname)
            if not await self._has_user_message(conv.id):
                await self._persist_user_msgs(batch, conv.id, batch_key, ttl)
                await self._add_message(conv.id, "assistant", default_reply)
                logger.info(f"使用商品默认回复(首条) | chat_id={chat_id}, item_id={item_id}, reply={default_reply}")
                await self.redis.setex(
                    committed_key, ttl,
                    json.dumps({"chat_id": chat_id, "toid": send_user_id, "reply": default_reply}),
                )
                if not self.is_connected:
                    logger.warning(f"WS 未连接，默认回复待重连后发送 | ids={ids}")
                    return "retry"
                try:
                    await self.send_msg_multi(self.ws, chat_id, send_user_id, default_reply)
                except Exception as e:
                    logger.warning(f"默认回复发送失败，留 PEL | ids={ids}: {e}")
                    return "retry"
                await self._mark_done(ids, ttl)
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
        item_desc = self.build_item_description(item_info)
        item_custom_prompt = await self._get_item_custom_prompt(item_id)

        # 留痕 user 消息 —— 整批仅一次。重投（上次 AI 失败、未 commit）时复用同一批行，
        # 并据首行 id 重建"落库前"的上下文，保证重试与首次的 LLM 入参字节级一致。
        umsg_key = f"mq:umsg:{batch_key}"
        prior = await self.redis.get(umsg_key)
        if prior:
            first_msg_id = int(prior)
            context = await self._get_context_before(conv.id, first_msg_id)
        else:
            context = await self._get_context(conv.id)
            first_msg_id = await self._persist_user_msgs(batch, conv.id, batch_key, ttl)
        logger.info(
            f"开始生成AI回复 | chat_id={chat_id}, 合并条数={len(batch)}, "
            f"上下文条数={len(context)}, 商品额外提示词长度={len(item_custom_prompt)}"
        )
        try:
            bot_reply, intent = await self.bot.generate_reply(
                merged_message, item_desc, context, item_custom_prompt=item_custom_prompt, chat_id=chat_id,
            )
        except Exception as e:
            logger.error(f"AI生成回复异常，user 消息已留痕，留 PEL 重试 | chat_id={chat_id}, err={e}")
            return "retry"

        if bot_reply == "-":
            logger.info(f"AI返回'-'，不回复 | chat_id={chat_id}")
            await self._mark_done(ids, ttl)
            return "done"

        # 提交：递增议价、落库 assistant、写 committed —— 这些副作用整批只发生一次。
        # 写 committed 之后即便发送失败，重投也只走"重发路径"，不再生成、不再落库、不再递增。
        # 合并语义：一批多条买家消息只算一轮议价（+1），比逐条 +N 更贴合真实交互。
        if intent == "price":
            if await self.redis.set(f"mq:bincr:{batch_key}", "1", nx=True, ex=ttl):
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
            logger.warning(f"WS 未连接，回复待重连后发送 | ids={ids}")
            return "retry"
        try:
            await self.send_msg(self.ws, chat_id, send_user_id, bot_reply)
        except Exception as e:
            logger.warning(f"发送失败，留 PEL 重发 | ids={ids}: {e}")
            return "retry"
        await self._mark_done(ids, ttl)
        return "done"

    async def _persist_user_msgs(self, batch, conv_id, batch_key, ttl) -> int:
        """把批内每条买家消息各自落一行 user（保真历史），返回首行 id 并缓存于
        mq:umsg:{batch_key}（供重投重建落库前上下文）。批大小=1 时与单条落库等价。"""
        first_id = None
        for _, f in batch:
            mid = await self._add_message(conv_id, "user", f.get("send_message", ""))
            if first_id is None:
                first_id = mid
        await self.redis.setex(f"mq:umsg:{batch_key}", ttl, str(first_id))
        return first_id


    async def _persist_cookies(self):
        """把 apis 滚动续期后的最新 cookie 写回 sellers 表。

        闲鱼登录态（_m_h5_tk / cookie2 等）是滑动过期的：每次 mtop 请求服务端会
        通过 Set-Cookie 回一份续期值，apis 已接住并存于 self.apis.cookies。若不落库，
        容器一重启就退回 .env / 旧 sellers 记录里几天前的快照，等于白滚——这正是
        手配 cookie 一两天就失效的根因之一。仅在 cookie 真正变化时写，避免无谓写库。"""
        latest = self.apis.cookie_str
        if latest == self._persisted_cookie_str:
            return
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    update(Seller)
                    .where(Seller.user_id == str(self.myid))
                    .values(cookies_str=latest, last_login_at=func.now())
                )
                if not result.rowcount:
                    # 纯 .env 模式：sellers 表还没有本账号的行，插一条让续期成果重启可用。
                    # user_id = cookie 里的 unb，与扫码登录建行口径一致。
                    db.add(Seller(
                        user_id=str(self.myid),
                        cookies_str=latest,
                        is_active=True,
                        last_login_at=func.now(),
                    ))
                await db.commit()
            self._persisted_cookie_str = latest
            logger.info("滚动续期 cookie 已持久化到 sellers 表")
        except Exception as e:
            logger.warning(f"持久化 cookie 失败（不影响运行）: {e}")

    async def token_refresh_loop(self):
        """连接存活期间的定时刷新/保活循环。

        闲鱼长连的 Cookie / token 只在握手 + /reg 注册时用一次，连接建立后靠心跳维持，
        服务端不会因初始 cookie 快照过期而主动断开这条已建立的长连。真正会失败的是
        断线后“重连”握手用到几天前的旧快照。所以这里不打断长连，只周期性打 mtop 接口
        让 token / cookie 滚动续期（refresh 经 Set-Cookie 续期 cookie）并落库——下次因
        网络原因自然重连时，run() 会从 apis.cookie_str 取到最新值，握手不再用过期快照。"""
        # 刷新失败（cookie 真失效）后的退避截止时间：在此之前不再打 token 接口，
        # 避免 needs_refresh() 恒为 true 导致每 60s 死循环重试、徒增风控风险。
        backoff_until = 0.0
        while True:
            try:
                await asyncio.sleep(60)
                if self.connection_restart_flag:
                    return
                if not self.token_mgr.needs_refresh():
                    continue
                if time.time() < backoff_until:
                    continue
                logger.info("Token 到刷新点，定时刷新中...")
                token = await self.token_mgr.refresh()
                # 无论刷新成败，apis.cookies 都可能已被本次请求滚动续期，尝试落库
                await self._persist_cookies()
                if token:
                    backoff_until = 0.0
                    logger.info("定时刷新成功，token / cookie 已滚动续期（保持长连）")
                else:
                    backoff_until = time.time() + self.token_mgr.retry_interval
                    logger.warning(
                        f"定时刷新失败，{self.token_mgr.retry_interval}s 后重试（保持当前连接）"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # 刷新链路意外异常也要退避，否则 refresh() 没更新 last_refresh_time，
                # needs_refresh() 恒 True，下一轮 60s 后必再触发，变成周期性风暴。
                backoff_until = time.time() + self.token_mgr.retry_interval
                logger.error(f"Token 刷新循环出错: {e}，{self.token_mgr.retry_interval}s 后重试")

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
                    await self._persist_cookies()
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
                    # 取 apis 维护的实时 cookie（含滚动续期），而非 __init__ 的初始快照，
                    # 否则重连永远用旧 cookie，初始快照一过期就连不上。
                    "Cookie": self.apis.cookie_str,
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
                    # 启动定时刷新/保活任务：连接存活期间持续滚动 token 与 cookie
                    refresh_task = asyncio.create_task(self.token_refresh_loop())

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
                    refresh_task.cancel()
                    for _t in (hb_task, refresh_task):
                        try:
                            await _t
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
