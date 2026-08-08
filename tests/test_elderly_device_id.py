# -*- coding: utf-8 -*-
"""elderly_assistant 设备 ID 纯逻辑测试。

注意：pinpong 的 `Board()` 在无硬件时直接 `exit(1)`（抛 SystemExit，
源码 `try/except Exception` 无法捕获），因此必须用 mock 隔离 `pinpong.board.Board`，
避免测试进程被真实硬件初始化退出。

设备 UUID 优先级：MAC派生 > pinpong(兼容) > 随机持久化。
"""
import importlib.util
import unittest
import unittest.mock  # noqa: F401  使 unittest.mock 作为属性可用（Python 3.x 不会随 import unittest 自动加载）
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
from tests._helpers import load_module

device_id = load_module("elderly_services_device_id",
                        "elderly_assistant/services/device_id.py")


class TestDeviceId(unittest.TestCase):
    def test_pinpong_uuid_success(self):
        fake_board = unittest.mock.MagicMock()
        fake_board.uuid = "12345678-1234-1234-1234-123456789abc"
        with unittest.mock.patch("pinpong.board.Board", return_value=fake_board), \
             unittest.mock.patch("pinpong.board.gboard", fake_board):
            did = device_id._get_pinpong_uuid()
        self.assertIsNotNone(did)
        self.assertEqual(did, "12345678-1234-1234-1234-123456789abc")

    def test_pinpong_uuid_none_when_no_hardware(self):
        fake_board = unittest.mock.MagicMock()
        fake_board.begin.side_effect = Exception("no hardware")
        with unittest.mock.patch("pinpong.board.Board", return_value=fake_board):
            self.assertIsNone(device_id._get_pinpong_uuid())

    def test_mac_uuid_deterministic(self):
        fixed_mac = 0x0A1B2C3D4E5F
        with unittest.mock.patch.object(uuid, "getnode", return_value=fixed_mac):
            did = device_id._get_mac_uuid()
        # 标准 UUID 格式：8-4-4-4-12 十六进制，含 4 个连字符，共 36 字符
        self.assertEqual(len(did), 36)
        self.assertEqual(did.count("-"), 4)
        expected = str(uuid.uuid5(uuid.NAMESPACE_DNS,
                                  "eating-medication:%012X" % fixed_mac))
        self.assertEqual(did, expected)

    def test_get_device_id_uses_mac_by_default(self):
        fixed_mac = 0x0A1B2C3D4E5F
        with unittest.mock.patch.object(uuid, "getnode", return_value=fixed_mac):
            did = device_id.get_device_id()
        expected = str(uuid.uuid5(uuid.NAMESPACE_DNS,
                                  "eating-medication:%012X" % fixed_mac))
        self.assertEqual(did, expected)

    def test_get_device_id_falls_back_to_pinpong_when_no_mac(self):
        fake_board = unittest.mock.MagicMock()
        fake_board.uuid = "12345678-1234-1234-1234-123456789abc"
        with unittest.mock.patch.object(uuid, "getnode", return_value=0), \
             unittest.mock.patch("pinpong.board.Board", return_value=fake_board), \
             unittest.mock.patch("pinpong.board.gboard", fake_board):
            did = device_id.get_device_id()
        self.assertEqual(did, "12345678-1234-1234-1234-123456789abc")

    def test_persisted_uuid_format(self):
        did = device_id._get_persisted_uuid()
        # 标准 UUID 格式：8-4-4-4-12 十六进制，含 4 个连字符，共 36 字符
        self.assertEqual(len(did), 36)
        self.assertEqual(did.count("-"), 4)
        # 幂等：持久化后再次调用返回相同值
        self.assertEqual(device_id._get_persisted_uuid(), did)


if __name__ == "__main__":
    unittest.main()
