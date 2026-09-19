# -*- coding: utf-8 -*-
"""family_monitor.services.medication_service.validate_and_build 补充测试（超集）。

原 tests/test_family_medication_service.py 已覆盖核心失败分支；本文件用
tests._helpers.load_module 加载，补充正常值、可选字段、字符串强转与混合空时间过滤等
分支，使该函数覆盖率更完整。
"""
import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_HAS = importlib.util.find_spec("dotenv") is not None

if _HAS:
    from tests._helpers import load_module
    med = load_module("family_services_medication_extra", "family_monitor/services/medication_service.py")
else:
    med = None


@unittest.skipIf(med is None, "dotenv not installed")
class TestValidateAndBuildExtra(unittest.TestCase):
    def _ok(self, payload):
        fields, error = med.validate_and_build(payload)
        self.assertIsNone(error)
        self.assertTrue(fields)
        return fields

    def test_valid_full(self):
        fields = self._ok({
            "drug_name": "阿司匹林", "dosage": "1片",
            "schedule_times": ["08:00", "20:00"], "frequency": "daily",
            "total_quantity": 30, "remaining_quantity": 10, "unit": "片",
            "low_stock_threshold": 5, "product_code": "690123",
        })
        self.assertEqual(fields["drug_name"], "阿司匹林")
        self.assertEqual(fields["schedule_times"], ["08:00", "20:00"])
        self.assertEqual(fields["total_quantity"], 30)
        self.assertEqual(fields["remaining_quantity"], 10)
        self.assertEqual(fields["product_code"], "690123")

    def test_missing_drug_name(self):
        fields, error = med.validate_and_build({"dosage": "1片",
                                                "schedule_times": ["08:00"]})
        self.assertEqual(error, "请填写药品名称")
        self.assertEqual(fields, {})

    def test_missing_dosage(self):
        fields, error = med.validate_and_build({"drug_name": "x",
                                                "schedule_times": ["08:00"]})
        self.assertEqual(error, "请填写剂量")

    def test_missing_schedule(self):
        fields, error = med.validate_and_build({"drug_name": "x", "dosage": "1"})
        self.assertEqual(error, "请至少添加一个服药时间")

    def test_schedule_not_list(self):
        fields, error = med.validate_and_build({"drug_name": "x", "dosage": "1",
                                                "schedule_times": "08:00"})
        self.assertEqual(error, "请至少添加一个服药时间")

    def test_schedule_filtered_empty(self):
        fields, error = med.validate_and_build({"drug_name": "x", "dosage": "1",
                                                "schedule_times": ["", "  "]})
        self.assertEqual(error, "请至少添加一个服药时间")

    def test_schedule_filters_mixed(self):
        """混合空字符串时间应被过滤，成功返回 ['08:00', '20:00']。"""
        fields, error = med.validate_and_build({
            "drug_name": "阿司匹林", "dosage": "1片",
            "schedule_times": ["08:00", "  ", "", "20:00"],
        })
        self.assertIsNone(error)
        self.assertEqual(fields["schedule_times"], ["08:00", "20:00"])

    def test_product_code_optional(self):
        fields = self._ok({"drug_name": "x", "dosage": "1",
                           "schedule_times": ["08:00"]})
        self.assertIsNone(fields["product_code"])

    def test_quantity_fallback_on_bad_int(self):
        fields = self._ok({"drug_name": "x", "dosage": "1",
                           "schedule_times": ["08:00"], "total_quantity": "bad"})
        self.assertEqual(fields["total_quantity"], 0)

    def test_remaining_defaults_to_total(self):
        fields = self._ok({"drug_name": "x", "dosage": "1",
                           "schedule_times": ["08:00"], "total_quantity": 20})
        self.assertEqual(fields["remaining_quantity"], 20)

    def test_string_quantity_coercion(self):
        """total_quantity 传字符串 '10' 应强转为整数 10，remaining None 回退为 total。"""
        fields = self._ok({
            "drug_name": "阿司匹林", "dosage": "1片", "schedule_times": ["08:00"],
            "total_quantity": "10", "remaining_quantity": None,
            "low_stock_threshold": "5",
        })
        self.assertEqual(fields["total_quantity"], 10)
        self.assertEqual(fields["remaining_quantity"], 10)
        self.assertEqual(fields["unit"], "片")
        self.assertEqual(fields["low_stock_threshold"], 5)

    def test_default_unit_and_threshold(self):
        fields = self._ok({"drug_name": "x", "dosage": "1",
                           "schedule_times": ["08:00"]})
        self.assertEqual(fields["unit"], "片")
        self.assertEqual(fields["low_stock_threshold"], 5)

    def test_low_stock_bad_int_fallback(self):
        fields = self._ok({"drug_name": "x", "dosage": "1",
                           "schedule_times": ["08:00"],
                           "low_stock_threshold": "nan"})
        self.assertEqual(fields["low_stock_threshold"], 5)

    def test_bad_int_falls_back(self):
        fields, error = med.validate_and_build({
            "drug_name": "阿司匹林", "dosage": "1片", "schedule_times": ["08:00"],
            "total_quantity": "abc", "remaining_quantity": "xyz",
        })
        self.assertIsNone(error)
        self.assertEqual(fields["total_quantity"], 0)
        self.assertEqual(fields["remaining_quantity"], 0)


if __name__ == "__main__":
    unittest.main()
