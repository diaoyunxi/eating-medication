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


class _NoRedirectClient:
    """兼容新旧 starlette 的 TestClient 包装：请求级统一不跟随重定向。

    新版 starlette（>=0.28）TestClient 构造器支持 follow_redirects 且默认 True；
    旧版构造器不接受该参数。本包装在请求级透传 follow_redirects=False，
    使两个版本下行为一致，避免带 PATH_PREFIX 的 302 被本地独立 app 误判为 404。
    """

    def __init__(self, app):
        self.app = app
        self._client = TestClient(app)

    def _call(self, method, *args, **kwargs):
        kwargs.setdefault("follow_redirects", False)
        return getattr(self._client, method)(*args, **kwargs)

    def get(self, *args, **kwargs):
        return self._call("get", *args, **kwargs)

    def post(self, *args, **kwargs):
        return self._call("post", *args, **kwargs)

    def put(self, *args, **kwargs):
        return self._call("put", *args, **kwargs)

    def delete(self, *args, **kwargs):
        return self._call("delete", *args, **kwargs)

    def request(self, *args, **kwargs):
        return self._call("request", *args, **kwargs)

    def __enter__(self):
        self._client.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._client.__exit__(exc_type, exc, tb)


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
        with _NoRedirectClient(self.app) as client:
            resp = client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["location"].endswith("/login"))

    def test_public_login_page(self):
        # 旧版 starlette 的 TestClient 不会按 app.root_path 自动剥离前缀，无法在测试客户端中
        # 模拟 Cloudflare 隧道的子路径转发；此处将 PATH_PREFIX 临时置空（等价于本地直连语义），
        # 验证登录页公开可访问。前缀剥离行为由真实 ASGI server 与 path_prefix_middleware 保证。
        saved = main.PATH_PREFIX
        main.PATH_PREFIX = ""
        try:
            with _NoRedirectClient(self.app) as client:
                resp = client.get("/login")
            self.assertEqual(resp.status_code, 200)
            self.assertIn(main.config.APP_NAME, resp.text)
        finally:
            main.PATH_PREFIX = saved

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
