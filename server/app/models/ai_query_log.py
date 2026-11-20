# -*- coding: utf-8 -*-
from sqlalchemy import Column, Integer, String, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.core.database import Base, UTCDateTime


def _utcnow():
    """返回带时区的当前 UTC 时间（写入数据库时由 UTCDateTime 统一转为 naive UTC）"""
    return datetime.now(timezone.utc)


class AIQueryLog(Base):
    __tablename__ = "ai_query_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    # 默认模型与实际使用的智谱模型保持一致
    model = Column(String(128), default="glm-4.7-flash")
    created_at = Column(UTCDateTime, default=_utcnow)

    # 关联关系
    user = relationship("User", back_populates="ai_query_logs")
