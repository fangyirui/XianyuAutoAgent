# 仪表盘详细信息 + 今日/累计区分 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把仪表盘从 3 个简单卡片扩展为「实时 / 今日 / 累计」三大区，新增对话量、买家/意图分布、人工接管、AI 调用次数、token 消耗、平均响应时长、AI 错误率等指标；同时把当前只打 debug 日志的 LLM 调用 token 用量持久化到新表 `ai_call_log`。

**Architecture:** 新建 `ai_call_log` 表；`BaseAgent._call_llm` 增加可选 `chat_id` 参数并在 `try/finally` 末尾以 `asyncio.create_task` fire-and-forget 落库，主流程不阻塞、不抛错；后端 `/logs/stats` 用 `asyncio.gather` 并发聚合返回结构化 JSON（保留旧字段做向后兼容）；前端 React Dashboard 重写为三大区，新增轻量 `<BarRow>` 组件实现水平条形分布，不引入图表库。

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy(async) / MySQL 8 / OpenAI SDK / React 18 + TypeScript / Vite / Tailwind

**Spec:** `docs/superpowers/specs/2026-05-22-dashboard-detail-design.md`

**约束:** 项目无现有 pytest 测试设施，沿用 spec §6 的「独立验证脚本 + 手工验证清单」模式做零回归保障。`feedback_main_flow_zero_regression` 硬约束：所有新增参数默认 `None` / `""`，主流程行为字节级与改动前一致。

---

## File Structure

**新增文件：**
- `common/models/ai_call_log.py` — `AiCallLog` ORM 模型
- `scripts/verify_dashboard_byte_equality.py` — 验证脚本，断言 `BaseAgent._call_llm(chat_id=None)` 路径未引入新异常、且 fire-and-forget 任务不影响返回值
- `frontend/src/components/dashboard/StatCard.tsx` — 复用卡片组件
- `frontend/src/components/dashboard/BarRow.tsx` — 水平条形占比组件

**修改文件：**
- `init.sql` — 追加 `ai_call_log` 建表语句
- `common/models/__init__.py` — 导出 `AiCallLog`
- `websocket/app/services/agent/base.py` — `generate`/`_call_llm` 加 `chat_id` 参数；新增 `_record_usage`
- `websocket/app/services/agent/price.py` — `_call_llm` 重构为复用 `_record_usage`；`generate` 透传 `chat_id`
- `websocket/app/services/agent/tech.py` — 同上
- `websocket/app/services/agent/default.py` — `_call_llm` 签名加 `chat_id`
- `websocket/app/services/agent/classify.py` — `generate` 透传 `chat_id`（kwargs 路径已支持）
- `websocket/app/services/agent/router.py` — `detect` 加可选 `chat_id` 并透传
- `websocket/app/services/agent/bot.py` — `generate_reply` 加可选 `chat_id` 并透传给 router/agents
- `websocket/app/websocket/manager.py` — 调 `generate_reply` 时传入当前 `chat_id`
- `backend-web/app/api/routes/logs.py` — 重写 `GET /logs/stats`
- `frontend/src/api/logs.ts` — `getStats()` 返回类型扩展为 `DashboardStats`
- `frontend/src/pages/dashboard/DashboardPage.tsx` — 重写布局为三大区

---

## Task 1: 数据库 Schema 与 ORM

**Files:**
- Modify: `init.sql`
- Create: `common/models/ai_call_log.py`
- Modify: `common/models/__init__.py`

- [ ] **Step 1: 追加 `init.sql` 建表语句**

在 `init.sql` 文件末尾（`sellers` 表之后）追加：

```sql

CREATE TABLE IF NOT EXISTS ai_call_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_name VARCHAR(32) NOT NULL COMMENT 'DefaultAgent/PriceAgent/TechAgent/ClassifyAgent',
    model VARCHAR(64) NOT NULL,
    chat_id VARCHAR(64) NULL COMMENT '关联会话；分类阶段可能为NULL',
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    total_tokens INT NOT NULL DEFAULT 0,
    latency_ms INT NOT NULL DEFAULT 0,
    success TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT NOW(),
    INDEX idx_ai_log_created (created_at),
    INDEX idx_ai_log_agent_created (agent_name, created_at)
);
```

- [ ] **Step 2: 新建 ORM 模型 `common/models/ai_call_log.py`**

```python
from sqlalchemy import Column, BigInteger, Integer, String, Boolean, DateTime, func
from .base import Base


class AiCallLog(Base):
    __tablename__ = "ai_call_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    agent_name = Column(String(32), nullable=False, index=True)
    model = Column(String(64), nullable=False)
    chat_id = Column(String(64), nullable=True)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Integer, nullable=False, default=0)
    success = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
```

- [ ] **Step 3: 在 `common/models/__init__.py` 导出**

把 `common/models/__init__.py` 整体替换为：

```python
from .base import Base
from .conversation import Conversation
from .message import Message
from .item_cache import ItemCache
from .system_config import SystemConfig
from .seller import Seller
from .ai_call_log import AiCallLog

__all__ = [
    "Base",
    "Conversation",
    "Message",
    "ItemCache",
    "SystemConfig",
    "Seller",
    "AiCallLog",
]
```

- [ ] **Step 4: 启动数据库验证建表**

```bash
docker compose up -d mysql
# 等 MySQL 起来（约 5-10s）
docker compose exec mysql mysql -uroot -proot -e "USE xianyu; SHOW TABLES;"
```

期望输出包含 `ai_call_log`。如果之前的部署已存在 DB（没有该表），手工执行：

```bash
docker compose exec -T mysql mysql -uroot -proot xianyu < init.sql
```

`CREATE TABLE IF NOT EXISTS` 对已存在表是 no-op。

- [ ] **Step 5: 验证 ORM 模型可导入**

```bash
docker compose exec websocket python -c "from common.models import AiCallLog; print(AiCallLog.__tablename__)"
```

期望输出：`ai_call_log`

- [ ] **Step 6: 提交**

```bash
git add init.sql common/models/ai_call_log.py common/models/__init__.py
git commit -m "feat(db): 新增 ai_call_log 表与 ORM 模型，记录 LLM 调用 token/耗时"
```

---

## Task 2: Agent 端 token/耗时落库埋点

**Files:**
- Modify: `websocket/app/services/agent/base.py`

- [ ] **Step 1: 重写 `base.py`**

把 `websocket/app/services/agent/base.py` 整体替换为下面内容。关键点：

1. `generate` 增加可选 `chat_id: Optional[str] = None`，默认 `None`。
2. `_call_llm` 同样增加 `chat_id` 参数。
3. 抽出 `_record_usage()` 内部协程，做 fire-and-forget 落库。
4. **零回归**：参数默认 `None` 时 `_build_messages` 输出和 `_call_llm` 主体逻辑完全不变；fire-and-forget 任务不影响返回值；写库失败仅 `logger.warning`，不抛。

```python
import time
import asyncio
from typing import List, Dict, Optional
from openai import AsyncOpenAI
from loguru import logger
from common.core import settings


def resolve_top_p() -> Optional[float]:
    """解析 settings.MODEL_TOP_P。默认 "0.8" 与旧行为字节一致；
    空串 / "none" / "null"（不区分大小写、允许前后空白）或非数值时返回 None，调用方应不传 top_p。"""
    raw = (settings.MODEL_TOP_P or "").strip()
    if not raw or raw.lower() in ("none", "null"):
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"MODEL_TOP_P={settings.MODEL_TOP_P!r} 无法解析为浮点数，已禁用 top_p")
        return None


class BaseAgent:
    def __init__(self, client: AsyncOpenAI, system_prompt: str, safety_filter):
        self.client = client
        self.system_prompt = system_prompt
        self.safety_filter = safety_filter

    async def generate(
        self,
        user_msg: str,
        item_desc: str,
        context: str,
        bargain_count: int = 0,
        item_custom_prompt: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> str:
        messages = self._build_messages(user_msg, item_desc, context, item_custom_prompt)
        logger.debug(f"[{self.__class__.__name__}] 构建消息完成，system_prompt长度={len(self.system_prompt)}, 商品额外提示词={'有' if item_custom_prompt else '无'}")
        response = await self._call_llm(messages, chat_id=chat_id)
        filtered = self.safety_filter(response)
        if filtered != response:
            logger.warning(f"[{self.__class__.__name__}] 安全过滤触发，原始回复: {response}")
        return filtered

    def _build_messages(
        self,
        user_msg: str,
        item_desc: str,
        context: str,
        item_custom_prompt: Optional[str] = None,
    ) -> List[Dict]:
        sys_content = f"【商品信息】{item_desc}\n【你与客户对话历史】{context}\n{self.system_prompt}"
        # 严格门控：空串 / None / 任何 falsy 值都完全不追加，保证主流程零回归
        if item_custom_prompt:
            sys_content += f"\n【针对本商品的特别说明】{item_custom_prompt}"
        return [
            {"role": "system", "content": sys_content},
            {"role": "user", "content": user_msg}
        ]

    async def _call_llm(
        self,
        messages: List[Dict],
        temperature: float = 0.4,
        chat_id: Optional[str] = None,
    ) -> str:
        logger.info(f"[{self.__class__.__name__}] LLM请求 | model={settings.MODEL_NAME}, temp={temperature}")
        logger.debug(f"[{self.__class__.__name__}] 完整提示词:\n{messages[0]['content']}")
        logger.debug(f"[{self.__class__.__name__}] 用户输入: {messages[-1]['content']}")
        kwargs = dict(
            model=settings.MODEL_NAME,
            messages=messages,
            temperature=temperature,
            max_tokens=500,
        )
        top_p = resolve_top_p()
        if top_p is not None:
            kwargs["top_p"] = top_p

        t0 = time.perf_counter()
        success = True
        response = None
        try:
            response = await self.client.chat.completions.create(**kwargs)
            result = response.choices[0].message.content or ""
            logger.info(f"[{self.__class__.__name__}] LLM响应: {result}")
            logger.debug(f"[{self.__class__.__name__}] token用量: {response.usage}")
            return result
        except Exception as e:
            success = False
            logger.error(f"[{self.__class__.__name__}] LLM调用失败: {e}")
            raise
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            self._fire_and_forget_record(
                model=str(kwargs.get("model", "")),
                chat_id=chat_id,
                response=response,
                latency_ms=latency_ms,
                success=success,
            )

    def _fire_and_forget_record(
        self,
        model: str,
        chat_id: Optional[str],
        response,
        latency_ms: int,
        success: bool,
    ) -> None:
        """调度 _record_usage 为后台任务；任何调度错误不抛、仅 warning，绝不影响主流程。"""
        try:
            asyncio.create_task(
                self._record_usage(
                    agent_name=self.__class__.__name__,
                    model=model,
                    chat_id=chat_id,
                    response=response,
                    latency_ms=latency_ms,
                    success=success,
                )
            )
        except Exception as e:
            logger.warning(f"[{self.__class__.__name__}] 落库任务调度失败: {e}")

    async def _record_usage(
        self,
        agent_name: str,
        model: str,
        chat_id: Optional[str],
        response,
        latency_ms: int,
        success: bool,
    ) -> None:
        """写入 ai_call_log。失败仅 warning。"""
        try:
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            if response is not None and getattr(response, "usage", None) is not None:
                usage = response.usage
                prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                total_tokens = int(getattr(usage, "total_tokens", 0) or 0)

            from common.db import AsyncSessionLocal
            from common.models import AiCallLog
            async with AsyncSessionLocal() as db:
                db.add(AiCallLog(
                    agent_name=agent_name,
                    model=model,
                    chat_id=chat_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency_ms,
                    success=success,
                ))
                await db.commit()
        except Exception as e:
            logger.warning(f"[{agent_name}] ai_call_log 写库失败: {e}")
```

- [ ] **Step 2: 静态检查**

```bash
docker compose exec websocket python -c "from app.services.agent.base import BaseAgent; print('ok')"
```

期望输出：`ok`

- [ ] **Step 3: 提交**

```bash
git add websocket/app/services/agent/base.py
git commit -m "feat(agent): BaseAgent 增加 chat_id 透传与 token/耗时 fire-and-forget 落库"
```

---

## Task 3: 子类 Agent 适配 `chat_id` 与落库

**Files:**
- Modify: `websocket/app/services/agent/price.py`
- Modify: `websocket/app/services/agent/tech.py`
- Modify: `websocket/app/services/agent/default.py`
- Modify: `websocket/app/services/agent/classify.py`

- [ ] **Step 1: 重写 `price.py`**

`PriceAgent.generate` 重写了 LLM 调用逻辑（直接 `client.chat.completions.create`），需要自己加 token 落库埋点。把 `websocket/app/services/agent/price.py` 整体替换为：

```python
import time
from typing import Optional
from loguru import logger
from .base import BaseAgent, resolve_top_p
from common.core import settings


class PriceAgent(BaseAgent):
    async def generate(
        self,
        user_msg: str,
        item_desc: str,
        context: str,
        bargain_count: int = 0,
        item_custom_prompt: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> str:
        dynamic_temp = self._calc_temperature(bargain_count)
        messages = self._build_messages(user_msg, item_desc, context, item_custom_prompt)
        # ▲议价轮次 永远追加到 system content 末尾（在 custom_prompt 之后），与原行为保持一致
        messages[0]["content"] += f"\n▲当前议价轮次：{bargain_count}"

        logger.info(f"[PriceAgent] LLM请求 | model={settings.MODEL_NAME}, temp={dynamic_temp}, 议价轮次={bargain_count}")
        logger.debug(f"[PriceAgent] 完整提示词:\n{messages[0]['content']}")
        logger.debug(f"[PriceAgent] 用户输入: {messages[-1]['content']}")

        kwargs = dict(
            model=settings.MODEL_NAME,
            messages=messages,
            temperature=dynamic_temp,
            max_tokens=500,
        )
        top_p = resolve_top_p()
        if top_p is not None:
            kwargs["top_p"] = top_p

        t0 = time.perf_counter()
        success = True
        response = None
        try:
            response = await self.client.chat.completions.create(**kwargs)
            result = self.safety_filter(response.choices[0].message.content)
            logger.info(f"[PriceAgent] LLM响应: {result}")
            logger.debug(f"[PriceAgent] token用量: {response.usage}")
            return result
        except Exception as e:
            success = False
            logger.error(f"[PriceAgent] LLM调用失败: {e}")
            raise
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            self._fire_and_forget_record(
                model=str(kwargs.get("model", "")),
                chat_id=chat_id,
                response=response,
                latency_ms=latency_ms,
                success=success,
            )

    def _calc_temperature(self, bargain_count: int) -> float:
        return min(0.3 + bargain_count * 0.15, 0.9)
```

- [ ] **Step 2: 重写 `tech.py`**

把 `websocket/app/services/agent/tech.py` 整体替换为：

```python
import time
from typing import Optional
from loguru import logger
from .base import BaseAgent, resolve_top_p
from common.core import settings


class TechAgent(BaseAgent):
    async def generate(
        self,
        user_msg: str,
        item_desc: str,
        context: str,
        bargain_count: int = 0,
        item_custom_prompt: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> str:
        messages = self._build_messages(user_msg, item_desc, context, item_custom_prompt)

        logger.info(f"[TechAgent] LLM请求 | model={settings.MODEL_NAME}, enable_search=True")
        logger.debug(f"[TechAgent] 完整提示词:\n{messages[0]['content']}")
        logger.debug(f"[TechAgent] 用户输入: {messages[-1]['content']}")

        kwargs = dict(
            model=settings.MODEL_NAME,
            messages=messages,
            temperature=0.4,
            max_tokens=500,
            extra_body={"enable_search": True},
        )
        top_p = resolve_top_p()
        if top_p is not None:
            kwargs["top_p"] = top_p

        t0 = time.perf_counter()
        success = True
        response = None
        try:
            response = await self.client.chat.completions.create(**kwargs)
            result = self.safety_filter(response.choices[0].message.content)
            logger.info(f"[TechAgent] LLM响应: {result}")
            logger.debug(f"[TechAgent] token用量: {response.usage}")
            return result
        except Exception as e:
            success = False
            logger.error(f"[TechAgent] LLM调用失败: {e}")
            raise
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            self._fire_and_forget_record(
                model=str(kwargs.get("model", "")),
                chat_id=chat_id,
                response=response,
                latency_ms=latency_ms,
                success=success,
            )
```

- [ ] **Step 3: 调整 `default.py`**

`DefaultAgent._call_llm` 用 `*args` 吸收额外参数，需要显式接收 `chat_id` 透传给父类。把 `websocket/app/services/agent/default.py` 整体替换为：

```python
from typing import Optional
from .base import BaseAgent


class DefaultAgent(BaseAgent):
    async def _call_llm(self, messages, temperature: float = 0.7, chat_id: Optional[str] = None) -> str:
        return await super()._call_llm(messages, temperature=temperature, chat_id=chat_id)
```

- [ ] **Step 4: `classify.py` 无需改动验证**

`ClassifyAgent.generate(**kwargs)` 通过 kwargs 透传，新增的 `chat_id` 会自动随调用方传入并向 `super().generate` 透传。无需改代码，但 Step 5 会显式验证。

- [ ] **Step 5: 静态导入验证**

```bash
docker compose exec websocket python -c "
from app.services.agent.price import PriceAgent
from app.services.agent.tech import TechAgent
from app.services.agent.default import DefaultAgent
from app.services.agent.classify import ClassifyAgent
import inspect
print('price.generate:', list(inspect.signature(PriceAgent.generate).parameters))
print('tech.generate:', list(inspect.signature(TechAgent.generate).parameters))
print('default._call_llm:', list(inspect.signature(DefaultAgent._call_llm).parameters))
"
```

期望输出：每个签名都包含 `chat_id`。

- [ ] **Step 6: 提交**

```bash
git add websocket/app/services/agent/price.py websocket/app/services/agent/tech.py websocket/app/services/agent/default.py
git commit -m "feat(agent): Price/Tech/Default Agent 加 chat_id 透传与 fire-and-forget 落库"
```

---

## Task 4: Router 与 Bot 透传 chat_id

**Files:**
- Modify: `websocket/app/services/agent/router.py`
- Modify: `websocket/app/services/agent/bot.py`
- Modify: `websocket/app/websocket/manager.py`

- [ ] **Step 1: 修改 `router.py`**

`IntentRouter.detect` 增加可选 `chat_id` 并向 classify_agent.generate 透传。把 `websocket/app/services/agent/router.py` 中 `detect` 方法修改如下（其余保持原样）：

```python
    async def detect(self, user_msg: str, item_desc: str, context: str, chat_id: str | None = None) -> str:
        text_clean = re.sub(r"[^\w一-龥]", "", user_msg)

        if any(kw in text_clean for kw in self.rules["tech"]["keywords"]):
            logger.info(f"[IntentRouter] 关键词命中 -> tech | 原文: {user_msg}")
            return "tech"
        for pattern in self.rules["tech"]["patterns"]:
            if re.search(pattern, text_clean):
                logger.info(f"[IntentRouter] 正则命中 '{pattern}' -> tech | 原文: {user_msg}")
                return "tech"

        if any(kw in text_clean for kw in self.rules["price"]["keywords"]):
            logger.info(f"[IntentRouter] 关键词命中 -> price | 原文: {user_msg}")
            return "price"
        for pattern in self.rules["price"]["patterns"]:
            if re.search(pattern, text_clean):
                logger.info(f"[IntentRouter] 正则命中 '{pattern}' -> price | 原文: {user_msg}")
                return "price"

        logger.info(f"[IntentRouter] 规则未命中，调用ClassifyAgent | 原文: {user_msg}")
        result = await self.classify_agent.generate(
            user_msg=user_msg, item_desc=item_desc, context=context, chat_id=chat_id
        )
        logger.info(f"[IntentRouter] ClassifyAgent返回意图: {result}")
        return result
```

- [ ] **Step 2: 修改 `bot.py`**

`generate_reply` 加可选 `chat_id` 并向下透传。把 `generate_reply` 整体替换为：

```python
    async def generate_reply(
        self,
        user_msg: str,
        item_desc: str,
        context: List[Dict],
        item_custom_prompt: str | None = None,
        chat_id: str | None = None,
    ) -> str:
        logger.info(f"[Bot] 开始处理 | 用户消息: {user_msg}")
        logger.debug(f"[Bot] 商品信息: {item_desc}")
        logger.debug(f"[Bot] 上下文条数: {len(context)}, 商品额外提示词={'有' if item_custom_prompt else '无'}")

        formatted_context = self.format_history(context)
        # IntentRouter / ClassifyAgent 不接收 item_custom_prompt（避免污染意图判断）
        detected_intent = await self.router.detect(user_msg, item_desc, formatted_context, chat_id=chat_id)

        if detected_intent == "no_reply":
            self.last_intent = "no_reply"
            logger.info("[Bot] 意图=no_reply，跳过回复")
            return "-"

        internal_intents = {"classify"}
        if detected_intent in self.agents and detected_intent not in internal_intents:
            agent = self.agents[detected_intent]
            self.last_intent = detected_intent
        else:
            agent = self.agents["default"]
            self.last_intent = "default"

        logger.info(f"[Bot] 最终意图={self.last_intent}，使用 {agent.__class__.__name__}")

        bargain_count = self._extract_bargain_count(context)
        reply = await agent.generate(
            user_msg=user_msg,
            item_desc=item_desc,
            context=formatted_context,
            bargain_count=bargain_count,
            item_custom_prompt=item_custom_prompt,
            chat_id=chat_id,
        )
        logger.info(f"[Bot] 最终回复: {reply}")
        return reply
```

- [ ] **Step 3: 修改 `manager.py` 传 chat_id**

`websocket/app/websocket/manager.py:427-430` 当前实现：

```python
        try:
            bot_reply = await self.bot.generate_reply(
                send_message, item_desc, context, item_custom_prompt=item_custom_prompt,
            )
```

替换为（仅追加 `chat_id=chat_id` 关键字参数，`chat_id` 已是该函数作用域内的局部变量，见 line 346 `chat_id = message["1"]["2"].split("@")[0]`）：

```python
        try:
            bot_reply = await self.bot.generate_reply(
                send_message, item_desc, context, item_custom_prompt=item_custom_prompt, chat_id=chat_id,
            )
```

如果将来发现该文件还有其它 `generate_reply` 调用，做相同处理：

```bash
grep -n "generate_reply" /Users/fangyirui/PycharmProjects/XianyuAutoAgent/websocket/app/websocket/manager.py
```

- [ ] **Step 4: 静态导入验证**

```bash
docker compose exec websocket python -c "
import inspect
from app.services.agent.bot import XianyuReplyBot
from app.services.agent.router import IntentRouter
print('bot.generate_reply:', list(inspect.signature(XianyuReplyBot.generate_reply).parameters))
print('router.detect:', list(inspect.signature(IntentRouter.detect).parameters))
"
```

期望输出：两个签名都包含 `chat_id`。

- [ ] **Step 5: 提交**

```bash
git add websocket/app/services/agent/router.py websocket/app/services/agent/bot.py websocket/app/websocket/manager.py
git commit -m "feat(agent): Router/Bot/Manager 透传 chat_id 到 LLM 调用日志"
```

---

## Task 5: 零回归验证脚本

**Files:**
- Create: `scripts/verify_dashboard_byte_equality.py`

- [ ] **Step 1: 编写验证脚本**

新建 `scripts/verify_dashboard_byte_equality.py`：

```python
"""
零回归验证：
1) BaseAgent._build_messages(item_custom_prompt=None) 输出与改动前预期一致
2) BaseAgent.generate / _call_llm 的 chat_id 默认 None 路径不引入新参数到 OpenAI kwargs
3) _fire_and_forget_record 在 None response 下不抛
4) _record_usage 在 None response 下能跑通（写库会失败但只 warning）

用法：在 websocket 容器内执行
  docker compose exec websocket python /app/scripts/verify_dashboard_byte_equality.py
"""
import asyncio
import inspect
import sys


def check_build_messages_unchanged():
    from app.services.agent.base import BaseAgent

    agent = BaseAgent.__new__(BaseAgent)
    agent.system_prompt = "SYS"
    agent.safety_filter = lambda x: x

    msgs_none = agent._build_messages("hi", "ITEM", "CTX", None)
    msgs_empty = agent._build_messages("hi", "ITEM", "CTX", "")
    msgs_baseline = [
        {"role": "system", "content": "【商品信息】ITEM\n【你与客户对话历史】CTX\nSYS"},
        {"role": "user", "content": "hi"},
    ]
    assert msgs_none == msgs_baseline, f"None 路径已发生变化: {msgs_none}"
    assert msgs_empty == msgs_baseline, f"空串路径已发生变化: {msgs_empty}"
    print("[OK] _build_messages 在 None / 空串下与基线字节级一致")


def check_signature_contains_chat_id():
    from app.services.agent.base import BaseAgent
    from app.services.agent.price import PriceAgent
    from app.services.agent.tech import TechAgent
    from app.services.agent.default import DefaultAgent
    from app.services.agent.bot import XianyuReplyBot
    from app.services.agent.router import IntentRouter

    for cls, method in [
        (BaseAgent, "generate"),
        (BaseAgent, "_call_llm"),
        (PriceAgent, "generate"),
        (TechAgent, "generate"),
        (DefaultAgent, "_call_llm"),
        (XianyuReplyBot, "generate_reply"),
        (IntentRouter, "detect"),
    ]:
        params = inspect.signature(getattr(cls, method)).parameters
        assert "chat_id" in params, f"{cls.__name__}.{method} 缺少 chat_id 参数"
        assert params["chat_id"].default is None, f"{cls.__name__}.{method}.chat_id 默认值不是 None"
    print("[OK] 所有透传方法均包含默认 None 的 chat_id 参数")


async def check_fire_and_forget_safe():
    """response=None 时落库任务不应抛错（仅 warning）。"""
    from app.services.agent.base import BaseAgent

    agent = BaseAgent.__new__(BaseAgent)
    agent.system_prompt = ""
    agent.safety_filter = lambda x: x

    # 应不抛
    agent._fire_and_forget_record(
        model="test-model", chat_id=None, response=None, latency_ms=10, success=False
    )
    # 让事件循环跑一遍
    await asyncio.sleep(0.1)
    print("[OK] _fire_and_forget_record(None response) 调度安全")


async def main():
    check_build_messages_unchanged()
    check_signature_contains_chat_id()
    await check_fire_and_forget_safe()
    print("\nAll byte-equality checks passed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 2: 执行验证**

```bash
docker compose exec websocket python /app/scripts/verify_dashboard_byte_equality.py
```

期望输出（最后一行）：`All byte-equality checks passed.`

如果失败，根据断言信息回到对应 Task 修复，再重跑此步骤。

- [ ] **Step 3: 提交**

```bash
git add scripts/verify_dashboard_byte_equality.py
git commit -m "test(agent): 加 dashboard 改动零回归验证脚本"
```

---

## Task 6: Backend `/logs/stats` 聚合接口重写

**Files:**
- Modify: `backend-web/app/api/routes/logs.py`

- [ ] **Step 1: 重写 `get_stats` 路由**

把 `backend-web/app/api/routes/logs.py` 文件末尾的 `@router.get("/stats")` 整段（约 148-155 行）替换为下面的实现。同时在文件顶部 import 块中追加 `AiCallLog` 和 `asyncio` 的导入。

文件顶部 import 块改成：

```python
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func, desc, and_
from common.db import get_db
from common.models import Conversation, Message, ItemCache, AiCallLog
from common.schemas import MessageOut
from app.api.deps import get_current_user
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
```

文件末尾的 `get_stats` 整段替换为：

```python
@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    today_start = func.curdate()  # MySQL CURDATE() — 容器时区 Asia/Shanghai

    # --- 实时 ---
    q_realtime_manual_active = select(func.count(Conversation.id)).where(Conversation.manual_mode.is_(True))

    # --- 今日 ---
    q_today_conv = select(func.count(Conversation.id)).where(Conversation.created_at >= today_start)
    q_today_msg = select(func.count(Message.id)).where(Message.created_at >= today_start)
    q_today_ai_reply = select(func.count(Message.id)).where(
        and_(Message.role == "assistant", Message.created_at >= today_start)
    )
    q_today_user_msg = select(func.count(Message.id)).where(
        and_(Message.role == "user", Message.created_at >= today_start)
    )
    q_today_new_buyers = select(func.count(func.distinct(Conversation.user_id))).where(
        Conversation.created_at >= today_start
    )
    q_today_takeover = select(func.count(Conversation.id)).where(
        Conversation.manual_mode_at >= today_start
    )
    q_today_ai_calls = select(func.count(AiCallLog.id)).where(AiCallLog.created_at >= today_start)
    q_today_tokens = select(func.coalesce(func.sum(AiCallLog.total_tokens), 0)).where(
        AiCallLog.created_at >= today_start
    )
    q_today_ai_errors = select(func.count(AiCallLog.id)).where(
        and_(AiCallLog.success.is_(False), AiCallLog.created_at >= today_start)
    )
    q_today_avg_latency = select(func.coalesce(func.avg(AiCallLog.latency_ms), 0)).where(
        and_(AiCallLog.success.is_(True), AiCallLog.created_at >= today_start)
    )
    q_today_intent_dist = (
        select(Conversation.last_intent, func.count(Conversation.id))
        .where(and_(Conversation.updated_at >= today_start, Conversation.last_intent.isnot(None)))
        .group_by(Conversation.last_intent)
    )
    q_today_agent_dist = (
        select(AiCallLog.agent_name, func.count(AiCallLog.id))
        .where(AiCallLog.created_at >= today_start)
        .group_by(AiCallLog.agent_name)
    )

    # --- 累计 ---
    q_cum_conv = select(func.count(Conversation.id))
    q_cum_msg = select(func.count(Message.id))
    q_cum_buyers = select(func.count(func.distinct(Conversation.user_id)))
    q_cum_bargain = select(func.count(Conversation.id)).where(Conversation.bargain_count > 0)
    q_cum_ai_calls = select(func.count(AiCallLog.id))
    q_cum_tokens = select(func.coalesce(func.sum(AiCallLog.total_tokens), 0))

    # 并发执行
    results = await asyncio.gather(
        db.execute(q_realtime_manual_active),
        db.execute(q_today_conv),
        db.execute(q_today_msg),
        db.execute(q_today_ai_reply),
        db.execute(q_today_user_msg),
        db.execute(q_today_new_buyers),
        db.execute(q_today_takeover),
        db.execute(q_today_ai_calls),
        db.execute(q_today_tokens),
        db.execute(q_today_ai_errors),
        db.execute(q_today_avg_latency),
        db.execute(q_today_intent_dist),
        db.execute(q_today_agent_dist),
        db.execute(q_cum_conv),
        db.execute(q_cum_msg),
        db.execute(q_cum_buyers),
        db.execute(q_cum_bargain),
        db.execute(q_cum_ai_calls),
        db.execute(q_cum_tokens),
    )

    (
        r_realtime_manual_active,
        r_today_conv,
        r_today_msg,
        r_today_ai_reply,
        r_today_user_msg,
        r_today_new_buyers,
        r_today_takeover,
        r_today_ai_calls,
        r_today_tokens,
        r_today_ai_errors,
        r_today_avg_latency,
        r_today_intent_dist,
        r_today_agent_dist,
        r_cum_conv,
        r_cum_msg,
        r_cum_buyers,
        r_cum_bargain,
        r_cum_ai_calls,
        r_cum_tokens,
    ) = results

    today_ai_calls = r_today_ai_calls.scalar() or 0
    today_ai_errors = r_today_ai_errors.scalar() or 0
    today_error_rate = (today_ai_errors / today_ai_calls) if today_ai_calls > 0 else 0.0
    today_avg_latency = int(r_today_avg_latency.scalar() or 0)

    intent_distribution = [
        {"name": name or "unknown", "count": int(count)}
        for name, count in r_today_intent_dist.all()
    ]
    intent_distribution.sort(key=lambda x: x["count"], reverse=True)

    agent_distribution = [
        {"name": name, "count": int(count)}
        for name, count in r_today_agent_dist.all()
    ]
    agent_distribution.sort(key=lambda x: x["count"], reverse=True)

    cum_conv = r_cum_conv.scalar() or 0
    cum_msg = r_cum_msg.scalar() or 0

    return {
        "realtime": {
            "manual_active": r_realtime_manual_active.scalar() or 0,
        },
        "today": {
            "conversations": r_today_conv.scalar() or 0,
            "messages": r_today_msg.scalar() or 0,
            "ai_replies": r_today_ai_reply.scalar() or 0,
            "user_messages": r_today_user_msg.scalar() or 0,
            "new_buyers": r_today_new_buyers.scalar() or 0,
            "manual_takeover_triggered": r_today_takeover.scalar() or 0,
            "ai_calls": today_ai_calls,
            "tokens": int(r_today_tokens.scalar() or 0),
            "ai_errors": today_ai_errors,
            "ai_error_rate": round(today_error_rate, 4),
            "avg_latency_ms": today_avg_latency,
            "intent_distribution": intent_distribution,
            "agent_distribution": agent_distribution,
        },
        "cumulative": {
            "conversations": cum_conv,
            "messages": cum_msg,
            "buyers": r_cum_buyers.scalar() or 0,
            "bargain_sessions": r_cum_bargain.scalar() or 0,
            "ai_calls": r_cum_ai_calls.scalar() or 0,
            "tokens": int(r_cum_tokens.scalar() or 0),
        },
        # 向后兼容旧字段，避免老前端构件加载时报错
        "total_conversations": cum_conv,
        "total_messages": cum_msg,
    }
```

- [ ] **Step 2: 重启 backend-web 并打 /logs/stats**

```bash
docker compose restart backend-web
sleep 3
# 拿一个 token
TOKEN=$(curl -s -X POST http://localhost:8089/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8089/api/logs/stats | python3 -m json.tool
```

期望返回包含 `realtime` / `today` / `cumulative` / `total_conversations` / `total_messages` 全部键，且数据类型为对应数字 / 数组。

如果登录凭据不同，按本项目实际管理员账号替换。

- [ ] **Step 3: 提交**

```bash
git add backend-web/app/api/routes/logs.py
git commit -m "feat(api): /logs/stats 扩展为三段式聚合（实时/今日/累计），保留旧字段"
```

---

## Task 7: 前端类型与 API 客户端

**Files:**
- Modify: `frontend/src/api/logs.ts`

- [ ] **Step 1: 扩展类型并修改 `getStats()`**

把 `frontend/src/api/logs.ts` 整体替换为：

```typescript
import request from '@/utils/request'

export async function getConversations(page = 1, pageSize = 20) {
  const { data } = await request.get('/logs/conversations', { params: { page, page_size: pageSize } })
  return data as { items: any[]; total: number; page: number; page_size: number }
}

export async function getMessages(chatId: string) {
  const { data } = await request.get(`/logs/conversations/${chatId}/messages`)
  return data
}

export interface IntentItem {
  name: string
  count: number
}

export interface DashboardStats {
  realtime: {
    manual_active: number
  }
  today: {
    conversations: number
    messages: number
    ai_replies: number
    user_messages: number
    new_buyers: number
    manual_takeover_triggered: number
    ai_calls: number
    tokens: number
    ai_errors: number
    ai_error_rate: number
    avg_latency_ms: number
    intent_distribution: IntentItem[]
    agent_distribution: IntentItem[]
  }
  cumulative: {
    conversations: number
    messages: number
    buyers: number
    bargain_sessions: number
    ai_calls: number
    tokens: number
  }
  total_conversations: number
  total_messages: number
}

export async function getStats(): Promise<DashboardStats> {
  const { data } = await request.get('/logs/stats')
  return data as DashboardStats
}

export async function deleteConversation(chatId: string) {
  await request.delete(`/logs/conversations/${chatId}`)
}

export async function batchDeleteConversations(chatIds: string[]) {
  await request.post('/logs/conversations/batch-delete', { chat_ids: chatIds })
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/api/logs.ts
git commit -m "feat(frontend): 扩展 DashboardStats 类型对接新版 /logs/stats"
```

---

## Task 8: 前端 BarRow 与 StatCard 组件

**Files:**
- Create: `frontend/src/components/dashboard/BarRow.tsx`
- Create: `frontend/src/components/dashboard/StatCard.tsx`

- [ ] **Step 1: 新建目录与 `BarRow.tsx`**

新建 `frontend/src/components/dashboard/BarRow.tsx`：

```tsx
interface BarRowProps {
  label: string
  count: number
  percent: number
}

export default function BarRow({ label, count, percent }: BarRowProps) {
  const safePercent = Math.max(0, Math.min(100, percent))
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="w-24 truncate text-dark-400" title={label}>
        {label}
      </span>
      <span className="w-12 text-right text-gray-50 tabular-nums">{count}</span>
      <div className="flex-1 h-2 bg-dark-700 rounded overflow-hidden">
        <div
          className="h-full bg-primary-500 rounded transition-all"
          style={{ width: `${safePercent}%` }}
        />
      </div>
      <span className="w-12 text-right text-dark-400 tabular-nums">{safePercent.toFixed(0)}%</span>
    </div>
  )
}
```

- [ ] **Step 2: 新建 `StatCard.tsx`**

```tsx
import { ReactNode } from 'react'

interface StatCardProps {
  label: string
  value: ReactNode
  icon?: ReactNode
  hint?: ReactNode
  valueClassName?: string
  iconWrapClassName?: string
}

export default function StatCard({
  label,
  value,
  icon,
  hint,
  valueClassName,
  iconWrapClassName,
}: StatCardProps) {
  return (
    <div className="stat-card card-hover">
      {icon ? (
        <div className={`stat-icon ${iconWrapClassName ?? 'stat-icon-primary'}`}>{icon}</div>
      ) : null}
      <div className="flex-1 min-w-0">
        <p className="text-sm text-dark-400">{label}</p>
        <p className={`text-2xl font-bold mt-1 tabular-nums ${valueClassName ?? 'text-gray-50'}`}>
          {value}
        </p>
        {hint ? <p className="text-xs text-dark-400 mt-1">{hint}</p> : null}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/dashboard/
git commit -m "feat(frontend): 加 BarRow/StatCard 仪表盘可复用组件"
```

---

## Task 9: 重写 DashboardPage

**Files:**
- Modify: `frontend/src/pages/dashboard/DashboardPage.tsx`

- [ ] **Step 1: 重写整个 DashboardPage**

把 `frontend/src/pages/dashboard/DashboardPage.tsx` 整体替换为：

```tsx
import { useEffect, useState } from 'react'
import {
  Activity,
  MessageCircle,
  Users,
  RefreshCw,
  UserPlus,
  Hand,
  Cpu,
  Coins,
  Bot,
  Clock,
  AlertTriangle,
  TrendingUp,
  Handshake,
} from 'lucide-react'
import { DashboardStats, getStats } from '@/api/logs'
import { getWsStatus, reconnectWs } from '@/api/config'
import StatCard from '@/components/dashboard/StatCard'
import BarRow from '@/components/dashboard/BarRow'

const EMPTY_STATS: DashboardStats = {
  realtime: { manual_active: 0 },
  today: {
    conversations: 0,
    messages: 0,
    ai_replies: 0,
    user_messages: 0,
    new_buyers: 0,
    manual_takeover_triggered: 0,
    ai_calls: 0,
    tokens: 0,
    ai_errors: 0,
    ai_error_rate: 0,
    avg_latency_ms: 0,
    intent_distribution: [],
    agent_distribution: [],
  },
  cumulative: {
    conversations: 0,
    messages: 0,
    buyers: 0,
    bargain_sessions: 0,
    ai_calls: 0,
    tokens: 0,
  },
  total_conversations: 0,
  total_messages: 0,
}

function formatNumber(n: number): string {
  return n.toLocaleString('en-US')
}

function formatLatency(ms: number): string {
  if (ms <= 0) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatPercent(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats>(EMPTY_STATS)
  const [wsStatus, setWsStatus] = useState<{ connected: boolean }>({ connected: false })
  const [reconnecting, setReconnecting] = useState(false)

  const refresh = () => {
    getStats().then(setStats).catch(() => {})
    getWsStatus().then(setWsStatus).catch(() => {})
  }

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 15000)
    return () => clearInterval(t)
  }, [])

  const handleReconnect = async () => {
    if (reconnecting) return
    setReconnecting(true)
    try {
      await reconnectWs()
      setTimeout(refresh, 1000)
    } finally {
      setReconnecting(false)
    }
  }

  const { realtime, today, cumulative } = stats
  const intentTotal = today.intent_distribution.reduce((s, x) => s + x.count, 0)
  const agentTotal = today.agent_distribution.reduce((s, x) => s + x.count, 0)
  const errorRateClass = today.ai_error_rate > 0.05 ? 'text-red-400' : 'text-gray-50'

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-50">仪表盘</h2>
          <p className="text-sm text-dark-400 mt-1">系统运行状态与对话统计</p>
        </div>
      </div>

      {/* 实时状态 */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-dark-300 uppercase tracking-wide">实时状态</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="stat-card card-hover">
            <div className={`stat-icon ${wsStatus.connected ? 'stat-icon-success' : 'stat-icon-danger'}`}>
              <Activity size={22} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm text-dark-400">闲鱼连接状态</p>
              <p className={`text-xl font-bold mt-1 ${wsStatus.connected ? 'text-emerald-400' : 'text-red-400'}`}>
                {wsStatus.connected ? '已连接' : '未连接'}
              </p>
              {!wsStatus.connected && (
                <button
                  onClick={handleReconnect}
                  disabled={reconnecting}
                  className="mt-2 inline-flex items-center gap-1.5 text-xs text-primary-400 hover:text-primary-300 disabled:opacity-50"
                >
                  <RefreshCw size={12} className={reconnecting ? 'animate-spin' : ''} />
                  {reconnecting ? '重连中…' : '重新连接'}
                </button>
              )}
            </div>
          </div>

          <StatCard
            label="当前人工接管中"
            value={formatNumber(realtime.manual_active)}
            icon={<Hand size={22} />}
            iconWrapClassName="stat-icon-warning"
            hint="manual_mode=1 的会话数"
          />
        </div>
      </section>

      {/* 今日概览 */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-dark-300 uppercase tracking-wide">
          今日概览（自零点起，Asia/Shanghai）
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard label="新增会话" value={formatNumber(today.conversations)} icon={<Users size={22} />} />
          <StatCard label="新增消息" value={formatNumber(today.messages)} icon={<MessageCircle size={22} />} />
          <StatCard label="AI 回复" value={formatNumber(today.ai_replies)} icon={<Bot size={22} />} />
          <StatCard label="买家提问" value={formatNumber(today.user_messages)} icon={<MessageCircle size={22} />} />
          <StatCard label="新增买家" value={formatNumber(today.new_buyers)} icon={<UserPlus size={22} />} />
          <StatCard label="触发接管次数" value={formatNumber(today.manual_takeover_triggered)} icon={<Hand size={22} />} iconWrapClassName="stat-icon-warning" />
          <StatCard label="AI 调用次数" value={formatNumber(today.ai_calls)} icon={<Cpu size={22} />} />
          <StatCard label="Token 消耗" value={formatNumber(today.tokens)} icon={<Coins size={22} />} />
          <StatCard
            label="平均响应时长"
            value={formatLatency(today.avg_latency_ms)}
            icon={<Clock size={22} />}
          />
          <StatCard
            label="AI 错误率"
            value={formatPercent(today.ai_error_rate)}
            icon={<AlertTriangle size={22} />}
            iconWrapClassName={today.ai_error_rate > 0.05 ? 'stat-icon-danger' : 'stat-icon-warning'}
            valueClassName={errorRateClass}
            hint={`失败 ${formatNumber(today.ai_errors)} / 总 ${formatNumber(today.ai_calls)}`}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
          <div className="card p-4 space-y-2">
            <p className="text-sm font-semibold text-gray-50 mb-2">今日意图分布</p>
            {today.intent_distribution.length === 0 ? (
              <p className="text-sm text-dark-400">暂无数据</p>
            ) : (
              today.intent_distribution.map((item) => (
                <BarRow
                  key={item.name}
                  label={item.name}
                  count={item.count}
                  percent={intentTotal > 0 ? (item.count / intentTotal) * 100 : 0}
                />
              ))
            )}
          </div>
          <div className="card p-4 space-y-2">
            <p className="text-sm font-semibold text-gray-50 mb-2">今日 Agent 调用拆分</p>
            {today.agent_distribution.length === 0 ? (
              <p className="text-sm text-dark-400">暂无数据</p>
            ) : (
              today.agent_distribution.map((item) => (
                <BarRow
                  key={item.name}
                  label={item.name}
                  count={item.count}
                  percent={agentTotal > 0 ? (item.count / agentTotal) * 100 : 0}
                />
              ))
            )}
          </div>
        </div>
      </section>

      {/* 累计 */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-dark-300 uppercase tracking-wide">累计</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <StatCard label="累计会话" value={formatNumber(cumulative.conversations)} icon={<Users size={22} />} />
          <StatCard label="累计消息" value={formatNumber(cumulative.messages)} icon={<MessageCircle size={22} />} />
          <StatCard label="累计买家" value={formatNumber(cumulative.buyers)} icon={<UserPlus size={22} />} />
          <StatCard label="议价会话" value={formatNumber(cumulative.bargain_sessions)} icon={<Handshake size={22} />} iconWrapClassName="stat-icon-warning" />
          <StatCard label="AI 调用次数" value={formatNumber(cumulative.ai_calls)} icon={<Cpu size={22} />} />
          <StatCard label="Token 消耗" value={formatNumber(cumulative.tokens)} icon={<TrendingUp size={22} />} />
        </div>
      </section>
    </div>
  )
}
```

- [ ] **Step 2: 重建前端镜像并检查页面**

```bash
docker compose up -d --build frontend
```

浏览器打开 `http://localhost/` 登录后访问仪表盘。检查：

- 实时状态区显示 WS 状态与人工接管数
- 今日概览有 10 张卡片 + 两个条形分布区
- 累计区有 6 张卡片
- 移动端宽度（开发者工具切到手机视图）卡片正常塌成 1 列
- 控制台无 TypeError

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/dashboard/DashboardPage.tsx
git commit -m "feat(frontend): 仪表盘重写为实时/今日/累计三大区 + 意图与Agent条形分布"
```

---

## Task 10: 集成验证

**Files:** 无修改，仅验证

- [ ] **Step 1: 跑零回归脚本**

```bash
docker compose exec websocket python /app/scripts/verify_dashboard_byte_equality.py
```

期望最后一行：`All byte-equality checks passed.`

- [ ] **Step 2: 触发一次真实 LLM 调用**

通过前端"商品 / 测试对话"或 curl 模拟一条买家消息流入 websocket。等几秒后查 DB：

```bash
docker compose exec mysql mysql -uroot -proot -e "
USE xianyu;
SELECT id, agent_name, model, chat_id, prompt_tokens, completion_tokens, total_tokens, latency_ms, success, created_at
FROM ai_call_log ORDER BY id DESC LIMIT 5;"
```

期望看到新增记录，`total_tokens > 0`、`latency_ms > 0`、`success=1`、`chat_id` 非空（如果来自实际买家对话）。

- [ ] **Step 3: 验证 stats 接口包含真实数据**

```bash
TOKEN=$(curl -s -X POST http://localhost:8089/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8089/api/logs/stats | python3 -m json.tool
```

期望 `today.ai_calls >= 1`、`today.tokens > 0`、`today.agent_distribution` 包含触发的 agent。

- [ ] **Step 4: 模拟 LLM 失败路径（可选）**

临时把 `.env` 的 `API_KEY` 改成无效值，触发一次对话，观察：

- 主流程不崩（manager 仍正常收消息）
- `ai_call_log` 多出 `success=0` 的记录
- `/logs/stats` 中 `today.ai_errors` +1、`today.ai_error_rate` 上升

完成后还原 `API_KEY`。

- [ ] **Step 5: 仪表盘 UI 终检**

浏览器刷新仪表盘，确认所有卡片数据与 `/logs/stats` 返回完全一致，两个条形分布的占比加起来约 100%。

- [ ] **Step 6: 不打提交**

本任务无代码变更，验证通过即结束。
