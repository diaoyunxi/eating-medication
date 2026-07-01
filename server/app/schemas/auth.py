# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field, field_validator
from typing import Optional
# M12：在 register schema 中调用 validators 进行格式校验
from app.utils.validators import is_valid_phone, is_valid_username, is_valid_password


class RegisterReq(BaseModel):
    """用户注册请求"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    full_name: str = Field(..., min_length=1, max_length=50, description="姓名")
    role: str = Field(..., description="角色: elderly 或 family")
    phone: Optional[str] = Field(None, description="手机号")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        if v not in ["elderly", "family"]:
            raise ValueError("role 必须是 elderly 或 family")
        return v

    # M12：使用 validators 校验手机号格式
    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        if not is_valid_phone(v):
            raise ValueError("手机号格式不正确")
        return v

    # M12：使用 validators 校验用户名格式
    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if not is_valid_username(v):
            raise ValueError("用户名格式不正确（3-20位字母数字下划线）")
        return v

    # M12：使用 validators 校验密码强度
    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if not is_valid_password(v):
            raise ValueError("密码必须包含字母和数字，长度6-100位")
        return v


class LoginReq(BaseModel):
    """用户登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class TokenResp(BaseModel):
    """Token 响应"""
    access_token: str
    token_type: str = "bearer"
