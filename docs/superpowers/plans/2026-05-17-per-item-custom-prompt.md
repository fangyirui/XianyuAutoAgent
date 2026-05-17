# 商品级额外 AI 提示词 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在商品配置页给每件商品加一个可选的"额外 AI 提示词"字段，AI 生成回复时把它追加到 price/tech/default Agent 的 system message 末尾；空值时主流程行为字节级与改动前一致。

**Architecture:** `item_cache` 表新增 `custom_prompt TEXT NULL` 列；后端加 `PATCH /items/{item_id}` 写入；websocket 服务从同表读取并透传给 Bot；BaseAgent 在 `_build_messages` 用严格门控 `if item_custom_prompt:` 决定是否追加（关键的零回归保证点）；前端表格加一列内嵌展开式 textarea。

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy(async) / MySQL / React + TypeScript / Vite / Tailwind

**Spec:** `docs/superpowers/specs/2026-05-17-per-item-custom-prompt-design.md`

**约束:** 项目无现有 pytest 测试设施。采用「编写一个独立验证脚本 + 走 spec §6 手工验证清单」的方式做零回归保障，而不是引入测试框架。

---

## File Structure

**新增文件：**
- `scripts/verify_prompt_byte_equality.py` —— 独立验证脚本，断言 `BaseAgent._build_messages(item_custom_prompt=None/"")` 输出与改动前字节级一致

**修改文件：**
- `init.sql` —— `item_cache` 表加列
- `common/models/item_cache.py` —— ORM 字段
- `backend-web/app/api/routes/items.py` —— GET 返回字段 + 新增 PATCH 路由
- `websocket/app/websocket/manager.py` —— 读 custom_prompt 并透传；保护性更新
- `websocket/app/services/agent/bot.py` —— `generate_reply` 加 kwarg + 透传（不传给 classify）
- `websocket/app/services/agent/base.py` —— `_build_messages` 加严格门控
- `websocket/app/services/agent/price.py` —— 透传 + 保持 ▲议价轮次 在最末
- `websocket/app/services/agent/tech.py` —— 透传
- `websocket/app/services/agent/default.py` —— 继承自动支持（_call_llm 没改 _build_messages）
- `frontend/src/api/items.ts` —— 新增 `updateItemPrompt`
- `frontend/src/pages/items/ItemsPage.tsx` —— 表格新增"AI 提示词"列 + 内嵌展开编辑

---

## Task 1: 数据库 Schema

**Files:**
- Modify: `init.sql`
- Modify: `common/models/item_cache.py`

- [ ] **Step 1: 修改 `init.sql`**

在 `item_cache` 表 `description TEXT,` 行下方加入新列。完整 `item_cache` 段落改为：

```sql
CREATE TABLE IF NOT EXISTS item_cache (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    item_id VARCHAR(64) UNIQUE NOT NULL,
    seller_id VARCHAR(64) COMMENT '商品所属卖家ID',
    title VARCHAR(256),
    price DECIMAL(10,2),
    description TEXT,
    custom_prompt TEXT NULL COMMENT '该商品的额外AI提示词',
    raw_json JSON,
    fetched_at DATETIME DEFAULT NOW(),
    expired_at DATETIME,
    INDEX idx_item_cache_seller_id (seller_id)
);
```

- [ ] **Step 2: 修改 `common/models/item_cache.py`**

在 `description` 行之后加 `custom_prompt`：

```python
from sqlalchemy import Column, BigInteger, String, Text, DateTime, Numeric, JSON, func
from .base import Base


class ItemCache(Base):
    __tablename__ = "item_cache"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    item_id = Column(String(64), unique=True, nullable=False)
    seller_id = Column(String(64), nullable=True, index=True, comment="商品所属卖家ID")
    title = Column(String(256), nullable=True)
    price = Column(Numeric(10, 2), nullable=True)
    description = Column(Text, nullable=True)
    custom_prompt = Column(Text, nullable=True, comment="该商品的额外AI提示词")
    raw_json = Column(JSON, nullable=True)
    fetched_at = Column(DateTime, server_default=func.now())
    expired_at = Column(DateTime, nullable=True)
```

- [ ] **Step 3: 对现有 DB 添加列（开发环境）**

如果开发库已经存在，需要手动迁移。运行：

```bash
# 假设 MySQL 容器名 xianyu-mysql / 用户 root / 库名 xianyu
# 实际命令以 docker-compose.yml / .env 为准
docker exec -i xianyu-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" xianyu <<'SQL'
ALTER TABLE item_cache
  ADD COLUMN custom_prompt TEXT NULL COMMENT '该商品的额外AI提示词'
  AFTER description;
SQL
```

如果没有 docker 环境或者用本地 MySQL，等价 SQL 直接执行。

Expected: 返回 0 行受影响（建表）或一条 `Query OK` 表示新增了列。再次执行报 `Duplicate column name 'custom_prompt'` 也属正常（说明已加过）。

- [ ] **Step 4: Commit**

```bash
git add init.sql common/models/item_cache.py
git commit -m "feat(db): 商品缓存表新增 custom_prompt 列"
```

---

## Task 2: 持久化保护（同步时不覆盖 custom_prompt）

**Files:**
- Modify: `websocket/app/websocket/manager.py`

由于 ORM 写入是按字段赋值（`row.title = ...`），只要我们**不写**就不会覆盖。`_save_item_cache` 和 `_batch_save_items_from_list` 当前都没写 `custom_prompt`，所以默认就是保留的。但为了未来维护安全，加一行显式注释。

- [ ] **Step 1: 在 `_save_item_cache` 更新分支加注释**

在 `websocket/app/websocket/manager.py` 第 135-142 行附近，找到：

```python
            if row:
                row.raw_json = data
                row.title = data.get("title", "") or row.title
                if price > 0:
                    row.price = price
                row.description = data.get("desc", "") or row.description
                row.seller_id = str(self.myid)
                row.fetched_at = now
```

替换为：

```python
            if row:
                row.raw_json = data
                row.title = data.get("title", "") or row.title
                if price > 0:
                    row.price = price
                row.description = data.get("desc", "") or row.description
                row.seller_id = str(self.myid)
                row.fetched_at = now
                # NOTE: 不要写 row.custom_prompt —— 用户在管理后台手工配置的提示词必须保留
```

- [ ] **Step 2: 在 `_batch_save_items_from_list` 更新分支加同样注释**

找到（约 174-182 行）：

```python
                if row:
                    if title:
                        row.title = title
                    if price > 0:
                        row.price = price
                    row.seller_id = str(self.myid)
                    if not row.raw_json or "soldPrice" not in row.raw_json:
                        row.raw_json = it
                    row.fetched_at = now
```

替换为：

```python
                if row:
                    if title:
                        row.title = title
                    if price > 0:
                        row.price = price
                    row.seller_id = str(self.myid)
                    if not row.raw_json or "soldPrice" not in row.raw_json:
                        row.raw_json = it
                    row.fetched_at = now
                    # NOTE: 不要写 row.custom_prompt —— 用户在管理后台手工配置的提示词必须保留
```

- [ ] **Step 3: Commit**

```bash
git add websocket/app/websocket/manager.py
git commit -m "chore(manager): 同步商品时保留用户配置的 custom_prompt"
```

---

## Task 3: 后端 API —— GET 返回字段 + 新增 PATCH

**Files:**
- Modify: `backend-web/app/api/routes/items.py`

- [ ] **Step 1: GET /items 响应增加 custom_prompt 字段**

找到 `backend-web/app/api/routes/items.py` 第 47-58 行的拼装循环：

```python
    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "item_id": r.item_id,
            "seller_id": r.seller_id or "",
            "title": r.title or "",
            "price": float(r.price) if r.price else 0,
            "description": r.description or "",
            "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
        })
```

替换为（新增 `custom_prompt` 字段，NULL 转空串以避免前端 null 兼容麻烦）：

```python
    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "item_id": r.item_id,
            "seller_id": r.seller_id or "",
            "title": r.title or "",
            "price": float(r.price) if r.price else 0,
            "description": r.description or "",
            "custom_prompt": r.custom_prompt or "",
            "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
        })
```

- [ ] **Step 2: 新增 PATCH /items/{item_id} 路由**

在文件末尾追加：

```python
from pydantic import BaseModel


class ItemPromptUpdate(BaseModel):
    custom_prompt: str


@router.patch("/{item_id}")
async def update_item_prompt(
    item_id: str,
    payload: ItemPromptUpdate,
    db: AsyncSession = Depends(get_db),
):
    # 仅允许修改当前活跃卖家名下的商品
    seller_result = await db.execute(select(Seller.user_id).where(Seller.is_active.is_(True)))
    seller_ids = [r[0] for r in seller_result.all()]

    query = select(ItemCache).where(ItemCache.item_id == item_id)
    if seller_ids:
        query = query.where(ItemCache.seller_id.in_(seller_ids))

    result = await db.execute(query)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="商品不存在或无权限修改")

    item.custom_prompt = payload.custom_prompt or None
    await db.commit()
    return {"ok": True, "custom_prompt": item.custom_prompt or ""}
```

- [ ] **Step 3: 重启 backend-web 服务确认路由注册成功**

```bash
# 取决于本地启动方式，常见为：
docker-compose restart backend-web
# 或本地：重启 uvicorn 进程
```

用 curl 测试（先准备好 JWT）：

```bash
TOKEN="<your access token>"
curl -X PATCH http://localhost:8000/api/items/<some_item_id> \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"custom_prompt": "测试用提示词"}'
```

Expected: `{"ok": true, "custom_prompt": "测试用提示词"}`

清空：

```bash
curl -X PATCH http://localhost:8000/api/items/<same_item_id> \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"custom_prompt": ""}'
```

Expected: `{"ok": true, "custom_prompt": ""}`

- [ ] **Step 4: Commit**

```bash
git add backend-web/app/api/routes/items.py
git commit -m "feat(api): GET /items 返回 custom_prompt，新增 PATCH /items/{item_id}"
```

---

## Task 4: BaseAgent 严格门控（最关键的零回归改动）

**Files:**
- Modify: `websocket/app/services/agent/base.py`

- [ ] **Step 1: 修改 `BaseAgent.generate` 和 `_build_messages`**

打开 `websocket/app/services/agent/base.py`，整文件替换为：

```python
from typing import List, Dict, Optional
from openai import AsyncOpenAI
from loguru import logger
from common.core import settings


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
    ) -> str:
        messages = self._build_messages(user_msg, item_desc, context, item_custom_prompt)
        logger.debug(f"[{self.__class__.__name__}] 构建消息完成，system_prompt长度={len(self.system_prompt)}, 商品额外提示词={'有' if item_custom_prompt else '无'}")
        response = await self._call_llm(messages)
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

    async def _call_llm(self, messages: List[Dict], temperature: float = 0.4) -> str:
        logger.info(f"[{self.__class__.__name__}] LLM请求 | model={settings.MODEL_NAME}, temp={temperature}")
        logger.debug(f"[{self.__class__.__name__}] 完整提示词:\n{messages[0]['content']}")
        logger.debug(f"[{self.__class__.__name__}] 用户输入: {messages[-1]['content']}")
        try:
            response = await self.client.chat.completions.create(
                model=settings.MODEL_NAME,
                messages=messages,
                temperature=temperature,
                max_tokens=500,
                top_p=0.8
            )
            result = response.choices[0].message.content or ""
            logger.info(f"[{self.__class__.__name__}] LLM响应: {result}")
            logger.debug(f"[{self.__class__.__name__}] token用量: {response.usage}")
            return result
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] LLM调用失败: {e}")
            raise
```

**关键点：** `if item_custom_prompt:` 这一行 —— 空串 `""`、`None`、`0` 都 falsy，进不去 if 分支，`sys_content` 字符串与原始版本字节级一致。

- [ ] **Step 2: Commit**

```bash
git add websocket/app/services/agent/base.py
git commit -m "feat(agent): BaseAgent 支持商品级 custom_prompt，空值零回归门控"
```

---

## Task 5: 字节级一致性验证脚本

**Files:**
- Create: `scripts/verify_prompt_byte_equality.py`

- [ ] **Step 1: 新建脚本目录与文件**

```bash
mkdir -p scripts
```

新建 `scripts/verify_prompt_byte_equality.py`：

```python
"""验证 BaseAgent._build_messages 在 item_custom_prompt 为空时输出与改动前字节级一致。

主流程零回归保障：旧版本拼接的字符串是
    f"【商品信息】{item_desc}\n【你与客户对话历史】{context}\n{self.system_prompt}"
新版本在空 custom_prompt 时不能添加任何字符（含换行、标题）。

用法：
    python scripts/verify_prompt_byte_equality.py
"""
import sys
from pathlib import Path

# 加载 project root 到 sys.path 让脚本能 import websocket.app.*
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "websocket"))

from websocket.app.services.agent.base import BaseAgent


def expected_old_content(item_desc, context, system_prompt):
    """1:1 复刻改动前的拼接逻辑"""
    return f"【商品信息】{item_desc}\n【你与客户对话历史】{context}\n{system_prompt}"


def main():
    # 构造一个不调用 LLM 的 BaseAgent 实例
    agent = BaseAgent(client=None, system_prompt="你是闲鱼客服，请礼貌回答。", safety_filter=lambda x: x)
    item_desc = '当前商品的信息如下：{"title":"测试","desc":"成色95新"}'
    context = "user: 你好\nassistant: 您好"
    user_msg = "在吗"

    expected_sys = expected_old_content(item_desc, context, agent.system_prompt)

    # Case 1: item_custom_prompt=None
    msgs = agent._build_messages(user_msg, item_desc, context, item_custom_prompt=None)
    actual = msgs[0]["content"]
    assert actual == expected_sys, f"[FAIL] None case\n--- expected ---\n{expected_sys!r}\n--- actual ---\n{actual!r}"
    print("[PASS] None case 字节一致")

    # Case 2: item_custom_prompt=""
    msgs = agent._build_messages(user_msg, item_desc, context, item_custom_prompt="")
    actual = msgs[0]["content"]
    assert actual == expected_sys, f"[FAIL] empty-string case\n--- expected ---\n{expected_sys!r}\n--- actual ---\n{actual!r}"
    print("[PASS] '' case 字节一致")

    # Case 3: 不传参（默认值 None）
    msgs = agent._build_messages(user_msg, item_desc, context)
    actual = msgs[0]["content"]
    assert actual == expected_sys, f"[FAIL] default-kwarg case\n--- expected ---\n{expected_sys!r}\n--- actual ---\n{actual!r}"
    print("[PASS] 默认参数（缺省）case 字节一致")

    # Case 4: 有值时正确追加
    msgs = agent._build_messages(user_msg, item_desc, context, item_custom_prompt="本商品仅顺丰发货")
    actual = msgs[0]["content"]
    expected_with = expected_sys + "\n【针对本商品的特别说明】本商品仅顺丰发货"
    assert actual == expected_with, f"[FAIL] with-prompt case\n--- expected ---\n{expected_with!r}\n--- actual ---\n{actual!r}"
    print("[PASS] 有值 case 拼接正确")

    print("\n全部通过：零回归门控有效。")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行脚本**

```bash
cd /Users/fangyirui/PycharmProjects/XianyuAutoAgent
python scripts/verify_prompt_byte_equality.py
```

Expected:
```
[PASS] None case 字节一致
[PASS] '' case 字节一致
[PASS] 默认参数（缺省）case 字节一致
[PASS] 有值 case 拼接正确

全部通过：零回归门控有效。
```

如果任意一行打印 `[FAIL]`，回到 Task 4 修复 `_build_messages` 后重跑，直到全部 PASS。

- [ ] **Step 3: Commit**

```bash
git add scripts/verify_prompt_byte_equality.py
git commit -m "test: 新增 _build_messages 字节级零回归验证脚本"
```

---

## Task 6: PriceAgent / TechAgent 透传 custom_prompt

**Files:**
- Modify: `websocket/app/services/agent/price.py`
- Modify: `websocket/app/services/agent/tech.py`

`DefaultAgent` 只重写了 `_call_llm`，不重写 `generate` 或 `_build_messages`，所以会自动通过 `BaseAgent.generate` 收到 `item_custom_prompt` kwarg —— 无需改动。

- [ ] **Step 1: 修改 `websocket/app/services/agent/price.py`**

整文件替换为：

```python
from typing import Optional
from loguru import logger
from .base import BaseAgent
from common.core import settings


class PriceAgent(BaseAgent):
    async def generate(
        self,
        user_msg: str,
        item_desc: str,
        context: str,
        bargain_count: int = 0,
        item_custom_prompt: Optional[str] = None,
    ) -> str:
        dynamic_temp = self._calc_temperature(bargain_count)
        messages = self._build_messages(user_msg, item_desc, context, item_custom_prompt)
        # ▲议价轮次 永远追加到 system content 末尾（在 custom_prompt 之后），与原行为保持一致
        messages[0]["content"] += f"\n▲当前议价轮次：{bargain_count}"

        logger.info(f"[PriceAgent] LLM请求 | model={settings.MODEL_NAME}, temp={dynamic_temp}, 议价轮次={bargain_count}")
        logger.debug(f"[PriceAgent] 完整提示词:\n{messages[0]['content']}")
        logger.debug(f"[PriceAgent] 用户输入: {messages[-1]['content']}")

        try:
            response = await self.client.chat.completions.create(
                model=settings.MODEL_NAME,
                messages=messages,
                temperature=dynamic_temp,
                max_tokens=500,
                top_p=0.8
            )
            result = self.safety_filter(response.choices[0].message.content)
            logger.info(f"[PriceAgent] LLM响应: {result}")
            logger.debug(f"[PriceAgent] token用量: {response.usage}")
            return result
        except Exception as e:
            logger.error(f"[PriceAgent] LLM调用失败: {e}")
            raise

    def _calc_temperature(self, bargain_count: int) -> float:
        return min(0.3 + bargain_count * 0.15, 0.9)
```

- [ ] **Step 2: 修改 `websocket/app/services/agent/tech.py`**

整文件替换为：

```python
from typing import Optional
from loguru import logger
from .base import BaseAgent
from common.core import settings


class TechAgent(BaseAgent):
    async def generate(
        self,
        user_msg: str,
        item_desc: str,
        context: str,
        bargain_count: int = 0,
        item_custom_prompt: Optional[str] = None,
    ) -> str:
        messages = self._build_messages(user_msg, item_desc, context, item_custom_prompt)

        logger.info(f"[TechAgent] LLM请求 | model={settings.MODEL_NAME}, enable_search=True")
        logger.debug(f"[TechAgent] 完整提示词:\n{messages[0]['content']}")
        logger.debug(f"[TechAgent] 用户输入: {messages[-1]['content']}")

        try:
            response = await self.client.chat.completions.create(
                model=settings.MODEL_NAME,
                messages=messages,
                temperature=0.4,
                max_tokens=500,
                top_p=0.8,
                extra_body={"enable_search": True}
            )
            result = self.safety_filter(response.choices[0].message.content)
            logger.info(f"[TechAgent] LLM响应: {result}")
            logger.debug(f"[TechAgent] token用量: {response.usage}")
            return result
        except Exception as e:
            logger.error(f"[TechAgent] LLM调用失败: {e}")
            raise
```

- [ ] **Step 3: 验证再次跑验证脚本**

```bash
python scripts/verify_prompt_byte_equality.py
```

Expected: 4 个 PASS 全部通过（脚本只验 BaseAgent，但 Price/Tech 用同一个 `_build_messages`，所以隐含验证）。

- [ ] **Step 4: Commit**

```bash
git add websocket/app/services/agent/price.py websocket/app/services/agent/tech.py
git commit -m "feat(agent): Price/Tech 透传 item_custom_prompt（保持 ▲议价轮次 在末尾）"
```

---

## Task 7: Bot 层透传 + 不传给 ClassifyAgent

**Files:**
- Modify: `websocket/app/services/agent/bot.py`

`IntentRouter.detect` 签名保持不变 —— classify 调用链完全隔离，自然不会拿到 `item_custom_prompt`。

- [ ] **Step 1: 修改 `XianyuReplyBot.generate_reply`**

打开 `websocket/app/services/agent/bot.py`，找到 131-159 行的 `generate_reply` 方法：

```python
    async def generate_reply(self, user_msg: str, item_desc: str, context: List[Dict]) -> str:
        logger.info(f"[Bot] 开始处理 | 用户消息: {user_msg}")
        logger.debug(f"[Bot] 商品信息: {item_desc}")
        logger.debug(f"[Bot] 上下文条数: {len(context)}")

        formatted_context = self.format_history(context)
        detected_intent = await self.router.detect(user_msg, item_desc, formatted_context)

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
            user_msg=user_msg, item_desc=item_desc, context=formatted_context, bargain_count=bargain_count
        )
        logger.info(f"[Bot] 最终回复: {reply}")
        return reply
```

替换为：

```python
    async def generate_reply(
        self,
        user_msg: str,
        item_desc: str,
        context: List[Dict],
        item_custom_prompt: str | None = None,
    ) -> str:
        logger.info(f"[Bot] 开始处理 | 用户消息: {user_msg}")
        logger.debug(f"[Bot] 商品信息: {item_desc}")
        logger.debug(f"[Bot] 上下文条数: {len(context)}, 商品额外提示词={'有' if item_custom_prompt else '无'}")

        formatted_context = self.format_history(context)
        # IntentRouter / ClassifyAgent 不接收 item_custom_prompt（避免污染意图判断）
        detected_intent = await self.router.detect(user_msg, item_desc, formatted_context)

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
        )
        logger.info(f"[Bot] 最终回复: {reply}")
        return reply
```

- [ ] **Step 2: Commit**

```bash
git add websocket/app/services/agent/bot.py
git commit -m "feat(bot): generate_reply 透传 item_custom_prompt 给非 classify Agent"
```

---

## Task 8: WebSocket Manager 读取 + 透传

**Files:**
- Modify: `websocket/app/websocket/manager.py`

- [ ] **Step 1: 修改 `_get_item_cache` 同时返回 custom_prompt**

找到 `websocket/app/websocket/manager.py` 第 105-112 行：

```python
    async def _get_item_cache(self, item_id: str) -> dict | None:
        """只在缓存含完整 itemDO（带 soldPrice）时返回；只有列表数据时返回 None 以触发详情补全。"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ItemCache).where(ItemCache.item_id == item_id))
            row = result.scalar_one_or_none()
            if row and row.raw_json and "soldPrice" in row.raw_json:
                return row.raw_json
            return None
```

替换为（保持原签名兼容，**新增**一个并行方法读 custom_prompt）：

```python
    async def _get_item_cache(self, item_id: str) -> dict | None:
        """只在缓存含完整 itemDO（带 soldPrice）时返回；只有列表数据时返回 None 以触发详情补全。"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ItemCache).where(ItemCache.item_id == item_id))
            row = result.scalar_one_or_none()
            if row and row.raw_json and "soldPrice" in row.raw_json:
                return row.raw_json
            return None

    async def _get_item_custom_prompt(self, item_id: str) -> str:
        """读取商品级额外 AI 提示词；不存在或空返回空串。"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ItemCache.custom_prompt).where(ItemCache.item_id == item_id)
            )
            row = result.first()
            return (row[0] or "") if row else ""
```

- [ ] **Step 2: 在 `handle_message` 里调用并透传**

找到第 363-380 行附近的代码块：

```python
        item_info = await self._get_item_cache(item_id)
        if not item_info:
            logger.info(f"商品详情未命中，调用详情API补全 | item_id={item_id}")
            api_result = await self.apis.get_item_info(item_id)
            if "data" in api_result and "itemDO" in api_result["data"]:
                item_info = api_result["data"]["itemDO"]
                await self._save_item_cache(item_id, item_info)
                logger.info(f"商品详情已缓存 | item_id={item_id}, title={item_info.get('title', '')}")
            else:
                logger.warning(f"获取商品详情失败 | item_id={item_id}, response_keys={list(api_result.keys())}")
                return

        conv = await self._get_or_create_conversation(chat_id, send_user_id, item_id, sender_nickname)
        context = await self._get_context(conv.id)
        item_desc = f"当前商品的信息如下：{self.build_item_description(item_info)}"
        logger.info(f"开始生成AI回复 | chat_id={chat_id}, 上下文条数={len(context)}")
        bot_reply = await self.bot.generate_reply(send_message, item_desc, context)
```

替换为：

```python
        item_info = await self._get_item_cache(item_id)
        if not item_info:
            logger.info(f"商品详情未命中，调用详情API补全 | item_id={item_id}")
            api_result = await self.apis.get_item_info(item_id)
            if "data" in api_result and "itemDO" in api_result["data"]:
                item_info = api_result["data"]["itemDO"]
                await self._save_item_cache(item_id, item_info)
                logger.info(f"商品详情已缓存 | item_id={item_id}, title={item_info.get('title', '')}")
            else:
                logger.warning(f"获取商品详情失败 | item_id={item_id}, response_keys={list(api_result.keys())}")
                return

        conv = await self._get_or_create_conversation(chat_id, send_user_id, item_id, sender_nickname)
        context = await self._get_context(conv.id)
        item_desc = f"当前商品的信息如下：{self.build_item_description(item_info)}"
        item_custom_prompt = await self._get_item_custom_prompt(item_id)
        logger.info(f"开始生成AI回复 | chat_id={chat_id}, 上下文条数={len(context)}, 商品额外提示词长度={len(item_custom_prompt)}")
        bot_reply = await self.bot.generate_reply(
            send_message, item_desc, context, item_custom_prompt=item_custom_prompt,
        )
```

- [ ] **Step 3: Commit**

```bash
git add websocket/app/websocket/manager.py
git commit -m "feat(ws): handle_message 读取并透传商品级 custom_prompt"
```

---

## Task 9: 前端 API 客户端

**Files:**
- Modify: `frontend/src/api/items.ts`

- [ ] **Step 1: 整文件替换 `frontend/src/api/items.ts`**

```typescript
import request from '@/utils/request'

export async function getItems(params: { page?: number; page_size?: number; keyword?: string }) {
  const { data } = await request.get('/items', { params })
  return data
}

export async function syncItems() {
  const { data } = await request.post('/items/sync')
  return data
}

export async function updateItemPrompt(itemId: string, customPrompt: string) {
  const { data } = await request.patch(`/items/${itemId}`, { custom_prompt: customPrompt })
  return data
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/items.ts
git commit -m "feat(fe-api): 新增 updateItemPrompt 调用 PATCH /items/{id}"
```

---

## Task 10: 前端 UI —— ItemsPage 加 "AI 提示词" 列与内嵌编辑

**Files:**
- Modify: `frontend/src/pages/items/ItemsPage.tsx`

- [ ] **Step 1: 整文件替换 `frontend/src/pages/items/ItemsPage.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { getItems, syncItems, updateItemPrompt } from '@/api/items'

interface Item {
  id: number
  item_id: string
  seller_id: string
  title: string
  price: number
  description: string
  custom_prompt: string
  fetched_at: string | null
}

export default function ItemsPage() {
  const [items, setItems] = useState<Item[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState('')
  const [error, setError] = useState('')
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())
  const [editingPromptId, setEditingPromptId] = useState<number | null>(null)
  const [promptDraft, setPromptDraft] = useState('')
  const [savingPromptId, setSavingPromptId] = useState<number | null>(null)
  const [promptErr, setPromptErr] = useState('')
  const pageSize = 20

  const toggleExpand = (id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const fetchItems = async (p: number, kw: string) => {
    setLoading(true)
    setError('')
    try {
      const res = await getItems({ page: p, page_size: pageSize, keyword: kw || undefined })
      setItems(res.items)
      setTotal(res.total)
    } catch (e: any) {
      setError(e?.response?.data?.detail || '加载失败，请稍后重试')
    }
    setLoading(false)
  }

  useEffect(() => { fetchItems(page, keyword) }, [page, keyword])

  const handleSearch = () => { setPage(1); setKeyword(searchInput) }

  const handleSync = async () => {
    if (syncing) return
    setSyncing(true)
    setSyncMsg('')
    try {
      const res = await syncItems()
      const saved = res?.saved ?? 0
      setSyncMsg(`同步完成，已写入 ${saved} 条商品`)
      await fetchItems(page, keyword)
    } catch (e: any) {
      setSyncMsg(e?.response?.data?.detail || '同步失败，请查看 websocket 日志')
    } finally {
      setSyncing(false)
      setTimeout(() => setSyncMsg(''), 6000)
    }
  }

  const startEditPrompt = (item: Item) => {
    setEditingPromptId(item.id)
    setPromptDraft(item.custom_prompt || '')
    setPromptErr('')
  }

  const cancelEditPrompt = () => {
    setEditingPromptId(null)
    setPromptDraft('')
    setPromptErr('')
  }

  const savePrompt = async (item: Item) => {
    setSavingPromptId(item.id)
    setPromptErr('')
    try {
      const res = await updateItemPrompt(item.item_id, promptDraft)
      setItems((prev) => prev.map((it) => it.id === item.id ? { ...it, custom_prompt: res.custom_prompt ?? promptDraft } : it))
      setEditingPromptId(null)
      setPromptDraft('')
    } catch (e: any) {
      setPromptErr(e?.response?.data?.detail || '保存失败')
    } finally {
      setSavingPromptId(null)
    }
  }

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">商品缓存</h2>
        <button onClick={handleSync} disabled={syncing}
          className="px-4 py-2 bg-emerald-500 text-gray-900 font-semibold rounded-lg text-sm hover:bg-emerald-400 disabled:opacity-50">
          {syncing ? '同步中...' : '从闲鱼同步商品'}
        </button>
      </div>
      <p className="text-sm text-gray-400">
        已缓存 {total} 件归属于当前卖家的商品。点击右上角按钮从闲鱼拉取最新商品列表（"在售"分组）。可单独为某商品配置"AI 提示词"，AI 生成回复时会作为系统提示词的补充。
      </p>

      <div className="flex gap-2">
        <input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="搜索商品标题..."
          className="flex-1 max-w-sm bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-400"
        />
        <button onClick={handleSearch}
          className="px-4 py-2 bg-gray-700 text-gray-200 rounded-lg text-sm hover:bg-gray-600">
          搜索
        </button>
      </div>

      {syncMsg && <div className="text-sm py-2 text-emerald-300">{syncMsg}</div>}
      {error && <div className="text-red-400 text-sm py-2">{error}</div>}

      {loading ? (
        <div className="text-gray-400 text-sm py-8 text-center">加载中...</div>
      ) : items.length === 0 && !error ? (
        <div className="text-gray-400 text-sm py-8 text-center">暂无商品缓存</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700 text-gray-400">
                <th className="text-left py-2 px-3">商品ID</th>
                <th className="text-left py-2 px-3">卖家ID</th>
                <th className="text-left py-2 px-3">标题</th>
                <th className="text-right py-2 px-3">价格</th>
                <th className="text-left py-2 px-3">描述</th>
                <th className="text-left py-2 px-3">AI 提示词</th>
                <th className="text-left py-2 px-3">缓存时间</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const expanded = expandedIds.has(item.id)
                const hasDesc = !!item.description
                const editing = editingPromptId === item.id
                const saving = savingPromptId === item.id
                const hasPrompt = !!(item.custom_prompt && item.custom_prompt.trim())
                return (
                  <tr key={item.id} className="border-b border-gray-700/50 hover:bg-gray-800/50 align-top">
                    <td className="py-2 px-3 font-mono text-xs text-gray-400 whitespace-nowrap">{item.item_id}</td>
                    <td className="py-2 px-3 font-mono text-xs text-gray-400 whitespace-nowrap">{item.seller_id || '-'}</td>
                    <td className="py-2 px-3 max-w-xs">{item.title || '-'}</td>
                    <td className="py-2 px-3 text-right text-emerald-400 whitespace-nowrap">{item.price > 0 ? `¥${item.price}` : '-'}</td>
                    <td
                      onClick={() => hasDesc && toggleExpand(item.id)}
                      className={`py-2 px-3 max-w-md text-gray-300 text-xs ${hasDesc ? 'cursor-pointer select-none' : ''} ${expanded ? 'whitespace-pre-line break-words' : 'truncate'}`}
                      title={hasDesc ? (expanded ? '点击收起' : '点击展开') : ''}
                    >
                      {hasDesc ? (
                        <>
                          <span className="mr-1 text-gray-500">{expanded ? '▼' : '▶'}</span>
                          {item.description}
                        </>
                      ) : '-'}
                    </td>
                    <td className="py-2 px-3 max-w-md text-xs">
                      {editing ? (
                        <div className="space-y-2">
                          <textarea
                            value={promptDraft}
                            onChange={(e) => setPromptDraft(e.target.value)}
                            maxLength={2000}
                            rows={4}
                            className="w-full bg-gray-800 border border-gray-600 rounded p-2 text-gray-200 focus:outline-none focus:border-emerald-400"
                            placeholder="为该商品单独配置额外提示词（可空），AI 生成回复时追加在系统提示词之后"
                          />
                          <div className="flex gap-2 items-center">
                            <button
                              onClick={() => savePrompt(item)}
                              disabled={saving}
                              className="px-3 py-1 bg-emerald-500 text-gray-900 font-semibold rounded text-xs hover:bg-emerald-400 disabled:opacity-50"
                            >
                              {saving ? '保存中...' : '保存'}
                            </button>
                            <button
                              onClick={cancelEditPrompt}
                              disabled={saving}
                              className="px-3 py-1 bg-gray-700 text-gray-200 rounded text-xs hover:bg-gray-600 disabled:opacity-50"
                            >
                              取消
                            </button>
                            <span className="text-gray-500">{promptDraft.length}/2000</span>
                          </div>
                          {promptErr && <div className="text-red-400 text-xs">{promptErr}</div>}
                        </div>
                      ) : (
                        <div
                          onClick={() => startEditPrompt(item)}
                          className="cursor-pointer select-none text-gray-300 hover:text-emerald-300"
                          title="点击编辑"
                        >
                          {hasPrompt ? (
                            <>
                              <span className="mr-1 text-gray-500">✎</span>
                              <span className="break-words">
                                {item.custom_prompt.length > 20
                                  ? `${item.custom_prompt.slice(0, 20)}...`
                                  : item.custom_prompt}
                              </span>
                            </>
                          ) : (
                            <span className="text-gray-500">未设置（点击配置）</span>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="py-2 px-3 text-xs text-gray-500 whitespace-nowrap">{item.fetched_at ? new Date(item.fetched_at).toLocaleString('zh-CN') : '-'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <span className="text-sm text-gray-400">第 {page}/{totalPages} 页</span>
          <div className="flex gap-2">
            <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}
              className="px-3 py-1 bg-gray-700 text-gray-200 rounded text-sm hover:bg-gray-600 disabled:opacity-50">
              上一页
            </button>
            <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
              className="px-3 py-1 bg-gray-700 text-gray-200 rounded text-sm hover:bg-gray-600 disabled:opacity-50">
              下一页
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: 前端构建检查**

```bash
cd frontend
npm run build
```

Expected: 构建成功无 TypeScript 错误。如有 `request.patch` 方法不存在的错误，检查 `frontend/src/utils/request.ts` 是否支持 PATCH（axios 默认就支持，应该没问题）。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/items/ItemsPage.tsx
git commit -m "feat(fe): ItemsPage 新增 AI 提示词列与内嵌编辑"
```

---

## Task 11: 端到端手工验证（spec §6 强制清单）

不写代码，只验证。逐项执行，全部通过才能交付。

- [ ] **Step 1: DB schema 应用成功**

```bash
docker exec -i xianyu-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" xianyu -e "DESCRIBE item_cache;"
```

Expected: 输出中包含 `custom_prompt | text | YES |  | NULL` 行。

- [ ] **Step 2: 空值零回归（最关键）**

操作：
1. 清空数据：`UPDATE item_cache SET custom_prompt = NULL;`
2. 重启 websocket 服务（确保新代码生效）
3. 给 websocket 服务的日志级别设为 DEBUG（loguru 默认就有 DEBUG 输出）
4. 从一个测试买家账号发一条消息给当前卖家某商品（任何文本，确保不命中跳过关键词）
5. 找日志里 `[xxxAgent] 完整提示词:` 那一段，复制 `messages[0].content`

预期：内容**不包含**`【针对本商品的特别说明】` 字样；末尾就是 `self.system_prompt` 的内容，或对于 PriceAgent，末尾是 `\n▲当前议价轮次：N`。

如果出现「特别说明」字样，回到 Task 4 检查 `if item_custom_prompt:` 门控逻辑。

- [ ] **Step 3: classify 不受影响**

在 Step 2 同一次消息处理中，日志里也会有 `[ClassifyAgent] 完整提示词:`（如果走到了大模型兜底分类的话）。验证它不包含 `【针对本商品的特别说明】`。

如果命中的是关键词/正则路由，可以发一条诸如 `"在不在"` 这种纯打招呼消息，迫使 router 走 ClassifyAgent 兜底。

- [ ] **Step 4: 配置后生效**

1. 浏览器打开商品配置页
2. 给某商品配 custom_prompt：`本商品仅支持顺丰发货，不议价`，保存
3. 再让测试买家发一条消息
4. 看 websocket 日志 `[xxxAgent] 完整提示词:`，确认末尾出现：
   ```
   【针对本商品的特别说明】本商品仅支持顺丰发货，不议价
   ```
5. （PriceAgent）确认 `▲当前议价轮次：N` 出现在「特别说明」**之后**

- [ ] **Step 5: 同步保留**

1. 当前商品的 custom_prompt 留着上一步配的值
2. 在商品配置页点"从闲鱼同步商品"
3. 同步完后查询 DB：
   ```sql
   SELECT item_id, custom_prompt FROM item_cache WHERE item_id = '<该商品ID>';
   ```
4. Expected: `custom_prompt` 字段值未变

- [ ] **Step 6: 权限隔离**

如果系统支持多卖家：
1. 用卖家 A 登录，记下卖家 B 名下某商品的 `item_id`
2. 用卖家 A 的 token：
   ```bash
   curl -X PATCH http://localhost:8000/api/items/<B的itemId> \
     -H "Authorization: Bearer $TOKEN_A" \
     -H "Content-Type: application/json" \
     -d '{"custom_prompt": "越权测试"}'
   ```
3. Expected: HTTP 404，body `{"detail":"商品不存在或无权限修改"}`

如果系统当前只支持单卖家，跳过此项并在最终交付备注里说明。

- [ ] **Step 7: 全部通过后做最终 commit**

如果验证过程中没有改动代码，无需 commit。如果改了，按修改的范围分别 commit 即可。

---

## 自检（Self-Review 结论）

✅ Spec §1 数据模型 → Task 1
✅ Spec §2 持久化保护 → Task 2
✅ Spec §3 后端 API → Task 3
✅ Spec §4 Bot 集成 → Tasks 4 / 6 / 7 / 8
✅ Spec §5 前端 → Tasks 9 / 10
✅ Spec §6 手工验证清单 → Task 11
✅ Spec §7 风险缓解 → 已通过 Task 4 严格门控、Task 2 不写覆盖、Task 6 ▲议价轮次保持末尾等措施落地

无 TBD / TODO / "类似 Task N"。所有签名 (`item_custom_prompt: Optional[str] = None`) 一致。`updateItemPrompt(itemId, customPrompt)` 在 Task 9 定义，Task 10 调用，参数顺序一致。
