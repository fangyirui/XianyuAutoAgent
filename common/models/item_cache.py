from sqlalchemy import Column, BigInteger, Boolean, String, Text, DateTime, Numeric, JSON, func
from .base import Base


class ItemCache(Base):
    __tablename__ = "item_cache"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    item_id = Column(String(64), unique=True, nullable=False)
    seller_id = Column(String(64), nullable=True, index=True, comment="商品所属卖家ID")
    title = Column(String(256), nullable=True)
    price = Column(Numeric(10, 2), nullable=True)
    description = Column(Text, nullable=True)
    custom_prompt = Column(Text, nullable=True, comment="该商品的额外AI提示词")
    default_reply = Column(Text, nullable=True, comment="该商品的固定默认回复文本")
    default_reply_enabled = Column(Boolean, nullable=False, server_default="0", comment="启用后跳过AI直接返回default_reply")
    raw_json = Column(JSON, nullable=True)
    fetched_at = Column(DateTime, server_default=func.now())
    expired_at = Column(DateTime, nullable=True)
