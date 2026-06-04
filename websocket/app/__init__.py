import asyncio
from fastapi import FastAPI
from loguru import logger
from common.core import settings
from .core import log_buffer


_live_instance = None
_live_task = None
_redis_task = None
_mq_consumer = None


async def _start_live(app_state=None):
    global _live_instance, _live_task, _mq_consumer

    await settings.load_from_db()

    if not settings.COOKIES_STR or not settings.API_KEY:
        logger.warning("配置不完整，WebSocket服务未启动")
        return

    from .websocket import XianyuLive
    from .websocket.message_queue import MessageQueueConsumer
    from .api.routes.health import set_live_instance as set_health
    from .api.routes.control import set_live_instance as set_control

    _live_instance = XianyuLive()
    await _live_instance.bot.load_prompts_from_db()
    set_health(_live_instance)
    set_control(_live_instance)
    _live_task = asyncio.create_task(_live_instance.run())
    # 消息队列消费者：持有 live 引用，soft_reload 换 bot 后无需重建
    _mq_consumer = MessageQueueConsumer(_live_instance, _live_instance.redis)
    await _mq_consumer.start()
    logger.info("WebSocket服务已启动")


async def _stop_live():
    global _live_instance, _live_task, _mq_consumer
    if _mq_consumer:
        await _mq_consumer.stop()
    if _live_instance:
        await _live_instance.stop()
    if _live_task:
        _live_task.cancel()
        try:
            await _live_task
        except asyncio.CancelledError:
            pass
    _mq_consumer = None
    _live_instance = None
    _live_task = None


async def _reload():
    logger.info("收到配置重载信号，正在重启...")
    await _stop_live()
    await _start_live()


async def _soft_reload():
    """热重载：刷新内存配置 + 重建 bot，不断开 WebSocket 连接。"""
    global _live_instance
    if not _live_instance:
        logger.info("WebSocket未运行，尝试启动...")
        await _start_live()
        return

    await settings.load_from_db()

    _live_instance.skip_keywords = [k.strip() for k in settings.SKIP_KEYWORDS.split(",") if k.strip()]
    _live_instance.toggle_keywords = settings.TOGGLE_KEYWORDS
    _live_instance.manual_mode_timeout = settings.MANUAL_MODE_TIMEOUT
    _live_instance.message_expire_time = settings.MESSAGE_EXPIRE_TIME
    _live_instance.simulate_human_typing = settings.SIMULATE_HUMAN_TYPING

    from .services.agent import XianyuReplyBot
    _live_instance.bot = XianyuReplyBot()
    await _live_instance.bot.load_prompts_from_db()

    logger.info("配置已软重载（WebSocket 连接保持）")


async def _redis_subscriber():
    import redis.asyncio as aioredis
    while True:
        r = None
        pubsub = None
        try:
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.subscribe("config:reload")
            logger.info("Redis 配置重载订阅已建立")
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                data = msg.get("data", "")
                try:
                    if data in ("cookie_updated", "qrlogin"):
                        await _reload()
                    else:
                        await _soft_reload()
                except Exception as e:
                    logger.exception(f"处理重载消息失败: {e}")
        except asyncio.CancelledError:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe("config:reload")
                except Exception:
                    pass
            if r is not None:
                try:
                    await r.aclose()
                except Exception:
                    pass
            raise
        except Exception as e:
            logger.warning(f"Redis 订阅异常，5 秒后重连: {e}")
            if pubsub is not None:
                try:
                    await pubsub.aclose()
                except Exception:
                    pass
            if r is not None:
                try:
                    await r.aclose()
                except Exception:
                    pass
            await asyncio.sleep(5)


def create_app() -> FastAPI:
    app = FastAPI(title="XianyuAutoAgent WebSocket Service", version="2.0.0")

    from .api.routes import router
    app.include_router(router, prefix="/api")

    logger.add(log_buffer.sink, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module}:{line} | {message}", level="DEBUG")

    @app.on_event("startup")
    async def startup():
        global _redis_task
        from common.db import engine, migrate
        from common.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        # 在开始处理消息之前先把 schema 迁移跑完（与 backend-web 启动并发安全：
        # 每条 ALTER 都先查 INFORMATION_SCHEMA，幂等且 MySQL DDL 互斥）
        await migrate()
        await _start_live()
        _redis_task = asyncio.create_task(_redis_subscriber())

    return app
