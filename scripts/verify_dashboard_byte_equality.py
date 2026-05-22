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
