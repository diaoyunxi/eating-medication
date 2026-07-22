# -*- coding: utf-8 -*-
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone
from app.models.user import User
from app.schemas.auth import RegisterReq
from app.core.security import hash_password, verify_password, create_access_token


class AuthService:
    """认证服务"""

    @staticmethod
    def register(db: Session, req: RegisterReq, oauth_pending: dict = None) -> str:
        """用户注册，返回 access_token

        :param oauth_pending: GitHub OAuth 待补全身份令牌载荷（dict），非空表示 OAuth 注册，
                              将绑定 github_id 并写入 oauth_provider="github"。
        """
        # ===== GitHub OAuth 注册：绑定 github_id =====
        github_id = None
        oauth_provider = None
        if oauth_pending:
            github_id = oauth_pending.get("github_id")
            oauth_provider = "github"
            # 双保险：确认该 GitHub 账号尚未绑定其他本地账号
            if github_id:
                bound = db.query(User).filter(User.github_id == github_id).first()
                if bound:
                    raise ValueError("该 GitHub 账号已绑定其他用户")

        # 用户名冲突自动加数字后缀（如 octocat -> octocat2），保证唯一
        base_username = req.username
        username = base_username
        suffix = 1
        while db.query(User).filter(User.username == username).first():
            suffix += 1
            username = f"{base_username}{suffix}"[:20]

        # 创建新用户
        user = User(
            username=username,
            hashed_password=hash_password(req.password),
            full_name=req.full_name,
            role=req.role,
            phone=req.phone,
            group_id=None,
            github_id=github_id,
            oauth_provider=oauth_provider,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # H7：sub 统一为字符串（在 create_access_token 内部转换）
        return create_access_token(data={"sub": user.id})

    @staticmethod
    def get_by_github_id(db: Session, github_id: int) -> Optional["User"]:
        """按 GitHub 用户 ID 查询已绑定的本地账号；无则返回 None"""
        if not github_id:
            return None
        return db.query(User).filter(User.github_id == github_id).first()

    @staticmethod
    def login(db: Session, username: str, password: str) -> Optional[str]:
        """用户登录，返回 access_token，失败返回 None"""
        user = db.query(User).filter(User.username == username).first()
        # H8：防时序攻击——用户不存在时也执行一次 bcrypt 验证消耗时间，
        # 避免通过响应时间差异探测用户是否存在
        if not user:
            dummy_hash = hash_password("dummy")
            verify_password(password, dummy_hash)
            return None
        if not verify_password(password, user.hashed_password):
            return None
        # L9：记录最后登录时间
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
        # H7：sub 统一为字符串（在 create_access_token 内部转换）
        return create_access_token(data={"sub": user.id})
