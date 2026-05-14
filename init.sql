CREATE TABLE IF NOT EXISTS conversations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    chat_id VARCHAR(64) UNIQUE NOT NULL,
    user_id VARCHAR(64) NOT NULL,
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
    role ENUM('user', 'assistant') NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT NOW(),
    INDEX idx_conv_time (conversation_id, created_at),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS item_cache (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    item_id VARCHAR(64) UNIQUE NOT NULL,
    title VARCHAR(256),
    price DECIMAL(10,2),
    description TEXT,
    raw_json JSON,
    fetched_at DATETIME DEFAULT NOW(),
    expired_at DATETIME
);

CREATE TABLE IF NOT EXISTS system_config (
    id INT AUTO_INCREMENT PRIMARY KEY,
    key_name VARCHAR(128) UNIQUE NOT NULL,
    value TEXT,
    updated_at DATETIME DEFAULT NOW() ON UPDATE NOW()
);
