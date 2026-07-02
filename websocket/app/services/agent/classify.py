from typing import List, Dict, Optional
from .base import BaseAgent


class ClassifyAgent(BaseAgent):
    """意图分类器。

    与生成回复的 price/tech/default 不同，它只需吐一个类别名。若沿用 BaseAgent 把
    历史摊成原生多轮 messages，历史里的 assistant 轮次是真实客服答复而非分类标签，
    会形成"续写=继续当客服"的引导，与 system 里"仅返回类别名"的指令相互拉扯，且每次
    分类都要白付一遍全量历史 token。

    因此这里覆写 _build_messages：历史拍平成一段文本塞进 system 当**参考资料**（帮助
    判断当前消息意图），消息列表末尾只留当前待分类消息一条 user。router 的 LLM 兜底
    走的就是本 agent，故整条分类链路都用这套轻量入参；reply agents 不受影响。
    """

    def _build_messages(
        self,
        user_msg: str,
        item_desc: str,
        context: List[Dict],
        item_custom_prompt: Optional[str] = None,
    ) -> List[Dict]:
        # item_custom_prompt 分类链路本就不接收（见 bot.py，避免污染意图判断），此处忽略。
        sys_content = f"### 商品信息\n{item_desc}\n\n{self.system_prompt}"
        history = "\n".join(
            f"{m.get('role')}: {(m.get('content') or '').replace('{$分隔符}', ' ')}"
            for m in (context or [])
            if m.get("role") in ("user", "assistant", "system")
        )
        if history:
            sys_content += (
                "\n\n### 对话历史（仅供参考，用于判断当前消息意图；不要模仿其语气去回复）\n"
                + history
            )
        return [
            {"role": "system", "content": sys_content},
            {"role": "user", "content": user_msg},
        ]
