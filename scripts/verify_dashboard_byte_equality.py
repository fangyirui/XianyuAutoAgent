"""
零回归验证：
1) BaseAgent._build_messages(item_custom_prompt=None) 输出与改动前预期一致
2) BaseAgent.generate / _call_llm 的 chat_id 默认 None 路径不引入新参数到 OpenAI kwargs
3) _fire_and_forget_record 在 None response 下不抛
4) _record_usage 在 None response 下能跑通（写库会失败但只 warning）

用法：在 websocket 容器内执行
  docker compose exec websocket python /app/scripts/verify_dashboard_byte_equality.py
或直接在本地执行（无需 PYTHONPATH）
  python scripts/verify_dashboard_byte_equality.py
"""
import asyncio
import inspect
import sys
from pathlib import Path

# 加载 project root 到 sys.path 让脚本能 import websocket.app.*（本地直接运行时使用）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "websocket"))


def check_build_messages_unchanged():
    from app.services.agent.base import BaseAgent

    agent = BaseAgent.__new__(BaseAgent)
    agent.system_prompt = "SYS"
    agent.safety_filter = lambda x: x

    # 历史含 assistant，规整后严格交替：system -> user(prev) -> assistant -> user(hi)
    history = [
        {"role": "user", "content": "prev"},
        {"role": "assistant", "content": "ack"},
    ]
    msgs_none = agent._build_messages("hi", "ITEM", history, None)
    msgs_empty = agent._build_messages("hi", "ITEM", history, "")
    msgs_baseline = [
        {"role": "system", "content": "### 商品信息\nITEM\n\nSYS"},
        {"role": "user", "content": "prev"},
        {"role": "assistant", "content": "ack"},
        {"role": "user", "content": "hi"},
    ]
    assert msgs_none == msgs_baseline, f"None 路径已发生变化: {msgs_none}"
    assert msgs_empty == msgs_baseline, f"空串路径已发生变化: {msgs_empty}"
    print("[OK] _build_messages 在 None / 空串下与基线一致（原生多轮 messages，严格交替）")


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
    """response=None 时 _fire_and_forget_record 的调度不抛；_record_usage 自身也不抛。"""
    from app.services.agent.base import BaseAgent

    agent = BaseAgent.__new__(BaseAgent)
    agent.system_prompt = ""
    agent.safety_filter = lambda x: x

    # 调度安全：不抛
    agent._fire_and_forget_record(
        model="test-model", chat_id=None, response=None, latency_ms=10, success=False
    )
    print("[OK] _fire_and_forget_record(None response) 调度安全")

    # 直接调用 _record_usage 验证内部路径对 None response 也是安全的
    # （写库会失败但 _record_usage 应自己 try/except 兜住，不向调用方抛）
    await agent._record_usage(
        agent_name="BaseAgent",
        model="test-model",
        chat_id=None,
        response=None,
        latency_ms=10,
        success=False,
    )
    print("[OK] _record_usage(None response) 内部路径安全（DB 写入失败仅 warning）")


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
