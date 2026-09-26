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
from unittest.mock import MagicMock, patch

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
        # 使用临时空目录隔离测试，避免扫描真实 /media /mnt /run/media
        empty_root = tempfile.mkdtemp(prefix="empty_root_")
        with patch.object(camera, "_DEFAULT_SD_SEARCH_ROOTS", [empty_root]):
            out = camera._fetch_huskylens_photo("x.jpg", self.save_dir, {}, self.logger)
        self.assertIsNone(out)

    def test_auto_discovers_huskylens_udisk(self):
        """自动发现二哈 V2 U 盘目录（Huskylens/storage/photo）并取回照片。"""
        # 模拟二哈 U 盘结构：<根>/<卷>/Huskylens/storage/photo/<文件>
        volume = Path(self.sd_dir) / "HUSKYLENS"
        photo_dir = volume / "Huskylens" / "storage" / "photo"
        photo_dir.mkdir(parents=True)
        name = "PHOTO_0001.jpg"
        (photo_dir / name).write_bytes(b"\xff\xd8\xff\xe0PHOTO")
        # 仅配置父根，依赖自动探测找到 Huskylens/storage/photo
        cfg = {"sd_search_paths": [self.sd_dir]}
        out = camera._fetch_huskylens_photo(name, self.save_dir, cfg, self.logger)
        self.assertTrue(out)
        self.assertEqual(os.path.dirname(out), self.save_dir)

    def test_filename_is_unique_with_microseconds_and_uuid(self):
        """验证生成的本地文件名包含微秒和 UUID，确保唯一性。"""
        name = self._write_remote("HUSKYLENS_0003.jpg")
        cfg = {"sd_search_paths": [self.sd_dir]}
        out1 = camera._fetch_huskylens_photo(name, self.save_dir, cfg, self.logger)
        out2 = camera._fetch_huskylens_photo(name, self.save_dir, cfg, self.logger)
        self.assertTrue(out1)
        self.assertTrue(out2)
        self.assertNotEqual(out1, out2)
        # 验证文件名格式包含微秒和 UUID
        basename1 = os.path.basename(out1)
        basename2 = os.path.basename(out2)
        self.assertIn("_", basename1)
        self.assertTrue(basename1.endswith(".jpg"))
        self.assertTrue(basename2.endswith(".jpg"))


class TestCaptureImage(unittest.TestCase):
    """capture_image 集成测试（使用 mock 模拟硬件）。"""

    def setUp(self):
        self.save_dir = tempfile.mkdtemp(prefix="cap_save_")
        self.sd_dir = tempfile.mkdtemp(prefix="sd_")
        self.logger = camera.setup_logger()
        # 预置模拟 SD 卡文件
        self.photo_name = "HUSKYLENS_0004.jpg"
        Path(self.sd_dir, self.photo_name).write_bytes(b"\xff\xd8\xff\xe0PHOTO")

    def _make_config(self, **overrides):
        """构建测试配置，合并默认值。"""
        cfg = {
            "camera": {
                "save_path": self.save_dir,
                "sd_search_paths": [self.sd_dir],
                "photo_resolution": "default",
            }
        }
        cfg["camera"].update(overrides)
        return cfg

    @patch.object(camera, "get_huskylens")
    def test_capture_image_uses_default_resolution(self, mock_get_hl):
        """默认 photo_resolution 为 default 时传给 takePhoto。"""
        mock_hl = MagicMock()
        mock_hl.takePhoto.return_value = self.photo_name
        mock_get_hl.return_value = mock_hl

        result = camera.capture_image(self._make_config())
        self.assertTrue(result)
        mock_hl.takePhoto.assert_called_once_with("default")

    @patch.object(camera, "get_huskylens")
    def test_capture_image_uses_custom_resolution(self, mock_get_hl):
        """自定义 photo_resolution 时正确传给 takePhoto。"""
        mock_hl = MagicMock()
        mock_hl.takePhoto.return_value = self.photo_name
        mock_get_hl.return_value = mock_hl

        result = camera.capture_image(self._make_config(photo_resolution="1920x1080"))
        self.assertTrue(result)
        mock_hl.takePhoto.assert_called_once_with("1920x1080")

    @patch.object(camera, "get_huskylens")
    def test_capture_image_returns_none_when_takephoto_empty(self, mock_get_hl):
        """takePhoto 返回空串时返回 None。"""
        mock_hl = MagicMock()
        mock_hl.takePhoto.return_value = ""
        mock_get_hl.return_value = mock_hl

        result = camera.capture_image(self._make_config())
        self.assertIsNone(result)

    @patch.object(camera, "get_huskylens")
    def test_capture_image_returns_none_when_fetch_fails(self, mock_get_hl):
        """取回照片失败时返回 None。"""
        mock_hl = MagicMock()
        mock_hl.takePhoto.return_value = "missing.jpg"
        mock_get_hl.return_value = mock_hl

        result = camera.capture_image(self._make_config())
        self.assertIsNone(result)

    @patch.object(camera, "get_huskylens")
    def test_capture_image_returns_none_on_import_error(self, mock_get_hl):
        """未安装 dfrobot_huskylensv2 库时返回 None。"""
        with patch.dict("sys.modules", {"dfrobot_huskylensv2": None}):
            # 强制触发 ImportError
            with patch.object(camera, "_init_huskylens", side_effect=ImportError("未安装")):
                result = camera.capture_image(self._make_config())
                self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
