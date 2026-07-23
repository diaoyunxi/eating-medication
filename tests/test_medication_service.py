# -*- coding: utf-8 -*-
"""app.services.medication_service 单元测试（需要 sqlalchemy / pydantic-settings）。

take_medication 为 async，但底层使用同步 Session，故以 MagicMock 模拟 db 即可，
并以 asyncio.run 驱动；服药通知通过 patch app.websocket.notifier.notifier 隔离。
依赖缺失时整体跳过。
"""
import os
import sys
import asyncio
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-not-for-production-0123456789")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test_elderly_care.db")

try:
    from app.services.medication_service import MedicationService
    from app.schemas.medication import TakeMedicationRequest
    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False


def _make_db(plan, existing_record=None, rowcount=1):
    """构造 mock 的同步 Session：两次 query 分别返回 plan / existing_record。"""
    db = mock.MagicMock()
    plan_query = mock.MagicMock()
    plan_query.filter.return_value.first.return_value = plan
    rec_query = mock.MagicMock()
    rec_query.filter.return_value.first.return_value = existing_record
    db.query.side_effect = [plan_query, rec_query]
    result = mock.MagicMock()
    result.rowcount = rowcount
    db.execute.return_value = result
    return db


@unittest.skipUnless(_HAVE, "需要 sqlalchemy / pydantic-settings（当前环境未安装）")
class TestTakeMedication(unittest.TestCase):
    def _plan(self, remaining=5):
        plan = mock.MagicMock()
        plan.id = 1
        plan.drug_name = "阿司匹林"
        plan.remaining_quantity = remaining
        return plan

    def test_plan_not_found(self):
        db = mock.MagicMock()
        pq = mock.MagicMock()
        pq.filter.return_value.first.return_value = None
        db.query.side_effect = [pq, mock.MagicMock()]
        req = TakeMedicationRequest(plan_id=1, scheduled_time=datetime(2026, 1, 1, 8, 0))
        with self.assertRaises(ValueError):
            asyncio.run(MedicationService.take_medication(db, 1, req))

    def test_taken_decrements_stock_and_notifies(self):
        plan = self._plan(remaining=5)
        db = _make_db(plan, existing_record=None, rowcount=1)
        req = TakeMedicationRequest(
            plan_id=1,
            scheduled_time=datetime(2026, 1, 1, 8, 0),
            taken_time=datetime(2026, 1, 1, 8, 5),
        )
        with mock.patch("app.websocket.notifier.notifier") as notifier:
            notifier.notify_taken_medication = mock.AsyncMock()
            record = asyncio.run(MedicationService.take_medication(db, 1, req))
        self.assertEqual(record.status, "taken")
        self.assertTrue(db.execute.called)
        self.assertTrue(db.commit.called)
        notifier.notify_taken_medication.assert_awaited_once()

    def test_stock_insufficient_rolls_back(self):
        plan = self._plan(remaining=0)
        db = _make_db(plan, existing_record=None, rowcount=0)
        req = TakeMedicationRequest(
            plan_id=1,
            scheduled_time=datetime(2026, 1, 1, 8, 0),
            taken_time=datetime(2026, 1, 1, 8, 5),
        )
        with self.assertRaises(ValueError):
            asyncio.run(MedicationService.take_medication(db, 1, req))
        db.rollback.assert_called_once()
        db.commit.assert_not_called()

    def test_existing_record_updated_not_added(self):
        plan = self._plan(remaining=5)
        existing = mock.MagicMock()
        db = _make_db(plan, existing_record=existing, rowcount=1)
        req = TakeMedicationRequest(
            plan_id=1,
            scheduled_time=datetime(2026, 1, 1, 8, 0),
            taken_time=datetime(2026, 1, 1, 8, 5),
        )
        with mock.patch("app.websocket.notifier.notifier") as notifier:
            notifier.notify_taken_medication = mock.AsyncMock()
            record = asyncio.run(MedicationService.take_medication(db, 1, req))
        self.assertIs(record, existing)
        db.add.assert_not_called()

    def test_pending_when_not_taken_within_window(self):
        # 计划时间设在未来，未确认服药 -> pending（不扣库存）
        plan = self._plan(remaining=5)
        db = _make_db(plan, existing_record=None, rowcount=0)
        req = TakeMedicationRequest(
            plan_id=1,
            scheduled_time=datetime(2099, 1, 1, 8, 0),
            taken_time=None,
        )
        record = asyncio.run(MedicationService.take_medication(db, 1, req))
        self.assertEqual(record.status, "pending")
        db.execute.assert_not_called()

    def test_missed_when_not_taken_after_window(self):
        # 计划时间在过去，未确认服药 -> missed
        plan = self._plan(remaining=5)
        db = _make_db(plan, existing_record=None, rowcount=0)
        req = TakeMedicationRequest(
            plan_id=1,
            scheduled_time=datetime(2020, 1, 1, 8, 0, tzinfo=timezone.utc),
            taken_time=None,
        )
        record = asyncio.run(MedicationService.take_medication(db, 1, req))
        self.assertEqual(record.status, "missed")
        db.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
