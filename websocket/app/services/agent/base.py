from typing import List, Dict
from openai import AsyncOpenAI
from common.core import settings


class BaseAgent:
    def __init__(self, client: AsyncOpenAI, system_prompt: str, safety_filter):
        self.client = client
        self.system_prompt = system_prompt
        self.safety_filter = safety_filter

    async def generate(self, user_msg: str, item_desc: str, context: str, bargain_count: int = 0) -> str:
        messages = self._build_messages(user_msg, item_desc, context)
        response = await self._call_llm(messages)
        return self.safety_filter(response)

    def _build_messages(self, user_msg: str, item_desc: str, context: str) -> List[Dict]:
        return [
            {"role": "system", "content": f"【商品信息】{item_desc}\n【你与客户对话历史】{context}\n{self.system_prompt}"},
            {"role": "user", "content": user_msg}
        ]

    async def _call_llm(self, messages: List[Dict], temperature: float = 0.4) -> str:
        response = await self.client.chat.completions.create(
            model=settings.MODEL_NAME,
            messages=messages,
            temperature=temperature,
            max_tokens=500,
            top_p=0.8
        )
        return response.choices[0].message.content or ""
