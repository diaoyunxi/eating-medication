# -*- coding: utf-8 -*-
"""app.services.vision_service 单元测试（需要 pydantic-settings / httpx）。

仅测试纯静态方法 _extract_drug_name（从模型/ OCR 文本中抽取药名），无需真实模型或网络。
依赖缺失时整体跳过。
"""
import os
import sys
import asyncio
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-not-for-production-0123456789")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test_elderly_care.db")

try:
    from app.services.vision_service import VisionService
    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False


@unittest.skipUnless(_HAVE, "需要 pydantic-settings / httpx（当前环境未安装）")
class TestExtractDrugName(unittest.TestCase):
    def test_from_json(self):
        text = '{"识别结果": {"药名": "阿司匹林", "数量": "1"}}'
        self.assertEqual(asyncio.run(VisionService._extract_drug_name(text)), "阿司匹林")

    def test_from_plain_chinese_colon(self):
        self.assertEqual(asyncio.run(VisionService._extract_drug_name("药名：布洛芬")), "布洛芬")

    def test_none_when_no_drug(self):
        self.assertIsNone(asyncio.run(VisionService._extract_drug_name("这是一段无关文字")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
