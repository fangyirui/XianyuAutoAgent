# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

XianyuAutoAgent 是一个闲鱼平台 AI 自动客服机器人。通过 WebSocket 长连接接入闲鱼消息系统，利用 LLM 多 Agent 协同实现 7×24 小时自动回复买家咨询。

## 运行方式

```bash
# 安装依赖
pip install -r requirements.txt

# 启动（需先配置 .env）
python main.py
```

Docker 部署：
```bash
docker-compose up -d
```

## 环境变量配置

复制 `.env.example` 为 `.env`，必填项：
- `API_KEY` — 模型平台 API Key（默认使用阿里百炼/通义千问）
- `COOKIES_STR` — 闲鱼网页端 Cookie（浏览器 F12 获取）
- `MODEL_BASE_URL` — OpenAI 兼容接口地址
- `MODEL_NAME` — 模型名称（默认 `qwen-max`）

## 架构

系统分四层：

**WebSocket 层**（`main.py` — `XianyuLive` 类）：与 `wss://wss-goofish.dingtalk.com/` 保持长连接。负责注册、心跳、Token 刷新、消息解密与分发。同时管理每个会话的人工接管模式（卖家发送关键词切换）。

**Agent 层**（`XianyuAgent.py`）：多 Agent 意图路由系统。
- `IntentRouter` — 三级路由：关键词匹配 → 正则匹配 → LLM 分类兜底
- `ClassifyAgent` — LLM 意图分类器（返回意图标签）
- `PriceAgent` — 议价处理，根据议价轮次动态调整 temperature
- `TechAgent` — 技术咨询，启用 DashScope 联网搜索
- `DefaultAgent` — 通用客服回复

所有 Agent 继承 `BaseAgent`，统一使用 OpenAI 兼容的 Chat Completions API。

**上下文层**（`context_manager.py` — `ChatContextManager`）：SQLite 持久化存储（`data/chat_history.db`）。按 `chat_id` 存储对话历史、商品信息缓存、议价次数统计。

**API 层**（`XianyuApis.py`）：闲鱼 H5 接口的 HTTP 客户端——Token 获取、登录刷新、商品详情拉取。处理 Cookie 轮换和签名生成。

**工具层**（`utils/xianyu_utils.py`）：消息 ID 生成、Cookie 解析、设备 ID 生成、API 签名（MD5）、MessagePack 解密（纯 Python 实现，无第三方依赖）。

## 提示词系统

提示词文件在 `prompts/` 目录。加载优先级：先找 `{name}.txt`，找不到则回退到 `{name}_example.txt`。自定义提示词被 gitignore，示例文件已提交。

- `classify_prompt.txt` — 意图分类
- `price_prompt.txt` — 议价策略
- `tech_prompt.txt` — 技术支持
- `default_prompt.txt` — 通用回复

## 关键设计决策

- 使用 OpenAI SDK 对接任意兼容接口，不绑定特定模型厂商
- WebSocket 消息体为 MessagePack 编码 + Base64 封装，通过自研纯 Python 解码器解密（无 msgpack 依赖）
- 对话上下文以 `chat_id` 为键（非 user_id），同一买家不同商品的咨询互相隔离
- 安全过滤器拦截包含站外联系方式关键词（微信、QQ、支付宝等）的回复
- Bot 返回 `"-"` 表示无需回复的哨兵值
- Token 刷新会触发 WebSocket 完整重连
