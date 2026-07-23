# -*- coding: utf-8 -*-
"""elderly_assistant 设备 ID 纯逻辑测试。

注意：pinpong 的 `Board()` 在无硬件时直接 `exit(1)`（抛 SystemExit，
源码 `try/except Exception` 无法捕获），因此必须用 mock 隔离 `pinpong.board.Board`，
避免测试进程被真实硬件初始化退出。
"""
import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
from tests._helpers import load_module

device_id = load_module("elderly_services_device_id",
                        "elderly_assistant/services/device_id.py")


class TestDeviceId(unittest.TestCase):
    def test_fcc_id_success(self):
        fake_board = unittest.mock.MagicMock()
        fake_board.mac = "AA:BB:CC:DD:EE:FF"
        with unittest.mock.patch("pinpong.board.Board", return_value=fake_board):
            fcc = device_id._get_fcc_id()
        self.assertIsNotNone(fcc)
        self.assertTrue(fcc.startswith("FCC_"))
        self.assertEqual(len(fcc), 4 + 12)

    def test_fcc_id_none_when_no_hardware(self):
        fake_board = unittest.mock.MagicMock()
        fake_board.begin.side_effect = Exception("no hardware")
        with unittest.mock.patch("pinpong.board.Board", return_value=fake_board):
            self.assertIsNone(device_id._get_fcc_id())

    def test_persisted_uuid_format(self):
        did = device_id._get_persisted_uuid()
        self.assertTrue(did.startswith("DEV_"))
        # 幂等：持久化后再次调用返回相同值
        self.assertEqual(device_id._get_persisted_uuid(), did)

    def test_get_device_id_uses_fcc(self):
        fake_board = unittest.mock.MagicMock()
        fake_board.mac = "11:22:33:44:55:66"
        with unittest.mock.patch("pinpong.board.Board", return_value=fake_board):
            did = device_id.get_device_id()
        self.assertTrue(did.startswith("FCC_"))


if __name__ == "__main__":
    unittest.main()
