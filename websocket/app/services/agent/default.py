from typing import Optional
from .base import BaseAgent


class DefaultAgent(BaseAgent):
    async def _call_llm(self, messages, temperature: float = 0.7, chat_id: Optional[str] = None) -> str:
        return await super()._call_llm(messages, temperature=temperature, chat_id=chat_id)
