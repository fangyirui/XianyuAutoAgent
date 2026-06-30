from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func, desc, and_, distinct
from common.db import get_db
from common.models import Conversation, Message, ItemCache, AiCallLog
from common.schemas import MessageOut
from app.api.deps import get_current_user
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

router = APIRouter(prefix="/logs", tags=["logs"], dependencies=[Depends(get_current_user)])


class ConversationListItem(BaseModel):
    id: int
    chat_id: str
    user_id: str
    user_nickname: Optional[str] = None
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


@router.get("/conversations")
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size
    query = select(Conversation)
    count_query = select(func.count(Conversation.id))
    if keyword:
        cond = (
            Conversation.chat_id.contains(keyword)
            | Conversation.user_id.contains(keyword)
            | Conversation.item_id.contains(keyword)
        )
        query = query.where(cond)
        count_query = count_query.where(cond)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

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
            user_nickname=c.user_nickname,
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

    return {"items": items, "total": total, "page": page, "page_size": page_size}


class MessagePage(BaseModel):
    items: List[MessageOut]
    has_more: bool


@router.get("/conversations/{chat_id}/messages", response_model=MessagePage)
async def get_messages(
    chat_id: str,
    limit: int = Query(50, ge=1, le=200),
    before_id: Optional[int] = Query(None, description="游标：只取 id 小于该值的更早消息"),
    db: AsyncSession = Depends(get_db),
):
    conv_result = await db.execute(select(Conversation).where(Conversation.chat_id == chat_id))
    conv = conv_result.scalar_one_or_none()
    if not conv:
        return MessagePage(items=[], has_more=False)
    # 按 id 倒序取最近一页（before_id 时取更早一页），多取 1 条用于判断是否还有更早消息
    stmt = select(Message).where(Message.conversation_id == conv.id)
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    stmt = stmt.order_by(Message.id.desc()).limit(limit + 1)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    rows.reverse()  # 翻回正序供前端按时间从上到下渲染
    return MessagePage(items=rows, has_more=has_more)


class BatchDeleteRequest(BaseModel):
    chat_ids: List[str] = Field(..., min_length=1, max_length=500)


@router.delete("/conversations/{chat_id}")
async def delete_conversation(chat_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(delete(Conversation).where(Conversation.chat_id == chat_id))
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"deleted": result.rowcount}


@router.post("/conversations/batch-delete")
async def batch_delete_conversations(payload: BatchDeleteRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(delete(Conversation).where(Conversation.chat_id.in_(payload.chat_ids)))
    await db.commit()
    return {"deleted": result.rowcount}


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    today_start = func.curdate()  # MySQL CURDATE() — 容器时区 Asia/Shanghai

    # --- 实时 ---
    q_realtime_manual_active = select(func.count(Conversation.id)).where(Conversation.manual_mode.is_(True))

    # --- 今日 ---
    q_today_conv = select(func.count(Conversation.id)).where(Conversation.created_at >= today_start)
    q_today_msg = select(func.count(Message.id)).where(Message.created_at >= today_start)
    q_today_ai_reply = select(func.count(Message.id)).where(
        and_(Message.role == "assistant", Message.created_at >= today_start)
    )
    q_today_user_msg = select(func.count(Message.id)).where(
        and_(Message.role == "user", Message.created_at >= today_start)
    )
    q_today_new_buyers = select(func.count(distinct(Conversation.user_id))).where(
        Conversation.created_at >= today_start
    )
    q_today_takeover = select(func.count(Conversation.id)).where(
        Conversation.manual_mode_at >= today_start
    )
    q_today_ai_calls = select(func.count(AiCallLog.id)).where(AiCallLog.created_at >= today_start)
    q_today_tokens = select(func.coalesce(func.sum(AiCallLog.total_tokens), 0)).where(
        AiCallLog.created_at >= today_start
    )
    q_today_ai_errors = select(func.count(AiCallLog.id)).where(
        and_(AiCallLog.success.is_(False), AiCallLog.created_at >= today_start)
    )
    q_today_avg_latency = select(func.coalesce(func.avg(AiCallLog.latency_ms), 0)).where(
        and_(AiCallLog.success.is_(True), AiCallLog.created_at >= today_start)
    )
    q_today_intent_dist = (
        select(Conversation.last_intent, func.count(Conversation.id))
        .where(and_(Conversation.updated_at >= today_start, Conversation.last_intent.isnot(None)))
        .group_by(Conversation.last_intent)
    )
    q_today_agent_dist = (
        select(AiCallLog.agent_name, func.count(AiCallLog.id))
        .where(AiCallLog.created_at >= today_start)
        .group_by(AiCallLog.agent_name)
    )

    # --- 累计 ---
    q_cum_conv = select(func.count(Conversation.id))
    q_cum_msg = select(func.count(Message.id))
    q_cum_buyers = select(func.count(distinct(Conversation.user_id)))
    q_cum_bargain = select(func.count(Conversation.id)).where(Conversation.bargain_count > 0)
    q_cum_ai_calls = select(func.count(AiCallLog.id))
    q_cum_tokens = select(func.coalesce(func.sum(AiCallLog.total_tokens), 0))

    # 顺序执行（AsyncSession 不支持单 session 并发；19 个轻量聚合查询 ~95ms 完全可接受）
    r_realtime_manual_active = await db.execute(q_realtime_manual_active)
    r_today_conv = await db.execute(q_today_conv)
    r_today_msg = await db.execute(q_today_msg)
    r_today_ai_reply = await db.execute(q_today_ai_reply)
    r_today_user_msg = await db.execute(q_today_user_msg)
    r_today_new_buyers = await db.execute(q_today_new_buyers)
    r_today_takeover = await db.execute(q_today_takeover)
    r_today_ai_calls = await db.execute(q_today_ai_calls)
    r_today_tokens = await db.execute(q_today_tokens)
    r_today_ai_errors = await db.execute(q_today_ai_errors)
    r_today_avg_latency = await db.execute(q_today_avg_latency)
    r_today_intent_dist = await db.execute(q_today_intent_dist)
    r_today_agent_dist = await db.execute(q_today_agent_dist)
    r_cum_conv = await db.execute(q_cum_conv)
    r_cum_msg = await db.execute(q_cum_msg)
    r_cum_buyers = await db.execute(q_cum_buyers)
    r_cum_bargain = await db.execute(q_cum_bargain)
    r_cum_ai_calls = await db.execute(q_cum_ai_calls)
    r_cum_tokens = await db.execute(q_cum_tokens)

    today_ai_calls = r_today_ai_calls.scalar() or 0
    today_ai_errors = r_today_ai_errors.scalar() or 0
    today_error_rate = (today_ai_errors / today_ai_calls) if today_ai_calls > 0 else 0.0
    today_avg_latency = int(round(r_today_avg_latency.scalar() or 0))

    intent_distribution = [
        {"name": name or "unknown", "count": int(count)}
        for name, count in r_today_intent_dist.all()
    ]
    intent_distribution.sort(key=lambda x: x["count"], reverse=True)

    agent_distribution = [
        {"name": name or "unknown", "count": int(count)}
        for name, count in r_today_agent_dist.all()
    ]
    agent_distribution.sort(key=lambda x: x["count"], reverse=True)

    cum_conv = r_cum_conv.scalar() or 0
    cum_msg = r_cum_msg.scalar() or 0

    return {
        "realtime": {
            "manual_active": r_realtime_manual_active.scalar() or 0,
        },
        "today": {
            "conversations": r_today_conv.scalar() or 0,
            "messages": r_today_msg.scalar() or 0,
            "ai_replies": r_today_ai_reply.scalar() or 0,
            "user_messages": r_today_user_msg.scalar() or 0,
            "new_buyers": r_today_new_buyers.scalar() or 0,
            "manual_takeover_triggered": r_today_takeover.scalar() or 0,
            "ai_calls": today_ai_calls,
            "tokens": int(r_today_tokens.scalar() or 0),
            "ai_errors": today_ai_errors,
            "ai_error_rate": round(today_error_rate, 4),
            "avg_latency_ms": today_avg_latency,
            "intent_distribution": intent_distribution,
            "agent_distribution": agent_distribution,
        },
        "cumulative": {
            "conversations": cum_conv,
            "messages": cum_msg,
            "buyers": r_cum_buyers.scalar() or 0,
            "bargain_sessions": r_cum_bargain.scalar() or 0,
            "ai_calls": r_cum_ai_calls.scalar() or 0,
            "tokens": int(r_cum_tokens.scalar() or 0),
        },
        # 向后兼容旧字段，避免老前端构件加载时报错
        "total_conversations": cum_conv,
        "total_messages": cum_msg,
    }
