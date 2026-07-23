# -*- coding: utf-8 -*-
"""server/app/utils/request_utils.py 单元测试。

验证客户端 IP 提取优先级：CF-Connecting-IP > X-Forwarded-For > client.host。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.utils.request_utils import get_client_ip  # noqa: E402


class TestGetClientIp(unittest.TestCase):
    """请求来源 IP 提取。"""

    def test_cf_connecting_ip_priority(self):
        req = mock.MagicMock()
        req.headers.get.side_effect = lambda k: {
            "CF-Connecting-IP": "203.0.113.9",
            "X-Forwarded-For": "198.51.100.1, 10.0.0.1",
        }.get(k)
        req.client.host = "192.0.2.5"
        self.assertEqual(get_client_ip(req), "203.0.113.9")

    def test_x_forwarded_for_fallback(self):
        req = mock.MagicMock()
        req.headers.get.side_effect = lambda k: {
            "X-Forwarded-For": "198.51.100.1, 10.0.0.1",
        }.get(k)
        req.client.host = "192.0.2.5"
        # 取首个（最左侧原始客户端）IP
        self.assertEqual(get_client_ip(req), "198.51.100.1")

    def test_client_host_fallback(self):
        req = mock.MagicMock()
        req.headers.get.return_value = None
        req.client.host = "192.0.2.5"
        self.assertEqual(get_client_ip(req), "192.0.2.5")

    def test_no_client_returns_unknown(self):
        req = mock.MagicMock()
        req.headers.get.return_value = None
        req.client = None
        self.assertEqual(get_client_ip(req), "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
