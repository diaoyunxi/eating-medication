# -*- coding: utf-8 -*-
"""family_monitor 会话管理纯逻辑测试。"""
import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_HAS_ITS = importlib.util.find_spec("itsdangerous") is not None

if _HAS_ITS:
    from tests._helpers import load_module
    session_mod = load_module("family_core_session", "family_monitor/core/session.py")
else:
    session_mod = None


@unittest.skipIf(session_mod is None, "itsdangerous not installed")
class TestSessionManager(unittest.TestCase):
    def test_create_and_verify(self):
        sm = session_mod.SessionManager("secret")
        token = sm.create_session("alice")
        data = sm.verify_session(token)
        self.assertIsNotNone(data)
        self.assertEqual(data["username"], "alice")
        self.assertTrue(sm.is_session_valid(token))

    def test_invalidate(self):
        sm = session_mod.SessionManager("secret")
        token = sm.create_session("bob")
        self.assertTrue(sm.invalidate_session(token))
        self.assertIsNone(sm.verify_session(token))
        self.assertFalse(sm.is_session_valid(token))

    def test_csrf(self):
        sm = session_mod.SessionManager("secret")
        csrf = sm.generate_csrf_token()
        self.assertTrue(sm.verify_csrf_token(csrf))
        self.assertFalse(sm.verify_csrf_token("bad.token"))

    def test_wrong_secret_rejects(self):
        sm1 = session_mod.SessionManager("secret1")
        sm2 = session_mod.SessionManager("secret2")
        token = sm1.create_session("x")
        self.assertIsNone(sm2.verify_session(token))


if __name__ == "__main__":
    unittest.main()
