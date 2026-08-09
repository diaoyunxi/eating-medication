# -*- coding: utf-8 -*-
"""elderly_assistant 热点联网检测纯逻辑测试。"""
import socket
import unittest
from unittest import mock

from tests._helpers import load_module

hotspot_manager = load_module(
    "elderly_services_hotspot_manager", "elderly_assistant/services/hotspot_manager.py"
)


class TestHotspotIsOnline(unittest.TestCase):
    def test_online_when_probe_reachable(self):
        # 任一探测地址可连即视为联网
        with mock.patch("socket.create_connection", return_value=mock.MagicMock()):
            hm = hotspot_manager.HotspotManager()
            self.assertTrue(hm.is_online())

    def test_offline_when_all_probes_fail(self):
        # 全部探测失败 -> 离线
        with mock.patch("socket.create_connection", side_effect=OSError("unreachable")):
            hm = hotspot_manager.HotspotManager()
            self.assertFalse(hm.is_online())

    def test_returns_bool(self):
        # 无论网络如何，返回值必须是布尔类型
        def _fake(addr, timeout):
            if addr[0] == "8.8.8.8":
                raise OSError("no")
            raise OSError("no")

        with mock.patch("socket.create_connection", side_effect=_fake):
            hm = hotspot_manager.HotspotManager()
            self.assertIsInstance(hm.is_online(), bool)


if __name__ == "__main__":
    unittest.main()
