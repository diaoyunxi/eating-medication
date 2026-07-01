# -*- coding: utf-8 -*-
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
import secrets
from app.core.config import settings

# 使用 bcrypt 但设置正确的 rounds
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

# L10：当前使用 HS256 对称加密，适用于单服务部署。
# 微服务场景应改用 RS256 非对称加密（公钥验签、私钥签发），避免多服务共享密钥。


def hash_password(password: str) -> str:
    """哈希密码"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


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
