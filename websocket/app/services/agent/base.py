import time
import asyncio
from typing import List, Dict, Optional
from openai import AsyncOpenAI
from loguru import logger
from common.core import settings


def resolve_top_p() -> Optional[float]:
    """解析 settings.MODEL_TOP_P。默认 "0.8" 与旧行为字节一致；
    空串 / "none" / "null"（不区分大小写、允许前后空白）或非数值时返回 None，调用方应不传 top_p。"""
    raw = (settings.MODEL_TOP_P or "").strip()
    if not raw or raw.lower() in ("none", "null"):
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"MODEL_TOP_P={settings.MODEL_TOP_P!r} 无法解析为浮点数，已禁用 top_p")
        return None


class BaseAgent:
    def __init__(self, client: AsyncOpenAI, system_prompt: str, safety_filter):
        self.client = client
        self.system_prompt = system_prompt
        self.safety_filter = safety_filter

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
        logger.debug(f"[{self.__class__.__name__}] 构建消息完成，system_prompt长度={len(self.system_prompt)}, 历史轮数={len(messages) - 2}, 商品额外提示词={'有' if item_custom_prompt else '无'}")
        response = await self._call_llm(messages, chat_id=chat_id)
        filtered = self.safety_filter(response)
        if filtered != response:
            logger.warning(f"[{self.__class__.__name__}] 安全过滤触发，原始回复: {response}")
        return filtered

    def _build_messages(
        self,
        user_msg: str,
        item_desc: str,
        context: List[Dict],
        item_custom_prompt: Optional[str] = None,
    ) -> List[Dict]:
        sys_content = f"### 商品信息\n{item_desc}\n\n{self.system_prompt}"
        # 严格门控：空串 / None / 任何 falsy 值都完全不追加
        if item_custom_prompt:
            sys_content += f"\n\n### 针对本商品的特别说明\n{item_custom_prompt}"

        # 历史规整成严格交替的 user/assistant 轮次，杜绝"连续同角色/中间 system"被
        # 严格网关（如部分版本的通义千问兼容接口）拒绝：
        #   1) 买家可连发多条 -> 历史存多行连续 user；
        #   2) 平台事件（[买家拍下了商品] 等）以 system 行落库，归到 user 侧（本就是买家侧动作）；
        #   3) AI 回复里的分隔符占位符还原成换行。
        # 连续同角色合并为一条（内容以换行拼接），当前买家消息并入末尾 user 轮次。
        turns: List[Dict] = []

        def _push(role: str, content: str):
            if turns and turns[-1]["role"] == role:
                turns[-1]["content"] += "\n" + content
            else:
                turns.append({"role": role, "content": content})

        for m in context or []:
            role = m.get("role")
            if role not in ("user", "assistant", "system"):
                continue
            content = (m.get("content") or "").replace("{$分隔符}", "\n")
            _push("assistant" if role == "assistant" else "user", content)
        _push("user", user_msg)

        return [{"role": "system", "content": sys_content}, *turns]

    async def _call_llm(
        self,
        messages: List[Dict],
        temperature: float = 0.4,
        chat_id: Optional[str] = None,
    ) -> str:
        logger.info(f"[{self.__class__.__name__}] LLM请求 | model={settings.MODEL_NAME}, temp={temperature}")
        logger.debug(f"[{self.__class__.__name__}] 完整提示词:\n" + "\n".join(f"[{m['role']}] {m['content']}" for m in messages))
        kwargs = dict(
            model=settings.MODEL_NAME,
            messages=messages,
            temperature=temperature,
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
            result = response.choices[0].message.content or ""
            logger.info(f"[{self.__class__.__name__}] LLM响应: {result}")
            logger.debug(f"[{self.__class__.__name__}] token用量: {response.usage}")
            return result
        except Exception as e:
            success = False
            logger.error(f"[{self.__class__.__name__}] LLM调用失败: {e}")
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

    def _fire_and_forget_record(
        self,
        model: str,
        chat_id: Optional[str],
        response,
        latency_ms: int,
        success: bool,
    ) -> None:
        """调度 _record_usage 为后台任务；任何调度错误不抛、仅 warning，绝不影响主流程。"""
        try:
            asyncio.create_task(
                self._record_usage(
                    agent_name=self.__class__.__name__,
                    model=model,
                    chat_id=chat_id,
                    response=response,
                    latency_ms=latency_ms,
                    success=success,
                )
            )
        except Exception as e:
            logger.warning(f"[{self.__class__.__name__}] 落库任务调度失败: {e}")

    async def _record_usage(
        self,
        agent_name: str,
        model: str,
        chat_id: Optional[str],
        response,
        latency_ms: int,
        success: bool,
    ) -> None:
        """写入 ai_call_log。失败仅 warning。"""
        try:
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            if response is not None and getattr(response, "usage", None) is not None:
                usage = response.usage
                prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                total_tokens = int(getattr(usage, "total_tokens", 0) or 0)

            from common.db import AsyncSessionLocal
            from common.models import AiCallLog
            async with AsyncSessionLocal() as db:
                db.add(AiCallLog(
                    agent_name=agent_name,
                    model=model,
                    chat_id=chat_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency_ms,
                    success=success,
                ))
                await db.commit()
        except Exception as e:
            logger.warning(f"[{agent_name}] ai_call_log 写库失败: {e}")
