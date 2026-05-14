import re


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

    async def detect(self, user_msg: str, item_desc: str, context: str) -> str:
        text_clean = re.sub(r"[^\w一-龥]", "", user_msg)

        if any(kw in text_clean for kw in self.rules["tech"]["keywords"]):
            return "tech"
        for pattern in self.rules["tech"]["patterns"]:
            if re.search(pattern, text_clean):
                return "tech"

        if any(kw in text_clean for kw in self.rules["price"]["keywords"]):
            return "price"
        for pattern in self.rules["price"]["patterns"]:
            if re.search(pattern, text_clean):
                return "price"

        return await self.classify_agent.generate(
            user_msg=user_msg, item_desc=item_desc, context=context
        )
