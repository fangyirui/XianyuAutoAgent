"""验证 BaseAgent._build_messages 生成 API 原生多轮 messages 的结构与不变量。

核心不变量：
1. messages[0] 为 system，内容 = "### 商品信息\n{item_desc}\n\n{system_prompt}"；
   空 / None custom_prompt 一个字符都不追加，非空才在末尾追加
   "\n\n### 针对本商品的特别说明\n{prompt}"。
2. 历史规整成严格交替的 user/assistant 轮次：连续同角色合并（换行拼接）、平台事件
   （system 行）归到 user 侧、分隔符占位符 {$分隔符} 还原成换行。
3. messages[-1] 为 user，且其内容以当前消息结尾；system 之后无连续同角色。

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


def expected_system(item_desc, system_prompt):
    """1:1 复刻 base.py 当前 system 消息拼接逻辑（无 custom_prompt 时）"""
    return f"### 商品信息\n{item_desc}\n\n{system_prompt}"


def assert_strict_alternation(msgs):
    body = [m["role"] for m in msgs[1:]]  # 跳过首位 system
    assert all(body[i] != body[i + 1] for i in range(len(body) - 1)), f"存在连续同角色: {body}"
    assert msgs[0]["role"] == "system" and msgs[-1]["role"] == "user", f"首/尾角色异常: {[m['role'] for m in msgs]}"


def main():
    # 构造一个不调用 LLM 的 BaseAgent 实例
    agent = BaseAgent(client=None, system_prompt="你是闲鱼客服，请礼貌回答。", safety_filter=lambda x: x)
    item_desc = "商品标题：测试\n商品描述：成色95新\n商品价格：¥38.0"
    # 买家连发2条 -> assistant（含分隔符） -> 平台事件（system）
    context = [
        {"role": "user", "content": "在吗"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "您好~欢迎光临{$分隔符}有什么可以帮您"},
        {"role": "system", "content": "[买家拍下了商品]"},
    ]
    user_msg = "现在能发吗"

    expected_sys = expected_system(item_desc, agent.system_prompt)
    # 规整预期：连发2条 user 合并；assistant 分隔符还原；平台事件归 user 侧并与当前消息合并
    expected_msgs = [
        {"role": "system", "content": expected_sys},
        {"role": "user", "content": "在吗\n你好"},
        {"role": "assistant", "content": "您好~欢迎光临\n有什么可以帮您"},
        {"role": "user", "content": "[买家拍下了商品]\n现在能发吗"},
    ]

    # Case 1: item_custom_prompt=None —— 结构与内容全量校验
    msgs = agent._build_messages(user_msg, item_desc, context, item_custom_prompt=None)
    assert msgs == expected_msgs, f"[FAIL] None case\n--- expected ---\n{expected_msgs!r}\n--- actual ---\n{msgs!r}"
    assert_strict_alternation(msgs)
    print("[PASS] None case 规整后严格交替、内容一致")

    # Case 2: item_custom_prompt="" —— system 不追加任何字符
    msgs = agent._build_messages(user_msg, item_desc, context, item_custom_prompt="")
    assert msgs[0]["content"] == expected_sys, f"[FAIL] empty-string case\n{msgs[0]['content']!r}"
    print("[PASS] '' case system 零追加")

    # Case 3: 不传参（默认值 None）
    msgs = agent._build_messages(user_msg, item_desc, context)
    assert msgs[0]["content"] == expected_sys, f"[FAIL] default-kwarg case\n{msgs[0]['content']!r}"
    print("[PASS] 默认参数（缺省）case system 零追加")

    # Case 4: 有值时正确追加到 system 末尾
    msgs = agent._build_messages(user_msg, item_desc, context, item_custom_prompt="本商品仅顺丰发货")
    expected_with = expected_sys + "\n\n### 针对本商品的特别说明\n本商品仅顺丰发货"
    assert msgs[0]["content"] == expected_with, f"[FAIL] with-prompt case\n--- expected ---\n{expected_with!r}\n--- actual ---\n{msgs[0]['content']!r}"
    print("[PASS] 有值 case system 追加正确")

    # Case 5: 空历史 —— 仅 system + 当前 user
    msgs = agent._build_messages(user_msg, item_desc, [], item_custom_prompt=None)
    assert msgs == [{"role": "system", "content": expected_sys}, {"role": "user", "content": user_msg}], f"[FAIL] empty-history\n{msgs!r}"
    print("[PASS] 空历史 case 仅 system + user")

    print("\n全部通过：多轮 messages 结构、严格交替与门控均有效。")


if __name__ == "__main__":
    main()

