import re
from typing import List, Dict
from loguru import logger


class IntentRouter:
    def __init__(self, classify_agent):
        self.rules = {
            "tech": {
                "keywords": ["参数", "规格", "型号", "连接", "对比"],
                "patterns": [r"和.+比"],
            },
            "price": {
                "keywords": ["便宜", "价", "砍价", "少点"],
                "patterns": [r"\d+元", r"能少\d+"],
            },
        }
        self.classify_agent = classify_agent

    async def detect(self, user_msg: str, item_desc: str, context: List[Dict], chat_id: str | None = None) -> str:
        text_clean = re.sub(r"[^\w一-龥]", "", user_msg)

        if any(kw in text_clean for kw in self.rules["tech"]["keywords"]):
            logger.info(f"[IntentRouter] 关键词命中 -> tech | 原文: {user_msg}")
            return "tech"
        for pattern in self.rules["tech"]["patterns"]:
            if re.search(pattern, text_clean):
                logger.info(f"[IntentRouter] 正则命中 '{pattern}' -> tech | 原文: {user_msg}")
                return "tech"

        if any(kw in text_clean for kw in self.rules["price"]["keywords"]):
            logger.info(f"[IntentRouter] 关键词命中 -> price | 原文: {user_msg}")
            return "price"
        for pattern in self.rules["price"]["patterns"]:
            if re.search(pattern, text_clean):
                logger.info(f"[IntentRouter] 正则命中 '{pattern}' -> price | 原文: {user_msg}")
                return "price"

        logger.info(f"[IntentRouter] 规则未命中，调用ClassifyAgent | 原文: {user_msg}")
        result = await self.classify_agent.generate(
            user_msg=user_msg, item_desc=item_desc, context=context, chat_id=chat_id
        )
        logger.info(f"[IntentRouter] ClassifyAgent返回意图: {result}")
        return result
