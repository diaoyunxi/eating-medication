# -*- coding: utf-8 -*-
"""family_monitor.core.api_client.ElderlyAPIClient 方法测试（mock _execute）。

通过继承并替换异步 _execute 为可控返回，覆盖设备绑定、各 REST 调用、
仪表板数据计算与异常降级分支，显著提升 api_client.py 覆盖率。
"""
import asyncio
import importlib.util
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_HAS = all(importlib.util.find_spec(m) is not None
           for m in ("httpx", "dotenv", "itsdangerous", "bcrypt"))

if _HAS:
    from tests._helpers import load_module
    api_client = load_module(
        "family_core_api_client_methods", "family_monitor/core/api_client.py"
    )
else:
    api_client = None


class _FakeResp:
    """模拟 _ResponseAdapter：带 status_code / json() 的轻量响应。"""

    def __init__(self, status_code=200, data=None, text=None, json_exc=None):
        self.status_code = status_code
        self._data = data
        if text is not None:
            self.text = text
        elif data is not None:
            self.text = json.dumps(data)
        else:
            self.text = ""
        self._json_exc = json_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        if self._data is not None:
            return self._data
        if self.text:
            # 模拟真实 _ResponseAdapter：文本尝试解析，失败则抛异常（而非返回 None）
            return json.loads(self.text)
        raise ValueError("no json")


class _ClientWithFakeExecute(api_client.ElderlyAPIClient):
    def __init__(self):
        super().__init__()
        self._calls = []
        self._next = None

    def set_response(self, resp):
        self._next = resp

    async def _execute(self, method, path, **kwargs):
        self._calls.append((method, path, kwargs))
        return self._next


@unittest.skipIf(api_client is None, "httpx/dotenv/itsdangerous/bcrypt not installed")
class TestExtractError(unittest.TestCase):
    def test_detail_dict(self):
        resp = _FakeResp(400, {"detail": "bad"})
        self.assertEqual(api_client.ElderlyAPIClient._extract_error(resp), "bad")

    def test_message_dict(self):
        resp = _FakeResp(400, {"message": "nope"})
        self.assertEqual(api_client.ElderlyAPIClient._extract_error(resp), "nope")

    def test_non_json_returns_status(self):
        resp = _FakeResp(500, text="boom", json_exc=ValueError())
        self.assertEqual(
            api_client.ElderlyAPIClient._extract_error(resp), "服务端返回状态码: 500"
        )

    def test_json_list_body_returns_status(self):
        resp = _FakeResp(500, data=[1, 2, 3])
        self.assertEqual(
            api_client.ElderlyAPIClient._extract_error(resp), "服务端返回状态码: 500"
        )


@unittest.skipIf(api_client is None, "deps missing")
class TestDeviceBindMethods(unittest.TestCase):
    def setUp(self):
        self.client = _ClientWithFakeExecute()
        self.client.clear_bound_device()

    def tearDown(self):
        f = api_client.config.DATA_DIR / "bound_device.json"
        if f.exists():
            f.unlink()

    def test_save_and_get_bound_device(self):
        self.client.save_bound_device("dev1", "name1", "tok1")
        self.assertEqual(self.client._device_id, "dev1")
        self.assertEqual(self.client._device_token, "tok1")
        info = self.client.get_bound_device()
        self.assertEqual(info["device_id"], "dev1")
        self.assertEqual(info["device_token"], "tok1")

    def test_save_preserves_token_when_empty(self):
        self.client.save_bound_device("dev1", "name1", "tok1")
        self.client.save_bound_device("dev1", "name1", "")
        self.assertEqual(self.client._device_token, "tok1")

    def test_clear_bound_device(self):
        self.client.save_bound_device("dev1", "name1", "tok1")
        self.client.clear_bound_device()
        self.assertIsNone(self.client._device_id)
        self.assertIsNone(self.client._device_token)
        self.assertIsNone(self.client.get_bound_device())


@unittest.skipIf(api_client is None, "deps missing")
class TestApiMethods(unittest.TestCase):
    def setUp(self):
        self.client = _ClientWithFakeExecute()
        self.client.clear_bound_device()
        self._run = asyncio.run

    def tearDown(self):
        f = api_client.config.DATA_DIR / "bound_device.json"
        if f.exists():
            f.unlink()

    def test_register_device_success(self):
        self.client.set_response(_FakeResp(200, {"device_token": "newtok"}))
        res = self._run(self.client.register_device("dev1", "n"))
        self.assertTrue(res["success"])
        self.assertEqual(self.client._device_id, "dev1")
        self.assertEqual(self.client._device_token, "newtok")

    def test_register_device_non_200(self):
        self.client.set_response(_FakeResp(400, {"detail": "x"}))
        res = self._run(self.client.register_device("dev1", "n"))
        self.assertFalse(res["success"])

    def test_register_device_exception(self):
        async def boom(*a, **k):
            raise RuntimeError("net")
        self.client._execute = boom
        res = self._run(self.client.register_device("dev1", "n"))
        self.assertFalse(res["success"])

    def test_check_device_success(self):
        self.client.set_response(_FakeResp(200, {"exists": True}))
        res = self._run(self.client.check_device("dev1"))
        self.assertTrue(res["success"])

    def test_check_device_fail(self):
        self.client.set_response(_FakeResp(404, {"detail": "no"}))
        res = self._run(self.client.check_device("dev1"))
        self.assertFalse(res["success"])

    def test_get_device_plans_no_device(self):
        self.client._device_id = None
        self.assertEqual(self._run(self.client.get_device_plans()), [])

    def test_get_device_plans_success(self):
        self.client._device_id = "dev1"
        self.client.set_response(_FakeResp(200, {"device_id": "dev1", "plans": [{"id": 1}]}))
        self.assertEqual(self._run(self.client.get_device_plans()), [{"id": 1}])

    def test_get_device_plans_non_200(self):
        self.client._device_id = "dev1"
        self.client.set_response(_FakeResp(500))
        self.assertEqual(self._run(self.client.get_device_plans()), [])

    def test_set_medication_plan_no_device(self):
        self.client._device_id = None
        res = self._run(self.client.set_medication_plan("药", "1片", ["08:00"]))
        self.assertFalse(res["success"])
        self.assertIn("未绑定", res["error"])

    def test_set_medication_plan_success(self):
        self.client._device_id = "dev1"
        self.client.set_response(_FakeResp(200, {"ok": True}))
        res = self._run(self.client.set_medication_plan("药", "1片", ["08:00"]))
        self.assertTrue(res["success"])

    def test_set_medication_plan_error_extract(self):
        self.client._device_id = "dev1"
        self.client.set_response(_FakeResp(400, {"detail": "bad"}))
        res = self._run(self.client.set_medication_plan("药", "1片", ["08:00"]))
        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "bad")

    def test_set_medication_plan_family_mode(self):
        # 家属模式（load_bound=False，_device_id 为空）应先进家属分支、
        # 先解析服务端绑定，再 POST 家属接口，而非提前返回未绑定。
        self.client.set_jwt_token("jwt-fake")
        calls = []

        async def seq_execute(method, path, **kwargs):
            calls.append((method, path))
            if path == "/api/v1/users/me":
                return _FakeResp(200, {"device_id": "server-dev"})
            if path == "/api/v1/family/device/medication_plan":
                return _FakeResp(200, {"status": "ok"})
            return _FakeResp(500)

        self.client._execute = seq_execute
        res = self._run(self.client.set_medication_plan("药", "1片", ["08:00"]))
        self.assertTrue(res["success"])
        self.assertEqual(self.client._device_id, "server-dev")
        self.assertIn(("GET", "/api/v1/users/me"), calls)
        self.assertIn(("POST", "/api/v1/family/device/medication_plan"), calls)

    def test_set_medication_plan_family_unbound(self):
        # 家属模式但服务端未绑定（/users/me 返回空 device_id）时应给出明确错误
        self.client.set_jwt_token("jwt-fake")
        calls = []

        async def seq_execute(method, path, **kwargs):
            calls.append((method, path))
            if path == "/api/v1/users/me":
                return _FakeResp(200, {"device_id": None})
            return _FakeResp(500)

        self.client._execute = seq_execute
        res = self._run(self.client.set_medication_plan("药", "1片", ["08:00"]))
        self.assertFalse(res["success"])
        self.assertIn("尚未绑定", res["error"])

    def test_delete_medication_plan_success(self):
        self.client.set_response(_FakeResp(200, {"ok": True}))
        res = self._run(self.client.delete_medication_plan(5))
        self.assertTrue(res["success"])

    def test_update_medication_plan_no_device(self):
        self.client._device_id = None
        res = self._run(self.client.update_medication_plan(5, "药", "1片", ["08:00"]))
        self.assertFalse(res["success"])

    def test_update_medication_plan_success(self):
        self.client._device_id = "dev1"
        self.client.set_response(_FakeResp(200, {"ok": True}))
        res = self._run(self.client.update_medication_plan(5, "药", "1片", ["08:00"]))
        self.assertTrue(res["success"])

    def test_update_medication_plan_family_mode(self):
        # 家属模式（_device_id 为空）应先进家属分支、先解析服务端绑定，再 PUT
        self.client.set_jwt_token("jwt-fake")
        calls = []

        async def seq_execute(method, path, **kwargs):
            calls.append((method, path))
            if path == "/api/v1/users/me":
                return _FakeResp(200, {"device_id": "server-dev"})
            if path == "/api/v1/family/device/medication_plan/5":
                return _FakeResp(200, {"status": "ok"})
            return _FakeResp(500)

        self.client._execute = seq_execute
        res = self._run(self.client.update_medication_plan(5, "药", "1片", ["08:00"]))
        self.assertTrue(res["success"])
        self.assertIn(("GET", "/api/v1/users/me"), calls)
        self.assertIn(("PUT", "/api/v1/family/device/medication_plan/5"), calls)

    def test_get_device_info_no_device(self):
        self.client._device_id = None
        info = self._run(self.client.get_device_info())
        self.assertFalse(info["connected"])
        self.assertEqual(info["status"], "未绑定")

    def test_get_device_info_success(self):
        self.client._device_id = "dev1"
        self.client.set_response(_FakeResp(200, {
            "is_online": True, "device_id": "dev1", "device_name": "老人机",
            "role": "elder", "created_at": "x", "total_plans": 2,
            "total_records": 3, "status": "online", "last_heartbeat": "t",
        }))
        info = self._run(self.client.get_device_info())
        self.assertTrue(info["connected"])
        self.assertEqual(info["device_name"], "老人机")

    def test_get_device_info_offline(self):
        self.client._device_id = "dev1"
        self.client.set_response(_FakeResp(500))
        info = self._run(self.client.get_device_info())
        self.assertFalse(info["connected"])
        self.assertEqual(info["status"], "offline")

    def test_get_reminders_returns_plans(self):
        self.client._device_id = "dev1"
        self.client.set_response(_FakeResp(200, {"plans": [{"id": 1}]}))
        self.assertEqual(self._run(self.client.get_reminders()), [{"id": 1}])

    def test_get_reminders_no_device(self):
        self.client._device_id = None
        self.assertEqual(self._run(self.client.get_reminders()), [])

    def test_get_medication_records(self):
        self.client._device_id = "dev1"
        self.client.set_response(_FakeResp(200, {"records": [{"id": 9}]}))
        self.assertEqual(self._run(self.client.get_medication_records()), [{"id": 9}])

    def test_get_chat_history(self):
        self.client._device_id = "dev1"
        self.client.set_response(_FakeResp(200, {"messages": [{"id": 1}]}))
        self.assertEqual(self._run(self.client.get_chat_history()), [{"id": 1}])

    def test_get_server_status(self):
        async def _conn():
            return True
        self.client.check_connection = _conn
        self.client._device_id = "dev1"
        self.client.save_bound_device("dev1", "n", "t")
        status = self._run(self.client.get_server_status())
        self.assertTrue(status["connected"])
        self.assertEqual(status["device_id"], "dev1")


@unittest.skipIf(api_client is None, "deps missing")
class TestDashboardData(unittest.TestCase):
    def setUp(self):
        self.client = _ClientWithFakeExecute()
        self.client.clear_bound_device()
        self.client._device_id = "dev1"
        self._run = asyncio.run
        self.reminders = [
            {"id": 1, "drug_name": "药A", "dosage": "1片", "frequency": "每日",
             "schedule_times": ["08:00", "12:00"], "total_quantity": 10,
             "remaining_quantity": 4, "unit": "片", "low_stock_threshold": 3,
             "enabled": True, "taken_today": True},
            {"id": 2, "drug_name": "药B", "dosage": "2片", "frequency": "每日",
             "schedule_times": ["20:00"], "total_quantity": 5, "remaining_quantity": 5,
             "unit": "片", "low_stock_threshold": 2, "enabled": True, "taken_today": False},
        ]
        self.records = [
            {"id": 100, "plan_id": 1, "status": "taken",
             "scheduled_time": "2026-08-08T08:00:00", "taken_time": "2026-08-08T08:05:00"},
            {"id": 101, "plan_id": 1, "status": "missed",
             "scheduled_time": "2026-08-07T08:00:00"},
            {"id": 102, "plan_id": 2, "status": "taken",
             "scheduled_time": "2026-08-08T20:00:00", "taken_time": "2026-08-08T20:10:00"},
        ]

    def tearDown(self):
        f = api_client.config.DATA_DIR / "bound_device.json"
        if f.exists():
            f.unlink()

    def _patch(self):
        async def _reminders():
            return self.reminders
        async def _records():
            return self.records
        self.client.get_reminders = _reminders
        self.client.get_medication_records = _records

    def test_dashboard_computed(self):
        self._patch()
        data = self._run(self.client.get_dashboard_data())
        s = data["summary"]
        self.assertEqual(s["total_reminders"], 2)
        self.assertEqual(s["active_reminders"], 2)
        self.assertEqual(s["taken_today"], 1)
        self.assertEqual(s["pending_today"], 1)
        self.assertEqual(s["adherence_rate"], 66)
        self.assertEqual(len(data["medications"]), 2)
        ds = data["chart_data"]["drug_stats"]
        self.assertEqual(ds["药A"]["total"], 2)
        self.assertEqual(ds["药A"]["taken"], 1)
        self.assertEqual(ds["药B"]["taken"], 1)
        self.assertEqual(ds["药B"]["missed"], 0)
        self.assertEqual(len(data["chart_data"]["heat_matrix"]), 14)
        self.assertEqual(len(data["chart_data"]["gantt"]), 3)
        self.assertEqual(data["chart_data"]["funnel"][0]["value"], 3)
        self.assertEqual(data["chart_data"]["funnel"][1]["value"], 2)
        self.assertEqual(data["chart_data"]["funnel"][2]["value"], 1)
        self.assertEqual(len(data["chart_data"]["calendar"]), 1)
        self.assertEqual(data["chart_data"]["calendar"][0][1], 2)
        self.assertEqual(len(data["recent_activities"]), 3)
        self.assertEqual(len(data["upcoming_reminders"]), 2)
        self.assertEqual(len(data["chart_data"]["days"]), 7)

    def test_dashboard_empty(self):
        async def _empty():
            return []
        self.client.get_reminders = _empty
        self.client.get_medication_records = _empty
        data = self._run(self.client.get_dashboard_data())
        self.assertEqual(data["summary"]["total_reminders"], 0)
        self.assertEqual(data["summary"]["adherence_rate"], 0)
        self.assertEqual(data["medications"], [])

    def test_dashboard_exception_returns_zeros(self):
        async def _boom():
            raise RuntimeError("x")
        self.client.get_reminders = _boom
        data = self._run(self.client.get_dashboard_data())
        self.assertEqual(data["summary"]["total_reminders"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
