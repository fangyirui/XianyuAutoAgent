from .base import BaseAgent


class DefaultAgent(BaseAgent):
    async def _call_llm(self, messages, *args) -> str:
        return await super()._call_llm(messages, temperature=0.7)
