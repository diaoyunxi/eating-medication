# -*- coding: utf-8 -*-
"""TOTP 校验失败锁定回归测试。

守护 /auth/totp/verify 的按令牌失败锁定（修复 P3-2）：
- 连续失败达到上限后，锁定期内后续请求返回 429；
- 成功校验清零计数；
- 锁定过期后重新计数。
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
    from fastapi import HTTPException
    from app.api.v1.endpoints import totp as totp_mod
    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False


@unittest.skipUnless(_HAVE, "需要 app 环境（当前环境未安装依赖）")
class TotpLockoutTest(unittest.TestCase):
    def setUp(self):
        totp_mod._mfa_fail_attempts.clear()

    def _verify(self, code_ok: bool):
        """模拟一次 totp_verify 调用（mock 全部依赖）。"""
        user = mock.MagicMock()
        user.id = 1
        user.is_active = True
        user.totp_secret = "enc"
        user.backup_codes = None
        db = mock.MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        with mock.patch.object(totp_mod, "verify_mfa_token", return_value=1), \
             mock.patch.object(totp_mod, "decrypt_text", return_value="secret"), \
             mock.patch.object(totp_mod.mfa_service, "verify_totp_code", return_value=code_ok), \
             mock.patch.object(totp_mod.mfa_service, "verify_backup_code", return_value=False), \
             mock.patch.object(totp_mod, "create_access_token", return_value="jwt"):
            return totp_mod.totp_verify(totp_mod.TOTPVerifyIn(mfa_token="tok-1", code="123456"), db=db)

    def test_failures_below_limit_return_400(self):
        for _ in range(totp_mod._MFA_MAX_ATTEMPTS - 1):
            with self.assertRaises(HTTPException) as ctx:
                self._verify(False)
            self.assertEqual(ctx.exception.status_code, 400)

    def test_lock_after_max_failures(self):
        for _ in range(totp_mod._MFA_MAX_ATTEMPTS):
            with self.assertRaises(HTTPException):
                self._verify(False)
        # 锁定后：即使密码正确也先被 429 拦截
        with self.assertRaises(HTTPException) as ctx:
            self._verify(True)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_success_clears_attempts(self):
        with self.assertRaises(HTTPException):
            self._verify(False)
        # 成功后清零：下一次失败重新计数，不会立刻触发锁定
        self._verify(True)
        with self.assertRaises(HTTPException) as ctx:
            self._verify(False)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(totp_mod._mfa_fail_attempts.get("tok-1", [0])[0], 1)

    def test_lock_expires_and_recounts(self):
        fake_now = [10 ** 9]
        with mock.patch.object(totp_mod._time, "time", side_effect=lambda: fake_now[0]):
            for _ in range(totp_mod._MFA_MAX_ATTEMPTS):
                with self.assertRaises(HTTPException):
                    self._verify(False)
            # 锁定期内：429
            with self.assertRaises(HTTPException) as ctx:
                self._verify(True)
            self.assertEqual(ctx.exception.status_code, 429)
            # 推进时间越过锁定截止：重新计数，锁定解除后正确码可正常通过
            fake_now[0] += totp_mod._MFA_LOCK_SECONDS + 1
            result = self._verify(True)
            self.assertEqual(result["access_token"], "jwt")


if __name__ == "__main__":
    unittest.main()
