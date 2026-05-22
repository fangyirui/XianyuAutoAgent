from sqlalchemy import Column, BigInteger, Integer, String, Boolean, DateTime, Index, func
from .base import Base


class AiCallLog(Base):
    __tablename__ = "ai_call_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    agent_name = Column(String(32), nullable=False)
    model = Column(String(64), nullable=False)
    chat_id = Column(String(64), nullable=True)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Integer, nullable=False, default=0)
    success = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_ai_log_created", "created_at"),
        Index("idx_ai_log_agent_created", "agent_name", "created_at"),
    )
