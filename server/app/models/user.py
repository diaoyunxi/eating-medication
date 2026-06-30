# -*- coding: utf-8 -*-
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "elderly" 或 "family"
    phone = Column(String, nullable=True)
    group_id = Column(Integer, nullable=True)  # 家庭组ID，老人和家属同组
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关联关系
    medication_plans = relationship("MedicationPlan", back_populates="user", cascade="all, delete-orphan")
    medication_records = relationship("MedicationRecord", back_populates="user", cascade="all, delete-orphan")
    ai_query_logs = relationship("AIQueryLog", back_populates="user", cascade="all, delete-orphan")