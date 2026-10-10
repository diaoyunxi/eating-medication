# -*- coding: utf-8 -*-
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, Index
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
    # 服药照片相对路径（如 uploads/{user_id}/{filename}.jpg），无照片则为空
    photo = Column(String(512), nullable=True)

    __table_args__ = (
        # 复合索引：take_medication 和 check_missed_medication_job 频繁按
        # plan_id + scheduled_time 查询/去重，缺少索引会导致全表扫描
        Index("ix_medication_record_plan_sched", "plan_id", "scheduled_time"),
    )

    # 关联关系
    user = relationship("User", back_populates="medication_records")
    plan = relationship("MedicationPlan", back_populates="records")
