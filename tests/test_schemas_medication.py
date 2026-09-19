# -*- coding: utf-8 -*-
"""server/app/schemas/medication.py 单元测试。

覆盖 MedicationPlanCreate 的库存/时间格式校验规则。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pydantic import ValidationError  # noqa: E402

from app.schemas.medication import MedicationPlanCreate  # noqa: E402


class TestMedicationPlanCreate(unittest.TestCase):
    """用药计划创建校验。"""

    def _valid(self, **overrides):
        base = {
            "drug_name": "阿司匹林",
            "dosage": "1片",
            "frequency": "daily",
            "schedule_times": ["08:00", "20:00"],
            "total_quantity": 30,
            "remaining_quantity": 20,
            "unit": "片",
            "low_stock_threshold": 5,
        }
        base.update(overrides)
        return base

    def test_valid(self):
        req = MedicationPlanCreate(**self._valid())
        self.assertEqual(req.drug_name, "阿司匹林")
        self.assertEqual(req.remaining_quantity, 20)

    def test_remaining_gt_total_rejected(self):
        with self.assertRaises(ValidationError):
            MedicationPlanCreate(**self._valid(remaining_quantity=40, total_quantity=30))

    def test_total_quantity_must_be_positive(self):
        with self.assertRaises(ValidationError):
            MedicationPlanCreate(**self._valid(total_quantity=0))

    def test_invalid_schedule_time_format(self):
        with self.assertRaises(ValidationError):
            MedicationPlanCreate(**self._valid(schedule_times=["8:00"]))

    def test_remaining_quantity_required(self):
        data = self._valid()
        del data["remaining_quantity"]
        with self.assertRaises(ValidationError):
            MedicationPlanCreate(**data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
