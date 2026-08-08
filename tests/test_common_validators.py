# -*- coding: utf-8 -*-
"""common.validators 纯函数测试（与 server/app/utils/validators 同源但为独立模块）。"""
import unittest

from common.validators import (
    is_valid_phone,
    is_valid_username,
    is_valid_password,
    is_valid_time_format,
    is_valid_email,
)


class TestIsValidPhone(unittest.TestCase):
    def test_none_or_empty_returns_true(self):
        self.assertTrue(is_valid_phone(None))
        self.assertTrue(is_valid_phone(""))

    def test_valid(self):
        self.assertTrue(is_valid_phone("13800138000"))
        self.assertTrue(is_valid_phone("19912345678"))

    def test_invalid(self):
        self.assertFalse(is_valid_phone("12345"))       # 太短
        self.assertFalse(is_valid_phone("23800138000"))  # 首位非 1[3-9]
        self.assertFalse(is_valid_phone("1380013800a"))  # 含非数字
        self.assertFalse(is_valid_phone("138001380000"))  # 太长


class TestIsValidUsername(unittest.TestCase):
    def test_empty_false(self):
        self.assertFalse(is_valid_username(""))
        self.assertFalse(is_valid_username(None))

    def test_length_bounds(self):
        self.assertFalse(is_valid_username("ab"))      # <3
        self.assertFalse(is_valid_username("a" * 21))  # >20

    def test_valid(self):
        self.assertTrue(is_valid_username("abc"))
        self.assertTrue(is_valid_username("user_123"))
        self.assertTrue(is_valid_username("A_B_9"))

    def test_invalid_chars(self):
        self.assertFalse(is_valid_username("user name"))  # 空格
        self.assertFalse(is_valid_username("user-name"))  # 连字符
        self.assertFalse(is_valid_username("用户"))        # 非 ASCII


class TestIsValidPassword(unittest.TestCase):
    def test_empty_false(self):
        self.assertFalse(is_valid_password(""))
        self.assertFalse(is_valid_password(None))

    def test_length_bounds(self):
        self.assertFalse(is_valid_password("abc12"))    # <6
        self.assertFalse(is_valid_password("a" * 101))  # >100

    def test_requires_letter_and_digit(self):
        self.assertFalse(is_valid_password("abcdef"))  # 无数字
        self.assertFalse(is_valid_password("123456"))  # 无字母

    def test_valid(self):
        self.assertTrue(is_valid_password("abc123"))
        self.assertTrue(is_valid_password("Password1"))


class TestIsValidTimeFormat(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(is_valid_time_format("08:00"))
        self.assertTrue(is_valid_time_format("23:59"))
        self.assertTrue(is_valid_time_format("00:00:00"))
        self.assertTrue(is_valid_time_format("12:30:45"))

    def test_invalid(self):
        self.assertFalse(is_valid_time_format("24:00"))  # 小时越界
        self.assertFalse(is_valid_time_format("12:60"))  # 分钟越界
        self.assertFalse(is_valid_time_format("8:00"))   # 缺前导零
        self.assertFalse(is_valid_time_format("abc"))
        self.assertFalse(is_valid_time_format(""))


class TestIsValidEmail(unittest.TestCase):
    def test_empty_false(self):
        self.assertFalse(is_valid_email(""))
        self.assertFalse(is_valid_email(None))

    def test_too_long(self):
        self.assertFalse(is_valid_email("a" * 300 + "@b.com"))

    def test_valid(self):
        self.assertTrue(is_valid_email("user@example.com"))
        self.assertTrue(is_valid_email("a.b+c@sub.domain.co.uk"))

    def test_invalid(self):
        self.assertFalse(is_valid_email("user@"))            # 缺域名
        self.assertFalse(is_valid_email("@example.com"))     # 缺本地
        self.assertFalse(is_valid_email("user.example.com"))  # 缺 @
        self.assertFalse(is_valid_email("user@ex"))          # 缺 TLD 点


if __name__ == "__main__":
    unittest.main()
