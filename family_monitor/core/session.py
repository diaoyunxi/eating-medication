# -*- coding: utf-8 -*-
"""
会话管理模块
使用itsdangerous进行安全的会话令牌管理
"""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional, Set
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature 

logger = logging.getLogger(__name__)


class SessionManager:
    """会话管理类"""

    def __init__(self, secret_key: str):
        self.serializer = URLSafeTimedSerializer(secret_key)
        self.max_age = 86400 * 7  # 7天有效期
        self._revoked_tokens: Set[str] = set()  # 已撤销的令牌集合

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
        logger.info("会话已撤销")
        return True
        
    def is_session_valid(self, token: str) -> bool:
        """检查会话是否有效"""
        if token in self._revoked_tokens:
            return False
        return self.verify_session(token) is not None


# 全局会话管理器实例
_session_manager: Optional[SessionManager] = None  


def get_session_manager(secret_key: str) -> SessionManager:
    """获取会话管理器实例"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager(secret_key)
    return _session_manager