# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.medication import (
    MedicationPlanCreate, MedicationPlanOut,
    TakeMedicationRequest, MedicationRecordOut
)
from app.services.medication_service import MedicationService

router = APIRouter(prefix="/medication", tags=["用药管理"])

@router.post("/plan", response_model=MedicationPlanOut, status_code=201)
def create_plan(
    plan_data: MedicationPlanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建用药计划（仅老人）"""
    if current_user.role != "elderly":
        raise HTTPException(status_code=403, detail="只有老人可以创建用药计划")
    return MedicationService.create_plan(db, current_user.id, plan_data)

@router.get("/plans", response_model=List[MedicationPlanOut])
def list_plans(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取当前用户的用药计划（老人自己的；家属看到同组老人的）"""
    if current_user.role == "elderly":
        return MedicationService.get_plans_by_user(db, current_user.id)
    elif current_user.role == "family":
        if not current_user.group_id:
            return []
        return MedicationService.get_plans_for_family(db, current_user.group_id)
    return []

@router.post("/take")
def take_medication(
    req: TakeMedicationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """记录服药（仅老人）"""
    if current_user.role != "elderly":
        raise HTTPException(status_code=403, detail="只有老人可以记录服药")
    try:
        record = MedicationService.take_medication(db, current_user.id, req)
        return {"status": "success", "record_id": record.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/history", response_model=List[MedicationRecordOut])
def get_history(
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取服药历史记录"""
    return MedicationService.get_history(db, current_user, start, end)