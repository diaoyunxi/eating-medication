# -*- coding: utf-8 -*-
"""family_monitor 配置校验纯逻辑测试。"""
import importlib.util
import os
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_HAS = importlib.util.find_spec("dotenv") is not None

if _HAS:
    from tests._helpers import load_module
    config_mod = load_module("family_core_config", "family_monitor/core/config.py")
else:
    config_mod = None


class _FakeConfig:
    DEBUG = True
    _secret_key_is_random = False
    APP_NAME = "测试应用"
    PATH_PREFIX = ""


@unittest.skipIf(config_mod is None, "dotenv not installed")
class TestConfig(unittest.TestCase):
    def test_generate_secret_key(self):
        key = config_mod._generate_secret_key()
        self.assertEqual(len(key), 43)

    def test_validate_ok_in_dev(self):
        fake = _FakeConfig()
        fake.DEBUG = True
        fake._secret_key_is_random = False
        fake.APP_NAME = "测试应用"
        fake.PATH_PREFIX = ""
        old = config_mod.config
        config_mod.config = fake
        try:
            os.environ.pop("PRODUCTION", None)
            config_mod.validate_mandatory_config()
        finally:
            config_mod.config = old

    def test_production_requires_explicit_key(self):
        fake = _FakeConfig()
        fake.DEBUG = False
        fake._secret_key_is_random = True
        fake.APP_NAME = "测试"
        fake.PATH_PREFIX = ""
        old = config_mod.config
        config_mod.config = fake
        try:
            os.environ["PRODUCTION"] = "true"
            with self.assertRaises(SystemExit):
                config_mod.validate_mandatory_config()
        finally:
            os.environ.pop("PRODUCTION", None)
            config_mod.config = old

    def test_bad_path_prefix_exits(self):
        fake = _FakeConfig()
        fake.DEBUG = True
        fake._secret_key_is_random = False
        fake.APP_NAME = "测试"
        fake.PATH_PREFIX = "badprefix"
        old = config_mod.config
        config_mod.config = fake
        try:
            os.environ.pop("PRODUCTION", None)
            with self.assertRaises(SystemExit):
                config_mod.validate_mandatory_config()
        finally:
            config_mod.config = old


if __name__ == "__main__":
    unittest.main()
