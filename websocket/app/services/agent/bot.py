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
        prompt_dir = Path(__file__).parent.parent.parent.parent / "prompts"

        def load_prompt(name: str) -> str:
            target = prompt_dir / f"{name}.txt"
            if target.exists():
                return target.read_text(encoding="utf-8")
            fallback = prompt_dir / f"{name}_example.txt"
            if fallback.exists():
                return fallback.read_text(encoding="utf-8")
            return ""

        # Try prompt.json first (has all 4 prompts in one file)
        prompt_json = prompt_dir / "prompt.json"
        if prompt_json.exists():
            try:
                data = json.loads(prompt_json.read_text(encoding="utf-8"))
                self.classify_prompt = data.get("classify", "")
                self.price_prompt = data.get("price", "")
                self.tech_prompt = data.get("tech", "")
                self.default_prompt = data.get("default", "")
                logger.info("从 prompt.json 加载提示词")
                return
            except Exception:
                pass

        self.classify_prompt = load_prompt("classify_prompt")
        self.price_prompt = load_prompt("price_prompt")
        self.tech_prompt = load_prompt("tech_prompt")
        self.default_prompt = load_prompt("default_prompt")
        logger.info("从文件加载提示词")

    async def load_prompts_from_db(self):
        try:
            from common.db import AsyncSessionLocal
            from sqlalchemy import select
            from common.models import SystemConfig

            prompt_keys = ["prompt:classify_prompt", "prompt:price_prompt", "prompt:tech_prompt", "prompt:default_prompt"]
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(SystemConfig).where(SystemConfig.key_name.in_(prompt_keys)))
                db_prompts = {r.key_name: r.value for r in result.scalars()}

            if db_prompts.get("prompt:classify_prompt"):
                self.classify_prompt = db_prompts["prompt:classify_prompt"]
            if db_prompts.get("prompt:price_prompt"):
                self.price_prompt = db_prompts["prompt:price_prompt"]
            if db_prompts.get("prompt:tech_prompt"):
                self.tech_prompt = db_prompts["prompt:tech_prompt"]
            if db_prompts.get("prompt:default_prompt"):
                self.default_prompt = db_prompts["prompt:default_prompt"]

            if any(db_prompts.values()):
                self._init_agents()
                self.router = IntentRouter(self.agents["classify"])
                logger.info("从数据库加载提示词")
        except Exception as e:
            logger.warning(f"从数据库加载提示词失败，使用文件默认值: {e}")

    def _safe_filter(self, text: str) -> str:
        if not text:
            return "-"
        blocked = ["微信", "QQ", "支付宝", "银行卡", "线下"]
        return "[安全提醒]请通过平台沟通" if any(p in text for p in blocked) else text

    def format_history(self, context: List[Dict]) -> str:
        msgs = [m for m in context if m["role"] in ("user", "assistant")]
        return "\n".join(f"{m['role']}: {m['content']}" for m in msgs)

    async def generate_reply(self, user_msg: str, item_desc: str, context: List[Dict]) -> str:
        formatted_context = self.format_history(context)
        detected_intent = await self.router.detect(user_msg, item_desc, formatted_context)

        if detected_intent == "no_reply":
            self.last_intent = "no_reply"
            return "-"

        internal_intents = {"classify"}
        if detected_intent in self.agents and detected_intent not in internal_intents:
            agent = self.agents[detected_intent]
            self.last_intent = detected_intent
        else:
            agent = self.agents["default"]
            self.last_intent = "default"

        bargain_count = self._extract_bargain_count(context)
        return await agent.generate(
            user_msg=user_msg, item_desc=item_desc, context=formatted_context, bargain_count=bargain_count
        )

    def _extract_bargain_count(self, context: List[Dict]) -> int:
        for msg in context:
            if msg["role"] == "system" and "议价次数" in msg["content"]:
                match = re.search(r"议价次数[:：]\s*(\d+)", msg["content"])
                if match:
                    return int(match.group(1))
        return 0

    def reload_prompts(self):
        self._init_system_prompts()
        self._init_agents()
        self.router = IntentRouter(self.agents["classify"])
