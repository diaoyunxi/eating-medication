# -*- coding: utf-8 -*-
"""app.utils.email_code 单元测试。

覆盖：验证码发送（成功 / 邮件未配置 / 重发间隔 / 每日上限）、校验（成功 / 错误码 /
过期 / 一次性消费防重放）。发信依赖通过 mock 隔离。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-not-for-production")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test_email_code.db")

try:
    from app.utils import email_code
    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False


@unittest.skipUnless(_HAVE, "需要 sqlalchemy / pydantic-settings（当前环境未安装）")
class TestEmailCode(unittest.TestCase):
    def setUp(self):
        # 每个用例前清空进程内存储，避免相互污染
        email_code._store.clear()

    def test_send_code_success_stores(self):
        with mock.patch.object(email_code, "mail_enabled", return_value=True), \
                mock.patch.object(email_code, "send_email", return_value=True):
            ok, msg = email_code.send_code("User@Example.com")
        self.assertTrue(ok)
        self.assertIn("已发送", msg)
        rec = email_code._store.get("user@example.com")
        self.assertIsNotNone(rec)
        self.assertEqual(len(rec.code), email_code.CODE_LENGTH)
        self.assertGreater(rec.expires_at, rec.last_sent_at)

    def test_send_code_mail_disabled(self):
        with mock.patch.object(email_code, "mail_enabled", return_value=False):
            ok, msg = email_code.send_code("a@b.com")
        self.assertFalse(ok)
        self.assertIn("未配置", msg)
        # 未配置时不写入存储
        self.assertNotIn("a@b.com", email_code._store)

    def test_send_code_resend_interval(self):
        fake = {"t": 1000.0}

        def fake_time():
            return fake["t"]

        with mock.patch.object(email_code, "mail_enabled", return_value=True), \
                mock.patch.object(email_code, "send_email", return_value=True), \
                mock.patch.object(email_code.time, "time", side_effect=fake_time):
            ok1, _ = email_code.send_code("a@b.com")
            # 仅过 30 秒，未到 60 秒重发间隔
            fake["t"] = 1030.0
            ok2, msg2 = email_code.send_code("a@b.com")
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertIn("频繁", msg2)

    def test_send_code_daily_limit(self):
        fake = {"t": 1000.0}

        def fake_time():
            return fake["t"]

        with mock.patch.object(email_code, "mail_enabled", return_value=True), \
                mock.patch.object(email_code, "send_email", return_value=True), \
                mock.patch.object(email_code.time, "time", side_effect=fake_time):
            for _ in range(email_code.DAILY_LIMIT):
                fake["t"] += 61.0  # 超过重发间隔，模拟多次发送
                ok, _ = email_code.send_code("a@b.com")
                self.assertTrue(ok)
            # 超过每日上限后再次发送应失败
            fake["t"] += 61.0
            ok_over, msg_over = email_code.send_code("a@b.com")
        self.assertFalse(ok_over)
        self.assertIn("上限", msg_over)

    def test_verify_success_and_one_time(self):
        with mock.patch.object(email_code, "mail_enabled", return_value=True), \
                mock.patch.object(email_code, "send_email", return_value=True):
            email_code.send_code("a@b.com")
        code = email_code._store["a@b.com"].code
        # 校验成功
        self.assertTrue(email_code.verify_code("a@b.com", code))
        # 一次性：再次校验同一码应失败（已被消费）
        self.assertFalse(email_code.verify_code("a@b.com", code))

    def test_verify_wrong_code_not_consume(self):
        with mock.patch.object(email_code, "mail_enabled", return_value=True), \
                mock.patch.object(email_code, "send_email", return_value=True):
            email_code.send_code("a@b.com")
        code = email_code._store["a@b.com"].code
        # 错误码校验失败，且不消费存储（正确码仍可验证）
        self.assertFalse(email_code.verify_code("a@b.com", "000000"))
        self.assertTrue(email_code.verify_code("a@b.com", code))

    def test_verify_expired(self):
        fake = {"t": 1000.0}

        def fake_time():
            return fake["t"]

        with mock.patch.object(email_code, "mail_enabled", return_value=True), \
                mock.patch.object(email_code, "send_email", return_value=True), \
                mock.patch.object(email_code.time, "time", side_effect=fake_time):
            email_code.send_code("a@b.com")
            fake["t"] += email_code.CODE_TTL_SECONDS + 1  # 超过有效期
            code = email_code._store["a@b.com"].code
        # 真实时间远大于过期时间，校验应失败
        self.assertFalse(email_code.verify_code("a@b.com", code))


if __name__ == "__main__":
    unittest.main(verbosity=2)
