"""幂等 schema 迁移：每次服务启动都跑一遍，已生效的步骤会被 INFORMATION_SCHEMA 检查跳过。

多服务并发调用安全：每条 ALTER 之前先查询当前结构，已满足条件就不发 ALTER；
即使两个服务同时进入到 ALTER 阶段，MySQL DDL 互斥也会让第二条成为重复无害操作。
"""
from sqlalchemy import text
from loguru import logger
from .session import engine


async def migrate() -> None:
    async with engine.begin() as conn:
        # item_cache.seller_id
        col_exists = (await conn.execute(text("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'item_cache' AND COLUMN_NAME = 'seller_id'
        """))).scalar()
        if col_exists == 0:
            await conn.execute(text(
                "ALTER TABLE item_cache ADD COLUMN seller_id VARCHAR(64) DEFAULT NULL, ADD INDEX idx_item_cache_seller_id (seller_id)"
            ))
            logger.info("迁移: 已为 item_cache 添加 seller_id 列")
        # 回填 seller_id（无论是否新加都跑一次幂等回填）
        await conn.execute(text("""
            UPDATE item_cache
            SET seller_id = NULLIF(COALESCE(
                JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.userId')),
                JSON_UNQUOTE(JSON_EXTRACT(raw_json, '$.sellerId'))
            ), 'null')
            WHERE seller_id IS NULL AND raw_json IS NOT NULL
        """))

        # conversations.user_nickname
        nick_col_exists = (await conn.execute(text("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'conversations' AND COLUMN_NAME = 'user_nickname'
        """))).scalar()
        if nick_col_exists == 0:
            await conn.execute(text(
                "ALTER TABLE conversations ADD COLUMN user_nickname VARCHAR(128) DEFAULT NULL AFTER user_id"
            ))
            logger.info("迁移: 已为 conversations 添加 user_nickname 列")

        # item_cache.custom_prompt
        cp_col_exists = (await conn.execute(text("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'item_cache' AND COLUMN_NAME = 'custom_prompt'
        """))).scalar()
        if cp_col_exists == 0:
            await conn.execute(text(
                "ALTER TABLE item_cache ADD COLUMN custom_prompt TEXT NULL COMMENT '该商品的额外AI提示词' AFTER description"
            ))
            logger.info("迁移: 已为 item_cache 添加 custom_prompt 列")

        # item_cache.default_reply / default_reply_enabled（商品级默认回复）
        dr_col_exists = (await conn.execute(text("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'item_cache' AND COLUMN_NAME = 'default_reply'
        """))).scalar()
        if dr_col_exists == 0:
            await conn.execute(text(
                "ALTER TABLE item_cache ADD COLUMN default_reply TEXT NULL COMMENT '该商品的固定默认回复文本' AFTER custom_prompt"
            ))
            logger.info("迁移: 已为 item_cache 添加 default_reply 列")
        dre_col_exists = (await conn.execute(text("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'item_cache' AND COLUMN_NAME = 'default_reply_enabled'
        """))).scalar()
        if dre_col_exists == 0:
            await conn.execute(text(
                "ALTER TABLE item_cache ADD COLUMN default_reply_enabled TINYINT(1) NOT NULL DEFAULT 0 COMMENT '启用后跳过AI直接返回default_reply' AFTER default_reply"
            ))
            logger.info("迁移: 已为 item_cache 添加 default_reply_enabled 列")

        # messages.role ENUM 扩充 'system'（闲鱼 [xxx] 系统事件入库）
        role_type = (await conn.execute(text("""
            SELECT COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'messages' AND COLUMN_NAME = 'role'
        """))).scalar() or ""
        if "system" not in role_type:
            await conn.execute(text(
                "ALTER TABLE messages MODIFY COLUMN role ENUM('user', 'assistant', 'system') NOT NULL"
            ))
            logger.info("迁移: 已为 messages.role 扩充 'system' 枚举值")
