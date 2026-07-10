# -*- coding: utf-8 -*-
import bcrypt
from jose import jwt
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
import secrets
from app.core.config import settings

# F-05 修复：移除 passlib（与 bcrypt 4.x 不兼容），改用 bcrypt 原生 API
# 密码哈希 rounds 固定为 12，与原 passlib 配置一致

# L10：当前使用 HS256 对称加密，适用于单服务部署。
# 微服务场景应改用 RS256 非对称加密（公钥验签、私钥签发），避免多服务共享密钥。


def hash_password(password: str) -> str:
    """哈希密码

    :param password: 明文密码
    :return: bcrypt 哈希字符串（含 salt 与 rounds）
    """
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12))
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码

    :param plain_password: 明文密码
    :param hashed_password: bcrypt 哈希字符串
    :return: 匹配返回 True，否则 False
    """
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        # 哈希格式非法或为空时返回 False，避免抛出异常
        return False


def create_access_token(data: Dict[str, Any], expires_delta: timedelta = None) -> str:
    """创建 JWT access token"""
    to_encode = data.copy()
    # H7：统一 sub 为字符串类型
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])
    # H7：增加 token 类型与唯一标识
    to_encode.setdefault("type", "access")
    to_encode.setdefault("jti", secrets.token_urlsafe(16))
    # M14：使用带时区的 UTC 时间
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """解码 JWT token"""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
