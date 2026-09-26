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


class _FakeInitEngine:
    """模拟 pyttsx3.init() 返回的引擎，支持注入属性读回与试播失败。"""

    def __init__(self, volume=0.9, rate=150, voice="default", say_fail=False,
                 voices=None, ignore_voice_set=False):
        self._volume = volume
        self._rate = rate
        self._voice = voice
        self._voices = voices
        self._say_fail = say_fail
        self._ignore_voice_set = ignore_voice_set
        self.stopped = False

    def setProperty(self, k, v):
        # 模拟后端"假成功"：setProperty 返回但音量/语速并不真正生效，
        # 校验阶段回读到的仍是构造时的值，用于验证未生效即丢弃引擎；
        # 仅当显式允许（非忽略）时才更新 voice（语音校验测试）。
        if k == "voice" and not self._ignore_voice_set:
            self._voice = v

    def getProperty(self, k):
        return {"volume": self._volume, "rate": self._rate, "voice": self._voice,
                "voices": self._voices}[k]

    def say(self, text):
        if self._say_fail:
            raise RuntimeError("backend late failure")

    def runAndWait(self):
        if self._say_fail:
            raise RuntimeError("backend late failure")

    def stop(self):
        self.stopped = True


class _FakeVoice:
    """模拟 pyttsx3 语音对象，需提供 id 属性供 _select_mbrola_voice 识别。"""

    def __init__(self, vid):
        self.id = vid

    def say(self, text):
        if self._say_fail:
            raise RuntimeError("backend late failure")

    def runAndWait(self):
        if self._say_fail:
            raise RuntimeError("backend late failure")

    def stop(self):
        self.stopped = True


class TestPyttsxEngineInitValidation(unittest.TestCase):
    """CodeRabbit 回归：发布引擎前必须校验 volume/rate/voice 并捕获延迟失败。"""

    def _init_engine_with(self, fake_engine):
        import importlib

        # 临时把 pyttsx3.init 指向构造假引擎，模拟后端
        mod = __import__("elderly_assistant.services.speech", fromlist=["speech"])
        real_init = None
        try:
            import pyttsx3  # 若已装则保存

            real_init = pyttsx3.init
            pyttsx3.init = lambda *a, **k: fake_engine
        except Exception:
            import sys
            import types

            fake_mod = types.ModuleType("pyttsx3")
            fake_mod.init = lambda *a, **k: fake_engine
            sys.modules["pyttsx3"] = fake_mod
        try:
            sp = mod.Speech.__new__(mod.Speech)
            sp.logger = __import__("logging").getLogger("t")
            sp._init_engines()
            return sp
        finally:
            # 恢复 pyttsx3
            try:
                import pyttsx3

                if real_init is not None:
                    pyttsx3.init = real_init
                else:
                    sys.modules.pop("pyttsx3", None)
            except Exception:
                pass

    def test_valid_engine_published(self):
        sp = self._init_engine_with(_FakeInitEngine())
        self.assertIsNotNone(sp._pyttsx_engine)

    def test_volume_not_effective_drops_engine(self):
        sp = self._init_engine_with(_FakeInitEngine(volume=0.1))
        self.assertIsNone(sp._pyttsx_engine)

    def test_rate_not_effective_drops_engine(self):
        sp = self._init_engine_with(_FakeInitEngine(rate=300))
        self.assertIsNone(sp._pyttsx_engine)

    def test_late_speak_failure_drops_engine(self):
        sp = self._init_engine_with(_FakeInitEngine(say_fail=True))
        self.assertIsNone(sp._pyttsx_engine)

    def test_voice_preferred_not_effective_restores_default(self):
        # 后端"假成功"：优选 mbrola 但 setProperty 未真正生效（voice 仍回读默认）。
        # 语音校验应失败并恢复（回写）保存的默认语音，引擎仍应发布而非丢弃。
        eng = _FakeInitEngine(voice="default", voices=[_FakeVoice("mbrola/cn1")],
                              ignore_voice_set=True)
        sp = self._init_engine_with(eng)
        self.assertIsNotNone(sp._pyttsx_engine)
        self.assertEqual(eng._voice, "default")


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
