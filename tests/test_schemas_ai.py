# -*- coding: utf-8 -*-
"""app.schemas.ai 单元测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pydantic import ValidationError
from app.schemas.ai import AIQuestion, AIAnswer


class TestAIQuestion(unittest.TestCase):
    def test_valid(self):
        q = AIQuestion(question="今天能吃水果吗？")
        self.assertEqual(q.question, "今天能吃水果吗？")

    def test_empty_rejected(self):
        with self.assertRaises(ValidationError):
            AIQuestion(question="")

    def test_too_long_rejected(self):
        with self.assertRaises(ValidationError):
            AIQuestion(question="x" * 501)

    def test_whitespace_allowed(self):
        # min_length=1，全空格仍满足长度，应可通过
        q = AIQuestion(question="   ")
        self.assertEqual(q.question, "   ")


class TestAIAnswer(unittest.TestCase):
    def test_valid(self):
        a = AIAnswer(answer="可以的")
        self.assertEqual(a.answer, "可以的")


if __name__ == "__main__":
    unittest.main(verbosity=2)
