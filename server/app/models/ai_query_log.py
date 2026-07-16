# -*- coding: utf-8 -*-
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.core.database import Base


def _utcnow():
    """M14：返回带时区的当前 UTC 时间"""
    return datetime.now(timezone.utc)


class AIQueryLog(Base):
    __tablename__ = "ai_query_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    # L14：默认模型与实际使用的智谱模型保持一致
    model = Column(String, default="glm-4.7-flash")
    created_at = Column(DateTime, default=_utcnow)

    # 关联关系
    user = relationship("User", back_populates="ai_query_logs")
