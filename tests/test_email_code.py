# -*- coding: utf-8 -*-
"""app.utils.email_code 单元测试。

覆盖：验证码发送（成功 / 发送失败 / 邮箱为空）、校验（成功 / 一次性消费防重放 /
错误码不消费 / 过期 / 空参数）。发信依赖通过 mock 隔离，仅验证实现真实存在的行为。

说明：
- 实现中 _store 为 email(小写) -> (code, expire_ts) 的元组，无对象字段。
- 实现无 mail_enabled 开关、无重发间隔、无每日上限；这些增强功能本测试不覆盖。
- 实现先写入 _store 再调用 _send_email 发送；因此发送失败时 _store 仍会保留记录。
"""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))

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
        # 模拟发信成功
        with mock.patch.object(email_code, "_send_email", return_value=(True, "")):
            ok, msg = email_code.send_code("User@Example.com")
        self.assertTrue(ok)
        self.assertIn("已发送", msg)
        rec = email_code._store.get("user@example.com")
        self.assertIsNotNone(rec)
        # _store 为 (code, expire_ts) 元组
        self.assertEqual(len(rec[0]), email_code._CODE_LEN)
        self.assertGreater(rec[1], time.time())  # 过期时间在未来

    def test_send_code_send_failed(self):
        # 模拟邮件服务未配置（_send_email 返回失败）
        err_msg = "邮件服务未配置，无法发送验证码（请配置 MAIL_* 后重试）"
        with mock.patch.object(email_code, "_send_email", return_value=(False, err_msg)):
            ok, msg = email_code.send_code("a@b.com")
        self.assertFalse(ok)
        self.assertIn("未配置", msg)
        # 实现先于发送写入 _store，故发送失败时记录仍会保留
        self.assertIn("a@b.com", email_code._store)

    def test_send_code_empty_email(self):
        # 邮箱为空直接返回失败，不写存储、不发信
        ok, msg = email_code.send_code("")
        self.assertFalse(ok)
        self.assertIn("不能为空", msg)
        self.assertEqual(len(email_code._store), 0)

    def test_verify_success_and_one_time(self):
        with mock.patch.object(email_code, "_send_email", return_value=(True, "")):
            email_code.send_code("a@b.com")
        code = email_code._store["a@b.com"][0]
        # 校验成功
        self.assertTrue(email_code.verify_code("a@b.com", code))
        # 一次性：再次校验同一码应失败（已被消费）
        self.assertFalse(email_code.verify_code("a@b.com", code))

    def test_verify_wrong_code_not_consume(self):
        with mock.patch.object(email_code, "_send_email", return_value=(True, "")):
            email_code.send_code("a@b.com")
        code = email_code._store["a@b.com"][0]
        # 错误码校验失败，且不消费存储（正确码仍可验证）
        self.assertFalse(email_code.verify_code("a@b.com", "000000"))
        self.assertTrue(email_code.verify_code("a@b.com", code))

    def test_verify_expired(self):
        fake = {"t": 1000.0}

        def fake_time():
            return fake["t"]

        with mock.patch.object(email_code, "_send_email", return_value=(True, "")), \
                mock.patch.object(email_code.time, "time", side_effect=fake_time):
            email_code.send_code("a@b.com")
            fake["t"] += email_code._CODE_TTL + 1  # 超过有效期
            code = email_code._store["a@b.com"][0]
        # 真实时间远大于过期时间，校验应失败
        self.assertFalse(email_code.verify_code("a@b.com", code))

    def test_verify_empty_args(self):
        # 空邮箱或空验证码直接返回失败，不抛异常
        self.assertFalse(email_code.verify_code("", ""))
        self.assertFalse(email_code.verify_code("a@b.com", ""))
        self.assertFalse(email_code.verify_code("", "123456"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
