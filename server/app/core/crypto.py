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
    """解密密文，返回明文；空字符串直接返回空。"""
    if not ciphertext:
        return ""
    try:
        from cryptography.fernet import Fernet
        f = Fernet(_fernet_key())
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error(f"❌ API Key 解密失败（SECRET_KEY 可能已变更）: {e}")
        return ""
