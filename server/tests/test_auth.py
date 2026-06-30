# -*- coding: utf-8 -*-
"""
认证模块测试
"""
import pytest

def test_register_success(client):
    """测试用户注册成功"""
    response = client.post("/api/v1/auth/register", json={
        "username": "newuser",
        "password": "password123",
        "full_name": "新用户",
        "role": "elderly",
        "phone": "13800138001"
    })
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

def test_register_duplicate_username(client, test_elderly_user):
    """测试重复用户名注册失败"""
    response = client.post("/api/v1/auth/register", json={
        "username": "test_elderly",
        "password": "password123",
        "full_name": "重复用户",
        "role": "elderly"
    })
    assert response.status_code == 400
    assert "用户名已存在" in response.json()["detail"]

def test_register_invalid_role(client):
    """测试无效角色注册失败"""
    response = client.post("/api/v1/auth/register", json={
        "username": "invalidrole",
        "password": "password123",
        "full_name": "无效角色",
        "role": "invalid"
    })
    assert response.status_code == 422  # 参数校验失败

def test_login_success(client, test_elderly_user):
    """测试登录成功"""
    response = client.post("/api/v1/auth/login", json={
        "username": "test_elderly",
        "password": "password"
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data

def test_login_wrong_password(client, test_elderly_user):
    """测试密码错误登录失败"""
    response = client.post("/api/v1/auth/login", json={
        "username": "test_elderly",
        "password": "wrongpassword"
    })
    assert response.status_code == 401
    assert "用户名或密码错误" in response.json()["detail"]

def test_login_nonexistent_user(client):
    """测试不存在的用户登录失败"""
    response = client.post("/api/v1/auth/login", json={
        "username": "nonexistent",
        "password": "password"
    })
    assert response.status_code == 401