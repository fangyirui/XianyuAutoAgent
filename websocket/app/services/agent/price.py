from typing import List, Dict
from .base import BaseAgent
from common.core import settings


class PriceAgent(BaseAgent):
    async def generate(self, user_msg: str, item_desc: str, context: str, bargain_count: int = 0) -> str:
        dynamic_temp = self._calc_temperature(bargain_count)
        messages = self._build_messages(user_msg, item_desc, context)
        messages[0]["content"] += f"\n▲当前议价轮次：{bargain_count}"

        response = await self.client.chat.completions.create(
            model=settings.MODEL_NAME,
            messages=messages,
            temperature=dynamic_temp,
            max_tokens=500,
            top_p=0.8
        )
        return self.safety_filter(response.choices[0].message.content)

    def _calc_temperature(self, bargain_count: int) -> float:
        return min(0.3 + bargain_count * 0.15, 0.9)
