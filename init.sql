CREATE TABLE IF NOT EXISTS conversations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    chat_id VARCHAR(64) UNIQUE NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    user_nickname VARCHAR(128) COMMENT '买家昵称',
    item_id VARCHAR(64),
    manual_mode BOOLEAN DEFAULT FALSE,
    manual_mode_at DATETIME,
    bargain_count INT DEFAULT 0,
    last_intent VARCHAR(32),
    created_at DATETIME DEFAULT NOW(),
    updated_at DATETIME DEFAULT NOW() ON UPDATE NOW(),
    INDEX idx_user (user_id),
    INDEX idx_item (item_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    conversation_id BIGINT NOT NULL,
    role ENUM('user', 'assistant', 'system') NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT NOW(),
    INDEX idx_conv_time (conversation_id, created_at),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS item_cache (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    item_id VARCHAR(64) UNIQUE NOT NULL,
    seller_id VARCHAR(64) COMMENT '商品所属卖家ID',
    title VARCHAR(256),
    price DECIMAL(10,2),
    description TEXT,
    custom_prompt TEXT NULL COMMENT '该商品的额外AI提示词',
    default_reply TEXT NULL COMMENT '该商品的固定默认回复文本',
    default_reply_enabled TINYINT(1) NOT NULL DEFAULT 0 COMMENT '启用后跳过AI直接返回default_reply',
    raw_json JSON,
    fetched_at DATETIME DEFAULT NOW(),
    expired_at DATETIME,
    INDEX idx_item_cache_seller_id (seller_id)
);

CREATE TABLE IF NOT EXISTS system_config (
    id INT AUTO_INCREMENT PRIMARY KEY,
    key_name VARCHAR(128) UNIQUE NOT NULL,
    value TEXT,
    updated_at DATETIME DEFAULT NOW() ON UPDATE NOW()
);

CREATE TABLE IF NOT EXISTS sellers (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(64) UNIQUE NOT NULL COMMENT '闲鱼用户ID（cookie中unb字段）',
    nickname VARCHAR(128) COMMENT '卖家昵称',
    cookies_str TEXT NOT NULL COMMENT '闲鱼Cookie',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    last_login_at DATETIME COMMENT '最后登录时间',
    created_at DATETIME DEFAULT NOW(),
    updated_at DATETIME DEFAULT NOW() ON UPDATE NOW(),
    INDEX idx_sellers_is_active (is_active)
);

CREATE TABLE IF NOT EXISTS ai_call_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_name VARCHAR(32) NOT NULL COMMENT 'DefaultAgent/PriceAgent/TechAgent/ClassifyAgent',
    model VARCHAR(64) NOT NULL,
    chat_id VARCHAR(64) NULL COMMENT '关联会话；分类阶段可能为NULL',
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    total_tokens INT NOT NULL DEFAULT 0,
    latency_ms INT NOT NULL DEFAULT 0,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME DEFAULT NOW(),
    INDEX idx_ai_log_created (created_at),
    INDEX idx_ai_log_agent_created (agent_name, created_at)
);
