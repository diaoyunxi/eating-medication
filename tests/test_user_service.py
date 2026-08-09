# -*- coding: utf-8 -*-
"""UserService 单元测试（通知偏好设置存取）。

依赖通过内存 SQLite 真实建表验证通知设置的保存与解析。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-not-for-production")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_SKIP_ENV_FILE", "1")

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models.user import User
    from app.schemas.user import UserOut, UserUpdate
    from app.services.user_service import UserService

    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False


@unittest.skipUnless(_HAVE, "需要 sqlalchemy（当前环境未安装）")
class TestNotificationSettings(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        db = self.SessionLocal()
        db.add(User(username="tester", role="family", phone="13800138000"))
        db.commit()
        db.close()

    def _new_user(self):
        db = self.SessionLocal()
        u = User(username="u2", role="family", phone="13900139000")
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
        db.close()
        return uid

    def test_save_partial_merges_defaults(self):
        # 仅传部分键：应合并默认值后保存为完整快照
        db = self.SessionLocal()
        uid = self._new_user()
        updated = UserService.update_user(
            db, uid, UserUpdate(notification_settings={"missed_reminder": False, "browser_notification": True})
        )
        out = UserOut.model_validate(updated)
        self.assertIsInstance(out.notification_settings, dict)
        self.assertEqual(
            out.notification_settings,
            {
                "medication_reminder": True,
                "missed_reminder": False,
                "offline_reminder": True,
                "browser_notification": True,
                "sound_alert": True,
            },
        )
        db.close()

    def test_invalid_value_is_coerced(self):
        # 非法值应能被 bool() 容错（字符串 "yes" -> True）
        db = self.SessionLocal()
        uid = self._new_user()
        updated = UserService.update_user(
            db, uid, UserUpdate(notification_settings={"sound_alert": "yes"})
        )
        out = UserOut.model_validate(updated)
        self.assertTrue(out.notification_settings["sound_alert"])
        db.close()

    def test_none_keeps_unset(self):
        # 不传 notification_settings 时原值保持 None
        db = self.SessionLocal()
        uid = self._new_user()
        updated = UserService.update_user(db, uid, UserUpdate(username="renamed"))
        self.assertIsNone(updated.notification_settings)
        db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
