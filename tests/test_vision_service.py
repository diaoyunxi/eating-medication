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
    def _call(self, text):
        return asyncio.run(VisionService._extract_drug_name(text))

    def test_single_line_json_with_keyword_returns_whole_line(self):
        # OCR 单行 JSON 含药名关键词'阿司匹林' -> 返回整行（非提取字段）
        text = '{"识别结果": {"药名": "阿司匹林", "数量": "1"}}'
        self.assertEqual(self._call(text), text)

    def test_single_line_plain_with_keyword_returns_whole_line(self):
        # 单行含关键词'布洛芬' -> 返回整行
        self.assertEqual(self._call("药名：布洛芬"), "药名：布洛芬")

    def test_returns_line_containing_drug_keyword_among_lines(self):
        # 多行 OCR 文本：应返回含药名关键词的那一行（前导行不含任何关键词，避免提前命中）
        text = "姓名：张三\n检查日期：2024-01-01\n布洛芬胶囊 0.3g\n用法：饭后"
        self.assertEqual(self._call(text), "布洛芬胶囊 0.3g")

    def test_no_keyword_returns_first_line(self):
        # 无关键词且非空 -> 返回第一行（并非 None）
        self.assertEqual(self._call("这是一段无关文字"), "这是一段无关文字")

    def test_empty_text_returns_empty(self):
        # 空文本 split 后 lines[0] 为 ''；源码 '识别失败' 分支因 split 永非空列表而不可达
        self.assertEqual(self._call(""), "")

    def test_short_lines_skipped_but_keyword_line_selected(self):
        # 长度 < 3 的短行被跳过，命中含关键词的长行
        text = "ab\ncd\n维生素C片\nxy"
        self.assertEqual(self._call(text), "维生素C片")


if __name__ == "__main__":
    unittest.main(verbosity=2)
