# -*- coding: utf-8 -*-
"""elderly_assistant 配置加载/合并纯逻辑测试。"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_HAS_YAML = importlib.util.find_spec("yaml") is not None

if _HAS_YAML:
    from tests._helpers import load_module
    config_loader = load_module("elderly_utils_config_loader",
                                "elderly_assistant/utils/config_loader.py")
else:
    config_loader = None


@unittest.skipIf(config_loader is None, "pyyaml not installed")
class TestDeepMerge(unittest.TestCase):
    def test_nested_merge(self):
        base = {"a": 1, "b": {"x": 1, "y": 2}}
        override = {"b": {"y": 3, "z": 4}, "c": 5}
        merged = config_loader._deep_merge(base, override)
        # 原对象不被修改
        self.assertEqual(base["b"]["y"], 2)
        self.assertEqual(merged, {"a": 1, "b": {"x": 1, "y": 3, "z": 4}, "c": 5})

    def test_scalar_override(self):
        self.assertEqual(config_loader._deep_merge({"a": 1}, {"a": 2}), {"a": 2})

    def test_list_override(self):
        self.assertEqual(config_loader._deep_merge({"a": [1, 2]}, {"a": [3]}), {"a": [3]})


@unittest.skipIf(config_loader is None, "pyyaml not installed")
class TestLoadSave(unittest.TestCase):
    def test_default_when_missing(self):
        p = os.path.join(tempfile.mkdtemp(), "config.yaml")
        cfg = config_loader.load_config(p)
        self.assertEqual(cfg["server"]["base_url"], "http://localhost:1059")
        self.assertTrue(os.path.exists(p))

    def test_roundtrip(self):
        p = os.path.join(tempfile.mkdtemp(), "config.yaml")
        cfg = {"server": {"base_url": "http://example.com"}}
        config_loader.save_config(cfg, p)
        loaded = config_loader.load_config(p)
        self.assertEqual(loaded["server"]["base_url"], "http://example.com")


if __name__ == "__main__":
    unittest.main()
