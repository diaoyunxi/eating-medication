# -*- coding: utf-8 -*-
import re
from typing import Optional

def is_valid_phone(phone: Optional[str]) -> bool:
    """验证手机号格式（中国大陆）"""
    if not phone:
        return True
    pattern = r'^1[3-9]\d{9}$'
    return bool(re.match(pattern, phone))

def is_valid_username(username: str) -> bool:
    """验证用户名格式"""
    if not username:
        return False
    if len(username) < 3 or len(username) > 20:
        return False
    pattern = r'^[a-zA-Z0-9_]+$'
    return bool(re.match(pattern, username))

def is_valid_password(password: str) -> bool:
    """验证密码强度"""
    if not password:
        return False
    if len(password) < 6 or len(password) > 100:
        return False
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    return has_letter and has_digit

def is_valid_time_format(time_str: str) -> bool:
    """验证时间格式"""
    pattern = r'^([01]\d|2[0-3]):([0-5]\d)(:([0-5]\d))?$'
    return bool(re.match(pattern, time_str))


def is_valid_email(email: str) -> bool:
    """验证邮箱格式（RFC 5322 简化版：local@domain.tld）"""
    if not email:
        return False
    # 长度限制（SMTP 标准上限 254）
    if len(email) > 254:
        return False
    pattern = r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$'
    return bool(re.match(pattern, email))