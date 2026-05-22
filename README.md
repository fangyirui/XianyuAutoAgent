# 🚀 Xianyu AutoAgent - 智能闲鱼客服机器人系统

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/) [![LLM Powered](https://img.shields.io/badge/LLM-powered-FF6F61)](https://platform.openai.com/)

专为闲鱼平台打造的AI值守解决方案，实现闲鱼平台7×24小时自动化值守，支持多专家协同决策、智能议价和上下文感知对话。 


## 🌟 核心特性

### 智能对话引擎
| 功能模块   | 技术实现            | 关键特性                                                     |
| ---------- | ------------------- | ------------------------------------------------------------ |
| 上下文感知 | 会话历史存储        | 轻量级对话记忆管理，完整对话历史作为LLM上下文输入            |
| 专家路由   | LLM prompt+规则路由 | 基于提示工程的意图识别 → 专家Agent动态分发，支持议价/技术/客服多场景切换 |

### 业务功能矩阵
| 模块     | 已实现                        | 规划中                       |
| -------- | ----------------------------- | ---------------------------- |
| 核心引擎 | ✅ LLM自动回复<br>✅ 上下文管理 | 🔄 情感分析增强               |
| 议价系统 | ✅ 阶梯降价策略                | 🔄 市场比价功能               |
| 技术支持 | ✅ 网络搜索整合                | 🔄 RAG知识库增强              |
| 运维监控 | ✅ 基础日志                    | 🔄 钉钉集成<br>🔄  Web管理界面 |

## 🎨效果图
<div align="center">
  <img src="./images/demo1.png" width="600" alt="客服">
  <br>
  <em>图1: 客服随叫随到</em>
</div>


<div align="center">
  <img src="./images/demo2.png" width="600" alt="议价专家">
  <br>
  <em>图2: 阶梯式议价</em>
</div>

<div align="center">
  <img src="./images/demo3.png" width="600" alt="技术专家"> 
  <br>
  <em>图3: 技术专家上场</em>
</div>

<div align="center">
  <img src="./images/log.png" width="600" alt="后台log"> 
  <br>
  <em>图4: 后台log</em>
</div>


## 🚴 快速开始
小白请直接查看[保姆级教学文档](https://my.feishu.cn/wiki/JtkBwkI9GiokZikVdyNceEfZncE)
### 环境要求
- Docker + Docker Compose

### 安装步骤
```bash
# 1. 克隆仓库
git clone https://github.com/shaxiu/XianyuAutoAgent.git
cd XianyuAutoAgent

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 API_KEY / MODEL_BASE_URL / MODEL_NAME / COOKIES_STR 等

# 3. 一键启动全部服务
docker compose up -d --build
```

启动后默认端口：
- `80` — 前端控制台（浏览器访问 `http://服务器IP/`）
- `8089` — 后端 API（backend-web）
- `8090` — WebSocket 服务
- `3306` / `6379` — MySQL / Redis（仅内网用，生产环境建议关闭对外端口）

查看日志：
```bash
docker compose logs -f websocket      # 闲鱼 WS 服务
docker compose logs -f backend-web    # 后台 API
docker compose logs -f frontend       # 前端
```

更详细的部署说明见 `部署.txt`。

### 自定义提示词

提示词存储在 MySQL `system_config` 表（key 形如 `prompt:classify_prompt`），可通过前端控制台在线编辑。

DB 中无对应记录时，回退读取 `websocket/prompts/` 目录下的同名 `.txt` 文件作为兜底（已提交 `*_prompt_example.txt` 作为模板，去掉 `_example` 后缀即可生效）：

- `classify_prompt.txt`: 意图分类提示词
- `price_prompt.txt`: 价格专家提示词
- `tech_prompt.txt`: 技术专家提示词
- `default_prompt.txt`: 默认回复提示词


## 🧸特别鸣谢
本项目参考了以下开源项目：
https://github.com/shaxiu/XianyuAutoAgent

## 🛡 注意事项

⚠️ 注意：**本项目仅供学习与交流，如有侵权联系作者删除。**



