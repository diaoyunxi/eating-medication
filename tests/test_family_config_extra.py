# -*- coding: utf-8 -*-
"""family_monitor.core.config 额外测试：save_config / _generate_default_env / _update_env_file。"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_HAS = importlib.util.find_spec("dotenv") is not None

if _HAS:
    from tests._helpers import load_module
    config_mod = load_module("family_core_config_extra", "family_monitor/core/config.py")
else:
    config_mod = None


@unittest.skipIf(config_mod is None, "dotenv not installed")
class TestGenerateDefaultEnv(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_env = Path(self._tmp.name) / ".env"

    def tearDown(self):
        self._tmp.cleanup()

    def test_generate_default_env(self):
        config_mod.config._generate_default_env(self.tmp_env)
        self.assertTrue(self.tmp_env.exists())
        content = self.tmp_env.read_text(encoding="utf-8")
        self.assertIn("SECRET_KEY=", content)
        self.assertIn("DEBUG=true", content)
        self.assertIn("SERVER_PORT=4430", content)
        self.assertIn("APP_NAME=子女守护中心", content)


@unittest.skipIf(config_mod is None, "dotenv not installed")
class TestSaveConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_env = Path(self._tmp.name) / ".env"
        # 基线 .env（含被更新字段的 key，便于 update_env_fields 就地修改）
        self.tmp_env.write_text(
            "APP_NAME=旧名\nSERVER_PORT=4430\nELDERLY_SERVER_URL=http://x\n"
            "PATH_PREFIX=\nDISPLAY_THEME=light\nDISPLAY_COLOR=purple\n"
            "DISPLAY_LANGUAGE=zh-CN\nDISPLAY_ANIMATIONS=True\nDISPLAY_COMPACT=False\n"
            "TURNSTILE_SITE_KEY=\n",
            encoding="utf-8",
        )
        self.config = config_mod.config
        self._orig_env_path = self.config.env_path
        self._orig_app_name = self.config.APP_NAME
        self._orig_server_port = self.config.SERVER_PORT
        self._orig_elderly_url = self.config.ELDERLY_SERVER_URL
        self.config.env_path = self.tmp_env

    def tearDown(self):
        self.config.env_path = self._orig_env_path
        self.config.APP_NAME = self._orig_app_name
        self.config.SERVER_PORT = self._orig_server_port
        self.config.ELDERLY_SERVER_URL = self._orig_elderly_url
        self._tmp.cleanup()

    def test_save_config_writes_fields(self):
        self.config.APP_NAME = "新名字"
        self.config.SERVER_PORT = 9999
        self.config.ELDERLY_SERVER_URL = "https://example.com/server"
        self.assertTrue(self.config.save_config())
        content = self.tmp_env.read_text(encoding="utf-8")
        self.assertIn("APP_NAME=新名字", content)
        self.assertIn("SERVER_PORT=9999", content)
        self.assertIn("ELDERLY_SERVER_URL=https://example.com/server", content)

    def test_save_config_returns_false_on_failure(self):
        # env_path 指向目录（不可写文件）时应失败并返回 False
        self.config.env_path = Path(self._tmp.name)
        self.assertFalse(self.config.save_config())


if __name__ == "__main__":
    unittest.main()
