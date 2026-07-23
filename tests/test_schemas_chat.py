# -*- coding: utf-8 -*-
"""app.schemas.chat 单元测试。"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pydantic import ValidationError
from app.schemas.chat import ChatMessageCreate, ChatMessageOut


class TestChatMessageCreate(unittest.TestCase):
    def test_valid_with_receiver(self):
        m = ChatMessageCreate(receiver_id=2, content="你好")
        self.assertEqual(m.receiver_id, 2)
        self.assertEqual(m.content, "你好")

    def test_receiver_optional(self):
        m = ChatMessageCreate(content="广播")
        self.assertIsNone(m.receiver_id)

    def test_content_required(self):
        with self.assertRaises(ValidationError):
            ChatMessageCreate(receiver_id=1)


class TestChatMessageOut(unittest.TestCase):
    def test_from_attributes(self):
        class FakeMsg:
            id = 10
            sender_id = 1
            receiver_id = 2
            sender_name = "Alice"
            content = "hi"
            created_at = datetime(2026, 1, 1)

        out = ChatMessageOut.model_validate(FakeMsg())
        self.assertEqual(out.id, 10)
        self.assertEqual(out.sender_name, "Alice")


if __name__ == "__main__":
    unittest.main(verbosity=2)
