# -*- coding: utf-8 -*-
"""
公开端点 - 供老人端设备使用（无需认证）
支持设备注册、消息上报、紧急通知等
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.core.database import get_db
from app.models.user import User
from app.services.medication_service import MedicationService
from app.services.ai_service import AIService
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public", tags=["设备公开接口"])


class DeviceMessage(BaseModel):
    """设备消息"""
    device_id: str
    message_type: str = "info"  # info, medication, emergency, ai
    content: str = ""
    data: Optional[dict] = None


class DeviceRegister(BaseModel):
    """设备注册"""
    device_id: str
    device_name: Optional[str] = None


class AIQuestion(BaseModel):
    """AI提问"""
    question: str
    device_id: Optional[str] = None


class FamilyMedicationPlan(BaseModel):
    """家属设置用药计划（通过设备ID，无需JWT认证）"""
    device_id: str
    drug_name: str
    dosage: str = "1片"
    frequency: str = "每日"
    schedule_times: list  # ["08:00", "12:00", "18:00"]
    total_quantity: float = 30.0
    remaining_quantity: float = 30.0
    unit: str = "片"
    low_stock_threshold: int = 5


@router.post("/device/register")
async def register_device(req: DeviceRegister, db: Session = Depends(get_db)):
    """设备注册/心跳上报"""
    logger.info(f"设备注册/心跳: {req.device_id}")
    # 查找或创建设备记录
    user = db.query(User).filter(User.username == req.device_id).first()
    if not user:
        # 自动创建老人用户（以device_id为用户名）
        user = User(
            username=req.device_id,
            hashed_password="device",  # 设备不需要密码登录
            full_name=req.device_name or req.device_id,
            role="elderly",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"自动创建设备用户: {req.device_id}")
    return {"status": "ok", "user_id": user.id}


@router.post("/device/message")
async def device_message(req: DeviceMessage, db: Session = Depends(get_db)):
    """接收设备上报消息"""
    logger.info(f"收到设备消息: {req.device_id} - {req.message_type}")
    # 查找关联用户
    user = db.query(User).filter(User.username == req.device_id).first()
    if not user:
        return {"status": "error", "detail": "设备未注册"}

    # 根据消息类型处理
    if req.message_type == "emergency":
        logger.warning(f"紧急消息: {req.device_id} - {req.content}")
        # TODO: 通过WebSocket推送给子女端

    return {"status": "ok"}


@router.get("/device/status/{device_id}")
async def get_device_status(device_id: str, db: Session = Depends(get_db)):
    """获取设备状态信息（供子女端查询）"""
    logger.info(f"查询设备状态: {device_id}")
    user = db.query(User).filter(User.username == device_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="设备未注册")

    # 获取设备相关统计
    from app.models.medication_plan import MedicationPlan
    from app.models.medication_record import MedicationRecord
    plans = db.query(MedicationPlan).filter(MedicationPlan.user_id == user.id).all()
    records = db.query(MedicationRecord).filter(MedicationRecord.user_id == user.id).all()

    return {
        "device_id": user.username,
        "device_name": user.full_name,
        "role": user.role,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "total_plans": len(plans) if plans else 0,
        "total_records": len(records) if records else 0,
        "status": "online"
    }


@router.post("/ai/ask")
async def ai_ask(req: AIQuestion, db: Session = Depends(get_db)):
    """AI问答（设备端）"""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    logger.info(f"设备AI提问: {req.device_id} - {req.question}")
    answer = await AIService.ask(req.question)

    # 记录问答日志
    if req.device_id:
        user = db.query(User).filter(User.username == req.device_id).first()
        if user:
            from app.models.ai_query_log import AIQueryLog
            log = AIQueryLog(
                user_id=user.id,
                question=req.question,
                answer=answer,
            )
            db.add(log)
            db.commit()

    return {"answer": answer}


@router.get("/device/check/{device_id}")
async def check_device(device_id: str, db: Session = Depends(get_db)):
    """检查设备是否已注册（供子女端绑定时校验）"""
    user = db.query(User).filter(User.username == device_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="设备未注册")
    return {
        "exists": True,
        "device_id": user.username,
        "device_name": user.full_name,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.get("/device/schedule/{device_id}")
async def get_device_schedule(device_id: str, db: Session = Depends(get_db)):
    """获取设备的用药计划（供老人端每分钟轮询，无需认证）"""
    user = db.query(User).filter(User.username == device_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="设备未注册")

    from app.models.medication_plan import MedicationPlan
    plans = db.query(MedicationPlan).filter(MedicationPlan.user_id == user.id).all()

    schedules = []
    for plan in plans:
        for time_str in plan.schedule_times:
            schedules.append({
                "plan_id": plan.id,
                "drug_name": plan.drug_name,
                "dosage": plan.dosage,
                "time": time_str,
                "frequency": plan.frequency,
                "remaining_quantity": plan.remaining_quantity,
                "unit": plan.unit,
            })

    return {
        "device_id": device_id,
        "device_name": user.full_name,
        "schedules": schedules,
        "updated_at": datetime.now().isoformat(),
    }


@router.post("/device/medication_plan")
async def set_device_medication_plan(req: FamilyMedicationPlan, db: Session = Depends(get_db)):
    """家属通过设备ID设置用药计划（无需JWT认证）"""
    user = db.query(User).filter(User.username == req.device_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="设备未注册，请先在老人端完成配网")

    from app.models.medication_plan import MedicationPlan
    from app.schemas.medication import MedicationPlanCreate

    plan_data = MedicationPlanCreate(
        drug_name=req.drug_name,
        dosage=req.dosage,
        frequency=req.frequency,
        schedule_times=req.schedule_times,
        total_quantity=req.total_quantity,
        remaining_quantity=req.remaining_quantity,
        unit=req.unit,
        low_stock_threshold=req.low_stock_threshold,
    )
    plan = MedicationService.create_plan(db, user.id, plan_data)
    logger.info(f"家属为设备 {req.device_id} 设置用药计划: {req.drug_name}")

    return {
        "status": "ok",
        "plan_id": plan.id,
        "drug_name": plan.drug_name,
        "schedule_times": plan.schedule_times,
    }


@router.get("/device/plans/{device_id}")
async def get_device_plans(device_id: str, db: Session = Depends(get_db)):
    """获取设备的所有用药计划（供子女端查看，无需认证）"""
    user = db.query(User).filter(User.username == device_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="设备未注册")

    plans = MedicationService.get_plans_by_user(db, user.id)
    return {
        "device_id": device_id,
        "plans": [
            {
                "id": p.id,
                "drug_name": p.drug_name,
                "dosage": p.dosage,
                "frequency": p.frequency,
                "schedule_times": p.schedule_times,
                "total_quantity": p.total_quantity,
                "remaining_quantity": p.remaining_quantity,
                "unit": p.unit,
                "low_stock_threshold": p.low_stock_threshold,
            }
            for p in plans
        ],
    }


@router.delete("/device/medication_plan/{plan_id}")
async def delete_device_medication_plan(plan_id: int, db: Session = Depends(get_db)):
    """删除用药计划（供子女端管理）"""
    from app.models.medication_plan import MedicationPlan
    plan = db.query(MedicationPlan).filter(MedicationPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")
    db.delete(plan)
    db.commit()
    return {"status": "ok"}