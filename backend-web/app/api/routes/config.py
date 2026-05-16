from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from common.db import get_db, get_redis
from common.models import SystemConfig, Seller
from common.schemas import ConfigItem, ConfigUpdate, PromptUpdate
from common.core.config import DB_OVERRIDABLE_KEYS, settings
from app.api.deps import get_current_user
from pydantic import BaseModel
from pathlib import Path
from typing import List, Optional

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(get_current_user)])


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) > 8:
        return value[:4] + "***" + value[-4:]
    return "***"


class EnvConfigResponse(BaseModel):
    API_KEY: str = ""
    MODEL_BASE_URL: str = ""
    MODEL_NAME: str = ""
    COOKIES_STR: str = ""
    SKIP_KEYWORDS: str = ""


class EnvConfigUpdate(BaseModel):
    API_KEY: Optional[str] = None
    MODEL_BASE_URL: Optional[str] = None
    MODEL_NAME: Optional[str] = None
    COOKIES_STR: Optional[str] = None
    SKIP_KEYWORDS: Optional[str] = None


class AiTestRequest(BaseModel):
    api_key: str = ""
    base_url: str = ""
    model: str = ""


@router.get("/env", response_model=EnvConfigResponse)
async def get_env_config(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key_name.in_(DB_OVERRIDABLE_KEYS))
    )
    db_values = {r.key_name: r.value for r in result.scalars()}

    # Cookie 从 sellers 表读取（取第一个活跃卖家）
    seller_result = await db.execute(select(Seller).where(Seller.is_active.is_(True)).limit(1))
    seller = seller_result.scalar_one_or_none()
    cookies_str = seller.cookies_str if seller else (db_values.get("COOKIES_STR") or settings.COOKIES_STR)

    return EnvConfigResponse(
        API_KEY=_mask(db_values.get("API_KEY") or settings.API_KEY),
        MODEL_BASE_URL=db_values.get("MODEL_BASE_URL") or settings.MODEL_BASE_URL,
        MODEL_NAME=db_values.get("MODEL_NAME") or settings.MODEL_NAME,
        COOKIES_STR=cookies_str,
        SKIP_KEYWORDS=db_values.get("SKIP_KEYWORDS") or settings.SKIP_KEYWORDS,
    )


@router.put("/env")
async def update_env_config(body: EnvConfigUpdate, db: AsyncSession = Depends(get_db)):
    raw = body.model_dump()
    updates = {}
    cookie_changed = False
    for k, v in raw.items():
        if v is None:
            continue
        if k == "API_KEY" and "***" in v:
            continue
        if k == "COOKIES_STR":
            cookie_changed = True
            # Cookie 存入 sellers 表
            cookies_str = v.strip()
            # 从 cookie 中提取 user_id (unb 字段)
            user_id = ""
            for part in cookies_str.split("; "):
                part = part.strip()
                if part.startswith("unb="):
                    user_id = part.split("=", 1)[1]
                    break
            if not user_id:
                raise HTTPException(status_code=400, detail="Cookie 中未找到 unb 字段，无法识别卖家身份")
            result = await db.execute(select(Seller).where(Seller.user_id == user_id))
            seller = result.scalar_one_or_none()
            if seller:
                seller.cookies_str = cookies_str
                seller.is_active = True
            else:
                db.add(Seller(user_id=user_id, cookies_str=cookies_str, is_active=True))
            continue
        updates[k] = v

    for key, value in updates.items():
        result = await db.execute(select(SystemConfig).where(SystemConfig.key_name == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = value
        else:
            db.add(SystemConfig(key_name=key, value=value))
    await db.commit()

    r = await get_redis()
    await r.publish("config:reload", "cookie_updated" if cookie_changed else "env_updated")
    return {"status": "ok"}


@router.post("/ai-test")
async def test_ai_connection(body: AiTestRequest, db: AsyncSession = Depends(get_db)):
    api_key = body.api_key
    if "***" in api_key:
        result = await db.execute(select(SystemConfig).where(SystemConfig.key_name == "API_KEY"))
        row = result.scalar_one_or_none()
        api_key = row.value if row and row.value else settings.API_KEY
    base_url = body.base_url or settings.MODEL_BASE_URL
    model = body.model or settings.MODEL_NAME
    if not api_key or not base_url or not model:
        return {"success": False, "error": "请填写完整的 API Key、Base URL 和模型名称"}
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=15)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "你好，请回复ok"}],
            max_tokens=10,
        )
        return {"success": True, "reply": resp.choices[0].message.content}
    except Exception as e:
        return {"success": False, "error": str(e)}


PROMPT_NAMES = ["classify_prompt", "price_prompt", "tech_prompt", "default_prompt"]
PROMPT_JSON_PATH = Path(__file__).parent.parent.parent.parent / "websocket" / "prompts" / "prompt.json"
PROMPT_KEY_MAP = {"classify_prompt": "classify", "price_prompt": "price", "tech_prompt": "tech", "default_prompt": "default"}


async def _load_default_prompts() -> dict:
    import json
    if PROMPT_JSON_PATH.exists():
        data = json.loads(PROMPT_JSON_PATH.read_text(encoding="utf-8"))
        return {f"{k}_prompt": v for k, v in data.items() if f"{k}_prompt" in PROMPT_NAMES}
    return {}


@router.get("/prompts", response_model=List[dict])
async def list_prompts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key_name.in_([f"prompt:{n}" for n in PROMPT_NAMES]))
    )
    db_prompts = {r.key_name.replace("prompt:", ""): r.value for r in result.scalars()}

    # 如果DB中缺少提示词，从文件加载默认值并写入DB
    missing = [n for n in PROMPT_NAMES if n not in db_prompts or not db_prompts[n]]
    if missing:
        defaults = await _load_default_prompts()
        for name in missing:
            value = defaults.get(name, "")
            if value:
                db.add(SystemConfig(key_name=f"prompt:{name}", value=value))
                db_prompts[name] = value
        await db.commit()

    return [{"name": n, "content": db_prompts.get(n, "")} for n in PROMPT_NAMES]


@router.put("/prompts")
async def update_prompt(body: PromptUpdate, db: AsyncSession = Depends(get_db)):
    key = f"prompt:{body.name}"
    result = await db.execute(select(SystemConfig).where(SystemConfig.key_name == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = body.content
    else:
        db.add(SystemConfig(key_name=key, value=body.content))
    await db.commit()

    r = await get_redis()
    await r.publish("config:reload", "prompt_updated")
    return {"status": "ok"}


@router.get("/system", response_model=List[ConfigItem])
async def list_config(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemConfig))
    rows = result.scalars().all()
    return [ConfigItem(key_name=r.key_name, value=r.value) for r in rows]


@router.put("/system/{key_name}")
async def update_config(key_name: str, body: ConfigUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemConfig).where(SystemConfig.key_name == key_name))
    row = result.scalar_one_or_none()
    if row:
        row.value = body.value
    else:
        db.add(SystemConfig(key_name=key_name, value=body.value))
    await db.commit()
    return {"status": "ok"}
