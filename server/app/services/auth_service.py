# -*- coding: utf-8 -*-
from sqlalchemy.orm import Session
from typing import Optional
from app.models.user import User
from app.schemas.auth import RegisterReq
from app.core.security import hash_password, verify_password, create_access_token

class AuthService:
    """认证服务"""

    @staticmethod
    def register(db: Session, req: RegisterReq) -> str:
        """用户注册，返回 access_token"""
        # 检查用户名是否已存在
        existing = db.query(User).filter(User.username == req.username).first()
        if existing:
            raise ValueError("用户名已存在")

        # 创建新用户
        user = User(
            username=req.username,
            hashed_password=hash_password(req.password),
            full_name=req.full_name,
            role=req.role,
            phone=req.phone,
            group_id=None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        return create_access_token(data={"sub": user.id})

    @staticmethod
    def login(db: Session, username: str, password: str) -> Optional[str]:
        """用户登录，返回 access_token，失败返回 None"""
        user = db.query(User).filter(User.username == username).first()
        if not user or not verify_password(password, user.hashed_password):
            return None
        return create_access_token(data={"sub": user.id})