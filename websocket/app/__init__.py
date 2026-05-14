import asyncio
from fastapi import FastAPI
from loguru import logger
from common.core import settings


def create_app() -> FastAPI:
    app = FastAPI(title="XianyuAutoAgent WebSocket Service", version="2.0.0")

    from .api.routes import router
    app.include_router(router, prefix="/api")

    @app.on_event("startup")
    async def startup():
        if not settings.COOKIES_STR or not settings.API_KEY:
            logger.warning("配置不完整，WebSocket服务未启动")
            return
        from .websocket import XianyuLive
        from .api.routes.health import set_live_instance as set_health
        from .api.routes.control import set_live_instance as set_control

        live = XianyuLive()
        set_health(live)
        set_control(live)
        asyncio.create_task(live.run())
        logger.info("WebSocket服务已启动")

    return app
