# -*- coding: utf-8 -*-
import logging
import secrets
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from app.models.user import User
from app.schemas.auth import RegisterReq
from app.core.security import hash_password, verify_password, create_access_token, create_mfa_token
from app.core.config import settings
from app.utils import email_code as email_code_store
from app.utils.validators import is_valid_phone, is_valid_email

logger = logging.getLogger(__name__)

# 预计算 dummy hash，用于时序攻击防护（用户不存在时也执行一次 bcrypt verify，
# 使两条路径耗时一致，避免通过响应时间差探测用户是否存在）
_DUMMY_HASH = hash_password("__dummy_timing_attack_protection__")


def _mask_email(email: Optional[str]) -> str:
    """对邮箱做日志脱敏，仅保留首字符，避免 PII 明文落日志。"""
    if not email:
        return "***"
    local = email.split("@", 1)[0]
    return (local[:1] + "***") if local else "***"


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
                    f"OAuth({provider}) 邮箱 {_mask_email(email)} 已合并绑定至现有账号 {existing_email_user.username}"
                )
                return create_access_token(data={"sub": existing_email_user.id})

        # 手机号唯一性校验（phone 为登录唯一标识，必填由 schema 保证）
        if req.phone and db.query(User).filter(User.phone == req.phone).first():
            raise ValueError("该手机号已注册")

        # 创建新用户（username 为昵称，可空、非唯一；full_name 已废弃）
        user = User(
            username=req.username,
            hashed_password=hash_password(req.password),
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
    def login(db: Session, phone: str, password: str) -> Optional[dict]:
        """用户登录（手机号 + 密码）。

        返回 dict：
          - {"access_token": <jwt>} 正常登录（未开启 TOTP 第二因子）
          - {"mfa_required": True, "mfa_token": <短期令牌>} 已开启 TOTP，需再校验动态码
        失败返回 None
        """
        user = db.query(User).filter(User.phone == phone).first()
        # 防时序攻击：用户存在和不存在时均执行一次 verify_password，
        # 使两条路径耗时一致，避免通过响应时间差探测用户是否存在
        user_hash = user.hashed_password if user else _DUMMY_HASH
        if not verify_password(password, user_hash):
            return None
        if not user:
            return None
        # 记录最后登录时间
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
        # 第二因子：密码正确但已开启 TOTP，签发 MFA 短期令牌，等待动态码
        if getattr(user, "mfa_enabled", False):
            return {"mfa_required": True, "mfa_token": create_mfa_token(user.id)}
        # sub 统一为字符串（在 create_access_token 内部转换）
        return {"access_token": create_access_token(data={"sub": user.id})}

    @staticmethod
    def login_or_register_by_email(db: Session, email: str) -> str:
        """邮箱验证码登录 / 自动注册，返回 access_token。

        流程：调用方须先通过 `email_code.verify_code` 校验验证码（本方法不再二次校验），
        因此只要进入本方法即代表验证码已通过。

        - 邮箱已注册：直接登录（更新最后登录时间）。
        - 邮箱未注册：自动创建账号（随机强密码，仅通过验证码登录；默认角色 family 子女端），
          用户名取自邮箱 @ 前段，冲突自动加数字后缀。

        :param email: 已通过验证码校验的用户邮箱（会归一化为小写）
        :return: access_token
        :raises ValueError: 邮箱格式异常（理论上已由 schema 拦截）
        """
        email = (email or "").strip().lower()
        if not email:
            raise ValueError("邮箱不能为空")

        # 已注册 -> 直接登录
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.last_login_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(f"邮箱验证码登录成功：{email}（账号 {user.username}）")
            return create_access_token(data={"sub": user.id})

        # 未注册 -> 自动建号（随机强密码，仅用于占位，用户仅以验证码登录）
        local = email.split("@")[0] or "user"
        base_username = "".join(ch for ch in local if ch.isalnum())[:18] or "user"
        username = base_username
        suffix = 1
        while db.query(User).filter(User.username == username).first():
            suffix += 1
            username = f"{base_username}{suffix}"[:20]

        random_pwd = secrets.token_urlsafe(24)  # 高熵随机密码，用户不需要知道
        user = User(
            username=username,
            hashed_password=hash_password(random_pwd),
            role="family",                       # 邮箱自动注册默认子女端（家人看护视角）
            phone=None,
            group_id=None,
            email=email,
            oauth_provider=None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"邮箱验证码自动注册并登录：{email}（新账号 {username}）")
        return create_access_token(data={"sub": user.id})

    # ==================== OAuth 自动注册 ====================

    @staticmethod
    def auto_register_oauth(
        db: Session,
        provider: str,
        provider_id,
        provider_name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> User:
        """OAuth 首次登录自动注册（不要求手机号/密码）

        创建一个新用户：
        - 随机高熵密码（用户不需要知道，仅以 OAuth 登录）
        - phone = None（未绑定手机号）
        - email = OAuth 返回的邮箱（可能为 None）
        - username 取自第三方昵称，冲突加后缀
        - github_id / gitee_id 绑定对应平台
        - oauth_provider 记录来源平台

        :param db: 数据库会话
        :param provider: "github" 或 "gitee"
        :param provider_id: 第三方平台用户唯一 ID
        :param provider_name: 第三方昵称（用于生成本地 username）
        :param email: 第三方返回的邮箱（可能为 None）
        :return: 新创建的 User 对象
        :raises ValueError: provider_id 已绑定其他账号
        """
        # 双保险：确认该第三方账号尚未绑定其他本地账号
        if AuthService.get_by_provider(db, provider, provider_id):
            raise ValueError(f"该 {provider} 账号已绑定其他用户")

        # 生成 username（取自昵称，冲突加后缀）
        base = "".join(
            ch for ch in (provider_name or "user") if ch.isalnum()
        )[:18] or "user"
        username = base
        suffix = 1
        while db.query(User).filter(User.username == username).first():
            suffix += 1
            username = f"{base}{suffix}"[:20]

        random_pwd = secrets.token_urlsafe(24)
        user = User(
            username=username,
            hashed_password=hash_password(random_pwd),
            role="family",
            phone=None,
            group_id=None,
            email=email.strip().lower() if email else None,
            oauth_provider=provider,
        )
        if provider == "github":
            user.github_id = provider_id
        elif provider == "gitee":
            user.gitee_id = provider_id
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(
            f"OAuth({provider}) 自动注册成功: username={username}, "
            f"email={_mask_email(email)}"
        )
        return user

    # ==================== 登录方式管理（绑定/解绑/查询） ====================

    @staticmethod
    def get_login_methods(db: Session, user: Optional[User] = None) -> Dict[str, Any]:
        """查询登录方式的绑定/启用状态

        兼容登录前（未认证）与登录后（已认证）两种场景（BUG-C07 修复）：
        - user 为 None（未携带/无效 token）：返回系统级「启用状态」，
          供登录页决定是否展示对应登录入口，不会泄露任何用户信息。
        - user 为有效用户：返回该用户各登录方式的「绑定状态」与脱敏值。

        :return: dict 结构:
            {
                "phone":  {"enabled": bool, "bound": bool, "value": ...},
                "email":  {"enabled": bool, "bound": bool, "value": ...},
                "github": {"enabled": bool, "bound": bool, "value": ...},
                "gitee":  {"enabled": bool, "bound": bool, "value": ...},
            }
        """
        # 系统级启用状态：手机号/邮箱登录始终可用；GitHub/Gitee 取决于是否完成 OAuth 配置
        github_enabled = bool(settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET)
        gitee_enabled = bool(settings.GITEE_CLIENT_ID and settings.GITEE_CLIENT_SECRET)

        # 未认证：仅返回系统级启用状态（登录页使用，不依赖用户上下文）
        if user is None:
            return {
                "phone": {"enabled": True, "bound": False, "value": None},
                "email": {"enabled": True, "bound": False, "value": None},
                "github": {"enabled": github_enabled, "bound": False, "value": None},
                "gitee": {"enabled": gitee_enabled, "bound": False, "value": None},
            }

        result = {}

        # 手机号
        if user.phone:
            masked = user.phone[:3] + "****" + user.phone[-4:] if len(user.phone) >= 7 else "***"
            result["phone"] = {"enabled": True, "bound": True, "value": masked}
        else:
            result["phone"] = {"enabled": True, "bound": False, "value": None}

        # 邮箱
        if user.email:
            result["email"] = {"enabled": True, "bound": True, "value": _mask_email(user.email)}
        else:
            result["email"] = {"enabled": True, "bound": False, "value": None}

        # GitHub
        if user.github_id:
            result["github"] = {"enabled": github_enabled, "bound": True, "value": str(user.github_id)}
        else:
            result["github"] = {"enabled": github_enabled, "bound": False, "value": None}

        # Gitee
        if user.gitee_id:
            result["gitee"] = {"enabled": gitee_enabled, "bound": True, "value": str(user.gitee_id)}
        else:
            result["gitee"] = {"enabled": gitee_enabled, "bound": False, "value": None}

        return result

    @staticmethod
    def count_bound_methods(user: User) -> int:
        """统计用户已绑定的登录方式数量（用于解绑时限制至少保留一种）"""
        count = 0
        if user.phone:
            count += 1
        if user.email:
            count += 1
        if user.github_id:
            count += 1
        if user.gitee_id:
            count += 1
        return count

    @staticmethod
    def bind_phone(db: Session, user: User, phone: str, password: str) -> User:
        """绑定手机号（需设置密码，绑定后可用手机号+密码登录）

        :param phone: 手机号
        :param password: 用户设置的密码
        :return: 更新后的 User
        :raises ValueError: 手机号已被其他用户绑定、格式错误、或当前已绑定手机号
        """
        if not is_valid_phone(phone):
            raise ValueError("手机号格式不正确")
        if user.phone:
            raise ValueError("当前已绑定手机号，请先解绑再重新绑定")
        # 检查手机号是否已被其他用户占用
        existing = db.query(User).filter(User.phone == phone).first()
        if existing and existing.id != user.id:
            raise ValueError("该手机号已被其他账号绑定")
        user.phone = phone
        user.hashed_password = hash_password(password)
        db.commit()
        db.refresh(user)
        logger.info(f"用户 {user.username} 绑定手机号成功")
        return user

    @staticmethod
    def bind_email(db: Session, user: User, email: str) -> User:
        """绑定邮箱（验证码由调用方在 endpoint 层校验后再调用本方法）

        :param email: 已通过验证码校验的邮箱
        :return: 更新后的 User
        :raises ValueError: 邮箱已被其他用户绑定、格式错误、或当前已绑定邮箱
        """
        email = (email or "").strip().lower()
        if not is_valid_email(email):
            raise ValueError("邮箱格式不正确")
        if user.email:
            raise ValueError("当前已绑定邮箱，请先解绑再重新绑定")
        existing = db.query(User).filter(User.email == email).first()
        if existing and existing.id != user.id:
            raise ValueError("该邮箱已被其他账号绑定")
        user.email = email
        db.commit()
        db.refresh(user)
        logger.info(f"用户 {user.username} 绑定邮箱成功: {_mask_email(email)}")
        return user

    @staticmethod
    def unbind_phone(db: Session, user: User) -> User:
        """解绑手机号（清空 phone 与 hashed_password）

        :raises ValueError: 解绑后无可用登录方式（至少保留一种）
        """
        if not user.phone:
            raise ValueError("当前未绑定手机号")
        if AuthService.count_bound_methods(user) <= 1:
            raise ValueError("至少保留一种登录方式，无法解绑")
        user.phone = None
        # 如果用户没有通过其他方式设置密码（如邮箱注册），清空密码
        # 但如果用户还绑定了邮箱/OAuth，密码仅用于手机号登录，解绑后清除
        user.hashed_password = None
        db.commit()
        db.refresh(user)
        logger.info(f"用户 {user.username} 解绑手机号")
        return user

    @staticmethod
    def unbind_email(db: Session, user: User) -> User:
        """解绑邮箱

        :raises ValueError: 解绑后无可用登录方式（至少保留一种）
        """
        if not user.email:
            raise ValueError("当前未绑定邮箱")
        if AuthService.count_bound_methods(user) <= 1:
            raise ValueError("至少保留一种登录方式，无法解绑")
        user.email = None
        db.commit()
        db.refresh(user)
        logger.info(f"用户 {user.username} 解绑邮箱")
        return user

    @staticmethod
    def unbind_oauth(db: Session, user: User, provider: str) -> User:
        """解绑第三方 OAuth（GitHub / Gitee）

        :param provider: "github" 或 "gitee"
        :raises ValueError: 未绑定该平台、或解绑后无可用登录方式
        """
        if provider == "github":
            if not user.github_id:
                raise ValueError("当前未绑定 GitHub")
            if AuthService.count_bound_methods(user) <= 1:
                raise ValueError("至少保留一种登录方式，无法解绑")
            user.github_id = None
        elif provider == "gitee":
            if not user.gitee_id:
                raise ValueError("当前未绑定 Gitee")
            if AuthService.count_bound_methods(user) <= 1:
                raise ValueError("至少保留一种登录方式，无法解绑")
            user.gitee_id = None
        else:
            raise ValueError(f"不支持的 OAuth 平台: {provider}")

        # 如果两个 OAuth 都解绑了，清除 oauth_provider
        if not user.github_id and not user.gitee_id:
            user.oauth_provider = None

        db.commit()
        db.refresh(user)
        logger.info(f"用户 {user.username} 解绑 {provider}")
        return user
