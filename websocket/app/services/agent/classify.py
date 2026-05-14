from .base import BaseAgent


class ClassifyAgent(BaseAgent):
    async def generate(self, **kwargs) -> str:
        return await super().generate(**kwargs)
