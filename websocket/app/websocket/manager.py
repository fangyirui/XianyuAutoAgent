import json
import time
import asyncio
import base64
import random
import websockets
from loguru import logger
from sqlalchemy import select
from common.core import settings
from common.db import AsyncSessionLocal
from common.models import Conversation, Message, ItemCache
from common.utils import generate_mid, generate_uuid, generate_device_id, trans_cookies
from ..services.xianyu import XianyuApis, TokenManager
from ..services.xianyu.message_handler import (
    is_sync_package, is_chat_message, is_typing_status,
    is_bracket_system_message, decrypt_sync_data,
)
from ..services.agent import XianyuReplyBot


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

    async def _get_or_create_conversation(self, chat_id: str, user_id: str, item_id: str):
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Conversation).where(Conversation.chat_id == chat_id))
            conv = result.scalar_one_or_none()
            if not conv:
                conv = Conversation(chat_id=chat_id, user_id=user_id, item_id=item_id)
                db.add(conv)
                await db.commit()
                await db.refresh(conv)
            return conv

    async def _add_message(self, conversation_id: int, role: str, content: str):
        async with AsyncSessionLocal() as db:
            db.add(Message(conversation_id=conversation_id, role=role, content=content))
            await db.commit()

    async def _get_context(self, conversation_id: int, limit: int = 50) -> list:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at).limit(limit)
            )
            return [{"role": m.role, "content": m.content} for m in result.scalars().all()]

    async def _get_item_cache(self, item_id: str) -> dict | None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ItemCache).where(ItemCache.item_id == item_id))
            row = result.scalar_one_or_none()
            if row and row.raw_json:
                return row.raw_json
            return None

    async def _save_item_cache(self, item_id: str, data: dict):
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ItemCache).where(ItemCache.item_id == item_id))
            row = result.scalar_one_or_none()
            if row:
                row.raw_json = data
                row.title = data.get("title", "")
                row.price = float(data.get("soldPrice", 0))
            else:
                db.add(ItemCache(
                    item_id=item_id, raw_json=data,
                    title=data.get("title", ""),
                    price=float(data.get("soldPrice", 0)),
                    description=data.get("desc", ""),
                ))
            await db.commit()

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
            conv = await self._get_or_create_conversation(chat_id, send_user_id, item_id)
            await self._add_message(conv.id, "assistant", send_message)
            logger.debug(f"自己发送的消息已记录 | chat_id={chat_id}")
            return

        logger.info(f"收到用户消息 | 会话: {chat_id}, 用户: {send_user_id}, 商品: {item_id}, 内容: {send_message}")

        if self.is_manual_mode(chat_id):
            conv = await self._get_or_create_conversation(chat_id, send_user_id, item_id)
            await self._add_message(conv.id, "user", send_message)
            logger.info(f"人工接管中，仅记录 | chat_id={chat_id}")
            return

        if is_bracket_system_message(send_message):
            logger.debug(f"系统方括号消息，跳过: {send_message}")
            return

        item_info = await self._get_item_cache(item_id)
        if not item_info:
            logger.info(f"商品缓存未命中，调用API | item_id={item_id}")
            api_result = await self.apis.get_item_info(item_id)
            if "data" in api_result and "itemDO" in api_result["data"]:
                item_info = api_result["data"]["itemDO"]
                await self._save_item_cache(item_id, item_info)
                logger.info(f"商品信息已缓存 | item_id={item_id}, title={item_info.get('title', '')}")
            else:
                logger.warning(f"获取商品信息失败 | item_id={item_id}, response_keys={list(api_result.keys())}")
                return

        conv = await self._get_or_create_conversation(chat_id, send_user_id, item_id)
        context = await self._get_context(conv.id)
        item_desc = f"当前商品的信息如下：{self.build_item_description(item_info)}"
        logger.info(f"开始生成AI回复 | chat_id={chat_id}, 上下文条数={len(context)}")
        bot_reply = await self.bot.generate_reply(send_message, item_desc, context)

        if bot_reply == "-":
            logger.info(f"AI返回'-'，不回复 | chat_id={chat_id}")
            return

        await self._add_message(conv.id, "user", send_message)
        if self.bot.last_intent == "price":
            await self._increment_bargain(chat_id)
        await self._add_message(conv.id, "assistant", bot_reply)
        logger.info(f"AI回复完成 | chat_id={chat_id}, 意图={self.bot.last_intent}, 回复: {bot_reply}")

        if self.simulate_human_typing:
            delay = min(random.uniform(0, 1) + len(bot_reply) * random.uniform(0.1, 0.3), 10.0)
            logger.debug(f"模拟打字延迟 {delay:.1f}s")
            await asyncio.sleep(delay)

        await self.send_msg(ws, chat_id, send_user_id, bot_reply)

    async def heartbeat_loop(self, ws):
        while True:
            if time.time() - self.last_heartbeat_time >= self.heartbeat_interval:
                await ws.send(json.dumps({"lwp": "/!", "headers": {"mid": generate_mid()}}))
                self.last_heartbeat_time = time.time()
            if (time.time() - self.last_heartbeat_response) > (self.heartbeat_interval + self.heartbeat_timeout):
                logger.warning("心跳超时")
                break
            await asyncio.sleep(1)

    async def run(self):
        while not self._stopped:
            try:
                self.connection_restart_flag = False
                if self.token_mgr.needs_refresh():
                    logger.info("Token需要刷新...")
                    await self.token_mgr.refresh()
                    logger.info("Token刷新完成")
                if not self.token_mgr.current_token:
                    logger.error("无法获取Token，等待重试...")
                    await asyncio.sleep(30)
                    continue

                headers = {"Cookie": self.cookies_str, "Host": "wss-goofish.dingtalk.com", "Origin": "https://www.goofish.com"}
                logger.info("正在连接WebSocket...")
                async with websockets.connect("wss://wss-goofish.dingtalk.com/", extra_headers=headers) as ws:
                    self.ws = ws
                    reg_msg = {
                        "lwp": "/reg",
                        "headers": {
                            "cache-header": "app-key token ua wv",
                            "app-key": "444e9908a51d1cb236a27862abc769c9",
                            "token": self.token_mgr.current_token,
                            "ua": "Mozilla/5.0 DingTalk(2.1.5) DingWeb/2.1.5 IMPaaS",
                            "dt": "j", "wv": "im:3,au:3,sy:6", "sync": "0,0;0;0;",
                            "did": self.device_id, "mid": generate_mid(),
                        },
                    }
                    await ws.send(json.dumps(reg_msg))
                    await asyncio.sleep(1)
                    logger.info(f"WebSocket连接注册完成 | myid={self.myid}, device_id={self.device_id}")

                    self.last_heartbeat_time = time.time()
                    self.last_heartbeat_response = time.time()
                    hb_task = asyncio.create_task(self.heartbeat_loop(ws))

                    async for raw in ws:
                        if self.connection_restart_flag:
                            break
                        data = json.loads(raw)
                        if data.get("code") == 200 and "mid" in data.get("headers", {}):
                            self.last_heartbeat_response = time.time()
                            continue
                        logger.debug(f"收到WebSocket消息 | lwp={data.get('lwp', 'N/A')}, keys={list(data.keys())}")
                        await self.handle_message(data, ws)

                    hb_task.cancel()

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket连接关闭: code={e.code}, reason={e.reason}")
            except Exception as e:
                logger.error(f"连接错误: {e}", exc_info=True)
            finally:
                self.ws = None
                if not self.connection_restart_flag:
                    logger.info("5秒后重连...")
                    await asyncio.sleep(5)
