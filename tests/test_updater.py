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


class TestGetUpdateInfo(unittest.TestCase):
    """测试 get_update_info() 返回结构化更新信息（供 API 端点 / 前端轮询）。"""

    def _call(self, latest_side_effect):
        orig = updater._fetch_latest_version
        updater._fetch_latest_version = lambda: latest_side_effect
        try:
            return updater.get_update_info()
        finally:
            updater._fetch_latest_version = orig

    def test_fields_present(self):
        info = self._call(("9.9.9", "https://github.com/repo/releases/tag/v9.9.9", {}))
        self.assertIn("current_version", info)
        self.assertIn("latest_version", info)
        self.assertIn("update_available", info)
        self.assertIn("auto_pull", info)
        self.assertIn("release_url", info)
        self.assertIn("checked_at", info)

    def test_update_available_true(self):
        info = self._call(("9.9.9", "url", {}))
        self.assertEqual(info["latest_version"], "9.9.9")
        self.assertTrue(info["update_available"])
        self.assertEqual(info["release_url"], "url")

    def test_update_available_false(self):
        info = self._call(("0.0.1", "url", {}))
        self.assertFalse(info["update_available"])

    def test_fetch_failure_no_crash(self):
        def boom():
            raise RuntimeError("network down")
        info = self._call(boom)
        # 网络异常时不应抛错，latest_version 为 None，update_available 为 False
        self.assertIsNone(info["latest_version"])
        self.assertFalse(info["update_available"])


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

    def test_env_files_protected(self):
        self.assertTrue(updater._is_protected_path("family_monitor/.env"))
        self.assertTrue(updater._is_protected_path("elderly_assistant/.env"))

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


class TestLoadAutoPull(unittest.TestCase):
    """测试 _load_auto_pull：由根目录 .env 的 AUTO_PULL 字段控制，缺省 True。"""

    def _call_with_config(self, payload):
        """临时改写根目录 .env（重定向 _CONFIG_PATH 到临时文件）并调用 _load_auto_pull。"""
        import tempfile
        # 使用 mkstemp 创建不可预测的临时文件（避免 mktemp 的文件名预测/竞态问题）
        _fd, tmp_str = tempfile.mkstemp(suffix=".env")
        os.close(_fd)
        tmp = Path(tmp_str)
        orig = updater._CONFIG_PATH
        updater._CONFIG_PATH = tmp
        try:
            if payload is not None:
                tmp.write_text(payload, encoding="utf-8")
            return updater._load_auto_pull()
        finally:
            updater._CONFIG_PATH = orig
            if tmp.exists():
                tmp.unlink()

    def test_default_true_when_missing(self):
        self.assertTrue(self._call_with_config(None))

    def test_true(self):
        self.assertTrue(self._call_with_config("AUTO_PULL=true"))

    def test_false(self):
        self.assertFalse(self._call_with_config("AUTO_PULL=false"))

    def test_true_case_insensitive(self):
        self.assertTrue(self._call_with_config("AUTO_PULL=True"))

    def test_false_explicit(self):
        self.assertFalse(self._call_with_config('AUTO_PULL="false"'))

    def test_unknown_value_false(self):
        # .env 值为非 true/false 字符串时按 False 处理（无布尔类型概念）
        self.assertFalse(self._call_with_config("AUTO_PULL=123"))

    def test_bad_env_fallback_true(self):
        # 非 key=value 内容被忽略，回退缺省 True
        self.assertTrue(self._call_with_config("this is not a valid env content"))


class TestCheckForUpdateDefault(unittest.TestCase):
    def test_default_pull_false_uses_config(self):
        orig_fetch = updater._fetch_latest_version
        orig_ver = updater.__version__
        orig_auto = updater._AUTO_PULL
        updater._fetch_latest_version = lambda: ("9.9.9", "url", {"tag": "v9.9.9"})
        updater.__version__ = "1.0.0"
        updater._AUTO_PULL = False
        try:
            updater.check_for_update()  # 不应抛异常，auto_pull=False 时仅提示
        finally:
            updater._fetch_latest_version = orig_fetch
            updater.__version__ = orig_ver
            updater._AUTO_PULL = orig_auto


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


class TestConfigureOpener(unittest.TestCase):
    """测试 _configure_opener 对代理类型的判定（gh-proxy 风格镜像 vs 正向代理）。"""

    def _call_with_proxy(self, proxy):
        orig = updater._GITHUB_PROXY
        updater._GITHUB_PROXY = proxy
        try:
            return updater._configure_opener()
        finally:
            updater._GITHUB_PROXY = orig

    def test_mirror_domain_no_port(self):
        # 普通域名（无端口）应判定为镜像前缀，而非正向代理
        _, is_mirror, base = self._call_with_proxy("https://gh.my-website.ccwu.cc")
        self.assertTrue(is_mirror)
        self.assertEqual(base, "https://gh.my-website.ccwu.cc")

    def test_mirror_gh_proxy_example(self):
        _, is_mirror, base = self._call_with_proxy("https://gh-proxy.com")
        self.assertTrue(is_mirror)
        self.assertEqual(base, "https://gh-proxy.com")

    def test_forward_localhost_port(self):
        _, is_mirror, base = self._call_with_proxy("http://127.0.0.1:7890")
        self.assertFalse(is_mirror)
        self.assertIsNone(base)

    def test_forward_socks_with_port(self):
        _, is_mirror, base = self._call_with_proxy("socks5://proxy.example:1080")
        self.assertFalse(is_mirror)
        self.assertIsNone(base)

    def test_empty_proxy_direct(self):
        _, is_mirror, base = self._call_with_proxy("")
        self.assertFalse(is_mirror)
        self.assertIsNone(base)

    def test_illegal_proxy_fallback_direct(self):
        _, is_mirror, base = self._call_with_proxy("not-a-url")
        self.assertFalse(is_mirror)
        self.assertIsNone(base)


class TestLoadPostUpdateCmd(unittest.TestCase):
    """测试 _load_post_update_cmd：由根目录 .env 的 POST_UPDATE_CMD 字段读取一条命令。"""

    def _call_with_config(self, payload):
        """临时改写根目录 .env（重定向 _CONFIG_PATH 到临时文件）并调用 _load_post_update_cmd。"""
        import tempfile
        _fd, tmp_str = tempfile.mkstemp(suffix=".env")
        os.close(_fd)
        tmp = Path(tmp_str)
        orig = updater._CONFIG_PATH
        updater._CONFIG_PATH = tmp
        try:
            if payload is not None:
                tmp.write_text(payload, encoding="utf-8")
            return updater._load_post_update_cmd()
        finally:
            updater._CONFIG_PATH = orig
            if tmp.exists():
                tmp.unlink()

    def test_none_when_missing(self):
        self.assertIsNone(self._call_with_config(None))

    def test_none_when_blank(self):
        self.assertIsNone(self._call_with_config("POST_UPDATE_CMD="))

    def test_strip_whitespace(self):
        self.assertEqual(
            self._call_with_config("POST_UPDATE_CMD=  python -m alembic upgrade head  "),
            "python -m alembic upgrade head",
        )


class TestRunPostUpdateCmd(unittest.TestCase):
    """测试 _run_post_update_cmd：更新成功后以 shell 执行 POST_UPDATE_CMD。"""

    def _call_with(self, cmd, mock_run):
        orig_cmd = updater._POST_UPDATE_CMD
        orig_run = updater.subprocess.run
        updater._POST_UPDATE_CMD = cmd
        updater.subprocess.run = mock_run
        try:
            updater._run_post_update_cmd()
        finally:
            updater._POST_UPDATE_CMD = orig_cmd
            updater.subprocess.run = orig_run

    def test_noop_when_none(self):
        called = {"n": 0}

        def fake_run(*a, **k):
            called["n"] += 1
            return None
        self._call_with(None, fake_run)
        self.assertEqual(called["n"], 0)

    def test_runs_command_with_cwd_and_shell(self):
        captured = {}

        class _Result:
            returncode = 0
            stderr = ""
        def fake_run(*a, **k):
            captured.update({"cmd": a[0], "shell": k.get("shell"), "cwd": k.get("cwd"),
                              "timeout": k.get("timeout")})
            return _Result()
        self._call_with("python -m alembic upgrade head", fake_run)
        self.assertEqual(captured["cmd"], "python -m alembic upgrade head")
        self.assertTrue(captured["shell"])
        self.assertIsNotNone(captured["cwd"])
        self.assertEqual(captured["timeout"], 300)

    def test_nonzero_returncode_is_warning_only(self):
        # 非零返回码不应抛异常，仅告警；此处验证能正常返回
        class _Result:
            returncode = 3
            stderr = "boom\n"
        def fake_run(*a, **k):
            return _Result()
        # 不抛异常即通过
        self._call_with("false", fake_run)


if __name__ == "__main__":
    unittest.main()
