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
    def test_ssid_removes_special(self):
        bad = 'a"b\\c\'d`e$f\n\r'
        self.assertEqual(wifi_config.sanitize_ssid(bad), "abcdef")

    def test_ssid_truncate_32(self):
        self.assertEqual(len(wifi_config.sanitize_ssid("x" * 40)), 32)

    def test_password_removes_special(self):
        bad = 'p"a\\s`s$word\n\r'
        self.assertEqual(wifi_config.sanitize_password(bad), "password")

    def test_normal_unchanged(self):
        self.assertEqual(wifi_config.sanitize_ssid("HomeWiFi_2.4G"), "HomeWiFi_2.4G")


if __name__ == "__main__":
    unittest.main()
