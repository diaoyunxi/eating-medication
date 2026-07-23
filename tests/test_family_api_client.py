# -*- coding: utf-8 -*-
"""family_monitor API 客户端 device_id 编码纯逻辑测试。"""
import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_HAS = all(importlib.util.find_spec(m) is not None
           for m in ("httpx", "dotenv", "itsdangerous"))

if _HAS:
    from tests._helpers import load_module
    api_client = load_module("family_core_api_client",
                             "family_monitor/core/api_client.py")
else:
    api_client = None


@unittest.skipIf(api_client is None, "httpx/dotenv/itsdangerous not installed")
class TestEncodeDeviceId(unittest.TestCase):
    def test_encodes_special_chars(self):
        self.assertEqual(api_client._encode_device_id("a b/c"), "a%20b%2Fc")

    def test_encodes_chinese(self):
        enc = api_client._encode_device_id("设备A")
        self.assertNotEqual(enc, "设备A")
        self.assertNotIn(" ", enc)

    def test_empty(self):
        self.assertEqual(api_client._encode_device_id(""), "")


if __name__ == "__main__":
    unittest.main()
