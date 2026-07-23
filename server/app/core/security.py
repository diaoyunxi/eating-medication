# -*- coding: utf-8 -*-
import bcrypt
from jose import jwt
from jose.exceptions import JWTError
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
import secrets
from app.core.config import settings

# 移除 passlib（与 bcrypt 4.x 不兼容），改用 bcrypt 原生 API
# 密码哈希 rounds 固定为 12，与原 passlib 配置一致

# 当前使用 HS256 对称加密，适用于单服务部署。
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
    # 统一 sub 为字符串类型
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])
    # 增加 token 类型与唯一标识
    to_encode.setdefault("type", "access")
    to_encode.setdefault("jti", secrets.token_urlsafe(16))
    # 使用带时区的 UTC 时间
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """解码 JWT token"""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


# ==================== GitHub OAuth 相关令牌 ====================

def create_oauth_state_token(state: str) -> str:
    """签发短时 OAuth state 令牌（防 CSRF）

    state 由服务端随机生成，写入 HttpOnly 签名 cookie；回调时比对 GitHub 返回的 state。
    使用 HS256 签名，10 分钟内有效。
    """
    return create_access_token(
        data={"type": "oauth_state", "state": state},
        expires_delta=timedelta(minutes=10),
    )


def verify_oauth_state_token(token: str) -> Optional[str]:
    """校验 OAuth state 令牌并返回内部 state 值；无效或类型不符返回 None"""
    try:
        payload = decode_token(token)
    except JWTError:
        return None
    if payload.get("type") != "oauth_state":
        return None
    return payload.get("state")


def create_oauth_pending_token(
    *,
    provider: str,
    provider_id: int,
    provider_login: str,
    provider_name: Optional[str] = None,
    provider_avatar: Optional[str] = None,
    email: Optional[str] = None,
) -> str:
    """签发短期 OAuth 待补全身份令牌（provider 无关）

    首次第三方登录（provider_id 尚未绑定本地账号）时，server 回调将此令牌写入
    HttpOnly cookie，并 302 跳转 family_monitor 注册页补全信息；注册接口凭此绑定对应
    平台的账号（github_id / gitee_id）并写入 email。15 分钟内有效。
    provider 取值："github" / "gitee"。
    """
    return create_access_token(
        data={
            "type": "oauth_pending",
            "provider": provider,
            "provider_id": provider_id,
            "provider_login": provider_login,
            "provider_name": provider_name,
            "provider_avatar": provider_avatar,
            "email": email,
        },
        expires_delta=timedelta(minutes=15),
    )


def verify_oauth_pending_token(token: str) -> Optional[Dict[str, Any]]:
    """校验 OAuth 待补全身份令牌；无效或类型不符返回 None"""
    try:
        payload = decode_token(token)
    except JWTError:
        return None
    if payload.get("type") != "oauth_pending":
        return None
    return payload

