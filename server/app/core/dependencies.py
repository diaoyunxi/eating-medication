# -*- coding: utf-8 -*-
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import JWTError
from app.core.database import SessionLocal
from app.core.security import decode_token
from app.models.user import User
from typing import Callable

security = HTTPBearer(auto_error=False)


def get_db():
    """获取数据库会话依赖（M17：统一入口，从 database.py 迁移至此）"""
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
        # H7：sub 统一为字符串，解码后转为 int
        sub = payload.get("sub")
        if sub is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的 token")
        user_id = int(sub)
    except (JWTError, ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的 token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    # L9：校验用户是否启用
    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户已被禁用")
    return user


def require_role(*allowed_roles: str) -> Callable:
    """G4 修复：角色校验依赖工厂，避免各端点散落 if role != xxx 判断

    用法：current_user: User = Depends(require_role("elderly"))
    """
    async def _role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"该操作仅允许 {', '.join(allowed_roles)} 角色执行"
            )
        return current_user
    return _role_checker
