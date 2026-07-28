# -*- coding: utf-8 -*-
"""family_monitor 用药计划校验纯逻辑测试（无 IO 依赖）。"""
import sys
import unittest
from pathlib import Path

FM = Path(__file__).resolve().parent.parent / "family_monitor"
if str(FM) not in sys.path:
    sys.path.insert(0, str(FM))

from services.medication_service import validate_and_build


class TestValidateAndBuild(unittest.TestCase):
    def test_missing_drug_name(self):
        fields, err = validate_and_build({"dosage": "1片", "schedule_times": ["08:00"]})
        self.assertEqual(err, "请填写药品名称")
        self.assertEqual(fields, {})

    def test_missing_dosage(self):
        fields, err = validate_and_build({"drug_name": "阿司匹林", "schedule_times": ["08:00"]})
        self.assertEqual(err, "请填写剂量")

    def test_missing_schedule(self):
        fields, err = validate_and_build({"drug_name": "阿司匹林", "dosage": "1片"})
        self.assertEqual(err, "请至少添加一个服药时间")

    def test_filters_empty_times(self):
        fields, err = validate_and_build({
            "drug_name": "阿司匹林", "dosage": "1片",
            "schedule_times": ["08:00", "  ", "", "20:00"],
        })
        self.assertIsNone(err)
        self.assertEqual(fields["schedule_times"], ["08:00", "20:00"])

    def test_int_coercion_defaults(self):
        fields, err = validate_and_build({
            "drug_name": "阿司匹林", "dosage": "1片", "schedule_times": ["08:00"],
            "total_quantity": "10", "remaining_quantity": None, "low_stock_threshold": "5",
        })
        self.assertIsNone(err)
        self.assertEqual(fields["total_quantity"], 10)
        self.assertEqual(fields["remaining_quantity"], 10)  # None -> total
        self.assertEqual(fields["unit"], "片")
        self.assertEqual(fields["low_stock_threshold"], 5)

    def test_bad_int_falls_back(self):
        fields, err = validate_and_build({
            "drug_name": "阿司匹林", "dosage": "1片", "schedule_times": ["08:00"],
            "total_quantity": "abc", "remaining_quantity": "xyz",
        })
        self.assertIsNone(err)
        self.assertEqual(fields["total_quantity"], 0)
        self.assertEqual(fields["remaining_quantity"], 0)


if __name__ == "__main__":
    unittest.main()
