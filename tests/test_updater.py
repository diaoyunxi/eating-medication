# -*- coding: utf-8 -*-
"""根目录 updater.py 纯函数单元测试（仅依赖标准库，可直接运行）。

CI 工作流 `.github/workflows/python-app.yml` 在仓库根执行 `pytest`，
本文件会被自动发现。
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# updater.py 仅依赖标准库，直接按文件加载为唯一模块名
_spec = importlib.util.spec_from_file_location("repo_updater", REPO_ROOT / "updater.py")
updater = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(updater)


class TestCompareVersions(unittest.TestCase):
    def test_greater(self):
        self.assertEqual(updater._compare_versions("2.13.1", "2.12.0"), 1)

    def test_less(self):
        self.assertEqual(updater._compare_versions("1.0.0", "1.0.1"), -1)

    def test_equal(self):
        self.assertEqual(updater._compare_versions("1.2.3", "1.2.3"), 0)

    def test_v_prefix(self):
        self.assertEqual(updater._compare_versions("v1.5.0", "1.4.9"), 1)

    def test_different_length(self):
        self.assertEqual(updater._compare_versions("1.2", "1.2.0"), 0)
        self.assertEqual(updater._compare_versions("1.10", "1.9"), 1)

    def test_invalid_returns_zero(self):
        self.assertEqual(updater._compare_versions("abc", "1.0.0"), 0)


class TestFindReleaseZip(unittest.TestCase):
    def test_find(self):
        release = {"assets": [
            {"name": "notes.txt", "browser_download_url": "u1"},
            {"name": "eating-medication-1.2.3.zip", "browser_download_url": "u2"},
        ]}
        asset = updater._find_release_zip(release)
        self.assertIsNotNone(asset)
        self.assertEqual(asset["name"], "eating-medication-1.2.3.zip")

    def test_none(self):
        self.assertIsNone(updater._find_release_zip({"assets": [{"name": "x.txt"}]}))
        self.assertIsNone(updater._find_release_zip(None))


class TestFindSha256Assets(unittest.TestCase):
    def test_find(self):
        release = {"assets": [
            {"name": "a.zip"},
            {"name": "eating-medication-1.2.3.zip.sha256"},
            {"name": "EATING-MEDICATION-1.2.3.WIN.SHA256"},
        ]}
        assets = updater._find_sha256_assets(release)
        self.assertEqual(len(assets), 2)

    def test_none(self):
        self.assertEqual(updater._find_sha256_assets(None), [])
        self.assertEqual(updater._find_sha256_assets({"assets": [{"name": "a.zip"}]}), [])


class TestIsProtectedPath(unittest.TestCase):
    def test_env_files(self):
        self.assertTrue(updater._is_protected_path("server/.env"))
        self.assertTrue(updater._is_protected_path(".env"))

    def test_config_json(self):
        self.assertTrue(updater._is_protected_path("family_monitor/config.json"))
        self.assertTrue(updater._is_protected_path("config.yaml"))

    def test_data_subdir(self):
        self.assertTrue(updater._is_protected_path("server/data/db.sqlite"))
        self.assertTrue(updater._is_protected_path("logs/x.log"))

    def test_db_pattern(self):
        self.assertTrue(updater._is_protected_path("x.db"))
        self.assertTrue(updater._is_protected_path("y.sqlite3"))

    def test_git(self):
        self.assertTrue(updater._is_protected_path(".git/config"))

    def test_normal_file(self):
        self.assertFalse(updater._is_protected_path("README.md"))
        self.assertFalse(updater._is_protected_path("server/app/main.py"))
        self.assertFalse(updater._is_protected_path("docs/guide.txt"))


class TestGhHeaders(unittest.TestCase):
    def test_no_token(self):
        old = os.environ.pop("GITHUB_TOKEN", None)
        try:
            self.assertEqual(
                updater._gh_headers(),
                {"User-Agent": "eating-medication-updater"},
            )
        finally:
            if old is not None:
                os.environ["GITHUB_TOKEN"] = old

    def test_with_token(self):
        old = os.environ.get("GITHUB_TOKEN")
        os.environ["GITHUB_TOKEN"] = "abc"
        try:
            headers = updater._gh_headers()
            self.assertEqual(headers.get("Authorization"), "token abc")
        finally:
            if old is None:
                os.environ.pop("GITHUB_TOKEN", None)
            else:
                os.environ["GITHUB_TOKEN"] = old


class TestLoadVersion(unittest.TestCase):
    def test_returns_nonempty_string(self):
        # 仓库根 VERSION 存在时返回真实版本；缺失时回退 "0.0.0"
        v = updater._load_version()
        self.assertIsInstance(v, str)
        self.assertTrue(len(v) > 0)


class TestVerifyReleaseSignature(unittest.TestCase):
    def test_none_when_no_sha(self):
        self.assertIsNone(updater._verify_release_signature({"assets": [{"name": "a.zip"}]}))
        self.assertIsNone(updater._verify_release_signature(None))

    def test_parse_sums(self):
        orig = updater._download_text
        updater._download_text = lambda url: "abc123  eating-medication-1.2.3.zip\n"
        try:
            release = {"assets": [{
                "name": "eating-medication-1.2.3.zip.sha256",
                "browser_download_url": "u",
            }]}
            sums = updater._verify_release_signature(release)
            self.assertIsNotNone(sums)
            self.assertEqual(sums.get("eating-medication-1.2.3.zip"), "abc123")
        finally:
            updater._download_text = orig


class TestCheckForUpdate(unittest.TestCase):
    def test_no_update_when_current_is_latest(self):
        orig_fetch = updater._fetch_latest_version
        orig_ver = updater.__version__
        updater._fetch_latest_version = lambda: ("1.0.0", "url", {"tag": "v1.0.0"})
        updater.__version__ = "1.0.0"
        try:
            # 不应抛异常，仅记录日志
            updater.check_for_update(auto_pull=False)
        finally:
            updater._fetch_latest_version = orig_fetch
            updater.__version__ = orig_ver


if __name__ == "__main__":
    unittest.main()
