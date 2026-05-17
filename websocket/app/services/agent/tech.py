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
