# -*- coding: utf-8 -*-
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class MedicationRecord(Base):
    __tablename__ = "medication_records"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("medication_plans.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    scheduled_time = Column(DateTime, nullable=False)  # 计划服药时间
    taken_time = Column(DateTime, nullable=True)       # 实际确认时间，None表示未服
    status = Column(String, default="pending")         # pending, taken, missed, skipped
    note = Column(String, nullable=True)

    # 关联关系
    user = relationship("User", back_populates="medication_records")
    plan = relationship("MedicationPlan", back_populates="records")