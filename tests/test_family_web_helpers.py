# -*- coding: utf-8 -*-
"""family_monitor 路由共享工具（routes.web_helpers）单元测试。

验证从 home/chat/ai_config 抽出的共享鉴权三件套与用户 JWT 服务端请求封装。
通过 tests._helpers.load_module 按文件路径加载，避免触发 routes 包 __init__
连带导入整个路由栈。
"""
import asyncio
import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FAMILY_DIR = REPO_ROOT / "family_monitor"
if str(FAMILY_DIR) not in sys.path:
    sys.path.insert(0, str(FAMILY_DIR))

_HAS = all(importlib.util.find_spec(m) is not None
           for m in ("fastapi", "httpx", "dotenv", "itsdangerous"))

if _HAS:
    from tests._helpers import load_module
    web_helpers = load_module(
        "family_web_helpers", "family_monitor/routes/web_helpers.py"
    )
else:
    web_helpers = None


class _FakeState:
    user = None


class _FakeRequest:
    def __init__(self, user=None):
        self.state = _FakeState()
        self.state.user = user


def _real_user_api_client():
    from core import config
    from common.server_client import BaseServerClient
    return BaseServerClient(
        base_url=f"{config.ELDERLY_SERVER_URL.rstrip('/')}/api/v1",
        timeout=15.0,
    )


@unittest.skipIf(web_helpers is None, "fastapi/httpx/dotenv/itsdangerous not installed")
class TestAuthHelpers(unittest.TestCase):
    def test_require_login(self):
        self.assertTrue(web_helpers.require_login(_FakeRequest(user="u1")))
        self.assertFalse(web_helpers.require_login(_FakeRequest(user=None)))

    def test_login_redirect_url(self):
        resp = web_helpers.login_redirect()
        self.assertEqual(resp.status_code, 302)
        prefix = web_helpers.config.PATH_PREFIX.rstrip("/")
        expected = f"{prefix}/login" if prefix else "/login"
        self.assertEqual(resp.headers["location"], expected)

    def test_unauthorized_json(self):
        resp = web_helpers.unauthorized_json()
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(json.loads(resp.body)["success"])
        self.assertEqual(json.loads(resp.body)["message"], "请先登录")


@unittest.skipIf(web_helpers is None, "fastapi/httpx/dotenv/itsdangerous not installed")
class TestUserApiRequest(unittest.TestCase):
    def tearDown(self):
        web_helpers._user_api_client = _real_user_api_client()

    def test_ok(self):
        class _FakeResp:
            status_code = 200
            text = "{}"

            def json(self):
                return {"providers": [1, 2]}

        class _FakeClient:
            async def _execute(self, *a, **k):
                return _FakeResp()

        web_helpers._user_api_client = _FakeClient()
        status, data = asyncio.run(
            web_helpers.user_api_request("GET", "/ai/providers", token="t")
        )
        self.assertEqual(status, 200)
        self.assertEqual(data, {"providers": [1, 2]})

    def test_non_json_body(self):
        class _FakeResp:
            status_code = 500
            text = "internal error"

            def json(self):
                raise ValueError("not json")

        class _FakeClient:
            async def _execute(self, *a, **k):
                return _FakeResp()

        web_helpers._user_api_client = _FakeClient()
        status, data = asyncio.run(
            web_helpers.user_api_request("GET", "/x", token=None)
        )
        self.assertEqual(status, 500)
        self.assertEqual(data, {"detail": "internal error"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
