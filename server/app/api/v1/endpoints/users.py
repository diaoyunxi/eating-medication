# -*- coding: utf-8 -*-
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import get_current_user, get_db
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
    """家属绑定老人（组成家庭组，并把 device_id 关联到真实老人）

    修复"设备即用户"设计缺陷后的绑定逻辑：
    1. 家属身份校验
    2. 校验目标用户是真实老人
    3. H13 弱保护：校验 device_id 对应的虚拟用户存在（即设备已通过 device/register 注册）
       - 若虚拟用户不存在，说明设备未注册或 device_id 错误
       - 若虚拟用户存在，绑定后会被迁移数据并删除，device_id 关联到真实老人
    4. 调用 UserService.bind_family 完成数据迁移 + device_id 关联 + 家庭组绑定

    :param req: 绑定请求（elderly_user_id + device_id）
    :param db: 数据库会话
    :param current_user: 当前登录用户（必须是家属）
    :return: {"group_id": int}
    """
    if current_user.role != "family":
        raise HTTPException(status_code=403, detail="只有家属可以发起绑定")

    elderly = db.query(User).filter(User.id == req.elderly_user_id, User.role == "elderly").first()
    if not elderly:
        raise HTTPException(status_code=400, detail="绑定失败，请检查用户ID或角色")

    # H13 弱保护：校验 device_id 对应的设备已注册
    # 修复后逻辑：
    # - 优先查 device_id 字段（已被其他老人绑定的情况）
    # - 回退查 username == device_id（虚拟用户，待迁移）
    existing_device_user = db.query(User).filter(User.device_id == req.device_id).first()
    virtual_user = db.query(User).filter(User.username == req.device_id).first()

    if not existing_device_user and not virtual_user:
        # 设备未注册，家属无法绑定
        raise HTTPException(status_code=400, detail="设备ID未注册，请先让老人端设备开机注册")

    # 如果 device_id 已被其他老人占用
    if existing_device_user and existing_device_user.id != req.elderly_user_id:
        raise HTTPException(status_code=400, detail="设备ID已被其他老人绑定")

    # 如果 elderly 自身已绑定该 device_id，说明重复绑定，直接返回成功
    if elderly.device_id == req.device_id:
        # 已绑定，确保家属加入家庭组
        group_id = UserService.bind_family(db, req.elderly_user_id, current_user.id, device_id=None)
        if not group_id:
            raise HTTPException(status_code=400, detail="绑定失败，请检查用户ID或角色")
        return {"group_id": group_id, "message": "设备已绑定，家属已加入家庭组"}

    # TODO: 实现双向确认机制（当前仅弱保护：家属知道设备ID即可绑定）
    logger.warning("TODO: 实现双向确认机制（当前仅弱保护：家属知道设备ID即可绑定）")

    # 调用服务层：迁移虚拟用户数据 + 关联 device_id 到真实老人 + 家庭组绑定
    group_id = UserService.bind_family(db, req.elderly_user_id, current_user.id, device_id=req.device_id)
    if not group_id:
        raise HTTPException(status_code=400, detail="绑定失败，可能是设备ID已被其他老人占用或参数错误")
    return {"group_id": group_id}


@router.delete("/me")
def delete_current_user(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """注销当前用户账号（硬删除，会级联删除用药计划/记录/AI日志）"""
    if not UserService.delete_user(db, current_user.id):
        # 防御性处理：current_user 通过鉴权必然存在，理论上不会走到这里
        raise HTTPException(status_code=404, detail="用户不存在")
    logger.info("用户注销账号: id=%s, username=%s", current_user.id, current_user.username)
    return {"status": "success", "message": "账号已删除"}


@router.delete("/{user_id}")
def delete_user_by_family(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """家属删除同家庭组的老人账号（硬删除）"""
    # 仅家属可调用
    if current_user.role != "family":
        raise HTTPException(status_code=403, detail="只有家属可以删除老人账号")
    # 禁止删除自己（家属注销自己应走 /me）
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己，请使用 /users/me 注销账号")
    # 家属必须已加入家庭组
    if current_user.group_id is None:
        raise HTTPException(status_code=400, detail="尚未绑定老人，无法执行删除")
    # 查询目标用户
    target = UserService.get_user_by_id(db, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 目标必须是老人
    if target.role != "elderly":
        raise HTTPException(status_code=403, detail="只能删除老人账号")
    # 必须在同一家庭组
    if target.group_id != current_user.group_id:
        raise HTTPException(status_code=403, detail="只能删除同家庭组的老人")
    # 执行硬删除（级联删除其用药计划/记录/AI日志）
    if not UserService.delete_user(db, user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    logger.info("家属删除老人: family_id=%s, elderly_id=%s", current_user.id, user_id)
    return {"status": "success", "message": "老人账号已删除"}
