# -*- coding: utf-8 -*-
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import datetime

class UserOut(BaseModel):
    """用户信息响应"""
    id: int
    username: str
    full_name: str
    role: str
    phone: Optional[str] = None
    group_id: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class UserUpdate(BaseModel):
    """更新用户信息请求"""
    full_name: Optional[str] = Field(None, min_length=1, max_length=50)
    phone: Optional[str] = None

class BindFamilyReq(BaseModel):
    """家属绑定老人请求"""
    elderly_user_id: int = Field(..., description="老人用户ID")