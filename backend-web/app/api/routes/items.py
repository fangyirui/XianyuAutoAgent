from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from common.db import get_db
from common.models import ItemCache
from app.api.deps import get_current_user
from typing import List, Optional

router = APIRouter(prefix="/items", tags=["items"], dependencies=[Depends(get_current_user)])


@router.get("")
async def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(ItemCache)
    count_query = select(func.count(ItemCache.id))

    if keyword:
        query = query.where(ItemCache.title.contains(keyword))
        count_query = count_query.where(ItemCache.title.contains(keyword))

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(ItemCache.fetched_at.desc().nulls_last()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = result.scalars().all()

    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "item_id": r.item_id,
            "title": r.title or "",
            "price": float(r.price) if r.price else 0,
            "description": r.description or "",
            "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}
