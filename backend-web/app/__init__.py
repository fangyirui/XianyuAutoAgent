from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    from common.db import engine
    from common.models import Base
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 补充已有表缺失的列
        col_exists = (await conn.execute(text("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'item_cache' AND COLUMN_NAME = 'seller_id'
        """))).scalar()
        if col_exists == 0:
            await conn.execute(text(
                "ALTER TABLE item_cache ADD COLUMN seller_id VARCHAR(64) DEFAULT NULL, ADD INDEX idx_item_cache_seller_id (seller_id)"
            ))
        # 回填已有商品的 seller_id（从 raw_json 提取）
        await conn.execute(text("""
            UPDATE item_cache
            SET seller_id = NULLIF(COALESCE(
                JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.userId')),
                JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.sellerId'))
            ), 'null')
            WHERE seller_id IS NULL AND raw_json IS NOT NULL
        """))
        # conversations 表补加 user_nickname 列
        nick_col_exists = (await conn.execute(text("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'conversations' AND COLUMN_NAME = 'user_nickname'
        """))).scalar()
        if nick_col_exists == 0:
            await conn.execute(text(
                "ALTER TABLE conversations ADD COLUMN user_nickname VARCHAR(128) DEFAULT NULL AFTER user_id"
            ))
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="XianyuAutoAgent API", version="2.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from .api.routes import router
    app.include_router(router, prefix="/api")

    return app
