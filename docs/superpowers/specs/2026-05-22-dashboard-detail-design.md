# 仪表盘详细信息 + 今日/累计区分 — 设计文档

日期：2026-05-22

## 1. 背景与目标

当前 `frontend/src/pages/dashboard/DashboardPage.tsx` 只展示三张卡片：WebSocket 连接状态、总会话数、总消息数。信息密度低，无法回答运营关心的问题：今天处理了多少咨询？AI 调用消耗多少 token？意图分布是什么？什么时候需要人工介入？

本次改造目标：

- 在仪表盘补充**对话/消息量、买家与意图、人工接管、AI 调用 & token 消耗**四类指标。
- 同一指标同时展示**今日**与**累计**两个口径，且在页面上以两个独立区块区分。
- 新增**意图分布**与 **Agent 调用分布**水平条形图（不引入图表库）。

## 2. 用户故事 / 场景

- 运营每天早上看仪表盘，能立刻判断"昨天到今早的咨询量、AI 是否在正常运转、是否有积压的人工接管"。
- 看到今日 token 消耗与累计 token 消耗，对成本心里有数。
- 看到今日 AI 错误率与平均响应时长，能感知模型/网关健康度。

## 3. 数据层改动

### 3.1 新表 `ai_call_log`

追加到 `init.sql`（首装会执行；存量部署需手工 `mysql < init.sql` 或在 PR 描述中说明执行该语句，因为只有 `IF NOT EXISTS`，重复执行安全）：

```sql
CREATE TABLE IF NOT EXISTS ai_call_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_name VARCHAR(32) NOT NULL,
    model VARCHAR(64) NOT NULL,
    chat_id VARCHAR(64) NULL,
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

字段说明：

| 字段 | 含义 |
| --- | --- |
| `agent_name` | `DefaultAgent` / `PriceAgent` / `TechAgent` / `ClassifyAgent` |
| `model` | `settings.MODEL_NAME`（实际请求所用模型） |
| `chat_id` | 关联的闲鱼会话 ID；分类阶段可能为 `NULL` |
| `prompt_tokens` / `completion_tokens` / `total_tokens` | 来自 `response.usage` |
| `latency_ms` | LLM 调用耗时（毫秒） |
| `success` | `1` 成功，`0` 失败（例如抛异常） |
| `created_at` | 入库时间，按 Asia/Shanghai 时区（容器统一 TZ） |

### 3.2 新 ORM 模型

新建 `common/models/ai_call_log.py`，按现有 `Conversation` / `Message` 风格用 `Column`。导出到 `common/models/__init__.py`。

### 3.3 Agent 端落库（零回归约束）

修改位置：

- `websocket/app/services/agent/base.py::BaseAgent._call_llm`
- `websocket/app/services/agent/price.py::PriceAgent._call_llm`
- `websocket/app/services/agent/tech.py::TechAgent._call_llm`
- `websocket/app/services/agent/classify.py`（如果它也调用 LLM）

抽取一个 `BaseAgent._record_usage(agent_name, model, chat_id, response, latency_ms, success)` 内部方法，三处子类复用。

落库实现：

```python
import time
import asyncio

async def _call_llm(self, messages, temperature=0.4, chat_id=None):
    t0 = time.perf_counter()
    success = True
    response = None
    try:
        response = await self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""
    except Exception:
        success = False
        raise
    finally:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        # fire-and-forget；写库失败仅 warning，绝不影响主流程
        asyncio.create_task(
            self._record_usage(
                agent_name=self.__class__.__name__,
                model=settings.MODEL_NAME,
                chat_id=chat_id,
                response=response,
                latency_ms=latency_ms,
                success=success,
            )
        )
```

`_record_usage` 内部用 `AsyncSessionLocal()` 起一个独立 session 插一条，`try/except` 包住，错误 `logger.warning`。

**`chat_id` 透传**：`bot.py` 现有调用链 `XianyuReplyBot.generate_reply(...)` → 各 agent `.generate(...)`。在 `BaseAgent.generate` 和 `_call_llm` 增加可选参数 `chat_id: Optional[str] = None`，默认 `None`。`bot.py` 调用时把当前 `chat_id` 透传下去。

**字节级零回归保证**：

- 所有新增参数默认 `None`；不传 / 传 `None` 时主流程与改动前路径完全一致。
- 落库走 `asyncio.create_task` fire-and-forget，不阻塞回复返回。
- DB 写入失败仅 `logger.warning`，不抛异常。

## 4. 后端 API 改动

文件：`backend-web/app/api/routes/logs.py`

把现有 `GET /logs/stats` 扩展成聚合接口。**保留旧字段** `total_conversations` / `total_messages` 做向后兼容（避免老版本前端构件加载时报错），同时新增完整结构。

### 4.1 响应结构

```json
{
  "realtime": {
    "manual_active": 3
  },
  "today": {
    "conversations": 23,
    "messages": 156,
    "ai_replies": 89,
    "user_messages": 67,
    "new_buyers": 18,
    "manual_takeover_triggered": 4,
    "ai_calls": 142,
    "tokens": 58932,
    "ai_errors": 3,
    "ai_error_rate": 0.021,
    "avg_latency_ms": 1842,
    "intent_distribution": [
      {"name": "price",    "count": 45},
      {"name": "tech",     "count": 32},
      {"name": "default",  "count": 28},
      {"name": "classify", "count": 13}
    ],
    "agent_distribution": [
      {"name": "DefaultAgent",  "count": 56},
      {"name": "PriceAgent",    "count": 45},
      {"name": "TechAgent",     "count": 32},
      {"name": "ClassifyAgent", "count": 8}
    ]
  },
  "cumulative": {
    "conversations": 1248,
    "messages": 8923,
    "buyers": 412,
    "bargain_sessions": 187,
    "ai_calls": 5621,
    "tokens": 2418773
  },
  "total_conversations": 1248,
  "total_messages": 8923
}
```

### 4.2 查询语义

时区：MySQL 容器 `TZ=Asia/Shanghai`，`CURDATE()` / `NOW()` 已是本地时间，可直接用 `WHERE created_at >= CURDATE()` 作为"今日"判定。

| 字段 | 查询 |
| --- | --- |
| `realtime.manual_active` | `SELECT COUNT(*) FROM conversations WHERE manual_mode = 1` |
| `today.conversations` | `COUNT(*) FROM conversations WHERE created_at >= CURDATE()` |
| `today.messages` | `COUNT(*) FROM messages WHERE created_at >= CURDATE()` |
| `today.ai_replies` | `COUNT(*) FROM messages WHERE role='assistant' AND created_at >= CURDATE()` |
| `today.user_messages` | `COUNT(*) FROM messages WHERE role='user' AND created_at >= CURDATE()` |
| `today.new_buyers` | `COUNT(DISTINCT user_id) FROM conversations WHERE created_at >= CURDATE()` |
| `today.manual_takeover_triggered` | `COUNT(*) FROM conversations WHERE manual_mode_at >= CURDATE()` |
| `today.ai_calls` | `COUNT(*) FROM ai_call_log WHERE created_at >= CURDATE()` |
| `today.tokens` | `COALESCE(SUM(total_tokens), 0) FROM ai_call_log WHERE created_at >= CURDATE()` |
| `today.ai_errors` | `COUNT(*) FROM ai_call_log WHERE success=0 AND created_at >= CURDATE()` |
| `today.ai_error_rate` | `ai_errors / ai_calls`（应用层算，`ai_calls=0` 时返回 `0`） |
| `today.avg_latency_ms` | `AVG(latency_ms) FROM ai_call_log WHERE success=1 AND created_at >= CURDATE()`，无数据返回 `0` |
| `today.intent_distribution` | `SELECT last_intent, COUNT(*) FROM conversations WHERE updated_at >= CURDATE() AND last_intent IS NOT NULL GROUP BY last_intent` |
| `today.agent_distribution` | `SELECT agent_name, COUNT(*) FROM ai_call_log WHERE created_at >= CURDATE() GROUP BY agent_name` |
| `cumulative.*` | 同上但去掉时间过滤 |

> 注：`today.intent_distribution` 用 `updated_at >= CURDATE()`，反映"今天有动静的会话最新意图分布"。这是近似值（同一会话今日多次切换意图只算最后一次），与 `last_intent` 字段的语义一致。

所有聚合用 `asyncio.gather` 并发，避免串行 N 次 round-trip。

## 5. 前端改动

### 5.1 文件

- `frontend/src/pages/dashboard/DashboardPage.tsx` — 重写
- `frontend/src/api/logs.ts` — `getStats()` 返回类型扩展

### 5.2 类型

```typescript
export interface DashboardStats {
  realtime: { manual_active: number }
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
    intent_distribution: { name: string; count: number }[]
    agent_distribution: { name: string; count: number }[]
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
```

### 5.3 布局

三大区块，自上而下：

**系统状态（实时）**
- WS 连接状态（沿用现有卡片，含重连按钮）
- 当前人工接管中（`realtime.manual_active`）

**今日概览**
- 卡片网格 4 列 × 多行（移动端塌成 1 列）：
  - 新增会话、新增消息、AI 回复、买家提问
  - 新增买家、触发接管、AI 调用、Token 消耗
  - 平均响应、AI 错误率
- 下方两个并列条形分布区：
  - 今日意图分布（`today.intent_distribution`）
  - 今日 Agent 调用拆分（`today.agent_distribution`）

**累计**
- 卡片网格：累计会话、累计消息、累计买家、议价会话、AI 调用、Token 消耗

### 5.4 内部组件

`<BarRow label count percent />` —— Tailwind 实现：

```tsx
<div className="flex items-center gap-2 text-sm">
  <span className="w-20 text-dark-400">{label}</span>
  <span className="w-12 text-right text-gray-50">{count}</span>
  <div className="flex-1 h-2 bg-dark-700 rounded">
    <div
      className="h-full bg-primary-500 rounded"
      style={{ width: `${percent}%` }}
    />
  </div>
  <span className="w-12 text-right text-dark-400">{percent.toFixed(0)}%</span>
</div>
```

数据为空时显示"暂无数据"占位。

### 5.5 数字格式化

`tokens` / 大数字加千分位（`toLocaleString()`）。`avg_latency_ms` 显示为 `1.8s` 或 `840ms`。`ai_error_rate` 显示为 `2.1%`，错误率 > 5% 时变红色。

## 6. 文件清单

新增：
- `common/models/ai_call_log.py`
- `docs/superpowers/specs/2026-05-22-dashboard-detail-design.md`（本文件）

修改：
- `init.sql` — 追加 `ai_call_log` 表
- `common/models/__init__.py` — 导出 `AiCallLog`
- `websocket/app/services/agent/base.py` — `_call_llm` 增加 `chat_id` 参数，新增 `_record_usage`
- `websocket/app/services/agent/price.py` — 同上
- `websocket/app/services/agent/tech.py` — 同上
- `websocket/app/services/agent/classify.py` — 同上
- `websocket/app/services/agent/bot.py` — 透传 `chat_id` 到各 agent
- `backend-web/app/api/routes/logs.py` — 重写 `GET /logs/stats`
- `frontend/src/pages/dashboard/DashboardPage.tsx` — 重写布局
- `frontend/src/api/logs.ts` — 扩展返回类型

## 7. 非目标 / 显式不做

- 不引入 recharts 等图表库（YAGNI；条形分布够用）。
- 不做时间序列折线图（本次只看今日 vs 累计快照）。
- 不做按卖家拆分（`sellers` 表已支持多卖家，但本仪表盘暂只展示全局）。
- 不做按 Tab 切换"今日/本周/累计"。
- 不做仪表盘数据导出。

## 8. 风险与回滚

| 风险 | 应对 |
| --- | --- |
| AI 调用埋点影响主流程性能 | `asyncio.create_task` fire-and-forget；写库失败仅 warning |
| 老版本前端拉新接口 | 保留 `total_conversations` / `total_messages` 字段向后兼容 |
| `ai_call_log` 表数据量增长 | 索引已加；后续可加定期归档（本次不做） |
| 存量部署没有 `ai_call_log` 表 | PR 描述里附 `mysql < init.sql` 指引；表用 `IF NOT EXISTS` 重复执行安全 |

回滚：删 `ai_call_log` 表 + 回退代码即可，无破坏性变更。

## 9. 验收标准

- [ ] 仪表盘三大区块正常渲染，移动端响应式
- [ ] 今日卡片在 0 点本地时间切换归零
- [ ] AI 调用产生后 `ai_call_log` 有记录，token 数与日志中 `response.usage` 一致
- [ ] 模拟 LLM 调用失败时，`ai_errors` 计数 +1 且主流程未受影响
- [ ] 旧版前端（如未刷新）调用 `/logs/stats` 仍能拿到 `total_conversations` / `total_messages`
- [ ] 不调用 `chat_id` 参数（默认 `None`）时，Agent 主流程字节级与改动前一致
