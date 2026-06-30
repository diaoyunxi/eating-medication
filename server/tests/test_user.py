# -*- coding: utf-8 -*-
"""
用户模块测试
"""
import pytest

def test_get_current_user(client, auth_headers, test_elderly_user):
    """测试获取当前用户信息"""
    response = client.get("/api/v1/users/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == test_elderly_user.id
    assert data["username"] == "test_elderly"
    assert data["full_name"] == "测试老人"
    assert data["role"] == "elderly"

def test_update_current_user(client, auth_headers):
    """测试更新用户信息"""
    response = client.put("/api/v1/users/me", headers=auth_headers, json={
        "full_name": "更新后的姓名",
        "phone": "13700137000"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "更新后的姓名"
    assert data["phone"] == "13700137000"

def test_bind_family(client, db, test_elderly_user, test_family_user):
    """测试家属绑定老人"""
    # 生成家属的 token
    from app.core.security import create_access_token
    family_token = create_access_token(data={"sub": test_family_user.id})
    family_headers = {"Authorization": f"Bearer {family_token}"}
    
    response = client.post(
        "/api/v1/users/bind",
        headers=family_headers,
        json={"elderly_user_id": test_elderly_user.id}
    )
    assert response.status_code == 200
    data = response.json()
    assert "group_id" in data
    
    # 验证数据库中的 group_id 已更新
    db.refresh(test_elderly_user)
    db.refresh(test_family_user)
    assert test_elderly_user.group_id is not None
    assert test_family_user.group_id == test_elderly_user.group_id

def test_bind_family_unauthorized(client, test_elderly_user):
    """测试非家属用户不能绑定"""
    response = client.post(
        "/api/v1/users/bind",
        json={"elderly_user_id": test_elderly_user.id}
    )
    assert response.status_code == 401  # 未认证