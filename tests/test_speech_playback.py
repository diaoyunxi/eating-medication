# -*- coding: utf-8 -*-
"""语音播报测试（无硬件/网络依赖）。

覆盖三块能力：
1. 离线优先：pyttsx3 可用时走离线分支；不可用降级 edge-tts。
2. edge-tts 本地缓存：相同文本命中 index.json 索引，直接播放本地文件，不重复合成。
3. 播放器自动安装：检测不到播放器时，Linux 自动 apt 安装 mpg123。
"""
import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._helpers import load_module

EA = Path(__file__).resolve().parent.parent / "elderly_assistant"
if str(EA) not in sys.path:
    sys.path.insert(0, str(EA))

speech_mod = load_module("elderly_test_speech", "elderly_assistant/services/speech.py")


class _FakeEngine:
    """记录播放文本，支持注入失败以模拟引擎异常。"""

    def __init__(self, fail=False):
        self.spoken = []
        self._fail = fail

    def say(self, text):
        if self._fail:
            raise RuntimeError("engine boom")
        self.spoken.append(text)

    def runAndWait(self):
        if self._fail:
            raise RuntimeError("engine boom")
        return None


def _make_base(tmp):
    """构造一个基础 Speech 实例（绕过 __init__ 的网络/引擎副作用）。"""
    sp = speech_mod.Speech.__new__(speech_mod.Speech)
    sp._online = False
    sp._tts = None
    sp._voice = "zh-CN-XiaoxiaoNeural"
    sp._rate = "+0%"
    sp._player_precedence = ["mpg123", "ffplay", "mpv", "play"]
    sp._cache_dir = Path(tmp)
    sp._index_path = Path(tmp) / "index.json"
    sp._player = None
    sp.logger = __import__("logging").getLogger("t")
    return sp


class TestOfflineSpeech(unittest.TestCase):
    def test_offline_speak_records_text(self):
        sp = _make_base(tempfile.mkdtemp())
        engine = _FakeEngine()
        sp._tts = engine
        sp.speak("请服药")
        self.assertEqual(engine.spoken, ["请服药"])

    def test_pyttsx_failure_falls_back(self):
        sp = _make_base(tempfile.mkdtemp())
        sp._tts = _FakeEngine(fail=True)
        with mock.patch.object(sp, "_speak_edge") as m:
            sp.speak("识别结果")
            m.assert_called_once_with("识别结果")

    def test_empty_text_skipped(self):
        sp = _make_base(tempfile.mkdtemp())
        engine = _FakeEngine()
        sp._tts = engine
        sp.speak("   ")
        self.assertEqual(engine.spoken, [])


class TestTtsCache(unittest.TestCase):
    """edge-tts 命中索引直接播放本地文件，不再重复联网合成。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sp = _make_base(self.tmp)
        self.sp._player = "mpg123"  # 已探测到播放器

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cache_hit_uses_local_file(self):
        # 预先写入缓存文件 + 索引
        key = speech_mod.Speech._cache_key("你好", self.sp._voice, self.sp._rate)
        cached_file = Path(self.tmp) / f"{key}.mp3"
        cached_file.write_bytes(b"FAKE_MP3")
        self.sp._index_register(key, str(cached_file))

        played = []
        with mock.patch.object(self.sp, "_speak_edge", wraps=self.sp._speak_edge), \
             mock.patch("subprocess.run", side_effect=lambda *a, **k: played.append(a)):
            self.sp._speak_edge("你好")
        # 命中索引：直接播放本地文件，未调用 edge_tts.Communicate 合成
        self.assertTrue(played)
        self.assertEqual(played[0][0], ["mpg123", str(cached_file)])

    def test_cache_miss_synthesizes_and_registers(self):
        # 模拟 edge_tts.Communicate 合成（注入模块级全局，避免依赖真实库）
        fake_comm = mock.MagicMock()
        # 让 save 真正落盘，验证缓存文件生成
        out_paths = []
        fake_comm.save.side_effect = lambda p: out_paths.append(Path(p)) or Path(p).write_bytes(b"MP3")
        fake_edge = mock.MagicMock()
        fake_edge.Communicate = mock.MagicMock(return_value=fake_comm)
        with mock.patch.object(speech_mod, "edge_tts", fake_edge), \
             mock.patch("asyncio.run") as m_run, \
             mock.patch.object(self.sp, "_play_file") as m_play:
            self.sp._speak_edge("请按时吃药")

        fake_comm.save.assert_called_once()
        m_run.assert_called_once()
        m_play.assert_called_once()
        # 索引已登记一条记录，且缓存文件真实存在
        index = self.sp._index_load()
        self.assertEqual(len(index), 1)
        self.assertTrue((Path(self.tmp) / list(index.values())[0]["file"]).exists())

    def test_cache_key_stable(self):
        k1 = speech_mod.Speech._cache_key("abc", "v", "+0%")
        k2 = speech_mod.Speech._cache_key("abc", "v", "+0%")
        k3 = speech_mod.Speech._cache_key("abc", "v", "+50%")
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)

    def test_index_recovers_when_file_missing(self):
        key = speech_mod.Speech._cache_key("丢了", self.sp._voice, self.sp._rate)
        # 索引存在但文件不存在
        self.sp._index_register(key, str(Path(self.tmp) / f"{key}.mp3"))
        self.assertIsNone(self.sp._index_lookup(key))
        # 无效条目被清理
        self.assertEqual(self.sp._index_load(), {})


class TestPlayerAutoInstall(unittest.TestCase):
    def test_install_on_linux_when_missing(self):
        sp = _make_base(tempfile.mkdtemp())
        sp._player_precedence = ["mpg123"]
        # shutil.which 首次返回 None（没装）→ 触发安装；安装后返回路径
        which_side = mock.Mock(side_effect=[None, "/usr/bin/mpg123"])
        with mock.patch("shutil.which", which_side), \
             mock.patch("subprocess.run") as m_run, \
             mock.patch("os.name", "posix"):
            result = sp._install_player()
        # 应尝试 apt 安装 mpg123
        install_calls = [c for c in m_run.call_args_list
                         if c.args and "mpg123" in str(c.args[0])]
        self.assertTrue(install_calls)
        # 安装后探测到播放器
        self.assertEqual(result, "/usr/bin/mpg123")

    def test_no_install_on_windows(self):
        sp = _make_base(tempfile.mkdtemp())
        with mock.patch("shutil.which", return_value=None), \
             mock.patch("subprocess.run") as m_run, \
             mock.patch("os.name", "nt"):
            result = sp._install_player()
        m_run.assert_not_called()
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
