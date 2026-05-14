from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from common.db import get_db
from common.models import Conversation, Message
from common.schemas import ConversationOut, MessageOut
from app.api.deps import get_current_user
from typing import List

router = APIRouter(prefix="/logs", tags=["logs"], dependencies=[Depends(get_current_user)])


@router.get("/conversations", response_model=List[ConversationOut])
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Conversation).order_by(desc(Conversation.updated_at)).offset(offset).limit(page_size)
    )
    return result.scalars().all()


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
