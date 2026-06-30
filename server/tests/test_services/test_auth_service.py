# -*- coding: utf-8 -*-
"""
认证服务单元测试
"""
import pytest
from app.services.auth_service import AuthService
from app.schemas.auth import RegisterReq

def test_register(db):
    """测试注册服务"""
    req = RegisterReq(
        username="service_test",
        password="password123",
        full_name="服务测试用户",
        role="elderly",
        phone="13800138002"
    )
    token = AuthService.register(db, req)
    assert token is not None
    assert isinstance(token, str)

def test_register_duplicate(db, test_elderly_user):
    """测试重复注册"""
    req = RegisterReq(
        username="test_elderly",  # 已存在的用户名
        password="password123",
        full_name="重复用户",
        role="elderly"
    )
    with pytest.raises(ValueError, match="用户名已存在"):
        AuthService.register(db, req)

def test_login_success(db, test_elderly_user):
    """测试登录成功"""
    token = AuthService.login(db, "test_elderly", "password")
    assert token is not None

def test_login_fail(db):
    """测试登录失败"""
    token = AuthService.login(db, "wrong_user", "wrong_pass")
    assert token is None