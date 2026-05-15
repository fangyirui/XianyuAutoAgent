from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, Integer, func
from .base import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    chat_id = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    user_nickname = Column(String(128), nullable=True, comment="买家昵称")
    item_id = Column(String(64), index=True)
    manual_mode = Column(Boolean, default=False)
    manual_mode_at = Column(DateTime, nullable=True)
    bargain_count = Column(Integer, default=0)
    last_intent = Column(String(32), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
