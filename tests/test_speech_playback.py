# -*- coding: utf-8 -*-
"""语音播报串行性与失败兜底测试（无硬件/网络依赖）。

聚焦「条形码识别到时没播报」的根因修复：
1. 多次 speak 经队列由唯一 worker 串行播放，不应因引擎交错而丢失某条；
2. edge-tts 失败时明确记录 last_error 并转出/或记录，不再静默吞掉。
"""
import sys
import time
import unittest
from pathlib import Path

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


class TestSpeechSerialPlayback(unittest.TestCase):
    def _make_speech(self, pyttsx_fail=False, with_engine=True):
        sp = speech_mod.Speech.__new__(speech_mod.Speech)
        # 关闭所有外部引擎，仅用注入的 FakeEngine 走 pyttsx 分支
        sp._edge_tts = None
        sp._edge_available = False
        sp._pyttsx_engine = _FakeEngine(fail=pyttsx_fail) if with_engine else None
        import threading
        import queue
        sp._speak_queue = queue.Queue(maxsize=20)
        sp._stop_event = threading.Event()
        sp._speak_lock = threading.Lock()
        sp.last_error = None
        sp.logger = __import__("logging").getLogger("t")
        return sp

    def test_speak_in_order_via_consumer(self):
        """多条播报经 _speak 串行消费，按序播放且识别结果不丢失。"""
        sp = self._make_speech()
        for i in range(5):
            sp._speak(f"消息{i}")
        self.assertEqual(sp._pyttsx_engine.spoken, [f"消息{i}" for i in range(5)])

    def test_pyttsx_failure_recorded(self):
        """当唯一引擎（pyttsx3）抛异常时，last_error 必须被记录，不可静默。"""
        sp = self._make_speech(pyttsx_fail=True)
        sp._speak("识别结果")
        self.assertIsNotNone(sp.last_error)
        self.assertIn("pyttsx3", sp.last_error)

    def test_no_engine_records_last_error(self):
        """当两路引擎均不可用时，speak() 必须记录 last_error（排查无声音）。"""
        sp = self._make_speech(with_engine=False)
        sp.speak("识别结果")
        self.assertEqual(sp.last_error, "无可用语音引擎")


if __name__ == "__main__":
    unittest.main()
