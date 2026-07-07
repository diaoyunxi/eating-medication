# -*- coding: utf-8 -*-
"""
公开端点 - 供老人端设备使用。
C5：引入设备密钥机制（device_token），写操作与读操作均需校验 X-Device-Token。
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from typing import Optional
# M17：get_db 统一从 dependencies 导入
from app.core.dependencies import get_db
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.models.medication_plan import MedicationPlan
from app.models.medication_record import MedicationRecord
from app.models.chat_message import ChatMessage
from app.models.ai_query_log import AIQueryLog
from app.services.medication_service import MedicationService
from app.services.ai_service import AIService
from app.schemas.medication import MedicationPlanCreate
# C5.6/M21：AI 端点限流
from app.utils.rate_limit import check_rate_limit
import secrets
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public", tags=["设备公开接口"])

# AI 公开端点限流：每分钟每 IP 最多 10 次
_AI_RATE_LIMIT = 10


def _verify_device_token(user: User, token: Optional[str]) -> bool:
    """C5：校验设备 token（device_token 存储于 user.hashed_password 的哈希）"""
    if not token:
        return False
    try:
        return verify_password(token, user.hashed_password)
    except Exception:
        return False


def _get_device_user_and_verify(db: Session, device_id: str, token: Optional[str]) -> User:
    """查找设备用户并校验 device_token（C5）"""
    user = db.query(User).filter(User.username == device_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="设备未注册")
    if not _verify_device_token(user, token):
        raise HTTPException(status_code=401, detail="设备 token 无效或缺失")
    return user


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
    """家属设置用药计划（通过设备ID，需携带 X-Device-Token）"""
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
async def register_device(
    req: DeviceRegister,
    db: Session = Depends(get_db),
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """设备注册/心跳上报（C5：成功注册时返回 device_token）"""
    # H-3 修复：日志脱敏，仅记录 device_id 前4位+后4位
    _did = req.device_id or ""
    _masked = _did[:4] + "***" + _did[-4:] if len(_did) > 8 else "***"
    logger.info(f"设备注册/心跳: {_masked}")
    # 查找或创建设备记录
    user = db.query(User).filter(User.username == req.device_id).first()
    if not user:
        # 自动创建老人用户（以device_id为用户名）
        # C5：生成 device_token，其哈希存入 password_hash 字段
        device_token = secrets.token_urlsafe(32)
        user = User(
            username=req.device_id,
            # C5.3：生成不可登录的随机密码（device_token 的哈希）
            hashed_password=hash_password(device_token),
            full_name=req.device_name or req.device_id,
            role="elderly",
            last_heartbeat_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"自动创建设备用户: {_masked}")
        return {"status": "ok", "user_id": user.id, "device_token": device_token}

    # 已注册设备 - 心跳上报
    # P0-2 修复：移除 legacy 无条件重置 token 分支，防止设备冒充接管
    # 已注册设备必须校验现有 X-Device-Token；若 token 丢失需通过管理员重置
    if not _verify_device_token(user, x_device_token):
        raise HTTPException(status_code=401, detail="设备 token 无效或缺失，已注册设备请携带正确的 X-Device-Token")
    user.last_heartbeat_at = datetime.now(timezone.utc)
    db.commit()
    logger.info(f"设备心跳更新: {_masked}")
    return {"status": "ok", "user_id": user.id}


@router.post("/device/message")
async def device_message(
    req: DeviceMessage,
    db: Session = Depends(get_db),
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """接收设备上报消息（F4 修复：增加 device_token 校验，防止伪造）"""
    # H-3 修复：日志脱敏
    _did = req.device_id or ""
    _masked = _did[:4] + "***" + _did[-4:] if len(_did) > 8 else "***"
    logger.info(f"收到设备消息: {_masked} - {req.message_type}")
    # F4：校验 device_token，防止任意伪造服药/紧急/聊天消息
    user = db.query(User).filter(User.username == req.device_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="设备未注册")
    if not _verify_device_token(user, x_device_token):
        raise HTTPException(status_code=401, detail="设备 token 无效或缺失")

    # 根据消息类型处理
    if req.message_type == "emergency":
        logger.warning(f"紧急消息: {req.device_id} - {req.content}")
        # TODO: 通过WebSocket推送给子女端

    return {"status": "ok"}


@router.get("/device/status/{device_id}")
async def get_device_status(
    device_id: str,
    db: Session = Depends(get_db),
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """获取设备状态信息（供子女端查询，C5：需校验 device_token）"""
    logger.info(f"查询设备状态: {device_id}")
    user = _get_device_user_and_verify(db, device_id, x_device_token)

    # 获取设备相关统计（G2 修复：使用 count 聚合，避免全量加载记录）
    total_plans = db.query(MedicationPlan).filter(MedicationPlan.user_id == user.id).count()
    total_records = db.query(MedicationRecord).filter(MedicationRecord.user_id == user.id).count()

    # 根据心跳时间判断在线状态（1分钟内有心跳视为在线）
    now = datetime.now(timezone.utc)
    is_online = False
    last_heartbeat = None
    if user.last_heartbeat_at:
        last_heartbeat = user.last_heartbeat_at.isoformat()
        time_diff = (now - user.last_heartbeat_at).total_seconds()
        is_online = time_diff <= 60

    return {
        "device_id": user.username,
        "device_name": user.full_name,
        "role": user.role,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "total_plans": total_plans,
        "total_records": total_records,
        "status": "online" if is_online else "offline",
        "last_heartbeat": last_heartbeat,
        "is_online": is_online
    }


@router.post("/ai/ask")
async def ai_ask(
    req: AIQuestion,
    request: Request,
    db: Session = Depends(get_db),
):
    """AI问答（设备端，C5.6/M21：基于 IP 限流，每分钟每 IP 最多 10 次）"""
    # C5.6/M21：限流
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(f"ai_ask:{client_ip}", _AI_RATE_LIMIT):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    logger.info(f"设备AI提问: {req.device_id} - {req.question}")
    answer = await AIService.ask(req.question)

    # 记录问答日志
    if req.device_id:
        user = db.query(User).filter(User.username == req.device_id).first()
        if user:
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
    """检查设备是否已注册（供子女端绑定时校验，P0-3 修复：仅返回 exists，不泄露敏感信息）"""
    user = db.query(User).filter(User.username == device_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="设备未注册")
    # P0-3 修复：仅返回最少信息，移除 device_name/created_at 防止用户名枚举与信息泄露
    return {"exists": True}


@router.get("/device/schedule/{device_id}")
async def get_device_schedule(
    device_id: str,
    db: Session = Depends(get_db),
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """获取设备的用药计划（供老人端每分钟轮询，C5.4：需校验 device_token）"""
    user = _get_device_user_and_verify(db, device_id, x_device_token)

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
async def set_device_medication_plan(
    req: FamilyMedicationPlan,
    db: Session = Depends(get_db),
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """家属通过设备ID设置用药计划（C5.2：需校验 device_token）"""
    user = _get_device_user_and_verify(db, req.device_id, x_device_token)

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
async def get_device_plans(
    device_id: str,
    db: Session = Depends(get_db),
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """获取设备的所有用药计划（供子女端查看，C5.4：需校验 device_token）"""
    user = _get_device_user_and_verify(db, device_id, x_device_token)

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


@router.get("/device/records/{device_id}")
async def get_device_records(
    device_id: str,
    limit: int = 100,
    db: Session = Depends(get_db),
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """获取设备的服药记录（F2 修复：供子女端 BFF 调用，需校验 device_token）"""
    user = _get_device_user_and_verify(db, device_id, x_device_token)

    # 限制 limit 范围，防止一次拉取过多记录
    limit = max(1, min(limit, 500))
    records = (
        db.query(MedicationRecord)
        .filter(MedicationRecord.user_id == user.id)
        .order_by(MedicationRecord.scheduled_time.desc())
        .limit(limit)
        .all()
    )
    return {
        "device_id": device_id,
        "records": [
            {
                "id": r.id,
                "plan_id": r.plan_id,
                "scheduled_time": r.scheduled_time.isoformat() if r.scheduled_time else None,
                "taken_time": r.taken_time.isoformat() if r.taken_time else None,
                "status": r.status,
                "note": r.note,
            }
            for r in records
        ],
    }


@router.get("/device/chat_history/{device_id}")
async def get_device_chat_history(
    device_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """获取设备相关的聊天历史（S9 修复：供子女端 BFF 调用，需校验 device_token）"""
    user = _get_device_user_and_verify(db, device_id, x_device_token)

    limit = max(1, min(limit, 200))
    messages = (
        db.query(ChatMessage)
        .filter(
            or_(
                ChatMessage.sender_id == user.id,
                ChatMessage.receiver_id == user.id,
            )
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "device_id": device_id,
        "messages": [
            {
                "id": m.id,
                "sender_id": m.sender_id,
                "receiver_id": m.receiver_id,
                "sender_name": m.sender_name,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.delete("/device/medication_plan/{plan_id}")
async def delete_device_medication_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """删除用药计划（供子女端管理，C5.2：需校验 device_token）"""
    plan = db.query(MedicationPlan).filter(MedicationPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")

    # C5.2：通过计划关联的设备用户校验 device_token
    device_user = db.query(User).filter(User.id == plan.user_id).first()
    if not device_user:
        raise HTTPException(status_code=404, detail="设备未注册")
    if not _verify_device_token(device_user, x_device_token):
        raise HTTPException(status_code=401, detail="设备 token 无效或缺失")

    db.delete(plan)
    db.commit()
    return {"status": "ok"}
