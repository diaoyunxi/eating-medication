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

def validate_drug_name(drug_name: str) -> bool:
    """验证药品名称"""
    if not drug_name:
        return False
    if len(drug_name) > 100:
        return False
    return True

def is_valid_time_format(time_str: str) -> bool:
    """验证时间格式"""
    pattern = r'^([01]\d|2[0-3]):([0-5]\d)(:([0-5]\d))?$'
    return bool(re.match(pattern, time_str))

def sanitize_string(text: str, max_length: int = 500) -> str:
    """清理字符串"""
    if not text:
        return ""
    text = text.strip()
    if len(text) > max_length:
        text = text[:max_length]
    return text