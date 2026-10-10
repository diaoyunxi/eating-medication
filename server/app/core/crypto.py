# -*- coding: utf-8 -*-
"""敏感字段加解密工具（用于加密存储 AI 厂商 API Key）

设计要点：
- 不引入额外的密钥管理，直接复用服务端已有的 SECRET_KEY 派生出 Fernet 密钥，
  保证重启后密文可解密、且不与代码/配置一起明文泄露。
- 依赖 cryptography 库（已由 python-jose[cryptography] 间接安装，requirements 显式声明）。
- 加解密函数内部惰性导入 cryptography，避免该库缺失时导致模块级 import 失败。
"""
import base64
import hashlib
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class DecryptionError(Exception):
    """解密失败异常。

    当密文无法用当前 SECRET_KEY 解密时抛出，调用方可据此区分
    "未配置"（空字符串）与"解密失败"（需用户重新配置 API Key）。
    """


def _fernet_key() -> bytes:
    """由 SECRET_KEY 派生出 32 字节 url-safe base64 密钥（Fernet 要求）"""
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_text(plaintext: str) -> str:
    """加密明文，返回密文字符串；空字符串直接返回空。"""
    if not plaintext:
        return ""
    try:
        from cryptography.fernet import Fernet
        f = Fernet(_fernet_key())
        return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error(f"❌ API Key 加密失败: {e}")
        raise


def decrypt_text(ciphertext: str) -> str:
    """解密密文，返回明文；空字符串直接返回空。

    解密失败时抛出 DecryptionError（自定义异常），调用方可据此区分
    "未配置"（空字符串输入）与"解密失败"（SECRET_KEY 变更或密文损坏）。
    """
    if not ciphertext:
        return ""
    try:
        from cryptography.fernet import Fernet
        f = Fernet(_fernet_key())
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error(
            "API Key 解密失败（可能原因：SECRET_KEY 已变更、密文损坏或格式不合法）。"
            "请在「设置 - AI 助手设置」中重新配置 API Key。错误详情: %s", e
        )
        raise DecryptionError(
            f"API Key 解密失败，请在设置中重新配置: {e}"
        ) from e
