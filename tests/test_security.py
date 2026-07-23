# -*- coding: utf-8 -*-
"""app.core.security 单元测试（需要 jose 与 pydantic-settings）。

本文件在导入任何 app 模块前注入测试环境变量，避免配置校验 sys.exit。
若运行环境缺少 jose / pydantic-settings，则整体跳过（不影响其它用例）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 在导入 app 之前注入环境变量，确保配置校验通过且可复现
os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-not-for-production-0123456789")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test_elderly_care.db")
os.environ.setdefault("API_V1_PREFIX", "/api/v1")
os.environ.setdefault("PATH_PREFIX", "/eating-medication/server")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")

try:
    from app.core.security import (
        hash_password,
        verify_password,
        create_access_token,
        decode_token,
        create_oauth_state_token,
        verify_oauth_state_token,
        create_oauth_pending_token,
        verify_oauth_pending_token,
    )
    _HAVE_SECURITY = True
except Exception:  # pragma: no cover - 依赖缺失时跳过
    _HAVE_SECURITY = False


@unittest.skipUnless(_HAVE_SECURITY, "需要 jose / pydantic-settings（当前环境未安装）")
class TestPasswordHashing(unittest.TestCase):
    def test_hash_and_verify(self):
        h = hash_password("Secret123")
        self.assertTrue(h.startswith("$2"))
        self.assertTrue(verify_password("Secret123", h))
        self.assertFalse(verify_password("wrong", h))

    def test_verify_invalid_hash(self):
        # 非法哈希不应抛异常，应返回 False
        self.assertFalse(verify_password("x", ""))
        self.assertFalse(verify_password("x", "not-a-hash"))

    def test_hash_is_salted(self):
        self.assertNotEqual(hash_password("Secret123"), hash_password("Secret123"))


@unittest.skipUnless(_HAVE_SECURITY, "需要 jose / pydantic-settings（当前环境未安装）")
class TestAccessToken(unittest.TestCase):
    def test_roundtrip(self):
        token = create_access_token({"sub": "alice", "role": "family"})
        payload = decode_token(token)
        self.assertEqual(payload["sub"], "alice")
        self.assertEqual(payload["role"], "family")
        self.assertEqual(payload.get("type"), "access")

    def test_sub_is_string(self):
        token = create_access_token({"sub": 123})
        self.assertEqual(decode_token(token)["sub"], "123")

    def test_expired_token_raises(self):
        from datetime import timedelta

        token = create_access_token({"sub": "alice"}, expires_delta=timedelta(seconds=-1))
        with self.assertRaises(Exception):
            decode_token(token)


@unittest.skipUnless(_HAVE_SECURITY, "需要 jose / pydantic-settings（当前环境未安装）")
class TestOAuthStateToken(unittest.TestCase):
    def test_roundtrip(self):
        token = create_oauth_state_token("state-abc")
        self.assertEqual(verify_oauth_state_token(token), "state-abc")

    def test_invalid_state_returns_none(self):
        self.assertIsNone(verify_oauth_state_token("not.a.valid.token"))

    def test_access_token_not_oauth_state(self):
        access = create_access_token({"sub": "x"})
        self.assertIsNone(verify_oauth_state_token(access))


@unittest.skipUnless(_HAVE_SECURITY, "需要 jose / pydantic-settings（当前环境未安装）")
class TestOAuthPendingToken(unittest.TestCase):
    def test_roundtrip(self):
        token = create_oauth_pending_token(
            provider="github",
            provider_id=42,
            provider_login="octocat",
            email="octo@example.com",
        )
        payload = verify_oauth_pending_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["provider"], "github")
        self.assertEqual(payload["provider_id"], 42)
        self.assertEqual(payload["provider_login"], "octocat")

    def test_wrong_type_returns_none(self):
        access = create_access_token({"sub": "x"})
        self.assertIsNone(verify_oauth_pending_token(access))


if __name__ == "__main__":
    unittest.main(verbosity=2)
