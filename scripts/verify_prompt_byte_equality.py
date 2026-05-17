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
