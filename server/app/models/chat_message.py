# -*- coding: utf-8 -*-
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from datetime import datetime, timezone
from app.core.database import Base


def _utcnow():
    """M14：返回带时区的当前 UTC 时间"""
    return datetime.now(timezone.utc)


class ChatMessage(Base):
    """聊天消息模型"""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    # L11：为 sender_id 和 receiver_id 增加索引，加速历史查询
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    receiver_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    sender_name = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
