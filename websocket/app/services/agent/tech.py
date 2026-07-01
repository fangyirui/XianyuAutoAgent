import time
from typing import Optional, List, Dict
from loguru import logger
from .base import BaseAgent, resolve_top_p
from common.core import settings


class TechAgent(BaseAgent):
    async def generate(
        self,
        user_msg: str,
        item_desc: str,
        context: List[Dict],
        bargain_count: int = 0,
        item_custom_prompt: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> str:
        messages = self._build_messages(user_msg, item_desc, context, item_custom_prompt)

        logger.info(f"[TechAgent] LLM请求 | model={settings.MODEL_NAME}, enable_search=True")
        logger.debug(f"[TechAgent] 完整提示词:\n" + "\n".join(f"[{m['role']}] {m['content']}" for m in messages))

        kwargs = dict(
            model=settings.MODEL_NAME,
            messages=messages,
            temperature=0.4,
            max_tokens=500,
            extra_body={"enable_search": True},
        )
        top_p = resolve_top_p()
        if top_p is not None:
            kwargs["top_p"] = top_p

        t0 = time.perf_counter()
        success = True
        response = None
        try:
            response = await self.client.chat.completions.create(**kwargs)
            result = self.safety_filter(response.choices[0].message.content)
            logger.info(f"[TechAgent] LLM响应: {result}")
            logger.debug(f"[TechAgent] token用量: {response.usage}")
            return result
        except Exception as e:
            success = False
            logger.error(f"[TechAgent] LLM调用失败: {e}")
            raise
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            self._fire_and_forget_record(
                model=str(kwargs.get("model", "")),
                chat_id=chat_id,
                response=response,
                latency_ms=latency_ms,
                success=success,
            )
