# -*- coding: utf-8 -*-
import logging
import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import get_current_user, get_db
from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserOut, UserUpdate, BindFamilyReq
from app.services.user_service import UserService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["用户"])

@router.get("/me", response_model=UserOut)
def read_current_user(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return current_user

@router.put("/me", response_model=UserOut)
def update_current_user(
    update_data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新当前用户信息"""
    updated = UserService.update_user(db, current_user.id, update_data)
    if not updated:
        raise HTTPException(status_code=400, detail="更新失败")
    return updated

@router.post("/bind")
def bind_family(
    req: BindFamilyReq,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """家属绑定老人（组成家庭组，H13：需提供老人的设备ID 作为弱保护）"""
    if current_user.role != "family":
        raise HTTPException(status_code=403, detail="只有家属可以发起绑定")

    elderly = db.query(User).filter(User.id == req.elderly_user_id, User.role == "elderly").first()
    if not elderly:
        raise HTTPException(status_code=400, detail="绑定失败，请检查用户ID或角色")

    # H13：弱保护——老人用户名即设备注册时的 device_id，家属必须提供正确的 device_id
    # 注意：User 模型暂无独立 device_id 字段，此处以 username 作为设备ID校验
    if elderly.username != req.device_id:
        raise HTTPException(status_code=400, detail="设备ID不匹配，请确认老人的设备ID")
    # TODO: 实现双向确认机制（当前仅弱保护：家属知道设备ID即可绑定）
    logger.warning("TODO: 实现双向确认机制（当前仅弱保护：家属知道设备ID即可绑定）")

    group_id = UserService.bind_family(db, req.elderly_user_id, current_user.id)
    if not group_id:
        raise HTTPException(status_code=400, detail="绑定失败，请检查用户ID或角色")
    return {"group_id": group_id}


@router.get("/device-token")
def get_device_token(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """家属获取老人端 device_token（需 JWT 认证）

    由于 device_token 只存储了哈希值，无法反推明文，因此会生成新的 token 并返回。
    注意：生成新 token 后，老人端下次心跳会发现 token 失效，需要重新注册获取新 token。
    """
    # 仅允许家属角色
    if current_user.role != "family":
        raise HTTPException(status_code=403, detail="只有家属可以获取设备 token")

    # 查找设备用户
    elderly_user = db.query(User).filter(
        User.username == device_id,
        User.role == "elderly"
    ).first()
    if not elderly_user:
        raise HTTPException(status_code=404, detail="设备未注册")

    # 生成新的 device_token
    device_token = secrets.token_urlsafe(32)
    elderly_user.hashed_password = hash_password(device_token)
    db.commit()

    logger.info(f"家属 {current_user.username} 获取设备 {device_id} 的 token")

    return {
        "device_id": device_id,
        "device_token": device_token,
        "message": "请注意：老人端下次心跳会发现 token 失效，需要重新注册获取新 token"
    }
