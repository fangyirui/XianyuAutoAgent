from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_
from common.db import get_db
from common.models import Conversation, Message, ItemCache
from common.schemas import MessageOut
from app.api.deps import get_current_user
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/logs", tags=["logs"], dependencies=[Depends(get_current_user)])


class ConversationListItem(BaseModel):
    id: int
    chat_id: str
    user_id: str
    item_id: Optional[str] = None
    item_title: Optional[str] = None
    item_price: Optional[float] = None
    manual_mode: bool
    bargain_count: int
    last_intent: Optional[str] = None
    last_message: Optional[str] = None
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


@router.get("/conversations", response_model=List[ConversationListItem])
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size
    query = select(Conversation)
    if keyword:
        query = query.where(
            Conversation.chat_id.contains(keyword)
            | Conversation.user_id.contains(keyword)
            | Conversation.item_id.contains(keyword)
        )
    result = await db.execute(
        query.order_by(desc(Conversation.updated_at)).offset(offset).limit(page_size)
    )
    conversations = result.scalars().all()

    # 批量查询关联的商品信息
    item_ids = [c.item_id for c in conversations if c.item_id]
    item_map = {}
    if item_ids:
        item_result = await db.execute(select(ItemCache).where(ItemCache.item_id.in_(item_ids)))
        item_map = {i.item_id: i for i in item_result.scalars().all()}

    # 批量查询每个会话的消息数和最后一条用户消息
    conv_ids = [c.id for c in conversations]
    msg_counts = {}
    last_messages = {}
    if conv_ids:
        count_result = await db.execute(
            select(Message.conversation_id, func.count(Message.id))
            .where(Message.conversation_id.in_(conv_ids))
            .group_by(Message.conversation_id)
        )
        msg_counts = dict(count_result.all())

        # 批量获取每个会话最后一条用户消息
        latest_msg_ids_subq = (
            select(func.max(Message.id).label("max_id"))
            .where(and_(
                Message.conversation_id.in_(conv_ids),
                Message.role == "user",
            ))
            .group_by(Message.conversation_id)
        ).subquery()
        last_msg_result = await db.execute(
            select(Message).where(Message.id.in_(select(latest_msg_ids_subq.c.max_id)))
        )
        for msg in last_msg_result.scalars():
            last_messages[msg.conversation_id] = msg.content

    items = []
    for c in conversations:
        item = item_map.get(c.item_id) if c.item_id else None
        items.append(ConversationListItem(
            id=c.id,
            chat_id=c.chat_id,
            user_id=c.user_id,
            item_id=c.item_id,
            item_title=item.title if item else None,
            item_price=float(item.price) if item and item.price else None,
            manual_mode=c.manual_mode,
            bargain_count=c.bargain_count,
            last_intent=c.last_intent,
            last_message=last_messages.get(c.id),
            message_count=msg_counts.get(c.id, 0),
            created_at=c.created_at,
            updated_at=c.updated_at,
        ))

    return items


@router.get("/conversations/{chat_id}/messages", response_model=List[MessageOut])
async def get_messages(chat_id: str, db: AsyncSession = Depends(get_db)):
    conv_result = await db.execute(select(Conversation).where(Conversation.chat_id == chat_id))
    conv = conv_result.scalar_one_or_none()
    if not conv:
        return []
    result = await db.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )
    return result.scalars().all()


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    conv_count = await db.execute(select(func.count(Conversation.id)))
    msg_count = await db.execute(select(func.count(Message.id)))
    return {
        "total_conversations": conv_count.scalar(),
        "total_messages": msg_count.scalar(),
    }
