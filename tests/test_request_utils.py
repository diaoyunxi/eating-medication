# -*- coding: utf-8 -*-
"""server/app/utils/request_utils.py 单元测试。

验证真实客户端 IP 提取（修复 P3-1：伪造代理头绕过限流）：
- 未配置 TRUSTED_PROXIES 时忽略一切代理头，返回直连 IP；
- 直连 IP 命中白名单（cloudflare 关键字 / 显式 CIDR）才信任代理头；
- 未命中白名单的直连请求无法伪造代理头。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-not-for-production-0123456789")
os.environ.setdefault("DEBUG", "true")

from app.utils.request_utils import (  # noqa: E402
    _parse_trusted_proxies,
    _trusted_networks,
    get_client_ip,
)


def _set_proxies(raw):
    """设置 TRUSTED_PROXIES 并清缓存（配置读取有进程内 lru_cache）。

    返回上下文管理器，保证断言期间配置一致。
    """
    _trusted_networks.cache_clear()
    return mock.patch("app.core.config.settings.TRUSTED_PROXIES", raw)


class TestGetClientIp(unittest.TestCase):
    """请求来源 IP 提取（默认最安全：忽略代理头）。"""

    def tearDown(self):
        _trusted_networks.cache_clear()

    def test_no_trusted_proxy_ignores_cf_header(self):
        with _set_proxies(""):
            req = mock.MagicMock()
            req.headers.get.side_effect = lambda k: {
                "CF-Connecting-IP": "203.0.113.9",
                "X-Forwarded-For": "198.51.100.1, 10.0.0.1",
            }.get(k)
            req.client.host = "192.0.2.5"
            # 未配置可信代理：伪造的 CF 头无效，返回直连 IP
            self.assertEqual(get_client_ip(req), "192.0.2.5")

    def test_no_trusted_proxy_ignores_xff(self):
        with _set_proxies(""):
            req = mock.MagicMock()
            req.headers.get.side_effect = lambda k: {
                "X-Forwarded-For": "198.51.100.1, 10.0.0.1",
            }.get(k)
            req.client.host = "192.0.2.5"
            self.assertEqual(get_client_ip(req), "192.0.2.5")

    def test_client_host_fallback(self):
        with _set_proxies(""):
            req = mock.MagicMock()
            req.headers.get.return_value = None
            req.client.host = "192.0.2.5"
            self.assertEqual(get_client_ip(req), "192.0.2.5")

    def test_no_client_returns_unknown(self):
        with _set_proxies(""):
            req = mock.MagicMock()
            req.headers.get.return_value = None
            req.client = None
            self.assertEqual(get_client_ip(req), "unknown")

    # ---- 配置可信代理后：仅白名单内的直连来源可信 ----
    def test_cloudflare_keyword_trusts_cf_header(self):
        with _set_proxies("cloudflare"):
            req = mock.MagicMock()
            req.headers.get.side_effect = lambda k: {
                "CF-Connecting-IP": "203.0.113.9",
            }.get(k)
            req.client.host = "104.16.1.1"  # Cloudflare 回源段
            self.assertEqual(get_client_ip(req), "203.0.113.9")

    def test_cidr_trusts_xff_first_entry(self):
        with _set_proxies("192.0.2.0/24"):
            req = mock.MagicMock()
            req.headers.get.side_effect = lambda k: {
                "X-Forwarded-For": "198.51.100.1, 10.0.0.1",
            }.get(k)
            req.client.host = "192.0.2.5"  # 命中白名单
            self.assertEqual(get_client_ip(req), "198.51.100.1")

    def test_forged_headers_rejected_outside_whitelist(self):
        with _set_proxies("192.0.2.0/24"):
            req = mock.MagicMock()
            req.headers.get.side_effect = lambda k: {
                "CF-Connecting-IP": "203.0.113.9",
                "X-Forwarded-For": "198.51.100.1",
            }.get(k)
            req.client.host = "198.51.100.66"  # 不在白名单
            self.assertEqual(get_client_ip(req), "198.51.100.66")


class TestParseTrustedProxies(unittest.TestCase):
    """TRUSTED_PROXIES 配置解析。"""

    def test_cloudflare_keyword_expands(self):
        nets = _parse_trusted_proxies("cloudflare")
        self.assertGreater(len(nets), 20)

    def test_ignores_invalid_entries(self):
        nets = _parse_trusted_proxies("10.0.0.0/8, not-an-ip, 192.168.1.1")
        self.assertEqual(len(nets), 2)

    def test_single_ip_becomes_host_net(self):
        nets = _parse_trusted_proxies("192.168.1.1")
        self.assertEqual(str(nets[0]), "192.168.1.1/32")


if __name__ == "__main__":
    unittest.main(verbosity=2)
