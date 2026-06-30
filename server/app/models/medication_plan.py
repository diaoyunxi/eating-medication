# -*- coding: utf-8 -*-
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

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
    low_stock_threshold = Column(Integer, default=5)   # 低于此数量提醒（单位：片/粒）
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联关系
    user = relationship("User", back_populates="medication_plans")
    records = relationship("MedicationRecord", back_populates="plan", cascade="all, delete-orphan")