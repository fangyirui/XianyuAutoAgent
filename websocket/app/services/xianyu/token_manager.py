import time
from loguru import logger
from common.core import settings
from .apis import XianyuApis


class TokenManager:
    def __init__(self, apis: XianyuApis, device_id: str):
        self.apis = apis
        self.device_id = device_id
        self.current_token: str | None = None
        self.last_refresh_time: float = 0
        self.refresh_interval = settings.TOKEN_REFRESH_INTERVAL
        self.retry_interval = settings.TOKEN_RETRY_INTERVAL

    async def refresh(self) -> str | None:
        result = await self.apis.get_token(self.device_id)
        if result and "data" in result and "accessToken" in result["data"]:
            self.current_token = result["data"]["accessToken"]
            self.last_refresh_time = time.time()
            logger.info("Token刷新成功")
            return self.current_token
        logger.error("Token刷新失败")
        return None

    def needs_refresh(self) -> bool:
        return time.time() - self.last_refresh_time >= self.refresh_interval
