# -*- coding: utf-8 -*-
"""family_monitor 子页路由（home/chat/ai_config）单元测试 + 页面冒烟。

通过 tests._helpers.load_module 按文件路径加载，避免同名顶层包冲突；
并以 FakeClient / FakeApiRequest 替换模块级 elderly_client / user_api_request /
require_login 等依赖，覆盖各分支。
"""
import asyncio
import importlib.util
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.testclient import TestClient


class _NoRedirectClient:
    """兼容新旧 starlette 的 TestClient 包装：请求级统一不跟随重定向。

    新版 starlette（>=0.28）TestClient 构造器支持 follow_redirects 且默认 True；
    旧版构造器不接受该参数。本包装在请求级透传 follow_redirects=False，
    使两个版本下行为一致，避免带 PATH_PREFIX 的 302 被本地独立 app 误判为 404。
    """

    def __init__(self, app):
        self.app = app
        self._client = TestClient(app)

    def _call(self, method, *args, **kwargs):
        kwargs.setdefault("follow_redirects", False)
        return getattr(self._client, method)(*args, **kwargs)

    def get(self, *args, **kwargs):
        return self._call("get", *args, **kwargs)

    def post(self, *args, **kwargs):
        return self._call("post", *args, **kwargs)

    def put(self, *args, **kwargs):
        return self._call("put", *args, **kwargs)

    def delete(self, *args, **kwargs):
        return self._call("delete", *args, **kwargs)

    def request(self, *args, **kwargs):
        return self._call("request", *args, **kwargs)

    def __enter__(self):
        self._client.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._client.__exit__(exc_type, exc, tb)


REPO_ROOT = Path(__file__).resolve().parent.parent
_HAS = all(importlib.util.find_spec(m) is not None
           for m in ("fastapi", "httpx", "dotenv", "itsdangerous"))

if _HAS:
    from tests._helpers import load_module
    home = load_module("family_routes_home", "family_monitor/routes/home.py")
    chat = load_module("family_routes_chat", "family_monitor/routes/chat.py")
    ai = load_module("family_routes_ai_config", "family_monitor/routes/ai_config.py")
else:
    home = chat = ai = None


class FakeClient:
    """替代 elderly_client 的假对象，记录调用并返回可控数据。"""

    def __init__(self):
        self.bound = None
        self.calls = []

    async def get_server_status(self):
        return {"online": True}

    async def get_device_info(self):
        return {"device_id": "d1", "connected": True, "status": "online"}

    async def get_dashboard_data(self):
        return {"stats": {"total": 1}}

    async def get_reminders(self):
        return [{"id": 1}]

    async def get_medication_records(self):
        return [{"id": 1}]

    async def get_device_plans(self):
        return [{"plan_id": 1}]

    async def get_chat_history(self, limit=50):
        self.calls.append(("get_chat_history", limit))
        return [{"text": "hi"}]

    async def check_device(self, device_id):
        self.calls.append(("check_device", device_id))
        return {"success": True, "data": {"exists": True}}

    async def register_device(self, device_id, device_name=""):
        self.calls.append(("register_device", device_id, device_name))
        return {"success": True, "data": {"device_token": "tok-xyz"}}

    async def set_medication_plan(self, **kw):
        self.calls.append(("set_medication_plan", kw))
        return {"success": True}

    async def update_medication_plan(self, plan_id, **kw):
        self.calls.append(("update_medication_plan", plan_id, kw))
        return {"success": True}

    async def delete_medication_plan(self, plan_id):
        self.calls.append(("delete_medication_plan", plan_id))
        return {"success": True}

    def get_bound_device(self):
        self.calls.append(("get_bound_device",))
        return self.bound

    def save_bound_device(self, device_id, device_name, device_token):
        self.bound = {"device_id": device_id, "device_name": device_name,
                      "device_token": device_token}

    def clear_bound_device(self):
        self.bound = None


def _login_true(request):
    return True


def _login_false(request):
    return False


class FakeTemplates:
    """替代 Jinja2Templates，避免页面路由测试依赖具体模板数据结构。

    仅记录被渲染的模板名并返回 200，从而覆盖路由中“取数→渲染”的完整分支。
    """

    def TemplateResponse(self, name, context):
        return Response(content=f"<html data-tpl=\"{name}\"></html>",
                        media_type="text/html")


@unittest.skipIf(home is None, "fastapi/httpx/dotenv/itsdangerous not installed")
class TestHomeRoutes(unittest.TestCase):
    def setUp(self):
        self.fake = FakeClient()
        home.elderly_client = self.fake
        home.require_login = _login_true
        home.login_redirect = lambda: RedirectResponse(url="/login", status_code=302)
        home.unauthorized_json = lambda: JSONResponse(content={"success": False}, status_code=401)
        home.templates = FakeTemplates()
        app = FastAPI()
        app.include_router(home.router)
        self.client = _NoRedirectClient(app)

    def _page(self, path):
        return self.client.get(path)

    def test_index(self):
        resp = self._page("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('data-tpl="index.html"', resp.text)

    def test_reminders(self):
        resp = self._page("/reminders")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('data-tpl="reminders.html"', resp.text)

    def test_records(self):
        resp = self._page("/records")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('data-tpl="records.html"', resp.text)

    def test_dashboard(self):
        resp = self._page("/dashboard")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('data-tpl="dashboard.html"', resp.text)

    def test_settings(self):
        resp = self._page("/settings")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('data-tpl="settings.html"', resp.text)

    def test_medication_settings(self):
        resp = self._page("/medication_settings")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('data-tpl="medication_settings.html"', resp.text)

    def test_get_status(self):
        resp = self.client.get("/status")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["connected"])

    def test_unbind_device(self):
        self.fake.bound = {"device_id": "d1"}
        resp = self.client.post("/settings/unbind_device")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        self.assertIsNone(self.fake.bound)

    def test_bind_device_success(self):
        resp = self.client.post(
            "/settings/bind_device",
            data={"device_id": "d1", "device_name": "老人机"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        self.assertEqual(self.fake.bound["device_token"], "tok-xyz")

    def test_bind_device_not_registered(self):
        async def fake_check(device_id):
            return {"success": True, "data": {"exists": False}}
        home.elderly_client.check_device = fake_check
        resp = self.client.post(
            "/settings/bind_device", data={"device_id": "x"}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("未注册", resp.json()["message"])

    def test_bind_device_check_failure(self):
        async def fake_check(device_id):
            return {"success": False, "error": "不可达"}
        home.elderly_client.check_device = fake_check
        resp = self.client.post(
            "/settings/bind_device", data={"device_id": "x"}
        )
        self.assertEqual(resp.status_code, 400)

    def test_bind_device_register_failure(self):
        async def fake_register(device_id, device_name=""):
            return {"success": False, "error": "绑定失败"}
        home.elderly_client.register_device = fake_register
        resp = self.client.post(
            "/settings/bind_device", data={"device_id": "d1"}
        )
        self.assertEqual(resp.status_code, 400)

    def test_bind_device_not_logged_in(self):
        home.require_login = _login_false
        resp = self.client.post(
            "/settings/bind_device", data={"device_id": "d1"}
        )
        self.assertEqual(resp.status_code, 401)

    def test_add_medication_plan_success(self):
        resp = self.client.post(
            "/medication_settings/add",
            json={"drug_name": "阿司匹林", "dosage": "1片",
                  "schedule_times": ["08:00"]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_add_medication_plan_bad_json(self):
        resp = self.client.post(
            "/medication_settings/add",
            content=b"not-json",
            headers={"content-type": "application/json"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_add_medication_plan_validation_error(self):
        resp = self.client.post(
            "/medication_settings/add", json={"drug_name": ""}
        )
        self.assertEqual(resp.status_code, 400)

    def test_add_medication_plan_server_fail(self):
        async def fake_set(**kw):
            return {"success": False, "error": "服务端错误"}
        home.elderly_client.set_medication_plan = fake_set
        resp = self.client.post(
            "/medication_settings/add",
            json={"drug_name": "阿司匹林", "dosage": "1片",
                  "schedule_times": ["08:00"]},
        )
        self.assertEqual(resp.status_code, 400)

    def test_add_medication_plan_not_logged_in(self):
        home.require_login = _login_false
        resp = self.client.post(
            "/medication_settings/add", json={"drug_name": "x", "dosage": "1"}
        )
        self.assertEqual(resp.status_code, 401)

    def test_update_medication_plan_success(self):
        resp = self.client.post(
            "/medication_settings/update/5",
            json={"drug_name": "布洛芬", "dosage": "2片",
                  "schedule_times": ["09:00"]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_update_medication_plan_validation_error(self):
        resp = self.client.post(
            "/medication_settings/update/5", json={"drug_name": ""}
        )
        self.assertEqual(resp.status_code, 400)

    def test_update_medication_plan_server_fail(self):
        async def fake_update(plan_id, **kw):
            return {"success": False, "error": "无此计划"}
        home.elderly_client.update_medication_plan = fake_update
        resp = self.client.post(
            "/medication_settings/update/5",
            json={"drug_name": "布洛芬", "dosage": "2片",
                  "schedule_times": ["09:00"]},
        )
        self.assertEqual(resp.status_code, 400)

    def test_update_medication_plan_not_logged_in(self):
        home.require_login = _login_false
        resp = self.client.post("/medication_settings/update/5", json={})
        self.assertEqual(resp.status_code, 401)

    def test_delete_medication_plan_success(self):
        resp = self.client.post("/medication_settings/delete/7")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_delete_medication_plan_fail(self):
        async def fake_delete(plan_id):
            return {"success": False, "error": "删除失败"}
        home.elderly_client.delete_medication_plan = fake_delete
        resp = self.client.post("/medication_settings/delete/7")
        self.assertEqual(resp.status_code, 400)

    def test_delete_medication_plan_not_logged_in(self):
        home.require_login = _login_false
        resp = self.client.post("/medication_settings/delete/7")
        self.assertEqual(resp.status_code, 401)

    def test_pages_not_logged_in_redirect(self):
        home.require_login = _login_false
        for path in ("/", "/reminders", "/records", "/dashboard",
                     "/settings", "/medication_settings"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 302)
            self.assertTrue(resp.headers["location"].endswith("/login"))


@unittest.skipIf(chat is None, "fastapi/httpx/dotenv/itsdangerous not installed")
class TestChatRoutes(unittest.TestCase):
    def setUp(self):
        self.fake = FakeClient()
        chat.elderly_client = self.fake
        chat.require_login = _login_true
        chat.login_redirect = lambda: RedirectResponse(url="/login", status_code=302)
        chat.templates = FakeTemplates()
        app = FastAPI()

        @app.middleware("http")
        async def _inject_user(request, call_next):
            request.state.user = "family_user"
            request.state.user_id = 42
            return await call_next(request)

        app.include_router(chat.router)
        self.client = _NoRedirectClient(app)

    def test_chat_page(self):
        resp = self.client.get("/chat")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('data-tpl="chat.html"', resp.text)

    def test_chat_page_with_bound_device(self):
        self.fake.bound = {"device_id": "dev-9"}
        resp = self.client.get("/chat")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(("get_bound_device",), self.fake.calls)

    def test_chat_page_not_logged_in(self):
        chat.require_login = _login_false
        resp = self.client.get("/chat")
        self.assertEqual(resp.status_code, 302)

    def test_chat_history(self):
        resp = self.client.get("/chat/history")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        self.assertEqual(resp.json()["messages"], [{"text": "hi"}])

    def test_chat_history_limit_clamped(self):
        self.client.get("/chat/history?limit=9999")
        self.assertEqual(self.fake.calls[-1][1], 200)

    def test_chat_history_not_logged_in(self):
        chat.require_login = _login_false
        resp = self.client.get("/chat/history")
        self.assertEqual(resp.status_code, 401)


@unittest.skipIf(ai is None, "fastapi/httpx/dotenv/itsdangerous not installed")
class TestAiConfigRoutes(unittest.TestCase):
    def setUp(self):
        self.fake = FakeClient()
        ai.elderly_client = self.fake
        ai.require_login = _login_true
        ai.unauthorized_json = lambda: JSONResponse(content={"success": False}, status_code=401)
        self.api_calls = []
        self.api_result = (200, {})

        async def fake_api_request(method, path, *, token="", params=None, json_body=None):
            self.api_calls.append((method, path, token, params, json_body))
            return self.api_result

        ai.user_api_request = fake_api_request
        app = FastAPI()
        app.include_router(ai.router)
        self.client = _NoRedirectClient(app)

    def test_providers(self):
        self.api_result = (200, [{"id": "openai"}])
        resp = self.client.get("/settings/ai-providers")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_providers_fail(self):
        self.api_result = (500, {"detail": "err"})
        resp = self.client.get("/settings/ai-providers")
        self.assertEqual(resp.status_code, 500)
        self.assertFalse(resp.json()["success"])

    def test_get_ai_config(self):
        self.api_result = (200, {"provider": "openai"})
        resp = self.client.get("/settings/ai-config")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_get_ai_config_with_device(self):
        self.fake.bound = {"device_id": "dev-1"}
        self.api_result = (200, {"provider": "openai"})
        resp = self.client.get("/settings/ai-config")
        self.assertEqual(resp.status_code, 200)
        # 应把 device_id 作为查询参数下发
        _, _, _, params, _ = self.api_calls[-1]
        self.assertEqual(params, {"device_id": "dev-1"})

    def test_get_ai_config_fail(self):
        self.api_result = (404, {"detail": "未找到"})
        resp = self.client.get("/settings/ai-config")
        self.assertEqual(resp.status_code, 404)

    def test_save_ai_config_success(self):
        self.api_result = (200, {"provider": "openai"})
        resp = self.client.post("/settings/ai-config",
                                json={"provider": "openai", "api_key": "sk-xxx"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        # api_key 不应回传
        self.assertNotIn("api_key", resp.json())

    def test_save_ai_config_missing_provider(self):
        resp = self.client.post("/settings/ai-config", json={"provider": ""})
        self.assertEqual(resp.status_code, 400)

    def test_save_ai_config_bad_json(self):
        resp = self.client.post("/settings/ai-config", content=b"bad",
                                headers={"content-type": "application/json"})
        self.assertEqual(resp.status_code, 400)

    def test_save_ai_config_fail(self):
        self.api_result = (400, {"detail": "参数错误"})
        resp = self.client.post("/settings/ai-config",
                                json={"provider": "openai"})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["success"])

    def test_not_logged_in(self):
        ai.require_login = _login_false
        for path in ("/settings/ai-providers", "/settings/ai-config"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 401)
        resp = self.client.post("/settings/ai-config", json={"provider": "x"})
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
