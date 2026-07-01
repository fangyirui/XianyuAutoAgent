import time
from typing import Optional, List, Dict
from loguru import logger
from .base import BaseAgent, resolve_top_p
from common.core import settings


class PriceAgent(BaseAgent):
    async def generate(
        self,
        user_msg: str,
        item_desc: str,
        context: List[Dict],
        bargain_count: int = 0,
        item_custom_prompt: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> str:
        dynamic_temp = self._calc_temperature(bargain_count)
        messages = self._build_messages(user_msg, item_desc, context, item_custom_prompt)
        # ▲议价轮次 永远追加到 system content 末尾（在 custom_prompt 之后），与原行为保持一致
        messages[0]["content"] += f"\n▲当前议价轮次：{bargain_count}"

        logger.info(f"[PriceAgent] LLM请求 | model={settings.MODEL_NAME}, temp={dynamic_temp}, 议价轮次={bargain_count}")
        logger.debug(f"[PriceAgent] 完整提示词:\n" + "\n".join(f"[{m['role']}] {m['content']}" for m in messages))

        kwargs = dict(
            model=settings.MODEL_NAME,
            messages=messages,
            temperature=dynamic_temp,
            max_tokens=500,
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
            logger.info(f"[PriceAgent] LLM响应: {result}")
            logger.debug(f"[PriceAgent] token用量: {response.usage}")
            return result
        except Exception as e:
            success = False
            logger.error(f"[PriceAgent] LLM调用失败: {e}")
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

    def _calc_temperature(self, bargain_count: int) -> float:
        return min(0.3 + bargain_count * 0.15, 0.9)
