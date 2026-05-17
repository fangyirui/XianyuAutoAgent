import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case
from common.core import settings
from common.db import get_db
from common.models import ItemCache, Seller
from app.api.deps import get_current_user
from typing import List, Optional
from pydantic import BaseModel

router = APIRouter(prefix="/items", tags=["items"], dependencies=[Depends(get_current_user)])


@router.get("")
async def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    # 获取当前活跃卖家ID列表
    seller_result = await db.execute(select(Seller.user_id).where(Seller.is_active.is_(True)))
    seller_ids = [r[0] for r in seller_result.all()]

    query = select(ItemCache)
    count_query = select(func.count(ItemCache.id))

    # 只显示属于当前卖家的商品；如果没有配置卖家则显示全部
    if seller_ids:
        query = query.where(ItemCache.seller_id.in_(seller_ids))
        count_query = count_query.where(ItemCache.seller_id.in_(seller_ids))

    if keyword:
        query = query.where(ItemCache.title.contains(keyword))
        count_query = count_query.where(ItemCache.title.contains(keyword))

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(
        case((ItemCache.fetched_at.is_(None), 1), else_=0),
        ItemCache.fetched_at.desc(),
    ).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = result.scalars().all()

    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "item_id": r.item_id,
            "seller_id": r.seller_id or "",
            "title": r.title or "",
            "price": float(r.price) if r.price else 0,
            "description": r.description or "",
            "custom_prompt": r.custom_prompt or "",
            "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/sync")
async def sync_items():
    """手动触发 websocket 服务从闲鱼拉取卖家商品列表并入库。"""
    url = f"{settings.WEBSOCKET_SERVICE_URL}/api/control/sync-items"
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=resp.status, detail="WebSocket service error")
            return await resp.json()


class ItemPromptUpdate(BaseModel):
    custom_prompt: str


@router.patch("/{item_id}")
async def update_item_prompt(
    item_id: str,
    payload: ItemPromptUpdate,
    db: AsyncSession = Depends(get_db),
):
    # 仅允许修改当前活跃卖家名下的商品
    seller_result = await db.execute(select(Seller.user_id).where(Seller.is_active.is_(True)))
    seller_ids = [r[0] for r in seller_result.all()]

    query = select(ItemCache).where(ItemCache.item_id == item_id)
    # 与 GET /items 行为一致：如果没有配置活跃卖家，不做卖家过滤
    if seller_ids:
        query = query.where(ItemCache.seller_id.in_(seller_ids))

    result = await db.execute(query)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="商品不存在或无权限修改")

    item.custom_prompt = payload.custom_prompt or None
    await db.commit()
    return {"ok": True, "custom_prompt": item.custom_prompt or ""}
