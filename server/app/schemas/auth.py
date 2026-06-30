# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field, field_validator
from typing import Optional

class RegisterReq(BaseModel):
    """用户注册请求"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    full_name: str = Field(..., min_length=1, max_length=50, description="姓名")
    role: str = Field(..., description="角色: elderly 或 family")
    phone: Optional[str] = Field(None, description="手机号")

    @field_validator("role")
    def validate_role(cls, v):
        if v not in ["elderly", "family"]:
            raise ValueError("role 必须是 elderly 或 family")
        return v

    @field_validator("phone")
    def validate_phone(cls, v):
        if v is not None and not v.isdigit():
            raise ValueError("手机号必须为数字")
        return v

class LoginReq(BaseModel):
    """用户登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")

class TokenResp(BaseModel):
    """Token 响应"""
    access_token: str
    token_type: str = "bearer"