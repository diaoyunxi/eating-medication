# -*- coding: utf-8 -*-
"""common.envfile 共享 .env 读写工具单元测试。

覆盖三端统一后复用的方法：write_env_text（写+600 权限）、ensure_env_template
（不存在才生成 + 幂等）、read_env_dict（扁平解析）、update_env_fields（就地更新）。
"""
import os
import stat
import tempfile
import unittest
from pathlib import Path

from common.envfile import (
    write_env_text,
    ensure_env_template,
    read_env_dict,
    update_env_fields,
)


class TestEnvFileHelpers(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="envfile_test_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_env_text_writes_and_sets_perms(self):
        p = self.tmp / ".env"
        write_env_text(p, "A=1\n")
        self.assertTrue(p.is_file())
        self.assertEqual(p.read_text(encoding="utf-8"), "A=1\n")
        # 至少保证所有者可写（600 权限意图）
        self.assertTrue(p.stat().st_mode & stat.S_IWUSR)

    def test_ensure_env_template_idempotent(self):
        p = self.tmp / ".env"
        self.assertTrue(ensure_env_template(p, "X=1\n"))
        # 已存在则不覆盖，返回 False
        self.assertFalse(ensure_env_template(p, "Y=2\n"))
        self.assertEqual(p.read_text(encoding="utf-8"), "X=1\n")

    def test_read_env_dict(self):
        p = self.tmp / ".env"
        p.write_text("# comment\nA=1\n\nB=2\n=bad\nC = 3\n", encoding="utf-8")
        data = read_env_dict(p)
        # 跳过注释/空行/无 '=' 行；strip 键值
        self.assertEqual(data, {"A": "1", "B": "2", "C": "3"})

    def test_read_env_dict_missing_file(self):
        self.assertEqual(read_env_dict(self.tmp / "nope.env"), {})

    def test_update_env_fields_keeps_comments(self):
        p = self.tmp / ".env"
        p.write_text("A=1\n# note\nB=2\n", encoding="utf-8")
        update_env_fields(p, {"A": "9", "C": "3"})
        text = p.read_text(encoding="utf-8")
        self.assertIn("# note", text)  # 注释保留
        data = read_env_dict(p)
        self.assertEqual(data["A"], "9")   # 已存在字段更新
        self.assertEqual(data["B"], "2")   # 其它字段保留
        self.assertEqual(data["C"], "3")   # 新字段追加


if __name__ == "__main__":
    unittest.main(verbosity=2)
