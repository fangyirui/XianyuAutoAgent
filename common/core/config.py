from typing import Optional
from pydantic_settings import BaseSettings

DB_OVERRIDABLE_KEYS = ("API_KEY", "MODEL_BASE_URL", "MODEL_NAME", "SKIP_KEYWORDS")


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
    # 字符串形式存放：允许 "" / "none" / "null" 表示禁用 top_p（部分网关不支持同时传 temperature 与 top_p）
    MODEL_TOP_P: Optional[str] = "0.8"

    COOKIES_STR: str = ""

    HEARTBEAT_INTERVAL: int = 15
    HEARTBEAT_TIMEOUT: int = 5
    TOKEN_REFRESH_INTERVAL: int = 3600
    TOKEN_RETRY_INTERVAL: int = 300
    MANUAL_MODE_TIMEOUT: int = 3600
    MESSAGE_EXPIRE_TIME: int = 300000
    TOGGLE_KEYWORDS: str = "。"
    SIMULATE_HUMAN_TYPING: bool = False
    SKIP_KEYWORDS: str = "快给ta一个评价吧,有蚂蚁森林能量可领"

    WEBSOCKET_SERVICE_URL: str = "http://localhost:8090"
    BACKEND_WEB_URL: str = "http://localhost:8089"

    # ── 消息队列（Redis Stream 可靠投递）────────────────────────────────
    # 买家消息先入 Stream，由同进程 worker 消费：AI 生成→发送，成功才 XACK；
    # 失败留 PEL 由 reclaimer 重投。彻底解决 AI/发送报错导致买家消息无人回复。
    MQ_WORKER_COUNT: int = 4            # 分片 worker 数：同 chat_id 串行、跨 chat_id 并发
    MQ_MAX_DELIVERIES: int = 5          # 单条最大投递次数，超过进死信流
    MQ_INLINE_RETRY: int = 2            # worker 内联快重试次数（兜瞬时抖动，不经 reclaimer）
    MQ_INLINE_RETRY_BASE_MS: int = 500  # 内联重试退避基值（指数：base*2^n）
    MQ_RECLAIM_IDLE_MS: int = 60000     # PEL 消息空闲多久可被 reclaim（> 单条最大处理耗时，防误抢在途）
    MQ_RECLAIM_INTERVAL: int = 15       # reclaimer 轮询间隔（秒）
    MQ_READ_BLOCK_MS: int = 5000        # XREADGROUP 阻塞读超时（毫秒）
    MQ_DEDUP_TTL: int = 600             # 去重标记 replied:{id} 存活秒数（>= 消息时效即可）
    # 新鲜度上限复用 MESSAGE_EXPIRE_TIME（毫秒）：age 超过则放弃发送，不回复过期消息
    # ── 去抖合并（短时间内同一买家连发多条 → 合并成一次 AI 回复）──────────
    # 同一 chat_id 的消息先在内存里按滑动窗口缓冲：每来一条把该会话的 flush
    # 推迟 WINDOW_MS；买家停顿超过窗口即合并 flush。MAX_MS 是从首条算起的硬上限，
    # 防"一直打字永不回复"。设 WINDOW_MS=0 关闭合并（每条立即处理，与改动前逐条等价）。
    MQ_DEBOUNCE_WINDOW_MS: int = 2000   # 滑动去抖窗口：买家停顿这么久就合并 flush
    MQ_DEBOUNCE_MAX_MS: int = 10000     # 合并硬上限：从首条消息算起最多等这么久必 flush

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
                    if row.value and row.key_name != "COOKIES_STR":
                        object.__setattr__(self, row.key_name, row.value)

                # Cookie 从 sellers 表读取
                from common.models import Seller
                seller_result = await db.execute(
                    select(Seller).where(Seller.is_active.is_(True)).limit(1)
                )
                seller = seller_result.scalar_one_or_none()
                if seller and seller.cookies_str:
                    object.__setattr__(self, "COOKIES_STR", seller.cookies_str)
        except Exception:
            pass

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
