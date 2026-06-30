# -*- coding: utf-8 -*-
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from datetime import datetime

class MedicationPlanCreate(BaseModel):
    """创建用药计划请求"""
    drug_name: str = Field(..., min_length=1, max_length=100)
    dosage: str = Field(..., description="每次剂量，如 '1片'")
    frequency: str = Field(..., description="频率描述，如 '每日3次'")
    schedule_times: List[str] = Field(..., description="服药时间点，如 ['08:00','20:00']")
    total_quantity: float = Field(..., gt=0, description="总数量")
    remaining_quantity: float = Field(..., ge=0, description="剩余数量")
    unit: str = Field(default="片")
    low_stock_threshold: int = Field(default=5, ge=1, description="低库存阈值（剩余数量）")

class MedicationPlanOut(BaseModel):
    """用药计划响应"""
    id: int
    user_id: int
    drug_name: str
    dosage: str
    frequency: str
    schedule_times: List[str]
    total_quantity: float
    remaining_quantity: float
    unit: str
    low_stock_threshold: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class TakeMedicationRequest(BaseModel):
    """记录服药请求"""
    plan_id: int
    scheduled_time: datetime   # 计划时间点
    taken_time: datetime       # 实际确认时间

class MedicationRecordOut(BaseModel):
    """服药记录响应"""
    id: int
    plan_id: int
    user_id: int
    scheduled_time: datetime
    taken_time: Optional[datetime] = None
    status: str
    note: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)