# -*- coding: utf-8 -*-
"""elderly_assistant 工作流纯逻辑测试（无硬件依赖，使用 Fake 替身）。"""
import sys
import unittest
from datetime import datetime
from pathlib import Path

# 将 elderly_assistant 加入 sys.path，使其顶层包 workflow / hardware / core 可导入
EA = Path(__file__).resolve().parent.parent / "elderly_assistant"
if str(EA) not in sys.path:
    sys.path.insert(0, str(EA))

from workflow.reminder import ReminderState, check_medication_trigger
from workflow.actions import handle_confirm, handle_snooze
from workflow.button_input import ButtonController
from hardware.fakes import FakeButton, FakeBuzzer, FakeDisplay, FakeHttpClient


class FakePoller:
    """最小轮询替身：固定返回预设的用药计划列表。"""

    def __init__(self, schedules):
        self._schedules = schedules

    @property
    def schedules(self):
        return self._schedules


class TestReminderState(unittest.TestCase):
    def test_trigger_confirm(self):
        st = ReminderState()
        self.assertFalse(st.active)
        st.trigger("阿司匹林", "1片", "k1", items=[{"plan_id": 1}])
        self.assertTrue(st.active)
        self.assertEqual(st.drug_name, "阿司匹林")
        self.assertEqual(st.items, [{"plan_id": 1}])
        st.confirm()
        self.assertFalse(st.active)
        self.assertEqual(st.drug_name, "")

    def test_snooze_keeps_active(self):
        st = ReminderState()
        st.trigger("药", "1片", "k")
        st.snooze(5)
        self.assertTrue(st.active)
        self.assertIsNotNone(st.snooze_until)


class TestCheckMedicationTrigger(unittest.TestCase):
    def _now(self, hhmm):
        y, m, d = 2026, 7, 28
        h, mi = map(int, hhmm.split(":"))
        return datetime(y, m, d, h, mi, 0)

    def test_triggers_at_match(self):
        poller = FakePoller([{"time": "12:00", "drug_name": "阿司匹林", "dosage": "1片", "plan_id": 1}])
        st = ReminderState()
        buzzer = FakeBuzzer()
        display = FakeDisplay()
        log = __import__("logging").getLogger("t")
        check_medication_trigger(self._now("12:00"), poller, st, buzzer, display, 5, log)
        self.assertTrue(st.active)
        self.assertTrue(buzzer.playing)
        self.assertEqual(display.reminder_shown, ("阿司匹林", "1片"))

    def test_no_trigger_when_mismatch(self):
        poller = FakePoller([{"time": "12:00", "drug_name": "药", "dosage": ""}])
        st = ReminderState()
        buzzer = FakeBuzzer()
        display = FakeDisplay()
        log = __import__("logging").getLogger("t")
        check_medication_trigger(self._now("13:00"), poller, st, buzzer, display, 5, log)
        self.assertFalse(st.active)
        self.assertFalse(buzzer.playing)

    def test_no_duplicate_trigger_same_minute(self):
        poller = FakePoller([{"time": "12:00", "drug_name": "药", "dosage": ""}])
        st = ReminderState()
        buzzer = FakeBuzzer()
        display = FakeDisplay()
        log = __import__("logging").getLogger("t")
        check_medication_trigger(self._now("12:00"), poller, st, buzzer, display, 5, log)
        # 再次触发同一分钟不应重复（fired_keys 已记录）
        check_medication_trigger(self._now("12:00"), poller, st, buzzer, display, 5, log)
        self.assertEqual(display.reminder_count, 1)


class TestHandleConfirm(unittest.TestCase):
    def test_confirm_reports_and_clears(self):
        st = ReminderState()
        st.trigger("阿司匹林", "1片", "k", items=[{"plan_id": 1}])
        buzzer = FakeBuzzer()
        display = FakeDisplay()
        http = FakeHttpClient()
        log = __import__("logging").getLogger("t")
        handle_confirm(st, buzzer, display, http, log)
        self.assertFalse(st.active)
        self.assertTrue(buzzer.stopped)
        self.assertEqual(http.confirmed, ("阿司匹林", "1片"))


class TestButtonController(unittest.TestCase):
    def test_short_press_confirms_when_active(self):
        ctrl = ButtonController(long_press_sec=1.5)
        st = ReminderState()
        st.trigger("药", "1片", "k")
        btn = FakeButton(pressed=False)
        buzzer = FakeBuzzer()
        display = FakeDisplay()
        http = FakeHttpClient()
        log = __import__("logging").getLogger("t")
        confirmed = []

        def on_confirm():
            # 与 main 主循环一致：on_confirm 实际执行确认动作
            confirmed.append(1)
            handle_confirm(st, buzzer, display, http, log)

        ctrl.process(1.0, btn, None, st, on_confirm, lambda: None, lambda: None)
        self.assertEqual(confirmed, [])
        btn.set_pressed(True)
        ctrl.process(1.1, btn, None, st, on_confirm, lambda: None, lambda: None)
        btn.set_pressed(False)
        ctrl.process(1.2, btn, None, st, on_confirm, lambda: None, lambda: None)
        self.assertEqual(confirmed, [1])
        self.assertFalse(st.active)

    def test_long_press_triggers_ai(self):
        ctrl = ButtonController(long_press_sec=1.5)
        st = ReminderState()
        st.trigger("药", "1片", "k")
        btn = FakeButton(pressed=True)
        ai = []
        ctrl.process(1.0, btn, None, st, lambda: None, lambda: ai.append(1), lambda: None)
        ctrl.process(3.0, btn, None, st, lambda: None, lambda: ai.append(1), lambda: None)
        self.assertEqual(ai, [1])

    def test_snooze_when_active(self):
        ctrl = ButtonController(long_press_sec=1.5)
        st = ReminderState()
        st.trigger("药", "1片", "k")
        btn_b = FakeButton(pressed=True)
        snoozed = []
        ctrl.process(1.0, None, btn_b, st, lambda: None, lambda: None, lambda: snoozed.append(1))
        self.assertEqual(snoozed, [1])
        self.assertGreater(ctrl.button_block_until, 1.0)


if __name__ == "__main__":
    unittest.main()
