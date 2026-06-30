# -*- coding: utf-8 -*-
"""
用户认证模块
使用bcrypt进行不可逆密码加权和验证
"""

import json
import bcrypt
import logging
import secrets
from pathlib import Path
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class UserCreate(BaseModel):
    """用户注册模型"""
    username: str
    password: str
    confirm_password: str


class UserLogin(BaseModel):
    """用户登录模型"""
    username: str
    password: str


class UserManager:
    """用户管理类，处理用户注册、登录和密码验证"""

    def __init__(self, data_dir: Path):
        self.users_file = data_dir / 'users.json'
        self.users_file.parent.mkdir(exist_ok=True)
        self._ensure_users_file()

    def _ensure_users_file(self):
        """确保用户文件存在，不自动创建默认账户"""
        if not self.users_file.exists():
            self._save_users({})
            logger.info("用户文件已创建")

    def _load_users(self) -> dict:
        """加载用户数据"""
        try:
            with open(self.users_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载用户数据失败: {e}")
            return {}

    def _save_users(self, users: dict):
        """保存用户数据"""
        try:
            with open(self.users_file, 'w', encoding='utf-8') as f:
                json.dump(users, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存用户数据失败: {e}")

    def hash_password(self, password: str) -> str:
        """使用bcrypt对密码进行不可逆加密"""
        password_bytes = password.encode('utf-8')
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """验证密码是否匹配哈希"""
        try:
            plain_bytes = plain_password.encode('utf-8')
            hashed_bytes = hashed_password.encode('utf-8')
            return bcrypt.checkpw(plain_bytes, hashed_bytes)
        except Exception as e:
            logger.error(f"密码验证失败: {e}")
            return False

    def register_user(self, username: str, password: str, confirm_password: str) -> tuple[bool, str]:
        """注册新用户"""
        if not username or len(username.strip()) < 3:
            return False, "用户名至少需要3个字符"
        if not password or len(password) < 6:
            return False, "密码至少需要6个字符"
        if password != confirm_password:
            return False, "两次输入的密码不一致"

        users = self._load_users()
        if username in users:
            return False, "用户名已存在"

        hashed_password = self.hash_password(password)
        users[username] = {
            'password_hash': hashed_password,
            'role': 'user',
            'created_at': datetime.now().isoformat(),
            'last_login': None
        }
        self._save_users(users)
        logger.info(f"用户注册成功: {username}")
        return True, "注册成功"

    def authenticate_user(self, username: str, password: str) -> tuple[bool, str]:
        """验证用户登录"""
        if not username or not password:
            return False, "用户名和密码不能为空"

        users = self._load_users()
        if username not in users:
            return False, "用户名或密码错误"

        user = users[username]
        if self.verify_password(password, user['password_hash']):
            users[username]['last_login'] = datetime.now().isoformat()
            self._save_users(users)
            logger.info(f"用户登录成功: {username}")
            return True, "登录成功"
        else:
            logger.warning(f"用户登录失败（密码错误）: {username}")  
            return False, "用户名或密码错误"

    def user_exists(self, username: str) -> bool:
        """检查用户是否存在"""
        users = self._load_users()
        return username in users

    def get_user_info(self, username: str) -> Optional[dict]:
        """获取用户信息（不包含密码哈希）"""
        users = self._load_users()
        if username in users:
            user = users[username].copy()
            user.pop('password_hash', None)
            return user
        return None

    def get_user_role(self, username: str) -> str:
        """获取用户角色"""
        users = self._load_users()
        if username in users:
            return users[username].get('role', 'user')
        return 'user'

    def is_admin(self, username: str) -> bool:
        """检查用户是否为管理员"""
        return self.get_user_role(username) == 'admin'


_user_manager: Optional[UserManager] = None

def get_user_manager(data_dir: Path) -> UserManager:
    """获取用户管理器实例"""
    global _user_manager
    if _user_manager is None:
        _user_manager = UserManager(data_dir)
    return _user_manager