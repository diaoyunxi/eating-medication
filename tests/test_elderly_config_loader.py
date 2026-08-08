# -*- coding: utf-8 -*-
"""elderly_assistant 配置加载纯逻辑测试（扁平 .env 体系）。"""
import os
import tempfile
import unittest
from pathlib import Path

from tests._helpers import load_module

config_loader = load_module(
    "elderly_utils_config_loader", "elderly_assistant/utils/config_loader.py"
)


def _clear_env():
    """清除所有扁平 .env 键，避免 load_dotenv 残留污染后续用例。"""
    for env_key, _, _, _ in config_loader._ENV_LEAVES:
        os.environ.pop(env_key, None)


class TestLoadSave(unittest.TestCase):
    def test_default_when_missing(self):
        _clear_env()
        # 传递一个空的 .env（不存在时 load_dotenv 不报错）
        p = Path(tempfile.mkdtemp()) / ".env"
        p.write_text("", encoding="utf-8")
        cfg = config_loader.load_config(p)
        self.assertEqual(cfg["server"]["base_url"], "http://localhost:1059")
        self.assertEqual(cfg["server"]["timeout"], 10)
        self.assertEqual(cfg["hotspot"]["web_port"], 8088)
        # 用药计划轮询默认 20 分钟（1200 秒）
        self.assertEqual(cfg["reminder"]["poll_interval"], 1200)
        self.assertEqual(cfg["camera"]["connection"], "i2c")
        self.assertEqual(cfg["scan"]["source"], "auto")
        self.assertEqual(cfg["scan"]["timeout_sec"], 8.0)

    def test_override(self):
        _clear_env()
        p = Path(tempfile.mkdtemp()) / ".env"
        p.write_text(
            "SERVER_BASE_URL=http://example.com\nSERVER_TIMEOUT=30\nHOTSPOT_WEB_PORT=9000\n",
            encoding="utf-8",
        )
        cfg = config_loader.load_config(p)
        self.assertEqual(cfg["server"]["base_url"], "http://example.com")
        self.assertEqual(cfg["server"]["timeout"], 30)
        self.assertEqual(cfg["hotspot"]["web_port"], 9000)

    def test_save_server_url(self):
        _clear_env()
        p = Path(tempfile.mkdtemp()) / ".env"
        p.write_text("SERVER_BASE_URL=http://old.example\n", encoding="utf-8")
        ok = config_loader.save_server_url("http://new.example", p)
        self.assertTrue(ok)
        cfg = config_loader.load_config(p)
        self.assertEqual(cfg["server"]["base_url"], "http://new.example")

    def test_save_server_url_adds_when_absent(self):
        _clear_env()
        p = Path(tempfile.mkdtemp()) / ".env"
        p.write_text("SERVER_TIMEOUT=10\n", encoding="utf-8")
        ok = config_loader.save_server_url("http://added.example", p)
        self.assertTrue(ok)
        cfg = config_loader.load_config(p)
        self.assertEqual(cfg["server"]["base_url"], "http://added.example")

    def test_int_coercion_invalid_keeps_default(self):
        _clear_env()
        p = Path(tempfile.mkdtemp()) / ".env"
        p.write_text("SERVER_TIMEOUT=notanint\n", encoding="utf-8")
        cfg = config_loader.load_config(p)
        # 非法整数保留默认值，不崩溃
        self.assertEqual(cfg["server"]["timeout"], 10)


if __name__ == "__main__":
    unittest.main()
