# -*- coding: utf-8 -*-
"""每用户 AI 助手配置（多厂商 OpenAI 兼容）

每个用户一行（user_id 为主键）：
- provider: 厂商标识（zhipuai/hunyuan/minimax/kimi/deepseek/doubao/qwen/custom）
- api_key:  厂商 API Key，入库前加密（见 app.core.crypto）
- model:    模型名（部分厂商需用户自填，如火山方舟推理接入点）
- base_url: 自定义/部分厂商的 OpenAI 兼容 base_url（custom 必填）
- enabled:  是否启用该配置
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from datetime import datetime, timezone
from app.core.database import Base


def _utcnow():
    """返回带时区的当前 UTC 时间"""
    return datetime.now(timezone.utc)


class UserAIConfig(Base):
    __tablename__ = "user_ai_configs"

    # 与 users.id 一对一（每个用户仅一份 AI 配置）
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    provider = Column(String(32), nullable=False, default="zhipuai")
    # 加密存储的 API Key（明文为空表示未配置）
    api_key = Column(Text, nullable=False, default="")
    model = Column(String(128), nullable=False, default="")
    # 自定义厂商或需指定 base_url 的厂商使用
    base_url = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
