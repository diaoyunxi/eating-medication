# -*- coding: utf-8 -*-
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta
from typing import Dict, Any
from app.core.config import settings

# 使用 bcrypt 但设置正确的 rounds
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

def hash_password(password: str) -> str:
    """哈希密码"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: Dict[str, Any], expires_delta: timedelta = None) -> str:
    """创建 JWT access token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_token(token: str) -> Dict[str, Any]:
    """解码 JWT token"""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])