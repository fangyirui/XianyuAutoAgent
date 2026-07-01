import re
import json
from typing import List, Dict
from pathlib import Path
from openai import AsyncOpenAI
from loguru import logger
from common.core import settings
from .router import IntentRouter
from .classify import ClassifyAgent
from .price import PriceAgent
from .tech import TechAgent
from .default import DefaultAgent


class XianyuReplyBot:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.API_KEY,
            base_url=settings.MODEL_BASE_URL,
        )
        self._init_system_prompts()
        self._init_agents()
        self.router = IntentRouter(self.agents["classify"])
        self.last_intent = None

    def _init_agents(self):
        self.agents = {
            "classify": ClassifyAgent(self.client, self.classify_prompt, self._safe_filter),
            "price": PriceAgent(self.client, self.price_prompt, self._safe_filter),
            "tech": TechAgent(self.client, self.tech_prompt, self._safe_filter),
            "default": DefaultAgent(self.client, self.default_prompt, self._safe_filter),
        }

    def _init_system_prompts(self):
        self.classify_prompt = ""
        self.price_prompt = ""
        self.tech_prompt = ""
        self.default_prompt = ""

    def _load_file_prompts(self) -> dict:
        """从本地文件加载提示词作为默认值（仅用于DB初始化种子）"""
        prompt_dir = Path(__file__).parent.parent.parent.parent / "prompts"

        def load_prompt(name: str) -> str:
            target = prompt_dir / f"{name}.txt"
            if target.exists():
                return target.read_text(encoding="utf-8")
            fallback = prompt_dir / f"{name}_example.txt"
            if fallback.exists():
                return fallback.read_text(encoding="utf-8")
            return ""

        prompt_json = prompt_dir / "prompt.json"
        if prompt_json.exists():
            try:
                data = json.loads(prompt_json.read_text(encoding="utf-8"))
                return {
                    "classify_prompt": data.get("classify", ""),
                    "price_prompt": data.get("price", ""),
                    "tech_prompt": data.get("tech", ""),
                    "default_prompt": data.get("default", ""),
                }
            except Exception:
                pass

        return {
            "classify_prompt": load_prompt("classify_prompt"),
            "price_prompt": load_prompt("price_prompt"),
            "tech_prompt": load_prompt("tech_prompt"),
            "default_prompt": load_prompt("default_prompt"),
        }

    async def load_prompts_from_db(self):
        try:
            from common.db import AsyncSessionLocal
            from sqlalchemy import select
            from common.models import SystemConfig

            prompt_keys = ["prompt:classify_prompt", "prompt:price_prompt", "prompt:tech_prompt", "prompt:default_prompt"]
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(SystemConfig).where(SystemConfig.key_name.in_(prompt_keys)))
                db_prompts = {r.key_name: r.value for r in result.scalars()}

            # 如果DB中缺少提示词，从文件加载默认值并写入DB
            missing_keys = [k for k in prompt_keys if not db_prompts.get(k)]
            if missing_keys:
                file_prompts = self._load_file_prompts()
                async with AsyncSessionLocal() as db:
                    for key in missing_keys:
                        name = key.replace("prompt:", "")
                        value = file_prompts.get(name, "")
                        if value:
                            db.add(SystemConfig(key_name=key, value=value))
                            db_prompts[key] = value
                    await db.commit()
                logger.info(f"已将 {len(missing_keys)} 个默认提示词写入数据库")

            # 从DB加载所有提示词
            self.classify_prompt = db_prompts.get("prompt:classify_prompt", "")
            self.price_prompt = db_prompts.get("prompt:price_prompt", "")
            self.tech_prompt = db_prompts.get("prompt:tech_prompt", "")
            self.default_prompt = db_prompts.get("prompt:default_prompt", "")

            self._init_agents()
            self.router = IntentRouter(self.agents["classify"])
            logger.info("从数据库加载提示词完成")
            logger.debug(f"classify_prompt ({len(self.classify_prompt)}字): {self.classify_prompt[:200]}...")
            logger.debug(f"price_prompt ({len(self.price_prompt)}字): {self.price_prompt[:200]}...")
            logger.debug(f"tech_prompt ({len(self.tech_prompt)}字): {self.tech_prompt[:200]}...")
            logger.debug(f"default_prompt ({len(self.default_prompt)}字): {self.default_prompt[:200]}...")
        except Exception as e:
            logger.warning(f"从数据库加载提示词失败，回退到文件: {e}")
            file_prompts = self._load_file_prompts()
            self.classify_prompt = file_prompts["classify_prompt"]
            self.price_prompt = file_prompts["price_prompt"]
            self.tech_prompt = file_prompts["tech_prompt"]
            self.default_prompt = file_prompts["default_prompt"]
            self._init_agents()
            self.router = IntentRouter(self.agents["classify"])

    def _safe_filter(self, text: str) -> str:
        if not text:
            return "-"
        blocked = ["微信", "QQ", "支付宝", "银行卡", "线下"]
        return "[安全提醒]请通过平台沟通" if any(p in text for p in blocked) else text

    async def generate_reply(
        self,
        user_msg: str,
        item_desc: str,
        context: List[Dict],
        item_custom_prompt: str | None = None,
        chat_id: str | None = None,
    ) -> tuple[str, str]:
        """返回 (reply, intent)。

        历史上意图存在 self.last_intent，但多 worker 并发消费时该共享字段会跨任务串改，
        故改为随返回值带出，调用方不要再读 self.last_intent。self.last_intent 仍同步写入
        以兼容潜在的其它读取点，但不应作为并发安全的事实来源。
        """
        logger.info(f"[Bot] 开始处理 | 用户消息: {user_msg}")
        logger.debug(f"[Bot] 商品信息: {item_desc}")
        logger.debug(f"[Bot] 上下文条数: {len(context)}, 商品额外提示词={'有' if item_custom_prompt else '无'}")

        # 历史对话作为原始列表直接下传，由 BaseAgent._build_messages 摊开成 API 原生多轮 messages。
        # IntentRouter / ClassifyAgent 不接收 item_custom_prompt（避免污染意图判断）
        detected_intent = await self.router.detect(user_msg, item_desc, context, chat_id=chat_id)

        if detected_intent == "no_reply":
            self.last_intent = "no_reply"
            logger.info("[Bot] 意图=no_reply，跳过回复")
            return "-", "no_reply"

        internal_intents = {"classify"}
        if detected_intent in self.agents and detected_intent not in internal_intents:
            agent = self.agents[detected_intent]
            intent = detected_intent
        else:
            agent = self.agents["default"]
            intent = "default"
        self.last_intent = intent

        logger.info(f"[Bot] 最终意图={intent}，使用 {agent.__class__.__name__}")

        bargain_count = self._extract_bargain_count(context)
        reply = await agent.generate(
            user_msg=user_msg,
            item_desc=item_desc,
            context=context,
            bargain_count=bargain_count,
            item_custom_prompt=item_custom_prompt,
            chat_id=chat_id,
        )
        logger.info(f"[Bot] 最终回复: {reply}")
        return reply, intent

    def _extract_bargain_count(self, context: List[Dict]) -> int:
        for msg in context:
            if msg["role"] == "system" and "议价次数" in msg["content"]:
                match = re.search(r"议价次数[:：]\s*(\d+)", msg["content"])
                if match:
                    return int(match.group(1))
        return 0

