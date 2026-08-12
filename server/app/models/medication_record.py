# -*- coding: utf-8 -*-
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base, UTCDateTime

class MedicationRecord(Base):
    __tablename__ = "medication_records"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("medication_plans.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    scheduled_time = Column(UTCDateTime, nullable=False)  # 计划服药时间
    taken_time = Column(UTCDateTime, nullable=True)       # 实际确认时间，None表示未服
    status = Column(String(20), default="pending")         # pending, taken, missed, skipped
    note = Column(String(255), nullable=True)
    # 未确认升级通知去重标志：1 分钟 / 3 分钟未确认分别只推送一次
    notified_unconfirmed_1m = Column(Boolean, default=False, nullable=False)
    notified_unconfirmed_3m = Column(Boolean, default=False, nullable=False)

    # 关联关系
    user = relationship("User", back_populates="medication_records")
    plan = relationship("MedicationPlan", back_populates="records")
