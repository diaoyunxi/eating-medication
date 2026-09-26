# -*- coding: utf-8 -*-
"""app.schemas.vision 单元测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pydantic import ValidationError
from app.schemas.vision import ImageRecognitionResp


class TestImageRecognitionResp(unittest.TestCase):
    def test_valid_with_confidence(self):
        r = ImageRecognitionResp(drug_name="阿司匹林", confidence=0.9)
        self.assertEqual(r.drug_name, "阿司匹林")
        self.assertEqual(r.confidence, 0.9)

    def test_confidence_optional(self):
        r = ImageRecognitionResp(drug_name="布洛芬")
        self.assertIsNone(r.confidence)

    def test_drug_name_required(self):
        with self.assertRaises(ValidationError):
            ImageRecognitionResp(confidence=0.5)

    def test_confidence_out_of_range(self):
        with self.assertRaises(ValidationError):
            ImageRecognitionResp(drug_name="X", confidence=1.5)
        with self.assertRaises(ValidationError):
            ImageRecognitionResp(drug_name="X", confidence=-0.1)

    def test_confidence_boundary(self):
        # 边界值 0 与 1 应通过
        self.assertEqual(ImageRecognitionResp(drug_name="X", confidence=0).confidence, 0)
        self.assertEqual(ImageRecognitionResp(drug_name="X", confidence=1).confidence, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
