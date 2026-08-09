# -*- coding: utf-8 -*-
"""阶段D step2 + step7(部分)：device_service 与统一脱敏 mask_device_id 的单元测试。

覆盖：
- mask_device_id 脱敏（长度边界）
- _parse_dt / _hhmm_to_today 时间解析（纯函数）
- DeviceService 设备身份解析、注册/心跳、令牌校验、状态计算、计划列表（内存 SQLite）
- save_upload 服药照片保存：文件名唯一性（含同一时间戳连续上传的回归用例）
"""
import base64
import os
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.security import mask_device_id
from app.models.user import User
from app.models.medication_plan import MedicationPlan
from app.services import device_service
from app.services.device_service import DeviceService


# ---------------- 纯函数：脱敏与时间解析 ----------------
def test_mask_device_id():
    assert mask_device_id("abcdefghij") == "abcd***ghij"
    # 长度不足 8 位统一返回 ***
    assert mask_device_id("abc") == "***"
    assert mask_device_id("") == "***"
    assert mask_device_id(None) == "***"


def test_parse_dt():
    assert device_service._parse_dt("") is None
    assert device_service._parse_dt(None) is None
    # 带 Z 的 ISO
    dt = device_service._parse_dt("2024-01-01T08:30:00Z")
    assert dt is not None and dt.tzinfo is None
    # 非法
    assert device_service._parse_dt("not-a-time") is None


def test_hhmm_to_today():
    now = datetime(2024, 1, 1, 12, 0, 0)
    dt = device_service.hhmm_to_today("08:30", now)
    assert dt is not None and dt.hour == 8 and dt.minute == 30 and dt.date() == now.date()
    assert device_service.hhmm_to_today("bad", now) is None


# ---------------- 内存 SQLite 集成 ----------------
def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_find_device_accounts_returns_both_candidates():
    db = _make_session()
    by_field = User(username="real-elderly", device_id="DEVICE_X", role="elderly")
    by_name = User(username="DEVICE_X", role="elderly")  # 开机注册产生的虚拟用户
    db.add_all([by_field, by_name])
    db.commit()
    f, n = DeviceService.find_device_accounts(db, "DEVICE_X")
    assert f is not None and f.id == by_field.id
    assert n is not None and n.id == by_name.id


def test_get_device_user_resolves_and_404():
    db = _make_session()
    # 仅 username 匹配（虚拟用户）也应解析成功
    db.add(User(username="DEVICE_Y", role="elderly"))
    db.commit()
    user = DeviceService.get_device_user(db, "DEVICE_Y")
    assert user.username == "DEVICE_Y"

    # 未注册 -> 404
    from fastapi import HTTPException
    try:
        DeviceService.get_device_user(db, "UNKNOWN_DEVICE")
        assert False, "应抛 404"
    except HTTPException as e:
        assert e.status_code == 404


def test_get_device_user_field_priority_over_username():
    db = _make_session()
    # device_id 字段与 username 同时匹配不同用户时，优先返回 device_id 字段命中者
    by_field = User(username="elderly-A", device_id="DUP", role="elderly")
    by_name = User(username="DUP", role="elderly")
    db.add_all([by_field, by_name])
    db.commit()
    user = DeviceService.get_device_user(db, "DUP")
    assert user.id == by_field.id


def test_get_device_user_authed():
    db = _make_session()
    user = User(
        username="dev1",
        device_id="DEVICE1234ABCD",
        device_token="tok-valid",
        role="elderly",
        last_heartbeat_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()

    # 正确令牌
    got = DeviceService.get_device_user_authed(db, "DEVICE1234ABCD", "tok-valid")
    assert got.id == user.id

    # 错误令牌 -> 403
    from fastapi import HTTPException
    try:
        DeviceService.get_device_user_authed(db, "DEVICE1234ABCD", "wrong")
        assert False, "应抛 403"
    except HTTPException as e:
        assert e.status_code == 403

    # 未注册 -> 404
    try:
        DeviceService.get_device_user_authed(db, "UNKNOWN", "x")
        assert False, "应抛 404"
    except HTTPException as e:
        assert e.status_code == 404


def test_register_or_heartbeat():
    db = _make_session()
    # 首次注册：无用户，应创建并返回 device_token
    user, token = DeviceService.register_or_heartbeat(db, "NEWDEVICE0001")
    assert user.id is not None
    assert token is not None
    assert user.device_token == token

    # 已注册设备再次心跳：不返回 token
    user2, token2 = DeviceService.register_or_heartbeat(db, "NEWDEVICE0001")
    assert user2.id == user.id
    assert token2 is None


def test_compute_status_online_offline():
    db = _make_session()
    online = User(username="o", device_id="ONLINEDEV0001", role="elderly",
                  last_heartbeat_at=datetime.now(timezone.utc))
    db.add(online)
    db.commit()
    st = DeviceService.compute_status(db, online, "ONLINEDEV0001")
    assert st["is_online"] is True
    assert st["status"] == "online"

    offline = User(username="f", device_id="OFFLINEDEV0001", role="elderly",
                   last_heartbeat_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    db.add(offline)
    db.commit()
    st2 = DeviceService.compute_status(db, offline, "OFFLINEDEV0001")
    assert st2["is_online"] is False
    assert st2["status"] == "offline"


def test_get_plans_formatting():
    db = _make_session()
    user = User(username="p", device_id="PLANUSER00001", role="elderly",
                last_heartbeat_at=datetime.now(timezone.utc))
    db.add(user)
    db.commit()
    db.refresh(user)
    plan = MedicationPlan(
        user_id=user.id, drug_name="阿司匹林", dosage="1片", frequency="每日",
        schedule_times=["08:00", "20:00"], total_quantity=30, remaining_quantity=20,
        unit="片", low_stock_threshold=5,
    )
    db.add(plan)
    db.commit()

    plans = DeviceService.get_plans(db, user)
    assert len(plans) == 1
    assert plans[0]["drug_name"] == "阿司匹林"
    assert plans[0]["schedule_times"] == ["08:00", "20:00"]
    assert plans[0]["remaining_quantity"] == 20


# ---------------- save_upload 文件名唯一性（回归测试） ----------------
def _make_user(db):
    """创建并返回一个持久化的 elderly 用户，供 save_upload 使用。"""
    user = User(username="uploader", device_id="UPLOADUSR0001", role="elderly")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _fake_jpeg():
    """返回最小合法 JPEG 的 base64 字符串（仅 SOI marker，足以通过格式校验）。"""
    return base64.b64encode(b"\xff\xd8\xff\xe0PHOTO_BYTES").decode("ascii")


def test_save_upload_returns_unique_paths():
    """连续调用 save_upload 返回的（相对）路径互不相同、均落盘成功。"""
    db = _make_session()
    user = _make_user(db)
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(device_service, "_UPLOAD_ROOT", tmp):
            paths = [
                DeviceService.save_upload(db, user, _fake_jpeg())
                for _ in range(20)
            ]
        # 20 次调用产生 20 条不同的相对路径
        assert len(paths) == 20
        assert len(set(paths)) == 20
        for p in paths:
            assert p.startswith(f"uploads/{user.id}/")
            assert p.endswith(".jpg")
        # 验证文件确实落盘到临时根目录下，且互不相同。
        # save_upload 实际存储路径为 _UPLOAD_ROOT/<user.id>/<fname>，
        # 返回的 "uploads/" 只是 URL 前缀，本地无此层目录。
        abs_paths = [os.path.join(tmp, *p.split("/")[1:]) for p in paths]
        assert len(set(os.path.abspath(a) for a in abs_paths)) == 20
        for a in abs_paths:
            assert os.path.isfile(a)


def test_save_upload_unique_under_same_timestamp():
    """回归用例：即使时间戳被冻结为同一值，随机 token 仍保证文件名唯一。

    对应 Greptile 评审意见——若将来移除 token 或降低时间精度，现有测试必须
    能阻止「同秒上传覆盖」回归。此处强制所有调用共享同一 datetime.now 返回值。
    """
    db = _make_session()
    user = _make_user(db)
    frozen = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    with tempfile.TemporaryDirectory() as tmp:
        # 冻结 device_service 内的 datetime.now，使所有调用时间戳完全一致
        fake_dt = MagicMock(now=MagicMock(return_value=frozen))
        with patch.object(device_service, "_UPLOAD_ROOT", tmp), \
             patch.object(device_service, "datetime", fake_dt):
            paths = [
                DeviceService.save_upload(db, user, _fake_jpeg())
                for _ in range(20)
            ]
        # 时间戳全相同，但 20 次调用仍应得到 20 个唯一文件名
        assert len(paths) == 20
        assert len(set(paths)) == 20
        # 文件名中时间戳前缀应完全相同（验证是 token 而非时间保证了唯一性）
        stamps = {os.path.basename(p).rsplit("_", 1)[0] for p in paths}
        assert stamps == {"20240601_120000_000000"}


def test_save_upload_rejects_invalid_encoding():
    """非法 base64 编码应抛 400。"""
    from fastapi import HTTPException
    db = _make_session()
    user = _make_user(db)
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(device_service, "_UPLOAD_ROOT", tmp):
            try:
                DeviceService.save_upload(db, user, "!!!not-base64!!!")
                assert False, "应抛 400"
            except HTTPException as e:
                assert e.status_code == 400


def test_save_upload_rejects_non_image():
    """非 JPEG/PNG 字节应抛 400。"""
    from fastapi import HTTPException
    db = _make_session()
    user = _make_user(db)
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(device_service, "_UPLOAD_ROOT", tmp):
            try:
                # 合法 base64，但解码后不是图片头
                DeviceService.save_upload(db, user, "aGVsbG8gd29ybGQ=")
                assert False, "应抛 400"
            except HTTPException as e:
                assert e.status_code == 400
