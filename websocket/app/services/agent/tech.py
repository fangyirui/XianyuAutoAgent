from .base import BaseAgent
from common.core import settings


class TechAgent(BaseAgent):
    async def generate(self, user_msg: str, item_desc: str, context: str, bargain_count: int = 0) -> str:
        messages = self._build_messages(user_msg, item_desc, context)
        response = await self.client.chat.completions.create(
            model=settings.MODEL_NAME,
            messages=messages,
            temperature=0.4,
            max_tokens=500,
            top_p=0.8,
            extra_body={"enable_search": True}
        )
        return self.safety_filter(response.choices[0].message.content)
