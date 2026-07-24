# -*- coding: utf-8 -*-
"""邮箱验证码登录接口测试（FastAPI TestClient）。

覆盖：
- POST /email/send-code：成功 / Turnstile 失败 / 发信失败。
- POST /email/code-login：成功并自动建号 / 邮箱已存在直接登录 / 验证码错误 /
  Turnstile 失败 / 触发限流返回 429。

依赖通过 mock 隔离：Turnstile、IP 限流、邮件实际发送/验证码生成；
数据库使用独立的内存 SQLite（StaticPool）真实建表，验证自动建号与登录链路。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-not-for-production")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_SKIP_ENV_FILE", "1")

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.api.v1.endpoints import auth
    from app.core.database import Base
    from app.core.dependencies import get_db
    from app.models.user import User
    from app.utils import email_code

    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False


@unittest.skipUnless(_HAVE, "需要 fastapi / sqlalchemy（当前环境未安装）")
class TestEmailAuthAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 独立内存 SQLite（单连接共享，表结构在会话间持久）
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

        app = FastAPI()
        app.include_router(auth.router)

        def override_get_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    def setUp(self):
        # 清空用户表，保证用例独立
        db = self.SessionLocal()
        db.query(User).delete()
        db.commit()
        db.close()
        email_code._store.clear()
        # 默认放行人机验证与限流；具体用例按需改 return_value
        self.ts_mock = mock.patch.object(auth, "verify_turnstile", return_value=True).start()
        self.rl_mock = mock.patch.object(auth, "check_rate_limit", return_value=True).start()
        self.addCleanup(self.ts_mock.stop)
        self.addCleanup(self.rl_mock.stop)

    # ===== send-code =====
    def test_send_code_success(self):
        with mock.patch.object(email_code, "send_code",
                                return_value=(True, "验证码已发送，请查收邮箱（5 分钟内有效）")):
            resp = self.client.post("/auth/email/send-code",
                                     json={"email": "a@b.com", "cf_turnstile_token": "t"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_send_code_turnstile_fail(self):
        self.ts_mock.return_value = False
        resp = self.client.post("/auth/email/send-code",
                                 json={"email": "a@b.com", "cf_turnstile_token": "bad"})
        self.ts_mock.return_value = True
        self.assertEqual(resp.status_code, 400)
        self.assertIn("人机验证", resp.json()["detail"])

    def test_send_code_send_failed(self):
        with mock.patch.object(email_code, "send_code",
                                return_value=(False, "验证码邮件发送失败，请稍后重试")):
            resp = self.client.post("/auth/email/send-code",
                                     json={"email": "a@b.com", "cf_turnstile_token": "t"})
        self.assertEqual(resp.status_code, 400)

    def test_send_code_rate_limited(self):
        self.rl_mock.return_value = False
        with mock.patch.object(email_code, "send_code", return_value=(True, "ok")):
            resp = self.client.post("/auth/email/send-code",
                                     json={"email": "a@b.com", "cf_turnstile_token": "t"})
        self.rl_mock.return_value = True
        self.assertEqual(resp.status_code, 429)

    # ===== code-login =====
    def test_code_login_success_new_user_auto_register(self):
        with mock.patch.object(email_code, "verify_code", return_value=True):
            resp = self.client.post("/auth/email/code-login",
                                     json={"email": "New@Example.com", "code": "123456",
                                           "cf_turnstile_token": "t"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["access_token"])
        # 数据库应自动建号：邮箱归一化 + 角色 family
        db = self.SessionLocal()
        user = db.query(User).filter(User.email == "new@example.com").first()
        db.close()
        self.assertIsNotNone(user)
        self.assertEqual(user.role, "family")

    def test_code_login_existing_user_no_duplicate(self):
        db = self.SessionLocal()
        db.add(User(username="exists", hashed_password="x",
                    email="existing@x.com", role="family"))
        db.commit()
        db.close()
        with mock.patch.object(email_code, "verify_code", return_value=True):
            resp = self.client.post("/auth/email/code-login",
                                     json={"email": "existing@x.com", "code": "123456",
                                           "cf_turnstile_token": "t"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["access_token"])
        db = self.SessionLocal()
        cnt = db.query(User).filter(User.email == "existing@x.com").count()
        db.close()
        self.assertEqual(cnt, 1)  # 不重复建号

    def test_code_login_wrong_code(self):
        with mock.patch.object(email_code, "verify_code", return_value=False):
            resp = self.client.post("/auth/email/code-login",
                                     json={"email": "a@b.com", "code": "000000",
                                           "cf_turnstile_token": "t"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("验证码", resp.json()["detail"])

    def test_code_login_turnstile_fail(self):
        self.ts_mock.return_value = False
        with mock.patch.object(email_code, "verify_code", return_value=True):
            resp = self.client.post("/auth/email/code-login",
                                     json={"email": "a@b.com", "code": "123456",
                                           "cf_turnstile_token": "bad"})
        self.ts_mock.return_value = True
        self.assertEqual(resp.status_code, 400)
        self.assertIn("人机验证", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
