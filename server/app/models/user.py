# -*- coding: utf-8 -*-
from sqlalchemy import Column, Integer, String, Boolean, LargeBinary, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.core.database import Base, UTCDateTime


def _utcnow():
    """返回带时区的当前 UTC 时间（写入数据库时由 UTCDateTime 统一转为 naive UTC）"""
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    # 昵称（展示名，可重复、非登录键；登录唯一标识为 phone）
    username = Column(String(50), nullable=True, index=True)
    # OAuth 用户（如 GitHub 登录）可不设密码，故允许为空
    hashed_password = Column(String(255), nullable=True)
    role = Column(String(20), nullable=False)  # "elderly" 或 "family"
    # 手机号：登录唯一标识（必填、唯一；邮箱验证码自动注册的用户为 NULL）
    phone = Column(String(20), nullable=True, unique=True, index=True)
    group_id = Column(Integer, nullable=True)  # 家庭组ID，老人和家属同组
    created_at = Column(UTCDateTime, default=_utcnow)
    # 账号启用状态与最后登录时间
    is_active = Column(Boolean, default=True)
    last_login_at = Column(UTCDateTime, nullable=True)
    last_heartbeat_at = Column(UTCDateTime, nullable=True)
    # 设备ID：家属绑定老人时，把 device_id 关联到真实老人用户
    # 解决"设备即用户"设计缺陷：原设计 device/register 会创建虚拟老人用户，
    # 导致家属绑定、设备状态查询、删除用药计划等接口因 user_id 不一致而失败。
    # 新逻辑：device_id 关联到真实老人后，所有 device_id 查询都能反查到真实老人。
    # 兼容旧数据：未绑定的虚拟用户 device_id 字段为 None，仍走 username == device_id 回退。
    device_id = Column(String(64), nullable=True, unique=True, index=True)
    # 设备访问令牌：register_device 时生成，设备端点需通过 X-Device-Token 校验
    device_token = Column(String(64), nullable=True, index=True)
    # ===== GitHub OAuth 关联字段 =====
    # GitHub 用户唯一 ID（首次 OAuth 登录绑定，唯一索引），非 GitHub 用户为 NULL
    github_id = Column(Integer, nullable=True, unique=True, index=True)
    # OAuth 提供方标识，如 "github" / "gitee"；本地注册用户为 NULL
    oauth_provider = Column(String(20), nullable=True)
    # Gitee OAuth 关联字段（与 github 对称）
    # Gitee 用户唯一 ID（首次 OAuth 登录绑定，唯一索引），非 Gitee 用户为 NULL
    gitee_id = Column(Integer, nullable=True, unique=True, index=True)
    # 第三方 OAuth 返回的邮箱（如 Gitee 已授权 emails 权限），本地用户为 NULL
    email = Column(String(255), nullable=True)

    # ===== TOTP 第二因子（密码后的第二因子，issue：新增登录方式） =====
    # TOTP 共享密钥（base32），使用 crypto.encrypt_text 加密存储，未开启时为 NULL
    totp_secret = Column(String(255), nullable=True)
    # 是否已开启 TOTP 第二因子（false 时登录仅需密码；true 时登录需再输入动态码）
    mfa_enabled = Column(Boolean, default=False, nullable=False)
    # 备用恢复码（bcrypt 哈希后的 JSON 列表，明文仅在开启时返回一次），未开启为 NULL
    backup_codes = Column(Text, nullable=True)
    # 通知偏好设置（JSON 字符串，记录各通知开关：用药提醒/漏服提醒/设备离线/浏览器通知/声音）
    # 允许为 NULL（未设置时前端按默认全部开启处理）
    notification_settings = Column(Text, nullable=True)

    # 关联关系
    medication_plans = relationship("MedicationPlan", back_populates="user", cascade="all, delete-orphan")
    medication_records = relationship("MedicationRecord", back_populates="user", cascade="all, delete-orphan")
    ai_query_logs = relationship("AIQueryLog", back_populates="user", cascade="all, delete-orphan")
    webauthn_credentials = relationship("WebAuthnCredential", back_populates="user", cascade="all, delete-orphan")


class WebAuthnCredential(Base):
    """WebAuthn / Passkey 凭证表

    一个用户可登记多把通行密钥（平台/外接安全密钥均可）。登录时按 credential_id
    反查用户并签发 JWT，实现无用户名（usernameless）passkey 登录。
    """
    __tablename__ = "webauthn_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 凭证 ID（base64url），全局唯一
    credential_id = Column(String(512), unique=True, nullable=False, index=True)
    # COSE 编码的公钥（字节），用于后续断言验证
    public_key = Column(LargeBinary, nullable=False)
    # 已记录的签名计数器，防止重放攻击
    sign_count = Column(Integer, default=0, nullable=False)
    # 支持的传输方式（JSON 列表，如 ["usb","ble","internal"]），可空
    transports = Column(Text, nullable=True)
    # 用户自定义昵称（如「我的手机」「YubiKey」），可空
    nickname = Column(String(100), nullable=True)
    created_at = Column(UTCDateTime, default=_utcnow, nullable=False)
    last_used_at = Column(UTCDateTime, nullable=True)

    user = relationship("User", back_populates="webauthn_credentials")
