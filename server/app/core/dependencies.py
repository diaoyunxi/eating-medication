# -*- coding: utf-8 -*-
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import JWTError
from app.core.database import SessionLocal
from app.core.security import decode_token
from app.models.user import User

security = HTTPBearer(auto_error=False)


def get_db():
    """获取数据库会话依赖（统一入口，从 database.py 迁移至此）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    从 JWT token 获取当前登录用户，如果无效则抛出 401 异常
    """
    if credentials is None:
        # 缺失 Authorization 头时返回 401（HTTPBearer 默认返回 403，不符合规范）
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供认证凭证")
    token = credentials.credentials
    try:
        payload = decode_token(token)
        # sub 统一为字符串，解码后转为 int
        sub = payload.get("sub")
        if sub is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的 token")
        user_id = int(sub)
    except (JWTError, ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的 token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    # 校验用户是否启用
    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户已被禁用")
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """可选认证：返回当前登录用户或 None（不抛 401）。

    用于登录页等公开场景：未携带/无效 token 时返回 None，由调用方决定
    返回系统级信息（如登录方式启用状态）而非拒绝访问（BUG-C07）。
    """
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials)
        sub = payload.get("sub")
        if sub is None:
            return None
        user = db.query(User).filter(User.id == int(sub)).first()
        return user
    except (JWTError, ValueError, TypeError):
        return None
