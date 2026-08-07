# -*- coding: utf-8 -*-
"""
公开端点 - 供老人端设备使用。
除 device_id 外，还需通过 X-Device-Token 头校验设备令牌，
防止仅凭 device_id 即可访问设备数据。register_device 例外（首次注册无 token）。

路由层仅负责 I/O（请求模型、Header、响应）；设备身份解析、注册/心跳、下线、状态、
上传、服药确认等纯逻辑已抽至 app.services.device_service.DeviceService。
"""
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.core.security import mask_device_id
from app.models.medication_plan import MedicationPlan
from app.models.ai_query_log import AIQueryLog
from app.services.medication_service import MedicationService
from app.services.ai_service import AIService
from app.services.ai_config_service import get_effective_config
from app.services.device_service import DeviceService
from app.schemas.medication import MedicationPlanCreate
from app.utils.rate_limit import check_rate_limit
from app.utils.request_utils import get_client_ip
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public", tags=["设备公开接口"])

# AI 公开端点限流：每分钟每 IP 最多 10 次
_AI_RATE_LIMIT = 10


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
    # 药品编号/条形码（可选，非必填）：供老人端扫码识别
    product_code: Optional[str] = None
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

    :return: {"status": "ok", "user_id": int}；首次注册额外返回 "device_token"
    """
    user, device_token = DeviceService.register_or_heartbeat(db, req.device_id, req.device_name)
    if device_token:
        return {"status": "ok", "user_id": user.id, "device_token": device_token}
    return {"status": "ok", "user_id": user.id}


@router.post("/device/offline")
async def device_offline(
    req: DeviceOffline,
    db: Session = Depends(get_db),
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """设备主动下线通知

    设备正常退出（SIGINT/SIGTERM/进程关闭）时调用，将 last_heartbeat_at 置为很早的时间，
    使 is_online 立即为 false，避免子女端在心跳超时窗口内看到虚假的"在线"状态。
    注意：掉电/SIGKILL 等异常退出仍需依赖心跳超时判定。需校验 X-Device-Token。
    """
    user = DeviceService.get_device_user_authed(db, req.device_id, device_token)
    DeviceService.mark_offline(db, user)
    return {"status": "ok"}


@router.post("/device/message")
async def device_message(
    req: DeviceMessage,
    db: Session = Depends(get_db),
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """接收设备上报消息（校验 device_id 与 X-Device-Token）"""
    user = DeviceService.get_device_user_authed(db, req.device_id, device_token)

    if req.message_type == "emergency":
        logger.warning(f"紧急消息: {mask_device_id(req.device_id or '')} - {req.content}")
        # TODO: 通过WebSocket推送给子女端
    elif req.message_type == "medication":
        # 设备上报服药确认：落库并通知家属（修复缺口①）
        await DeviceService.handle_medication(db, user, req.data or {})
        return {"status": "ok"}

    return {"status": "ok"}


class DeviceUpload(BaseModel):
    """设备上传图片（base64 编码）"""
    device_id: str
    image_base64: str
    note: Optional[str] = None


@router.post("/device/upload")
async def device_upload(
    req: DeviceUpload,
    db: Session = Depends(get_db),
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """接收设备上传的服药照片（base64 解码后落盘，HuskyLens 采集）"""
    user = DeviceService.get_device_user_authed(db, req.device_id, device_token)
    path = DeviceService.save_upload(db, user, req.image_base64, req.note)
    return {"status": "ok", "path": path}


@router.get("/device/status/{device_id}")
async def get_device_status(
    device_id: str,
    db: Session = Depends(get_db),
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """获取设备状态信息（供子女端查询，校验 device_id 与 X-Device-Token）"""
    logger.info(f"查询设备状态: {mask_device_id(device_id or '')}")
    user = DeviceService.get_device_user_authed(db, device_id, device_token)
    return DeviceService.compute_status(db, user, device_id)


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
        logger.info(f"设备AI提问: {mask_device_id(req.device_id or '')} - {req.question}")
        user = DeviceService.get_device_user_authed(db, req.device_id, device_token)

    answer = await AIService.ask(req.question, **(get_effective_config(db, user) if user else {}))

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
async def check_device(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """检查设备是否已注册（供子女端绑定时校验，仅返回 exists，不泄露敏感信息）

    查找逻辑：优先 device_id 字段，回退 username。
    """
    DeviceService.get_device_user(db, device_id)  # 未注册则抛 404
    return {"exists": True}


@router.get("/device/schedule/{device_id}")
async def get_device_schedule(
    device_id: str,
    db: Session = Depends(get_db),
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """获取设备的用药计划（供老人端每分钟轮询，校验 device_id 与 X-Device-Token）"""
    user = DeviceService.get_device_user_authed(db, device_id, device_token)
    schedules = DeviceService.get_schedule(db, user)
    return {
        "device_id": device_id,
        "device_name": user.username,
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
    user = DeviceService.get_device_user_authed(db, req.device_id, device_token)

    plan_data = MedicationPlanCreate(
        drug_name=req.drug_name,
        dosage=req.dosage,
        product_code=req.product_code,
        frequency=req.frequency,
        schedule_times=req.schedule_times,
        total_quantity=req.total_quantity,
        remaining_quantity=req.remaining_quantity,
        unit=req.unit,
        low_stock_threshold=req.low_stock_threshold,
    )
    plan = MedicationService.create_plan(db, user.id, plan_data)
    logger.info(f"家属为设备 {mask_device_id(req.device_id or '')} 设置用药计划: {req.drug_name}")

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
    user = DeviceService.get_device_user_authed(db, device_id, device_token)
    plans = DeviceService.get_plans(db, user)
    return {"device_id": device_id, "plans": plans}


@router.get("/device/records/{device_id}")
async def get_device_records(
    device_id: str,
    limit: int = 100,
    db: Session = Depends(get_db),
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """获取设备的服药记录（供子女端 BFF 调用，校验 device_id 与 X-Device-Token）"""
    user = DeviceService.get_device_user_authed(db, device_id, device_token)
    records = DeviceService.get_records(db, user, limit)
    return {"device_id": device_id, "records": records}


@router.get("/device/chat_history/{device_id}")
async def get_device_chat_history(
    device_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """获取设备相关的聊天历史（供子女端 BFF 调用，校验 device_id 与 X-Device-Token）"""
    user = DeviceService.get_device_user_authed(db, device_id, device_token)
    messages = DeviceService.get_chat_history(db, user, limit)
    return {"device_id": device_id, "messages": messages}


@router.delete("/device/medication_plan/{plan_id}")
async def delete_device_medication_plan(
    plan_id: int,
    device_id: str,
    db: Session = Depends(get_db),
    device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """删除用药计划（校验 device_id 与 X-Device-Token 及设备归属）"""
    user = DeviceService.get_device_user_authed(db, device_id, device_token)
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
    user = DeviceService.get_device_user_authed(db, req.device_id, device_token)

    plan_data = MedicationPlanCreate(
        drug_name=req.drug_name,
        dosage=req.dosage,
        product_code=req.product_code,
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

    logger.info(
        f"家属为设备 {mask_device_id(req.device_id or '')} 更新用药计划 {plan_id}: {req.drug_name}"
    )

    return {
        "status": "ok",
        "plan_id": plan.id,
        "drug_name": plan.drug_name,
        "schedule_times": plan.schedule_times,
    }
