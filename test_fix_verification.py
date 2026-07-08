#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复验证测试：验证"设备即用户"设计缺陷已修复

测试流程：
1. 老人通过 /auth/register 注册（真实老人 user_id=13）
2. 设备通过 /public/device/register 注册（创建虚拟用户 user_id=15）
3. 家属注册
4. 家属调用 /users/bind（elderly_user_id=13, device_id=xxx）：
   - 虚拟用户数据迁移到真实老人
   - 删除虚拟用户
   - 真实老人 device_id 字段 = xxx
   - 家属加入家庭组
5. 设备心跳：device_id → 反查到真实老人 → 更新心跳
6. 设备状态查询：device_id → user_id=13 → 返回真实老人的计划/记录数
7. 老人创建计划：user_id=13
8. 删除计划：device_id → user_id=13 → 匹配 plan.user_id=13 → 200 OK
"""
import os
import sys
import tempfile

# 使用临时文件 SQLite 数据库（内存数据库在多线程下每个连接独立）
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ["JWT_SECRET"] = "test-secret-key-for-verification-only-32chars"
os.environ["ALLOWED_ORIGINS"] = "*"
os.environ["DEBUG"] = "true"

sys.path.insert(0, "/workspace/server")

from fastapi.testclient import TestClient
from app.core.database import engine, Base, SessionLocal
from app.main import app

# 先创建所有表（必须用同一个 engine）
Base.metadata.create_all(bind=engine)

client = TestClient(app)

print("=" * 70)
print("修复验证测试：设备即用户设计缺陷修复")
print("=" * 70)

# ---------- 1. 老人注册（真实老人）----------
print("\n[1] 老人注册（真实老人，有账号密码）...")
resp = client.post("/api/v1/auth/register", json={
    "username": "elderly_zhang",
    "password": "Test1234!",
    "full_name": "张爷爷",
    "role": "elderly",
})
assert resp.status_code == 201, f"老人注册失败: {resp.status_code} {resp.text}"
elderly_token = resp.json()["access_token"]
# 从 /users/me 获取 elderly_user_id
resp_me = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {elderly_token}"})
elderly_user_id = resp_me.json()["id"]
print(f"  ✓ 老人注册成功: user_id={elderly_user_id}, username=elderly_zhang")

# ---------- 2. 设备注册（创建虚拟用户）----------
print("\n[2] 设备注册（创建虚拟用户）...")
device_id = "FCC_001122334455"
resp = client.post("/api/v1/public/device/register", json={
    "device_id": device_id,
    "device_name": "张爷爷的设备",
})
assert resp.status_code == 200, f"设备注册失败: {resp.status_code} {resp.text}"
virtual_user_id = resp.json()["user_id"]
assert virtual_user_id != elderly_user_id, "虚拟用户 ID 不应等于真实老人 ID"
print(f"  ✓ 设备注册成功: 虚拟 user_id={virtual_user_id} (应不等于真实老人 {elderly_user_id})")

# ---------- 3. 家属注册 ----------
print("\n[3] 家属注册...")
resp = client.post("/api/v1/auth/register", json={
    "username": "family_li",
    "password": "Test1234!",
    "full_name": "李家属",
    "role": "family",
})
assert resp.status_code == 201, f"家属注册失败: {resp.status_code} {resp.text}"
family_token = resp.json()["access_token"]
print(f"  ✓ 家属注册成功")

# ---------- 4. 家属绑定老人（核心修复点）----------
print("\n[4] 家属绑定老人（核心修复点：数据迁移 + device_id 关联）...")
resp = client.post(
    "/api/v1/users/bind",
    json={
        "elderly_user_id": elderly_user_id,
        "device_id": device_id,
    },
    headers={"Authorization": f"Bearer {family_token}"},
)
assert resp.status_code == 200, f"绑定失败: {resp.status_code} {resp.text}"
group_id = resp.json()["group_id"]
print(f"  ✓ 绑定成功: group_id={group_id}")

# 验证虚拟用户已被删除，真实老人的 device_id 已关联
db = SessionLocal()
from app.models.user import User
virtual_user = db.query(User).filter(User.id == virtual_user_id).first()
real_elderly = db.query(User).filter(User.id == elderly_user_id).first()
assert virtual_user is None, "虚拟用户应已被删除"
assert real_elderly.device_id == device_id, f"真实老人 device_id 应为 {device_id}，实际为 {real_elderly.device_id}"
assert real_elderly.group_id == group_id, "真实老人 group_id 应已设置"
print(f"  ✓ 虚拟用户 user_id={virtual_user_id} 已删除")
print(f"  ✓ 真实老人 user_id={elderly_user_id} 的 device_id 字段 = {real_elderly.device_id}")

# ---------- 5. 设备心跳（应反查到真实老人）----------
print("\n[5] 设备心跳（应反查到真实老人，不再创建新虚拟用户）...")
resp = client.post("/api/v1/public/device/register", json={
    "device_id": device_id,
    "device_name": "张爷爷的设备",
})
assert resp.status_code == 200, f"心跳失败: {resp.status_code} {resp.text}"
heartbeat_user_id = resp.json()["user_id"]
assert heartbeat_user_id == elderly_user_id, \
    f"心跳应返回真实老人 user_id={elderly_user_id}，实际返回 {heartbeat_user_id}"
print(f"  ✓ 心跳返回真实老人 user_id={heartbeat_user_id} (修复前会返回虚拟用户 {virtual_user_id})")

# ---------- 6. 设备状态查询 ----------
print("\n[6] 设备状态查询（应返回真实老人的数据）...")
resp = client.get(f"/api/v1/public/device/status/{device_id}")
assert resp.status_code == 200, f"状态查询失败: {resp.status_code} {resp.text}"
status = resp.json()
assert status["device_id"] == device_id, "状态中 device_id 应匹配"
print(f"  ✓ 状态查询成功: device_name={status['device_name']}, total_plans={status['total_plans']}")

# ---------- 7. 老人创建用药计划（JWT）----------
print("\n[7] 老人创建用药计划（通过 JWT，user_id=13）...")
resp = client.post(
    "/api/v1/medication/plan",
    json={
        "drug_name": "降压药",
        "dosage": "1片",
        "frequency": "每日1次",
        "schedule_times": ["08:00"],
        "total_quantity": 30,
        "remaining_quantity": 30,
        "unit": "片",
        "low_stock_threshold": 5,
    },
    headers={"Authorization": f"Bearer {elderly_token}"},
)
assert resp.status_code == 201, f"创建计划失败: {resp.status_code} {resp.text}"
plan_id = resp.json()["id"]
print(f"  ✓ 计划创建成功: plan_id={plan_id}, user_id={elderly_user_id}")

# ---------- 8. 删除用药计划（通过 device_id，核心修复点）----------
print("\n[8] 删除用药计划（通过 device_id，核心修复点）...")
resp = client.delete(
    f"/api/v1/public/device/medication_plan/{plan_id}?device_id={device_id}",
)
assert resp.status_code == 200, f"删除计划失败: {resp.status_code} {resp.text}"
print(f"  ✓ 删除成功（修复前会 404，因为 device_id 反查到虚拟用户 user_id={virtual_user_id}，与 plan.user_id={elderly_user_id} 不匹配）")

# ---------- 9. 设备检查接口 ----------
print("\n[9] 设备检查接口（应返回 exists=True）...")
resp = client.get(f"/api/v1/public/device/check/{device_id}")
assert resp.status_code == 200, f"设备检查失败: {resp.status_code} {resp.text}"
assert resp.json()["exists"] is True
print(f"  ✓ 设备检查返回 exists=True")

# ---------- 10. 验证 UserOut 包含 device_id 字段 ----------
print("\n[10] 验证 UserOut schema 包含 device_id 字段...")
resp = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {elderly_token}"})
assert resp.status_code == 200
user_data = resp.json()
assert "device_id" in user_data, "UserOut 应包含 device_id 字段"
assert user_data["device_id"] == device_id, f"device_id 应为 {device_id}"
print(f"  ✓ UserOut 返回 device_id={user_data['device_id']}")

db.close()

print("\n" + "=" * 70)
print("全部测试通过！设备即用户设计缺陷已修复。")
print("=" * 70)
print("\n修复的 3 个失败项：")
print("  ✓ #9  家属绑定老人   - 数据迁移 + device_id 关联成功")
print("  ✓ #21 获取设备状态   - device_id 反查到真实老人，正常返回")
print("  ✓ #29 删除用药计划   - device_id 反查到真实老人 user_id，匹配 plan.user_id 成功删除")
