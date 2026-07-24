# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field, field_validator
from typing import Optional
# register schema 中调用 validators 进行格式校验
from app.utils.validators import is_valid_phone, is_valid_password, is_valid_email


class RegisterReq(BaseModel):
    """用户注册请求

    登录方式变更（issue #3）：
    - phone 为唯一登录标识（必填）
    - username 作为昵称（可选，不再作为登录名）
    - full_name 已废弃，昵称统一使用 username
    """
    phone: str = Field(..., min_length=11, max_length=11, description="手机号（唯一登录标识）")
    username: Optional[str] = Field(None, max_length=50, description="昵称（可选）")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    role: str = Field(..., description="角色: elderly 或 family")
    # Cloudflare Turnstile 人机验证令牌（前端提交，后端调 siteverify 校验）
    cf_turnstile_token: Optional[str] = Field(None, description="Cloudflare Turnstile 令牌")
    # GitHub/Gitee OAuth 补全注册时携带的短期身份令牌（由 server 回调签发）；为空表示普通注册
    oauth_token: Optional[str] = Field(None, description="GitHub/Gitee OAuth 身份令牌")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        if v not in ["elderly", "family"]:
            raise ValueError("role 必须是 elderly 或 family")
        return v

    # 使用 validators 校验手机号格式
    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        if not is_valid_phone(v):
            raise ValueError("手机号格式不正确")
        return v

    # 昵称允许中文等自由文本，仅做空值与长度校验
    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if v is None:
            return v
        v = v.strip()
        return v or None

    # 使用 validators 校验密码强度
    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if not is_valid_password(v):
            raise ValueError("密码必须包含字母和数字，长度6-100位")
        return v


class LoginReq(BaseModel):
    """用户登录请求（手机号 + 密码）"""
    phone: str = Field(..., description="手机号")
    password: str = Field(..., description="密码")
    # Cloudflare Turnstile 人机验证令牌（前端提交，后端调 siteverify 校验）
    cf_turnstile_token: Optional[str] = Field(None, description="Cloudflare Turnstile 令牌")


class TokenResp(BaseModel):
    """Token 响应"""
    access_token: str
    token_type: str = "bearer"


class EmailSendCodeReq(BaseModel):
    """邮箱验证码 - 发送验证码请求"""
    email: str = Field(..., description="收件邮箱")
    cf_turnstile_token: Optional[str] = Field(None, description="Cloudflare Turnstile 令牌")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if not is_valid_email(v):
            raise ValueError("邮箱格式不正确")
        return v


class EmailCodeLoginReq(BaseModel):
    """邮箱验证码 - 登录/注册请求"""
    email: str = Field(..., description="邮箱")
    code: str = Field(..., min_length=4, max_length=8, description="6 位数字验证码")
    cf_turnstile_token: Optional[str] = Field(None, description="Cloudflare Turnstile 令牌")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if not is_valid_email(v):
            raise ValueError("邮箱格式不正确")
        return v
