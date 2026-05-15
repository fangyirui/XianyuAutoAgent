import asyncio
from fastapi import FastAPI
from loguru import logger
from common.core import settings
from .core import log_buffer


_live_instance = None
_live_task = None


async def _start_live(app_state=None):
    global _live_instance, _live_task

    await settings.load_from_db()

    if not settings.COOKIES_STR or not settings.API_KEY:
        logger.warning("配置不完整，WebSocket服务未启动")
        return

    from .websocket import XianyuLive
    from .api.routes.health import set_live_instance as set_health
    from .api.routes.control import set_live_instance as set_control

    _live_instance = XianyuLive()
    set_health(_live_instance)
    set_control(_live_instance)
    _live_task = asyncio.create_task(_live_instance.run())
    logger.info("WebSocket服务已启动")


async def _stop_live():
    global _live_instance, _live_task
    if _live_instance:
        await _live_instance.stop()
    if _live_task:
        _live_task.cancel()
        try:
            await _live_task
        except asyncio.CancelledError:
            pass
    _live_instance = None
    _live_task = None


async def _reload():
    logger.info("收到配置重载信号，正在重启...")
    await _stop_live()
    await _start_live()


async def _redis_subscriber():
    import redis.asyncio as aioredis
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe("config:reload")
    try:
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                await _reload()
    except asyncio.CancelledError:
        await pubsub.unsubscribe("config:reload")
        await r.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="XianyuAutoAgent WebSocket Service", version="2.0.0")

    from .api.routes import router
    app.include_router(router, prefix="/api")

    logger.add(log_buffer.sink, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module}:{line} | {message}", level="DEBUG")

    @app.on_event("startup")
    async def startup():
        await _start_live()
        asyncio.create_task(_redis_subscriber())

    return app
