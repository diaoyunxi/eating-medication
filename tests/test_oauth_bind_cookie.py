# -*- coding: utf-8 -*-
"""OAuth 绑定 JWT 传输安全回归测试。

守护修复 P3-4（JWT 不得出现在 URL 查询参数）：
- POST /auth/oauth/bind-start 以 Authorization header 交换 HttpOnly cookie；
- 无 Authorization 头 / 无效 JWT 返回 401；
- _bind_authorize 只接受 cookie 中的 oauth_bind_jwt，忽略 query token。
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-not-for-production-0123456789")
os.environ.setdefault("DEBUG", "true")

try:
    from app.api.v1.endpoints.oauth import _bind_authorize, oauth_bind_start
    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False


class _FakeRequest:
    def __init__(self, auth_header=None, cookies=None):
        self.headers = {"Authorization": auth_header} if auth_header else {}
        self.cookies = cookies or {}
        self.client = type("C", (), {"host": "127.0.0.1"})()


@unittest.skipUnless(_HAVE, "需要 app 环境（当前环境未安装依赖）")
class OAuthBindStartTest(unittest.TestCase):
    def test_valid_token_sets_cookie(self):
        req = _FakeRequest(auth_header="Bearer good-jwt")
        with mock.patch("app.api.v1.endpoints.oauth.decode_token",
                        return_value={"sub": 42, "exp": 9999999999}):
            resp = asyncio.run(oauth_bind_start(req))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.body, b'{"success": true}')
        # Set-Cookie 携带 oauth_bind_jwt（HttpOnly）
        headers = resp.raw_headers
        cookie_headers = [v.decode() for k, v in headers if k == b"set-cookie"]
        self.assertTrue(any("oauth_bind_jwt=good-jwt" in h for h in cookie_headers))
        self.assertTrue(any("HttpOnly" in h for h in cookie_headers))

    def test_missing_auth_header_401(self):
        resp = asyncio.run(oauth_bind_start(_FakeRequest()))
        self.assertEqual(resp.status_code, 401)

    def test_invalid_jwt_401(self):
        req = _FakeRequest(auth_header="Bearer bad-jwt")
        with mock.patch("app.api.v1.endpoints.oauth.decode_token",
                        side_effect=Exception("bad token")):
            resp = asyncio.run(oauth_bind_start(req))
        self.assertEqual(resp.status_code, 401)

    def test_bind_authorize_reads_cookie_not_query(self):
        # query 中带 token 但 cookie 缺失：拒绝（不再接受 URL 参数）
        req = mock.MagicMock()
        req.cookies.get.return_value = ""
        with mock.patch("app.api.v1.endpoints.oauth._authorize") as m_auth:
            m_auth.return_value = mock.MagicMock()
            with mock.patch("app.api.v1.endpoints.oauth._OAUTH", {"github": {}}):
                resp = asyncio.run(_bind_authorize("github", req))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("error=no_token", resp.headers["location"])
        m_auth.assert_not_called()

    def test_bind_authorize_accepts_cookie(self):
        req = mock.MagicMock()
        req.cookies.get.return_value = "cookie-jwt"
        with mock.patch("app.api.v1.endpoints.oauth._authorize") as m_auth, \
             mock.patch("app.api.v1.endpoints.oauth.decode_token",
                        return_value={"sub": 42}) as m_decode, \
             mock.patch("app.api.v1.endpoints.oauth._OAUTH", {"github": {}}):
            m_auth.return_value = mock.MagicMock()
            asyncio.run(_bind_authorize("github", req))
            m_decode.assert_called_once_with("cookie-jwt")
            m_auth.assert_called_once()


if __name__ == "__main__":
    unittest.main()
