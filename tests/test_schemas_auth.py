# -*- coding: utf-8 -*-
"""server/app/schemas/auth.py 单元测试。

覆盖 RegisterReq / LoginReq 的字段校验（角色、手机号、用户名、密码规则）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pydantic import ValidationError  # noqa: E402

from app.schemas.auth import RegisterReq, LoginReq  # noqa: E402


class TestRegisterReq(unittest.TestCase):
    """注册请求校验。"""

    def _valid(self, **overrides):
        base = {
            "username": "alice_01",
            "password": "Passw0rd",
            "full_name": "Alice",
            "role": "family",
            "phone": "13800138000",
        }
        base.update(overrides)
        return base

    def test_valid(self):
        req = RegisterReq(**self._valid())
        self.assertEqual(req.username, "alice_01")
        self.assertEqual(req.role, "family")

    def test_invalid_role(self):
        with self.assertRaises(ValidationError):
            RegisterReq(**self._valid(role="admin"))

    def test_invalid_phone(self):
        with self.assertRaises(ValidationError):
            RegisterReq(**self._valid(phone="12345"))

    def test_username_too_short(self):
        with self.assertRaises(ValidationError):
            RegisterReq(**self._valid(username="ab"))

    def test_password_too_short(self):
        with self.assertRaises(ValidationError):
            RegisterReq(**self._valid(password="12345"))

    def test_phone_optional(self):
        # 手机号可省略
        data = self._valid()
        del data["phone"]
        req = RegisterReq(**data)
        self.assertIsNone(req.phone)


class TestLoginReq(unittest.TestCase):
    """登录请求校验。"""

    def test_valid(self):
        req = LoginReq(username="alice", password="Passw0rd")
        self.assertEqual(req.username, "alice")

    def test_username_not_validated(self):
        # LoginReq 不强制用户名长度（仅 RegisterReq 校验），应可接受
        req = LoginReq(username="ab", password="123")
        self.assertEqual(req.username, "ab")

    def test_password_not_validated(self):
        # LoginReq 不强制密码规则，应可接受任意非空密码
        req = LoginReq(username="alice", password="123")
        self.assertEqual(req.password, "123")


if __name__ == "__main__":
    unittest.main(verbosity=2)
