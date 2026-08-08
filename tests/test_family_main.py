# -*- coding: utf-8 -*-
"""family_monitor.main 应用装配冒烟测试。

通过 tests._helpers.load_module 加载完整应用，验证中间件、公开路由、
受保护路由重定向、lifespan 与 JWT 服务端校验逻辑，覆盖 main.py 的主体分支。
"""
import asyncio
import importlib.util
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from common.server_client import _ResponseAdapter

REPO_ROOT = Path(__file__).resolve().parent.parent
_HAS = all(importlib.util.find_spec(m) is not None
           for m in ("fastapi", "httpx", "dotenv", "itsdangerous", "uvicorn"))

if _HAS:
    from tests._helpers import load_module
    main = load_module("family_main_app", "family_monitor/main.py")
else:
    main = None


@unittest.skipIf(main is None, "fastapi/httpx/dotenv/itsdangerous/uvicorn not installed")
class TestMainApp(unittest.TestCase):
    def setUp(self):
        self.app = main.app

    def test_favicon(self):
        with TestClient(self.app) as client:
            resp = client.get("/favicon.ico")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "image/x-icon")
        # 安全响应头中间件生效
        self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")

    def test_well_known_devtools(self):
        with TestClient(self.app) as client:
            resp = client.get("/.well-known/appspecific/com.chrome.devtools.json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {})

    def test_static_404_hint(self):
        with TestClient(self.app) as client:
            resp = client.get("/static/does-not-exist.css")
        # 静态目录存在则返回 404，不存在则同样 404；均触发 static_404_hint 中间件
        self.assertIn(resp.status_code, (404,))

    def test_protected_redirect_when_unauthenticated(self):
        with TestClient(self.app, follow_redirects=False) as client:
            resp = client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["location"].endswith("/login"))

    def test_public_login_page(self):
        # 在隧道子路径模式下以带前缀路径访问登录页，验证 path_prefix 中间件的前缀剥离
        prefix = main.PATH_PREFIX
        path = f"{prefix}/login" if prefix else "/login"
        with TestClient(self.app, follow_redirects=False) as client:
            resp = client.get(path)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(main.config.APP_NAME, resp.text)

    def test_verify_jwt_via_server_success(self):
        async def fake_ok(method, p, **kw):
            return _ResponseAdapter(200, '{"username":"u","id":7}',
                                    {"username": "u", "id": 7}, None)
        main._http_client._execute = fake_ok
        result = asyncio.run(main._verify_jwt_via_server("tok"))
        self.assertEqual(result, ("u", 7))
        # 二次调用命中 30 秒缓存
        result2 = asyncio.run(main._verify_jwt_via_server("tok"))
        self.assertEqual(result2, ("u", 7))

    def test_verify_jwt_via_server_failure(self):
        async def fake_401(method, p, **kw):
            return _ResponseAdapter(401, "{}", {}, None)
        main._http_client._execute = fake_401
        result = asyncio.run(main._verify_jwt_via_server("bad"))
        self.assertIsNone(result)

    def test_lifespan_runs(self):
        # 进入上下文触发 lifespan startup/shutdown
        with TestClient(self.app) as client:
            self.assertTrue(client.app is self.app)


if __name__ == "__main__":
    unittest.main()
