# -*- coding: utf-8 -*-
"""common.server_client.BaseServerClient 单元测试（纯逻辑 + httpx 替身，无外部依赖）。"""
import asyncio
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.server_client import BaseServerClient, encode_device_id


class _FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self._text = text

    async def aread(self):
        return None

    @property
    def text(self):
        return self._text

    def json(self):
        import json as _json
        return _json.loads(self._text)


class _FakeAsyncClient:
    last = None

    def __init__(self, timeout=None, verify=True):
        self.timeout = timeout
        self.verify = verify
        self.captured = None
        _FakeAsyncClient.last = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, params=None, json=None, headers=None):
        self.captured = {
            "method": method,
            "url": url,
            "params": params,
            "json": json,
            "headers": headers,
        }
        return _FakeResponse(200, '{"ok": true, "n": 3}')


class _FakeHttpx:
    AsyncClient = _FakeAsyncClient


class _FakeBadJsonClient(_FakeAsyncClient):
    async def request(self, method, url, params=None, json=None, headers=None):
        self.captured = {"method": method, "url": url}
        return _FakeResponse(200, "{not valid json")


class _FakeHttpxBadJson:
    AsyncClient = _FakeBadJsonClient


class _FakeRaiseClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, *a, **k):
        raise RuntimeError("network down")


class _FakeHttpxRaise:
    AsyncClient = _FakeRaiseClient


@contextmanager
def _with_fake(test_case, fake_httpx):
    """上下文管理器：临时把 sys.modules['httpx'] 替换为替身。"""
    saved = sys.modules.get("httpx")
    sys.modules["httpx"] = fake_httpx
    try:
        yield
    finally:
        if saved is None:
            sys.modules.pop("httpx", None)
        else:
            sys.modules["httpx"] = saved


class TestEncodeDeviceId(unittest.TestCase):
    def test_encodes_special_chars(self):
        self.assertEqual(encode_device_id("a b/c"), "a%20b%2Fc")

    def test_encodes_chinese(self):
        enc = encode_device_id("设备A")
        self.assertNotEqual(enc, "设备A")
        self.assertNotIn(" ", enc)

    def test_empty(self):
        self.assertEqual(encode_device_id(""), "")


class TestUrlJoin(unittest.TestCase):
    def test_url_with_leading_slash(self):
        c = BaseServerClient(base_url="https://x.com/api")
        self.assertEqual(c._url("/users/me"), "https://x.com/api/users/me")

    def test_url_without_leading_slash(self):
        c = BaseServerClient(base_url="https://x.com/api")
        self.assertEqual(c._url("users/me"), "https://x.com/api/users/me")

    def test_base_url_trailing_slash_normalized(self):
        c = BaseServerClient(base_url="https://x.com/")
        self.assertEqual(c._url("/users/me"), "https://x.com/users/me")
        self.assertEqual(c.base_url, "https://x.com/")

    def test_ssl_context_only_for_https(self):
        self.assertIsNone(BaseServerClient(base_url="http://x.com")._ssl_context)
        self.assertIsNotNone(BaseServerClient(base_url="https://x.com")._ssl_context)


class TestExecute(unittest.TestCase):
    def test_execute_builds_url_merges_headers(self):
        with _with_fake(self, _FakeHttpx()):

            class Dev(BaseServerClient):
                def _auth_headers(self):
                    return {"X-Device-ID": "abc"}

            c = Dev(base_url="https://x.com/api", timeout=5.0)
            resp = asyncio.run(
                c._execute("POST", "/v1/x", params={"q": 1}, json_body={"a": 1}, headers={"X-Extra": "1"})
            )
            cap = _FakeAsyncClient.last.captured
            self.assertEqual(cap["method"], "POST")
            self.assertEqual(cap["url"], "https://x.com/api/v1/x")
            self.assertEqual(cap["params"], {"q": 1})
            self.assertEqual(cap["json"], {"a": 1})
            # 认证头优先，额外头合并
            self.assertEqual(cap["headers"]["X-Device-ID"], "abc")
            self.assertEqual(cap["headers"]["X-Extra"], "1")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"ok": True, "n": 3})

    def test_execute_json_parse_error_propagates(self):
        with _with_fake(self, _FakeHttpxBadJson()):
            c = BaseServerClient(base_url="https://x.com")
            resp = asyncio.run(c._execute("GET", "/x"))
            self.assertEqual(resp.status_code, 200)
            with self.assertRaises(Exception):
                resp.json()

    def test_execute_propagates_network_error(self):
        with _with_fake(self, _FakeHttpxRaise()):
            c = BaseServerClient(base_url="https://x.com")
            with self.assertRaises(RuntimeError):
                asyncio.run(c._execute("GET", "/x"))

    def test_check_connection_true(self):
        with _with_fake(self, _FakeHttpx()):
            c = BaseServerClient(base_url="https://x.com")
            self.assertTrue(asyncio.run(c.check_connection("/health")))

    def test_check_connection_false_on_error(self):
        with _with_fake(self, _FakeHttpxRaise()):
            c = BaseServerClient(base_url="https://x.com")
            self.assertFalse(asyncio.run(c.check_connection("/health")))


if __name__ == "__main__":
    unittest.main()
