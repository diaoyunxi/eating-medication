# -*- coding: utf-8 -*-
"""app.utils.validators 单元测试（unittest 风格，与现有测试套件一致）。

覆盖：手机号 / 用户名 / 密码 / 时间格式四类校验器的正常、边界与非法输入。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.utils.validators import (
    is_valid_phone,
    is_valid_username,
    is_valid_password,
    is_valid_time_format,
    is_valid_email,
)


class TestIsValidPhone(unittest.TestCase):
    def test_falsy_is_valid(self):
        # 手机号可选：空值 / None 视为通过
        self.assertTrue(is_valid_phone(None))
        self.assertTrue(is_valid_phone(""))

    def test_valid(self):
        for phone in ["13800138000", "19912345678"]:
            self.assertTrue(is_valid_phone(phone), phone)

    def test_invalid(self):
        for phone in [
            "12345678901",   # 第二位非 3-9
            "1380013800",    # 10 位（不足 11）
            "138001380000",  # 12 位（超出 11）
            "abcdefghijk",   # 非数字
            "1380013800a",   # 含字母
        ]:
            self.assertFalse(is_valid_phone(phone), phone)


class TestIsValidUsername(unittest.TestCase):
    def test_invalid(self):
        for username in ["", "ab", "a" * 21, "user-name", "user name", "用户"]:
            self.assertFalse(is_valid_username(username), username)

    def test_valid(self):
        for username in ["ab1", "user_name", "User123", "alice01"]:
            self.assertTrue(is_valid_username(username), username)


class TestIsValidPassword(unittest.TestCase):
    def test_invalid(self):
        for pwd in ["", "abcdef", "123456", "a" * 101, "abc", "123"]:
            self.assertFalse(is_valid_password(pwd), pwd)

    def test_valid(self):
        for pwd in ["abcd12", "Passw0", "1a" * 3, "abc123"]:
            self.assertTrue(is_valid_password(pwd), pwd)


class TestIsValidTimeFormat(unittest.TestCase):
    def test_valid(self):
        for t in ["00:00", "08:00", "23:59", "12:30:45"]:
            self.assertTrue(is_valid_time_format(t), t)

    def test_invalid(self):
        for t in ["24:00", "08:60", "8:00", "12:345", "ab:cd", ""]:
            self.assertFalse(is_valid_time_format(t), t)


class TestIsValidEmail(unittest.TestCase):
    def test_valid(self):
        for email in [
            "a@b.com",
            "user.name@sub.example.com",
            "user+tag@domain.io",
            "user-01@a-b.co",
        ]:
            self.assertTrue(is_valid_email(email), email)

    def test_invalid(self):
        for email in [
            "",
            None,
            "no-at-sign",
            "a@b",
            "a@b.",
            "@missing-local.com",
            "missing-domain@",
            "a b@c.com",        # 含空格
            "a" * 255 + "@b.com",  # 超长（>254）
        ]:
            self.assertFalse(is_valid_email(email), repr(email))


if __name__ == "__main__":
    unittest.main(verbosity=2)
