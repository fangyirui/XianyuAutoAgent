# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

XianyuAutoAgent 是一个闲鱼平台 AI 自动客服机器人。通过 WebSocket 长连接接入闲鱼消息系统，利用 LLM 多 Agent 协同实现 7×24 小时自动回复买家咨询。系统采用 docker-compose 编排的微服务架构：MySQL 提供持久化，Redis 负责刷新令牌存储与跨服务配置热重载消息总线，websocket 服务负责闲鱼长连与对话生成，backend-web 提供管理 API，frontend 是 Vue 控制台。

## 运行方式

```bash
# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API_KEY / MODEL_BASE_URL / MODEL_NAME / COOKIES_STR

# 一键启动全部服务
docker compose up -d --build

# 查看日志
docker compose logs -f websocket
docker compose logs -f backend-web
```

端口：`80`（前端）/ `8089`（后端 API）/ `8090`（WebSocket 服务）/ `3306` MySQL / `6379` Redis。

本地开发某个服务时，可在对应子目录内直接 `python main.py`（需先把 `common/` 加入 `PYTHONPATH`，两个服务的入口已自动处理）。

## 环境变量配置

见 `.env.example`。关键必填项：
- `API_KEY` — 模型平台 API Key（默认使用阿里百炼/通义千问）
- `COOKIES_STR` — 闲鱼网页端 Cookie（首次启动用；之后可在前端登录由 `sellers` 表接管）
- `MODEL_BASE_URL` — OpenAI 兼容接口地址
- `MODEL_NAME` — 模型名称（默认 `qwen-max`）
- `MYSQL_*` / `REDIS_*` — 数据库连接（compose 内部默认值即可）
- `JWT_SECRET_KEY` — 后端 API 登录令牌签名密钥（生产环境务必改）

`common/core/config.py` 中 `DB_OVERRIDABLE_KEYS` 列出的字段（`API_KEY` / `MODEL_BASE_URL` / `MODEL_NAME` / `SKIP_KEYWORDS`）会在服务启动时被 `system_config` 表的同名记录覆盖，便于在前端控制台热改。

## 架构

四个运行时服务 + 一个共享库：

**`common/`** — 跨服务共享库（通过 docker-compose volume 挂载进 backend-web 和 websocket 容器的 `/app/common`）：
- `common/core/config.py` — `Settings` 单例，pydantic_settings 读取 `.env`，支持启动后从 DB 拉覆盖配置
- `common/db/session.py` — SQLAlchemy 异步引擎（`mysql+asyncmy`），提供 `AsyncSessionLocal` 与 `get_db` 依赖
- `common/db/redis_client.py` — Redis 异步客户端
- `common/models/` — ORM 模型：`Conversation` / `Message` / `ItemCache` / `SystemConfig` / `Seller`
- `common/schemas/` — Pydantic 入参/出参模型
- `common/utils/xianyu_utils.py` — 消息 ID 生成、Cookie 解析、设备 ID 生成、API 签名（MD5）、MessagePack 解密（纯 Python，无第三方依赖）

**`websocket/` 服务**（FastAPI，端口 8090）— 闲鱼长连接 + Agent 推理：
- `websocket/app/websocket/manager.py` — 与 `wss://wss-goofish.dingtalk.com/` 保持长连接：注册、心跳、Token 刷新、消息解密与分发；管理每个会话的人工接管模式（卖家发送 `TOGGLE_KEYWORDS` 切换）
- `websocket/app/services/xianyu/apis.py` — 闲鱼 H5 接口异步客户端（aiohttp），Token 获取/刷新、商品详情拉取
- `websocket/app/services/xianyu/token_manager.py` — Token 生命周期管理
- `websocket/app/services/agent/` — 多 Agent 意图路由：
  - `router.py` — `IntentRouter` 三级路由：关键词匹配 → 正则匹配 → LLM 分类兜底
  - `classify.py` — `ClassifyAgent` LLM 意图分类器
  - `price.py` — `PriceAgent` 议价处理，根据议价轮次动态调整 temperature
  - `tech.py` — `TechAgent` 技术咨询，启用 DashScope 联网搜索
  - `default.py` — `DefaultAgent` 通用客服回复
  - `base.py` — `BaseAgent` 统一封装 OpenAI 兼容 Chat Completions 调用；`resolve_top_p()` 处理 `MODEL_TOP_P` 可禁用语义
  - `bot.py` — `XianyuReplyBot` 聚合各 Agent，负责提示词从 DB / 文件双源加载
- `websocket/app/api/routes/` — 健康检查、控制接口、日志接口
- `websocket/app/core/log_buffer.py` — 内存环形日志缓冲（前端实时日志面板用）

**`backend-web/` 服务**（FastAPI，端口 8089）— 管理 API：
- `backend-web/app/api/routes/auth.py` — JWT 登录/续签
- `backend-web/app/api/routes/config.py` — 配置读写（写回 `system_config` 表）
- `backend-web/app/api/routes/items.py` — 商品缓存查询/自定义提示词
- `backend-web/app/api/routes/logs.py` / `logs_runtime.py` — 历史日志与实时日志（后者代理到 websocket 服务）
- `backend-web/app/api/routes/qrlogin.py` — 闲鱼扫码登录
- `backend-web/app/api/routes/websocket_proxy.py` — 透传到 websocket 服务的控制接口
- `backend-web/app/core/security.py` — JWT/密码哈希

**`frontend/`** — Vite + Vue + Tailwind 控制台，由 nginx 容器（`frontend/Dockerfile`）提供静态服务，端口 80。

**MySQL** — 表结构由 `init.sql` 在首次启动时初始化：
- `conversations` — 会话主键（含 `chat_id` / `manual_mode` / `bargain_count` / `last_intent`）
- `messages` — 对话历史（`role` / `content` / 外键回 `conversations.id`）
- `item_cache` — 商品信息缓存（含 `custom_prompt` 商品级提示词追加）
- `system_config` — 可在线编辑的系统配置与提示词
- `sellers` — 卖家 Cookie 池，支持多卖家

**Redis** — 三个用途：1）存储 JWT 刷新令牌（key `refresh_token:{token}`，带 TTL，续签时旧令牌即删）；2）跨服务配置热重载的发布/订阅通道（频道 `config:reload`）。backend-web 改配置后 publish 信号，websocket 服务的 `_redis_subscriber` 订阅消费：`cookie_updated`/`qrlogin` 触发完整重连，`env_updated`/`prompt_updated` 触发软重载（保持长连接）；3）买家消息可靠投递队列（Redis Stream `stream:messages` + 消费组 `cg:messages`，见 `websocket/app/websocket/message_queue.py`）——消息经 `handle_message` 全部门控后入队，由 websocket 进程内的 consumer 消费（取详情→AI生成→发送，成功才 XACK，失败留 PEL 自动重投），彻底解决 AI/发送报错导致买家消息无人回复。为此 Redis 开启了 AOF 持久化（compose 中 `--appendonly yes`，挂 `redis_data` 卷），重启不丢未消费消息。会话与商品缓存仍在 MySQL，实时日志走内存环形缓冲 `log_buffer`。

## 提示词系统

提示词存储在 MySQL `system_config` 表，key 命名规则 `prompt:classify_prompt` / `prompt:price_prompt` / `prompt:tech_prompt` / `prompt:default_prompt`。加载顺序（见 `websocket/app/services/agent/bot.py:73` `load_prompts_from_db`）：

1. 启动时从 DB 读取四条 prompt 记录
2. 若 DB 中某条缺失或为空，从 `websocket/prompts/` 目录下的同名 `.txt` 文件加载并回写 DB
3. 文件命名优先级：`{name}.txt` 找不到则回退到 `{name}_example.txt`

自定义提示词被 gitignore（`*_prompt.txt`），仓库只提交 `*_prompt_example.txt` 与 `prompt.json` 模板。前端控制台可在线编辑。

## 关键设计决策

- 使用 OpenAI SDK 对接任意兼容接口，不绑定特定模型厂商
- WebSocket 消息体为 MessagePack 编码 + Base64 封装，通过自研纯 Python 解码器解密（无 msgpack 依赖）
- 对话上下文以 `chat_id` 为键（非 user_id），同一买家不同商品的咨询互相隔离
- 安全过滤器拦截包含站外联系方式关键词（微信、QQ、支付宝等）的回复
- Bot 返回 `"-"` 表示无需回复的哨兵值
- Token 刷新会触发 WebSocket 完整重连
- 商品级 `custom_prompt` 仅在非空时追加到 system prompt（`base.py:_build_messages` 中"严格门控"），保证空值时主流程与默认行为字节一致
- `MODEL_TOP_P` 字符串型配置，允许设为空串 / `none` / `null` 关闭 `top_p`（部分网关不允许同时传 `temperature` 与 `top_p`）
- 配置热改：`API_KEY` / `MODEL_BASE_URL` / `MODEL_NAME` / `SKIP_KEYWORDS` 启动时从 DB 拉取覆盖，Cookie 从 `sellers` 表的首个 `is_active` 记录读取
