# -*- coding: utf-8 -*-
"""family_monitor.routes.auth 单元测试 + 端点冒烟（TestClient）。

通过 tests._helpers.load_module 按文件路径加载，避免触发 routes 包 __init__
连带导入整个路由栈；并以假 _execute 替换模块级 _server_client，覆盖各分支。
"""
import asyncio
import importlib.util
import json
import unittest
from collections import deque
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
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


REPO_ROOT = Path(__file__).resolve().parent.parent
_HAS = all(importlib.util.find_spec(m) is not None
           for m in ("fastapi", "httpx", "dotenv", "itsdangerous"))

if _HAS:
    import httpx
    from common.server_client import _ResponseAdapter
    from tests._helpers import load_module
    auth = load_module("family_routes_auth", "family_monitor/routes/auth.py")
else:
    auth = None
    httpx = None


def _make_resp(status_code, data=None, text=None):
    """构造 _ResponseAdapter：优先用 text，否则按 data 序列化。"""
    if text is None:
        text = json.dumps(data) if data is not None else ""
    parse_exc = None
    parsed = None
    if text:
        try:
            parsed = json.loads(text)
        except Exception as e:  # noqa: BLE001
            parsed = None
            parse_exc = e
    return _ResponseAdapter(status_code, text, parsed, parse_exc)


class _FakeExecutor:
    """替换 _server_client._execute，按调用顺序回放队列中的响应。"""

    def __init__(self):
        self.queue = deque()
        self.default = _make_resp(200, {"ok": True})
        self.raise_error = False

    async def execute(self, method, path, **kwargs):
        if self.raise_error:
            raise httpx.RequestError("connection failed")
        if self.queue:
            return self.queue.popleft()
        return self.default

    def push(self, resp):
        self.queue.append(resp)


@unittest.skipIf(auth is None, "fastapi/httpx/dotenv/itsdangerous not installed")
class TestAuthHelpers(unittest.TestCase):
    def test_get_turnstile_site_key(self):
        resp = asyncio.run(auth.get_turnstile_site_key())
        self.assertIn("site_key", resp)
        self.assertEqual(resp["site_key"], auth.config.TURNSTILE_SITE_KEY)

    def test_set_jwt_cookie(self):
        response = JSONResponse({"ok": True})
        auth._set_jwt_cookie(response, "tok123")
        cookie = response.headers.get("set-cookie", "")
        self.assertIn("access_token", cookie)
        self.assertIn("tok123", cookie)
        self.assertIn("httponly", cookie.lower())

    def test_server_url(self):
        url = auth._server_url("/auth/login")
        self.assertTrue(url.endswith("/api/v1/auth/login"))

    def test_oauth_error_messages(self):
        self.assertIn("oauth_fail", auth._OAUTH_ERROR_MESSAGES)
        self.assertTrue(auth._OAUTH_ERROR_MESSAGES["oauth_fail"])


@unittest.skipIf(auth is None, "fastapi/httpx/dotenv/itsdangerous not installed")
class TestParseServerError(unittest.TestCase):
    def _parse(self, resp, default="默认错误"):
        return auth._parse_server_error(resp, default)

    def test_string_detail(self):
        resp = _make_resp(400, {"detail": "账号或密码错误"})
        self.assertEqual(self._parse(resp), "账号或密码错误")

    def test_list_detail(self):
        resp = _make_resp(422, {"detail": [
            {"loc": ["body", "phone"], "msg": "字段必填", "type": "value_error"},
        ]})
        self.assertEqual(self._parse(resp), "phone: 字段必填")

    def test_list_detail_no_body_prefix(self):
        resp = _make_resp(422, {"detail": [
            {"loc": ["query", "x"], "msg": "无效", "type": "t"},
        ]})
        self.assertEqual(self._parse(resp), "query.x: 无效")

    def test_empty_list_falls_back(self):
        resp = _make_resp(422, {"detail": []})
        self.assertEqual(self._parse(resp, "兜底"), "兜底")

    def test_non_json_falls_back(self):
        resp = _make_resp(500, text="<html>err</html>")
        self.assertEqual(self._parse(resp, "兜底"), "兜底")


@unittest.skipIf(auth is None, "fastapi/httpx/dotenv/itsdangerous not installed")
class TestAuthPages(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(auth.router)
        self.client = _NoRedirectClient(app)
        self._orig = auth._server_client._execute
        auth._server_client._execute = _FakeExecutor().execute

    def tearDown(self):
        auth._server_client._execute = self._orig

    def test_login_page(self):
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(auth.config.APP_NAME, resp.text)

    def test_login_page_with_oauth_error(self):
        resp = self.client.get("/login?error=oauth_fail")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(auth._OAUTH_ERROR_MESSAGES["oauth_fail"], resp.text)

    def test_login_page_unknown_error(self):
        resp = self.client.get("/login?error=unknown_code")
        self.assertEqual(resp.status_code, 200)

    def test_register_page(self):
        resp = self.client.get("/register")
        self.assertEqual(resp.status_code, 200)

    def test_register_page_oauth_mode(self):
        resp = self.client.get(
            "/register?oauth=1&provider=github&provider_name=GitHub"
            "&prefill_username=alice&prefill_name=Alice&bind_email=a@b.com"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Alice", resp.text)

    def test_turnstile_site_key_endpoint(self):
        resp = self.client.get("/turnstile/site-key")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("site_key", resp.json())

    def test_oauth_github_authorize_redirect(self):
        resp = self.client.get("/oauth/github/authorize")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/api/v1/auth/oauth/github/authorize", resp.headers["location"])

    def test_oauth_gitee_authorize_redirect(self):
        resp = self.client.get("/oauth/gitee/authorize")
        self.assertEqual(resp.status_code, 302)

    def test_oauth_github_bind_no_token_redirect_login(self):
        resp = self.client.get("/oauth/github/bind")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["location"].endswith("/login"))

    def test_oauth_github_bind_with_token_redirect_server(self):
        resp = self.client.get("/oauth/github/bind", cookies={"access_token": "tok"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("token=tok", resp.headers["location"])

    def test_oauth_gitee_bind_no_token_redirect_login(self):
        resp = self.client.get("/oauth/gitee/bind")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["location"].endswith("/login"))

    def test_oauth_github_enabled_proxy(self):
        exe = auth._server_client._execute.__self__
        exe.push(_make_resp(200, {"enabled": True}))
        resp = self.client.get("/oauth/github/enabled")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"enabled": True})

    def test_oauth_github_enabled_proxy_failure(self):
        exe = auth._server_client._execute.__self__
        exe.raise_error = True
        resp = self.client.get("/oauth/github/enabled")
        self.assertEqual(resp.json(), {"enabled": False})

    def test_oauth_gitee_enabled_proxy(self):
        exe = auth._server_client._execute.__self__
        exe.push(_make_resp(200, {"enabled": False}))
        resp = self.client.get("/oauth/gitee/enabled")
        self.assertEqual(resp.json(), {"enabled": False})

    def test_logout_get(self):
        resp = self.client.get("/logout")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["location"].endswith("/login"))

    def test_logout_post(self):
        resp = self.client.post("/logout")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["location"].endswith("/login"))


@unittest.skipIf(auth is None, "fastapi/httpx/dotenv/itsdangerous not installed")
class TestLoginRegister(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(auth.router)
        self.client = _NoRedirectClient(app)
        self.exe = _FakeExecutor()
        self._orig = auth._server_client._execute
        auth._server_client._execute = self.exe.execute

    def tearDown(self):
        auth._server_client._execute = self._orig

    # ---- 登录 ----
    def test_login_success(self):
        self.exe.push(_make_resp(200, {"access_token": "jwt-token"}))
        resp = self.client.post(
            "/login", data={"phone": "13800000000", "password": "pw"}
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["redirect"], auth._PATH_PREFIX + "/")
        self.assertIn("access_token", resp.headers.get("set-cookie", ""))

    def test_login_missing_fields(self):
        resp = self.client.post("/login", data={"phone": "", "password": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["success"])

    def test_login_mfa_required(self):
        self.exe.push(_make_resp(200, {"mfa_required": True, "mfa_token": "mt"}))
        resp = self.client.post(
            "/login", data={"phone": "13800000000", "password": "pw"}
        )
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertTrue(body["mfa_required"])
        self.assertEqual(body["mfa_token"], "mt")

    def test_login_server_error_string(self):
        self.exe.push(_make_resp(401, {"detail": "手机号或密码错误"}))
        resp = self.client.post(
            "/login", data={"phone": "13800000000", "password": "bad"}
        )
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(resp.json()["success"])

    def test_login_server_422_list(self):
        self.exe.push(_make_resp(422, {"detail": [
            {"loc": ["body", "phone"], "msg": "手机号格式不正确", "type": "t"},
        ]}))
        resp = self.client.post(
            "/login", data={"phone": "x", "password": "pw"}
        )
        self.assertEqual(resp.status_code, 422)
        self.assertIn("手机号格式不正确", resp.json()["error"])

    def test_login_no_token(self):
        self.exe.push(_make_resp(200, {}))
        resp = self.client.post(
            "/login", data={"phone": "13800000000", "password": "pw"}
        )
        self.assertEqual(resp.status_code, 502)
        self.assertIn("认证服务返回异常", resp.json()["error"])

    def test_login_connection_error(self):
        self.exe.raise_error = True
        resp = self.client.post(
            "/login", data={"phone": "13800000000", "password": "pw"}
        )
        self.assertEqual(resp.status_code, 502)
        self.assertIn("无法连接认证服务", resp.json()["error"])

    # ---- 注册 ----
    def test_register_success(self):
        self.exe.push(_make_resp(201, {"access_token": "jwt-token"}))
        resp = self.client.post("/register", data={
            "phone": "13800000000", "username": "nick",
            "password": "pw", "confirm_password": "pw",
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["redirect"], auth._PATH_PREFIX + "/security-setup")

    def test_register_missing_fields(self):
        resp = self.client.post("/register", data={"phone": "", "password": ""})
        self.assertEqual(resp.status_code, 400)

    def test_register_password_mismatch(self):
        resp = self.client.post("/register", data={
            "phone": "13800000000", "password": "pw1", "confirm_password": "pw2",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("不一致", resp.json()["error"])

    def test_register_no_token_redirect_login(self):
        self.exe.push(_make_resp(201, {}))
        resp = self.client.post("/register", data={
            "phone": "13800000000", "password": "pw", "confirm_password": "pw",
        })
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["redirect"], auth._PATH_PREFIX + "/login")

    def test_register_server_error(self):
        self.exe.push(_make_resp(400, {"detail": "手机号已注册"}))
        resp = self.client.post("/register", data={
            "phone": "13800000000", "password": "pw", "confirm_password": "pw",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("手机号已注册", resp.json()["error"])

    def test_register_oauth_token_clears_cookie(self):
        self.exe.push(_make_resp(201, {"access_token": "jwt-token"}))
        resp = self.client.post("/register", data={
            "phone": "13800000000", "password": "pw", "confirm_password": "pw",
        }, cookies={"oauth_pending": "oat"})
        self.assertEqual(resp.status_code, 200)
        # 应清除 oauth_pending cookie
        self.assertIn("oauth_pending", resp.headers.get("set-cookie", ""))


@unittest.skipIf(auth is None, "fastapi/httpx/dotenv/itsdangerous not installed")
class TestEmailAndMfa(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(auth.router)
        self.client = _NoRedirectClient(app)
        self.exe = _FakeExecutor()
        self._orig = auth._server_client._execute
        auth._server_client._execute = self.exe.execute

    def tearDown(self):
        auth._server_client._execute = self._orig

    def test_email_send_code_success(self):
        self.exe.push(_make_resp(200, {"message": "已发送"}))
        resp = self.client.post("/email/send-code",
                                json={"email": "a@b.com", "cf_turnstile_token": "t"})
        self.assertTrue(resp.json()["success"])

    def test_email_send_code_missing(self):
        resp = self.client.post("/email/send-code", json={})
        self.assertEqual(resp.status_code, 400)

    def test_email_send_code_bad_json(self):
        resp = self.client.post("/email/send-code", content=b"not-json",
                                headers={"content-type": "application/json"})
        self.assertEqual(resp.status_code, 400)

    def test_email_send_code_error(self):
        self.exe.push(_make_resp(429, {"detail": "发送过于频繁"}))
        resp = self.client.post("/email/send-code", json={"email": "a@b.com"})
        self.assertEqual(resp.status_code, 429)
        self.assertIn("发送过于频繁", resp.json()["error"])

    def test_email_code_login_success(self):
        self.exe.push(_make_resp(200, {"access_token": "jwt"}))
        resp = self.client.post("/email/code-login",
                                json={"email": "a@b.com", "code": "123456"})
        self.assertTrue(resp.json()["success"])
        self.assertIn("access_token", resp.headers.get("set-cookie", ""))

    def test_email_code_login_missing(self):
        resp = self.client.post("/email/code-login", json={"email": ""})
        self.assertEqual(resp.status_code, 400)

    def test_email_code_login_no_token(self):
        self.exe.push(_make_resp(200, {}))
        resp = self.client.post("/email/code-login",
                                json={"email": "a@b.com", "code": "1"})
        self.assertEqual(resp.status_code, 502)

    def test_totp_verify_success(self):
        self.exe.push(_make_resp(200, {"access_token": "jwt"}))
        resp = self.client.post("/totp/verify", json={"code": "123456"})
        self.assertTrue(resp.json()["success"])

    def test_totp_verify_error(self):
        self.exe.push(_make_resp(400, {"detail": "动态验证码错误"}))
        resp = self.client.post("/totp/verify", json={"code": "0"})
        self.assertEqual(resp.status_code, 400)

    def test_webauthn_login_success(self):
        self.exe.push(_make_resp(200, {"access_token": "jwt"}))
        resp = self.client.post("/webauthn/login", json={"id": "c"})
        self.assertTrue(resp.json()["success"])

    def test_webauthn_login_error(self):
        self.exe.push(_make_resp(401, {"detail": "通行密钥登录失败"}))
        resp = self.client.post("/webauthn/login", json={"id": "c"})
        self.assertEqual(resp.status_code, 401)


@unittest.skipIf(auth is None, "fastapi/httpx/dotenv/itsdangerous not installed")
class TestAuthRequiredProxies(unittest.TestCase):
    """需登录 / 无需登录代理端点的覆盖。"""

    def setUp(self):
        app = FastAPI()
        app.include_router(auth.router)
        self.client = _NoRedirectClient(app)
        self.exe = _FakeExecutor()
        self._orig = auth._server_client._execute
        auth._server_client._execute = self.exe.execute

    def tearDown(self):
        auth._server_client._execute = self._orig

    def _auth_cases(self, method, path, json_body=None):
        # 未登录 -> 401
        resp = self.client.request(method, path, json=json_body)
        self.assertEqual(resp.status_code, 401)
        # 已登录 -> 代理返回
        self.exe.push(_make_resp(200, {"ok": True}))
        resp = self.client.request(method, path, json=json_body,
                                    cookies={"access_token": "tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True})

    def test_login_methods(self):
        self._auth_cases("GET", "/auth/login-methods")

    def test_bind_phone(self):
        self._auth_cases("POST", "/auth/bind-phone", json_body={"phone": "1"})

    def test_bind_email_send_code(self):
        self._auth_cases("POST", "/auth/bind-email/send-code", json_body={})

    def test_bind_email(self):
        self._auth_cases("POST", "/auth/bind-email", json_body={})

    def test_unbind_phone(self):
        self._auth_cases("DELETE", "/auth/unbind-phone")

    def test_unbind_email(self):
        self._auth_cases("DELETE", "/auth/unbind-email")

    def test_unbind_oauth(self):
        self._auth_cases("DELETE", "/auth/unbind-oauth/github")

    def test_totp_setup(self):
        self._auth_cases("POST", "/totp/setup")

    def test_totp_enable(self):
        self._auth_cases("POST", "/totp/enable", json_body={})

    def test_totp_disable(self):
        self._auth_cases("POST", "/totp/disable", json_body={})

    def test_webauthn_register_options(self):
        self._auth_cases("POST", "/webauthn/register/options")

    def test_webauthn_register(self):
        self._auth_cases("POST", "/webauthn/register", json_body={})

    def test_webauthn_login_options_public(self):
        self.exe.push(_make_resp(200, {"ok": True}))
        resp = self.client.post("/webauthn/login/options")
        self.assertEqual(resp.status_code, 200)

    def test_webauthn_list_credentials(self):
        self._auth_cases("GET", "/webauthn/credentials")

    def test_webauthn_delete_credential(self):
        self._auth_cases("DELETE", "/webauthn/credentials/abc")

    def test_security_setup_no_token(self):
        resp = self.client.get("/security-setup")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(auth.config.APP_NAME, resp.text)

    def test_security_setup_with_token(self):
        self.exe.push(_make_resp(200, {"username": "alice", "phone": "138", "mfa_enabled": True}))
        self.exe.push(_make_resp(200, [{"id": "c1"}]))
        resp = self.client.get("/security-setup", cookies={"access_token": "tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("alice", resp.text)


if __name__ == "__main__":
    unittest.main()
