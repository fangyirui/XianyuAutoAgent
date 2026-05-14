from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from common.db import get_db
from common.models import SystemConfig
from common.schemas import ConfigItem, ConfigUpdate, PromptUpdate
from app.api.deps import get_current_user
from pathlib import Path
from typing import List

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(get_current_user)])

PROMPTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "websocket" / "prompts"


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
