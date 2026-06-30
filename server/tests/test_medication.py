# -*- coding: utf-8 -*-
"""
用药管理模块测试
"""
import pytest
from datetime import datetime

def test_create_plan(client, auth_headers):
    """测试创建用药计划"""
    response = client.post("/api/v1/medication/plan", headers=auth_headers, json={
        "drug_name": "阿司匹林",
        "dosage": "1片",
        "frequency": "每日1次",
        "schedule_times": ["08:00"],
        "total_quantity": 30,
        "remaining_quantity": 30,
        "unit": "片",
        "low_stock_threshold": 5
    })
    assert response.status_code == 201
    data = response.json()
    assert data["drug_name"] == "阿司匹林"
    assert data["remaining_quantity"] == 30
    assert "id" in data

def test_get_plans(client, auth_headers, db, test_elderly_user):
    """测试获取用药计划列表"""
    # 先创建一个计划
    from app.models.medication_plan import MedicationPlan
    plan = MedicationPlan(
        user_id=test_elderly_user.id,
        drug_name="维生素C",
        dosage="2片",
        frequency="每日2次",
        schedule_times=["09:00", "21:00"],
        total_quantity=60,
        remaining_quantity=58,
        unit="片",
        low_stock_threshold=10
    )
    db.add(plan)
    db.commit()
    
    response = client.get("/api/v1/medication/plans", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert any(p["drug_name"] == "维生素C" for p in data)

def test_take_medication(client, auth_headers, db, test_elderly_user):
    """测试记录服药"""
    # 创建用药计划
    from app.models.medication_plan import MedicationPlan
    plan = MedicationPlan(
        user_id=test_elderly_user.id,
        drug_name="降压药",
        dosage="1片",
        frequency="每日1次",
        schedule_times=["07:00"],
        total_quantity=30,
        remaining_quantity=30,
        unit="片",
        low_stock_threshold=5
    )
    db.add(plan)
    db.commit()
    
    scheduled_time = datetime.utcnow().isoformat()
    taken_time = datetime.utcnow().isoformat()
    
    response = client.post("/api/v1/medication/take", headers=auth_headers, json={
        "plan_id": plan.id,
        "scheduled_time": scheduled_time,
        "taken_time": taken_time
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    
    # 验证库存已扣减
    db.refresh(plan)
    assert plan.remaining_quantity == 29

def test_take_medication_unauthorized(client, db, test_elderly_user):
    """测试未认证不能记录服药"""
    # 创建用药计划
    from app.models.medication_plan import MedicationPlan
    plan = MedicationPlan(
        user_id=test_elderly_user.id,
        drug_name="测试药",
        dosage="1片",
        frequency="每日1次",
        schedule_times=["07:00"],
        total_quantity=10,
        remaining_quantity=10,
        unit="片"
    )
    db.add(plan)
    db.commit()
    
    response = client.post("/api/v1/medication/take", json={
        "plan_id": plan.id,
        "scheduled_time": datetime.utcnow().isoformat(),
        "taken_time": datetime.utcnow().isoformat()
    })
    assert response.status_code == 401