# -*- coding: utf-8 -*-
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import datetime

class UserOut(BaseModel):
    """用户信息响应"""
    id: int
    username: Optional[str] = None  # 昵称
    role: str
    phone: Optional[str] = None
    email: Optional[str] = None
    group_id: Optional[int] = None
    # 设备ID（老人绑定设备后填充，家属为 None）
    device_id: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class UserUpdate(BaseModel):
    """更新用户信息请求（昵称与手机号均可修改，二选一或全部）"""
    username: Optional[str] = Field(None, max_length=50, description="昵称")
    phone: Optional[str] = Field(None, description="手机号")

class BindFamilyReq(BaseModel):
    """家属绑定老人请求"""
    elderly_user_id: int = Field(..., description="老人用户ID")
    # 弱保护：家属必须知道老人的设备ID（老人用户名即设备注册时的 device_id）
    device_id: str = Field(..., description="老人设备ID（弱保护：需知道设备ID才能绑定）")
