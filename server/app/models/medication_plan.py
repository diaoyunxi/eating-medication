# -*- coding: utf-8 -*-
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.core.database import Base


def _utcnow():
    """M14：返回带时区的当前 UTC 时间"""
    return datetime.now(timezone.utc)


class MedicationPlan(Base):
    __tablename__ = "medication_plans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    drug_name = Column(String, nullable=False)
    dosage = Column(String, nullable=False)           # 每次剂量，如 "1片"
    frequency = Column(String, nullable=False)        # 频率描述，如 "每日3次"
    schedule_times = Column(JSON, nullable=False)     # 服药时间点列表 ["08:00", "12:00", "18:00"]
    total_quantity = Column(Float, nullable=False)    # 总数量（盒/瓶）
    remaining_quantity = Column(Float, nullable=False) # 剩余数量
    unit = Column(String, default="片")
    # M19：统一为 Float，与 remaining_quantity 类型一致
    low_stock_threshold = Column(Float, default=5.0)   # 低于此数量提醒（单位：片/粒）
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    # S-05 修复：记录上次低库存通知时间，避免重复通知（每天最多通知一次）
    last_notified_at = Column(DateTime, nullable=True)

    # 关联关系
    user = relationship("User", back_populates="medication_plans")
    records = relationship("MedicationRecord", back_populates="plan", cascade="all, delete-orphan")
