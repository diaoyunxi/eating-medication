# -*- coding: utf-8 -*-
import logging
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone
from app.models.user import User
from app.schemas.auth import RegisterReq
from app.core.security import hash_password, verify_password, create_access_token

logger = logging.getLogger(__name__)


class AuthService:
    """认证服务"""

    @staticmethod
    def register(db: Session, req: RegisterReq, oauth_pending: dict = None) -> str:
        """用户注册，返回 access_token

        :param oauth_pending: OAuth 待补全身份令牌载荷（dict），非空表示第三方 OAuth 注册，
                              将绑定对应平台的账号（github_id / gitee_id）、写入 oauth_provider
                              与 email（如 GitHub/Gitee 已授权 emails 权限）。provider 取值 "github"/"gitee"。
        """
        # ===== OAuth 注册：解析第三方身份 =====
        provider = None
        provider_id = None
        email = None
        if oauth_pending:
            provider = oauth_pending.get("provider")
            provider_id = oauth_pending.get("provider_id")
            email = oauth_pending.get("email")
            # 双保险：确认该第三方账号尚未绑定其他本地账号
            if provider and provider_id and AuthService.get_by_provider(db, provider, provider_id):
                raise ValueError(f"该 {provider} 账号已绑定其他用户")

        # ===== 邮箱冲突处理 =====
        # 第三方返回的邮箱若已属于某本地账号，则「合并绑定到该账号并直接登录」，
        # 避免同一邮箱产生重复账号；若邮箱已被「另一个第三方」绑定则为明确冲突，拒绝注册。
        if oauth_pending and email:
            existing_email_user = (
                db.query(User)
                .filter(User.email == email.strip().lower())
                .first()
            )
            if existing_email_user:
                if existing_email_user.oauth_provider and existing_email_user.oauth_provider != provider:
                    raise ValueError(
                        f"该邮箱已通过 {existing_email_user.oauth_provider} 绑定，"
                        f"请使用对应方式登录，或换用其他邮箱后重试"
                    )
                # 现有账号（普通密码账号或未绑定第三方的账号）：合并绑定当前 OAuth 后直接登录
                AuthService._bind_provider(existing_email_user, provider, provider_id)
                db.commit()
                logger.info(
                    f"OAuth({provider}) 邮箱 {email} 已合并绑定至现有账号 {existing_email_user.username}"
                )
                return create_access_token(data={"sub": existing_email_user.id})

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
            email=email,
            oauth_provider=provider,
        )
        if provider == "github":
            user.github_id = provider_id
        elif provider == "gitee":
            user.gitee_id = provider_id
        db.add(user)
        db.commit()
        db.refresh(user)

        # sub 统一为字符串（在 create_access_token 内部转换）
        return create_access_token(data={"sub": user.id})

    @staticmethod
    def _bind_provider(user: "User", provider: str, provider_id) -> None:
        """将第三方账号绑定到已有本地用户（用于邮箱冲突时的合并登录）

        :param user: 待绑定的现有本地用户（其邮箱与第三方返回的邮箱一致）
        :param provider: "github" 或 "gitee"
        :param provider_id: 第三方平台用户唯一 ID
        """
        if provider == "github":
            user.github_id = provider_id
        elif provider == "gitee":
            user.gitee_id = provider_id
        user.oauth_provider = provider

    @staticmethod
    def get_by_provider(db: Session, provider: str, provider_id) -> Optional["User"]:
        """按第三方平台用户 ID 查询已绑定的本地账号；无则返回 None

        :param provider: "github" 或 "gitee"
        """
        if not provider_id:
            return None
        if provider == "gitee":
            return db.query(User).filter(User.gitee_id == provider_id).first()
        # 默认按 github 处理（兼容旧逻辑）
        return db.query(User).filter(User.github_id == provider_id).first()

    @staticmethod
    def get_by_github_id(db: Session, github_id: int) -> Optional["User"]:
        """按 GitHub 用户 ID 查询已绑定的本地账号（兼容别名，内部转调 get_by_provider）"""
        return AuthService.get_by_provider(db, "github", github_id)

    @staticmethod
    def login(db: Session, username: str, password: str) -> Optional[str]:
        """用户登录，返回 access_token，失败返回 None"""
        user = db.query(User).filter(User.username == username).first()
        # 防时序攻击——用户不存在时也执行一次 bcrypt 验证消耗时间，
        # 避免通过响应时间差异探测用户是否存在
        if not user:
            dummy_hash = hash_password("dummy")
            verify_password(password, dummy_hash)
            return None
        if not verify_password(password, user.hashed_password):
            return None
        # 记录最后登录时间
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
        # sub 统一为字符串（在 create_access_token 内部转换）
        return create_access_token(data={"sub": user.id})
