# -*- coding: utf-8 -*-
"""app.core.exceptions 单元测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import status
from app.core.exceptions import BusinessError


class TestBusinessError(unittest.TestCase):
    def test_defaults(self):
        err = BusinessError("出错了")
        self.assertEqual(err.message, "出错了")
        self.assertEqual(err.code, status.HTTP_400_BAD_REQUEST)

    def test_custom_code(self):
        err = BusinessError("无权限", 403)
        self.assertEqual(err.message, "无权限")
        self.assertEqual(err.code, 403)

    def test_is_exception(self):
        err = BusinessError("m")
        self.assertIsInstance(err, Exception)
        self.assertEqual(str(err), "m")


if __name__ == "__main__":
    unittest.main(verbosity=2)
