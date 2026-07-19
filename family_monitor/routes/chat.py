# -*- coding: utf-8 -*-
"""
消息路由
S9 修复：增加 /chat/history BFF 代理接口，从服务端获取聊天历史
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from core import config, elderly_client

router = APIRouter()
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))
templates.env.cache = {}
# 注入路径前缀变量，供模板链接加前缀
templates.env.globals["prefix"] = config.PATH_PREFIX


def _require_login(request: Request) -> bool:
    """显式校验登录状态，防御中间件逻辑变更导致的越权"""
    return bool(getattr(request.state, 'user', None))


def _login_redirect():
    """未登录时重定向到登录页（显式拼接 PATH_PREFIX）"""
    prefix = config.PATH_PREFIX.rstrip("/")
    login_url = f"{prefix}/login" if prefix else "/login"
    return RedirectResponse(url=login_url, status_code=302)


@router.get("/chat")
async def chat(request: Request):
    """消息页面
    传入 current_user 和 elderly_id 供模板使用"""
    if not _require_login(request):
        return _login_redirect()
    user = getattr(request.state, 'user', None) or ''
    elderly_id = ''
    # 从已绑定的设备获取 elderly_id
    if user:
        bound = elderly_client.get_bound_device()
        if bound:
            elderly_id = bound.get('device_id', '')

    # 注入当前登录用户的数字 ID（family_monitor 用户系统基于 username，
    # 暂无数字 ID，此处为 None；前端用于与服务端 sender_id 比较以判定消息方向）
    current_user_id = None

    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "current_user": user,
            "current_user_id": current_user_id,
            "elderly_id": elderly_id,
            "server_url": config.ELDERLY_SERVER_URL,
            "prefix": config.PATH_PREFIX,
        }
    )


@router.get("/chat/history")
async def chat_history(request: Request, limit: int = 50):
    """S9 修复：BFF 代理聊天历史接口"""
    if not _require_login(request):
        return JSONResponse(content={"success": False, "message": "请先登录"}, status_code=401)
    # 边界校验：限制 1~200，防止过大查询拖慢服务
    limit = max(1, min(limit, 200))
    messages = await elderly_client.get_chat_history(limit=limit)
    return JSONResponse(content={"success": True, "messages": messages})
