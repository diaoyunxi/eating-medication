# -*- coding: utf-8 -*-
"""OAuth 邮箱所有权校验回归测试。

守护 oauth.py 的邮箱过滤逻辑：
- GitHub /user/emails 回退只接受「主邮箱且已验证」的邮箱；
- 未验证邮箱（攻击者可将其设为 GitHub 主邮箱）不得用于账号合并/注册；
- _fetch_email 在 require_verified=True 时不回退到未验证邮箱。
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
    from app.api.v1.endpoints.oauth import _fetch_email, _pick_verified_email
    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False


@unittest.skipUnless(_HAVE, "需要 app 环境（当前环境未安装依赖）")
class PickVerifiedEmailTest(unittest.TestCase):
    """_pick_verified_email：GitHub /user/emails 过滤逻辑"""

    def test_picks_primary_and_verified(self):
        emails = [
            {"email": "a@x.com", "primary": False, "verified": True},
            {"email": "victim@x.com", "primary": True, "verified": True},
        ]
        self.assertEqual(_pick_verified_email(emails), "victim@x.com")

    def test_rejects_unverified_primary(self):
        # 攻击者把受害者邮箱设为主邮箱但未验证：必须返回 None，绝不回退
        emails = [
            {"email": "victim@x.com", "primary": True, "verified": False},
            {"email": "attacker@x.com", "primary": False, "verified": True},
        ]
        self.assertIsNone(_pick_verified_email(emails))

    def test_requires_primary(self):
        # 全部已验证但无主邮箱：同样视为不可信
        emails = [
            {"email": "a@x.com", "primary": False, "verified": True},
            {"email": "b@x.com", "primary": False, "verified": True},
        ]
        self.assertIsNone(_pick_verified_email(emails))

    def test_empty_and_malformed(self):
        self.assertIsNone(_pick_verified_email([]))
        self.assertIsNone(_pick_verified_email("not-a-list"))
        self.assertIsNone(_pick_verified_email([{"email": "x@x.com"}]))


@unittest.skipUnless(_HAVE, "需要 app 环境（当前环境未安装依赖）")
class FetchEmailTest(unittest.TestCase):
    """_fetch_email：require_verified=True 时不回退到未验证邮箱"""

    def _run(self, emails_payload, require_verified=True):
        with mock.patch("httpx.get") as m_get:
            m_get.return_value.json.return_value = emails_payload
            import asyncio
            return asyncio.run(
                _fetch_email(
                    "https://api.github.com/user/emails",
                    "fake-access-token",
                    "Bearer",
                    require_verified=require_verified,
                )
            )

    def test_verified_primary_returned(self):
        emails = [{"email": "ok@x.com", "primary": True, "verified": True}]
        self.assertEqual(self._run(emails), "ok@x.com")

    def test_unverified_primary_rejected(self):
        emails = [
            {"email": "victim@x.com", "primary": True, "verified": False},
            {"email": "attacker@x.com", "primary": False, "verified": True},
        ]
        self.assertIsNone(self._run(emails))

    def test_no_verified_primary_rejected(self):
        emails = [{"email": "a@x.com", "primary": True, "verified": False}]
        self.assertIsNone(self._run(emails))

    def test_lenient_mode_falls_back_to_first(self):
        # Gitee（require_verified=False）保持原行为：取列表首个
        emails = [{"email": "first@x.com", "primary": False}]
        self.assertEqual(self._run(emails, require_verified=False), "first@x.com")


if __name__ == "__main__":
    unittest.main()
