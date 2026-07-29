# -*- coding: utf-8 -*-
"""家属端 Web 路由共享工具（消除跨路由重复样板）。

集中家属端各路由文件（home / chat / ai_config）此前各自重复定义的：
- Jinja2Templates 装配：禁用缓存 + 注入 PATH_PREFIX 与 current_year 全局变量
- 鉴权三件套：登录态校验 require_login / 未登录重定向 login_redirect / 未授权 JSON unauthorized_json
- 以当前登录用户 JWT 调用服务端 /api/v1 的共享客户端与请求封装 user_api_request

统一后各路由文件只需 ``from .web_helpers import ...``，职责更清晰、行为一致。
"""
import logging
from datetime import datetime

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from core import config
from common.server_client import BaseServerClient

logger = logging.getLogger(__name__)

# 全路由共享同一 Jinja 环境，避免每文件重复装配
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))
# 禁用 Jinja2 缓存以避免网络驱动器上的缓存问题
templates.env.cache = {}
# 注入路径前缀变量，供模板链接加前缀
templates.env.globals["prefix"] = config.PATH_PREFIX
# 注入当前年份变量，供页脚版权信息使用（替换原硬编码年份）
templates.env.globals["current_year"] = datetime.now().year

# 以当前登录用户 JWT 调用服务端 /api/v1 的共享客户端
# （每次请求内部使用独立 httpx.AsyncClient，避免连接耗尽）
_user_api_client = BaseServerClient(
    base_url=f"{config.ELDERLY_SERVER_URL.rstrip('/')}/api/v1",
    timeout=15.0,
)


def require_login(request: Request) -> bool:
    """显式校验登录状态，防御中间件逻辑变更导致的越权。"""
    return bool(getattr(request.state, "user", None))


def login_redirect():
    """未登录时重定向到登录页（显式拼接 PATH_PREFIX）。"""
    prefix = config.PATH_PREFIX.rstrip("/")
    login_url = f"{prefix}/login" if prefix else "/login"
    return RedirectResponse(url=login_url, status_code=302)


def unauthorized_json():
    """API 路由未登录时返回 401 JSON。"""
    return JSONResponse(content={"success": False, "message": "请先登录"}, status_code=401)


async def user_api_request(method: str, path: str, *, token: str,
                           params=None, json_body=None):
    """以用户 JWT 调用服务端 /api/v1 接口，返回 (status_code, json)。

    :param token: 当前登录用户的 access_token（Bearer 凭证）
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = await _user_api_client._execute(
        method, path, params=params, json_body=json_body, headers=headers,
    )
    try:
        data = resp.json()
    except Exception:
        data = {"detail": resp.text}
    return resp.status_code, data
