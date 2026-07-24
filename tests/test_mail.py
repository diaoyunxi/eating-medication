# -*- coding: utf-8 -*-
"""app.utils.mail 单元测试。

覆盖：
- mail_enabled() 分支判断（SMTP / API / 未配置 / 非法 provider）。
- send_email() 降级：未配置 provider 时返回 False 且不抛异常。
- _send_smtp()：标准 SMTP 发信（starttls / login / sendmail 调用）。
- _send_api()：Resend 兼容 HTTP API 发信（成功 / 失败返回 False）。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-not-for-production")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test_mail.db")

try:
    from app.utils import mail
    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False


@unittest.skipUnless(_HAVE, "需要 httpx / smtplib（标准库）")
class TestMailEnabled(unittest.TestCase):
    def _patch(self, **kwargs):
        defaults = dict(
            MAIL_PROVIDER=None, MAIL_HOST=None, MAIL_PORT=None,
            MAIL_USERNAME=None, MAIL_PASSWORD=None, MAIL_FROM=None,
            MAIL_API_URL=None, MAIL_API_KEY=None,
        )
        defaults.update(kwargs)
        return mock.patch.multiple(mail.settings, **defaults)

    def test_disabled_when_provider_unset(self):
        with self._patch(MAIL_PROVIDER=""):
            self.assertFalse(mail.mail_enabled())

    def test_disabled_invalid_provider(self):
        with self._patch(MAIL_PROVIDER="gcp"):
            self.assertFalse(mail.mail_enabled())

    def test_smtp_enabled_full(self):
        with self._patch(MAIL_PROVIDER="smtp", MAIL_HOST="smtp.x",
                          MAIL_FROM="a@b.com", MAIL_USERNAME="u"):
            self.assertTrue(mail.mail_enabled())

    def test_smtp_disabled_missing_host(self):
        with self._patch(MAIL_PROVIDER="smtp", MAIL_FROM="a@b.com", MAIL_USERNAME="u"):
            self.assertFalse(mail.mail_enabled())

    def test_api_enabled_full(self):
        with self._patch(MAIL_PROVIDER="api",
                          MAIL_API_URL="https://api.x/emails", MAIL_API_KEY="k"):
            self.assertTrue(mail.mail_enabled())

    def test_api_disabled_missing_key(self):
        with self._patch(MAIL_PROVIDER="api", MAIL_API_URL="https://api.x/emails"):
            self.assertFalse(mail.mail_enabled())


@unittest.skipUnless(_HAVE, "需要 httpx / smtplib（标准库）")
class TestSendEmail(unittest.TestCase):
    def test_send_disabled_returns_false_no_raise(self):
        with mock.patch.object(mail.settings, "MAIL_PROVIDER", ""):
            self.assertFalse(mail.send_email("a@b.com", "sub", "<p>hi</p>"))

    def test_send_smtp_success(self):
        with mock.patch.object(mail.settings, "MAIL_PROVIDER", "smtp"), \
                mock.patch.object(mail.settings, "MAIL_HOST", "smtp.x"), \
                mock.patch.object(mail.settings, "MAIL_PORT", "587"), \
                mock.patch.object(mail.settings, "MAIL_FROM", "from@b.com"), \
                mock.patch.object(mail.settings, "MAIL_USERNAME", "u"), \
                mock.patch.object(mail.settings, "MAIL_PASSWORD", "p"), \
                mock.patch.object(mail.settings, "MAIL_USE_TLS", True), \
                mock.patch.object(mail.settings, "MAIL_USE_SSL", False), \
                mock.patch.object(mail, "smtplib") as msmtp:
            server = mock.MagicMock()
            # smtplib.SMTP(...) 作为上下文管理器返回 server
            msmtp.SMTP.return_value.__enter__.return_value = server
            result = mail.send_email("to@b.com", "主题", "<p>内容</p>")
        self.assertTrue(result)
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("u", "p")
        server.sendmail.assert_called_once()

    def test_send_api_success(self):
        with mock.patch.object(mail.settings, "MAIL_PROVIDER", "api"), \
                mock.patch.object(mail.settings, "MAIL_API_URL", "https://api.x/emails"), \
                mock.patch.object(mail.settings, "MAIL_API_KEY", "k"), \
                mock.patch.object(mail.settings, "MAIL_FROM", "from@b.com"), \
                mock.patch.object(mail, "httpx") as mhttpx:
            resp = mock.MagicMock()
            resp.status_code = 200
            mhttpx.post.return_value = resp
            result = mail.send_email("to@b.com", "主题", "<p>内容</p>")
        self.assertTrue(result)
        mhttpx.post.assert_called_once()

    def test_send_api_error_returns_false(self):
        with mock.patch.object(mail.settings, "MAIL_PROVIDER", "api"), \
                mock.patch.object(mail.settings, "MAIL_API_URL", "https://api.x/emails"), \
                mock.patch.object(mail.settings, "MAIL_API_KEY", "k"), \
                mock.patch.object(mail, "httpx") as mhttpx:
            resp = mock.MagicMock()
            resp.status_code = 400
            resp.text = "bad"
            mhttpx.post.return_value = resp
            result = mail.send_email("to@b.com", "主题", "<p>内容</p>")
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
