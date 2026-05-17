# 商品级额外 AI 提示词 设计文档

日期: 2026-05-17

## 背景

目前 4 个 Agent（classify / price / tech / default）共用从 `system_config` 表加载的全局系统提示词。卖家有时希望对**单个商品**追加特殊说明（例如"此商品瑕疵介意慎拍"、"成色 95 新"、"只支持顺丰"等），让 AI 回复时携带这些上下文。

## 目标

- 在「商品配置」页（`ItemsPage.tsx`）为每件商品提供一个独立、可选的 `custom_prompt` 字段。
- 该提示词在生成回复时**作为系统提示词的补充**注入到 price / tech / default Agent；**不**注入 classify（避免干扰意图识别）。
- **核心约束：主流程零回归。** `custom_prompt` 为空（NULL / "" / 未设置）时，所有现网行为与改动前完全一致——拼接出的 system 消息字节级相同，调用链完全相同。

## 非目标

- 不引入对提示词的版本/审核流程
- 不支持模板变量（如 `{title}` 自动替换），就是纯文本
- 不在分类 Agent 中使用

---

## 1. 数据模型

`item_cache` 表新增字段：

```sql
ALTER TABLE item_cache ADD COLUMN custom_prompt TEXT NULL COMMENT '该商品的额外AI提示词';
```

- `init.sql` 同步加上该列定义
- `common/models/item_cache.py` 模型新增 `custom_prompt = Column(Text, nullable=True)`
- 字段**必须** nullable，老数据自动落到 NULL → "不拼接" 分支

## 2. 数据持久化保护

`websocket/app/websocket/manager.py` 的 `_save_item_cache` 和 `_save_items_from_card_data` 在更新已有 `item_cache` 行时，**不能覆盖** `custom_prompt` 字段。同步闲鱼商品列表只更新平台返回的字段（title/price/description/raw_json/fetched_at），用户手动配置的提示词保留。

## 3. 后端 API

文件：`backend-web/app/api/routes/items.py`

- `GET /items`：响应每条 item 加 `custom_prompt: string` 字段（NULL 序列化为空串）
- 新增 `PATCH /items/{item_id}`：
  - 请求体：`{ "custom_prompt": "..." }`（字符串，允许空）
  - 鉴权：`get_current_user`
  - 权限校验：只能修改 `seller_id` 在当前活跃卖家列表里的商品
  - 响应：`{ "ok": true }` 或 404

前端 API：`frontend/src/api/items.ts` 新增 `updateItemPrompt(itemId: string, customPrompt: string)`。

## 4. Bot 集成

### 4.1 manager.py
`_get_item_cache(item_id)` 当前返回 `raw_json` 解析后的 dict。增加同表 `custom_prompt` 字段读取，作为独立值返回（不混入 item_info dict，避免污染发给 LLM 的 item_desc 结构）。

`handle_message` 里调用：
```python
item_info, custom_prompt = await self._get_item_cache_with_prompt(item_id)
# ... existing logic ...
bot_reply = await self.bot.generate_reply(
    send_message, item_desc, context,
    item_custom_prompt=custom_prompt,   # 新增 kwarg
)
```

### 4.2 bot.py
`XianyuReplyBot.generate_reply` 签名加可选 kwarg：
```python
async def generate_reply(self, user_msg, item_desc, context, item_custom_prompt: str | None = None) -> str:
```
路由分类（`self.router.detect(...)`）**不**传 `item_custom_prompt`。最终选中 agent 是 price/tech/default 时把它透传过去；选中 default fallback 时也透传。

### 4.3 base.py / agents
`BaseAgent.generate` 签名加可选 kwarg：
```python
async def generate(self, user_msg, item_desc, context, bargain_count=0, item_custom_prompt: str | None = None) -> str:
```

`_build_messages` 拼接逻辑（**这是零回归的关键**）：
```python
def _build_messages(self, user_msg, item_desc, context, item_custom_prompt=None):
    sys_content = f"【商品信息】{item_desc}\n【你与客户对话历史】{context}\n{self.system_prompt}"
    if item_custom_prompt:                                  # 空串 / None 跳过整块
        sys_content += f"\n【针对本商品的特别说明】{item_custom_prompt}"
    return [
        {"role": "system", "content": sys_content},
        {"role": "user", "content": user_msg},
    ]
```

**注意：** `if item_custom_prompt:` 这一行决定行为——空值时**完全不追加任何字符**（含换行、标题），保证旧字符串字节级不变。

`ClassifyAgent` 不接收 `item_custom_prompt`（即使签名兼容也不传），由 `IntentRouter.detect` 控制。

`PriceAgent.generate` 自己重写过，要在它的 `_build_messages(...)` 调用处同步把 `item_custom_prompt` 透传过去，并保留它对 system content 追加 `▲当前议价轮次：{n}` 的逻辑（放在 custom_prompt 之后还是之前需要一致）。**统一规则：先追加 custom_prompt，再追加议价轮次**，保证 PriceAgent 的"轮次"始终是 system content 的最后一段（与现状一致）。

### 4.4 router.py
意图分类调用链不变，**不**修改 `IntentRouter.detect` 签名。

## 5. 前端

文件：`frontend/src/pages/items/ItemsPage.tsx`

- 表格新增列 "AI 提示词"，紧跟在 "描述" 列之后、"缓存时间" 列之前
- 默认显示：
  - 有内容时：`▶ {custom_prompt[:20]}...`（前 20 字）
  - 无内容时：灰色 "未设置"
- 点击展开：变为内嵌 `<textarea>`（高度 4 行，maxLength=2000）+ "保存" 和 "取消" 按钮
- 保存：调 `PATCH /items/{item_id}`，成功后更新本地 state 对应行
- 取消：恢复原值，关闭展开
- 编辑过程不影响其他行展开/折叠的描述列状态

## 6. 测试 & 验证（强制项）

实现完成后**必须**逐项验证：

1. **DB schema 应用成功**：新启动 / 现有库都能识别 `custom_prompt` 列
2. **空值零回归**：清空数据库中所有 `custom_prompt`，发一条买家消息，对比改动前后传给 LLM 的 messages 数组（开 DEBUG 日志看 `_call_llm` 打印），要求 `messages[0]["content"]` 字节级相同
3. **classify 不受影响**：意图分类的 prompt 中**不**出现「针对本商品的特别说明」
4. **配置后生效**：通过页面给某商品配 custom_prompt，发一条该商品的买家消息，日志里 system content 末尾包含该提示词
5. **同步保留**：在某商品配 custom_prompt 后，触发"从闲鱼同步商品"，再查 DB，该字段值保留未被覆盖
6. **权限隔离**：用户 A 不能 PATCH 卖家 B 的商品（即使知道 item_id）

## 7. 风险 & 缓解

| 风险 | 缓解 |
|---|---|
| custom_prompt 拼接位置导致 system prompt 变化触发回归 | 用 `if item_custom_prompt:` 严格门控；测试项 #2 强制验证字节级一致 |
| 同步商品时覆盖用户配置 | 测试项 #5 强制验证；代码中显式不写 `custom_prompt` 列 |
| 议价 Agent 的 `▲议价轮次` 顺序问题 | 设计文档统一：custom_prompt 在前，bargain 提示在后 |
| 长 prompt 触发 LLM token 超限 | 前端 maxLength 2000；后端不硬限，靠 LLM max_tokens 自然处理 |
| 字段 NULL 在 Pydantic / ORM 序列化为 `null` 而非空串导致前端校验问题 | API 层 `custom_prompt or ""` 显式转空串再返回 |

## 8. 任务粒度（供 writing-plans 参考）

1. DB schema：`init.sql` + 模型字段
2. 后端：GET 返回字段 + PATCH 路由 + 权限校验
3. WebSocket 服务：`_get_item_cache` 读 custom_prompt + `_save_item_cache` 不覆盖
4. Bot/Agent：bot.generate_reply / base / price / tech / default 透传链路（带零回归门控）
5. 前端 API：`items.ts` 新增方法
6. 前端 UI：`ItemsPage.tsx` 表格列 + 展开编辑
7. 手工验证清单 6 项
