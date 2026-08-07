# -*- coding: utf-8 -*-
"""老人端药品扫码与离线回退纯逻辑测试（无硬件/网络依赖，使用 Fake 替身）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

# 将 elderly_assistant 加入 sys.path，使其顶层包 workflow / hardware / core 可导入
EA = Path(__file__).resolve().parent.parent / "elderly_assistant"
if str(EA) not in sys.path:
    sys.path.insert(0, str(EA))

from tests._helpers import load_module  # noqa: E402

from workflow.actions import find_plan_by_product_code, handle_scan_medication  # noqa: E402
from workflow.reminder import MedicationPoller  # noqa: E402
from hardware.fakes import FakeBarcodeScanner, FakeSpeech  # noqa: E402

LOG = __import__("logging").getLogger("t")

PLANS = [
    {"plan_id": 1, "drug_name": "阿司匹林", "dosage": "1片", "time": "08:00", "product_code": "6901234567890"},
    {"plan_id": 2, "drug_name": "降压药", "dosage": "2片", "time": "20:00", "product_code": None},
]


class FakePoller:
    """最小轮询替身：固定返回预设的用药计划列表。"""

    def __init__(self, schedules):
        self._schedules = schedules

    @property
    def schedules(self):
        return self._schedules


class TestFindPlanByProductCode(unittest.TestCase):
    def test_match_exact(self):
        plan = find_plan_by_product_code(PLANS, "6901234567890")
        self.assertIsNotNone(plan)
        self.assertEqual(plan["drug_name"], "阿司匹林")

    def test_match_ignores_case_and_space(self):
        plans = [{"drug_name": "药", "dosage": "1片", "product_code": " AbC123 "}]
        self.assertIsNotNone(find_plan_by_product_code(plans, "abc123"))

    def test_no_match_returns_none(self):
        self.assertIsNone(find_plan_by_product_code(PLANS, "0000000000000"))

    def test_empty_code_returns_none(self):
        # 空编号不得与 product_code 为空的计划误匹配
        self.assertIsNone(find_plan_by_product_code(PLANS, ""))
        self.assertIsNone(find_plan_by_product_code(PLANS, None))
        self.assertIsNone(find_plan_by_product_code(PLANS, "   "))

    def test_tolerates_dirty_items(self):
        self.assertIsNone(find_plan_by_product_code([None, "x", 1], "abc"))


class TestHandleScanMedication(unittest.TestCase):
    def test_speaks_name_and_dosage_when_matched(self):
        scanner = FakeBarcodeScanner(["6901234567890"])
        speech = FakeSpeech()
        plan = handle_scan_medication(scanner, FakePoller(PLANS), speech, LOG, timeout=1)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["plan_id"], 1)
        self.assertTrue(any("阿司匹林" in t and "1片" in t for t in speech.spoken))

    def test_speaks_hint_when_not_matched(self):
        scanner = FakeBarcodeScanner(["1111111111111"])
        speech = FakeSpeech()
        plan = handle_scan_medication(scanner, FakePoller(PLANS), speech, LOG, timeout=1)
        self.assertIsNone(plan)
        self.assertTrue(any("没有找到" in t for t in speech.spoken))

    def test_speaks_hint_when_no_code(self):
        scanner = FakeBarcodeScanner([])  # 模拟超时未识别
        speech = FakeSpeech()
        plan = handle_scan_medication(scanner, FakePoller(PLANS), speech, LOG, timeout=1)
        self.assertIsNone(plan)
        self.assertTrue(any("没有识别到" in t for t in speech.spoken))

    def test_scanner_missing_degrades(self):
        speech = FakeSpeech()
        plan = handle_scan_medication(None, FakePoller(PLANS), speech, LOG)
        self.assertIsNone(plan)
        self.assertTrue(any("不可用" in t for t in speech.spoken))

    def test_scanner_exception_does_not_propagate(self):
        class BrokenScanner:
            def scan(self, timeout=None):
                raise RuntimeError("摄像头掉线")

        speech = FakeSpeech()
        plan = handle_scan_medication(BrokenScanner(), FakePoller(PLANS), speech, LOG)
        self.assertIsNone(plan)
        self.assertTrue(any("出错" in t for t in speech.spoken))

    def test_works_without_speech(self):
        scanner = FakeBarcodeScanner(["6901234567890"])
        plan = handle_scan_medication(scanner, FakePoller(PLANS), None, LOG)
        self.assertIsNotNone(plan)


display_mod = load_module("elderly_core_display", "elderly_assistant/core/display.py")


class TestDisplayScanButton(unittest.TestCase):
    """屏幕「扫码查药」触摸按钮（非 M10 环境 gui=None，仅验证回调装配逻辑）。"""

    def _display(self):
        # 非 M10 环境下 unihiker 缺失，Display 自动降级为 gui=None
        return display_mod.Display()

    def test_handler_not_registered_by_default(self):
        d = self._display()
        self.assertIsNone(d._scan_handler)
        self.assertFalse(d._on_scan_clicked())

    def test_click_invokes_registered_handler(self):
        d = self._display()
        clicks = []
        d.set_scan_handler(lambda: clicks.append(1))
        self.assertTrue(d._on_scan_clicked())
        self.assertEqual(clicks, [1])

    def test_non_callable_handler_rejected(self):
        d = self._display()
        d.set_scan_handler("not-callable")
        self.assertIsNone(d._scan_handler)
        self.assertFalse(d._on_scan_clicked())

    def test_handler_exception_is_isolated(self):
        # 回调异常不得向上抛出，避免 GUI 事件线程中断
        d = self._display()

        def boom():
            raise RuntimeError("扫码线程启动失败")

        d.set_scan_handler(boom)
        self.assertFalse(d._on_scan_clicked())

    def test_draw_scan_button_noop_without_gui(self):
        # 无 GUI 时绘制按钮应静默跳过，不抛异常
        d = self._display()
        d.set_scan_handler(lambda: None)
        d._draw_scan_button()
        self.assertIsNone(d._scan_button)


class FakeOfflineClient:
    """按预设序列返回拉取结果的 HTTP 替身（None 表示本次拉取结果未知）。"""

    def __init__(self, results):
        self.results = list(results)

    def get_medication_schedule(self):
        return self.results.pop(0) if self.results else None


class TestPollerOfflineFallback(unittest.TestCase):
    def test_seeds_from_cache_loader(self):
        poller = MedicationPoller(None, poll_interval=1, cache_loader=lambda: PLANS)
        self.assertEqual(len(poller.schedules), 2)

    def test_cache_loader_exception_is_tolerated(self):
        def boom():
            raise IOError("磁盘错误")

        poller = MedicationPoller(None, poll_interval=1, cache_loader=boom)
        self.assertEqual(poller.schedules, [])

    def test_none_result_keeps_existing_schedules(self):
        client = FakeOfflineClient([PLANS, None])
        poller = MedicationPoller(client, poll_interval=1)
        poller._poll_once()
        self.assertEqual(len(poller.schedules), 2)
        self.assertTrue(poller.last_success)
        # 第二轮返回 None（断网且无本地缓存）：保留既有计划，不清空
        poller._poll_once()
        self.assertEqual(len(poller.schedules), 2)
        self.assertFalse(poller.last_success)

    def test_empty_list_result_clears_schedules(self):
        # 服务端明确返回空列表（家人删光了计划）时应清空
        client = FakeOfflineClient([PLANS, []])
        poller = MedicationPoller(client, poll_interval=1)
        poller._poll_once()
        poller._poll_once()
        self.assertEqual(poller.schedules, [])

    def test_client_exception_keeps_existing_schedules(self):
        class BrokenClient:
            def __init__(self):
                self.calls = 0

            def get_medication_schedule(self):
                self.calls += 1
                if self.calls == 1:
                    return PLANS
                raise RuntimeError("连接被重置")

        poller = MedicationPoller(BrokenClient(), poll_interval=1)
        poller._poll_once()
        poller._poll_once()
        self.assertEqual(len(poller.schedules), 2)
        self.assertFalse(poller.last_success)


schedule_cache = load_module(
    "elderly_services_schedule_cache", "elderly_assistant/services/schedule_cache.py"
)


class TestScheduleCache(unittest.TestCase):
    def _tmp(self):
        return Path(tempfile.mkdtemp()) / "schedules.json"

    def test_save_and_load_roundtrip(self):
        p = self._tmp()
        self.assertTrue(schedule_cache.save_schedules(PLANS, p))
        loaded = schedule_cache.load_schedules(p)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["drug_name"], "阿司匹林")

    def test_load_missing_file_returns_empty(self):
        self.assertEqual(schedule_cache.load_schedules(self._tmp()), [])

    def test_load_corrupted_file_returns_empty(self):
        p = self._tmp()
        p.write_text("{ 半截 json", encoding="utf-8")
        self.assertEqual(schedule_cache.load_schedules(p), [])

    def test_load_non_list_returns_empty(self):
        p = self._tmp()
        p.write_text(json.dumps({"schedules": []}), encoding="utf-8")
        self.assertEqual(schedule_cache.load_schedules(p), [])

    def test_save_rejects_non_list(self):
        self.assertFalse(schedule_cache.save_schedules({"a": 1}, self._tmp()))

    def test_save_filters_dirty_items(self):
        p = self._tmp()
        self.assertTrue(schedule_cache.save_schedules([{"a": 1}, None, "x"], p))
        self.assertEqual(schedule_cache.load_schedules(p), [{"a": 1}])


if __name__ == "__main__":
    unittest.main()
