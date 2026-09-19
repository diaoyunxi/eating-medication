# -*- coding: utf-8 -*-
"""elderly_assistant 设备 ID 纯逻辑测试。

设备 ID 直接取 `uuid.getnode()`（网卡 MAC 地址整数值），
不再使用 uuid5 派生、pinpong 兼容分支与本地持久化兜底。
"""
import unittest
import unittest.mock  # noqa: F401  使 unittest.mock 作为属性可用（Python 3.x 不会随 import unittest 自动加载）
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
from tests._helpers import load_module

device_id = load_module("elderly_services_device_id",
                        "elderly_assistant/services/device_id.py")


class TestDeviceId(unittest.TestCase):
    def test_returns_getnode_decimal_string(self):
        """设备 ID 为 uuid.getnode() 的十进制字符串形式"""
        fixed_mac = 0x0A1B2C3D4E5F
        with unittest.mock.patch.object(uuid, "getnode", return_value=fixed_mac):
            did = device_id.get_device_id()
        self.assertEqual(did, str(fixed_mac))
        self.assertTrue(did.isdigit())

    def test_deterministic_across_calls(self):
        """同一 MAC 多次调用返回一致（重启不变的前提）"""
        fixed_mac = 0x0A1B2C3D4E5F
        with unittest.mock.patch.object(uuid, "getnode", return_value=fixed_mac):
            first = device_id.get_device_id()
            second = device_id.get_device_id()
        self.assertEqual(first, second)

    def test_returns_none_when_mac_unavailable(self):
        """MAC 读取为 0（不可用）时返回 None，不再回落其它来源"""
        with unittest.mock.patch.object(uuid, "getnode", return_value=0):
            self.assertIsNone(device_id.get_device_id())

    def test_returns_none_when_getnode_raises(self):
        """getnode 异常时降级返回 None，不向外抛出"""
        with unittest.mock.patch.object(uuid, "getnode",
                                        side_effect=Exception("no nic")):
            self.assertIsNone(device_id.get_device_id())

    def test_no_legacy_helpers(self):
        """确认 uuid5 派生 / pinpong / 持久化兜底三个旧实现已移除"""
        for name in ("_get_mac_uuid", "_get_pinpong_uuid", "_get_persisted_uuid"):
            self.assertFalse(hasattr(device_id, name),
                             f"遗留函数未清理: {name}")


if __name__ == "__main__":
    unittest.main()
