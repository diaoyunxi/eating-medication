# -*- coding: utf-8 -*-
"""elderly_assistant 用药管理纯逻辑测试。"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_HAS_YAML = importlib.util.find_spec("yaml") is not None

if _HAS_YAML:
    from tests._helpers import load_module
    medication = load_module("elderly_core_medication", "elderly_assistant/core/medication.py")
else:
    medication = None


@unittest.skipIf(medication is None, "pyyaml not installed")
class TestParseDosage(unittest.TestCase):
    def test_arabic_first(self):
        self.assertEqual(medication._parse_dosage("每天1次"), 1)
        self.assertEqual(medication._parse_dosage("2片"), 2)
        self.assertEqual(medication._parse_dosage("第10次"), 10)
        self.assertEqual(medication._parse_dosage("每日1.5片"), 1)

    def test_chinese(self):
        self.assertEqual(medication._parse_dosage("三次"), 3)
        self.assertEqual(medication._parse_dosage("一次"), 1)
        self.assertEqual(medication._parse_dosage("两片"), 2)
        self.assertEqual(medication._parse_dosage("半片"), 0.5)

    def test_invalid(self):
        self.assertEqual(medication._parse_dosage(""), 0)
        self.assertEqual(medication._parse_dosage("abc"), 0)


@unittest.skipIf(medication is None, "pyyaml not installed")
class TestMedicationManager(unittest.TestCase):
    def _new_mgr(self):
        d = tempfile.mkdtemp()
        return medication.MedicationManager(data_path=os.path.join(d, "meds.json"))

    def test_add_and_not_low(self):
        mgr = self._new_mgr()
        mgr.add_medication("布洛芬", total_quantity=10, dosage_per_use=2, reminder_days=5)
        med = mgr.medications[0]
        # remaining=10, dosage=2 -> 5 天；等于阈值(5)不算低 -> 返回 (None, None)
        name, days = mgr.check_low(med)
        self.assertIsNone(name)
        self.assertIsNone(days)

    def test_low_detection(self):
        mgr = self._new_mgr()
        mgr.add_medication("阿司匹林", total_quantity=3, dosage_per_use=2, reminder_days=5)
        med = mgr.medications[0]
        name, days = mgr.check_low(med)
        self.assertEqual(name, "阿司匹林")
        self.assertEqual(days, 1.5)

    def test_consume_reduces_remaining(self):
        mgr = self._new_mgr()
        mgr.add_medication("布洛芬", total_quantity=10, dosage_per_use=2)
        self.assertTrue(mgr.consume("布洛芬", "两片"))
        self.assertEqual(mgr.medications[0]["remaining"], 8)
        # 服用后 remaining=8, dosage=2 -> 4 天 < 5 -> 触发低库存
        name, days = mgr.check_low(mgr.medications[0])
        self.assertEqual(name, "布洛芬")

    def test_consume_unknown(self):
        mgr = self._new_mgr()
        self.assertFalse(mgr.consume("不存在", "一片"))

    def test_load_roundtrip(self):
        mgr = self._new_mgr()
        mgr.add_medication("维C", total_quantity=20, dosage_per_use=1)
        mgr2 = medication.MedicationManager(data_path=mgr.data_path)
        self.assertEqual(len(mgr2.medications), 1)
        self.assertEqual(mgr2.medications[0]["name"], "维C")


if __name__ == "__main__":
    unittest.main()
