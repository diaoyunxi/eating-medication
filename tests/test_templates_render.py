# -*- coding: utf-8 -*-
"""阶段C step4 模板抽取后的渲染冒烟测试。

用应用自身的 Jinja2Templates 环境渲染每个模板（含 base.html 继承链），
确保：
  1. 模板语法正确、extends/block 结构合法；
  2. 不存在未渲染的 Jinja 占位符（{{ 或 {% 残留在输出中）；
  3. 应用页确实渲染出导航栏（navbar-brand），认证页渲染出登录表单。
不依赖浏览器，纯服务端渲染校验。
"""
import os
import sys
import types

import pytest

from tests._helpers import load_module

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(REPO_ROOT, "family_monitor", "templates")

APP_PAGES = [
    "dashboard.html",
    "index.html",
    "medication_settings.html",
    "chat.html",
    "records.html",
    "reminders.html",
    "settings.html",
]

AUTH_PAGES = ["login.html", "register.html"]


def _fake_request(path):
    req = types.SimpleNamespace()
    req.url = types.SimpleNamespace(path=path)
    req.state = types.SimpleNamespace(user="smoke_user")
    return req


# 真实路由会传入的上下文变量；此处给安全默认值，确保 |tojson 等渲染不抛错。
# 仅用于校验模板语法与继承链，不代表业务逻辑正确性。
class _Node(dict):
    """宽容节点：任意属性/索引访问均返回自身（可被 json 序列化为 {}）。"""

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _Node()

    def __missing__(self, key):
        return _Node()

    # 支持模板中的比较运算（如 plan.remaining_quantity <= plan.low_stock_threshold）
    def __le__(self, other):
        return False

    def __lt__(self, other):
        return False

    def __gt__(self, other):
        return False

    def __ge__(self, other):
        return False

    def __eq__(self, other):
        return False

    def __ne__(self, other):
        return True


_DEFAULT_CTX = {
    "dashboard": _Node(),
    "reminders": [_Node()],
    "records": [_Node()],
    "status": _Node(),
    "device_info": _Node(),
    "bound_device": _Node(),
    "current_user": _Node(),
    "current_user_id": 0,
    "elderly_id": "",
    "server_url": "",
    "oauth_mode": False,
    "oauth_provider": "",
    "oauth_provider_name": "",
    "prefill_username": "",
    "prefill_name": "",
    "bind_email": "",
}


@pytest.fixture(scope="module")
def env():
    home = load_module("family_home_smoke", "family_monitor/routes/home.py")
    return home.templates.env


def _render(env, name, path):
    tpl = env.get_template(name)
    ctx = dict(_DEFAULT_CTX)
    ctx["request"] = _fake_request(path)
    ctx["app_name"] = "冒烟测试"
    return tpl.render(**ctx)


def test_base_html_exists():
    assert os.path.isfile(os.path.join(TEMPLATES_DIR, "base.html"))


@pytest.mark.parametrize("name", APP_PAGES)
def test_app_page_renders(env, name):
    html = _render(env, name, "/" + name.replace(".html", ""))
    # 无未渲染占位符
    assert "{{" not in html, f"{name} 输出残留 '{{'"
    assert "{%" not in html, f"{name} 输出残留 '{{%'"
    # 继承链生效：导航栏由 base.html 提供
    assert "navbar-brand" in html, f"{name} 未渲染导航栏（base.html 继承失败）"
    # 活动导航基于 request.url.path 计算（不应再出现硬编码 active 在原始位置，
    # 至少保证渲染不报错且含 nav-link）
    assert "nav-link" in html


@pytest.mark.parametrize("name", AUTH_PAGES)
def test_auth_page_renders(env, name):
    html = _render(env, name, "/" + name.replace(".html", ""))
    assert "{{" not in html, f"{name} 输出残留 '{{'"
    assert "{%" not in html, f"{name} 输出残留 '{{%'"
    # 认证页应含登录/注册表单，且无应用导航栏（nav 被显式关闭）
    assert "auth-form" in html, f"{name} 未渲染认证表单"
    assert "navbar-brand" not in html, f"{name} 不应渲染应用导航栏"


def test_all_templates_present():
    expected = set(APP_PAGES) | set(AUTH_PAGES) | {"base.html"}
    actual = set(os.listdir(TEMPLATES_DIR))
    assert expected.issubset(actual)
