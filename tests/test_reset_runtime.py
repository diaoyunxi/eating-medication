# -*- coding: utf-8 -*-
"""reset_runtime 单元测试。

验证 ``--reset`` 的运行时数据清理逻辑：
- 仅删除未跟踪 / 被忽略的运行时文件（DB、users.json、device_id.txt 等）
- 保留 .env / config.json / logs（含子目录中的同名文件）
- 不误删已跟踪的源码文件
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# 仓库根目录需在 sys.path 中才能导入 reset_runtime
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reset_runtime import reset_runtime_data, _is_preserved  # noqa: E402


class TestIsPreserved(unittest.TestCase):
    """路径保留判定单元测试。"""

    def test_preserve_dotenv(self):
        self.assertTrue(_is_preserved((".env",)))
        self.assertTrue(_is_preserved(("server", ".env")))

    def test_preserve_config_json(self):
        self.assertTrue(_is_preserved(("config.json",)))
        self.assertTrue(_is_preserved(("family_monitor", "config.json")))

    def test_preserve_logs_dir(self):
        self.assertTrue(_is_preserved(("logs",)))
        self.assertTrue(_is_preserved(("logs", "server.log")))

    def test_not_preserved(self):
        self.assertFalse(_is_preserved(("server", "data", "db.sqlite")))
        self.assertFalse(_is_preserved(("family_monitor", "data", "users.json")))


class TestResetRuntimeData(unittest.TestCase):
    """基于临时 git 仓库的重置行为集成测试。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="reset_test_"))
        gitignore = (
            "*.sqlite\n*.db\ndata/\nusers.json\ndevice_id.txt\n"
            "dfrobot_huskylensv2.py\n__pycache__/\n*.pyc\n.env\nconfig.json\n*.log\n"
        )
        (self.tmp / ".gitignore").write_text(gitignore, encoding="utf-8")
        # 已跟踪文件（不应被删除）
        (self.tmp / "README.md").write_text("tracked\n", encoding="utf-8")
        # 需保留的运行时文件
        (self.tmp / ".env").write_text("SECRET=1\n", encoding="utf-8")
        (self.tmp / "config.json").write_text("{}\n", encoding="utf-8")
        (self.tmp / "logs").mkdir()
        (self.tmp / "logs" / "server.log").write_text("log\n", encoding="utf-8")
        (self.tmp / "server").mkdir()
        (self.tmp / "server" / ".env").write_text("S=2\n", encoding="utf-8")
        (self.tmp / "family_monitor").mkdir()
        (self.tmp / "family_monitor" / "config.json").write_text("{}\n", encoding="utf-8")
        # 需删除的运行时文件
        (self.tmp / "server" / "data").mkdir()
        (self.tmp / "server" / "data" / "db.sqlite").write_text("db", encoding="utf-8")
        (self.tmp / "family_monitor" / "data").mkdir()
        (self.tmp / "family_monitor" / "data" / "users.json").write_text("{}", encoding="utf-8")
        (self.tmp / "elderly_assistant").mkdir()
        (self.tmp / "elderly_assistant" / "device_id.txt").write_text("x", encoding="utf-8")
        (self.tmp / "elderly_assistant" / "dfrobot_huskylensv2.py").write_text("#", encoding="utf-8")
        cache = self.tmp / "server" / "__pycache__"
        cache.mkdir()
        (self.tmp / "server" / "x.pyc").write_text("", encoding="utf-8")

        subprocess.run(["git", "init"], cwd=str(self.tmp), capture_output=True)
        subprocess.run(["git", "add", "README.md"], cwd=str(self.tmp), capture_output=True)
        subprocess.run(["git", "commit", "-m", "t"], cwd=str(self.tmp), capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reset_preserves_and_deletes(self):
        deleted, skipped = reset_runtime_data(str(self.tmp))

        # 保留项
        self.assertTrue((self.tmp / ".env").exists(), ".env 应保留")
        self.assertTrue((self.tmp / "config.json").exists(), "config.json 应保留")
        self.assertTrue((self.tmp / "logs" / "server.log").exists(), "logs 应保留")
        self.assertTrue((self.tmp / "server" / ".env").exists(), "server/.env 应保留")
        self.assertTrue(
            (self.tmp / "family_monitor" / "config.json").exists(),
            "family_monitor/config.json 应保留",
        )
        # 已跟踪源码不被误删
        self.assertTrue((self.tmp / "README.md").exists(), "已跟踪文件不应被删")

        # 删除项
        self.assertFalse((self.tmp / "server" / "data").exists(), "server/data 应删除")
        self.assertFalse(
            (self.tmp / "family_monitor" / "data" / "users.json").exists(),
            "users.json 应删除",
        )
        self.assertFalse(
            (self.tmp / "elderly_assistant" / "device_id.txt").exists(),
            "device_id.txt 应删除",
        )
        self.assertFalse(
            (self.tmp / "elderly_assistant" / "dfrobot_huskylensv2.py").exists(),
            "dfrobot_huskylensv2.py 应删除",
        )
        self.assertFalse(
            (self.tmp / "server" / "__pycache__").exists(), "__pycache__ 应删除"
        )
        self.assertFalse((self.tmp / "server" / "x.pyc").exists(), "*.pyc 应删除")


if __name__ == "__main__":
    unittest.main(verbosity=2)
