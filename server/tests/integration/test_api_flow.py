# -*- coding: utf-8 -*-
"""
完整业务流程集成测试
"""
import pytest
from datetime import datetime, timezone

def test_complete_user_flow(client, db):
    """测试完整用户流程：注册 -> 登录 -> 创建计划 -> 服药"""
    
    # 1. 注册老人
    register_response = client.post("/api/v1/auth/register", json={
        "username": "flow_elderly",
        "password": "password123",
        "full_name": "流程测试老人",
        "role": "elderly",
        "phone": "13800138003"
    })
    assert register_response.status_code == 201
    token = register_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. 获取当前用户信息
    me_response = client.get("/api/v1/users/me", headers=headers)
    assert me_response.status_code == 200
    user_id = me_response.json()["id"]
    
    # 3. 创建用药计划
    plan_response = client.post("/api/v1/medication/plan", headers=headers, json={
        "drug_name": "测试药品",
        "dosage": "1片",
        "frequency": "每日1次",
        "schedule_times": ["09:00"],
        "total_quantity": 10,
        "remaining_quantity": 10,
        "unit": "片",
        "low_stock_threshold": 3
    })
    assert plan_response.status_code == 201
    plan_id = plan_response.json()["id"]
    
    # 4. 记录服药
    now = datetime.now(timezone.utc).isoformat()
    take_response = client.post("/api/v1/medication/take", headers=headers, json={
        "plan_id": plan_id,
        "scheduled_time": now,
        "taken_time": now
    })
    assert take_response.status_code == 200
    
    # 5. 获取用药历史
    history_response = client.get("/api/v1/medication/history", headers=headers)
    assert history_response.status_code == 200
    history = history_response.json()
    assert len(history) >= 1

def test_family_bind_and_view(client, db):
    """测试家属绑定后查看老人信息"""
    
    # 1. 注册老人
    elderly_reg = client.post("/api/v1/auth/register", json={
        "username": "bind_elderly",
        "password": "password123",
        "full_name": "被绑定的老人",
        "role": "elderly"
    })
    elderly_token = elderly_reg.json()["access_token"]
    elderly_id = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {elderly_token}"}).json()["id"]
    
    # 2. 注册家属
    family_reg = client.post("/api/v1/auth/register", json={
        "username": "bind_family",
        "password": "password123",
        "full_name": "绑定的家属",
        "role": "family"
    })
    family_token = family_reg.json()["access_token"]
    
    # 3. 家属绑定老人（H13：需提供老人的设备ID，此处老人 username 即作为设备ID）
    bind_response = client.post(
        "/api/v1/users/bind",
        headers={"Authorization": f"Bearer {family_token}"},
        json={"elderly_user_id": elderly_id, "device_id": "bind_elderly"}
    )
    assert bind_response.status_code == 200
    
    # 4. 家属查看用药计划（空，因为老人还没创建）
    plans_response = client.get(
        "/api/v1/medication/plans",
        headers={"Authorization": f"Bearer {family_token}"}
    )
    assert plans_response.status_code == 200