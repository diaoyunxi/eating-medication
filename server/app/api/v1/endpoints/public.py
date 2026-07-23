# -*- coding: utf-8 -*-
"""
公开端点 - 供老人端设备使用。
除 device_id 外，还需通过 X-Device-Token 头校验设备令牌，
防止仅凭 device_id 即可访问设备数据。register_device 例外（首次注册无 token）。
"""
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from typing import Optional
from app.core.dependencies import get_db
from app.core.security import hash_password
from app.models.user import User
from app.models.medication_plan import MedicationPlan
from app.models.medication_record import MedicationRecord
from app.models.chat_message import ChatMessage
from app.models.ai_query_log import AIQueryLog
from app.services.medication_service import MedicationService
from app.services.ai_service import AIService
from app.schemas.medication import MedicationPlanCreate
from app.utils.rate_limit import check_rate_limit
from app.utils.request_utils import get_client_ip
import secrets
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public", tags=["设备公开接口"])

# AI 公开端点限流：每分钟每 IP 最多 10 次
_AI_RATE_LIMIT = 10


def _get_device_user(db: Session, device_id: str) -> User:
    """查找设备对应的真实用户

    优先按 User.device_id 字段查找（真实老人，家属绑定后关联），
    回退按 User.username == device_id 查找（兼容旧虚拟用户）。

    :param db: 数据库会话
    :param device_id: 设备 ID
    :return: 设备关联的用户（真实老人或旧虚拟用户）
    :raises HTTPException: 设备未注册时抛 404
    """
    # 优先按 device_id 字段查找（真实老人）
    user = db.query(User).filter(User.device_id == device_id).first()
    if user:
        return user
    # 回退按 username == device_id 查找（兼容旧虚拟用户）
    user = db.query(User).filter(User.username == device_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="设备未注册")
    return user


def _get_device_user_authed(db: Session, device_id: str, device_token: Optional[str]) -> User:
    """查找设备对应的真实用户并校验 device_token

    设备端点除 device_id 外，还需校验 X-Device-Token 头，
    防止仅凭 device_id 即可访问设备数据。

    移除旧数据兼容放行逻辑，强制要求所有设备必须有 device_token。无 token 的旧设备由
    register_device 自动生成后，需家属通过认证接口重新获取。

    :param db: 数据库会话
    :param device_id: 设备 ID
    :param device_token: 请求头 X-Device-Token 中的设备令牌
    :return: 设备关联的用户
    :raises HTTPException: 设备未注册(404)或令牌不匹配(403)
    """
    user = _get_device_user(db, device_id)
    # 无 token 的设备拒绝访问，不再放行
    if not user.device_token:
        raise HTTPException(
            status_code=403,
            detail="设备未初始化令牌，请联系家属重新绑定设备"
        )
    if not device_token or not secrets.compare_digest(user.device_token, device_token):
        raise HTTPException(status_code=403, detail="设备令牌无效或缺失")
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


class DeviceOffline(BaseModel):
    """设备主动下线通知"""
    device_id: str


class AIQuestion(BaseModel):
    """AI提问"""
    question: str
    device_id: Optional[str] = None


class FamilyMedicationPlan(BaseModel):
    """家属设置用药计划（通过设备ID）"""
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
):
    """设备注册/心跳上报

    查找逻辑：
    1. 优先按 User.device_id 查找（家属已绑定到真实老人）
    2. 回退按 User.username == device_id 查找（旧虚拟用户）
    3. 都找不到则创建虚拟用户（兼容老人端开机即用场景，待家属后续绑定）

    :param req: 设备注册请求（含 device_id 和可选 device_name）
    :param db: 数据库会话
    :return: {"status": "ok", "user_id": int}
    """
    # 日志脱敏，仅记录 device_id 前4位+后4位
    _did = req.device_id or ""
    _masked = _did[:4] + "***" + _did[-4:] if len(_did) > 8 else "***"
    logger.info(f"设备注册/心跳: {_masked}")

    # 1. 优先按 device_id 字段查找（真实老人，家属已绑定）
    user = db.query(User).filter(User.device_id == req.device_id).first()
    # 2. 回退按 username == device_id 查找（旧虚拟用户）
    if not user:
        user = db.query(User).filter(User.username == req.device_id).first()

    if not user:
        # 3. 都找不到，创建虚拟用户（待家属后续绑定到真实老人）
        # 生成设备访问令牌
        device_token = secrets.token_urlsafe(32)
        user = User(
            username=req.device_id,
            # 生成不可登录的随机密码
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            full_name=req.device_name or req.device_id,
            role="elderly",
            last_heartbeat_at=datetime.now(timezone.utc),
            device_token=device_token,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"自动创建设备用户（待绑定）: {_masked}")
        return {"status": "ok", "user_id": user.id, "device_token": device_token}

    # 已注册设备 - 心跳上报
    user.last_heartbeat_at = datetime.now(timezone.utc)
    # 已注册设备不再返回 device_token，防止攻击者通过
    # /device/register 枚举 device_id 获取已有设备的访问令牌。
    # 若旧用户尚无 device_token，自动生成但不返回（需家属重新绑定）。
    if not user.device_token:
        user.device_token = secrets.token_urlsafe(32)
        logger.warning(f"旧设备无 token，已自动生成（需家属重新绑定）: {_masked}")
    db.commit()
    logger.info(f"设备心跳更新: {_masked}")
    # 仅返回 user_id，不返回 device_token
    return {"status": "ok", "user_id": user.id}


@router.post("/device/offline")
async def device_offline(
    req: DeviceOffline,
    db: Session = Depends(get_db),
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """设备主动下线通知

    设备正常退出（SIGINT/SIGTERM/进程关闭）时调用，
    将 last_heartbeat_at 置为很早的时间，使 is_online 立即为 false，
    避免子女端在心跳超时窗口内看到虚假的"在线"状态。
    注意：掉电/SIGKILL 等异常退出仍需依赖心跳超时判定。

    需校验 X-Device-Token。
    """
    _did = req.device_id or ""
    _masked = _did[:4] + "***" + _did[-4:] if len(_did) > 8 else "***"
    logger.info(f"设备主动下线: {_masked}")

    # 校验 device_token
    user = _get_device_user_authed(db, req.device_id, device_token)

    # 将 last_heartbeat_at 置为很早的时间，使在线判断立即返回 false
    user.last_heartbeat_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    db.commit()
    logger.info(f"设备已标记离线: {_masked}")
    return {"status": "ok"}


@router.post("/device/message")
async def device_message(
    req: DeviceMessage,
    db: Session = Depends(get_db),
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """接收设备上报消息（校验 device_id 与 X-Device-Token）"""
    # 日志脱敏
    _did = req.device_id or ""
    _masked = _did[:4] + "***" + _did[-4:] if len(_did) > 8 else "***"
    logger.info(f"收到设备消息: {_masked} - {req.message_type}")
    user = _get_device_user_authed(db, req.device_id, device_token)

    # 根据消息类型处理
    if req.message_type == "emergency":
        logger.warning(f"紧急消息: {_masked} - {req.content}")
        # TODO: 通过WebSocket推送给子女端

    return {"status": "ok"}


@router.get("/device/status/{device_id}")
async def get_device_status(
    device_id: str,
    db: Session = Depends(get_db),
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """获取设备状态信息（供子女端查询，校验 device_id 与 X-Device-Token）

    设备状态接口需兼容两类历史问题：
    - 设备-用户关联：通过 _get_device_user 反查到真实老人（原虚拟用户方案）
    - 时区兼容：SQLite 不保留时区信息，需把 naive datetime 补上 UTC 时区
    """
    # 日志脱敏，仅记录 device_id 前4位+后4位
    _did = device_id or ""
    _masked = _did[:4] + "***" + _did[-4:] if len(_did) > 8 else "***"
    logger.info(f"查询设备状态: {_masked}")
    user = _get_device_user_authed(db, device_id, device_token)

    # 使用 count 聚合，避免全量加载记录
    total_plans = db.query(MedicationPlan).filter(MedicationPlan.user_id == user.id).count()
    total_records = db.query(MedicationRecord).filter(MedicationRecord.user_id == user.id).count()

    # 根据心跳时间判断在线状态（1分钟内有心跳视为在线）
    # 时区兼容：SQLite 不保留时区信息，取出的 datetime 可能是 naive，需补上 UTC 时区
    now = datetime.now(timezone.utc)
    is_online = False
    last_heartbeat = None
    if user.last_heartbeat_at:
        heartbeat = user.last_heartbeat_at
        # 若为 naive datetime（SQLite 取出），补上 UTC 时区
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        last_heartbeat = heartbeat.isoformat()
        time_diff = (now - heartbeat).total_seconds()
        is_online = time_diff <= 60

    # device_id 优先取真实老人绑定的字段；回退路径参数；最后回退 username（旧虚拟用户）
    resolved_device_id = user.device_id or device_id or user.username
    return {
        "device_id": resolved_device_id,
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
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """AI问答（设备端，基于 IP 限流，每分钟每 IP 最多 10 次）

    若提供 device_id，需校验 X-Device-Token。
    """
    # 限流（使用真实客户端 IP）
    client_ip = get_client_ip(request)
    if not check_rate_limit(f"ai_ask:{client_ip}", _AI_RATE_LIMIT):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    # 若提供 device_id，校验设备令牌
    user = None
    if req.device_id:
        _did = req.device_id or ""
        _masked = _did[:4] + "***" + _did[-4:] if len(_did) > 8 else "***"
        logger.info(f"设备AI提问: {_masked} - {req.question}")
        user = _get_device_user_authed(db, req.device_id, device_token)

    answer = await AIService.ask(req.question)

    # 记录问答日志
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
    """检查设备是否已注册（供子女端绑定时校验，仅返回 exists，不泄露敏感信息）

    查找逻辑：优先 device_id 字段，回退 username。
    """
    # 优先按 device_id 字段查找（真实老人），回退 username（旧虚拟用户）
    user = db.query(User).filter(User.device_id == device_id).first()
    if not user:
        user = db.query(User).filter(User.username == device_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="设备未注册")
    # 仅返回最少信息，移除 device_name/created_at 防止用户名枚举与信息泄露
    return {"exists": True}


@router.get("/device/schedule/{device_id}")
async def get_device_schedule(
    device_id: str,
    db: Session = Depends(get_db),
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """获取设备的用药计划（供老人端每分钟轮询，校验 device_id 与 X-Device-Token）"""
    user = _get_device_user_authed(db, device_id, device_token)

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
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/device/medication_plan")
async def set_device_medication_plan(
    req: FamilyMedicationPlan,
    db: Session = Depends(get_db),
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """家属通过设备ID设置用药计划（校验 device_id 与 X-Device-Token）"""
    user = _get_device_user_authed(db, req.device_id, device_token)

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
    # 日志脱敏，仅记录 device_id 前4位+后4位
    _did = req.device_id or ""
    _masked = _did[:4] + "***" + _did[-4:] if len(_did) > 8 else "***"
    logger.info(f"家属为设备 {_masked} 设置用药计划: {req.drug_name}")

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
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """获取设备的所有用药计划（供子女端查看，校验 device_id 与 X-Device-Token）"""
    user = _get_device_user_authed(db, device_id, device_token)

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
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """获取设备的服药记录（供子女端 BFF 调用，校验 device_id 与 X-Device-Token）"""
    user = _get_device_user_authed(db, device_id, device_token)

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
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """获取设备相关的聊天历史（供子女端 BFF 调用，校验 device_id 与 X-Device-Token）"""
    user = _get_device_user_authed(db, device_id, device_token)

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
    device_id: str,
    db: Session = Depends(get_db),
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """删除用药计划（校验 device_id 与 X-Device-Token 及设备归属）"""
    user = _get_device_user_authed(db, device_id, device_token)
    plan = db.query(MedicationPlan).filter(
        MedicationPlan.id == plan_id,
        MedicationPlan.user_id == user.id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在或不属于该设备")
    db.delete(plan)
    db.commit()
    return {"status": "ok"}


@router.put("/device/medication_plan/{plan_id}")
async def update_device_medication_plan(
    plan_id: int,
    req: FamilyMedicationPlan,
    db: Session = Depends(get_db),
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """更新用药计划（校验 device_id 与 X-Device-Token 及设备归属）"""
    user = _get_device_user_authed(db, req.device_id, device_token)

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
    try:
        plan = MedicationService.update_plan(db, plan_id, user.id, plan_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    _did = req.device_id or ""
    _masked = _did[:4] + "***" + _did[-4:] if len(_did) > 8 else "***"
    logger.info(f"家属为设备 {_masked} 更新用药计划 {plan_id}: {req.drug_name}")

    return {
        "status": "ok",
        "plan_id": plan.id,
        "drug_name": plan.drug_name,
        "schedule_times": plan.schedule_times,
    }
