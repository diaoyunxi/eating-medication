# -*- coding: utf-8 -*-
"""server/app/utils/rate_limit.py 单元测试。

mock 时间以验证滑动窗口限流：放行、超限拦截、窗口过期重置。
"""
import os
import sys
import unittest
from collections import defaultdict
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.utils import rate_limit  # noqa: E402


class TestCheckRateLimit(unittest.TestCase):
    """滑动窗口限流逻辑。"""

    def setUp(self):
        # 每个用例前清空全局 bucket，避免相互污染
        rate_limit._bucket = defaultdict(list)
        self._fake_now = 1000.0

    def _patch_time(self):
        return mock.patch.object(rate_limit.time, "time", return_value=self._fake_now)

    def test_allows_within_limit(self):
        with self._patch_time():
            for _ in range(5):
                self.assertTrue(rate_limit.check_rate_limit("127.0.0.1", 5))

    def test_blocks_after_limit(self):
        with self._patch_time():
            for _ in range(5):
                rate_limit.check_rate_limit("127.0.0.1", 5)
            self.assertFalse(rate_limit.check_rate_limit("127.0.0.1", 5))

    def test_reset_after_window(self):
        with self._patch_time():
            for _ in range(5):
                rate_limit.check_rate_limit("127.0.0.1", 5)
            self.assertFalse(rate_limit.check_rate_limit("127.0.0.1", 5))
        # 时间推进超过窗口（默认 60s），应重新放行
        self._fake_now += 61
        with self._patch_time():
            self.assertTrue(rate_limit.check_rate_limit("127.0.0.1", 5))

    def test_different_identifiers_isolated(self):
        with self._patch_time():
            for _ in range(5):
                rate_limit.check_rate_limit("10.0.0.1", 5)
            # 不同标识不受影响
            self.assertTrue(rate_limit.check_rate_limit("10.0.0.2", 5))


if __name__ == "__main__":
    unittest.main(verbosity=2)
