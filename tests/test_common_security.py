# -*- coding: utf-8 -*-
"""common.security 纯函数测试（密码哈希/JWT/设备ID脱敏）。"""
import unittest
from datetime import timedelta

from common.security import (
    hash_password,
    verify_password,
    mask_device_id,
    create_access_token,
    decode_token,
)


class TestPasswordHashing(unittest.TestCase):
    def test_hash_and_verify(self):
        h = hash_password("secret123")
        self.assertTrue(h.startswith("$2"))
        self.assertTrue(verify_password("secret123", h))
        self.assertFalse(verify_password("wrong", h))

    def test_hash_is_salted(self):
        self.assertNotEqual(hash_password("secret123"), hash_password("secret123"))

    def test_verify_invalid_hash_returns_false(self):
        # 非 bcrypt 字符串应被捕获并返回 False，而非抛异常
        self.assertFalse(verify_password("x", "not-a-hash"))
        self.assertFalse(verify_password("x", "$2b$12$short"))


class TestMaskDeviceId(unittest.TestCase):
    def test_long(self):
        self.assertEqual(mask_device_id("ABCDEFGH1234"), "ABCD***1234")

    def test_short_returns_stars(self):
        self.assertEqual(mask_device_id("abc"), "***")
        self.assertEqual(mask_device_id(""), "***")
        self.assertEqual(mask_device_id(None), "***")

    def test_boundary_length_eight(self):
        # len == 8 不大于 8，走兜底返回 ***
        self.assertEqual(mask_device_id("ABCDEFGH"), "***")


class TestAccessToken(unittest.TestCase):
    def _roundtrip(self, data, secret="k", algorithm="HS256", delta=None):
        token = create_access_token(data, secret, algorithm, delta)
        return token, decode_token(token, secret, algorithm)

    def test_roundtrip(self):
        token, decoded = self._roundtrip({"sub": "42", "extra": "x"})
        self.assertEqual(decoded["sub"], "42")
        self.assertEqual(decoded["extra"], "x")
        self.assertEqual(decoded["type"], "access")
        self.assertIn("jti", decoded)
        self.assertIn("exp", decoded)

    def test_sub_is_string(self):
        _, decoded = self._roundtrip({"sub": 42})
        self.assertIsInstance(decoded["sub"], str)
        self.assertEqual(decoded["sub"], "42")

    def test_wrong_secret_raises(self):
        token, _ = self._roundtrip({"sub": "1"})
        with self.assertRaises(Exception):
            decode_token(token, "wrong-secret")

    def test_expired_token_raises(self):
        token = create_access_token({"sub": "1"}, "k", "HS256", expires_delta=timedelta(seconds=-1))
        with self.assertRaises(Exception):
            decode_token(token, "k")

    def test_bad_token_raises(self):
        with self.assertRaises(Exception):
            decode_token("not.a.jwt", "k")


if __name__ == "__main__":
    unittest.main()
