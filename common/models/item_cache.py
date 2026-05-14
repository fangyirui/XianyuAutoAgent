from sqlalchemy import Column, BigInteger, String, Text, DateTime, Numeric, JSON, func
from .base import Base


class ItemCache(Base):
    __tablename__ = "item_cache"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    item_id = Column(String(64), unique=True, nullable=False)
    title = Column(String(256), nullable=True)
    price = Column(Numeric(10, 2), nullable=True)
    description = Column(Text, nullable=True)
    raw_json = Column(JSON, nullable=True)
    fetched_at = Column(DateTime, server_default=func.now())
    expired_at = Column(DateTime, nullable=True)
