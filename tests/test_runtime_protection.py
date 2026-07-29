# -*- coding: utf-8 -*-
"""common.runtime_protection 单一事实来源的回归测试。

验证两组判定：
- is_protected_path：更新 / 部署保护（.env、data/、logs/、*.db 等）
- is_reset_preserved_path：重置保留（仅 .env 与 logs/）

此前 PROTECTED_* 与 PRESERVE_* 散落于 updater.py / reset_runtime.py，
本测试作为合并后的统一回归网。
"""
import os
import sys
import unittest
from pathlib import Path

# 保证仓库根在 sys.path，便于直接 import common.*
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.runtime_protection import (  # noqa: E402
    is_protected_path,
    is_reset_preserved_path,
)


class TestIsProtectedPath(unittest.TestCase):
    """更新 / 部署保护：范围应广，覆盖嵌套 .env 与 data/、logs/ 等运行时数据。"""

    def test_root_env(self):
        self.assertTrue(is_protected_path(".env"))

    def test_nested_env_each_module(self):
        for mod in ("server", "family_monitor", "elderly_assistant"):
            self.assertTrue(is_protected_path(f"{mod}/.env"))

    def test_nested_data_file(self):
        self.assertTrue(is_protected_path("server/data/db.sqlite"))

    def test_data_dir_name_protected(self):
        self.assertTrue(is_protected_path("data"))

    def test_logs_dir_and_file(self):
        self.assertTrue(is_protected_path("logs"))
        self.assertTrue(is_protected_path("logs/x.log"))

    def test_db_patterns(self):
        self.assertTrue(is_protected_path("x.db"))
        self.assertTrue(is_protected_path("y.sqlite3"))
        self.assertTrue(is_protected_path("z.sqlite"))

    def test_git_protected(self):
        self.assertTrue(is_protected_path(".git/config"))

    def test_venv_protected(self):
        self.assertTrue(is_protected_path(".venv"))
        self.assertTrue(is_protected_path("venv"))
        self.assertTrue(is_protected_path(".venv/Scripts/python.exe"))

    def test_case_insensitive(self):
        self.assertTrue(is_protected_path("server/.ENV"))
        self.assertTrue(is_protected_path("server/DATA/X.DB"))

    def test_non_protected_paths(self):
        self.assertFalse(is_protected_path("README.md"))
        self.assertFalse(is_protected_path("server/app/main.py"))
        self.assertFalse(is_protected_path("docs/guide.txt"))

    def test_path_input_forms(self):
        # 同时接受 str / Path / 路径段元组
        self.assertTrue(is_protected_path(Path("server/.env")))
        self.assertTrue(is_protected_path(("server", ".env")))


class TestIsResetPreservedPath(unittest.TestCase):
    """重置保留：范围应窄，仅 .env 与 logs/，刻意不含 data/、*.db。"""

    def test_env_preserved(self):
        self.assertTrue(is_reset_preserved_path((".env",)))
        self.assertTrue(is_reset_preserved_path(("server", ".env")))
        self.assertTrue(is_reset_preserved_path(("a", "b", ".env")))

    def test_logs_preserved(self):
        self.assertTrue(is_reset_preserved_path(("logs",)))
        self.assertTrue(is_reset_preserved_path(("logs", "server.log")))

    def test_data_not_preserved(self):
        # 重置会主动删除 data/ 与 *.db，不应保留
        self.assertFalse(is_reset_preserved_path(("server", "data", "db.sqlite")))
        self.assertFalse(is_reset_preserved_path(("family_monitor", "data", "users.json")))
        self.assertFalse(is_reset_preserved_path(("data",)))

    def test_case_insensitive(self):
        self.assertTrue(is_reset_preserved_path((".ENV",)))
        self.assertTrue(is_reset_preserved_path(("LOGS", "x")))

    def test_path_input_forms(self):
        self.assertTrue(is_reset_preserved_path(Path("server/.env")))
        self.assertTrue(is_reset_preserved_path("server/.env"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
