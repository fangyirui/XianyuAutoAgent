from typing import List, Dict
from openai import AsyncOpenAI
from loguru import logger
from common.core import settings


class BaseAgent:
    def __init__(self, client: AsyncOpenAI, system_prompt: str, safety_filter):
        self.client = client
        self.system_prompt = system_prompt
        self.safety_filter = safety_filter

    async def generate(self, user_msg: str, item_desc: str, context: str, bargain_count: int = 0) -> str:
        messages = self._build_messages(user_msg, item_desc, context)
        logger.debug(f"[{self.__class__.__name__}] 构建消息完成，system_prompt长度={len(self.system_prompt)}")
        response = await self._call_llm(messages)
        filtered = self.safety_filter(response)
        if filtered != response:
            logger.warning(f"[{self.__class__.__name__}] 安全过滤触发，原始回复: {response}")
        return filtered

    def _build_messages(self, user_msg: str, item_desc: str, context: str) -> List[Dict]:
        return [
            {"role": "system", "content": f"【商品信息】{item_desc}\n【你与客户对话历史】{context}\n{self.system_prompt}"},
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
