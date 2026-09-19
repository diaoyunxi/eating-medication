# -*- coding: utf-8 -*-
"""板载功放静音控制器（AudioAmpMute）测试：无硬件依赖。

覆盖：
1. 无 pinpong 环境降级为无操作；
2. 注入 pinpong.board 替身后走真实初始化路径（含持锁同步）；
3. 引用计数驱动的静音/解除静音电平；
4. 并发场景：多个线程同时 unmute/mute 或并发初始化时引用计数不遗漏。

CodeRabbit 建议：用 pinpong.board 替身（而非直接设置 _pin）注入，
并新增并发测试验证持锁初始化期间引用的实例不会遗漏引用计数更新。
"""
import sys
import threading
import unittest
import unittest.mock as mock
from pathlib import Path

EA = Path(__file__).resolve().parent.parent / "elderly_assistant"
if str(EA) not in sys.path:
    sys.path.insert(0, str(EA))

board_mod = __import__("hardware.board", fromlist=["AudioAmpMute"])


def _install_fake_pinpong_board():
    """将 pinpong.board 注入为替身模块，使 AudioAmpMute 走真实 import 路径。

    Pin 返回共享实例（_FakePin），便于在测试中断言功放电平。调用方需在
    tearDown 清理 sys.modules['pinpong.board']。
    """
    fake_module = mock.MagicMock()
    fake_module.P20 = 20

    class _FakePin:
        P20 = 20
        OUT = 1
        _shared = None

        def __new__(cls, *a, **k):
            if cls._shared is None:
                cls._shared = object.__new__(cls)
            return cls._shared

        def __init__(self, *a, **k):
            if not hasattr(self, "values"):
                self.values = []

        def write_digital(self, value):
            self.values.append(value)

    fake_module.Pin = _FakePin
    sys.modules["pinpong.board"] = fake_module
    return fake_module


class TestAudioAmpMuteNoHardware(unittest.TestCase):
    """无 pinpong 环境：降级为无操作，不抛异常。"""

    def setUp(self):
        sys.modules.pop("pinpong.board", None)

    def test_no_hardware_degrades_gracefully(self):
        amp = board_mod.AudioAmpMute()
        self.assertFalse(amp._available)
        self.assertIsNone(amp._pin)
        # 不应抛异常
        amp.unmute()
        amp.mute()
        self.assertEqual(amp._refcount, 0)


class TestAudioAmpMuteWithFakePin(unittest.TestCase):
    """注入 pinpong.board 替身：走真实 _ensure_init 路径（持锁同步）。"""

    def setUp(self):
        self._fake_mod = _install_fake_pinpong_board()
        self.amp = board_mod.AudioAmpMute()
        self.amp._ensure_init()  # 触发真实初始化路径（持锁），上电即静音
        self.fake_pin = self.amp._pin  # 共享的替身实例

    def tearDown(self):
        sys.modules.pop("pinpong.board", None)

    def test_init_default_muted(self):
        # 上电即静音（write_digital(0)）
        self.assertEqual(self.fake_pin.values, [0])
        self.assertTrue(self.amp._available)
        self.assertTrue(self.amp._initialized)

    def test_unmute_mute_toggles_level_once(self):
        self.amp.unmute()
        self.assertEqual(self.amp._refcount, 1)
        self.assertEqual(self.fake_pin.values[-1], 1)
        self.amp.mute()
        self.assertEqual(self.amp._refcount, 0)
        self.assertEqual(self.fake_pin.values[-1], 0)

    def test_refcount_held_until_last_mute(self):
        self.amp.unmute()
        self.amp.unmute()
        self.assertEqual(self.amp._refcount, 2)
        self.assertEqual(self.fake_pin.values[-1], 1)
        self.amp.mute()
        self.assertEqual(self.amp._refcount, 1)
        self.assertEqual(self.fake_pin.values[-1], 1)
        self.amp.mute()
        self.assertEqual(self.amp._refcount, 0)
        self.assertEqual(self.fake_pin.values[-1], 0)


class TestAudioAmpMuteConcurrent(unittest.TestCase):
    """并发场景：持锁初始化与引用计数更新不遗漏。"""

    def setUp(self):
        self._fake_mod = _install_fake_pinpong_board()
        self.amp = board_mod.AudioAmpMute()
        self.amp._ensure_init()  # 触发真实初始化路径（持锁），上电即静音
        self.fake_pin = self.amp._pin  # 共享的替身实例

    def tearDown(self):
        sys.modules.pop("pinpong.board", None)

    def test_concurrent_unmute_refcount(self):
        n = 12

        def worker():
            self.amp.unmute()

        threads = [threading.Thread(target=worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 每个线程的 unmute 都应被计数，最后电平为 1（解除静音）
        self.assertEqual(self.amp._refcount, n)
        self.assertEqual(self.fake_pin.values[-1], 1)

        def worker2():
            self.amp.mute()

        threads2 = [threading.Thread(target=worker2) for _ in range(n)]
        for t in threads2:
            t.start()
        for t in threads2:
            t.join()
        self.assertEqual(self.amp._refcount, 0)
        self.assertEqual(self.fake_pin.values[-1], 0)

    def test_concurrent_init_only_once(self):
        # 多个线程并发触发 _ensure_init（重置已初始化标记模拟首次竞争），
        # 默认静音（write_digital(0)）只应发生一次
        n = 12
        self.amp._initialized = False
        self.fake_pin.values = []
        threads = [threading.Thread(target=self.amp._ensure_init) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self.fake_pin.values.count(0), 1)
        self.assertTrue(self.amp._initialized)


if __name__ == "__main__":
    unittest.main()
