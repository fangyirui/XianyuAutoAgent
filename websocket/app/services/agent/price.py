from typing import List, Dict
from loguru import logger
from .base import BaseAgent
from common.core import settings


class PriceAgent(BaseAgent):
    async def generate(self, user_msg: str, item_desc: str, context: str, bargain_count: int = 0) -> str:
        dynamic_temp = self._calc_temperature(bargain_count)
        messages = self._build_messages(user_msg, item_desc, context)
        messages[0]["content"] += f"\n▲当前议价轮次：{bargain_count}"

        logger.info(f"[PriceAgent] LLM请求 | model={settings.MODEL_NAME}, temp={dynamic_temp}, 议价轮次={bargain_count}")
        logger.debug(f"[PriceAgent] 完整提示词:\n{messages[0]['content']}")
        logger.debug(f"[PriceAgent] 用户输入: {messages[-1]['content']}")

        try:
            response = await self.client.chat.completions.create(
                model=settings.MODEL_NAME,
                messages=messages,
                temperature=dynamic_temp,
                max_tokens=500,
                top_p=0.8
            )
            result = self.safety_filter(response.choices[0].message.content)
            logger.info(f"[PriceAgent] LLM响应: {result}")
            logger.debug(f"[PriceAgent] token用量: {response.usage}")
            return result
        except Exception as e:
            logger.error(f"[PriceAgent] LLM调用失败: {e}")
            raise

    def _calc_temperature(self, bargain_count: int) -> float:
        return min(0.3 + bargain_count * 0.15, 0.9)
