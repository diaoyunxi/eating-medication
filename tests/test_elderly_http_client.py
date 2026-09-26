# -*- coding: utf-8 -*-
"""老人端 HTTPClient 心跳超时解析测试（无网络/硬件依赖）。

PR #45：heartbeat_timeout 仅接受有限正数，拒绝 inf/-inf/nan/非数值/非正值，
一律回退默认 HEARTBEAT_TIMEOUT，避免 MathDomain / 无限等待等异常。
"""
import sys
import unittest
import unittest.mock as mock
from pathlib import Path

EA = Path(__file__).resolve().parent.parent / "elderly_assistant"
if str(EA) not in sys.path:
    sys.path.insert(0, str(EA))

http_client_mod = __import__("services.http_client", fromlist=["HTTPClient"])

HEARTBEAT_TIMEOUT = http_client_mod.HEARTBEAT_TIMEOUT


class TestHeartbeatTimeoutConfig(unittest.TestCase):
    """heartbeat_timeout 仅接受有限正数，非有限/非正/非数值回退默认。"""

    def _client(self, hb_cfg):
        # get_device_id 在无开发板环境下可能失败，统一打桩为安全返回值
        with mock.patch.object(http_client_mod, "get_device_id", return_value="test-dev"):
            return http_client_mod.HTTPClient(
                {"server": {"base_url": "http://t", "heartbeat_timeout": hb_cfg}}
            )

    def test_positive_kept(self):
        c = self._client(5)
        self.assertEqual(c.heartbeat_timeout, 5)

    def test_inf_falls_back(self):
        c = self._client(float("inf"))
        self.assertEqual(c.heartbeat_timeout, HEARTBEAT_TIMEOUT)

    def test_neg_inf_falls_back(self):
        c = self._client(float("-inf"))
        self.assertEqual(c.heartbeat_timeout, HEARTBEAT_TIMEOUT)

    def test_nan_falls_back(self):
        c = self._client(float("nan"))
        self.assertEqual(c.heartbeat_timeout, HEARTBEAT_TIMEOUT)

    def test_string_inf_falls_back(self):
        c = self._client("inf")
        self.assertEqual(c.heartbeat_timeout, HEARTBEAT_TIMEOUT)

    def test_string_infinity_falls_back(self):
        c = self._client("Infinity")
        self.assertEqual(c.heartbeat_timeout, HEARTBEAT_TIMEOUT)

    def test_string_nan_falls_back(self):
        c = self._client("nan")
        self.assertEqual(c.heartbeat_timeout, HEARTBEAT_TIMEOUT)

    def test_string_neg_inf_falls_back(self):
        c = self._client("-inf")
        self.assertEqual(c.heartbeat_timeout, HEARTBEAT_TIMEOUT)

    def test_negative_falls_back(self):
        c = self._client(-1)
        self.assertEqual(c.heartbeat_timeout, HEARTBEAT_TIMEOUT)

    def test_zero_falls_back(self):
        c = self._client(0)
        self.assertEqual(c.heartbeat_timeout, HEARTBEAT_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
