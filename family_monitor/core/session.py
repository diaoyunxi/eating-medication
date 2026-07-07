# -*- coding: utf-8 -*-
"""
会话管理模块
使用itsdangerous进行安全的会话令牌管理
包含 CSRF token 生成与校验、撤销令牌持久化
"""

import json
import logging
import secrets
from pathlib import Path
from datetime import datetime
from typing import Optional, Set
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

logger = logging.getLogger(__name__)


class SessionManager:
    """会话管理类"""

    def __init__(self, secret_key: str, revocation_file: Optional[Path] = None):
        self.serializer = URLSafeTimedSerializer(secret_key)
        self.max_age = 86400 * 7  # 7天有效期
        self._revoked_tokens: Set[str] = set()  # 已撤销的令牌集合
        self._revocation_file = revocation_file
        if revocation_file:
            self._load_revoked_tokens()

    def _load_revoked_tokens(self):
        """启动时从文件加载已撤销的令牌"""
        if self._revocation_file and self._revocation_file.exists():
            try:
                with open(self._revocation_file, 'r', encoding='utf-8') as f:
                    self._revoked_tokens = set(json.load(f))
                logger.info(f"已加载 {len(self._revoked_tokens)} 个撤销令牌")
            except Exception as e:
                logger.warning(f"加载撤销令牌文件失败: {e}")
                self._revoked_tokens = set()

    def _save_revoked_tokens(self):
        """将撤销令牌持久化到文件"""
        if self._revocation_file:
            try:
                with open(self._revocation_file, 'w', encoding='utf-8') as f:
                    json.dump(list(self._revoked_tokens), f, ensure_ascii=False)
            except Exception as e:
                logger.warning(f"保存撤销令牌文件失败: {e}")

    def create_session(self, username: str) -> str:
        """
        创建会话令牌

        Args:
            username: 用户名
        Returns:
            加密的会话令牌
        """
        payload = {
            'username': username,
            'created_at': datetime.now().isoformat(),
            'token_id': secrets.token_urlsafe(16)  # 添加唯一令牌ID
        }
        token = self.serializer.dumps(payload)
        logger.info(f"创建会话: {username}")
        return token

    def verify_session(self, token: str) -> Optional[dict]:
        """
        验证会话令牌

        Args:
            token: 会话令牌

        Returns:
            会话数据（如有有效），否则返回None
        """
        if token in self._revoked_tokens:
            logger.warning("会话已撤销")
            return None

        try:
            payload = self.serializer.loads(token, max_age=self.max_age)
            return payload
        except SignatureExpired:
            logger.warning("会话已过期")
            return None
        except BadSignature:
            logger.warning("无效的会话令牌")
            return None

    def invalidate_session(self, token: str) -> bool:
        """
        使会话失效（登出）
        Args:
            token: 会话令牌

        Returns:
            是否成功
        """
        self._revoked_tokens.add(token)
        # 修复内存泄漏：清理已过期的撤销令牌，防止 _revoked_tokens 无限增长
        self._cleanup_expired_revoked_tokens()
        self._save_revoked_tokens()
        logger.info("会话已撤销")
        return True

    def _cleanup_expired_revoked_tokens(self):
        """清理已过期的撤销令牌（token 过期或无效即无需保留在撤销列表）"""
        expired = []
        for token in list(self._revoked_tokens):
            try:
                self.serializer.loads(token, max_age=self.max_age)
            except (SignatureExpired, BadSignature):
                expired.append(token)
        for token in expired:
            self._revoked_tokens.discard(token)
        if expired:
            logger.info(f"清理 {len(expired)} 个过期撤销令牌")

    def is_session_valid(self, token: str) -> bool:
        """检查会话是否有效"""
        if token in self._revoked_tokens:
            return False
        return self.verify_session(token) is not None

    def generate_csrf_token(self) -> str:
        """生成并签名 CSRF token（使用 secrets.token_urlsafe(32) 生成随机数并签名）"""
        payload = {
            'type': 'csrf',
            'nonce': secrets.token_urlsafe(32)
        }
        return self.serializer.dumps(payload)

    def verify_csrf_token(self, token: str) -> bool:
        """验证 CSRF token 的签名是否有效"""
        try:
            payload = self.serializer.loads(token, max_age=self.max_age)
            return payload.get('type') == 'csrf'
        except (SignatureExpired, BadSignature):
            return False


# 全局会话管理器实例
_session_manager: Optional[SessionManager] = None


def get_session_manager(secret_key: str) -> SessionManager:
    """获取会话管理器实例"""
    global _session_manager
    if _session_manager is None:
        from core.config import config
        revocation_file = config.DATA_DIR / 'revoked_tokens.json'
        _session_manager = SessionManager(secret_key, revocation_file)
    return _session_manager
