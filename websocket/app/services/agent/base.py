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
        kwargs = dict(
            model=settings.MODEL_NAME,
            messages=messages,
            temperature=temperature,
            max_tokens=500,
        )
        top_p = resolve_top_p()
        if top_p is not None:
            kwargs["top_p"] = top_p
        try:
            response = await self.client.chat.completions.create(**kwargs)
            result = response.choices[0].message.content or ""
            logger.info(f"[{self.__class__.__name__}] LLM响应: {result}")
            logger.debug(f"[{self.__class__.__name__}] token用量: {response.usage}")
            return result
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] LLM调用失败: {e}")
            raise
