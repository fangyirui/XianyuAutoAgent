from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from common.db import get_db, get_redis
from common.models import SystemConfig
from common.schemas import ConfigItem, ConfigUpdate, PromptUpdate
from common.core.config import DB_OVERRIDABLE_KEYS, settings
from app.api.deps import get_current_user
from pydantic import BaseModel
from pathlib import Path
from typing import List, Optional

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(get_current_user)])

PROMPTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "websocket" / "prompts"


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


class EnvConfigUpdate(BaseModel):
    API_KEY: Optional[str] = None
    MODEL_BASE_URL: Optional[str] = None
    MODEL_NAME: Optional[str] = None
    COOKIES_STR: Optional[str] = None


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
    return EnvConfigResponse(
        API_KEY=_mask(db_values.get("API_KEY") or settings.API_KEY),
        MODEL_BASE_URL=db_values.get("MODEL_BASE_URL") or settings.MODEL_BASE_URL,
        MODEL_NAME=db_values.get("MODEL_NAME") or settings.MODEL_NAME,
        COOKIES_STR=_mask(db_values.get("COOKIES_STR") or settings.COOKIES_STR),
    )


@router.put("/env")
async def update_env_config(body: EnvConfigUpdate, db: AsyncSession = Depends(get_db)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None and "***" not in v}
    for key, value in updates.items():
        result = await db.execute(select(SystemConfig).where(SystemConfig.key_name == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = value
        else:
            db.add(SystemConfig(key_name=key, value=value))
    await db.commit()

    r = await get_redis()
    await r.publish("config:reload", "env_updated")
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


@router.get("/prompts", response_model=List[dict])
async def list_prompts():
    prompts = []
    if PROMPTS_DIR.exists():
        for f in sorted(PROMPTS_DIR.glob("*.txt")):
            prompts.append({"name": f.stem, "content": f.read_text(encoding="utf-8")})
    return prompts


@router.put("/prompts")
async def update_prompt(body: PromptUpdate):
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = PROMPTS_DIR / f"{body.name}.txt"
    path.write_text(body.content, encoding="utf-8")
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
