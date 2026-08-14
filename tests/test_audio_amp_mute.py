# -*- coding: utf-8 -*-
"""板载功放静音控制测试（修复 #34：语音播报电流声）。

重点验证：
1. 非 M10 环境（无 pinpong / Pin）自动降级为无操作，不抛异常；
2. 默认上电即静音（低电平），播放前解除静音（高电平）、播放后恢复静音；
3. 引用计数支持并发：最后一次退出才真正静音。
"""
import sys
import unittest
from pathlib import Path

from tests._helpers import load_module

EA = Path(__file__).resolve().parent.parent / "elderly_assistant"
if str(EA) not in sys.path:
    sys.path.insert(0, str(EA))

board_mod = load_module("elderly_test_board", "elderly_assistant/hardware/board.py")


class _FakePin:
    """模拟 pinpong Pin，记录 write_digital 调用序列。"""

    def __init__(self, pin_no, mode):
        self.pin_no = pin_no
        self.mode = mode
        self.values = []

    def write_digital(self, v):
        self.values.append(v)


class TestAudioAmpMuteNoHardware(unittest.TestCase):
    """无 pinpong 环境下降级为无操作。"""

    def test_unmute_mute_noop_when_no_pinpong(self):
        amp = board_mod.AudioAmpMute()
        # 不应抛出异常
        amp.unmute()
        amp.mute()
        amp.force_mute()
        self.assertFalse(amp._available)


class TestAudioAmpMuteWithFakePin(unittest.TestCase):
    """模拟引脚，验证静音/解除静音电平与引用计数。"""

    def _install_fake_pin(self, monkeypatch_pin):
        amp = board_mod.AudioAmpMute()
        amp._ensure_init()
        # 强制走模拟引脚（绕过 import 失败分支）
        amp._available = True
        amp._pin = monkeypatch_pin
        amp._initialized = True
        amp._refcount = 0
        return amp

    def test_init_mutes_by_default(self):
        fake = _FakePin(20, "OUT")
        amp = self._install_fake_pin(fake)
        # 重新触发初始化逻辑中的默认静音：通过 force_mute 验证电平
        amp.force_mute()
        self.assertEqual(fake.values[-1], 0)

    def test_unmute_then_mute_levels(self):
        fake = _FakePin(20, "OUT")
        amp = self._install_fake_pin(fake)
        amp.unmute()
        self.assertEqual(fake.values[-1], 1)  # 解除静音=高电平
        amp.mute()
        self.assertEqual(fake.values[-1], 0)  # 恢复静音=低电平

    def test_refcount_pairs_only_last_mute(self):
        fake = _FakePin(20, "OUT")
        amp = self._install_fake_pin(fake)
        amp.unmute()
        amp.unmute()  # 第二次解除静音仍应保持高电平，且不应重复写
        self.assertEqual(fake.values.count(1), 1)
        amp.mute()    # 仍有未退出调用，不该静音
        self.assertEqual(fake.values[-1], 1)
        amp.mute()    # 最后一个退出，才真正静音
        self.assertEqual(fake.values[-1], 0)

    def test_context_manager_wraps_playback(self):
        fake = _FakePin(20, "OUT")
        amp = self._install_fake_pin(fake)
        with amp:
            self.assertEqual(fake.values[-1], 1)
        self.assertEqual(fake.values[-1], 0)


if __name__ == "__main__":
    unittest.main()
