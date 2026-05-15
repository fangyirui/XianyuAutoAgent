from sqlalchemy import Column, BigInteger, String, Text, Boolean, DateTime, func
from .base import Base


class Seller(Base):
    __tablename__ = "sellers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String(64), unique=True, nullable=False, comment="闲鱼用户ID（从cookie中unb字段提取）")
    nickname = Column(String(128), nullable=True, comment="卖家昵称")
    cookies_str = Column(Text, nullable=False, comment="闲鱼Cookie")
    is_active = Column(Boolean, default=True, comment="是否启用")
    last_login_at = Column(DateTime, nullable=True, comment="最后登录时间")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
