# -*- coding: utf-8 -*-
"""server/app/schemas/auth.py 单元测试。

覆盖 RegisterReq / LoginReq 的字段校验（角色、手机号、昵称、密码规则）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pydantic import ValidationError  # noqa: E402

from app.schemas.auth import RegisterReq, LoginReq, EmailSendCodeReq, EmailCodeLoginReq  # noqa: E402


class TestRegisterReq(unittest.TestCase):
    """注册请求校验。"""

    def _valid(self, **overrides):
        base = {
            "username": "alice_01",
            "password": "Passw0rd",
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

    def test_username_too_long(self):
        # 昵称为展示名，最长 50 字符
        with self.assertRaises(ValidationError):
            RegisterReq(**self._valid(username="昵" * 51))

    def test_password_too_short(self):
        with self.assertRaises(ValidationError):
            RegisterReq(**self._valid(password="12345"))

    def test_phone_required(self):
        # 手机号为必填（唯一登录标识），缺省应报错
        data = self._valid()
        del data["phone"]
        with self.assertRaises(ValidationError):
            RegisterReq(**data)


class TestLoginReq(unittest.TestCase):
    """登录请求校验（手机号 + 密码）。"""

    def test_valid(self):
        req = LoginReq(phone="13800138000", password="Passw0rd")
        self.assertEqual(req.phone, "13800138000")

    def test_phone_required(self):
        # 手机号必填
        with self.assertRaises(ValidationError):
            LoginReq(password="123")

    def test_password_not_validated(self):
        # LoginReq 不强制密码规则，应可接受任意非空密码
        req = LoginReq(phone="13800138000", password="123")
        self.assertEqual(req.password, "123")


class TestEmailSendCodeReq(unittest.TestCase):
    """邮箱验证码 - 发送请求校验。"""

    def test_valid(self):
        req = EmailSendCodeReq(email="user@example.com")
        self.assertEqual(req.email, "user@example.com")

    def test_invalid_email(self):
        with self.assertRaises(ValidationError):
            EmailSendCodeReq(email="not-an-email")

    def test_turnstile_token_optional(self):
        req = EmailSendCodeReq(email="user@example.com")
        self.assertIsNone(req.cf_turnstile_token)


class TestEmailCodeLoginReq(unittest.TestCase):
    """邮箱验证码 - 登录请求校验。"""

    def test_valid(self):
        req = EmailCodeLoginReq(email="user@example.com", code="123456")
        self.assertEqual(req.code, "123456")

    def test_invalid_email(self):
        with self.assertRaises(ValidationError):
            EmailCodeLoginReq(email="bad", code="123456")

    def test_code_length(self):
        # code 长度限定 4~8
        with self.assertRaises(ValidationError):
            EmailCodeLoginReq(email="user@example.com", code="12")
        with self.assertRaises(ValidationError):
            EmailCodeLoginReq(email="user@example.com", code="123456789")


if __name__ == "__main__":
    unittest.main(verbosity=2)
