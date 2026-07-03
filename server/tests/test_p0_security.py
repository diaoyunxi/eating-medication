# -*- coding: utf-8 -*-
"""
P0 安全修复验证测试
验证 public.py 的 P0-2（legacy 设备接管移除）、P0-3（设备枚举脱敏）、
F4（device/message 加认证）、H-3（日志脱敏）等修复
"""
import pytest
from fastapi.testclient import TestClient
from app.core.security import hash_password
from app.models.user import User
from tests.conftest import override_get_db
from app.core.dependencies import get_db


@pytest.fixture
def client(db):
    def _get_db_override():
        return db
    app_dependency_overrides = {get_db: _get_db_override}
    from app.main import app
    old = app.dependency_overrides.copy()
    app.dependency_overrides.update(app_dependency_overrides)
    yield TestClient(app)
    app.dependency_overrides = old


class TestP0DeviceRegister:
    """P0-2: 移除 legacy 无条件重置 token 分支"""

    def test_registered_device_without_token_returns_401(self, client, db):
        """已注册设备不携带 token 应返回 401（而非重置 token）"""
        # 预置一个已注册设备
        user = User(
            username="FCC_TEST001",
            hashed_password=hash_password("old_token_value"),
            full_name="测试设备",
            role="elderly",
        )
        db.add(user)
        db.commit()

        resp = client.post("/api/v1/public/device/register", json={
            "device_id": "FCC_TEST001",
            "device_name": "测试设备"
        })
        assert resp.status_code == 401
        assert "token" in resp.json()["detail"].lower()

    def test_registered_device_with_correct_token_returns_ok(self, client, db):
        """已注册设备携带正确 token 应返回 200"""
        token = "correct_token_abc123"
        user = User(
            username="FCC_TEST002",
            hashed_password=hash_password(token),
            full_name="测试设备2",
            role="elderly",
        )
        db.add(user)
        db.commit()

        resp = client.post("/api/v1/public/device/register",
                           json={"device_id": "FCC_TEST002", "device_name": "测试设备2"},
                           headers={"X-Device-Token": token})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_legacy_device_no_unconditional_reset(self, client, db):
        """hashed_password == 'device' 的 legacy 设备不应被无条件重置 token"""
        user = User(
            username="FCC_LEGACY01",
            hashed_password="device",  # legacy 值
            full_name="旧设备",
            role="elderly",
        )
        db.add(user)
        db.commit()

        resp = client.post("/api/v1/public/device/register", json={
            "device_id": "FCC_LEGACY01",
            "device_name": "旧设备"
        })
        # P0-2 修复：不应返回 200 + device_token，应返回 401
        assert resp.status_code == 401
        assert "device_token" not in resp.json()


class TestP0DeviceCheck:
    """P0-3: 设备枚举脱敏"""

    def test_check_returns_only_exists(self, client, db):
        """check 接口仅返回 exists，不泄露 device_name/created_at"""
        user = User(
            username="FCC_ENUM001",
            hashed_password=hash_password("any"),
            full_name="敏感设备名",
            role="elderly",
        )
        db.add(user)
        db.commit()

        resp = client.get("/api/v1/public/device/check/FCC_ENUM001")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"exists": True}
        # 确保不泄露敏感字段
        assert "device_name" not in data
        assert "created_at" not in data

    def test_check_nonexistent_returns_404(self, client):
        """不存在的设备返回 404"""
        resp = client.get("/api/v1/public/device/check/NOT_EXIST_999")
        assert resp.status_code == 404


class TestF4DeviceMessage:
    """F4: device/message 增加 device_token 校验"""

    def test_message_without_token_returns_401(self, client, db):
        """无 token 上报消息应返回 401"""
        user = User(
            username="FCC_MSG001",
            hashed_password=hash_password("msg_token"),
            full_name="消息设备",
            role="elderly",
        )
        db.add(user)
        db.commit()

        resp = client.post("/api/v1/public/device/message", json={
            "device_id": "FCC_MSG001",
            "message_type": "medication",
            "content": "已服药"
        })
        assert resp.status_code == 401

    def test_message_with_correct_token_returns_ok(self, client, db):
        """携带正确 token 上报消息应返回 200"""
        token = "msg_correct_token"
        user = User(
            username="FCC_MSG002",
            hashed_password=hash_password(token),
            full_name="消息设备2",
            role="elderly",
        )
        db.add(user)
        db.commit()

        resp = client.post("/api/v1/public/device/message",
                           json={"device_id": "FCC_MSG002", "message_type": "emergency", "content": "紧急求助"},
                           headers={"X-Device-Token": token})
        assert resp.status_code == 200

    def test_message_nonexistent_device_returns_404(self, client):
        """不存在的设备上报消息返回 404"""
        resp = client.post("/api/v1/public/device/message", json={
            "device_id": "GHOST_DEVICE",
            "message_type": "info",
            "content": "test"
        }, headers={"X-Device-Token": "any"})
        assert resp.status_code == 404


class TestP0_5MedicationSchema:
    """P0-5: remaining_quantity 不能超过 total_quantity"""

    def test_remaining_exceeds_total_rejected(self):
        from app.schemas.medication import MedicationPlanCreate
        with pytest.raises(Exception) as exc_info:
            MedicationPlanCreate(
                drug_name="测试药",
                dosage="1片",
                frequency="每日",
                schedule_times=["08:00"],
                total_quantity=10,
                remaining_quantity=20,  # 超过 total
            )
        assert "剩余数量不能超过总数量" in str(exc_info.value)

    def test_remaining_equals_total_ok(self):
        from app.schemas.medication import MedicationPlanCreate
        plan = MedicationPlanCreate(
            drug_name="测试药",
            dosage="1片",
            frequency="每日",
            schedule_times=["08:00"],
            total_quantity=10,
            remaining_quantity=10,
        )
        assert plan.remaining_quantity == 10

    def test_remaining_less_than_total_ok(self):
        from app.schemas.medication import MedicationPlanCreate
        plan = MedicationPlanCreate(
            drug_name="测试药",
            dosage="1片",
            frequency="每日",
            schedule_times=["08:00"],
            total_quantity=30,
            remaining_quantity=5,
        )
        assert plan.remaining_quantity == 5


class TestDeviceRecordsEndpoint:
    """F2: 新增 /device/records 端点（device_token 鉴权）"""

    def test_records_without_token_returns_401(self, client, db):
        user = User(
            username="FCC_REC001",
            hashed_password=hash_password("rec_token"),
            full_name="记录设备",
            role="elderly",
        )
        db.add(user)
        db.commit()

        resp = client.get("/api/v1/public/device/records/FCC_REC001")
        assert resp.status_code == 401

    def test_records_with_token_returns_200(self, client, db):
        token = "rec_correct"
        user = User(
            username="FCC_REC002",
            hashed_password=hash_password(token),
            full_name="记录设备2",
            role="elderly",
        )
        db.add(user)
        db.commit()

        resp = client.get("/api/v1/public/device/records/FCC_REC002",
                          headers={"X-Device-Token": token})
        assert resp.status_code == 200
        data = resp.json()
        assert "records" in data
        assert isinstance(data["records"], list)


class TestDeviceChatHistoryEndpoint:
    """S9: 新增 /device/chat_history 端点"""

    def test_chat_history_without_token_returns_401(self, client, db):
        user = User(
            username="FCC_CHAT01",
            hashed_password=hash_password("chat_token"),
            full_name="聊天设备",
            role="elderly",
        )
        db.add(user)
        db.commit()

        resp = client.get("/api/v1/public/device/chat_history/FCC_CHAT01")
        assert resp.status_code == 401

    def test_chat_history_with_token_returns_200(self, client, db):
        token = "chat_correct"
        user = User(
            username="FCC_CHAT02",
            hashed_password=hash_password(token),
            full_name="聊天设备2",
            role="elderly",
        )
        db.add(user)
        db.commit()

        resp = client.get("/api/v1/public/device/chat_history/FCC_CHAT02",
                          headers={"X-Device-Token": token})
        assert resp.status_code == 200
        assert "messages" in resp.json()
