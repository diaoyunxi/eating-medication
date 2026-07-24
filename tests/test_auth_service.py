# -*- coding: utf-8 -*-
"""app.services.auth_service 单元测试（需要 sqlalchemy / pydantic-settings）。

AuthService 方法均为同步，依赖注入的 db 为 SQLAlchemy Session。
依赖缺失时整体跳过。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-not-for-production-0123456789")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test_elderly_care.db")

try:
    from app.services.auth_service import AuthService
    from app.schemas.auth import RegisterReq
    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False


@unittest.skipUnless(_HAVE, "需要 sqlalchemy / pydantic-settings（当前环境未安装）")
class TestBindProvider(unittest.TestCase):
    def test_bind_github(self):
        user = mock.MagicMock()
        AuthService._bind_provider(user, "github", 123)
        self.assertEqual(user.github_id, 123)
        self.assertEqual(user.oauth_provider, "github")

    def test_bind_gitee(self):
        user = mock.MagicMock()
        AuthService._bind_provider(user, "gitee", 456)
        self.assertEqual(user.gitee_id, 456)
        self.assertEqual(user.oauth_provider, "gitee")


@unittest.skipUnless(_HAVE, "需要 sqlalchemy / pydantic-settings（当前环境未安装）")
class TestRegister(unittest.TestCase):
    def _req(self):
        return RegisterReq(
            username="alice",
            password="Passw0rd",
            full_name="Alice",
            role="family",
            phone="13800138000",
        )

    def test_register_returns_token(self):
        db = mock.MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        token = AuthService.register(db, self._req())
        self.assertIsInstance(token, str)
        self.assertTrue(token)
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_register_username_conflict_gets_suffix(self):
        db = mock.MagicMock()
        existing = mock.MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [existing, None, None]
        token = AuthService.register(db, self._req())
        self.assertIsInstance(token, str)


@unittest.skipUnless(_HAVE, "需要 sqlalchemy / pydantic-settings（当前环境未安装）")
class TestLogin(unittest.TestCase):
    def test_login_success(self):
        db = mock.MagicMock()
        user = mock.MagicMock()
        user.hashed_password = "hashed"
        db.query.return_value.filter.return_value.first.return_value = user
        with mock.patch("app.services.auth_service.verify_password", return_value=True), \
                mock.patch("app.services.auth_service.create_access_token", return_value="tok"):
            self.assertEqual(AuthService.login(db, "alice", "Passw0rd"), "tok")

    def test_login_wrong_password(self):
        db = mock.MagicMock()
        user = mock.MagicMock()
        user.hashed_password = "hashed"
        db.query.return_value.filter.return_value.first.return_value = user
        with mock.patch("app.services.auth_service.verify_password", return_value=False):
            self.assertIsNone(AuthService.login(db, "alice", "wrong"))

    def test_login_user_not_found(self):
        db = mock.MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        self.assertIsNone(AuthService.login(db, "ghost", "x"))


@unittest.skipUnless(_HAVE, "需要 sqlalchemy / pydantic-settings（当前环境未安装）")
class TestLoginOrRegisterByEmail(unittest.TestCase):
    """邮箱验证码登录 / 自动注册。验证码校验由接口层完成，此处直接进入服务方法。"""

    def test_existing_email_logs_in(self):
        db = mock.MagicMock()
        user = mock.MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        with mock.patch("app.services.auth_service.create_access_token", return_value="tok"):
            token = AuthService.login_or_register_by_email(db, "Existing@Example.com")
        self.assertEqual(token, "tok")
        # 已注册：不新建账号，仅提交最后登录时间
        db.add.assert_not_called()
        db.commit.assert_called()

    def test_new_email_auto_registers(self):
        db = mock.MagicMock()
        # 邮箱未注册 -> 建号；用户名前缀未冲突 -> 不再查重
        db.query.return_value.filter.return_value.first.return_value = None
        with mock.patch("app.services.auth_service.create_access_token", return_value="tok"), \
                mock.patch("app.services.auth_service.hash_password", return_value="hashed"):
            token = AuthService.login_or_register_by_email(db, "New@Example.com")
        self.assertEqual(token, "tok")
        db.add.assert_called_once()
        created = db.add.call_args.args[0]
        # 邮箱归一化为小写；未注册自动建号默认角色 family
        self.assertEqual(created.email, "new@example.com")
        self.assertEqual(created.role, "family")


if __name__ == "__main__":
    unittest.main(verbosity=2)
