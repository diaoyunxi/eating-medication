# -*- coding: utf-8 -*-
"""家属授权设备接口 - 供子女端（已登录家属）查询/管理其绑定的设备。

本模块与 public.py（设备公开接口，靠 X-Device-Token 鉴权）是两套独立鉴权：

- public.py 面向「设备本人」（老人端），用设备令牌证明"我是这台设备"。
- 本模块面向「已登录家属」（子女端网页），用 JWT 证明"我是登录的家属"，
  并校验该家属已绑定目标设备（current_user.device_id == device_id）。

此前子女端复用 public.py 的设备 token 接口，但设备令牌只存在于老人端本机、
服务端对已注册设备不再下发，导致子女端拿到空令牌 → /device/status 返回 403 →
子女端状态显示离线（见 issue）。本模块让家属用自身登录态访问设备数据，
不再依赖老人端设备令牌；bind 端点会在家属合法绑定后下发设备令牌（供家属侧
本地保存、用于后续设备行为写操作），从根本上解决空令牌问题。

路由层仅负责 I/O（请求模型、Header、响应）；设备状态/计划/记录等纯逻辑
复用 app.services.device_service.DeviceService，避免重复实现。
"""
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.core.security import mask_device_id
from app.models.medication_plan import MedicationPlan
from app.services.medication_service import MedicationService
from app.services.device_service import DeviceService
from app.schemas.medication import MedicationPlanCreate
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/family/device", tags=["家属设备接口"])

_ONLINE_THRESHOLD_SECONDS = 60


class FamilyBindReq(BaseModel):
    """家属绑定设备请求"""
    device_id: str
    device_name: Optional[str] = None


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


def _require_bound_device(current_user: User, db: Session, device_id: str) -> User:
    """校验当前登录家属已绑定目标设备，并返回设备对应的用户对象。

    :raises HTTPException 403: 当前用户未绑定该设备
    :raises HTTPException 404: 设备未注册（数据不一致保护）
    """
    if not current_user.device_id or current_user.device_id != device_id:
        raise HTTPException(
            status_code=403,
            detail="当前账号未绑定该设备，请先在设置页绑定设备",
        )
    # 反查设备对应的真实老人用户（device_id 字段或 username 回退）
    user = DeviceService.get_device_user(db, device_id)
    return user


@router.post("/bind")
async def bind_device(
    req: FamilyBindReq,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """家属绑定设备并合法获取设备令牌。

    弱保护：需知道设备 ID（device_id）。校验设备已注册后，将当前登录家属的
    device_id 设为该设备，并返回该设备的 device_token，供子女端本地保存。
    该令牌使家属侧在调用需设备令牌的写操作（如下线/上传，若后续需要）时
    拥有合法凭据，解决此前"已注册设备不再下发令牌导致空令牌 403"的问题。

    :return: {"status": "ok", "device_id": str, "device_name": str, "device_token": str}
    """
    # 设备必须已注册（老人端已开机上报过），否则无法绑定
    try:
        user = DeviceService.get_device_user(db, req.device_id)
    except HTTPException:
        raise HTTPException(status_code=404, detail="设备未注册，请先让老人端开机联网")

    # 弱保护：设备须曾上报过心跳（即老人端确实在线/存在），避免仅凭 device_id
    # 即可绑定一个从不在线、可能属他人的设备。device_id 本身为 15 位随机整数，
    # 不可猜测；此处进一步要求"设备存在且曾被使用"，降低越权绑定风险。
    if user.last_heartbeat_at is None:
        raise HTTPException(
            status_code=409,
            detail="设备尚未联机，请先让老人端开机联网后再绑定",
        )

    # 家属账号持有该设备关联（复用 User.device_id 字段，语义与老人侧一致）
    current_user.device_id = req.device_id
    if req.device_name and not user.username:
        user.username = req.device_name
    db.commit()
    logger.info(
        f"家属绑定设备成功: user={current_user.id} device={mask_device_id(req.device_id)}"
    )
    return {
        "status": "ok",
        "device_id": req.device_id,
        "device_name": user.username or req.device_name or "",
        "device_token": user.device_token or "",
    }


@router.post("/unbind")
async def family_device_unbind(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """家属解绑当前设备（JWT 鉴权）。

    将当前家属账号的 device_id 置空，清除服务端绑定关系；仅清服务端，不涉及
    老人端设备本身。前端在服务端解绑成功后再清理本地 bound_device.json，避免
    "前端已解绑、服务端仍绑定" 的不一致。

    :return: {"status": "ok", "message": "设备已解绑"}
    """
    if current_user.device_id:
        logger.info(
            f"家属解绑设备: user={current_user.id} device={mask_device_id(current_user.device_id)}"
        )
        current_user.device_id = None
        db.commit()
    return {"status": "ok", "message": "设备已解绑"}


@router.get("/status/{device_id}")
async def family_device_status(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取绑定设备的状态（供子女端查询，JWT 鉴权 + 设备绑定校验）"""
    logger.info(f"家属查询设备状态: {mask_device_id(device_id or '')} user={current_user.id}")
    user = _require_bound_device(current_user, db, device_id)
    return DeviceService.compute_status(db, user, device_id)


@router.get("/plans/{device_id}")
async def family_device_plans(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取绑定设备的所有用药计划（JWT 鉴权 + 设备绑定校验）"""
    user = _require_bound_device(current_user, db, device_id)
    plans = DeviceService.get_plans(db, user)
    return {"device_id": device_id, "plans": plans}


@router.get("/records/{device_id}")
async def family_device_records(
    device_id: str,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取绑定设备的服药记录（JWT 鉴权 + 设备绑定校验）"""
    user = _require_bound_device(current_user, db, device_id)
    records = DeviceService.get_records(db, user, limit)
    return {"device_id": device_id, "records": records}


@router.get("/chat_history/{device_id}")
async def family_device_chat_history(
    device_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取绑定设备相关的聊天历史（JWT 鉴权 + 设备绑定校验）"""
    user = _require_bound_device(current_user, db, device_id)
    messages = DeviceService.get_chat_history(db, user, limit)
    return {"device_id": device_id, "messages": messages}


@router.get("/reminders/{device_id}")
async def family_device_reminders(
    device_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取绑定设备的今日提醒（供子女端仪表盘，JWT 鉴权 + 设备绑定校验）。

    基于用药计划生成今日各时点的服药提醒，并关联已上报的服药记录标记完成状态。
    """
    user = _require_bound_device(current_user, db, device_id)
    reminders = DeviceService.get_reminders(db, user, limit)
    return {"device_id": device_id, "reminders": reminders}


@router.post("/medication_plan")
async def family_set_medication_plan(
    req: FamilyMedicationPlan,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """家属为绑定设备设置用药计划（JWT 鉴权 + 设备绑定校验）"""
    user = _require_bound_device(current_user, db, req.device_id)
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
    logger.info(
        f"家属为设备 {mask_device_id(req.device_id or '')} 设置用药计划: {req.drug_name}"
    )
    return {
        "status": "ok",
        "plan_id": plan.id,
        "drug_name": plan.drug_name,
        "schedule_times": plan.schedule_times,
    }


@router.put("/medication_plan/{plan_id}")
async def family_update_medication_plan(
    plan_id: int,
    req: FamilyMedicationPlan,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新绑定设备的用药计划（JWT 鉴权 + 设备绑定校验）"""
    user = _require_bound_device(current_user, db, req.device_id)
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
        f"家属更新设备 {mask_device_id(req.device_id or '')} 用药计划 {plan_id}: {req.drug_name}"
    )
    return {
        "status": "ok",
        "plan_id": plan.id,
        "drug_name": plan.drug_name,
        "schedule_times": plan.schedule_times,
    }


@router.delete("/medication_plan/{plan_id}")
async def family_delete_medication_plan(
    plan_id: int,
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除绑定设备的用药计划（JWT 鉴权 + 设备绑定校验）"""
    user = _require_bound_device(current_user, db, device_id)
    plan = db.query(MedicationPlan).filter(
        MedicationPlan.id == plan_id,
        MedicationPlan.user_id == user.id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在或不属于该设备")
    db.delete(plan)
    db.commit()
    return {"status": "ok"}
