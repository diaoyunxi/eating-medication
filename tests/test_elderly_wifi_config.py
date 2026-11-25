# -*- coding: utf-8 -*-
"""elderly_assistant WiFi 配置清洗纯逻辑测试。"""
import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_HAS_YAML = importlib.util.find_spec("yaml") is not None

if _HAS_YAML:
    from tests._helpers import load_module
    wifi_config = load_module("elderly_services_wifi_config",
                              "elderly_assistant/services/wifi_config.py")
else:
    wifi_config = None


@unittest.skipIf(wifi_config is None, "pyyaml not installed")
class TestSanitize(unittest.TestCase):
    # 契约已变更：sanitize_* 不再静默删字符/截断，而是校验失败直接抛 ValueError
    # （见 elderly_assistant/services/wifi_config.py 的 docstring：shell=False 无需过滤，
    #   静默改密码会导致连接失败且用户不知情）。以下用例按新契约断言。

    def test_ssid_rejects_control_chars(self):
        bad = 'a"b\\c\'d`e$f\n\r'
        with self.assertRaises(ValueError):
            wifi_config.sanitize_ssid(bad)

    def test_ssid_rejects_over_32_bytes(self):
        with self.assertRaises(ValueError):
            wifi_config.sanitize_ssid("x" * 40)

    def test_ssid_rejects_empty(self):
        with self.assertRaises(ValueError):
            wifi_config.sanitize_ssid("   ")

    def test_ssid_rejects_nul_byte(self):
        with self.assertRaises(ValueError):
            wifi_config.sanitize_ssid("abc\x00def")

    def test_password_rejects_control_chars(self):
        bad = 'p"a\\s`s$word\n\r'
        with self.assertRaises(ValueError):
            wifi_config.sanitize_password(bad)

    def test_password_length_bounds(self):
        # WPA2 要求 8-63 字符
        with self.assertRaises(ValueError):
            wifi_config.sanitize_password("a\n" * 1)
        with self.assertRaises(ValueError):
            wifi_config.sanitize_password("1234567")
        with self.assertRaises(ValueError):
            wifi_config.sanitize_password("x" * 64)
        self.assertEqual(wifi_config.sanitize_password("password123"), "password123")

    def test_normal_unchanged(self):
        self.assertEqual(wifi_config.sanitize_ssid("HomeWiFi_2.4G"), "HomeWiFi_2.4G")


if __name__ == "__main__":
    unittest.main()
