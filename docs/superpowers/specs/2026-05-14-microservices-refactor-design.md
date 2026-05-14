# XianyuAutoAgent 微服务架构重构设计

## 概述

将 XianyuAutoAgent 从单体 Python 应用重构为前后端分离的微服务架构，参照 xianyu-auto-reply 项目的架构模式。保留现有全部功能（WebSocket 接入、LLM Agent 自动回复、人工接管、扫码登录、提示词配置），不新增业务功能。

## 服务划分

| 服务 | 端口 | 技术栈 | 职责 |
|------|------|--------|------|
| frontend | 9000 (dev) / 80 (prod) | React 18 + Vite + Tailwind + Zustand | Web 管理界面 |
| backend-web | 8089 | Python FastAPI + async SQLAlchemy | 主业务 API |
| websocket | 8090 | Python FastAPI + websockets | 闲鱼 IM 接入、Agent 回复 |
| mysql | 3306 | MySQL 8.0 | 持久化存储 |
| redis | 6379 | Redis 7 | 缓存 + 会话 + JWT 存储 |

## 目录结构

```
XianyuAutoAgent/
├── common/                     # 共享模块
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py           # Pydantic Settings 统一配置
│   ├── db/
│   │   ├── __init__.py
│   │   ├── session.py          # async SQLAlchemy session factory
│   │   └── redis_client.py     # Redis 连接池
│   ├── models/
│   │   ├── __init__.py
│   │   ├── message.py          # 消息记录 ORM
│   │   ├── conversation.py     # 会话 ORM
│   │   └── item_cache.py       # 商品缓存 ORM
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── message.py          # Pydantic 请求/响应模型
│   └── utils/
│       ├── __init__.py
│       └── xianyu_utils.py     # 工具函数
│
├── backend-web/
│   ├── main.py
│   ├── app/
│   │   ├── __init__.py         # create_app() factory
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── deps.py         # 依赖注入
│   │   │   └── routes/
│   │   │       ├── __init__.py
│   │   │       ├── auth.py     # JWT 登录/刷新
│   │   │       ├── config.py   # 提示词/环境变量 CRUD
│   │   │       ├── logs.py     # 对话日志查询
│   │   │       └── qr_login.py # 扫码登录
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   └── security.py     # JWT 生成/验证
│   │   └── services/
│   │       ├── __init__.py
│   │       └── qr_login/
│   ├── Dockerfile
│   └── requirements.txt
│
├── websocket/
│   ├── main.py
│   ├── app/
│   │   ├── __init__.py         # create_app()
│   │   ├── api/
│   │   │   └── routes/
│   │   │       ├── __init__.py
│   │   │       └── health.py   # 健康检查 + 状态查询
│   │   ├── core/
│   │   │   └── __init__.py
│   │   ├── services/
│   │   │   ├── xianyu/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── connection.py   # WebSocket 连接管理
│   │   │   │   ├── message_handler.py  # 消息解密、分发
│   │   │   │   └── token_manager.py    # Token 刷新
│   │   │   └── agent/
│   │   │       ├── __init__.py
│   │   │       ├── router.py       # IntentRouter
│   │   │       ├── base.py         # BaseAgent
│   │   │       ├── classify.py     # ClassifyAgent
│   │   │       ├── price.py        # PriceAgent
│   │   │       ├── tech.py         # TechAgent
│   │   │       └── default.py      # DefaultAgent
│   │   └── websocket/
│   │       ├── __init__.py
│   │       └── manager.py     # XianyuLive 主循环
│   ├── prompts/
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   ├── src/
│   │   ├── api/
│   │   │   ├── auth.ts
│   │   │   ├── config.ts
│   │   │   └── logs.ts
│   │   ├── pages/
│   │   │   ├── auth/           # 登录页
│   │   │   ├── dashboard/      # 仪表盘
│   │   │   ├── settings/       # 配置管理
│   │   │   └── logs/           # 对话日志
│   │   ├── components/
│   │   ├── store/
│   │   │   └── authStore.ts
│   │   ├── utils/
│   │   │   └── request.ts     # Axios + JWT 拦截器
│   │   └── App.tsx
│   ├── Dockerfile
│   └── nginx.conf
│
├── docker-compose.yml
├── .env.example
└── README.md
```

## 数据库设计

### MySQL 表结构

```sql
CREATE TABLE conversations (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    chat_id         VARCHAR(64) UNIQUE NOT NULL,
    user_id         VARCHAR(64) NOT NULL,
    item_id         VARCHAR(64),
    manual_mode     BOOLEAN DEFAULT FALSE,
    manual_mode_at  DATETIME,
    bargain_count   INT DEFAULT 0,
    last_intent     VARCHAR(32),
    created_at      DATETIME DEFAULT NOW(),
    updated_at      DATETIME DEFAULT NOW() ON UPDATE NOW(),
    INDEX idx_user (user_id),
    INDEX idx_item (item_id)
);

CREATE TABLE messages (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    conversation_id BIGINT NOT NULL,
    role            ENUM('user', 'assistant') NOT NULL,
    content         TEXT NOT NULL,
    created_at      DATETIME DEFAULT NOW(),
    INDEX idx_conv_time (conversation_id, created_at),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE item_cache (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    item_id         VARCHAR(64) UNIQUE NOT NULL,
    title           VARCHAR(256),
    price           DECIMAL(10,2),
    description     TEXT,
    raw_json        JSON,
    fetched_at      DATETIME DEFAULT NOW(),
    expired_at      DATETIME
);

CREATE TABLE system_config (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    key_name        VARCHAR(128) UNIQUE NOT NULL,
    value           TEXT,
    updated_at      DATETIME DEFAULT NOW() ON UPDATE NOW()
);
```

### Redis 用途

- 会话上下文热缓存（最近 N 条消息）
- WebSocket 连接状态（供 backend-web 查询）
- JWT refresh token 存储（支持主动吊销）

## 认证鉴权

### JWT 双 Token 机制

- Access Token：15-30 分钟有效期，用于 API 请求鉴权
- Refresh Token：7 天有效期，存 Redis，支持服务端主动吊销
- Token Rotation：刷新时旧 refresh token 立即失效

### 密码存储

- bcrypt 哈希，不存明文
- 单管理员账号，首次启动时设置

### API 防护

- 所有路由（除 login/refresh）需 Bearer Token
- FastAPI `Depends(get_current_user)` 统一注入
- 服务间通信走 Docker 内网 + shared secret header

## 服务间通信

```
Browser → Nginx (port 80)
  ├── /api/* → backend-web:8089
  └── 静态文件 → frontend dist

backend-web → websocket:8090 (Docker 内网 HTTP)
  - 查询连接状态
  - 触发重连
  - 切换人工模式

websocket → wss://wss-goofish.dingtalk.com (闲鱼 IM)
```

- 前端不直接访问 websocket 服务
- 服务间仅 Docker 内网可达，不暴露到宿主机

## 前端页面

| 页面 | 路由 | 功能 |
|------|------|------|
| Login | /login | JWT 登录 |
| Dashboard | / | 连接状态、今日消息数、最近对话摘要 |
| Settings | /settings | 提示词编辑、环境变量配置、Cookie 更新/扫码登录 |
| Logs | /logs | 对话历史列表，按会话筛选，查看完整上下文 |

技术栈：React 18 + TypeScript + Vite + Tailwind CSS + Zustand + Axios + React Router 6

## Docker 部署

```yaml
# docker-compose.yml 概要
services:
  mysql:
    image: mysql:8.0
    volumes: [mysql_data]
    networks: [internal]

  redis:
    image: redis:7-alpine
    networks: [internal]

  backend-web:
    build: ./backend-web
    depends_on: [mysql, redis]
    env_file: .env
    networks: [internal]

  websocket:
    build: ./websocket
    depends_on: [mysql, redis]
    env_file: .env
    networks: [internal]

  frontend:
    build: ./frontend
    ports: ["80:80"]
    depends_on: [backend-web]
    networks: [internal]

networks:
  internal:

volumes:
  mysql_data:
```

只有 frontend (80) 对外暴露。

## 迁移映射

| 现有文件 | 迁移目标 |
|----------|----------|
| main.py (XianyuLive) | websocket/app/websocket/manager.py |
| XianyuAgent.py | websocket/app/services/agent/ (拆分为多文件) |
| context_manager.py | common/models/ + common/db/ (SQLAlchemy 重写) |
| XianyuApis.py | websocket/app/services/xianyu/ (异步化) |
| utils/xianyu_utils.py | common/utils/xianyu_utils.py |
| log_server.py | backend-web/app/api/routes/ (拆分) + frontend/ |
| prompts/ | websocket/prompts/ |

## 关键改造点

- 同步 `requests` → 异步 `aiohttp`（XianyuApis）
- 同步 `sqlite3` → 异步 SQLAlchemy + MySQL
- 同步 `OpenAI` SDK → 异步 `AsyncOpenAI`
- 内嵌 HTML → 独立 React 前端
- 内存 token set → JWT + Redis
