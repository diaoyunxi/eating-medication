# -*- coding: utf-8 -*-
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.core.database import Base


def _utcnow():
    """返回带时区的当前 UTC 时间"""
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(20), unique=True, index=True, nullable=False)
    # OAuth 用户（如 GitHub 登录）可不设密码，故允许为空
    hashed_password = Column(String, nullable=True)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "elderly" 或 "family"
    phone = Column(String, nullable=True)
    group_id = Column(Integer, nullable=True)  # 家庭组ID，老人和家属同组
    created_at = Column(DateTime, default=_utcnow)
    # 账号启用状态与最后登录时间
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime, nullable=True)
    last_heartbeat_at = Column(DateTime, nullable=True)
    # 设备ID：家属绑定老人时，把 device_id 关联到真实老人用户
    # 解决"设备即用户"设计缺陷：原设计 device/register 会创建虚拟老人用户，
    # 导致家属绑定、设备状态查询、删除用药计划等接口因 user_id 不一致而失败。
    # 新逻辑：device_id 关联到真实老人后，所有 device_id 查询都能反查到真实老人。
    # 兼容旧数据：未绑定的虚拟用户 device_id 字段为 None，仍走 username == device_id 回退。
    device_id = Column(String, nullable=True, unique=True, index=True)
    # 设备访问令牌：register_device 时生成，设备端点需通过 X-Device-Token 校验
    device_token = Column(String(64), nullable=True, index=True)
    # ===== GitHub OAuth 关联字段 =====
    # GitHub 用户唯一 ID（首次 OAuth 登录绑定，唯一索引），非 GitHub 用户为 NULL
    github_id = Column(Integer, nullable=True, unique=True, index=True)
    # OAuth 提供方标识，如 "github"；本地注册用户为 NULL
    oauth_provider = Column(String(20), nullable=True)

    # 关联关系
    medication_plans = relationship("MedicationPlan", back_populates="user", cascade="all, delete-orphan")
    medication_records = relationship("MedicationRecord", back_populates="user", cascade="all, delete-orphan")
    ai_query_logs = relationship("AIQueryLog", back_populates="user", cascade="all, delete-orphan")
