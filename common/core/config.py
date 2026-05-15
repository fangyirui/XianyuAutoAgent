from pydantic_settings import BaseSettings

DB_OVERRIDABLE_KEYS = ("API_KEY", "MODEL_BASE_URL", "MODEL_NAME", "COOKIES_STR")


class Settings(BaseSettings):
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "xianyu"
    MYSQL_PASSWORD: str = "xianyu_pass_123"
    MYSQL_DATABASE: str = "xianyu"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = "xianyu_redis_123"
    REDIS_DB: int = 0

    JWT_SECRET_KEY: str = "change-this-to-a-random-secret-key"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 10080

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"

    API_KEY: str = ""
    MODEL_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    MODEL_NAME: str = "qwen-max"

    COOKIES_STR: str = ""

    HEARTBEAT_INTERVAL: int = 15
    HEARTBEAT_TIMEOUT: int = 5
    TOKEN_REFRESH_INTERVAL: int = 3600
    TOKEN_RETRY_INTERVAL: int = 300
    MANUAL_MODE_TIMEOUT: int = 3600
    MESSAGE_EXPIRE_TIME: int = 300000
    TOGGLE_KEYWORDS: str = "。"
    SIMULATE_HUMAN_TYPING: bool = False

    WEBSOCKET_SERVICE_URL: str = "http://localhost:8090"
    BACKEND_WEB_URL: str = "http://localhost:8089"

    LOG_LEVEL: str = "INFO"

    @property
    def MYSQL_URL(self) -> str:
        return f"mysql+asyncmy://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"

    @property
    def REDIS_URL(self) -> str:
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    async def load_from_db(self):
        try:
            from common.db import AsyncSessionLocal
            from sqlalchemy import select

            async with AsyncSessionLocal() as db:
                from common.models import SystemConfig
                result = await db.execute(
                    select(SystemConfig).where(SystemConfig.key_name.in_(DB_OVERRIDABLE_KEYS))
                )
                for row in result.scalars():
                    if row.value:
                        object.__setattr__(self, row.key_name, row.value)
        except Exception:
            pass

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
