# -*- coding: utf-8 -*-
"""
通用安全工具：密码哈希、JWT 令牌、设备 ID 脱敏。
与 server/app/core/security.py 对外接口兼容，但配置通过参数（而非模块级 import）注入。

设计原则：
- 纯函数设计，不依赖任何端私有的 config/__init__ 模块
- JWT 配置（secret_key/algorithm/expire_minutes）通过调用方传入，
  而非在 common 内部 import settings，避免反向依赖
"""
import bcrypt
import secrets

try:
    # bcrypt 的 Rust 绑定（pyo3）对畸形/损坏的哈希会触发原生 panic，
    # 抛出的 PanicException 是 BaseException 子类，需显式捕获
    from pyo3_runtime import PanicException as _PanicException
except Exception:  # noqa: BLE001
    # 纯 C 版 bcrypt / pyo3_runtime 不可直接导入时，用 BaseException 兜底：
    # pyo3 的 PanicException 是 BaseException 子类，只有 BaseException 才能兜住它
    _PanicException = BaseException
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


def hash_password(password: str, rounds: int = 12) -> str:
    """哈希密码

    :param password: 明文密码
    :param rounds: bcrypt rounds，默认 12
    :return: bcrypt 哈希字符串（含 salt 与 rounds）
    """
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds))
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码

    :param plain_password: 明文密码
    :param hashed_password: bcrypt 哈希字符串
    :return: 匹配返回 True，否则 False
    """
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (_PanicException, ValueError, TypeError):
        # 畸形/损坏的哈希会让 bcrypt（pyo3 绑定）触发原生 panic 抛出 PanicException，
        # 它并非 ValueError/TypeError 子类，统一兜底为验证失败，避免校验流程崩溃
        return False


def mask_device_id(device_id: str) -> str:
    """设备 ID 日志脱敏：仅保留前 4 位与后 4 位，中间以 *** 遮挡。

    :param device_id: 原始设备 ID
    :return: 脱敏后的字符串
    """
    _did = device_id or ""
    if len(_did) > 8:
        return _did[:4] + "***" + _did[-4:]
    return "***"


def create_access_token(
    data: Dict[str, Any],
    secret_key: str,
    algorithm: str = "HS256",
    expires_delta: Optional[timedelta] = None,
) -> str:
    """创建 JWT access token

    :param data: 载荷数据
    :param secret_key: 签名密钥
    :param algorithm: 签名算法，默认 HS256
    :param expires_delta: 过期时间，默认 None（由调用方提供默认值）
    """
    from jose import jwt

    to_encode = data.copy()
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])
    to_encode.setdefault("type", "access")
    to_encode.setdefault("jti", secrets.token_urlsafe(16))
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=30))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, secret_key, algorithm=algorithm)


def decode_token(token: str, secret_key: str, algorithm: str = "HS256") -> Dict[str, Any]:
    """解码 JWT token"""
    from jose import jwt
    from jose.exceptions import JWTError as _JWTError

    try:
        return jwt.decode(token, secret_key, algorithms=[algorithm])
    except _JWTError:
        raise
