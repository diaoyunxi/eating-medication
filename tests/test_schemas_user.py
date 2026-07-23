# -*- coding: utf-8 -*-
"""app.schemas.user 单元测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pydantic import ValidationError
from app.schemas.user import UserUpdate, UserOut, BindFamilyReq


class TestUserUpdate(unittest.TestCase):
    def test_empty_allowed(self):
        u = UserUpdate()
        self.assertIsNone(u.full_name)
        self.assertIsNone(u.phone)

    def test_valid(self):
        u = UserUpdate(full_name="张三", phone="13800138000")
        self.assertEqual(u.full_name, "张三")
        self.assertEqual(u.phone, "13800138000")

    def test_full_name_too_long(self):
        with self.assertRaises(ValidationError):
            UserUpdate(full_name="张" * 51)

    def test_full_name_empty(self):
        with self.assertRaises(ValidationError):
            UserUpdate(full_name="")


class TestUserOut(unittest.TestCase):
    def test_from_attributes(self):
        # 验证 UserOut 支持 from_attributes（ORM 模式）；phone/group_id/device_id 可选
        class FakeUser:
            id = 1
            username = "alice"
            full_name = "Alice"
            role = "family"
            phone = None
            group_id = None
            device_id = None
            created_at = "2026-01-01"

        out = UserOut.model_validate(FakeUser())
        self.assertEqual(out.username, "alice")
        self.assertIsNone(out.group_id)
        self.assertIsNone(out.device_id)


class TestBindFamilyReq(unittest.TestCase):
    def test_valid(self):
        req = BindFamilyReq(elderly_user_id=1, device_id="dev-123")
        self.assertEqual(req.device_id, "dev-123")

    def test_device_id_required(self):
        with self.assertRaises(ValidationError):
            BindFamilyReq(elderly_user_id=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
