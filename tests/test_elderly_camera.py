# -*- coding: utf-8 -*-
"""camera.py 拍照取回逻辑单元测试。

验证修复点：二哈（HuskyLens V2）拍照后仅返回 SD 卡文件名，需从 M10 可访问的
挂载点把文件复制到本地 save_path；覆盖「配置路径 / 字符串逗号分隔 / 找不到 /
默认路径不存在」等场景。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests._helpers import load_module

# 以唯一名加载 elderly_assistant/core/camera.py，规避同名顶层包 core 冲突
camera = load_module("elderly_test_camera", "elderly_assistant/core/camera.py")


class TestFetchHuskylensPhoto(unittest.TestCase):
    """_fetch_huskylens_photo 取回逻辑测试（纯逻辑，无需硬件）。"""

    def setUp(self):
        self.save_dir = tempfile.mkdtemp(prefix="cap_save_")
        self.sd_dir = tempfile.mkdtemp(prefix="sd_")
        self.logger = camera.setup_logger()

    def _write_remote(self, name):
        """在模拟的二哈 SD 卡目录写入一张照片文件。"""
        p = Path(self.sd_dir) / name
        p.write_bytes(b"\xff\xd8\xff\xe0PHOTO")
        return name

    def test_fetches_photo_from_configured_path(self):
        """从配置列表指定的挂载目录成功取回照片到本地。"""
        name = self._write_remote("HUSKYLENS_0001.jpg")
        cfg = {"sd_search_paths": [self.sd_dir]}
        out = camera._fetch_huskylens_photo(name, self.save_dir, cfg, self.logger)
        self.assertTrue(out)
        self.assertTrue(os.path.exists(out))
        # 目标应位于本地 save_dir，而非原始 SD 卡目录
        self.assertEqual(os.path.dirname(out), self.save_dir)

    def test_fetches_photo_from_csv_string(self):
        """sd_search_paths 为逗号分隔字符串时也能解析并取回。"""
        name = self._write_remote("HUSKYLENS_0002.jpg")
        cfg = {"sd_search_paths": f"{self.sd_dir},/nonexistent_path"}
        out = camera._fetch_huskylens_photo(name, self.save_dir, cfg, self.logger)
        self.assertTrue(out)

    def test_returns_none_when_not_found(self):
        """照片在挂载目录中不存在时优雅返回 None。"""
        cfg = {"sd_search_paths": [tempfile.mkdtemp()]}
        out = camera._fetch_huskylens_photo("missing.jpg", self.save_dir, cfg, self.logger)
        self.assertIsNone(out)

    def test_returns_none_on_default_roots_missing(self):
        """默认挂载根目录（/media 等）在测试环境不存在时返回 None 而非抛异常。"""
        out = camera._fetch_huskylens_photo("x.jpg", self.save_dir, {}, self.logger)
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
