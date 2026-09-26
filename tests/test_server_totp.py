# -*- coding: utf-8 -*-
"""server 端 TOTP 端点回归测试。

守护 totp.py 中 encrypt/decrypt 调用名：曾误写为不存在的
encrypt_sensitive_data / decrypt_sensitive_data，运行时 NameError 导致 MFA 完全不可用。
本测试直接调用端点处理函数（mock DB 与 mfa_service），验证加解密调用真实可用、
且 totp_secret 落库为密文（可round-trip解密），防止该致命 bug 复发。
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-not-for-production-0123456789")
os.environ.setdefault("DEBUG", "true")

try:
    from app.api.v1.endpoints import totp
    from app.core.crypto import decrypt_text, encrypt_text
    from app.core.security import create_access_token, verify_mfa_token
    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False


@unittest.skipUnless(_HAVE, "需要 sqlalchemy / pydantic-settings（当前环境未安装）")
class TestTOTPHandlers(unittest.TestCase):
    def setUp(self):
        self.db = mock.MagicMock()
        self.user = mock.MagicMock()
        self.user.mfa_enabled = False
        self.user.totp_secret = None
        self.user.phone = "13800138000"
        self.user.username = "alice"
        self.user.id = 1
        self.user.is_active = True
        self.user.backup_codes = None

        # mock mfa_service：TOTP 相关纯逻辑用桩替代，专注验证端点加解密调用
        self._orig_mfa = totp.mfa_service
        fake = mock.MagicMock()
        fake.generate_totp_secret.return_value = "ABCDEFGHIJKLMNOP"
        fake.totp_provisioning_uri.return_value = "otpauth://x"
        fake.generate_totp_qr_svg.return_value = "<svg/>"
        fake.verify_totp_code.return_value = True
        fake.generate_backup_codes.return_value = ["bc1", "bc2"]
        fake.hash_backup_codes.return_value = ["h1", "h2"]
        fake.verify_backup_code.return_value = True
        fake.consume_backup_code.return_value = ["h2"]
        totp.mfa_service = fake
        self.fake_mfa = fake

        # mock security 中与 JWT 相关的调用
        self._p_verify = mock.patch.object(totp, "verify_mfa_token", return_value=1)
        self._p_verify.start()
        self._p_create = mock.patch.object(totp, "create_access_token", return_value="jwt")
        self._p_create.start()

    def tearDown(self):
        totp.mfa_service = self._orig_mfa
        self._p_verify.stop()
        self._p_create.stop()

    def test_totp_setup_encrypts_secret(self):
        """setup 必须将 TOTP 密钥加密落库（非明文），且返回明文给前端扫码。"""
        out = totp.totp_setup(self.user, self.db)
        self.assertEqual(out.secret, "ABCDEFGHIJKLMNOP")
        # totp_secret 必须是加密后的非空字符串，且不等于明文
        self.assertTrue(self.user.totp_secret)
        self.assertNotEqual(self.user.totp_secret, "ABCDEFGHIJKLMNOP")
        # 可 round-trip 解密回明文（验证用的是真实 encrypt_text）
        self.assertEqual(decrypt_text(self.user.totp_secret), "ABCDEFGHIJKLMNOP")
        self.db.commit.assert_called_once()

    def test_totp_enable_requires_setup(self):
        self.user.totp_secret = None
        with self.assertRaises(Exception):
            totp.totp_enable(totp.TOTPCodeIn(code="123456"), self.user, self.db)

    def test_totp_enable_success(self):
        self.user.totp_secret = encrypt_text("ABCDEFGHIJKLMNOP")
        out = totp.totp_enable(totp.TOTPCodeIn(code="123456"), self.user, self.db)
        self.assertEqual(out.backup_codes, ["bc1", "bc2"])
        self.assertTrue(self.user.mfa_enabled)

    def test_totp_disable_success(self):
        self.user.mfa_enabled = True
        self.user.totp_secret = encrypt_text("ABCDEFGHIJKLMNOP")
        result = totp.totp_disable(totp.TOTPCodeIn(code="123456"), self.user, self.db)
        self.assertEqual(result, {"success": True})
        self.assertFalse(self.user.mfa_enabled)
        self.assertIsNone(self.user.totp_secret)

    def test_totp_verify_success(self):
        self.user.totp_secret = encrypt_text("ABCDEFGHIJKLMNOP")
        self.db.query.return_value.filter.return_value.first.return_value = self.user
        result = totp.totp_verify(
            totp.TOTPVerifyIn(mfa_token="mt", code="123456"), self.db
        )
        self.assertEqual(result["access_token"], "jwt")
        self.assertEqual(result["token_type"], "bearer")


if __name__ == "__main__":
    unittest.main()
